"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  🚀  AI SMC/ICT Pro Sniper — V.13 PRODUCTION                                ║
║                                                                              ║
║  CHANGES vs V.11 (all Phase-1 through Phase-4 fixes applied)                ║
║  ─────────────────────────────────────────────────────────────────────────  ║
║  [V13-P0-A]  V.12 Parameters ported to live engine (London=68, ADR hard     ║
║              block, SL_ATR_MULT=1.2, FVG mid-entry, tighter trails).        ║
║                                                                              ║
║  [V13-P0-B]  SQLite concurrency fixed: thread-local connections replace      ║
║              the shared singleton.  Each thread owns its own connection      ║
║              opened in WAL mode.  The writer queue serialises all writes     ║
║              through a single background thread eliminating race conditions. ║
║                                                                              ║
║  [V13-P0-C]  ML gate decoupled from score: score_norm removed from feature  ║
║              vector.  Features are now 12 stationary, independent signals.  ║
║              Dynamic z-score normalisation with 200-trade rolling window     ║
║              replaces hardcoded StandardScaler dependency.  Leakage-free.   ║
║                                                                              ║
║  [V13-P1-A]  get_m15_structure() rebuilt: uses confirmed swing BOS over     ║
║              proper HTF_SWING_PERIOD window, not single-bar comparison.     ║
║                                                                              ║
║  [V13-P1-B]  find_order_block() adds OBResult.bar_age + OBResult.mitigated  ║
║              fields.  Mitigated OBs score 0 instead of SCORE_OB_BONUS.      ║
║                                                                              ║
║  [V13-P1-C]  build_liquidity_map_np() adds gap_crossed sweep detection:     ║
║              prev_close vs current_open covers gap-through-level sweeps      ║
║              that were invisible to the high/low comparator.                ║
║                                                                              ║
║  [V13-P2-A]  Operator heartbeat log emitted every HEARTBEAT_SEC (300 s)    ║
║              showing equity, DD%, session, HTF, ADR, open positions,        ║
║              today P&L, and bot mode (NORMAL / ELEVATED / NEAR HALT /       ║
║              PAUSED / HALTED).                                               ║
║                                                                              ║
║  [V13-P2-B]  Win-probability context logged with 60-trade rolling average   ║
║              so operator sees "WinProb:0.71 [avg:0.68]" not a raw float.   ║
║                                                                              ║
║  [V13-P2-C]  Three-tier DD communication protocol:                           ║
║              Yellow (>3%) → reduce risk tier;                               ║
║              Orange (>5%) → pause new entries + operator alert;             ║
║              Red (>MAX_TOTAL_DD_PCT) → circuit breaker.                     ║
║                                                                              ║
║  [V13-P2-D]  Emergency kill-switch: presence of KILL.flag file OR           ║
║              SIGTERM/SIGINT triggers graceful_shutdown() which cancels       ║
║              all pending limit orders then closes all positions at market.  ║
║                                                                              ║
║  [V13-P2-E]  PAUSE.flag mechanism: new entries suspended while file exists; ║
║              PositionManager continues managing open trades uninterrupted.  ║
║                                                                              ║
║  PRESERVED FROM V.11                                                         ║
║  ─────────────────────────────────────────────────────────────────────────  ║
║  [OPT-1]  NumPy ATR / Swings / Liq hot paths                                ║
║  [FIX-1]  _send_retry with price refresh on REQUOTE                         ║
║  [FIX-2]  dynamic_deviation per trade                                        ║
║  [FIX-3]  dual-key position tracking (ticket + hash)                        ║
║  [FIX-4]  live schema migration (idempotent)                                ║
║  [FIX-5]  close_partial with live ATR deviation                             ║
║  [FIX-6]  non-blocking 2 s tick poll + intrabar trigger                    ║
║  [FIX-7]  0.2 s PositionManager + batched DB reads                         ║
║  [FIX-8]  ML feature vector persisted to setup_log                         ║
║  [EDGE-1] lot zero-floor                                                    ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# ─────────────────────────────────────────────────────────────────────────────
#  IMPORTS
# ─────────────────────────────────────────────────────────────────────────────
import MetaTrader5 as mt5
import numpy as np
import pandas as pd
import sqlite3
import json
import math
import os
import signal
import time
import hashlib
import logging
import threading
import warnings
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, time as dtime
from decimal import Decimal, ROUND_DOWN
from typing import Optional, List, Tuple, Dict, Deque

import pytz

warnings.filterwarnings("ignore", category=RuntimeWarning)

try:
    from sklearn.preprocessing import StandardScaler
    import joblib
    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False


# ══════════════════════════════════════════════════════════════════════════════
# ⚙️  CONFIGURATION  — single source of truth for both engine and risk layer
# ══════════════════════════════════════════════════════════════════════════════

SYMBOL          = "XAUUSDm"
MAGIC_NUMBER    = 99999
RR_RATIO        = 2.5
MAX_DAILY_LOSS_PCT  = 4.0
MAX_TOTAL_DD_PCT    = 8.0

# [V13-P0-A] V.12 expiry (3 H → 36 M5 bars)
EXPIRATION_CANDLES  = 36          # was 6 in V.11 live (= 30 min); V.12 correct = 36

# Spread guards
HARD_SPREAD_BLOCK   = 100.0
MAX_SPREAD_POINTS   = 50.0
SPREAD_LOT_PENALTY  = 0.3
SPREAD_SL_PADDING   = True

MOMENTUM_BODY_ATR   = 1.2
BREAKEVEN_RR        = 1.0

# [V13-P0-A] V.12 trail parameters
TRAIL_AFTER_RR      = 1.5         # was 2.0 in V.11 live
TRAIL_ATR_MULT      = 0.8         # was 1.2 in V.11 live
TRAIL_MIN_MOVE_ATR  = 0.3

# [V13-P0-A] ADR — V.12 hard block at 80%
ADR_EXHAUSTED_PCT   = 0.80        # was 0.85 in V.11 live
ADR_HARD_BLOCK      = True        # if True: skip entry; False: score penalty only

# [V13-P0-A] SL widened to 1.2×ATR (V.12 fix)
SL_ATR_MULT         = 1.2         # was effectively 0.5 in V.11 live

# [V13-P0-A] FVG mid-zone entry (V.12 fix)
FVG_ENTRY_MID       = True        # enter at 50% of FVG instead of edge

SWING_PERIOD        = 5
SWING_CONFIRM_BARS  = 2
SETUP_COOLDOWN_SEC  = 180

PARTIAL_TP_RR       = 1.0
PARTIAL_TP_PCT      = 0.50

# [V13-P0-A] Max concurrent positions cap from V.12
MAX_CONCURRENT_TRADES = 2

INTRABAR_ENABLED    = True

# FVG
FVG_BUFFER_RATIO    = 0.6
FVG_MOMENTUM_RATIO  = 0.25
FVG_MITIGATED_PCT   = 0.5
FVG_MEMORY_BARS: Dict[str, int] = {
    "PRE_LONDON":    24,
    "LONDON":        36,
    "NY_OPEN_EARLY": 30,
    "NEW_YORK":      36,
    "DEFAULT":       30,
}

# Liquidity
LIQ_SWING_PERIOD    = 10
LIQ_EQUAL_TOLERANCE = 0.0003
LIQ_MIN_CLUSTER     = 2

# HTF
HTF_SWING_PERIOD    = 8
HTF_SWING_CONFIRM   = 2

# M1 bonus
MTF_M1_BODY_ATR     = 0.3
SCORE_M1_CONFIRM    = 5

# ── Scoring constants ─────────────────────────────────────────────────────────
SCORE_BASE          = 55
SCORE_SWEEP_AND_FVG = 20
SCORE_HTF_ALIGN     = 12
SCORE_HTF_AGAINST   = -8
SCORE_M15_BOS       = 8
SCORE_STRONG_CANDLE = 10
SCORE_OB_BONUS      = 10
SCORE_OB_OVERLAP    = 5
SCORE_BOS_M5        = 7
SCORE_FVG_FRESH     = 8
SCORE_FVG_STRENGTH  = 4
SCORE_LIQ_SWEPT     = 10
SCORE_LIQ_TARGET    = 10
SCORE_ADR_WARN      = -8
SCORE_SPREAD_WARN   = -4

# [V13-P0-A] V.12 score thresholds
SCORE_THRESHOLD: Dict[str, int] = {
    "LONDON":        68,   # was 55 — V.12 critical fix
    "NEW_YORK":      58,   # was 55
    "NY_OPEN_EARLY": 62,   # was 58
    "PRE_LONDON":    65,   # was 62
    "DEFAULT":       65,   # was 60
}

# [V13-P0-A] HTF-NEUTRAL requires very high score (V.12 FIX-D)
HTF_NEUTRAL_MIN_SCORE   = 85

SCORE_PENALTY_HTF_NEUTRAL = 3
SCORE_PENALTY_HIGH_ADR    = 2

# ML gate
ML_WIN_PROB_THRESHOLD   = 0.65
ML_ROLLING_WINDOW       = 60    # trades to track for rolling win-prob average

# [V13-P0-A] V.12 risk tiers
LOT_MIN  = 0.01
LOT_MAX  = 1.00
RISK_TIERS = [
    (85, 1.00),    # was (90, 1.00) in V.11
    (78, 0.75),    # was (80, 0.75) in V.11
    (70, 0.50),    # unchanged
    (65, 0.25),    # was (60, 0.25) in V.11
    (0,  0.05),    # was (0,  0.10) in V.11 — halved floor risk
]

# DD tiers [V13-P2-C]
DD_YELLOW_PCT   = 3.0   # reduce risk tier 1 step
DD_ORANGE_PCT   = 5.0   # suspend new entries, log operator alert

CIRCUIT_BREAKER_PCT = 3.0

# Killzone filter (Bangkok time)
KILLZONE_ENABLED = True
KILLZONES = [
    (14,  0, 16, 30, "London Open"),
    (19, 45, 22,  0, "NY Open"),
]

SESSIONS = [
    (12,  0, 14,  0, "PRE_LONDON"),
    (14,  0, 18,  0, "LONDON"),
    (18, 30, 19, 15, "NY_OPEN_EARLY"),
    (19, 45, 23, 59, "NEW_YORK"),
]
NEWS_BLOCKS = [(19, 15, 19, 45)]

# Cache TTL (seconds)
CACHE_TTL_LTF = 5
CACHE_TTL_HTF = 60
CACHE_TTL_D1  = 300

# Polling intervals
POSITION_POLL_SEC       = 0.2
TICK_POLL_SEC           = 2.0
INTRABAR_TICK_MOVE_ATR  = 0.30
HEARTBEAT_SEC           = 300   # [V13-P2-A] operator status log every 5 min

# File-based signals [V13-P2-D/E]
KILL_FLAG_PATH  = "KILL.flag"
PAUSE_FLAG_PATH = "PAUSE.flag"

DB_PATH  = "smc_state.db"
LOG_PATH = "smc_bot.log"
bkk_tz   = pytz.timezone("Asia/Bangkok")


# ══════════════════════════════════════════════════════════════════════════════
# 📋  LOGGING
# ══════════════════════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# 💾  PERSISTENCE LAYER  — [V13-P0-B] thread-local connections + writer queue
# ══════════════════════════════════════════════════════════════════════════════

# Each thread gets its own read connection; all writes go through a single
# serialised writer thread.  This eliminates the "database is locked" race
# that the old shared-singleton approach could hit under concurrent 0.2 s PM
# reads and main-thread writes.

_tls = threading.local()          # thread-local read connections
_write_queue: "queue.Queue" = None  # type: ignore[assignment]  # filled in init_db()

import queue as _queue_module     # noqa: E402  (imported after stdlib block)


def _get_read_conn() -> sqlite3.Connection:
    """Return this thread's dedicated read connection, opening it if needed."""
    if not hasattr(_tls, "conn") or _tls.conn is None:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-4000")
        conn.execute("PRAGMA temp_store=MEMORY")
        _tls.conn = conn
    return _tls.conn


def _writer_loop(q: _queue_module.Queue) -> None:
    """
    [V13-P0-B] Single-threaded writer: dequeues (sql, params, event) tuples
    and executes them on a dedicated write connection.  The optional Event is
    set after commit so callers that need synchronous write confirmation can
    wait on it.
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    while True:
        item = q.get()
        if item is None:               # sentinel — shut down
            conn.close()
            break
        sql, params, done_event = item
        try:
            conn.execute(sql, params)
            conn.commit()
        except Exception as exc:
            log.warning(f"DB writer error: {exc} | SQL: {sql[:80]}")
        finally:
            if done_event is not None:
                done_event.set()
        q.task_done()


_writer_thread: Optional[threading.Thread] = None
_write_q: Optional[_queue_module.Queue] = None


def _db_exec(sql: str, params: tuple = (), wait: bool = False) -> None:
    """Enqueue a write operation.  If wait=True, block until committed."""
    global _write_q
    if _write_q is None:
        raise RuntimeError("DB writer not initialised — call init_db() first")
    ev = threading.Event() if wait else None
    _write_q.put((sql, params, ev))
    if ev is not None:
        ev.wait(timeout=5.0)


def _db_query(sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
    """Thread-safe read on this thread's local connection."""
    try:
        return _get_read_conn().execute(sql, params).fetchone()
    except Exception as exc:
        log.warning(f"DB read error: {exc}")
        return None


def _db_query_all(sql: str, params: tuple = ()) -> List[sqlite3.Row]:
    """Thread-safe multi-row read."""
    try:
        return _get_read_conn().execute(sql, params).fetchall()
    except Exception as exc:
        log.warning(f"DB read_all error: {exc}")
        return []


def init_db() -> None:
    """
    Create tables, apply live schema migrations, start writer thread.
    Idempotent and re-entrant.
    """
    global _writer_thread, _write_q

    # Start writer thread once
    if _write_q is None:
        _write_q = _queue_module.Queue()
        _writer_thread = threading.Thread(
            target=_writer_loop, args=(_write_q,),
            name="DBWriter", daemon=True,
        )
        _writer_thread.start()
        log.info("💾 DB writer thread started")

    # Create tables via the writer (synchronous so tables exist before we return)
    schema = """
    CREATE TABLE IF NOT EXISTS setup_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        ts         REAL,
        signal     TEXT,
        score      INTEGER,
        entry      REAL,
        sl         REAL,
        tp         REAL,
        setup_hash TEXT,
        session    TEXT,
        features   TEXT,
        win_prob   REAL
    );
    CREATE TABLE IF NOT EXISTS cooldown (
        setup_hash TEXT PRIMARY KEY, expires_at REAL
    );
    CREATE TABLE IF NOT EXISTS trail_state (
        ticket       INTEGER PRIMARY KEY,
        setup_hash   TEXT,
        last_sl      REAL,
        updated_at   REAL,
        partial_done INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS bot_state (
        key TEXT PRIMARY KEY, value TEXT
    );
    CREATE TABLE IF NOT EXISTS win_prob_history (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        ts      REAL,
        prob    REAL,
        outcome INTEGER DEFAULT -1
    );
    CREATE INDEX IF NOT EXISTS idx_trail_hash   ON trail_state (setup_hash);
    CREATE INDEX IF NOT EXISTS idx_setup_log_ts ON setup_log (ts);
    CREATE INDEX IF NOT EXISTS idx_wph_ts       ON win_prob_history (ts);
    """
    # Execute each statement individually through the writer
    for stmt in [s.strip() for s in schema.split(";") if s.strip()]:
        _db_exec(stmt, wait=True)

    # Live migrations
    read_conn = _get_read_conn()
    trail_cols = {row[1] for row in read_conn.execute(
        "PRAGMA table_info(trail_state)"
    ).fetchall()}
    if "setup_hash" not in trail_cols:
        _db_exec("ALTER TABLE trail_state ADD COLUMN setup_hash TEXT DEFAULT ''", wait=True)
        log.info("DB migration: trail_state.setup_hash added")

    setup_cols = {row[1] for row in read_conn.execute(
        "PRAGMA table_info(setup_log)"
    ).fetchall()}
    for col, defn in [("features", "TEXT DEFAULT NULL"), ("win_prob", "REAL DEFAULT 0")]:
        if col not in setup_cols:
            _db_exec(f"ALTER TABLE setup_log ADD COLUMN {col} {defn}", wait=True)
            log.info(f"DB migration: setup_log.{col} added")

    log.info("✅ Database initialised / migrated (V13 schema)")


def close_db() -> None:
    """Signal writer thread to exit and close thread-local connections."""
    global _write_q
    if _write_q is not None:
        _write_q.put(None)   # sentinel
        _write_q = None
    if hasattr(_tls, "conn") and _tls.conn is not None:
        try:
            _tls.conn.close()
        except Exception:
            pass
        _tls.conn = None


# ── Cooldown helpers ──────────────────────────────────────────────────────────
def is_on_cooldown(h: str) -> bool:
    row = _db_query("SELECT expires_at FROM cooldown WHERE setup_hash=?", (h,))
    return bool(row and row["expires_at"] > time.time())


def set_cooldown(h: str) -> None:
    _db_exec(
        "INSERT OR REPLACE INTO cooldown VALUES(?,?)",
        (h, time.time() + SETUP_COOLDOWN_SEC),
    )


def cleanup_cooldowns() -> None:
    _db_exec("DELETE FROM cooldown WHERE expires_at<=?", (time.time(),))


# ── Setup log ─────────────────────────────────────────────────────────────────
def db_log_setup(
    signal: str,
    score: int,
    entry: float,
    sl: float,
    tp: float,
    h: str,
    session: str = "",
    features: Optional[np.ndarray] = None,
    win_prob: float = 0.0,
) -> None:
    features_json: Optional[str] = None
    if features is not None:
        try:
            features_json = json.dumps(
                [round(float(v), 8) for v in features], separators=(",", ":")
            )
        except Exception as exc:
            log.warning(f"db_log_setup: feature serialise error: {exc}")
    _db_exec(
        "INSERT INTO setup_log"
        "(ts,signal,score,entry,sl,tp,setup_hash,session,features,win_prob)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (time.time(), signal, score, entry, sl, tp, h, session, features_json, win_prob),
    )
    # Track win_prob history for rolling average
    _db_exec(
        "INSERT INTO win_prob_history(ts,prob) VALUES(?,?)",
        (time.time(), win_prob),
    )


# ── Trail state ───────────────────────────────────────────────────────────────
def get_trail_state_by_ticket(ticket: int) -> Optional[sqlite3.Row]:
    return _db_query(
        "SELECT setup_hash,last_sl,partial_done FROM trail_state WHERE ticket=?",
        (ticket,),
    )


def get_trail_state_by_hash(setup_hash: str) -> Optional[sqlite3.Row]:
    return _db_query(
        "SELECT ticket,last_sl,partial_done FROM trail_state WHERE setup_hash=?",
        (setup_hash,),
    )


def get_trail_state(ticket: int, setup_hash: str = "") -> Optional[sqlite3.Row]:
    row = get_trail_state_by_ticket(ticket)
    if row:
        return row
    if setup_hash:
        return get_trail_state_by_hash(setup_hash)
    return None


def save_trail_sl(ticket: int, sl: float, setup_hash: str = "",
                  partial_done: Optional[int] = None) -> None:
    existing = get_trail_state(ticket, setup_hash)
    if partial_done is None:
        partial_done = int(existing["partial_done"]) if existing else 0
    _db_exec(
        "INSERT OR REPLACE INTO trail_state VALUES(?,?,?,?,?)",
        (ticket, setup_hash or "", sl, time.time(), partial_done),
    )


def set_partial_done(ticket: int, setup_hash: str = "") -> None:
    existing = get_trail_state(ticket, setup_hash)
    last_sl  = float(existing["last_sl"]) if existing else 0.0
    _db_exec(
        "INSERT OR REPLACE INTO trail_state VALUES(?,?,?,?,?)",
        (ticket, setup_hash or "", last_sl, time.time(), 1),
    )


def cleanup_trail_state(open_tickets: set) -> None:
    if not open_tickets:
        _db_exec("DELETE FROM trail_state")
        return
    ph = ",".join("?" * len(open_tickets))
    _db_exec(
        f"DELETE FROM trail_state WHERE ticket NOT IN ({ph})",
        tuple(open_tickets),
    )


def batch_load_trail_states(tickets: List[int]) -> Dict[int, sqlite3.Row]:
    """[FIX-7] Single-query batch load for PositionManager hot path."""
    if not tickets:
        return {}
    ph   = ",".join("?" * len(tickets))
    rows = _db_query_all(
        f"SELECT ticket,setup_hash,last_sl,partial_done "
        f"FROM trail_state WHERE ticket IN ({ph})",
        tuple(tickets),
    )
    return {int(r["ticket"]): r for r in rows}


# ── Win-prob rolling average [V13-P2-B] ──────────────────────────────────────
def get_rolling_win_prob_avg(n: int = ML_ROLLING_WINDOW) -> float:
    """Return average win_prob over the last n logged trades."""
    rows = _db_query_all(
        "SELECT prob FROM win_prob_history ORDER BY ts DESC LIMIT ?", (n,)
    )
    if not rows:
        return 0.0
    return float(np.mean([r["prob"] for r in rows]))


# ── Generic bot state ─────────────────────────────────────────────────────────
def get_state(key: str, default=None):
    row = _db_query("SELECT value FROM bot_state WHERE key=?", (key,))
    return json.loads(row["value"]) if row else default


def set_state(key: str, value) -> None:
    _db_exec(
        "INSERT OR REPLACE INTO bot_state VALUES(?,?)",
        (key, json.dumps(value)),
    )


# ══════════════════════════════════════════════════════════════════════════════
# 📐  DATA CLASSES
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class HTFBiasResult:
    bias:         str             = "NEUTRAL"
    last_bos:     str             = "NONE"
    choch_signal: str             = "NONE"
    swept_high:   Optional[float] = None
    swept_low:    Optional[float] = None
    reason:       str             = ""


@dataclass
class FVGZone:
    kind:      str
    top:       float
    bot:       float
    strength:  float
    bar_index: int
    mitigated: bool = False


@dataclass
class LiquidityMap:
    buy_side:    List[float] = field(default_factory=list)
    sell_side:   List[float] = field(default_factory=list)
    swept_high:  Optional[float] = None
    swept_low:   Optional[float] = None
    gap_swept_high: Optional[float] = None  # [V13-P1-C]
    gap_swept_low:  Optional[float] = None  # [V13-P1-C]
    bsl_nearest: Optional[float] = None
    ssl_nearest: Optional[float] = None


@dataclass
class OBResult:
    found:     bool  = False
    high:      float = 0.0
    low:       float = 0.0
    score:     float = 0.0
    bar_age:   int   = 0      # [V13-P1-B] bars since OB formed
    mitigated: bool  = False  # [V13-P1-B] True if price closed through OB


@dataclass
class SetupResult:
    signal:     str              = "WAIT"
    score:      int              = 0
    entry:      float            = 0.0
    sl:         float            = 0.0
    atr:        float            = 0.0
    htf_bias:   str              = "NEUTRAL"
    m15_struct: str              = "NEUTRAL"
    adr_pct:    float            = 0.0
    threshold:  int              = 65
    reasons:    List[str]        = field(default_factory=list)
    setup_hash: str              = ""
    use_market: bool             = False
    liq_map:    Optional[LiquidityMap]  = None
    fvg_zone:   Optional[FVGZone]       = None
    candle_ts:  float            = 0.0
    htf_result: Optional[HTFBiasResult] = None
    features:   Optional[np.ndarray]    = None
    win_prob:   float            = 0.0
    spread_pts: float            = 0.0

    def summary(self) -> str:
        mode = "MKT" if self.use_market else "LMT"
        gap  = self.score - self.threshold
        conf = "🔥🔥🔥" if gap >= 20 else "🔥🔥" if gap >= 10 else "🔥"
        return (
            f"{conf} {self.signal}({mode}) "
            f"Score:{self.score}/{self.threshold} "
            f"WinProb:{self.win_prob:.2f} "
            f"| {' | '.join(self.reasons)}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 🤖  ML LAYER  [V13-P0-C] — decoupled features + dynamic z-score normaliser
# ══════════════════════════════════════════════════════════════════════════════

class RollingZScoreNormaliser:
    """
    [V13-P0-C] Online z-score normaliser using a capped deque of observations.

    This replaces the offline StandardScaler to eliminate the train/deploy
    distribution mismatch (data leakage). Features are standardised against
    the rolling mean and std of the last `window` trades, so the scaler
    adapts to the current volatility regime automatically.

    Cold-start: for the first `min_samples` trades, the raw features are
    returned unchanged so the ML gate degrades gracefully to heuristic mode.
    """

    def __init__(self, n_features: int, window: int = 200, min_samples: int = 20):
        self._n    = n_features
        self._win  = window
        self._min  = min_samples
        # One deque per feature
        self._bufs: List[Deque[float]] = [deque(maxlen=window) for _ in range(n_features)]

    def update(self, x: np.ndarray) -> None:
        """Push a raw feature observation into the rolling buffers."""
        for i, v in enumerate(x):
            if np.isfinite(v):
                self._bufs[i].append(float(v))

    def transform(self, x: np.ndarray) -> np.ndarray:
        """Standardise x using rolling stats.  Returns raw x during cold-start."""
        out = x.copy()
        ready = all(len(b) >= self._min for b in self._bufs)
        if not ready:
            return out
        for i in range(self._n):
            buf = np.array(self._bufs[i])
            mu, sigma = buf.mean(), buf.std()
            if sigma > 1e-9:
                out[i] = (out[i] - mu) / sigma
            else:
                out[i] = 0.0
        return out

    @property
    def is_warm(self) -> bool:
        return all(len(b) >= self._min for b in self._bufs)

    def check_distribution_shift(self, x: np.ndarray, z_bound: float = 3.5) -> bool:
        """Return True if any feature is beyond z_bound SD from rolling mean."""
        if not self.is_warm:
            return False
        for i in range(self._n):
            buf   = np.array(self._bufs[i])
            mu, sigma = buf.mean(), buf.std()
            if sigma > 1e-9 and abs((x[i] - mu) / sigma) > z_bound:
                return True
        return False


N_FEATURES = 12  # [V13-P0-C] expanded, score_norm removed


def extract_features(setup: SetupResult, close_price: float = 2000.0) -> np.ndarray:
    """
    [V13-P0-C] Stationary 12-feature vector (score_norm removed to break
    circular dependency).

    Feature index → name:
      0   htf_bias_enc        BULLISH=1, BEARISH=-1, NEUTRAL=0
      1   atr_norm            atr / close_price  (stationary)
      2   adr_pct             day_range / avg_daily_range
      3   fvg_strength        gap / atr (already normalised)
      4   spread_norm         spread_pts / atr  (stationary)
      5   m15_enc             BULLISH_BOS=1, BEARISH_BOS=-1, else 0
      6   has_liq_target      1 if BSL/SSL target within RR reach
      7   has_ob              1 if order block found and NOT mitigated
      8   sweep_and_fvg       1 if Sweep+FVG confluence
      9   fvg_age_norm        bar_age of FVG / 36  (recency 0=fresh, 1=stale)
     10   sweep_depth         (sweep_extreme - level) / atr  (filtered to 0 if no sweep)
     11   session_sin         sin(2π * minute_of_day / 1440)  cyclical time
    """
    htf_bias_enc = {"BULLISH": 1.0, "BEARISH": -1.0}.get(setup.htf_bias, 0.0)

    atr        = max(setup.atr, 1e-6)
    atr_norm   = atr / max(close_price, 1.0)

    fvg_strength = setup.fvg_zone.strength if setup.fvg_zone else 0.0
    fvg_age_norm = 0.0
    if setup.fvg_zone is not None:
        max_lookback = FVG_MEMORY_BARS.get("DEFAULT", 30)
        fvg_age_norm = min(1.0, setup.fvg_zone.bar_index / max(max_lookback, 1))

    spread_norm = setup.spread_pts / atr

    m15_enc = {"BULLISH_BOS": 1.0, "BEARISH_BOS": -1.0}.get(setup.m15_struct, 0.0)

    reasons_str    = " ".join(setup.reasons)
    has_ob         = 0.0
    for r in setup.reasons:
        if "OB(q:" in r:
            # Only count un-mitigated OB (mitigated ones are filtered in find_order_block)
            has_ob = 1.0
            break
    sweep_and_fvg  = 1.0 if "Sweep+FVG" in reasons_str else 0.0
    has_liq_target = 1.0 if ("BSL→" in reasons_str or "SSL→" in reasons_str) else 0.0

    # Sweep depth: how far price penetrated into liquidity before reversing
    sweep_depth = 0.0
    if setup.liq_map is not None:
        lm = setup.liq_map
        if lm.swept_low is not None and setup.signal == "BUY":
            sweep_depth = min(1.0, (lm.swept_low - (lm.ssl_nearest or lm.swept_low)) / atr)
        elif lm.swept_high is not None and setup.signal == "SELL":
            sweep_depth = min(1.0, ((lm.bsl_nearest or lm.swept_high) - lm.swept_high) / atr)

    # Cyclical time encoding
    now_bkk = datetime.now(bkk_tz)
    minute_of_day = now_bkk.hour * 60 + now_bkk.minute
    session_sin = math.sin(2.0 * math.pi * minute_of_day / 1440.0)

    return np.array([
        htf_bias_enc,
        atr_norm,
        float(setup.adr_pct),
        float(fvg_strength),
        float(spread_norm),
        m15_enc,
        float(has_liq_target),
        float(has_ob),
        float(sweep_and_fvg),
        float(fvg_age_norm),
        float(sweep_depth),
        float(session_sin),
    ], dtype=np.float64)


class MLPredictor:
    """
    [V13-P0-C] ML inference with dynamic rolling z-score normaliser.

    The normaliser adapts to the live market's volatility regime without
    requiring an offline-fitted StandardScaler, eliminating data leakage
    and distribution-shift failures.

    A real XGBoost/RF model can be loaded via load_model(); until then the
    heuristic path runs using the normalised features.
    """

    def __init__(self):
        self._model    = None
        self._norm     = RollingZScoreNormaliser(N_FEATURES)
        self._prob_buf: Deque[float] = deque(maxlen=ML_ROLLING_WINDOW)
        log.info(
            f"🧠 MLPredictor V13: {N_FEATURES}-feature stationary vector | "
            "dynamic z-score normaliser | no score_norm circular dependency"
        )

    def load_model(self, path: str) -> bool:
        try:
            import joblib as _joblib
            obj = _joblib.load(path)
            if isinstance(obj, tuple) and len(obj) == 2:
                # (external_scaler, model) — external scaler is ignored;
                # V13 uses the internal rolling normaliser instead.
                log.warning(
                    "MLPredictor: loaded (scaler, model) tuple — external scaler "
                    "is IGNORED in V13; internal rolling z-score normaliser is used."
                )
                self._model = obj[1]
            else:
                self._model = obj
            log.info(f"🧠 MLPredictor: model loaded from {path}")
            return True
        except Exception as exc:
            log.warning(f"🧠 MLPredictor: load failed ({exc}) — heuristic mode")
            return False

    def predict_win_probability(
        self, features: np.ndarray, update_norm: bool = True
    ) -> float:
        """
        Update the rolling normaliser, check for distribution shift,
        then return a probability in [0, 1].
        """
        if update_norm:
            self._norm.update(features)

        # Distribution-shift guard: if any feature >3.5 SD from rolling mean,
        # disable ML gate and fall through to heuristic so we don't trade on
        # an out-of-distribution feature set.
        if self._norm.check_distribution_shift(features, z_bound=3.5):
            log.warning(
                "🧠 MLPredictor: feature distribution shift detected "
                "(>3.5 SD) — returning threshold-minus-epsilon (0.64)"
            )
            return 0.64   # just below ML_WIN_PROB_THRESHOLD

        x = self._norm.transform(features)

        if self._model is not None:
            try:
                prob = float(self._model.predict_proba(x.reshape(1, -1))[0][1])
                prob = max(0.0, min(1.0, prob))
                self._prob_buf.append(prob)
                return prob
            except Exception as exc:
                log.warning(f"🧠 MLPredictor inference error: {exc} — heuristic")

        # ── Heuristic (features are normalised x) ─────────────────────────────
        # Indices (from extract_features):
        #  0 htf_bias | 1 atr_norm | 2 adr_pct | 3 fvg_strength
        #  4 spread_norm | 5 m15_enc | 6 has_liq | 7 has_ob
        #  8 sweep_fvg | 9 fvg_age_norm | 10 sweep_depth | 11 session_sin
        # Raw (not z-scored during cold-start) features:
        raw = features   # extract_features produces bounded [−1, 1]-ish values

        htf_aligned   = abs(float(raw[0])) > 0.5
        adr_pct       = float(raw[2])
        sweep_and_fvg = float(raw[8]) > 0.5
        has_liq       = float(raw[6]) > 0.5
        has_ob        = float(raw[7]) > 0.5
        m15_confirms  = abs(float(raw[5])) > 0.5
        fvg_fresh     = float(raw[9]) < 0.3   # normalised age below 30% of window
        sweep_depth   = float(raw[10])

        prob = 0.38
        if htf_aligned:    prob += 0.12
        if sweep_and_fvg:  prob += 0.10
        if has_liq:        prob += 0.07
        if has_ob:         prob += 0.06
        if m15_confirms:   prob += 0.06
        if fvg_fresh:      prob += 0.05
        if sweep_depth > 0.1: prob += min(0.04, sweep_depth * 0.4)
        if adr_pct > 0.80: prob -= 0.10

        prob = max(0.0, min(1.0, round(prob, 4)))
        self._prob_buf.append(prob)
        return prob

    @property
    def rolling_avg_prob(self) -> float:
        return float(np.mean(self._prob_buf)) if self._prob_buf else 0.0

    @property
    def norm_is_warm(self) -> bool:
        return self._norm.is_warm


# ══════════════════════════════════════════════════════════════════════════════
# 📊  CLASS: MarketDataFeed
# ══════════════════════════════════════════════════════════════════════════════
class MarketDataFeed:
    """
    All MT5 data retrieval and in-memory caching.
    Cache keyed by (timeframe, n_bars) — TTL differs by timeframe.
    """

    def __init__(self):
        self._cache: Dict[int, Tuple[float, pd.DataFrame]] = {}
        self._lock  = threading.Lock()

    @staticmethod
    def _ttl(tf: int) -> float:
        if tf in (mt5.TIMEFRAME_M1, mt5.TIMEFRAME_M5):
            return CACHE_TTL_LTF
        if tf == mt5.TIMEFRAME_D1:
            return CACHE_TTL_D1
        return CACHE_TTL_HTF

    def fetch(self, tf: int, n: int, use_cache: bool = True) -> Optional[pd.DataFrame]:
        now = time.time()
        with self._lock:
            if use_cache and tf in self._cache:
                ts, df = self._cache[tf]
                if now - ts < self._ttl(tf):
                    return df

        rates = mt5.copy_rates_from_pos(SYMBOL, tf, 0, n)
        if rates is None or len(rates) == 0:
            log.warning(f"MarketDataFeed.fetch: no data tf={tf}")
            return None

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        with self._lock:
            self._cache[tf] = (now, df)
        return df

    def get_cached_m5(self) -> Optional[pd.DataFrame]:
        with self._lock:
            entry = self._cache.get(mt5.TIMEFRAME_M5)
        return entry[1] if entry else None

    def fetch_all(self) -> Dict[str, Optional[pd.DataFrame]]:
        def _trim(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
            return df.iloc[:-1].copy() if df is not None else None

        m1  = _trim(self.fetch(mt5.TIMEFRAME_M1,   60, use_cache=False))
        m5  = _trim(self.fetch(mt5.TIMEFRAME_M5,  300, use_cache=False))
        m15 = _trim(self.fetch(mt5.TIMEFRAME_M15, 100, use_cache=True))
        h1  = _trim(self.fetch(mt5.TIMEFRAME_H1,  220, use_cache=True))
        d1  = self.fetch(mt5.TIMEFRAME_D1,  20, use_cache=True)
        return {"m1": m1, "m5": m5, "m15": m15, "h1": h1, "d1": d1}

    def get_current_m5_bar_time(self) -> Optional[int]:
        rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M5, 0, 1)
        if rates is not None and len(rates) > 0:
            return int(rates[0]["time"])
        return None


# ══════════════════════════════════════════════════════════════════════════════
# 🧮  INDICATOR FUNCTIONS  — [OPT-1] NumPy hot-path preserved
# ══════════════════════════════════════════════════════════════════════════════

def _to_numpy(df: pd.DataFrame, col: str) -> np.ndarray:
    return np.ascontiguousarray(df[col].values, dtype=np.float64)


def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """[OPT-1] Wilder ATR via NumPy vectorised TR calculation."""
    if len(df) < period + 1:
        return 0.0
    high  = _to_numpy(df, "high")
    low   = _to_numpy(df, "low")
    close = _to_numpy(df, "close")
    prev  = close[:-1]
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(np.abs(high[1:] - prev), np.abs(low[1:] - prev)),
    )
    if len(tr) < period:
        return 0.0
    atr_val = float(tr[:period].mean())
    alpha   = 1.0 / period
    for v in tr[period:]:
        atr_val = atr_val * (1.0 - alpha) + float(v) * alpha
    return atr_val if not np.isnan(atr_val) else 0.0


def calculate_adr(df_d1: Optional[pd.DataFrame], period: int = 10) -> float:
    """[OPT-1] Average Daily Range."""
    if df_d1 is None or len(df_d1) < period:
        return 0.0
    high = _to_numpy(df_d1, "high")
    low  = _to_numpy(df_d1, "low")
    return float((high - low)[-period:].mean())


def get_confirmed_swings_np(
    df: pd.DataFrame, period: int = 5, confirm: int = 2
) -> Tuple[float, float]:
    """[OPT-1] Confirmed swing High / Low using NumPy stride windows."""
    if len(df) < period * 2 + confirm + 1:
        return float(df["high"].max()), float(df["low"].min())
    high     = _to_numpy(df, "high")
    low      = _to_numpy(df, "low")
    safe_len = len(high) - confirm
    sh_vals, sl_vals = [], []
    for i in range(period, safe_len - period):
        if high[i] == high[i - period: i + period + 1].max():
            sh_vals.append(high[i])
        if low[i] == low[i - period: i + period + 1].min():
            sl_vals.append(low[i])
    return (
        float(sh_vals[-1]) if sh_vals else float(high.max()),
        float(sl_vals[-1]) if sl_vals else float(low.min()),
    )


def _cluster_liquidity_levels(prices: List[float], tol: float) -> List[float]:
    """Module-level O(n²) cluster helper (n is always small ≤ 50)."""
    clusters: List[float] = []
    used = [False] * len(prices)
    for i in range(len(prices)):
        if used[i]:
            continue
        group = [prices[i]]
        for j in range(i + 1, len(prices)):
            if not used[j] and abs(prices[j] - prices[i]) <= tol:
                group.append(prices[j])
                used[j] = True
        if len(group) >= LIQ_MIN_CLUSTER:
            clusters.append(round(sum(group) / len(group), 5))
    return clusters


def build_liquidity_map_np(
    df: pd.DataFrame, atr: float, period: int = 10
) -> LiquidityMap:
    """
    [OPT-1] + [V13-P1-C] Liquidity map with gap-crossed sweep detection.

    Original:  swept if last_high > level AND last_close < level.
               Misses gap-through events (last_high and last_close both below level).
    V13 adds:  gap_crossed sweep — if prev_close was above level and
               current_open is below level (or vice versa), the level was
               swept by the gap itself.
    """
    liq = LiquidityMap()
    if len(df) < period * 2 + 4 or atr == 0:
        return liq

    high = _to_numpy(df, "high")
    low  = _to_numpy(df, "low")
    cls  = _to_numpy(df, "close")
    opn  = _to_numpy(df, "open")
    safe = len(high) - 2
    tol  = max(atr * 0.08, abs(cls[-1]) * LIQ_EQUAL_TOLERANCE)

    ph_list, pl_list = [], []
    for i in range(period, safe - period):
        if high[i] == high[i - period: i + period + 1].max():
            ph_list.append(high[i])
        if low[i] == low[i - period: i + period + 1].min():
            pl_list.append(low[i])

    liq.buy_side  = sorted(_cluster_liquidity_levels(ph_list, tol), reverse=True)
    liq.sell_side = sorted(_cluster_liquidity_levels(pl_list, tol))

    last_high  = float(high[-1])
    last_low   = float(low[-1])
    last_close = float(cls[-1])
    prev_close = float(cls[-2]) if len(cls) >= 2 else last_close
    cur_open   = float(opn[-1])

    # Standard wick sweep
    for lvl in liq.buy_side:
        if last_high > lvl and last_close < lvl:
            liq.swept_high = lvl
            break
    for lvl in liq.sell_side:
        if last_low < lvl and last_close > lvl:
            liq.swept_low = lvl
            break

    # [V13-P1-C] Gap-through sweep (NFP/CPI gap candles)
    for lvl in liq.buy_side:
        if prev_close >= lvl > cur_open:        # gap down through BSL
            liq.gap_swept_high = lvl
            break
    for lvl in liq.sell_side:
        if prev_close <= lvl < cur_open:        # gap up through SSL
            liq.gap_swept_low = lvl
            break

    price = last_close
    above = [l for l in liq.buy_side  if l > price]
    below = [l for l in liq.sell_side if l < price]
    liq.bsl_nearest = min(above) if above else None
    liq.ssl_nearest = max(below) if below else None
    return liq


# ══════════════════════════════════════════════════════════════════════════════
# 🧠  CLASS: SMCSignalEngine
# ══════════════════════════════════════════════════════════════════════════════
class SMCSignalEngine:
    """
    Encapsulates all signal detection logic.
    V13 fixes: M15 BOS rebuilt, OB freshness/mitigation added.
    """

    # ── HTF Bias ──────────────────────────────────────────────────────────────
    @staticmethod
    def get_htf_bias(df_h1: Optional[pd.DataFrame]) -> HTFBiasResult:
        res = HTFBiasResult()
        if df_h1 is None or len(df_h1) < HTF_SWING_PERIOD * 2 + HTF_SWING_CONFIRM + 5:
            res.reason = "H1 data insufficient"
            return res

        lookback = min(60, len(df_h1))
        df = df_h1.iloc[-lookback:].reset_index(drop=True)
        p, c = HTF_SWING_PERIOD, HTF_SWING_CONFIRM
        high = _to_numpy(df, "high")
        low  = _to_numpy(df, "low")
        cls  = _to_numpy(df, "close")
        safe = len(high) - c

        sh_list: List[Tuple[int, float]] = []
        sl_list: List[Tuple[int, float]] = []
        for i in range(p, safe - p):
            if high[i] == high[i - p: i + p + 1].max():
                sh_list.append((i, float(high[i])))
            if low[i] == low[i - p: i + p + 1].min():
                sl_list.append((i, float(low[i])))

        if len(sh_list) < 2 or len(sl_list) < 2:
            res.reason = "Insufficient swings"
            return res

        prev_sh = sh_list[-1][1]
        prev_sl = sl_list[-1][1]

        last_high  = float(high[-1])
        last_low   = float(low[-1])
        last_close = float(cls[-1])

        if last_high > prev_sh and last_close < prev_sh:
            res.swept_high = prev_sh
        if last_low < prev_sl and last_close > prev_sl:
            res.swept_low = prev_sl

        recent_cls = cls[-5:]
        bos_up   = bool(np.any(recent_cls > prev_sh))
        bos_down = bool(np.any(recent_cls < prev_sl))

        hh = sh_list[-1][1] > sh_list[-2][1]
        lh = sh_list[-1][1] < sh_list[-2][1]
        hl = sl_list[-1][1] > sl_list[-2][1]
        ll = sl_list[-1][1] < sl_list[-2][1]

        bull_pts = bear_pts = 0
        if bos_up:         bull_pts += 2; res.last_bos = "UP"
        if bos_down:       bear_pts += 2; res.last_bos = "DOWN"
        if hh and hl:      bull_pts += 2
        if lh and ll:      bear_pts += 2
        if res.swept_low:  bull_pts += 1
        if res.swept_high: bear_pts += 1

        if bos_up   and (lh and ll): res.choch_signal = "UP"
        if bos_down and (hh and hl): res.choch_signal = "DOWN"

        if bull_pts >= 3 and bull_pts > bear_pts:
            res.bias   = "BULLISH"
            res.reason = f"BOS_UP:{bos_up}|HH:{hh}|HL:{hl}|SwL:{res.swept_low is not None}"
        elif bear_pts >= 3 and bear_pts > bull_pts:
            res.bias   = "BEARISH"
            res.reason = f"BOS_DN:{bos_down}|LH:{lh}|LL:{ll}|SwH:{res.swept_high is not None}"
        else:
            res.bias   = "NEUTRAL"
            res.reason = f"Bull:{bull_pts} Bear:{bear_pts} unclear"
        return res

    # ── M15 Structure [V13-P1-A] rebuilt ─────────────────────────────────────
    @staticmethod
    def get_m15_structure(df_m15: Optional[pd.DataFrame]) -> str:
        """
        [V13-P1-A] Proper swing-BOS on M15 using get_confirmed_swings_np.
        Previous version compared close[-1] vs high[-2]/low[-2] — single-bar
        noise masquerading as structural BOS.  Now requires the close to break
        a confirmed swing high/low over SWING_PERIOD bars on M15.
        """
        if df_m15 is None or len(df_m15) < SWING_PERIOD * 2 + SWING_CONFIRM_BARS + 5:
            return "NEUTRAL"
        # Use the most recent 40 bars to avoid stale swings dominating
        sub = df_m15.iloc[-40:].reset_index(drop=True)
        sh, sl = get_confirmed_swings_np(sub, period=SWING_PERIOD, confirm=SWING_CONFIRM_BARS)
        last_close = float(sub["close"].iloc[-1])
        # Require a definitive break — not just touching
        point_buffer = (sh - sl) * 0.005   # 0.5% of range as minimum break distance
        if last_close > sh + point_buffer:
            return "BULLISH_BOS"
        if last_close < sl - point_buffer:
            return "BEARISH_BOS"
        return "NEUTRAL"

    # ── FVG Memory ────────────────────────────────────────────────────────────
    @staticmethod
    def scan_fvg_memory(df: pd.DataFrame, atr: float, lookback: int = 30) -> List[FVGZone]:
        zones: List[FVGZone] = []
        if len(df) < lookback + 3 or atr == 0:
            return zones

        min_gap = atr * FVG_BUFFER_RATIO
        start   = max(3, len(df) - lookback)

        for i in range(start, len(df) - 2):
            c1 = df.iloc[i]
            c2 = df.iloc[i + 1]
            c3 = df.iloc[i + 2]

            c2_range = float(c2["high"] - c2["low"])
            c2_body  = abs(float(c2["close"] - c2["open"]))
            if c2_range > 0 and (c2_body / c2_range) < FVG_MOMENTUM_RATIO:
                continue

            # Bullish FVG: c3.low > c1.high
            gap_bull = float(c3["low"]) - float(c1["high"])
            if gap_bull >= min_gap:
                top = float(c3["low"])
                bot = float(c1["high"])
                gap = top - bot
                strength = min(2.0, gap / atr)
                mitigated = False
                mid = bot + gap * FVG_MITIGATED_PCT
                for j in range(i + 3, len(df)):
                    if float(df.iloc[j]["low"]) <= mid:
                        mitigated = True
                        break
                zones.append(FVGZone("BULLISH", top, bot, strength, i, mitigated))

            # Bearish FVG: c1.low > c3.high
            gap_bear = float(c1["low"]) - float(c3["high"])
            if gap_bear >= min_gap:
                top = float(c1["low"])
                bot = float(c3["high"])
                gap = top - bot
                strength = min(2.0, gap / atr)
                mitigated = False
                mid = top - gap * FVG_MITIGATED_PCT
                for j in range(i + 3, len(df)):
                    if float(df.iloc[j]["high"]) >= mid:
                        mitigated = True
                        break
                zones.append(FVGZone("BEARISH", top, bot, strength, i, mitigated))

        zones.sort(key=lambda z: z.bar_index, reverse=True)
        return zones

    @staticmethod
    def get_active_fvg(
        zones: List[FVGZone], price: float, direction: str
    ) -> Optional[FVGZone]:
        target = "BULLISH" if direction == "BUY" else "BEARISH"
        for z in zones:
            if z.mitigated or z.kind != target:
                continue
            buf = (z.top - z.bot) * FVG_BUFFER_RATIO
            if (z.bot - buf) <= price <= (z.top + buf):
                return z
        return None

    # ── Order Block [V13-P1-B] with freshness + mitigation ───────────────────
    @staticmethod
    def find_order_block(
        df: pd.DataFrame, direction: str, atr: float
    ) -> OBResult:
        """
        [V13-P1-B] OBResult now tracks bar_age and mitigated status.
        A mitigated OB (price has closed through it) returns mitigated=True
        and should NOT receive SCORE_OB_BONUS.
        """
        if len(df) < 10 or atr == 0:
            return OBResult()

        closed   = df.iloc[:-1]
        n        = len(closed)
        max_age  = min(30, n - 2)

        for age in range(1, max_age):
            i   = n - 1 - age
            ob  = closed.iloc[i]
            if i + 1 >= n - 1:
                continue
            imp = closed.iloc[i + 1]

            imp_body = abs(float(imp["close"]) - float(imp["open"]))
            if imp_body < atr * 1.2:
                continue

            if direction == "BUY":
                if ob["close"] >= ob["open"]:
                    continue
                if imp["close"] <= imp["open"]:
                    continue
                # Require impulse to break prior structure
                ph_window = closed["high"].iloc[max(0, i - 10): i]
                if len(ph_window) > 0 and imp["close"] <= ph_window.max() * 0.998:
                    continue
                # Check mitigation: any close below OB.low since formation
                ob_low = float(ob["low"])
                ob_high = float(ob["high"])
                mitigated = False
                for j in range(i + 2, n):
                    if float(closed.iloc[j]["close"]) < ob_low:
                        mitigated = True
                        break

                rng   = ob_high - ob_low
                body  = (float(ob["open"]) - float(ob["close"])) / rng if rng > 0 else 0
                sweep = float(closed["low"].iloc[max(0, i - 5): i].min()) < ob_low
                q     = 0.5 + (0.3 if sweep else 0) + (0.2 if body > 0.6 else 0)
                return OBResult(True, ob_high, ob_low, q, bar_age=age, mitigated=mitigated)

            else:  # SELL
                if ob["close"] <= ob["open"]:
                    continue
                if imp["close"] >= imp["open"]:
                    continue
                pl_window = closed["low"].iloc[max(0, i - 10): i]
                if len(pl_window) > 0 and imp["close"] >= float(pl_window.min()) * 1.002:
                    continue
                ob_low  = float(ob["low"])
                ob_high = float(ob["high"])
                mitigated = False
                for j in range(i + 2, n):
                    if float(closed.iloc[j]["close"]) > ob_high:
                        mitigated = True
                        break

                rng   = ob_high - ob_low
                body  = (float(ob["close"]) - float(ob["open"])) / rng if rng > 0 else 0
                sweep = float(closed["high"].iloc[max(0, i - 5): i].max()) > ob_high
                q     = 0.5 + (0.3 if sweep else 0) + (0.2 if body > 0.6 else 0)
                return OBResult(True, ob_high, ob_low, q, bar_age=age, mitigated=mitigated)

        return OBResult()

    # ── Session helpers ───────────────────────────────────────────────────────
    @staticmethod
    def get_session() -> str:
        now = datetime.now(bkk_tz).time()
        for sh, sm, eh, em in NEWS_BLOCKS:
            if dtime(sh, sm) <= now <= dtime(eh, em):
                return "RED_NEWS_BLOCK"
        for sh, sm, eh, em, name in SESSIONS:
            s, e = dtime(sh, sm), dtime(eh, em)
            if e < s:
                if now >= s or now <= e:
                    return name
            else:
                if s <= now <= e:
                    return name
        return "OUT_OF_SESSION"

    @staticmethod
    def is_in_killzone() -> Tuple[bool, str]:
        if not KILLZONE_ENABLED:
            return True, "All"
        now = datetime.now(bkk_tz).time()
        for sh, sm, eh, em, name in KILLZONES:
            if dtime(sh, sm) <= now <= dtime(eh, em):
                return True, name
        return False, "Outside Killzone"

    @staticmethod
    def get_dynamic_threshold(session: str, htf_bias: str, adr_pct: float) -> int:
        base = SCORE_THRESHOLD.get(session, SCORE_THRESHOLD["DEFAULT"])
        if htf_bias == "NEUTRAL":
            base += SCORE_PENALTY_HTF_NEUTRAL
        if adr_pct >= ADR_EXHAUSTED_PCT:
            base += SCORE_PENALTY_HIGH_ADR
        return base

    # ── Master setup analyser ─────────────────────────────────────────────────
    def analyze_setup(
        self,
        df_m5:  Optional[pd.DataFrame],
        df_h1:  Optional[pd.DataFrame],
        df_d1:  Optional[pd.DataFrame],
        df_m15: Optional[pd.DataFrame],
        session: str = "DEFAULT",
    ) -> SetupResult:
        r = SetupResult()

        if df_m5 is None or len(df_m5) < 30:
            r.reasons.append("M5 data insufficient")
            return r

        atr = calculate_atr(df_m5)
        if atr == 0:
            r.reasons.append("ATR=0")
            return r
        r.atr = atr

        adr = calculate_adr(df_d1)
        if adr > 0 and df_d1 is not None and len(df_d1) >= 1:
            day_range = float(df_d1["high"].iloc[-1] - df_d1["low"].iloc[-1])
            r.adr_pct = day_range / adr

        # [V13-P0-A] ADR hard block
        if ADR_HARD_BLOCK and r.adr_pct >= ADR_EXHAUSTED_PCT:
            r.reasons.append(f"ADR_HARD_BLOCK({r.adr_pct*100:.0f}%)")
            return r   # signal=WAIT

        htf_res     = self.get_htf_bias(df_h1)
        r.htf_bias  = htf_res.bias
        r.htf_result = htf_res
        r.m15_struct = self.get_m15_structure(df_m15)
        r.threshold  = self.get_dynamic_threshold(session, r.htf_bias, r.adr_pct)

        liq       = build_liquidity_map_np(df_m5, atr, LIQ_SWING_PERIOD)
        r.liq_map = liq

        last_sh, last_sl = get_confirmed_swings_np(df_m5, SWING_PERIOD, SWING_CONFIRM_BARS)
        fvg_lookback     = FVG_MEMORY_BARS.get(session, FVG_MEMORY_BARS["DEFAULT"])
        fvg_zones        = self.scan_fvg_memory(df_m5, atr, fvg_lookback)

        last  = df_m5.iloc[-1]
        prev  = df_m5.iloc[-2]
        r.candle_ts = (
            float(last["time"].timestamp())
            if hasattr(last["time"], "timestamp") else time.time()
        )

        price      = float(last["close"])
        sweep_sell = float(last["low"]) < last_sl and float(last["close"]) > last_sl
        sweep_buy  = float(last["high"]) > last_sh and float(last["close"]) < last_sh

        # Also count gap sweeps
        if liq.gap_swept_low is not None:
            sweep_sell = True
        if liq.gap_swept_high is not None:
            sweep_buy = True

        # ── Inner build helpers ───────────────────────────────────────────────
        def _build_buy() -> bool:
            has_sweep  = sweep_sell
            fvg_active = self.get_active_fvg(fvg_zones, price, "BUY")
            if not has_sweep and fvg_active is None:
                return False

            r.signal = "BUY"
            r.score  = SCORE_BASE

            if fvg_active is not None:
                if FVG_ENTRY_MID:
                    # [V13-P0-A] Mid-zone entry
                    r.entry = fvg_active.bot + (fvg_active.top - fvg_active.bot) * 0.5
                else:
                    r.entry = fvg_active.top
                r.fvg_zone = fvg_active
            elif has_sweep:
                r.entry = last_sl + (atr * 0.1)

            # [V13-P0-A] SL widened to SL_ATR_MULT × ATR
            r.sl = last_sl - (atr * SL_ATR_MULT)

            if has_sweep and fvg_active is not None:
                r.score += SCORE_SWEEP_AND_FVG
                r.reasons.append("Sweep+FVG ✓✓")
            elif has_sweep:
                r.reasons.append("Sweep SSL ✓")
            else:
                r.reasons.append("FVG Zone ✓")

            if liq.gap_swept_low is not None:
                r.score += 5
                r.reasons.append("Gap-Sweep SSL ✓")

            if fvg_active is not None and not fvg_active.mitigated:
                r.score += SCORE_FVG_FRESH
                r.reasons.append(f"FVG Fresh(s:{fvg_active.strength:.2f}) ✓")
                if fvg_active.strength > 0.5:
                    r.score += SCORE_FVG_STRENGTH

            if r.htf_bias == "BULLISH":
                r.score += SCORE_HTF_ALIGN
                choch_tag = "(CHOCH)" if htf_res.choch_signal == "UP" else ""
                r.reasons.append(f"HTF Bull{choch_tag} ✓")
            elif r.htf_bias == "BEARISH":
                r.score += SCORE_HTF_AGAINST
                r.reasons.append("HTF Bear ⚠️")

            # [V13-P0-A] FIX-D: HTF NEUTRAL requires very high score
            if r.htf_bias == "NEUTRAL":
                r.reasons.append("HTF Neutral ⚠️")
                # Threshold enforcement happens after score assembly in analyze_setup

            if htf_res.swept_low is not None:
                r.score += 4
                r.reasons.append("H1 SSL Swept ✓")

            if r.m15_struct == "BULLISH_BOS":
                r.score += SCORE_M15_BOS
                r.reasons.append("M15 BOS ✓")

            body = float(last["close"]) - float(last["open"])
            if body > atr * 0.6:
                r.score += SCORE_STRONG_CANDLE
                r.reasons.append("Strong ✓")

            ob = self.find_order_block(df_m5, "BUY", atr)
            if ob.found and not ob.mitigated:
                r.score += int(SCORE_OB_BONUS * ob.score)
                r.reasons.append(f"OB(q:{ob.score:.2f},age:{ob.bar_age}) ✓")
                if ob.low <= r.entry <= ob.high:
                    r.score += SCORE_OB_OVERLAP
                    r.reasons.append("OB Overlap ✓")
            elif ob.found and ob.mitigated:
                r.reasons.append(f"OB(mitigated,age:{ob.bar_age}) ⚠️")

            if float(last["close"]) > float(prev["high"]):
                r.score += SCORE_BOS_M5
                r.reasons.append("BOS ✓")

            if liq.swept_low is not None:
                r.score += SCORE_LIQ_SWEPT
                r.reasons.append(f"SSL Swept({liq.swept_low:.2f}) ✓")
            if liq.bsl_nearest is not None:
                risk = abs(r.entry - r.sl)
                if risk > 0 and (liq.bsl_nearest - r.entry) >= risk * RR_RATIO * 0.8:
                    r.score += SCORE_LIQ_TARGET
                    r.reasons.append(f"BSL→{liq.bsl_nearest:.2f} ✓")

            if r.adr_pct >= ADR_EXHAUSTED_PCT:
                r.score += SCORE_ADR_WARN
                r.reasons.append(f"ADR{r.adr_pct*100:.0f}% ⚠️")

            body_ratio = body / atr if atr > 0 else 0
            if (
                float(last["close"]) > float(prev["high"])
                and body_ratio > MOMENTUM_BODY_ATR
                and r.score >= r.threshold
            ):
                r.use_market = True
                r.entry      = 0.0
                r.reasons.append("🚀 MKT")

            return True

        def _build_sell() -> bool:
            has_sweep  = sweep_buy
            fvg_active = self.get_active_fvg(fvg_zones, price, "SELL")
            if not has_sweep and fvg_active is None:
                return False

            r.signal = "SELL"
            r.score  = SCORE_BASE

            if fvg_active is not None:
                if FVG_ENTRY_MID:
                    r.entry = fvg_active.bot + (fvg_active.top - fvg_active.bot) * 0.5
                else:
                    r.entry = fvg_active.bot
                r.fvg_zone = fvg_active
            elif has_sweep:
                r.entry = last_sh - (atr * 0.1)

            r.sl = last_sh + (atr * SL_ATR_MULT)

            if has_sweep and fvg_active is not None:
                r.score += SCORE_SWEEP_AND_FVG
                r.reasons.append("Sweep+FVG ✓✓")
            elif has_sweep:
                r.reasons.append("Sweep BSL ✓")
            else:
                r.reasons.append("FVG Zone ✓")

            if liq.gap_swept_high is not None:
                r.score += 5
                r.reasons.append("Gap-Sweep BSL ✓")

            if fvg_active is not None and not fvg_active.mitigated:
                r.score += SCORE_FVG_FRESH
                r.reasons.append(f"FVG Fresh(s:{fvg_active.strength:.2f}) ✓")
                if fvg_active.strength > 0.5:
                    r.score += SCORE_FVG_STRENGTH

            if r.htf_bias == "BEARISH":
                r.score += SCORE_HTF_ALIGN
                choch_tag = "(CHOCH)" if htf_res.choch_signal == "DOWN" else ""
                r.reasons.append(f"HTF Bear{choch_tag} ✓")
            elif r.htf_bias == "BULLISH":
                r.score += SCORE_HTF_AGAINST
                r.reasons.append("HTF Bull ⚠️")

            if r.htf_bias == "NEUTRAL":
                r.reasons.append("HTF Neutral ⚠️")

            if htf_res.swept_high is not None:
                r.score += 4
                r.reasons.append("H1 BSL Swept ✓")

            if r.m15_struct == "BEARISH_BOS":
                r.score += SCORE_M15_BOS
                r.reasons.append("M15 BOS ✓")

            body = float(last["open"]) - float(last["close"])
            if body > atr * 0.6:
                r.score += SCORE_STRONG_CANDLE
                r.reasons.append("Strong ✓")

            ob = self.find_order_block(df_m5, "SELL", atr)
            if ob.found and not ob.mitigated:
                r.score += int(SCORE_OB_BONUS * ob.score)
                r.reasons.append(f"OB(q:{ob.score:.2f},age:{ob.bar_age}) ✓")
                if ob.low <= r.entry <= ob.high:
                    r.score += SCORE_OB_OVERLAP
                    r.reasons.append("OB Overlap ✓")
            elif ob.found and ob.mitigated:
                r.reasons.append(f"OB(mitigated,age:{ob.bar_age}) ⚠️")

            if float(last["close"]) < float(prev["low"]):
                r.score += SCORE_BOS_M5
                r.reasons.append("BOS ✓")

            if liq.swept_high is not None:
                r.score += SCORE_LIQ_SWEPT
                r.reasons.append(f"BSL Swept({liq.swept_high:.2f}) ✓")
            if liq.ssl_nearest is not None:
                risk = abs(r.sl - r.entry)
                if risk > 0 and (r.entry - liq.ssl_nearest) >= risk * RR_RATIO * 0.8:
                    r.score += SCORE_LIQ_TARGET
                    r.reasons.append(f"SSL→{liq.ssl_nearest:.2f} ✓")

            if r.adr_pct >= ADR_EXHAUSTED_PCT:
                r.score += SCORE_ADR_WARN
                r.reasons.append(f"ADR{r.adr_pct*100:.0f}% ⚠️")

            body_ratio = body / atr if atr > 0 else 0
            if (
                float(last["close"]) < float(prev["low"])
                and body_ratio > MOMENTUM_BODY_ATR
                and r.score >= r.threshold
            ):
                r.use_market = True
                r.entry      = 0.0
                r.reasons.append("🚀 MKT")

            return True

        if not _build_buy():
            r.signal  = "WAIT"
            r.score   = 0
            r.reasons = []
            if not _build_sell():
                return r

        # [V13-P0-A] FIX-D: reject NEUTRAL HTF unless score exceeds HTF_NEUTRAL_MIN_SCORE
        if r.signal != "WAIT" and r.htf_bias == "NEUTRAL":
            if r.score < HTF_NEUTRAL_MIN_SCORE:
                log.info(
                    f"🚫 HTF-NEUTRAL filter: score {r.score} < {HTF_NEUTRAL_MIN_SCORE} → WAIT"
                )
                return SetupResult()   # WAIT

        if r.signal != "WAIT":
            entry_h      = r.entry if not r.use_market else -1.0
            r.setup_hash = _make_hash(r.signal, entry_h, r.sl, r.candle_ts)

        return r


# ══════════════════════════════════════════════════════════════════════════════
# 💰  CLASS: RiskManager  [V13-P2-C] three-tier DD protocol
# ══════════════════════════════════════════════════════════════════════════════
class RiskManager:
    """
    Encapsulates all risk checks and lot sizing.
    V13: three-tier DD communication (yellow/orange/red) integrated here.
    """

    @staticmethod
    def get_broker_date() -> str:
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is not None:
            return datetime.fromtimestamp(tick.time, tz=pytz.utc).strftime("%Y%m%d")
        return datetime.utcnow().strftime("%Y%m%d")

    @staticmethod
    def get_spread_pts() -> float:
        tick = mt5.symbol_info_tick(SYMBOL)
        info = mt5.symbol_info(SYMBOL)
        if tick is None or info is None:
            return 999.0
        return (tick.ask - tick.bid) / info.point

    def is_spread_ok(self) -> bool:
        sp = self.get_spread_pts()
        if sp > HARD_SPREAD_BLOCK:
            log.warning(f"⛔ Spread {sp:.1f}pts > HARD_BLOCK {HARD_SPREAD_BLOCK}")
            return False
        return True

    @staticmethod
    def get_spread_sl_padding() -> float:
        if not SPREAD_SL_PADDING:
            return 0.0
        tick = mt5.symbol_info_tick(SYMBOL)
        info = mt5.symbol_info(SYMBOL)
        if tick is None or info is None:
            return 0.0
        return ((tick.ask - tick.bid) / info.point) * info.point

    def get_dd_state(self) -> Tuple[float, float, str]:
        """
        [V13-P2-C] Returns (daily_dd_pct, total_dd_pct, mode_str).
        mode_str ∈ {"NORMAL", "YELLOW", "ORANGE", "RED"}
        """
        acct = mt5.account_info()
        if acct is None:
            return 0.0, 0.0, "NORMAL"

        equity  = acct.equity
        balance = acct.balance

        today_key   = "daily_start_balance_" + self.get_broker_date()
        daily_start = get_state(today_key)
        if daily_start is None or daily_start <= 0:
            set_state(today_key, balance)
            daily_start = balance

        daily_dd = max(0.0, (daily_start - equity) / daily_start * 100)

        init_bal = get_state("initial_balance")
        if init_bal is None:
            set_state("initial_balance", balance)
            init_bal = balance
        total_dd = max(0.0, (init_bal - equity) / init_bal * 100)

        if daily_dd >= MAX_DAILY_LOSS_PCT or total_dd >= MAX_TOTAL_DD_PCT:
            mode = "RED"
        elif daily_dd >= DD_ORANGE_PCT:
            mode = "ORANGE"
        elif daily_dd >= DD_YELLOW_PCT:
            mode = "YELLOW"
        else:
            mode = "NORMAL"

        return round(daily_dd, 2), round(total_dd, 2), mode

    def is_within_risk_limits(self) -> bool:
        _, _, mode = self.get_dd_state()
        return mode not in ("RED",)

    def new_entries_allowed(self) -> bool:
        """[V13-P2-C] Orange and above suspends new entries."""
        _, _, mode = self.get_dd_state()
        return mode not in ("RED", "ORANGE")

    def is_circuit_breaker_tripped(self) -> bool:
        acct = mt5.account_info()
        if acct is None:
            return False
        today_key   = "daily_start_balance_" + self.get_broker_date()
        daily_start = get_state(today_key)
        if daily_start is None or daily_start <= 0:
            return False
        dd_pct = (daily_start - acct.equity) / daily_start * 100
        if dd_pct >= CIRCUIT_BREAKER_PCT:
            log.warning(
                f"⚡ Circuit Breaker: DD {dd_pct:.2f}% ≥ {CIRCUIT_BREAKER_PCT}%"
                " → halting new orders"
            )
            return True
        return False

    def get_risk_tier_multiplier(self, score: int, dd_mode: str) -> float:
        """[V13-P2-C] Yellow DD reduces risk tier by 1 step."""
        base_pct = RISK_TIERS[-1][1]
        for score_min, pct in RISK_TIERS:
            if score >= score_min:
                base_pct = pct
                break
        if dd_mode == "YELLOW":
            # Find next lower tier
            current_idx = next(
                (i for i, (sm, _) in enumerate(RISK_TIERS) if score >= sm), len(RISK_TIERS) - 1
            )
            reduced_idx = min(current_idx + 1, len(RISK_TIERS) - 1)
            base_pct = RISK_TIERS[reduced_idx][1]
            log.info(f"💛 DD Yellow: risk tier reduced → {base_pct:.2f}×")
        return base_pct

    @staticmethod
    def _round_lot(lot: float, step: float) -> float:
        d_lot  = Decimal(str(lot))
        d_step = Decimal(str(step))
        return float(
            (d_lot / d_step).to_integral_value(rounding=ROUND_DOWN) * d_step
        )

    def calculate_lot(
        self, entry: float, sl: float,
        score: int = 0, spread_pts: float = 0.0, atr: float = 0.0,
        dd_mode: str = "NORMAL",
    ) -> float:
        """[EDGE-1] Risk-based lot sizing with DD-tier reduction."""
        info = mt5.symbol_info(SYMBOL)
        acct = mt5.account_info()
        if info is None or acct is None:
            log.warning("calculate_lot: cannot read broker info → LOT_MIN")
            return LOT_MIN

        risk_pct = self.get_risk_tier_multiplier(score, dd_mode)

        if spread_pts > MAX_SPREAD_POINTS:
            risk_pct *= (1.0 - SPREAD_LOT_PENALTY)
            log.info(f"📉 Spread penalty → risk_pct={risk_pct:.3f}")

        balance     = acct.balance
        risk_amount = balance * (risk_pct / 100.0)

        sl_dist = abs(entry - sl)
        if sl_dist == 0:
            log.error("calculate_lot: SL dist=0 → LOT_MIN")
            return LOT_MIN

        sl_pts   = max(1.0, sl_dist / info.point)
        tick_val = info.trade_tick_value
        if not tick_val or tick_val <= 0:
            tick_val = info.trade_contract_size * info.point
        if tick_val <= 0:
            log.warning("calculate_lot: tick_value unavailable → LOT_MIN")
            return LOT_MIN

        raw_lot = risk_amount / (sl_pts * tick_val)
        step    = info.volume_step if info.volume_step > 0 else 0.01
        lot     = self._round_lot(raw_lot, step)

        if lot <= 0.0:
            lot = info.volume_min

        lot = max(info.volume_min, min(lot, info.volume_max, LOT_MAX))
        log.info(
            f"💰 Lot | Score:{score} DD:{dd_mode} Risk:{risk_pct:.2f}% "
            f"Bal:{balance:.0f} SL:{sl_pts:.1f}pts → {lot}"
        )
        return float(lot)

    @staticmethod
    def dynamic_deviation(atr: float) -> int:
        info = mt5.symbol_info(SYMBOL)
        if info is None or info.point == 0:
            return 50
        return max(50, int(atr * 0.1 / info.point))

    @staticmethod
    def validate_order(
        entry: float, sl: float, tp: float, lot: float, signal: str
    ) -> Tuple[bool, str]:
        info = mt5.symbol_info(SYMBOL)
        acct = mt5.account_info()
        tick = mt5.symbol_info_tick(SYMBOL)
        if not all([info, acct, tick]):
            return False, "Cannot read broker data"

        min_d = info.trade_stops_level * info.point
        if abs(entry - sl) < min_d:
            return False, "SL too close (stop_level)"
        if abs(entry - tp) < min_d:
            return False, "TP too close (stop_level)"

        frz = info.trade_freeze_level * info.point
        if frz > 0 and abs(entry - tick.ask) < frz:
            return False, "Entry in freeze zone"

        d_lot  = Decimal(str(lot))
        d_step = Decimal(str(info.volume_step))
        if d_lot % d_step > Decimal("1e-8"):
            return False, "Lot step mismatch"

        otype      = mt5.ORDER_TYPE_BUY if signal == "BUY" else mt5.ORDER_TYPE_SELL
        margin_req = mt5.order_calc_margin(otype, SYMBOL, lot, entry)
        if margin_req is None or margin_req > acct.margin_free * 0.9:
            return False, "Insufficient margin"

        return True, "OK"

    @staticmethod
    def has_duplicate_setup(setup_hash: str, signal: str) -> bool:  # noqa: ARG002
        for p in (mt5.positions_get(symbol=SYMBOL) or []):
            if p.magic == MAGIC_NUMBER and setup_hash in (p.comment or ""):
                return True
        for o in (mt5.orders_get(symbol=SYMBOL) or []):
            if o.magic == MAGIC_NUMBER and setup_hash in (o.comment or ""):
                return True
        return False

    @staticmethod
    def count_open_positions() -> int:
        positions = mt5.positions_get(symbol=SYMBOL) or []
        return sum(1 for p in positions if p.magic == MAGIC_NUMBER)


# ══════════════════════════════════════════════════════════════════════════════
# 📤  CLASS: ExecutionHandler  [FIX-1/2/5/8 preserved]
# ══════════════════════════════════════════════════════════════════════════════
class ExecutionHandler:
    """
    Wraps all MT5 order-send operations.
    V13: place_order passes dd_mode to calculate_lot for tier-aware sizing.
    """

    def __init__(self, risk: RiskManager):
        self._risk = risk
        self._lock = threading.Lock()   # wraps only the order_send call

    def _send_retry(self, req: dict, retries: int = 3):
        """[FIX-1] Non-blocking retry with live price refresh on REQUOTE."""
        last_res = None
        is_buy   = req.get("type") in (
            mt5.ORDER_TYPE_BUY,
            mt5.ORDER_TYPE_BUY_LIMIT,
            mt5.ORDER_TYPE_BUY_STOP,
        )
        for i in range(1, retries + 1):
            with self._lock:
                res = mt5.order_send(req)

            if res is None:
                log.warning(f"order_send None (try {i}/{retries})")
                if i < retries:
                    time.sleep(0.5)
                continue

            last_res = res
            if res.retcode == mt5.TRADE_RETCODE_DONE:
                return res

            if res.retcode in (
                mt5.TRADE_RETCODE_REQUOTE,
                mt5.TRADE_RETCODE_PRICE_CHANGED,
                mt5.TRADE_RETCODE_PRICE_OFF,
            ):
                tick = mt5.symbol_info_tick(SYMBOL)
                if tick is not None:
                    new_price = tick.ask if is_buy else tick.bid
                    log.warning(
                        f"[FIX-1] Price refresh retcode {res.retcode}: "
                        f"{req.get('price','?'):.2f}→{new_price:.2f} (try {i})"
                    )
                    req["price"] = round(float(new_price), 2)
                if i < retries:
                    time.sleep(0.3 * i)
                continue

            if res.retcode in (
                mt5.TRADE_RETCODE_CONNECTION,
                mt5.TRADE_RETCODE_TIMEOUT,
            ):
                log.warning(f"Retry retcode:{res.retcode} (try {i}/{retries})")
                if i < retries:
                    time.sleep(0.5 * i)
                continue

            log.error(f"❌ retcode:{res.retcode} | {res.comment}")
            return res

        log.error(f"❌ _send_retry exhausted {retries} attempts")
        return last_res

    def modify_sl(self, ticket: int, new_sl: float) -> None:
        req = {
            "action":   mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "sl":       round(float(new_sl), 2),
        }
        with self._lock:
            res = mt5.order_send(req)
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            log.warning(
                f"modify_sl FAIL #{ticket} retcode:{res.retcode if res else 'None'}"
            )

    def close_partial(self, pos, lot_close: float, atr: float = 0.0) -> None:
        """[FIX-5] close_partial with live ATR-scaled deviation."""
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None:
            return
        info  = mt5.symbol_info(SYMBOL)
        step  = info.volume_step if info else 0.01
        v_min = info.volume_min  if info else 0.01

        lot_close = float(max(
            v_min,
            min(self._risk._round_lot(lot_close, step), pos.volume),
        ))
        is_buy     = (pos.type == mt5.ORDER_TYPE_BUY)
        close_type = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
        price      = tick.bid if is_buy else tick.ask
        dev        = self._risk.dynamic_deviation(atr)

        res = self._send_retry({
            "action":    mt5.TRADE_ACTION_DEAL,
            "symbol":    SYMBOL,
            "volume":    lot_close,
            "type":      close_type,
            "position":  pos.ticket,
            "price":     round(float(price), 2),
            "deviation": dev,
            "magic":     MAGIC_NUMBER,
            "comment":   "V13|PartialTP",
        })
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            log.info(f"💰 Partial #{pos.ticket} Lot:{lot_close:.2f} @ {price:.2f}")

    def close_position_market(self, pos) -> bool:
        """[V13-P2-D] Close a position at market for emergency kill-switch."""
        tick = mt5.symbol_info_tick(SYMBOL)
        info = mt5.symbol_info(SYMBOL)
        if tick is None or info is None:
            return False
        is_buy     = (pos.type == mt5.ORDER_TYPE_BUY)
        close_type = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
        price      = tick.bid if is_buy else tick.ask
        atr_approx = info.point * 100   # fallback if no cached ATR

        req = {
            "action":    mt5.TRADE_ACTION_DEAL,
            "symbol":    SYMBOL,
            "volume":    pos.volume,
            "type":      close_type,
            "position":  pos.ticket,
            "price":     round(float(price), 2),
            "deviation": max(100, self._risk.dynamic_deviation(atr_approx)),
            "magic":     MAGIC_NUMBER,
            "comment":   "V13|KILL",
        }
        res = self._send_retry(req, retries=5)
        ok  = res is not None and res.retcode == mt5.TRADE_RETCODE_DONE
        log.info(
            f"{'✅' if ok else '❌'} Kill-close #{pos.ticket} "
            f"Lot:{pos.volume} @ {price:.2f}"
        )
        return ok

    def cancel_pending_order(self, ticket: int) -> bool:
        """[V13-P2-D] Cancel a pending limit order by ticket."""
        req = {"action": mt5.TRADE_ACTION_REMOVE, "order": ticket}
        with self._lock:
            res = mt5.order_send(req)
        ok = res is not None and res.retcode == mt5.TRADE_RETCODE_DONE
        log.info(f"{'✅' if ok else '❌'} Cancel pending #{ticket}")
        return ok

    def place_order(
        self, setup: SetupResult, session: str = "", dd_mode: str = "NORMAL"
    ) -> bool:
        """Full order placement pipeline. [FIX-8] features persisted to DB."""
        if not self._risk.is_spread_ok() or not self._risk.is_within_risk_limits():
            return False
        if self._risk.has_duplicate_setup(setup.setup_hash, setup.signal):
            log.info(f"🚫 Duplicate {setup.setup_hash} → skip")
            return False

        # [V13-P0-A] Concurrent positions cap
        if self._risk.count_open_positions() >= MAX_CONCURRENT_TRADES:
            log.info(
                f"⚠️ Max concurrent positions reached ({MAX_CONCURRENT_TRADES}) → skip"
            )
            return False

        sp     = self._risk.get_spread_pts()
        sl_pad = self._risk.get_spread_sl_padding()

        if sp > MAX_SPREAD_POINTS:
            setup.score += SCORE_SPREAD_WARN
            setup.reasons.append(f"Spread{sp:.0f}pts ⚠️")

        # M1 confirmation bonus
        rates_m1 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 5)
        if rates_m1 is not None and len(rates_m1) >= 3:
            df_m1 = pd.DataFrame(rates_m1)
            c     = df_m1.iloc[-2]
            body_m1 = abs(float(c["close"]) - float(c["open"]))
            if body_m1 >= setup.atr * MTF_M1_BODY_ATR:
                if (
                    (setup.signal == "BUY"  and c["close"] > c["open"]) or
                    (setup.signal == "SELL" and c["close"] < c["open"])
                ):
                    setup.score += SCORE_M1_CONFIRM
                    setup.reasons.append("M1 ✓")

        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None:
            return False

        sig        = setup.signal
        sl_raw     = setup.sl
        sl_adjusted = (sl_raw - sl_pad) if sig == "BUY" else (sl_raw + sl_pad)
        log.info(f"📏 SL: {sl_raw:.2f}→{sl_adjusted:.2f} (spread={sp:.1f}pts)")

        if setup.use_market or not INTRABAR_ENABLED:
            entry  = tick.ask if sig == "BUY" else tick.bid
            otype  = mt5.ORDER_TYPE_BUY  if sig == "BUY" else mt5.ORDER_TYPE_SELL
            action = mt5.TRADE_ACTION_DEAL
            exp    = 0
        else:
            entry  = setup.entry
            otype  = mt5.ORDER_TYPE_BUY_LIMIT if sig == "BUY" else mt5.ORDER_TYPE_SELL_LIMIT
            action = mt5.TRADE_ACTION_PENDING
            exp    = int(time.time()) + (EXPIRATION_CANDLES * 5 * 60)
            if sig == "BUY" and entry >= tick.ask:
                entry  = tick.ask
                otype  = mt5.ORDER_TYPE_BUY
                action = mt5.TRADE_ACTION_DEAL
                exp    = 0
            elif sig == "SELL" and entry <= tick.bid:
                entry  = tick.bid
                otype  = mt5.ORDER_TYPE_SELL
                action = mt5.TRADE_ACTION_DEAL
                exp    = 0

        risk = abs(entry - sl_adjusted)
        if risk == 0:
            log.error("place_order: risk=0 → abort")
            return False

        tp_full  = (
            entry + risk * RR_RATIO if sig == "BUY"
            else entry - risk * RR_RATIO
        )
        lot_full = self._risk.calculate_lot(
            entry, sl_adjusted, setup.score, sp, setup.atr, dd_mode=dd_mode
        )
        ok, reason = self._risk.validate_order(entry, sl_adjusted, tp_full, lot_full, sig)
        if not ok:
            log.warning(f"⚠️ Validate: {reason}")
            return False

        info   = mt5.symbol_info(SYMBOL)
        v_step = info.volume_step if info else 0.01
        v_min  = info.volume_min  if info else 0.01

        lot_a = max(v_min, self._risk._round_lot(lot_full * PARTIAL_TP_PCT, v_step))
        lot_b = max(v_min, self._risk._round_lot(lot_full - lot_a, v_step))
        if lot_a + lot_b > lot_full + v_step:
            lot_b = max(v_min, self._risk._round_lot(lot_full - lot_a, v_step))

        tp_pt = (
            entry + risk * PARTIAL_TP_RR if sig == "BUY"
            else entry - risk * PARTIAL_TP_RR
        )

        dev = self._risk.dynamic_deviation(setup.atr)
        log.info(f"📐 Deviation: {dev}pts (ATR={setup.atr:.4f})")

        sent = 0
        for lot_i, tp_i, label in [(lot_a, tp_pt, "PT"), (lot_b, tp_full, "FT")]:
            req = {
                "action":    action,
                "symbol":    SYMBOL,
                "volume":    lot_i,
                "type":      otype,
                "price":     round(float(entry), 2),
                "sl":        round(float(sl_adjusted), 2),
                "tp":        round(float(tp_i), 2),
                "deviation": dev,
                "magic":     MAGIC_NUMBER,
                "comment":   f"V13|{sig}|{label}|{setup.score}|{setup.setup_hash}",
            }
            if action == mt5.TRADE_ACTION_PENDING:
                req["type_time"]  = mt5.ORDER_TIME_SPECIFIED
                req["expiration"] = exp

            res = self._send_retry(req)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                sent += 1
                mode_tag = "MKT" if action == mt5.TRADE_ACTION_DEAL else "LMT"
                log.info(
                    f"✅ {label}|{sig}|{mode_tag}|Lot:{lot_i}|"
                    f"E:{entry:.2f}|SL:{sl_adjusted:.2f}|TP:{tp_i:.2f}"
                )
            else:
                log.warning(f"⚠️ {label} order failed")

        if sent > 0:
            mode = "MKT" if action == mt5.TRADE_ACTION_DEAL else "LMT"
            log.info(
                f"📦 {mode}|{sig}|Score:{setup.score}|DD:{dd_mode}|"
                f"Lot:{lot_a}+{lot_b}|WinProb:{setup.win_prob:.2f}|{session}"
            )
            db_log_setup(
                sig, setup.score, entry, sl_adjusted, tp_full,
                setup.setup_hash, session,
                features=setup.features,
                win_prob=setup.win_prob,
            )
            return True
        return False


# ══════════════════════════════════════════════════════════════════════════════
# 🔄  CLASS: PositionManager  [FIX-7 preserved, V13-P0-B DB fix]
# ══════════════════════════════════════════════════════════════════════════════
class PositionManager:
    """
    Background 0.2 s thread: partial TP, breakeven, trailing SL.
    [FIX-7] Batch trail-state loads, deferred DB writes.
    [V13-P0-B] Uses thread-local DB reads — no shared connection conflict.
    """

    def __init__(self, feed: MarketDataFeed, execution: ExecutionHandler):
        self._feed    = feed
        self._exec    = execution
        self._running = threading.Event()
        self._running.set()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._loop, name="PositionManager", daemon=True
        )
        self._thread.start()
        log.info(
            f"🔄 PositionManager started (poll={POSITION_POLL_SEC*1000:.0f}ms)"
        )

    def stop(self) -> None:
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=5)
        log.info("🔄 PositionManager stopped")

    def _loop(self) -> None:
        while self._running.is_set():
            try:
                if mt5.terminal_info() is not None:
                    df_m5 = self._feed.get_cached_m5()
                    atr   = calculate_atr(df_m5) if df_m5 is not None else 1.0
                    self._manage_positions(atr)
            except Exception as exc:
                log.warning(f"⚠️ PositionManager error: {exc}")
            time.sleep(POSITION_POLL_SEC)

    def _manage_positions(self, atr: float) -> None:
        """
        [FIX-3] Hash-based dual-key position tracking.
        [FIX-7] Batch trail-state load; deferred DB writes.
        [V13-P3] continue-after-partial fixed: trailing evaluated independently.
        """
        positions = [
            p for p in (mt5.positions_get(symbol=SYMBOL) or [])
            if p.magic == MAGIC_NUMBER
        ]
        if not positions:
            return

        tick = mt5.symbol_info_tick(SYMBOL)
        info = mt5.symbol_info(SYMBOL)
        if tick is None or info is None:
            return

        a            = max(atr, info.point * 10)
        open_tickets = {p.ticket for p in positions}

        # [FIX-7] Single DB query for all trail states
        trail_cache: Dict[int, sqlite3.Row] = batch_load_trail_states(list(open_tickets))

        for pos in positions:
            entry  = pos.price_open
            sl_now = pos.sl
            is_buy = (pos.type == mt5.ORDER_TYPE_BUY)

            comment_parts = (pos.comment or "").split("|")
            pos_hash = comment_parts[-1] if len(comment_parts) >= 5 else ""

            risk = abs(entry - sl_now)
            if risk < info.point:
                risk = a * 1.5
                log.warning(f"⚠️ #{pos.ticket} SL≈0 → fallback risk={risk:.2f}")

            price    = tick.bid if is_buy else tick.ask
            buf      = info.point * 5
            profit_r = (
                (price - entry) / risk if is_buy
                else (entry - price) / risk
            )

            ts           = trail_cache.get(pos.ticket)
            partial_done = int(ts["partial_done"]) if ts else 0

            # [V13-P3] Evaluate all three steps independently (no early continue
            # that skips later steps when partial fires at the same tick as trail).

            # Step 1: Partial TP
            did_partial = False
            if not partial_done and profit_r >= PARTIAL_TP_RR:
                self._exec.close_partial(pos, pos.volume * PARTIAL_TP_PCT, atr=a)
                set_partial_done(pos.ticket, pos_hash)
                be_sl = (entry + buf) if is_buy else (entry - buf)
                if (is_buy and sl_now < be_sl) or (not is_buy and sl_now > be_sl):
                    self._exec.modify_sl(pos.ticket, be_sl)
                    log.info(
                        f"🔒 BE+Partial #{pos.ticket} "
                        f"SL:{sl_now:.2f}→{be_sl:.2f} R:{profit_r:.2f}"
                    )
                did_partial = True

            # Step 2: Breakeven (only if we didn't just do partial — avoid double modify)
            if not did_partial and profit_r >= BREAKEVEN_RR:
                be_sl = (entry + buf) if is_buy else (entry - buf)
                if (is_buy and sl_now < be_sl) or (not is_buy and sl_now > be_sl):
                    self._exec.modify_sl(pos.ticket, be_sl)
                    log.info(
                        f"🔒 BE #{pos.ticket} SL:{sl_now:.2f}→{be_sl:.2f}"
                    )

            # Step 3: Trailing SL — runs independently of partial/BE
            if profit_r >= TRAIL_AFTER_RR:
                last_tsl = float(ts["last_sl"]) if ts else None
                min_move = a * TRAIL_MIN_MOVE_ATR

                if is_buy:
                    new_tsl = price - (a * TRAIL_ATR_MULT)
                    if (
                        new_tsl > sl_now and
                        (last_tsl is None or new_tsl > last_tsl + min_move)
                    ):
                        self._exec.modify_sl(pos.ticket, new_tsl)
                        save_trail_sl(pos.ticket, new_tsl, pos_hash)
                        log.info(
                            f"📈 Trail #{pos.ticket} "
                            f"SL:{sl_now:.2f}→{new_tsl:.2f} R:{profit_r:.2f}"
                        )
                else:
                    new_tsl = price + (a * TRAIL_ATR_MULT)
                    if (
                        new_tsl < sl_now and
                        (last_tsl is None or new_tsl < last_tsl - min_move)
                    ):
                        self._exec.modify_sl(pos.ticket, new_tsl)
                        save_trail_sl(pos.ticket, new_tsl, pos_hash)
                        log.info(
                            f"📉 Trail #{pos.ticket} "
                            f"SL:{sl_now:.2f}→{new_tsl:.2f} R:{profit_r:.2f}"
                        )

        cleanup_trail_state(open_tickets)


# ══════════════════════════════════════════════════════════════════════════════
# 🆘  EMERGENCY KILL-SWITCH  [V13-P2-D]
# ══════════════════════════════════════════════════════════════════════════════

def graceful_shutdown(execution: ExecutionHandler, reason: str = "KILL") -> None:
    """
    [V13-P2-D] Emergency kill-switch procedure:
      1. Cancel all pending limit orders (bot-managed only).
      2. Close all open positions at market price.
      3. Log final equity.

    Triggered by:
      - KILL.flag file present (checked every poll cycle)
      - KeyboardInterrupt (Ctrl+C)
      - SIGTERM signal
    """
    log.warning(f"🚨 GRACEFUL SHUTDOWN initiated — reason: {reason}")
    log.warning("🚨 Step 1/3: Cancelling all pending limit orders...")

    pending = mt5.orders_get(symbol=SYMBOL) or []
    for o in pending:
        if o.magic == MAGIC_NUMBER:
            execution.cancel_pending_order(o.ticket)

    time.sleep(0.5)

    log.warning("🚨 Step 2/3: Closing all open positions at market...")
    positions = mt5.positions_get(symbol=SYMBOL) or []
    for pos in positions:
        if pos.magic == MAGIC_NUMBER:
            execution.close_position_market(pos)
            time.sleep(0.2)   # brief pause between closes

    time.sleep(1.0)

    acct = mt5.account_info()
    if acct is not None:
        log.warning(
            f"🚨 Step 3/3: Final equity = ${acct.equity:,.2f} "
            f"(balance = ${acct.balance:,.2f})"
        )

    log.warning("🚨 SHUTDOWN COMPLETE — bot terminated.")


# ══════════════════════════════════════════════════════════════════════════════
# 📊  OPERATOR HEARTBEAT  [V13-P2-A]
# ══════════════════════════════════════════════════════════════════════════════

def emit_heartbeat(
    risk: RiskManager,
    predictor: MLPredictor,
    session: str,
    htf_bias: str,
    adr_pct: float,
) -> None:
    """
    [V13-P2-A] Structured status log emitted every HEARTBEAT_SEC.
    Gives human operator a complete situational snapshot in one line.
    """
    acct = mt5.account_info()
    if acct is None:
        return

    daily_dd, total_dd, dd_mode = risk.get_dd_state()

    init_bal    = get_state("initial_balance") or acct.balance
    equity_pct  = (acct.equity - init_bal) / init_bal * 100 if init_bal > 0 else 0

    open_pos    = risk.count_open_positions()
    avg_wp      = predictor.rolling_avg_prob

    today_key   = "daily_start_balance_" + risk.get_broker_date()
    day_start   = get_state(today_key) or acct.balance
    today_pl    = acct.equity - day_start

    pause_active = os.path.isfile(PAUSE_FLAG_PATH)
    kill_active  = os.path.isfile(KILL_FLAG_PATH)

    mode_label = dd_mode
    if kill_active:
        mode_label = "🔴 KILL DETECTED"
    elif pause_active:
        mode_label = "⏸️  PAUSED"
    elif dd_mode == "ORANGE":
        mode_label = "🟠 ORANGE — entries suspended"
    elif dd_mode == "YELLOW":
        mode_label = "💛 YELLOW — reduced risk"
    elif dd_mode == "RED":
        mode_label = "🔴 RED — circuit breaker"

    norm_status = "🟢 WARM" if predictor.norm_is_warm else "🟡 COLD-START"

    log.info(
        f"{'═'*72}\n"
        f"  📊  OPERATOR STATUS HEARTBEAT\n"
        f"  {'─'*68}\n"
        f"  Equity   : ${acct.equity:>10,.2f}  ({equity_pct:+.2f}%)\n"
        f"  Today P&L: ${today_pl:>+10,.2f}\n"
        f"  Daily DD : {daily_dd:.2f}%   Total DD: {total_dd:.2f}%\n"
        f"  Session  : {session:<16}  HTF: {htf_bias:<10}  ADR: {adr_pct*100:.0f}%\n"
        f"  OpenPos  : {open_pos}  /  {MAX_CONCURRENT_TRADES} max\n"
        f"  ML Norm  : {norm_status}  |  60-trade avg WinProb: {avg_wp:.3f}\n"
        f"  Mode     : {mode_label}\n"
        f"  {'═'*68}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 🔧  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _make_hash(sig: str, entry: float, sl: float, ts: float) -> str:
    raw = f"{sig}:{entry:.2f}:{sl:.2f}:{int(ts)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def mt5_connect(retries: int = 10, delay: float = 5.0) -> bool:
    for i in range(1, retries + 1):
        if mt5.initialize():
            log.info(f"✅ MT5 connected (try {i})")
            return True
        log.warning(f"MT5 connect try {i}/{retries}…")
        time.sleep(delay)
    return False


def mt5_alive() -> bool:
    return mt5.terminal_info() is not None


def ensure_alive() -> bool:
    if mt5_alive():
        return True
    log.warning("MT5 disconnected → reconnecting…")
    return mt5_connect(retries=5, delay=3.0)


# ══════════════════════════════════════════════════════════════════════════════
# 🚀  SIGNAL CYCLE
# ══════════════════════════════════════════════════════════════════════════════

def _run_signal_cycle(
    feed:          "MarketDataFeed",
    signal_engine: "SMCSignalEngine",
    risk:          "RiskManager",
    execution:     "ExecutionHandler",
    predictor:     "MLPredictor",
    last_htf:      Dict[str, str],   # mutable dict for heartbeat state sharing
) -> None:
    """
    One full signal evaluation cycle.
    Called on new M5 candle AND on significant intrabar move.
    All gates checked identically regardless of trigger path.
    """
    # GATE 1: Connection
    if not ensure_alive():
        log.error("Reconnect failed → skip cycle")
        return

    # GATE 2: Drawdown / risk limits
    daily_dd, total_dd, dd_mode = risk.get_dd_state()
    if dd_mode == "RED":
        log.warning(
            f"⛔ DD limit | daily={daily_dd:.2f}% total={total_dd:.2f}% → halting"
        )
        return

    # GATE 3: Circuit Breaker
    if risk.is_circuit_breaker_tripped():
        log.warning("⚡ Circuit Breaker → no new orders")
        return

    # GATE 4: Session
    session = signal_engine.get_session()
    if session in ("OUT_OF_SESSION", "RED_NEWS_BLOCK"):
        return

    # GATE 5: Killzone
    in_kz, kz_name = signal_engine.is_in_killzone()
    if not in_kz:
        return

    # GATE 6: Hard spread
    if not risk.is_spread_ok():
        log.warning("⚠️ Spread > HARD_BLOCK → skip")
        return

    # GATE 7: PAUSE flag [V13-P2-E]
    if os.path.isfile(PAUSE_FLAG_PATH):
        log.info("⏸️  PAUSE.flag detected — skipping new entry evaluation")
        return

    # GATE 8: Orange DD (entries suspended)
    if not risk.new_entries_allowed():
        log.warning(
            f"🟠 DD ORANGE ({daily_dd:.2f}%) → new entries suspended; "
            "PositionManager continues"
        )
        return

    # Fetch data
    data = feed.fetch_all()
    if data["m5"] is None:
        log.warning("M5 unavailable → skip cycle")
        return

    cleanup_cooldowns()

    setup = signal_engine.analyze_setup(
        data["m5"], data["h1"], data["d1"], data["m15"], session,
    )
    setup.spread_pts = risk.get_spread_pts()

    # Update heartbeat state
    last_htf["bias"]    = setup.htf_bias
    last_htf["session"] = session
    last_htf["adr_pct"] = str(setup.adr_pct)

    # Market context log
    liq = setup.liq_map
    if liq:
        gap_info = ""
        if liq.gap_swept_high:
            gap_info += f" | GapSwH:{liq.gap_swept_high:.2f}"
        if liq.gap_swept_low:
            gap_info += f" | GapSwL:{liq.gap_swept_low:.2f}"
        log.info(
            f"💧 BSL:{liq.bsl_nearest or '—'} SSL:{liq.ssl_nearest or '—'} "
            f"SwH:{liq.swept_high} SwL:{liq.swept_low}{gap_info}"
        )

    htf = setup.htf_result
    if htf:
        log.info(
            f"🏗️  HTF | Bias:{htf.bias} BOS:{htf.last_bos} "
            f"CHOCH:{htf.choch_signal} | {htf.reason}"
        )

    log.info(
        f"📊 Sess:{session} KZ:{kz_name} | "
        f"M15:{setup.m15_struct} | ADR:{setup.adr_pct*100:.0f}% | "
        f"Threshold:{setup.threshold} | DD:{dd_mode}"
    )

    if setup.signal == "WAIT":
        return

    if setup.score < setup.threshold:
        log.info(f"⚠️ Score {setup.score} < {setup.threshold} → skip")
        return

    # Extract normalised features [V13-P0-C]
    close_price = float(data["m5"]["close"].iloc[-1]) if data["m5"] is not None else 2000.0
    setup.features = extract_features(setup, close_price=close_price)

    # Win-probability gate
    setup.win_prob = predictor.predict_win_probability(setup.features)
    avg_wp = predictor.rolling_avg_prob
    norm_tag = "WARM" if predictor.norm_is_warm else "COLD"

    # [V13-P2-B] Log with rolling context
    log.info(
        f"🧠 ML WinProb: {setup.win_prob:.3f} "
        f"[60-trade avg:{avg_wp:.3f}] "
        f"(threshold:{ML_WIN_PROB_THRESHOLD}) "
        f"Norm:{norm_tag} | {setup.summary()}"
    )

    if setup.win_prob < ML_WIN_PROB_THRESHOLD:
        log.info(
            f"🤖 ML gate rejected: prob={setup.win_prob:.3f} "
            f"< {ML_WIN_PROB_THRESHOLD}"
        )
        return

    # Cooldown / duplicate guard
    if is_on_cooldown(setup.setup_hash):
        log.info(f"🔁 Cooldown ({setup.setup_hash}) → skip")
        return
    if risk.has_duplicate_setup(setup.setup_hash, setup.signal):
        log.info(f"🚫 Duplicate → skip")
        return

    # Execute
    if execution.place_order(setup, session, dd_mode=dd_mode):
        set_cooldown(setup.setup_hash)
        log.info(f"🎯 Placed | hash:{setup.setup_hash} DD:{dd_mode}")


# ══════════════════════════════════════════════════════════════════════════════
# 🚀  MAIN
# ══════════════════════════════════════════════════════════════════════════════

BANNER = """
╔══════════════════════════════════════════════════════════════════════════════╗
║  🚀  AI SMC/ICT Pro Sniper — V.13 PRODUCTION                                ║
║  [V13-P0-A] V.12 params live  [V13-P0-B] Thread-local SQLite + writer queue ║
║  [V13-P0-C] 12-feat stationary ML / dynamic z-score normaliser              ║
║  [V13-P1]   M15 BOS rebuilt · OB freshness · gap-sweep detection            ║
║  [V13-P2]   Heartbeat · DD 3-tier · PAUSE/KILL flags · WinProb context      ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""


def main() -> None:
    print(BANNER)
    log.info("Bot V.13 PRODUCTION starting")
    init_db()

    if not mt5_connect():
        log.error("❌ Cannot connect to MT5")
        return

    feed          = MarketDataFeed()
    signal_engine = SMCSignalEngine()
    risk          = RiskManager()
    execution     = ExecutionHandler(risk)
    predictor     = MLPredictor()
    # Uncomment to load a real trained model:
    # predictor.load_model("smc_model.joblib")

    pm = PositionManager(feed, execution)
    pm.start()

    # Shared mutable dict for heartbeat state (written by signal cycle)
    last_htf: Dict[str, str] = {
        "bias":    "NEUTRAL",
        "session": "UNKNOWN",
        "adr_pct": "0.0",
    }

    # [V13-P2-D] SIGTERM handler → graceful shutdown
    _shutdown_requested = threading.Event()

    def _sig_handler(signum, frame):
        log.warning(f"Signal {signum} received → requesting shutdown")
        _shutdown_requested.set()

    signal.signal(signal.SIGTERM, _sig_handler)
    signal.signal(signal.SIGINT,  _sig_handler)

    last_seen_bar_time: Optional[int] = None
    last_eval_price:    float         = 0.0
    cached_atr:         float         = 1.0
    last_heartbeat:     float         = time.time()

    log.info(
        f"📡 Tick poll: {TICK_POLL_SEC:.1f}s | "
        f"Intrabar: {INTRABAR_TICK_MOVE_ATR}×ATR | "
        f"PM: {POSITION_POLL_SEC*1000:.0f}ms | "
        f"Heartbeat: {HEARTBEAT_SEC}s"
    )
    log.info(
        f"📁 Kill-switch: '{KILL_FLAG_PATH}' | "
        f"Pause: '{PAUSE_FLAG_PATH}'"
    )

    try:
        while not _shutdown_requested.is_set():

            # [V13-P2-D] Check KILL flag every poll cycle
            if os.path.isfile(KILL_FLAG_PATH):
                log.warning("🚨 KILL.flag detected!")
                _shutdown_requested.set()
                break

            current_bar_time = feed.get_current_m5_bar_time()
            tick             = mt5.symbol_info_tick(SYMBOL)

            if tick is None:
                time.sleep(TICK_POLL_SEC)
                continue

            current_bid = tick.bid

            # ── Trigger A: New M5 candle ──────────────────────────────────────
            new_candle = (
                current_bar_time is not None
                and current_bar_time != last_seen_bar_time
            )
            if new_candle:
                log.info("─" * 72)
                log.info(
                    f"🕯️  New M5 candle @ {current_bar_time} "
                    f"[{datetime.now(bkk_tz).strftime('%H:%M:%S')} BKK]"
                )
                last_seen_bar_time = current_bar_time
                _run_signal_cycle(
                    feed, signal_engine, risk, execution, predictor, last_htf
                )
                df_m5_cache = feed.get_cached_m5()
                if df_m5_cache is not None:
                    new_atr = calculate_atr(df_m5_cache)
                    if new_atr > 0:
                        cached_atr = new_atr
                last_eval_price = current_bid
                time.sleep(TICK_POLL_SEC)

                # [V13-P2-A] Heartbeat check after candle cycle
                now = time.time()
                if now - last_heartbeat >= HEARTBEAT_SEC:
                    emit_heartbeat(
                        risk, predictor,
                        last_htf.get("session", "UNKNOWN"),
                        last_htf.get("bias", "NEUTRAL"),
                        float(last_htf.get("adr_pct", "0")),
                    )
                    last_heartbeat = now
                continue

            # ── Trigger B: Significant intrabar move ──────────────────────────
            if INTRABAR_ENABLED and last_eval_price > 0:
                move          = abs(current_bid - last_eval_price)
                threshold_move = INTRABAR_TICK_MOVE_ATR * cached_atr
                if move >= threshold_move:
                    log.info(
                        f"⚡ Intrabar move {move:.2f} ≥ {threshold_move:.2f} "
                        f"({INTRABAR_TICK_MOVE_ATR}×ATR) → evaluate"
                    )
                    _run_signal_cycle(
                        feed, signal_engine, risk, execution, predictor, last_htf
                    )
                    last_eval_price = current_bid

            # [V13-P2-A] Heartbeat on quiet periods too
            now = time.time()
            if now - last_heartbeat >= HEARTBEAT_SEC:
                emit_heartbeat(
                    risk, predictor,
                    last_htf.get("session", "UNKNOWN"),
                    last_htf.get("bias", "NEUTRAL"),
                    float(last_htf.get("adr_pct", "0")),
                )
                last_heartbeat = now

            time.sleep(TICK_POLL_SEC)

    except KeyboardInterrupt:
        log.info("🛑 KeyboardInterrupt received")
    except Exception as exc:
        log.exception(f"💥 Unhandled exception: {exc}")
    finally:
        log.info("Initiating graceful shutdown sequence…")
        pm.stop()
        graceful_shutdown(execution, reason="MAIN_EXIT")
        close_db()
        mt5.shutdown()
        log.info("MT5 offline. Bot V.13 terminated.")


# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    main()
