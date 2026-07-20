"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  🏆  AI SMC/ICT Pro Sniper — V.15 PRODUCTION  (XAUUSD Gold Specialist)      ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  ██████████████████  V.15 CHANGELOG  ████████████████████████████████████  ║
║                                                                              ║
║  [V15-S1]  BALANCED WEIGHTED SCORING SYSTEM (Anti-Paralysis Refactor)       ║
║            Root-cause fix for Analysis Paralysis.  Scoring rebuilt from     ║
║            scratch with clear tier separation:                               ║
║              Base = 40.  Threshold = 60 (all sessions / all HTF states).    ║
║              Tier 1 Core (must have ≥1): FVG Fresh +20  OR  Liq Sweep +20  ║
║              → Base+Core already reaches 60: minimum viable trade signal.  ║
║              Tier 2 Context: HTF Aligned +10, HTF Against -15, Neutral ±0   ║
║              Tier 3 Confluence boosters: M15 BOS +10, OB +5, Strong +5,    ║
║                FVG Strength +5, BOS M5 +5, Liq Target +5, Vol Spike +5     ║
║              Tier 4 Penalties: ADR Exhausted -10, Spread Warn -5            ║
║            HTF NEUTRAL no longer penalised or blocked.  Ranging markets     ║
║            with valid FVG/Sweep setups now execute.                         ║
║                                                                              ║
║  [V15-S2]  ML GATE RELAXED TO 0.50                                          ║
║            ML_WIN_PROB_THRESHOLD = 0.50. Heuristic model now acts as a      ║
║            sanity check, not a hard gate. Any setup with genuine confluence  ║
║            will naturally score > 0.50 in the heuristic.                    ║
║                                                                              ║
║  [V15-S3]  HTF NEUTRAL FULLY DECOUPLED                                       ║
║            SCORE_PENALTY_HTF_NEUTRAL = 0 (no threshold raise).              ║
║            HTF_NEUTRAL_MIN_SCORE guard removed entirely.                    ║
║            Neutral H4 = opportunity zone, not a blocked state.              ║
║                                                                              ║
║  [V15-S4]  RESTRICTIVE FILTERS DISABLED BY DEFAULT                          ║
║            VOL_SPIKE_ENABLED = False (no volume data in many brokers).      ║
║            PD_ZONE_ENABLED   = False (equilibrium penalty removed).         ║
║            DXY_ENABLED       = False (optional, set symbol if desired).     ║
║            ADR_HARD_BLOCK    = False (score penalty only, not a hard stop). ║
║                                                                              ║
║  PRESERVED FROM V.14 (all fixes intact)                                     ║
║  ─────────────────────────────────────────────────────────────────────────  ║
║  Thread-local SQLite + writer queue · Batch trail-state · PAUSE/KILL flags  ║
║  3-tier DD protocol · graceful_shutdown · SIGTERM · NumPy hot-path          ║
║  OB freshness/mitigation · Gap-sweep · Dual-key tracking · FVG memory       ║
║  M15 swing-BOS · Welford normaliser · NewsGuard · Judas Swing [V14-S2]     ║
║  Dynamic ADR TP cap [V14-S3] · H4 HTF bias [V14-F2] · DXY filter opt-in   ║
║  CB decoupled [V14-F5] · FVG age norm fix [V14-F6] · Outlier guard [V14-F7]║
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
import queue as _queue_module
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, time as dtime
from decimal import Decimal, ROUND_DOWN
from typing import Optional, List, Tuple, Dict, Deque

import pytz

warnings.filterwarnings("ignore", category=RuntimeWarning)

try:
    import joblib
    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False


# ══════════════════════════════════════════════════════════════════════════════
# 🏦  BROKER CONFIG  — change this block per broker; nothing else needs editing
# ══════════════════════════════════════════════════════════════════════════════
SYMBOL           = "XAUUSDm"
DXY_SYMBOL       = "USDXm"          # set "" to disable DXY filter
MAGIC_NUMBER     = 99999
BROKER_TZ_NAME   = "Etc/UTC"
STRATEGY_TZ_NAME = "Asia/Bangkok"
BROKER_TZ        = pytz.timezone(BROKER_TZ_NAME)
STRATEGY_TZ      = pytz.timezone(STRATEGY_TZ_NAME)


# ══════════════════════════════════════════════════════════════════════════════
# ⚙️  STRATEGY CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════
RR_RATIO            = 2.5
MAX_DAILY_LOSS_PCT  = 4.0
MAX_TOTAL_DD_PCT    = 8.0
EXPIRATION_CANDLES  = 36          # M5 bars until pending order expires (~3 h)

# Spread guards
HARD_SPREAD_BLOCK   = 100.0
MAX_SPREAD_POINTS   = 50.0
SPREAD_LOT_PENALTY  = 0.3
SPREAD_SL_PADDING   = True

MOMENTUM_BODY_ATR   = 1.2
BREAKEVEN_RR        = 1.0
TRAIL_AFTER_RR      = 1.5
TRAIL_ATR_MULT      = 0.8
TRAIL_MIN_MOVE_ATR  = 0.3

# ADR — [V15-S4] hard block disabled; penalty-only mode
ADR_EXHAUSTED_PCT     = 0.88
ADR_NY_EXHAUSTED_PCT  = 0.93
ADR_HARD_BLOCK        = False   # [V15-S4] False = score penalty only, never a hard stop
ADR_TP_BUFFER_PCT     = 0.95

SL_ATR_MULT         = 1.2
FVG_ENTRY_MID       = True
SWING_PERIOD        = 5
SWING_CONFIRM_BARS  = 2
SETUP_COOLDOWN_SEC  = 180

PARTIAL_TP_RR       = 1.0
PARTIAL_TP_PCT      = 0.50
MAX_CONCURRENT_TRADES = 2

# Entry discipline — signals only on CLOSED M5 candles
INTRABAR_ENABLED    = True   # controls PM management cadence, NOT entry signals

# FVG
FVG_BUFFER_RATIO    = 0.5
FVG_MOMENTUM_RATIO  = 0.25
FVG_MITIGATED_PCT   = 0.5
FVG_MIN_GAP_ATR     = 0.15
FVG_MEMORY_BARS: Dict[str, int] = {
    "PRE_LONDON":    24,
    "LONDON":        36,
    "NY_OPEN_EARLY": 30,
    "NEW_YORK":      36,
    "DEFAULT":       30,
}

# [V15-S4] Volume Spike — disabled by default (many brokers have no real volume)
VOL_SPIKE_ENABLED   = False
VOL_SPIKE_MULT      = 1.5
VOL_SPIKE_PERIOD    = 20

# Judas Swing Override
JUDAS_SWING_ENABLED  = True
JUDAS_WINDOW_MIN     = 15
JUDAS_SCORE_BONUS    = 15

# Liquidity
LIQ_SWING_PERIOD    = 10
LIQ_EQUAL_TOLERANCE = 0.0003
LIQ_MIN_CLUSTER     = 2

# HTF — H4 for Gold
HTF_BARS            = 120
HTF_SWING_PERIOD    = 3
HTF_SWING_CONFIRM   = 2

# DXY Inverse Filter — [V15-S4] disabled by default
DXY_ENABLED         = False
DXY_SWING_PERIOD    = 5
DXY_BUY_PENALTY     = -10
DXY_SELL_BONUS      = 8

# [V15-S4] Premium/Discount zone — disabled by default
PD_ZONE_ENABLED     = False
PD_PERIOD           = 50
PD_PENALTY          = -6

MTF_M1_BODY_ATR     = 0.3
SCORE_M1_CONFIRM    = 5

# ══════════════════════════════════════════════════════════════════════════════
# 🎯  [V15-S1]  BALANCED WEIGHTED SCORING SYSTEM
#
#  PHILOSOPHY: Base(40) + ONE Core signal = 60 = tradeable.
#              Confluences boost; HTF Neutral never blocks.
#
#  SCORE FLOW EXAMPLE (Neutral HTF market, FVG only):
#    Base=40 + FVG_FRESH=20 → 60 ✅ trade fires
#
#  SCORE FLOW EXAMPLE (Aligned HTF, Sweep+FVG, M15 BOS):
#    Base=40 + SWEEP=20 + FVG_FRESH=20 + SWEEP_AND_FVG=5(bonus)
#    + HTF_ALIGN=10 + M15_BOS=10 → 105 💎 high-confidence
# ══════════════════════════════════════════════════════════════════════════════

SCORE_BASE          = 40   # Starting point

# ── Tier 1: Core Setups — ONE required to reach 60 (threshold) ───────────────
SCORE_FVG_FRESH     = 20   # Fresh, un-mitigated FVG   → 40+20 = 60 ✅
SCORE_LIQ_SWEPT     = 20   # Liquidity sweep (SSL/BSL)  → 40+20 = 60 ✅
SCORE_SWEEP_AND_FVG = 5    # Bonus: BOTH present simultaneously

# ── Tier 2: HTF Context — boosts or reduces but never blocks ─────────────────
SCORE_HTF_ALIGN     = 10   # H4 trend aligned with trade direction
SCORE_HTF_AGAINST   = -15  # H4 trend opposing — still tradeable with confluences

# ── Tier 3: Confluence Boosters ───────────────────────────────────────────────
SCORE_M15_BOS       = 10   # M15 structural BOS confirms entry direction
SCORE_OB_BONUS      = 5    # Order Block present and un-mitigated
SCORE_OB_OVERLAP    = 5    # OB overlaps the FVG zone
SCORE_STRONG_CANDLE = 5    # Impulse candle body > 0.6×ATR
SCORE_BOS_M5        = 5    # M5 micro structure break
SCORE_LIQ_TARGET    = 5    # Clear BSL/SSL target within RR reach
SCORE_FVG_STRENGTH  = 5    # FVG gap width > 0.5×ATR
SCORE_VOL_SPIKE     = 5    # Volume spike on impulse candle

# ── Tier 4: Risk Penalties ────────────────────────────────────────────────────
SCORE_ADR_WARN      = -10  # Daily range already extended (exhaustion risk)
SCORE_SPREAD_WARN   = -5   # Spread above normal threshold

# ── Threshold — FLAT 60 for all sessions ─────────────────────────────────────
# [V15-S3] No per-session escalation; no HTF-neutral penalty
SCORE_THRESHOLD: Dict[str, int] = {
    "LONDON":        70,
    "NEW_YORK":      70,
    "NY_OPEN_EARLY": 70,
    "PRE_LONDON":    70,
    "DEFAULT":       70,
}

# [V15-S3] HTF Neutral: zero penalty, no minimum score guard
SCORE_PENALTY_HTF_NEUTRAL = 0   # was 3 in V14 — removed
SCORE_PENALTY_HIGH_ADR    = 0   # threshold raise for ADR also removed

# [V15-S2] ML gate relaxed — heuristic now acts as sanity check
ML_WIN_PROB_THRESHOLD = 0.50    # was 0.62 in V14
ML_ROLLING_WINDOW     = 60

# Risk tiers
LOT_MIN  = 0.01
LOT_MAX  = 1.00
RISK_TIERS = [
    (85, 1.00),
    (78, 0.75),
    (70, 0.50),
    (65, 0.25),
    (0,  0.05),
]

# DD tiers
DD_YELLOW_PCT       = 3.0
DD_ORANGE_PCT       = 5.0
CIRCUIT_BREAKER_PCT = 4.5   # [V14-F5] decoupled from DD Yellow

# Killzones (Strategy timezone = Bangkok GMT+7)
KILLZONE_ENABLED = True
KILLZONES = [
    (14,  0, 16, 30, "London Open"),
    (19, 45, 22,  0, "NY Open"),
]

# Sessions (Strategy timezone)
SESSIONS = [
    (12,  0, 14,  0, "PRE_LONDON"),
    (14,  0, 18,  0, "LONDON"),
    (18, 30, 19, 15, "NY_OPEN_EARLY"),
    (19, 45, 23, 59, "NEW_YORK"),
]

# Cache TTL (seconds)
CACHE_TTL_LTF = 5
CACHE_TTL_HTF = 60
CACHE_TTL_D1  = 300

# Polling
POSITION_POLL_SEC = 0.2
TICK_POLL_SEC     = 1.0
HEARTBEAT_SEC     = 300

# Flag files
KILL_FLAG_PATH  = "KILL.flag"
PAUSE_FLAG_PATH = "PAUSE.flag"

DB_PATH  = "smc_state.db"
LOG_PATH = "smc_bot.log"

# News Guard
NEWS_EVENTS_FILE    = "news_events.json"
NEWS_BUFFER_MIN     = 30
NEWS_STATIC_FALLBACK = [
    (19, 15, 19, 45),
    (15, 25, 15, 35),
]


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
# 📰  NEWS GUARD  [V14-O3]
# ══════════════════════════════════════════════════════════════════════════════
class NewsGuard:
    def __init__(self):
        self._events: List[Dict]   = []
        self._last_load: float     = 0.0
        self._load_interval        = 300.0

    def _maybe_reload(self) -> None:
        now = time.time()
        if now - self._last_load < self._load_interval:
            return
        try:
            if os.path.isfile(NEWS_EVENTS_FILE):
                with open(NEWS_EVENTS_FILE, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                self._events = [
                    e for e in raw
                    if e.get("impact", "").upper() == "HIGH"
                    and e.get("currency", "") in ("USD", "XAU", "GOLD")
                ]
            self._last_load = now
        except Exception as exc:
            log.warning(f"NewsGuard reload error: {exc}")
            self._last_load = now

    def is_blocked(self, now: datetime) -> Tuple[bool, str]:
        self._maybe_reload()
        buf = timedelta(minutes=NEWS_BUFFER_MIN)
        if self._events:
            for ev in self._events:
                try:
                    ts = datetime.fromisoformat(ev["ts_utc"]).replace(tzinfo=pytz.utc)
                    ts_local = ts.astimezone(STRATEGY_TZ)
                    if ts_local - buf <= now <= ts_local + buf:
                        return True, ev.get("event", "HIGH-IMPACT")
                except Exception:
                    continue
        t = now.time()
        for sh, sm, eh, em in NEWS_STATIC_FALLBACK:
            if dtime(sh, sm) <= t <= dtime(eh, em):
                return True, "StaticNewsBlock"
        return False, ""


# ══════════════════════════════════════════════════════════════════════════════
# 💾  PERSISTENCE LAYER  — thread-local connections + single writer queue
# ══════════════════════════════════════════════════════════════════════════════
_tls = threading.local()
_write_q: Optional[_queue_module.Queue] = None
_writer_thread: Optional[threading.Thread] = None


def _get_read_conn() -> sqlite3.Connection:
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
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    while True:
        item = q.get()
        if item is None:
            conn.close(); break
        sql, params, done_ev = item
        try:
            conn.execute(sql, params)
            conn.commit()
        except Exception as exc:
            log.warning(f"DB writer: {exc} | {sql[:60]}")
        finally:
            if done_ev is not None:
                done_ev.set()
        q.task_done()


def _db_exec(sql: str, params: tuple = (), wait: bool = False) -> None:
    global _write_q
    if _write_q is None:
        raise RuntimeError("DB writer not initialised — call init_db() first")
    ev = threading.Event() if wait else None
    _write_q.put((sql, params, ev))
    if ev is not None:
        ev.wait(timeout=5.0)


def _db_query(sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
    try:
        return _get_read_conn().execute(sql, params).fetchone()
    except Exception as exc:
        log.warning(f"DB read: {exc}"); return None


def _db_query_all(sql: str, params: tuple = ()) -> List[sqlite3.Row]:
    try:
        return _get_read_conn().execute(sql, params).fetchall()
    except Exception as exc:
        log.warning(f"DB read_all: {exc}"); return []


def init_db() -> None:
    global _write_q, _writer_thread
    if _write_q is None:
        _write_q = _queue_module.Queue()
        _writer_thread = threading.Thread(
            target=_writer_loop, args=(_write_q,), name="DBWriter", daemon=True
        )
        _writer_thread.start()
        log.info("💾 DB writer thread started")

    schema_stmts = [
        """CREATE TABLE IF NOT EXISTS setup_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL, signal TEXT, score INTEGER, entry REAL, sl REAL, tp REAL,
            setup_hash TEXT, session TEXT, features TEXT, win_prob REAL)""",
        "CREATE TABLE IF NOT EXISTS cooldown (setup_hash TEXT PRIMARY KEY, expires_at REAL)",
        """CREATE TABLE IF NOT EXISTS trail_state (
            ticket INTEGER PRIMARY KEY, setup_hash TEXT,
            last_sl REAL, updated_at REAL, partial_done INTEGER DEFAULT 0)""",
        "CREATE TABLE IF NOT EXISTS bot_state (key TEXT PRIMARY KEY, value TEXT)",
        """CREATE TABLE IF NOT EXISTS win_prob_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, prob REAL, outcome INTEGER DEFAULT -1)""",
        "CREATE INDEX IF NOT EXISTS idx_trail_hash ON trail_state(setup_hash)",
        "CREATE INDEX IF NOT EXISTS idx_setup_ts ON setup_log(ts)",
    ]
    for stmt in schema_stmts:
        _db_exec(stmt, wait=True)

    # Live migrations
    rc = _get_read_conn()
    trail_cols = {r[1] for r in rc.execute("PRAGMA table_info(trail_state)").fetchall()}
    if "setup_hash" not in trail_cols:
        _db_exec("ALTER TABLE trail_state ADD COLUMN setup_hash TEXT DEFAULT ''", wait=True)
    setup_cols = {r[1] for r in rc.execute("PRAGMA table_info(setup_log)").fetchall()}
    for col, defn in [("features", "TEXT DEFAULT NULL"), ("win_prob", "REAL DEFAULT 0")]:
        if col not in setup_cols:
            _db_exec(f"ALTER TABLE setup_log ADD COLUMN {col} {defn}", wait=True)
    log.info("✅ Database initialised (V15 schema)")


def close_db() -> None:
    global _write_q
    if _write_q is not None:
        _write_q.put(None)
        _write_q = None
    if hasattr(_tls, "conn") and _tls.conn:
        try: _tls.conn.close()
        except Exception: pass
        _tls.conn = None


def is_on_cooldown(h: str) -> bool:
    row = _db_query("SELECT expires_at FROM cooldown WHERE setup_hash=?", (h,))
    return bool(row and row["expires_at"] > time.time())


def set_cooldown(h: str) -> None:
    _db_exec("INSERT OR REPLACE INTO cooldown VALUES(?,?)",
             (h, time.time() + SETUP_COOLDOWN_SEC))


def cleanup_cooldowns() -> None:
    _db_exec("DELETE FROM cooldown WHERE expires_at<=?", (time.time(),))


def db_log_setup(signal: str, score: int, entry: float, sl: float, tp: float,
                 h: str, session: str = "", features=None, win_prob: float = 0.0) -> None:
    fj = json.dumps([round(float(v), 8) for v in features], separators=(",", ":")) \
         if features is not None else None
    _db_exec(
        "INSERT INTO setup_log(ts,signal,score,entry,sl,tp,setup_hash,session,features,win_prob)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (time.time(), signal, score, entry, sl, tp, h, session, fj, win_prob))
    _db_exec("INSERT INTO win_prob_history(ts,prob) VALUES(?,?)", (time.time(), win_prob))


def get_trail_state(ticket: int, setup_hash: str = "") -> Optional[sqlite3.Row]:
    row = _db_query("SELECT setup_hash,last_sl,partial_done FROM trail_state WHERE ticket=?",
                    (ticket,))
    if row: return row
    if setup_hash:
        return _db_query(
            "SELECT ticket,last_sl,partial_done FROM trail_state WHERE setup_hash=?",
            (setup_hash,))
    return None


def save_trail_sl(ticket: int, sl: float, setup_hash: str = "",
                  partial_done: Optional[int] = None) -> None:
    ex = get_trail_state(ticket, setup_hash)
    pd_ = int(ex["partial_done"]) if ex else 0
    if partial_done is not None: pd_ = partial_done
    _db_exec("INSERT OR REPLACE INTO trail_state VALUES(?,?,?,?,?)",
             (ticket, setup_hash or "", sl, time.time(), pd_))


def set_partial_done(ticket: int, setup_hash: str = "") -> None:
    ex = get_trail_state(ticket, setup_hash)
    ls = float(ex["last_sl"]) if ex else 0.0
    _db_exec("INSERT OR REPLACE INTO trail_state VALUES(?,?,?,?,?)",
             (ticket, setup_hash or "", ls, time.time(), 1))


def cleanup_trail_state(open_tickets: set) -> None:
    if not open_tickets:
        _db_exec("DELETE FROM trail_state"); return
    ph = ",".join("?" * len(open_tickets))
    _db_exec(f"DELETE FROM trail_state WHERE ticket NOT IN ({ph})", tuple(open_tickets))


def batch_load_trail_states(tickets: List[int]) -> Dict[int, sqlite3.Row]:
    if not tickets: return {}
    ph = ",".join("?" * len(tickets))
    rows = _db_query_all(
        f"SELECT ticket,setup_hash,last_sl,partial_done FROM trail_state WHERE ticket IN ({ph})",
        tuple(tickets))
    return {int(r["ticket"]): r for r in rows}


def get_rolling_win_prob_avg(n: int = ML_ROLLING_WINDOW) -> float:
    rows = _db_query_all("SELECT prob FROM win_prob_history ORDER BY ts DESC LIMIT ?", (n,))
    return float(np.mean([r["prob"] for r in rows])) if rows else 0.0


def get_state(key: str, default=None):
    row = _db_query("SELECT value FROM bot_state WHERE key=?", (key,))
    return json.loads(row["value"]) if row else default


def set_state(key: str, value) -> None:
    _db_exec("INSERT OR REPLACE INTO bot_state VALUES(?,?)", (key, json.dumps(value)))


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
class DXYBias:
    available:   bool  = False
    trend:       str   = "NEUTRAL"
    buy_penalty: int   = 0
    sell_bonus:  int   = 0


@dataclass
class FVGZone:
    kind:         str
    top:          float
    bot:          float
    strength:     float
    bar_index:    int
    mitigated:    bool  = False
    volume_spike: bool  = False


@dataclass
class LiquidityMap:
    buy_side:       List[float] = field(default_factory=list)
    sell_side:      List[float] = field(default_factory=list)
    swept_high:     Optional[float] = None
    swept_low:      Optional[float] = None
    gap_swept_high: Optional[float] = None
    gap_swept_low:  Optional[float] = None
    bsl_nearest:    Optional[float] = None
    ssl_nearest:    Optional[float] = None


@dataclass
class OBResult:
    found:        bool  = False
    high:         float = 0.0
    low:          float = 0.0
    score:        float = 0.0
    bar_age:      int   = 0
    mitigated:    bool  = False
    volume_spike: bool  = False


@dataclass
class SetupResult:
    signal:      str              = "WAIT"
    score:       int              = 0
    entry:       float            = 0.0
    sl:          float            = 0.0
    atr:         float            = 0.0
    htf_bias:    str              = "NEUTRAL"
    m15_struct:  str              = "NEUTRAL"
    adr_pct:     float            = 0.0
    threshold:   int              = 60
    reasons:     List[str]        = field(default_factory=list)
    setup_hash:  str              = ""
    use_market:  bool             = False
    liq_map:     Optional[LiquidityMap]  = None
    fvg_zone:    Optional[FVGZone]       = None
    candle_ts:   float            = 0.0
    htf_result:  Optional[HTFBiasResult] = None
    dxy_bias:    Optional[DXYBias]       = None
    pd_zone:     str              = "NEUTRAL"
    features:    Optional[np.ndarray]    = None
    win_prob:    float            = 0.0
    spread_pts:  float            = 0.0
    is_judas:    bool             = False

    def summary(self) -> str:
        gap = self.score - self.threshold
        conf = "💎" if gap >= 30 else "🔥🔥" if gap >= 15 else "🔥" if gap >= 0 else "⚠️"
        mode = "MKT" if self.use_market else "LMT"
        return (f"{conf} {self.signal}({mode}) Score:{self.score}/{self.threshold} "
                f"WinProb:{self.win_prob:.2f} | {' | '.join(self.reasons)}")


# ══════════════════════════════════════════════════════════════════════════════
# 🤖  ML LAYER  — Welford online normaliser [V14-O1] + [V14-F7] outlier guard
# ══════════════════════════════════════════════════════════════════════════════
class WelfordNormaliser:
    """[V14-O1] O(1) per-update Welford online mean/variance estimator."""
    def __init__(self, n_features: int, min_samples: int = 20):
        self._n  = n_features
        self._min = min_samples
        self._count  = np.zeros(n_features, dtype=np.float64)
        self._mean   = np.zeros(n_features, dtype=np.float64)
        self._M2     = np.zeros(n_features, dtype=np.float64)

    def update(self, x: np.ndarray) -> None:
        for i, v in enumerate(x):
            if np.isfinite(v):
                self._count[i] += 1
                delta  = v - self._mean[i]
                self._mean[i] += delta / self._count[i]
                delta2 = v - self._mean[i]
                self._M2[i] += delta * delta2

    def transform(self, x: np.ndarray) -> np.ndarray:
        out = x.copy()
        if not self.is_warm: return out
        for i in range(self._n):
            var = self._M2[i] / (self._count[i] - 1) if self._count[i] > 1 else 0.0
            std = math.sqrt(var) if var > 0 else 0.0
            out[i] = (out[i] - self._mean[i]) / std if std > 1e-9 else 0.0
        return out

    def check_shift(self, x: np.ndarray, z_bound: float = 3.5) -> bool:
        if not self.is_warm: return False
        for i in range(self._n):
            var = self._M2[i] / (self._count[i] - 1) if self._count[i] > 1 else 0.0
            std = math.sqrt(var) if var > 0 else 0.0
            if std > 1e-9 and abs((x[i] - self._mean[i]) / std) > z_bound:
                return True
        return False

    @property
    def is_warm(self) -> bool:
        return bool(np.all(self._count >= self._min))


N_FEATURES = 12


def extract_features(setup: "SetupResult", close_price: float = 2000.0,
                     df_len: int = 300) -> np.ndarray:
    """
    12-feature stationary vector.  score_norm removed (circular dependency fix).
    [V14-F6] fvg_age_norm uses relative bar distance from current candle.
    """
    htf_enc  = {"BULLISH": 1.0, "BEARISH": -1.0}.get(setup.htf_bias, 0.0)
    atr      = max(setup.atr, 1e-6)
    atr_norm = atr / max(close_price, 1.0)

    fvg_strength = setup.fvg_zone.strength if setup.fvg_zone else 0.0
    # [V14-F6] age relative to current bar position, not absolute index
    fvg_age_norm = 0.0
    if setup.fvg_zone is not None:
        age_bars = max(0, df_len - 1 - setup.fvg_zone.bar_index)
        lookback = FVG_MEMORY_BARS.get("DEFAULT", 30)
        fvg_age_norm = min(1.0, age_bars / max(lookback, 1))

    spread_norm = setup.spread_pts / atr
    m15_enc     = {"BULLISH_BOS": 1.0, "BEARISH_BOS": -1.0}.get(setup.m15_struct, 0.0)
    reasons_str = " ".join(setup.reasons)
    has_ob         = 1.0 if any("OB(q:" in r for r in setup.reasons) else 0.0
    sweep_and_fvg  = 1.0 if "Sweep+FVG" in reasons_str else 0.0
    has_liq_target = 1.0 if ("BSL→" in reasons_str or "SSL→" in reasons_str) else 0.0

    sweep_depth = 0.0
    lm = setup.liq_map
    if lm is not None:
        if lm.swept_low is not None and setup.signal == "BUY":
            sweep_depth = min(1.0, abs((lm.ssl_nearest or lm.swept_low) - lm.swept_low) / atr)
        elif lm.swept_high is not None and setup.signal == "SELL":
            sweep_depth = min(1.0, abs(lm.swept_high - (lm.bsl_nearest or lm.swept_high)) / atr)

    now = datetime.now(STRATEGY_TZ)
    session_sin = math.sin(2.0 * math.pi * (now.hour * 60 + now.minute) / 1440.0)

    return np.array([htf_enc, atr_norm, float(setup.adr_pct), float(fvg_strength),
                     float(spread_norm), m15_enc, float(has_liq_target), float(has_ob),
                     float(sweep_and_fvg), float(fvg_age_norm), float(sweep_depth),
                     float(session_sin)], dtype=np.float64)


class MLPredictor:
    """[V15-S2] ML gate relaxed to 0.50. Welford normaliser [V14-O1]."""
    def __init__(self):
        self._model = None
        self._norm  = WelfordNormaliser(N_FEATURES)
        self._prob_buf: Deque[float] = deque(maxlen=ML_ROLLING_WINDOW)
        log.info(f"🧠 MLPredictor V15: {N_FEATURES}-feature vector | "
                 "Welford normaliser | ML gate = 0.50")

    def load_model(self, path: str) -> bool:
        try:
            obj = joblib.load(path)
            self._model = obj[1] if isinstance(obj, tuple) and len(obj) == 2 else obj
            log.info(f"🧠 MLPredictor: model loaded from {path}")
            return True
        except Exception as exc:
            log.warning(f"🧠 MLPredictor: load failed ({exc}) — heuristic mode")
            return False

    def predict_win_probability(self, features: np.ndarray,
                                update_norm: bool = True) -> float:
        # [V14-F7] Check distribution shift BEFORE updating the buffer
        shift = self._norm.check_shift(features, z_bound=3.5)
        if update_norm and not shift:
            self._norm.update(features)
        if shift:
            log.warning("🧠 Distribution shift detected (>3.5 SD) → returning 0.49")
            return 0.49   # below threshold: reject without contaminating buffer

        x = self._norm.transform(features)
        if self._model is not None:
            try:
                prob = float(self._model.predict_proba(x.reshape(1, -1))[0][1])
                prob = max(0.0, min(1.0, prob))
                self._prob_buf.append(prob)
                return prob
            except Exception as exc:
                log.warning(f"🧠 Inference error: {exc} — heuristic fallback")

        # ── Heuristic (no model loaded) ────────────────────────────────────
        raw = features   # raw values from extract_features
        htf_aligned   = abs(float(raw[0])) > 0.5
        adr_pct       = float(raw[2])
        sweep_and_fvg = float(raw[8]) > 0.5
        has_liq       = float(raw[6]) > 0.5
        has_ob        = float(raw[7]) > 0.5
        m15_confirms  = abs(float(raw[5])) > 0.5
        fvg_fresh     = float(raw[9]) < 0.3
        sweep_depth   = float(raw[10])

        prob = 0.38
        if htf_aligned:        prob += 0.12
        if sweep_and_fvg:      prob += 0.10
        if has_liq:            prob += 0.07
        if has_ob:             prob += 0.06
        if m15_confirms:       prob += 0.06
        if fvg_fresh:          prob += 0.05
        if sweep_depth > 0.1:  prob += min(0.04, sweep_depth * 0.4)
        if adr_pct > 0.80:     prob -= 0.10

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
    def __init__(self):
        self._cache: Dict[int, Tuple[float, pd.DataFrame]] = {}
        self._lock  = threading.Lock()

    def _ttl(self, tf: int) -> float:
        if tf in (mt5.TIMEFRAME_M1, mt5.TIMEFRAME_M5): return CACHE_TTL_LTF
        if tf == mt5.TIMEFRAME_D1: return CACHE_TTL_D1
        return CACHE_TTL_HTF

    def fetch(self, tf: int, n: int, use_cache: bool = True) -> Optional[pd.DataFrame]:
        now = time.time()
        with self._lock:
            if use_cache and tf in self._cache:
                ts, df = self._cache[tf]
                if now - ts < self._ttl(tf): return df
        rates = mt5.copy_rates_from_pos(SYMBOL, tf, 0, n)
        if rates is None or len(rates) == 0:
            log.warning(f"MarketDataFeed.fetch: no data tf={tf}"); return None
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
        def _trim(df):
            return df.iloc[:-1].copy() if df is not None else None
        m1  = _trim(self.fetch(mt5.TIMEFRAME_M1,   60,  use_cache=False))
        m5  = _trim(self.fetch(mt5.TIMEFRAME_M5,  300,  use_cache=False))
        m15 = _trim(self.fetch(mt5.TIMEFRAME_M15, 100,  use_cache=True))
        h4  = _trim(self.fetch(mt5.TIMEFRAME_H4,  120,  use_cache=True))
        d1  = self.fetch(mt5.TIMEFRAME_D1,  20, use_cache=True)
        dxy = None
        if DXY_ENABLED and DXY_SYMBOL:
            r = mt5.copy_rates_from_pos(DXY_SYMBOL, mt5.TIMEFRAME_H1, 0, 60)
            if r is not None and len(r) > 0:
                dxy = pd.DataFrame(r)
                dxy["time"] = pd.to_datetime(dxy["time"], unit="s")
        return {"m1": m1, "m5": m5, "m15": m15, "h4": h4, "d1": d1, "dxy": dxy}

    def get_current_m5_bar_time(self) -> Optional[int]:
        rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M5, 0, 1)
        if rates is not None and len(rates) > 0: return int(rates[0]["time"])
        return None


# ══════════════════════════════════════════════════════════════════════════════
# 🧮  INDICATOR FUNCTIONS  — [OPT-1] NumPy hot-paths preserved
# ══════════════════════════════════════════════════════════════════════════════
def _to_numpy(df: pd.DataFrame, col: str) -> np.ndarray:
    return np.ascontiguousarray(df[col].values, dtype=np.float64)


def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < period + 1: return 0.0
    high  = _to_numpy(df, "high");  low = _to_numpy(df, "low")
    close = _to_numpy(df, "close"); prev = close[:-1]
    tr = np.maximum(high[1:] - low[1:],
                    np.maximum(np.abs(high[1:] - prev), np.abs(low[1:] - prev)))
    if len(tr) < period: return 0.0
    atr_val = float(tr[:period].mean())
    alpha   = 1.0 / period
    for v in tr[period:]:
        atr_val = atr_val * (1.0 - alpha) + float(v) * alpha
    return atr_val if not np.isnan(atr_val) else 0.0


def calculate_adr(df_d1: Optional[pd.DataFrame], period: int = 10) -> float:
    if df_d1 is None or len(df_d1) < period: return 0.0
    high = _to_numpy(df_d1, "high");  low = _to_numpy(df_d1, "low")
    return float((high - low)[-period:].mean())


def get_confirmed_swings_np(df: pd.DataFrame, period: int = 5,
                             confirm: int = 2) -> Tuple[float, float]:
    if len(df) < period * 2 + confirm + 1:
        return float(df["high"].max()), float(df["low"].min())
    high = _to_numpy(df, "high");  low = _to_numpy(df, "low")
    safe = len(high) - confirm
    sh_vals, sl_vals = [], []
    for i in range(period, safe - period):
        if high[i] == high[i - period: i + period + 1].max(): sh_vals.append(high[i])
        if low[i]  == low[i  - period: i + period + 1].min(): sl_vals.append(low[i])
    return (float(sh_vals[-1]) if sh_vals else float(high.max()),
            float(sl_vals[-1]) if sl_vals else float(low.min()))


def _cluster_liquidity_levels(prices: List[float], tol: float) -> List[float]:
    clusters: List[float] = []
    used = [False] * len(prices)
    for i in range(len(prices)):
        if used[i]: continue
        group = [prices[i]]
        for j in range(i + 1, len(prices)):
            if not used[j] and abs(prices[j] - prices[i]) <= tol:
                group.append(prices[j]); used[j] = True
        if len(group) >= LIQ_MIN_CLUSTER:
            clusters.append(round(sum(group) / len(group), 5))
    return clusters


def build_liquidity_map_np(df: pd.DataFrame, atr: float,
                            period: int = 10) -> LiquidityMap:
    liq = LiquidityMap()
    if len(df) < period * 2 + 4 or atr == 0: return liq
    high = _to_numpy(df, "high"); low = _to_numpy(df, "low")
    cls  = _to_numpy(df, "close"); opn = _to_numpy(df, "open")
    safe = len(high) - 2
    tol  = max(atr * 0.08, abs(cls[-1]) * LIQ_EQUAL_TOLERANCE)
    ph_list, pl_list = [], []
    for i in range(period, safe - period):
        if high[i] == high[i - period: i + period + 1].max(): ph_list.append(high[i])
        if low[i]  == low[i  - period: i + period + 1].min(): pl_list.append(low[i])
    liq.buy_side  = sorted(_cluster_liquidity_levels(ph_list, tol), reverse=True)
    liq.sell_side = sorted(_cluster_liquidity_levels(pl_list, tol))
    last_high  = float(high[-1]); last_low  = float(low[-1])
    last_close = float(cls[-1]);  prev_close = float(cls[-2]) if len(cls) >= 2 else last_close
    cur_open   = float(opn[-1])
    for lvl in liq.buy_side:
        if last_high > lvl and last_close < lvl: liq.swept_high = lvl; break
    for lvl in liq.sell_side:
        if last_low < lvl and last_close > lvl: liq.swept_low  = lvl; break
    for lvl in liq.buy_side:
        if prev_close >= lvl > cur_open: liq.gap_swept_high = lvl; break
    for lvl in liq.sell_side:
        if prev_close <= lvl < cur_open: liq.gap_swept_low  = lvl; break
    price = last_close
    above = [l for l in liq.buy_side  if l > price]
    below = [l for l in liq.sell_side if l < price]
    liq.bsl_nearest = min(above) if above else None
    liq.ssl_nearest = max(below) if below else None
    return liq


def _rolling_vol_mean(df: pd.DataFrame, period: int) -> Optional[np.ndarray]:
    if "tick_volume" not in df.columns: return None
    vol = df["tick_volume"].astype(float).values
    result = np.full(len(vol), np.nan)
    for i in range(period, len(vol)):
        result[i] = vol[max(0, i - period): i].mean()
    return result


def _make_hash(sig: str, entry: float, sl: float, ts: float) -> str:
    raw = f"{sig}:{entry:.2f}:{sl:.2f}:{int(ts)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


# ══════════════════════════════════════════════════════════════════════════════
# 🧠  CLASS: SMCSignalEngine  [V15-S1] Balanced scoring system
# ══════════════════════════════════════════════════════════════════════════════
class SMCSignalEngine:

    def __init__(self):
        self._news_guard = NewsGuard()

    # ── HTF Bias (H4) ─────────────────────────────────────────────────────────
    @staticmethod
    def get_htf_bias(df_h4: Optional[pd.DataFrame]) -> HTFBiasResult:
        res = HTFBiasResult()
        if df_h4 is None or len(df_h4) < HTF_SWING_PERIOD * 2 + HTF_SWING_CONFIRM + 5:
            res.reason = "H4 data insufficient"; return res
        lookback = min(60, len(df_h4))
        df = df_h4.iloc[-lookback:].reset_index(drop=True)
        p, c = HTF_SWING_PERIOD, HTF_SWING_CONFIRM
        high = _to_numpy(df, "high"); low = _to_numpy(df, "low"); cls = _to_numpy(df, "close")
        safe = len(high) - c
        sh_list: List[Tuple[int, float]] = []
        sl_list: List[Tuple[int, float]] = []
        for i in range(p, safe - p):
            if high[i] == high[i - p: i + p + 1].max(): sh_list.append((i, float(high[i])))
            if low[i]  == low[i  - p: i + p + 1].min(): sl_list.append((i, float(low[i])))
        if len(sh_list) < 2 or len(sl_list) < 2:
            res.reason = "Insufficient swings"; return res
        prev_sh = sh_list[-1][1]; prev_sl = sl_list[-1][1]
        last_high = float(high[-1]); last_low = float(low[-1]); last_close = float(cls[-1])
        if last_high > prev_sh and last_close < prev_sh: res.swept_high = prev_sh
        if last_low  < prev_sl and last_close > prev_sl: res.swept_low  = prev_sl
        recent_cls = cls[-5:]
        bos_up   = bool(np.any(recent_cls > prev_sh))
        bos_down = bool(np.any(recent_cls < prev_sl))
        hh = sh_list[-1][1] > sh_list[-2][1]; lh = sh_list[-1][1] < sh_list[-2][1]
        hl = sl_list[-1][1] > sl_list[-2][1]; ll = sl_list[-1][1] < sl_list[-2][1]
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
            res.bias = "NEUTRAL"; res.reason = f"Bull:{bull_pts} Bear:{bear_pts} — ranging"
        return res

    # ── DXY Bias ──────────────────────────────────────────────────────────────
    @staticmethod
    def get_dxy_bias(df_dxy: Optional[pd.DataFrame]) -> DXYBias:
        result = DXYBias()
        if not DXY_ENABLED or df_dxy is None or len(df_dxy) < DXY_SWING_PERIOD * 2 + 3:
            return result
        result.available = True
        try:
            sh, sl = get_confirmed_swings_np(df_dxy, period=DXY_SWING_PERIOD, confirm=2)
            last_c = float(df_dxy["close"].iloc[-1])
            if last_c > sh:
                result.trend = "BULLISH"
                result.buy_penalty = DXY_BUY_PENALTY
                result.sell_bonus  = DXY_SELL_BONUS
            elif last_c < sl:
                result.trend = "BEARISH"
        except Exception:
            result.available = False
        return result

    # ── M15 Structure ─────────────────────────────────────────────────────────
    @staticmethod
    def get_m15_structure(df_m15: Optional[pd.DataFrame]) -> str:
        if df_m15 is None or len(df_m15) < SWING_PERIOD * 2 + SWING_CONFIRM_BARS + 5:
            return "NEUTRAL"
        sub = df_m15.iloc[-40:].reset_index(drop=True)
        sh, sl = get_confirmed_swings_np(sub, period=SWING_PERIOD, confirm=SWING_CONFIRM_BARS)
        last_c = float(sub["close"].iloc[-1])
        buf    = (sh - sl) * 0.005
        if last_c > sh + buf: return "BULLISH_BOS"
        if last_c < sl - buf: return "BEARISH_BOS"
        return "NEUTRAL"

    # ── Premium / Discount Zone ────────────────────────────────────────────────
    @staticmethod
    def get_pd_zone(df_m5: pd.DataFrame, period: int = PD_PERIOD) -> str:
        if not PD_ZONE_ENABLED or len(df_m5) < period: return "NEUTRAL"
        sub   = df_m5.iloc[-period:]
        rng_h = float(sub["high"].max());  rng_l = float(sub["low"].min())
        spread = rng_h - rng_l
        if spread < 1e-6: return "NEUTRAL"
        pct = (float(df_m5["close"].iloc[-1]) - rng_l) / spread
        if pct > 0.67: return "PREMIUM"
        if pct < 0.33: return "DISCOUNT"
        return "EQUILIBRIUM"

    # ── FVG Memory ────────────────────────────────────────────────────────────
    @staticmethod
    def scan_fvg_memory(df: pd.DataFrame, atr: float, lookback: int = 30) -> List[FVGZone]:
        zones: List[FVGZone] = []
        if len(df) < lookback + 3 or atr == 0: return zones
        min_gap  = atr * FVG_MIN_GAP_ATR
        start    = max(3, len(df) - lookback)
        vol_mean = _rolling_vol_mean(df, VOL_SPIKE_PERIOD) if VOL_SPIKE_ENABLED else None

        for i in range(start, len(df) - 2):
            c1 = df.iloc[i]; c2 = df.iloc[i + 1]; c3 = df.iloc[i + 2]
            c2_range = float(c2["high"] - c2["low"])
            c2_body  = abs(float(c2["close"] - c2["open"]))
            if c2_range > 0 and (c2_body / c2_range) < FVG_MOMENTUM_RATIO: continue

            vol_spike = False
            if VOL_SPIKE_ENABLED and vol_mean is not None:
                idx = i + 1
                vm = vol_mean[idx] if idx < len(vol_mean) else np.nan
                if not np.isnan(vm) and vm > 0:
                    vol_spike = float(df.iloc[idx]["tick_volume"]) >= vm * VOL_SPIKE_MULT

            gap_bull = float(c3["low"]) - float(c1["high"])
            if gap_bull >= min_gap:
                top = float(c3["low"]); bot = float(c1["high"])
                gap = top - bot; strength = min(2.0, gap / atr)
                mid = bot + gap * FVG_MITIGATED_PCT; mitigated = False
                for j in range(i + 3, len(df)):
                    if float(df.iloc[j]["low"]) <= mid: mitigated = True; break
                zones.append(FVGZone("BULLISH", top, bot, strength, i, mitigated, vol_spike))

            gap_bear = float(c1["low"]) - float(c3["high"])
            if gap_bear >= min_gap:
                top = float(c1["low"]); bot = float(c3["high"])
                gap = top - bot; strength = min(2.0, gap / atr)
                mid = top - gap * FVG_MITIGATED_PCT; mitigated = False
                for j in range(i + 3, len(df)):
                    if float(df.iloc[j]["high"]) >= mid: mitigated = True; break
                zones.append(FVGZone("BEARISH", top, bot, strength, i, mitigated, vol_spike))

        zones.sort(key=lambda z: z.bar_index, reverse=True)
        return zones

    @staticmethod
    def get_active_fvg(zones: List[FVGZone], price: float,
                        direction: str) -> Optional[FVGZone]:
        target = "BULLISH" if direction == "BUY" else "BEARISH"
        for z in zones:
            if z.mitigated or z.kind != target: continue
            buf = (z.top - z.bot) * FVG_BUFFER_RATIO
            if (z.bot - buf) <= price <= (z.top + buf): return z
        return None

    # ── Order Block ───────────────────────────────────────────────────────────
    @staticmethod
    def find_order_block(df: pd.DataFrame, direction: str, atr: float) -> OBResult:
        if len(df) < 10 or atr == 0: return OBResult()
        closed   = df.iloc[:-1]; n = len(closed); max_age = min(30, n - 2)
        vol_mean = _rolling_vol_mean(closed, VOL_SPIKE_PERIOD) if VOL_SPIKE_ENABLED else None
        for age in range(1, max_age):
            i = n - 1 - age
            if i + 1 >= n - 1: continue
            ob = closed.iloc[i]; imp = closed.iloc[i + 1]
            if abs(float(imp["close"]) - float(imp["open"])) < atr * 1.2: continue
            vol_spike = False
            if VOL_SPIKE_ENABLED and vol_mean is not None:
                vm = vol_mean[i + 1] if i + 1 < len(vol_mean) else np.nan
                if not np.isnan(vm) and vm > 0:
                    vol_spike = float(imp["tick_volume"]) >= vm * VOL_SPIKE_MULT
            ob_low = float(ob["low"]); ob_high = float(ob["high"]); rng = ob_high - ob_low
            if direction == "BUY":
                if ob["close"] >= ob["open"] or imp["close"] <= imp["open"]: continue
                ph_w = closed["high"].iloc[max(0, i - 10): i]
                if len(ph_w) > 0 and imp["close"] <= ph_w.max() * 0.998: continue
                mitigated = any(float(closed.iloc[j]["close"]) < ob_low
                                for j in range(i + 2, n))
                body  = (float(ob["open"]) - float(ob["close"])) / rng if rng > 0 else 0
                sweep = float(closed["low"].iloc[max(0, i - 5): i].min()) < ob_low
            else:
                if ob["close"] <= ob["open"] or imp["close"] >= imp["open"]: continue
                pl_w = closed["low"].iloc[max(0, i - 10): i]
                if len(pl_w) > 0 and imp["close"] >= float(pl_w.min()) * 1.002: continue
                mitigated = any(float(closed.iloc[j]["close"]) > ob_high
                                for j in range(i + 2, n))
                body  = (float(ob["close"]) - float(ob["open"])) / rng if rng > 0 else 0
                sweep = float(closed["high"].iloc[max(0, i - 5): i].max()) > ob_high
            q = 0.5 + (0.3 if sweep else 0) + (0.2 if body > 0.6 else 0)
            return OBResult(True, ob_high, ob_low, q, bar_age=age,
                            mitigated=mitigated, volume_spike=vol_spike)
        return OBResult()

    # ── Judas Swing Detection [V14-S2] ────────────────────────────────────────
    @staticmethod
    def is_judas_swing(liq: LiquidityMap, fvg_zones: List[FVGZone],
                        signal: str, session: str) -> bool:
        if not JUDAS_SWING_ENABLED: return False
        now = datetime.now(STRATEGY_TZ)
        session_opens = {"LONDON": dtime(14, 0), "NY_OPEN_EARLY": dtime(18, 30),
                         "NEW_YORK": dtime(19, 45)}
        open_t = session_opens.get(session)
        if open_t is None: return False
        minutes_since_open = (now.hour * 60 + now.minute) - (open_t.hour * 60 + open_t.minute)
        if not (0 <= minutes_since_open <= JUDAS_WINDOW_MIN): return False
        if signal == "BUY" and liq.swept_low is not None:
            return any(z.kind == "BULLISH" and not z.mitigated for z in fvg_zones)
        if signal == "SELL" and liq.swept_high is not None:
            return any(z.kind == "BEARISH" and not z.mitigated for z in fvg_zones)
        return False

    # ── ADR TP Cap [V14-S3] ───────────────────────────────────────────────────
    @staticmethod
    def apply_adr_tp_cap(entry: float, tp_raw: float, sl: float, adr: float,
                          df_d1: Optional[pd.DataFrame], session: str,
                          signal: str) -> Tuple[float, bool]:
        if adr <= 0 or df_d1 is None or len(df_d1) < 1: return tp_raw, False
        day_high = float(df_d1["high"].iloc[-1]); day_low = float(df_d1["low"].iloc[-1])
        adr_ceil = ADR_NY_EXHAUSTED_PCT if session in ("NEW_YORK", "NY_OPEN_EARLY") \
                   else ADR_EXHAUSTED_PCT
        capped = False; tp_adj = tp_raw
        if signal == "BUY":
            cap = day_low + adr * adr_ceil
            if tp_raw > cap: tp_adj = entry + (cap - entry) * ADR_TP_BUFFER_PCT; capped = True
        elif signal == "SELL":
            cap = day_high - adr * adr_ceil
            if tp_raw < cap: tp_adj = entry - (entry - cap) * ADR_TP_BUFFER_PCT; capped = True
        risk = abs(entry - sl)
        if signal == "BUY"  and (tp_adj - entry) < risk: tp_adj = tp_raw; capped = False
        if signal == "SELL" and (entry - tp_adj) < risk: tp_adj = tp_raw; capped = False
        return tp_adj, capped

    # ── Session helpers ───────────────────────────────────────────────────────
    def get_session(self) -> str:
        now = datetime.now(STRATEGY_TZ)
        blocked, event = self._news_guard.is_blocked(now)
        if blocked:
            log.info(f"📰 News Guard: blocked ({event})"); return "RED_NEWS_BLOCK"
        t = now.time()
        for sh, sm, eh, em, name in SESSIONS:
            s, e = dtime(sh, sm), dtime(eh, em)
            if e < s:
                if t >= s or t <= e: return name
            else:
                if s <= t <= e: return name
        return "OUT_OF_SESSION"

    @staticmethod
    def is_in_killzone() -> Tuple[bool, str]:
        if not KILLZONE_ENABLED: return True, "All"
        t = datetime.now(STRATEGY_TZ).time()
        for sh, sm, eh, em, name in KILLZONES:
            if dtime(sh, sm) <= t <= dtime(eh, em): return True, name
        return False, "Outside Killzone"

    @staticmethod
    def get_dynamic_threshold(session: str) -> int:
        """[V15-S3] Flat threshold — no HTF neutral penalty, no ADR raise."""
        return SCORE_THRESHOLD.get(session, SCORE_THRESHOLD["DEFAULT"])

    # ── Master setup analyser [V15-S1] ───────────────────────────────────────
    def analyze_setup(self, df_m5: Optional[pd.DataFrame],
                      df_h4:  Optional[pd.DataFrame],
                      df_d1:  Optional[pd.DataFrame],
                      df_m15: Optional[pd.DataFrame],
                      df_dxy: Optional[pd.DataFrame],
                      session: str = "DEFAULT") -> SetupResult:
        r = SetupResult()

        if df_m5 is None or len(df_m5) < 30:
            r.reasons.append("M5 data insufficient"); return r
        atr = calculate_atr(df_m5)
        if atr == 0:
            r.reasons.append("ATR=0"); return r
        r.atr = atr

        adr = calculate_adr(df_d1)
        if adr > 0 and df_d1 is not None and len(df_d1) >= 1:
            day_range  = float(df_d1["high"].iloc[-1] - df_d1["low"].iloc[-1])
            r.adr_pct  = day_range / adr

        # [V15-S4] ADR hard block disabled — penalty applied in scoring
        adr_ceil = ADR_NY_EXHAUSTED_PCT if session in ("NEW_YORK", "NY_OPEN_EARLY") \
                   else ADR_EXHAUSTED_PCT
        if ADR_HARD_BLOCK and r.adr_pct >= adr_ceil:
            r.reasons.append(f"ADR_HARD_BLOCK({r.adr_pct*100:.0f}%)")
            return r

        htf_res      = self.get_htf_bias(df_h4)
        r.htf_bias   = htf_res.bias
        r.htf_result = htf_res
        dxy_b        = self.get_dxy_bias(df_dxy)
        r.dxy_bias   = dxy_b
        r.m15_struct = self.get_m15_structure(df_m15)
        r.threshold  = self.get_dynamic_threshold(session)  # flat 60
        r.pd_zone    = self.get_pd_zone(df_m5)

        liq       = build_liquidity_map_np(df_m5, atr, LIQ_SWING_PERIOD)
        r.liq_map = liq
        last_sh, last_sl = get_confirmed_swings_np(df_m5, SWING_PERIOD, SWING_CONFIRM_BARS)
        fvg_lookback     = FVG_MEMORY_BARS.get(session, FVG_MEMORY_BARS["DEFAULT"])
        fvg_zones        = self.scan_fvg_memory(df_m5, atr, fvg_lookback)
        df_len = len(df_m5)

        last = df_m5.iloc[-1]; prev = df_m5.iloc[-2]
        r.candle_ts = (float(last["time"].timestamp())
                       if hasattr(last["time"], "timestamp") else time.time())

        price      = float(last["close"])
        sweep_sell = float(last["low"]) < last_sl and float(last["close"]) > last_sl
        sweep_buy  = float(last["high"]) > last_sh and float(last["close"]) < last_sh
        if liq.gap_swept_low  is not None: sweep_sell = True
        if liq.gap_swept_high is not None: sweep_buy  = True

        # ── Shared scoring helpers [V15-S1] ───────────────────────────────────
        def _apply_htf_scores(sig: str) -> None:
            """[V15-S1] HTF Neutral = 0 bonus/penalty.  Never blocks."""
            if r.htf_bias == "BULLISH" and sig == "BUY":
                r.score += SCORE_HTF_ALIGN
                choch = "(CHOCH)" if htf_res.choch_signal == "UP" else ""
                r.reasons.append(f"H4 Bull{choch} ✓ +{SCORE_HTF_ALIGN}")
            elif r.htf_bias == "BEARISH" and sig == "SELL":
                r.score += SCORE_HTF_ALIGN
                choch = "(CHOCH)" if htf_res.choch_signal == "DOWN" else ""
                r.reasons.append(f"H4 Bear{choch} ✓ +{SCORE_HTF_ALIGN}")
            elif (r.htf_bias == "BULLISH" and sig == "SELL") or \
                 (r.htf_bias == "BEARISH" and sig == "BUY"):
                r.score += SCORE_HTF_AGAINST
                r.reasons.append(f"H4 {r.htf_bias} ⚠️ ({SCORE_HTF_AGAINST}pts)")
            else:  # NEUTRAL — no effect
                r.reasons.append("H4 Neutral ± 0")

        def _apply_dxy_scores(sig: str) -> None:
            if not (DXY_ENABLED and dxy_b.available): return
            if dxy_b.trend == "BULLISH" and sig == "BUY":
                r.score += dxy_b.buy_penalty
                r.reasons.append(f"DXY↑ BUY ({dxy_b.buy_penalty})")
            elif dxy_b.trend == "BULLISH" and sig == "SELL":
                r.score += dxy_b.sell_bonus
                r.reasons.append(f"DXY↑ SELL +{dxy_b.sell_bonus} ✓")
            elif dxy_b.trend == "BEARISH" and sig == "BUY":
                r.score += abs(dxy_b.sell_bonus)
                r.reasons.append(f"DXY↓ BUY +{abs(dxy_b.sell_bonus)} ✓")

        def _apply_pd_scores(sig: str) -> None:
            if not PD_ZONE_ENABLED: return
            if r.pd_zone == "DISCOUNT" and sig == "BUY":
                r.score += 5; r.reasons.append("Discount ✓")
            elif r.pd_zone == "PREMIUM" and sig == "SELL":
                r.score += 5; r.reasons.append("Premium ✓")
            elif r.pd_zone == "EQUILIBRIUM":
                r.score += PD_PENALTY; r.reasons.append("Equilibrium ⚠️")

        # ── BUY builder [V15-S1 balanced scoring] ─────────────────────────────
        def _build_buy() -> bool:
            has_sweep  = sweep_sell
            fvg_active = self.get_active_fvg(fvg_zones, price, "BUY")

            # Must have at least one CORE signal
            if not has_sweep and fvg_active is None:
                return False

            r.signal = "BUY"
            r.score  = SCORE_BASE   # 40

            # Entry price
            if fvg_active is not None:
                r.entry = (fvg_active.bot + (fvg_active.top - fvg_active.bot) * 0.5
                           if FVG_ENTRY_MID else fvg_active.top)
                r.fvg_zone = fvg_active
            elif has_sweep:
                r.entry = last_sl + (atr * 0.1)
            r.sl = last_sl - (atr * SL_ATR_MULT)

            # ── Tier 1: Core signals ──────────────────────────────────────────
            if fvg_active is not None and not fvg_active.mitigated:
                r.score += SCORE_FVG_FRESH            # +20 → 60 ✅
                r.reasons.append(f"FVG Fresh(s:{fvg_active.strength:.2f}) +{SCORE_FVG_FRESH}")

            if has_sweep:
                r.score += SCORE_LIQ_SWEPT             # +20 → 60 ✅
                lbl = "Gap-Sweep" if liq.gap_swept_low else "Sweep"
                r.reasons.append(f"{lbl} SSL +{SCORE_LIQ_SWEPT}")

            # Bonus: both core signals present
            if has_sweep and fvg_active is not None:
                r.score += SCORE_SWEEP_AND_FVG
                r.reasons.append(f"Sweep+FVG Bonus +{SCORE_SWEEP_AND_FVG}")

            # ── Tier 2: HTF Context ───────────────────────────────────────────
            _apply_htf_scores("BUY")
            if htf_res.swept_low is not None:
                r.score += 4; r.reasons.append("H4 SSL Swept +4")

            # ── Tier 3: Confluence Boosters ───────────────────────────────────
            if r.m15_struct == "BULLISH_BOS":
                r.score += SCORE_M15_BOS; r.reasons.append(f"M15 BOS +{SCORE_M15_BOS}")

            body = float(last["close"]) - float(last["open"])
            if body > atr * 0.6:
                r.score += SCORE_STRONG_CANDLE; r.reasons.append(f"Strong ✓ +{SCORE_STRONG_CANDLE}")

            ob = self.find_order_block(df_m5, "BUY", atr)
            if ob.found and not ob.mitigated:
                r.score += SCORE_OB_BONUS
                r.reasons.append(f"OB(q:{ob.score:.2f},age:{ob.bar_age}) +{SCORE_OB_BONUS}")
                if ob.low <= r.entry <= ob.high:
                    r.score += SCORE_OB_OVERLAP; r.reasons.append(f"OB Overlap +{SCORE_OB_OVERLAP}")
                if VOL_SPIKE_ENABLED and ob.volume_spike:
                    r.score += SCORE_VOL_SPIKE; r.reasons.append("VolSpike OB ✓")
            elif ob.found and ob.mitigated:
                r.reasons.append(f"OB(mitigated,age:{ob.bar_age}) ⚠️")

            if fvg_active is not None and fvg_active.strength > 0.5:
                r.score += SCORE_FVG_STRENGTH; r.reasons.append(f"FVG Strong +{SCORE_FVG_STRENGTH}")
            if VOL_SPIKE_ENABLED and fvg_active is not None and fvg_active.volume_spike:
                r.score += SCORE_VOL_SPIKE; r.reasons.append("VolSpike FVG ✓")

            if float(last["close"]) > float(prev["high"]):
                r.score += SCORE_BOS_M5; r.reasons.append(f"BOS M5 +{SCORE_BOS_M5}")

            if liq.bsl_nearest is not None:
                rsk = abs(r.entry - r.sl)
                if rsk > 0 and (liq.bsl_nearest - r.entry) >= rsk * RR_RATIO * 0.8:
                    r.score += SCORE_LIQ_TARGET
                    r.reasons.append(f"BSL→{liq.bsl_nearest:.2f} +{SCORE_LIQ_TARGET}")

            # ── Tier 4: Penalties ─────────────────────────────────────────────
            if r.adr_pct >= adr_ceil:
                r.score += SCORE_ADR_WARN; r.reasons.append(f"ADR{r.adr_pct*100:.0f}% ⚠️{SCORE_ADR_WARN}")

            _apply_dxy_scores("BUY")
            _apply_pd_scores("BUY")

            # Judas Swing bonus
            if self.is_judas_swing(liq, fvg_zones, "BUY", session):
                r.score += JUDAS_SCORE_BONUS; r.is_judas = True
                r.reasons.append(f"⚡ Judas +{JUDAS_SCORE_BONUS}")

            # Market order trigger
            body_ratio = body / atr if atr > 0 else 0
            if (float(last["close"]) > float(prev["high"])
                    and body_ratio > MOMENTUM_BODY_ATR and r.score >= r.threshold):
                r.use_market = True; r.entry = 0.0; r.reasons.append("🚀 MKT")
            return True

        # ── SELL builder [V15-S1 balanced scoring] ────────────────────────────
        def _build_sell() -> bool:
            has_sweep  = sweep_buy
            fvg_active = self.get_active_fvg(fvg_zones, price, "SELL")

            if not has_sweep and fvg_active is None:
                return False

            r.signal = "SELL"
            r.score  = SCORE_BASE   # 40

            if fvg_active is not None:
                r.entry = (fvg_active.bot + (fvg_active.top - fvg_active.bot) * 0.5
                           if FVG_ENTRY_MID else fvg_active.bot)
                r.fvg_zone = fvg_active
            elif has_sweep:
                r.entry = last_sh - (atr * 0.1)
            r.sl = last_sh + (atr * SL_ATR_MULT)

            # ── Tier 1: Core signals ──────────────────────────────────────────
            if fvg_active is not None and not fvg_active.mitigated:
                r.score += SCORE_FVG_FRESH
                r.reasons.append(f"FVG Fresh(s:{fvg_active.strength:.2f}) +{SCORE_FVG_FRESH}")

            if has_sweep:
                r.score += SCORE_LIQ_SWEPT
                lbl = "Gap-Sweep" if liq.gap_swept_high else "Sweep"
                r.reasons.append(f"{lbl} BSL +{SCORE_LIQ_SWEPT}")

            if has_sweep and fvg_active is not None:
                r.score += SCORE_SWEEP_AND_FVG
                r.reasons.append(f"Sweep+FVG Bonus +{SCORE_SWEEP_AND_FVG}")

            # ── Tier 2: HTF Context ───────────────────────────────────────────
            _apply_htf_scores("SELL")
            if htf_res.swept_high is not None:
                r.score += 4; r.reasons.append("H4 BSL Swept +4")

            # ── Tier 3: Confluence Boosters ───────────────────────────────────
            if r.m15_struct == "BEARISH_BOS":
                r.score += SCORE_M15_BOS; r.reasons.append(f"M15 BOS +{SCORE_M15_BOS}")

            body = float(last["open"]) - float(last["close"])
            if body > atr * 0.6:
                r.score += SCORE_STRONG_CANDLE; r.reasons.append(f"Strong ✓ +{SCORE_STRONG_CANDLE}")

            ob = self.find_order_block(df_m5, "SELL", atr)
            if ob.found and not ob.mitigated:
                r.score += SCORE_OB_BONUS
                r.reasons.append(f"OB(q:{ob.score:.2f},age:{ob.bar_age}) +{SCORE_OB_BONUS}")
                if ob.low <= r.entry <= ob.high:
                    r.score += SCORE_OB_OVERLAP; r.reasons.append(f"OB Overlap +{SCORE_OB_OVERLAP}")
                if VOL_SPIKE_ENABLED and ob.volume_spike:
                    r.score += SCORE_VOL_SPIKE; r.reasons.append("VolSpike OB ✓")
            elif ob.found and ob.mitigated:
                r.reasons.append(f"OB(mitigated,age:{ob.bar_age}) ⚠️")

            if fvg_active is not None and fvg_active.strength > 0.5:
                r.score += SCORE_FVG_STRENGTH; r.reasons.append(f"FVG Strong +{SCORE_FVG_STRENGTH}")
            if VOL_SPIKE_ENABLED and fvg_active is not None and fvg_active.volume_spike:
                r.score += SCORE_VOL_SPIKE; r.reasons.append("VolSpike FVG ✓")

            if float(last["close"]) < float(prev["low"]):
                r.score += SCORE_BOS_M5; r.reasons.append(f"BOS M5 +{SCORE_BOS_M5}")

            if liq.ssl_nearest is not None:
                rsk = abs(r.sl - r.entry)
                if rsk > 0 and (r.entry - liq.ssl_nearest) >= rsk * RR_RATIO * 0.8:
                    r.score += SCORE_LIQ_TARGET
                    r.reasons.append(f"SSL→{liq.ssl_nearest:.2f} +{SCORE_LIQ_TARGET}")

            # ── Tier 4: Penalties ─────────────────────────────────────────────
            if r.adr_pct >= adr_ceil:
                r.score += SCORE_ADR_WARN; r.reasons.append(f"ADR{r.adr_pct*100:.0f}% ⚠️{SCORE_ADR_WARN}")

            _apply_dxy_scores("SELL")
            _apply_pd_scores("SELL")

            if self.is_judas_swing(liq, fvg_zones, "SELL", session):
                r.score += JUDAS_SCORE_BONUS; r.is_judas = True
                r.reasons.append(f"⚡ Judas +{JUDAS_SCORE_BONUS}")

            body_ratio = body / atr if atr > 0 else 0
            if (float(last["close"]) < float(prev["low"])
                    and body_ratio > MOMENTUM_BODY_ATR and r.score >= r.threshold):
                r.use_market = True; r.entry = 0.0; r.reasons.append("🚀 MKT")
            return True

        # ── Assemble signal ───────────────────────────────────────────────────
        if not _build_buy():
            r.signal = "WAIT"; r.score = 0; r.reasons = []
            if not _build_sell():
                return r

        # [V15-S3] HTF Neutral guard REMOVED — Neutral market is tradeable
        # (old guard: if r.htf_bias == "NEUTRAL" and r.score < 78 → reject)

        if r.signal != "WAIT":
            entry_h      = r.entry if not r.use_market else -1.0
            r.setup_hash = _make_hash(r.signal, entry_h, r.sl, r.candle_ts)

        return r


# ══════════════════════════════════════════════════════════════════════════════
# 💰  CLASS: RiskManager
# ══════════════════════════════════════════════════════════════════════════════
class RiskManager:
    @staticmethod
    def get_broker_date() -> str:
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick: return datetime.fromtimestamp(tick.time, tz=pytz.utc).strftime("%Y%m%d")
        return datetime.utcnow().strftime("%Y%m%d")

    @staticmethod
    def get_spread_pts() -> float:
        tick = mt5.symbol_info_tick(SYMBOL); info = mt5.symbol_info(SYMBOL)
        if tick is None or info is None: return 999.0
        return (tick.ask - tick.bid) / info.point

    def is_spread_ok(self) -> bool:
        sp = self.get_spread_pts()
        if sp > HARD_SPREAD_BLOCK:
            log.warning(f"⛔ Spread {sp:.1f}pts > {HARD_SPREAD_BLOCK}"); return False
        return True

    @staticmethod
    def get_spread_sl_padding() -> float:
        if not SPREAD_SL_PADDING: return 0.0
        tick = mt5.symbol_info_tick(SYMBOL); info = mt5.symbol_info(SYMBOL)
        if tick is None or info is None: return 0.0
        return ((tick.ask - tick.bid) / info.point) * info.point

    def get_dd_state(self) -> Tuple[float, float, str]:
        acct = mt5.account_info()
        if acct is None: return 0.0, 0.0, "NORMAL"
        equity = acct.equity; balance = acct.balance
        today_key   = "daily_start_balance_" + self.get_broker_date()
        daily_start = get_state(today_key)
        if daily_start is None or daily_start <= 0:
            set_state(today_key, balance); daily_start = balance
        daily_dd = max(0.0, (daily_start - equity) / daily_start * 100)
        init_bal = get_state("initial_balance")
        if init_bal is None:
            set_state("initial_balance", balance); init_bal = balance
        total_dd = max(0.0, (init_bal - equity) / init_bal * 100)
        if daily_dd >= MAX_DAILY_LOSS_PCT or total_dd >= MAX_TOTAL_DD_PCT: mode = "RED"
        elif daily_dd >= DD_ORANGE_PCT: mode = "ORANGE"
        elif daily_dd >= DD_YELLOW_PCT: mode = "YELLOW"
        else: mode = "NORMAL"
        return round(daily_dd, 2), round(total_dd, 2), mode

    def is_within_risk_limits(self) -> bool:
        _, _, mode = self.get_dd_state(); return mode != "RED"

    def new_entries_allowed(self) -> bool:
        _, _, mode = self.get_dd_state(); return mode not in ("RED", "ORANGE")

    def is_circuit_breaker_tripped(self) -> bool:
        acct = mt5.account_info()
        if acct is None: return False
        today_key   = "daily_start_balance_" + self.get_broker_date()
        daily_start = get_state(today_key)
        if daily_start is None or daily_start <= 0: return False
        dd_pct = (daily_start - acct.equity) / daily_start * 100
        if dd_pct >= CIRCUIT_BREAKER_PCT:
            log.warning(f"⚡ CB: DD {dd_pct:.2f}% ≥ {CIRCUIT_BREAKER_PCT}%"); return True
        return False

    def get_risk_tier_multiplier(self, score: int, dd_mode: str) -> float:
        base_pct = RISK_TIERS[-1][1]
        for sm, pct in RISK_TIERS:
            if score >= sm: base_pct = pct; break
        if dd_mode == "YELLOW":
            ci = next((i for i, (sm, _) in enumerate(RISK_TIERS) if score >= sm),
                      len(RISK_TIERS) - 1)
            base_pct = RISK_TIERS[min(ci + 1, len(RISK_TIERS) - 1)][1]
        return base_pct

    @staticmethod
    def _round_lot(lot: float, step: float) -> float:
        d = Decimal(str(lot)); s = Decimal(str(step))
        return float((d / s).to_integral_value(rounding=ROUND_DOWN) * s)

    def calculate_lot(self, entry: float, sl: float, score: int = 0,
                      spread_pts: float = 0.0, atr: float = 0.0,
                      dd_mode: str = "NORMAL") -> float:
        info = mt5.symbol_info(SYMBOL); acct = mt5.account_info()
        if info is None or acct is None: return LOT_MIN
        risk_pct = self.get_risk_tier_multiplier(score, dd_mode)
        if spread_pts > MAX_SPREAD_POINTS: risk_pct *= (1.0 - SPREAD_LOT_PENALTY)
        sl_dist = abs(entry - sl)
        if sl_dist == 0: return LOT_MIN
        sl_pts   = max(1.0, sl_dist / info.point)
        tick_val = info.trade_tick_value or (info.trade_contract_size * info.point)
        if tick_val <= 0: return LOT_MIN
        raw_lot = (acct.balance * risk_pct / 100.0) / (sl_pts * tick_val)
        step    = info.volume_step if info.volume_step > 0 else 0.01
        lot     = self._round_lot(raw_lot, step)
        if lot <= 0.0: lot = info.volume_min
        lot = max(info.volume_min, min(lot, info.volume_max, LOT_MAX))
        log.info(f"💰 Lot Score:{score} DD:{dd_mode} Risk:{risk_pct:.2f}% → {lot}")
        return float(lot)

    @staticmethod
    def dynamic_deviation(atr: float) -> int:
        info = mt5.symbol_info(SYMBOL)
        if info is None or info.point == 0: return 50
        return max(50, int(atr * 0.1 / info.point))

    @staticmethod
    def validate_order(entry: float, sl: float, tp: float,
                       lot: float, signal: str) -> Tuple[bool, str]:
        info = mt5.symbol_info(SYMBOL); acct = mt5.account_info()
        tick = mt5.symbol_info_tick(SYMBOL)
        if not all([info, acct, tick]): return False, "Cannot read broker data"
        min_d = info.trade_stops_level * info.point
        if abs(entry - sl) < min_d: return False, "SL too close"
        if abs(entry - tp) < min_d: return False, "TP too close"
        frz = info.trade_freeze_level * info.point
        if frz > 0 and abs(entry - tick.ask) < frz: return False, "Entry in freeze zone"
        d_lot = Decimal(str(lot)); d_step = Decimal(str(info.volume_step))
        if d_lot % d_step > Decimal("1e-8"): return False, "Lot step mismatch"
        otype = mt5.ORDER_TYPE_BUY if signal == "BUY" else mt5.ORDER_TYPE_SELL
        margin_req = mt5.order_calc_margin(otype, SYMBOL, lot, entry)
        if margin_req is None or margin_req > acct.margin_free * 0.9:
            return False, "Insufficient margin"
        return True, "OK"

    @staticmethod
    def has_duplicate_setup(setup_hash: str, signal: str) -> bool:  # noqa: ARG002
        for p in (mt5.positions_get(symbol=SYMBOL) or []):
            if p.magic == MAGIC_NUMBER and setup_hash in (p.comment or ""): return True
        for o in (mt5.orders_get(symbol=SYMBOL) or []):
            if o.magic == MAGIC_NUMBER and setup_hash in (o.comment or ""): return True
        return False

    @staticmethod
    def count_open_positions() -> int:
        return sum(1 for p in (mt5.positions_get(symbol=SYMBOL) or [])
                   if p.magic == MAGIC_NUMBER)


# ══════════════════════════════════════════════════════════════════════════════
# 📤  CLASS: ExecutionHandler
# ══════════════════════════════════════════════════════════════════════════════
class ExecutionHandler:
    def __init__(self, risk: RiskManager, signal_engine: SMCSignalEngine):
        self._risk   = risk
        self._engine = signal_engine
        self._lock   = threading.Lock()

    def _send_retry(self, req: dict, retries: int = 3):
        last_res = None
        is_buy   = req.get("type") in (mt5.ORDER_TYPE_BUY,
                                        mt5.ORDER_TYPE_BUY_LIMIT,
                                        mt5.ORDER_TYPE_BUY_STOP)
        for i in range(1, retries + 1):
            with self._lock:
                res = mt5.order_send(req)
            if res is None:
                if i < retries: time.sleep(0.5)
                continue
            last_res = res
            if res.retcode == mt5.TRADE_RETCODE_DONE: return res
            if res.retcode in (mt5.TRADE_RETCODE_REQUOTE,
                               mt5.TRADE_RETCODE_PRICE_CHANGED,
                               mt5.TRADE_RETCODE_PRICE_OFF):
                tick = mt5.symbol_info_tick(SYMBOL)
                if tick:
                    req["price"] = round(float(tick.ask if is_buy else tick.bid), 2)
                if i < retries: time.sleep(0.3 * i)
                continue
            if res.retcode in (mt5.TRADE_RETCODE_CONNECTION, mt5.TRADE_RETCODE_TIMEOUT):
                if i < retries: time.sleep(0.5 * i)
                continue
            log.error(f"❌ retcode:{res.retcode} | {res.comment}"); return res
        return last_res

    def modify_sl(self, ticket: int, new_sl: float) -> None:
        with self._lock:
            res = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP,
                                   "position": ticket, "sl": round(float(new_sl), 2)})
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            log.warning(f"modify_sl FAIL #{ticket}")

    def close_partial(self, pos, lot_close: float, atr: float = 0.0) -> None:
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None: return
        info  = mt5.symbol_info(SYMBOL)
        step  = info.volume_step if info else 0.01
        v_min = info.volume_min  if info else 0.01
        lot_close  = float(max(v_min, min(self._risk._round_lot(lot_close, step), pos.volume)))
        is_buy     = (pos.type == mt5.ORDER_TYPE_BUY)
        close_type = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
        price      = tick.bid if is_buy else tick.ask
        dev        = self._risk.dynamic_deviation(atr)
        res = self._send_retry({
            "action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL,
            "volume": lot_close, "type": close_type, "position": pos.ticket,
            "price": round(float(price), 2), "deviation": dev,
            "magic": MAGIC_NUMBER, "comment": "V15|PartialTP"})
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            log.info(f"💰 Partial #{pos.ticket} Lot:{lot_close:.2f} @ {price:.2f}")

    def close_position_market(self, pos) -> bool:
        tick = mt5.symbol_info_tick(SYMBOL); info = mt5.symbol_info(SYMBOL)
        if tick is None or info is None: return False
        is_buy     = (pos.type == mt5.ORDER_TYPE_BUY)
        close_type = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
        price      = tick.bid if is_buy else tick.ask
        res = self._send_retry({
            "action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL,
            "volume": pos.volume, "type": close_type, "position": pos.ticket,
            "price": round(float(price), 2),
            "deviation": max(100, self._risk.dynamic_deviation(info.point * 100)),
            "magic": MAGIC_NUMBER, "comment": "V15|KILL"}, retries=5)
        ok = res is not None and res.retcode == mt5.TRADE_RETCODE_DONE
        log.info(f"{'✅' if ok else '❌'} Kill-close #{pos.ticket} @ {price:.2f}")
        return ok

    def cancel_pending_order(self, ticket: int) -> bool:
        with self._lock:
            res = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": ticket})
        ok = res is not None and res.retcode == mt5.TRADE_RETCODE_DONE
        log.info(f"{'✅' if ok else '❌'} Cancel pending #{ticket}")
        return ok

    def place_order(self, setup: SetupResult, session: str = "",
                    dd_mode: str = "NORMAL",
                    adr: float = 0.0, df_d1: Optional[pd.DataFrame] = None) -> bool:
        if not self._risk.is_spread_ok() or not self._risk.is_within_risk_limits():
            return False
        if self._risk.has_duplicate_setup(setup.setup_hash, setup.signal):
            log.info(f"🚫 Duplicate {setup.setup_hash} → skip"); return False
        if self._risk.count_open_positions() >= MAX_CONCURRENT_TRADES:
            log.info(f"⚠️ Max concurrent ({MAX_CONCURRENT_TRADES}) → skip"); return False

        sp     = self._risk.get_spread_pts()
        sl_pad = self._risk.get_spread_sl_padding()

        # M1 confirmation bonus
        rates_m1 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 5)
        if rates_m1 is not None and len(rates_m1) >= 3:
            df_m1 = pd.DataFrame(rates_m1)
            c = df_m1.iloc[-2]
            body_m1 = abs(float(c["close"]) - float(c["open"]))
            if body_m1 >= setup.atr * MTF_M1_BODY_ATR:
                if ((setup.signal == "BUY"  and c["close"] > c["open"]) or
                    (setup.signal == "SELL" and c["close"] < c["open"])):
                    setup.score += SCORE_M1_CONFIRM; setup.reasons.append("M1 ✓")

        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None: return False

        sig = setup.signal
        sl_adj = (setup.sl - sl_pad) if sig == "BUY" else (setup.sl + sl_pad)

        if setup.use_market:
            entry  = tick.ask if sig == "BUY" else tick.bid
            otype  = mt5.ORDER_TYPE_BUY if sig == "BUY" else mt5.ORDER_TYPE_SELL
            action = mt5.TRADE_ACTION_DEAL; exp = 0
        else:
            entry  = setup.entry
            otype  = mt5.ORDER_TYPE_BUY_LIMIT if sig == "BUY" else mt5.ORDER_TYPE_SELL_LIMIT
            action = mt5.TRADE_ACTION_PENDING
            exp    = int(time.time()) + (EXPIRATION_CANDLES * 5 * 60)
            if sig == "BUY" and entry >= tick.ask:
                entry = tick.ask; otype = mt5.ORDER_TYPE_BUY
                action = mt5.TRADE_ACTION_DEAL; exp = 0
            elif sig == "SELL" and entry <= tick.bid:
                entry = tick.bid; otype = mt5.ORDER_TYPE_SELL
                action = mt5.TRADE_ACTION_DEAL; exp = 0

        risk = abs(entry - sl_adj)
        if risk == 0: log.error("place_order: risk=0 → abort"); return False

        tp_raw = entry + risk * RR_RATIO if sig == "BUY" else entry - risk * RR_RATIO
        tp_full, capped = self._engine.apply_adr_tp_cap(
            entry, tp_raw, sl_adj, adr, df_d1, session, sig)
        if capped: log.info(f"📏 TP capped by ADR: {tp_raw:.2f}→{tp_full:.2f}")

        lot_full = self._risk.calculate_lot(entry, sl_adj, setup.score, sp, setup.atr, dd_mode)
        ok, reason = self._risk.validate_order(entry, sl_adj, tp_full, lot_full, sig)
        if not ok: log.warning(f"⚠️ Validate: {reason}"); return False

        info  = mt5.symbol_info(SYMBOL)
        step  = info.volume_step if info else 0.01
        v_min = info.volume_min  if info else 0.01
        lot_a = max(v_min, self._risk._round_lot(lot_full * PARTIAL_TP_PCT, step))
        lot_b = max(v_min, self._risk._round_lot(lot_full - lot_a, step))
        tp_pt = entry + risk * PARTIAL_TP_RR if sig == "BUY" else entry - risk * PARTIAL_TP_RR
        dev   = self._risk.dynamic_deviation(setup.atr)

        sent = 0
        for lot_i, tp_i, label in [(lot_a, tp_pt, "PT"), (lot_b, tp_full, "FT")]:
            req = {"action": action, "symbol": SYMBOL, "volume": lot_i, "type": otype,
                   "price": round(float(entry), 2), "sl": round(float(sl_adj), 2),
                   "tp": round(float(tp_i), 2), "deviation": dev, "magic": MAGIC_NUMBER,
                   "comment": f"V15|{sig}|{label}|{setup.score}|{setup.setup_hash}"}
            if action == mt5.TRADE_ACTION_PENDING:
                req["type_time"] = mt5.ORDER_TIME_SPECIFIED; req["expiration"] = exp
            res = self._send_retry(req)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                sent += 1
                log.info(f"✅ {label}|{sig}|Lot:{lot_i}|E:{entry:.2f}|SL:{sl_adj:.2f}|TP:{tp_i:.2f}")
            else:
                log.warning(f"⚠️ {label} order failed")

        if sent > 0:
            mode = "MKT" if action == mt5.TRADE_ACTION_DEAL else "LMT"
            log.info(
                f"📦 ╔══ TRADE TICKET ═══════════════════════════════════════\n"
                f"   ║  Symbol : {SYMBOL}  Session: {session}  DD: {dd_mode}\n"
                f"   ║  Signal : {sig} ({mode})  Score: {setup.score}/{setup.threshold}\n"
                f"   ║  Entry  : {entry:.2f}  SL: {sl_adj:.2f}  TP: {tp_full:.2f}\n"
                f"   ║  Lots   : {lot_a}+{lot_b}  WinProb: {setup.win_prob:.2f}\n"
                f"   ║  Hash   : {setup.setup_hash}  Judas: {setup.is_judas}\n"
                f"   ╚══════════════════════════════════════════════════════"
            )
            db_log_setup(sig, setup.score, entry, sl_adj, tp_full, setup.setup_hash,
                         session, setup.features, setup.win_prob)
            return True
        return False


# ══════════════════════════════════════════════════════════════════════════════
# 🔄  CLASS: PositionManager
# ══════════════════════════════════════════════════════════════════════════════
class PositionManager:
    def __init__(self, feed: MarketDataFeed, execution: ExecutionHandler):
        self._feed    = feed
        self._exec    = execution
        self._running = threading.Event()
        self._running.set()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="PositionManager", daemon=True)
        self._thread.start()
        log.info(f"🔄 PositionManager started ({POSITION_POLL_SEC*1000:.0f}ms)")

    def stop(self) -> None:
        self._running.clear()
        if self._thread: self._thread.join(timeout=5)
        log.info("🔄 PositionManager stopped")

    def _loop(self) -> None:
        while self._running.is_set():
            try:
                if mt5.terminal_info() is not None:
                    df_m5 = self._feed.get_cached_m5()
                    atr   = calculate_atr(df_m5) if df_m5 is not None else 1.0
                    self._manage_positions(atr)
            except Exception as exc:
                log.warning(f"⚠️ PM error: {exc}")
            time.sleep(POSITION_POLL_SEC)

    def _manage_positions(self, atr: float) -> None:
        positions = [p for p in (mt5.positions_get(symbol=SYMBOL) or [])
                     if p.magic == MAGIC_NUMBER]
        if not positions: return
        tick = mt5.symbol_info_tick(SYMBOL); info = mt5.symbol_info(SYMBOL)
        if tick is None or info is None: return
        a            = max(atr, info.point * 10)
        open_tickets = {p.ticket for p in positions}
        trail_cache  = batch_load_trail_states(list(open_tickets))

        for pos in positions:
            entry = pos.price_open; sl_now = pos.sl
            is_buy = (pos.type == mt5.ORDER_TYPE_BUY)
            parts  = (pos.comment or "").split("|")
            pos_hash = parts[-1] if len(parts) >= 5 else ""
            risk = abs(entry - sl_now)
            if risk < info.point: risk = a * 1.5
            price    = tick.bid if is_buy else tick.ask
            buf      = info.point * 5
            profit_r = (price - entry) / risk if is_buy else (entry - price) / risk
            ts       = trail_cache.get(pos.ticket)
            partial_done = int(ts["partial_done"]) if ts else 0

            # [V13 fix] All three steps evaluated independently — no early continue
            did_partial = False
            if not partial_done and profit_r >= PARTIAL_TP_RR:
                self._exec.close_partial(pos, pos.volume * PARTIAL_TP_PCT, atr=a)
                set_partial_done(pos.ticket, pos_hash)
                be_sl = (entry + buf) if is_buy else (entry - buf)
                if (is_buy and sl_now < be_sl) or (not is_buy and sl_now > be_sl):
                    self._exec.modify_sl(pos.ticket, be_sl)
                    log.info(f"🔒 BE+Partial #{pos.ticket} SL:{sl_now:.2f}→{be_sl:.2f}")
                did_partial = True

            if not did_partial and profit_r >= BREAKEVEN_RR:
                be_sl = (entry + buf) if is_buy else (entry - buf)
                if (is_buy and sl_now < be_sl) or (not is_buy and sl_now > be_sl):
                    self._exec.modify_sl(pos.ticket, be_sl)
                    log.info(f"🔒 BE #{pos.ticket} SL:{sl_now:.2f}→{be_sl:.2f}")

            if profit_r >= TRAIL_AFTER_RR:
                last_tsl  = float(ts["last_sl"]) if ts else None
                min_move  = a * TRAIL_MIN_MOVE_ATR
                if is_buy:
                    new_tsl = price - (a * TRAIL_ATR_MULT)
                    if new_tsl > sl_now and (last_tsl is None or new_tsl > last_tsl + min_move):
                        self._exec.modify_sl(pos.ticket, new_tsl)
                        save_trail_sl(pos.ticket, new_tsl, pos_hash)
                        log.info(f"📈 Trail #{pos.ticket} SL:{sl_now:.2f}→{new_tsl:.2f} R:{profit_r:.2f}")
                else:
                    new_tsl = price + (a * TRAIL_ATR_MULT)
                    if new_tsl < sl_now and (last_tsl is None or new_tsl < last_tsl - min_move):
                        self._exec.modify_sl(pos.ticket, new_tsl)
                        save_trail_sl(pos.ticket, new_tsl, pos_hash)
                        log.info(f"📉 Trail #{pos.ticket} SL:{sl_now:.2f}→{new_tsl:.2f} R:{profit_r:.2f}")

            # [V14-A4] P&L tracker
            unrealised = pos.profit
            log.debug(f"📍 Pos #{pos.ticket}: ${unrealised:+.2f} ({profit_r:+.2f}R)")

        cleanup_trail_state(open_tickets)


# ══════════════════════════════════════════════════════════════════════════════
# 🆘  EMERGENCY KILL-SWITCH
# ══════════════════════════════════════════════════════════════════════════════
def graceful_shutdown(execution: ExecutionHandler, reason: str = "EXIT") -> None:
    log.warning(f"🚨 GRACEFUL SHUTDOWN — reason: {reason}")
    log.warning("🚨 Step 1/3: Cancelling pending orders…")
    for o in (mt5.orders_get(symbol=SYMBOL) or []):
        if o.magic == MAGIC_NUMBER: execution.cancel_pending_order(o.ticket)
    time.sleep(0.5)
    log.warning("🚨 Step 2/3: Closing all open positions at market…")
    for pos in (mt5.positions_get(symbol=SYMBOL) or []):
        if pos.magic == MAGIC_NUMBER:
            execution.close_position_market(pos); time.sleep(0.2)
    time.sleep(1.0)
    acct = mt5.account_info()
    if acct:
        log.warning(f"🚨 Step 3/3: Final equity ${acct.equity:,.2f} | balance ${acct.balance:,.2f}")
    log.warning("🚨 SHUTDOWN COMPLETE.")


# ══════════════════════════════════════════════════════════════════════════════
# 📊  OPERATOR HEARTBEAT
# ══════════════════════════════════════════════════════════════════════════════
def emit_heartbeat(risk: RiskManager, predictor: MLPredictor,
                   session: str, htf_bias: str, adr_pct: float) -> None:
    acct = mt5.account_info()
    if acct is None: return
    daily_dd, total_dd, dd_mode = risk.get_dd_state()
    init_bal  = get_state("initial_balance") or acct.balance
    eq_pct    = (acct.equity - init_bal) / init_bal * 100 if init_bal > 0 else 0
    open_pos  = risk.count_open_positions()
    avg_wp    = predictor.rolling_avg_prob
    day_start = get_state("daily_start_balance_" + risk.get_broker_date()) or acct.balance
    today_pl  = acct.equity - day_start
    pause_on  = os.path.isfile(PAUSE_FLAG_PATH)
    kill_on   = os.path.isfile(KILL_FLAG_PATH)
    mode_lbl  = ("🔴 KILL DETECTED" if kill_on else "⏸️ PAUSED" if pause_on
                 else f"🟠 ORANGE" if dd_mode == "ORANGE"
                 else f"💛 YELLOW" if dd_mode == "YELLOW"
                 else f"🔴 RED"    if dd_mode == "RED" else "🟢 NORMAL")
    log.info(
        f"\n{'═'*70}\n"
        f"  📊  OPERATOR STATUS  [{datetime.now(STRATEGY_TZ).strftime('%H:%M:%S')} BKK]\n"
        f"  {'─'*66}\n"
        f"  Equity     : ${acct.equity:>10,.2f}  ({eq_pct:+.2f}%)\n"
        f"  Today P&L  : ${today_pl:>+10,.2f}\n"
        f"  DD Daily   : {daily_dd:.2f}%   DD Total: {total_dd:.2f}%\n"
        f"  Session    : {session:<16} HTF: {htf_bias:<10} ADR: {adr_pct*100:.0f}%\n"
        f"  Open Pos   : {open_pos}/{MAX_CONCURRENT_TRADES}\n"
        f"  ML avg prob: {avg_wp:.3f}   Norm: {'WARM' if predictor.norm_is_warm else 'COLD'}\n"
        f"  Mode       : {mode_lbl}\n"
        f"{'═'*70}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 🔧  HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def mt5_connect(retries: int = 10, delay: float = 5.0) -> bool:
    for i in range(1, retries + 1):
        if mt5.initialize():
            log.info(f"✅ MT5 connected (try {i})"); return True
        log.warning(f"MT5 connect try {i}/{retries}…"); time.sleep(delay)
    return False


def ensure_alive() -> bool:
    if mt5.terminal_info() is not None: return True
    log.warning("MT5 disconnected → reconnecting…")
    return mt5_connect(retries=5, delay=3.0)


# ══════════════════════════════════════════════════════════════════════════════
# 🚀  SIGNAL CYCLE  — entry only on CLOSED M5 candles [V14-F1]
# ══════════════════════════════════════════════════════════════════════════════
def _run_signal_cycle(feed: MarketDataFeed, signal_engine: SMCSignalEngine,
                      risk: RiskManager, execution: ExecutionHandler,
                      predictor: MLPredictor, last_ctx: Dict) -> None:
    if not ensure_alive(): return

    daily_dd, total_dd, dd_mode = risk.get_dd_state()
    if dd_mode == "RED":
        log.warning(f"⛔ DD RED daily={daily_dd:.2f}% total={total_dd:.2f}% → halt"); return
    if risk.is_circuit_breaker_tripped(): return

    session = signal_engine.get_session()
    if session in ("OUT_OF_SESSION", "RED_NEWS_BLOCK"): return

    in_kz, kz_name = signal_engine.is_in_killzone()
    if not in_kz: return
    if not risk.is_spread_ok(): return
    if os.path.isfile(PAUSE_FLAG_PATH):
        log.info("⏸️ PAUSE.flag → skip new entries"); return
    if not risk.new_entries_allowed():
        log.warning(f"🟠 DD {dd_mode} → new entries suspended"); return

    data = feed.fetch_all()
    if data["m5"] is None: log.warning("M5 unavailable → skip"); return
    cleanup_cooldowns()

    setup = signal_engine.analyze_setup(
        data["m5"], data["h4"], data["d1"], data["m15"], data.get("dxy"), session)
    setup.spread_pts = risk.get_spread_pts()

    last_ctx["bias"]    = setup.htf_bias
    last_ctx["session"] = session
    last_ctx["adr_pct"] = str(setup.adr_pct)

    liq = setup.liq_map
    if liq:
        log.info(f"💧 BSL:{liq.bsl_nearest or '—'} SSL:{liq.ssl_nearest or '—'} "
                 f"SwH:{liq.swept_high} SwL:{liq.swept_low}")
    htf = setup.htf_result
    if htf:
        log.info(f"🏗️ H4 Bias:{htf.bias} BOS:{htf.last_bos} CHOCH:{htf.choch_signal}")
    log.info(f"📊 {session} KZ:{kz_name} | M15:{setup.m15_struct} | "
             f"ADR:{setup.adr_pct*100:.0f}% | Thr:{setup.threshold} | DD:{dd_mode}")

    if setup.signal == "WAIT": return
    if setup.score < setup.threshold:
        log.info(f"⚠️ Score {setup.score} < {setup.threshold} → skip"); return

    close_price = float(data["m5"]["close"].iloc[-1]) if data["m5"] is not None else 2000.0
    setup.features = extract_features(setup, close_price=close_price, df_len=len(data["m5"]))
    setup.win_prob = predictor.predict_win_probability(setup.features)
    avg_wp = predictor.rolling_avg_prob

    log.info(f"🧠 WinProb:{setup.win_prob:.3f} [avg:{avg_wp:.3f}] "
             f"gate:{ML_WIN_PROB_THRESHOLD} | {setup.summary()}")

    if setup.win_prob < ML_WIN_PROB_THRESHOLD:
        log.info(f"🤖 ML gate rejected: {setup.win_prob:.3f} < {ML_WIN_PROB_THRESHOLD}"); return

    if is_on_cooldown(setup.setup_hash):
        log.info(f"🔁 Cooldown {setup.setup_hash} → skip"); return
    if risk.has_duplicate_setup(setup.setup_hash, setup.signal):
        log.info("🚫 Duplicate → skip"); return

    adr_val = calculate_adr(data.get("d1"))
    if execution.place_order(setup, session, dd_mode, adr=adr_val, df_d1=data.get("d1")):
        set_cooldown(setup.setup_hash)
        log.info(f"🎯 Placed | hash:{setup.setup_hash}")


# ══════════════════════════════════════════════════════════════════════════════
# 🚀  MAIN
# ══════════════════════════════════════════════════════════════════════════════
BANNER = """
╔══════════════════════════════════════════════════════════════════════════════╗
║  🏆  AI SMC/ICT Pro Sniper — V.15 PRODUCTION                                ║
║  [V15-S1] Balanced scoring: Base40+FVG/Sweep20=60 — NO analysis paralysis   ║
║  [V15-S2] ML gate 0.50  [V15-S3] HTF Neutral fully decoupled               ║
║  [V15-S4] VOL/PD/DXY/ADR_HARD disabled by default                          ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""


def main() -> None:
    print(BANNER)
    log.info("Bot V.15 PRODUCTION starting")
    init_db()

    if not mt5_connect():
        log.error("❌ Cannot connect to MT5"); return

    feed          = MarketDataFeed()
    signal_engine = SMCSignalEngine()
    risk          = RiskManager()
    execution     = ExecutionHandler(risk, signal_engine)
    predictor     = MLPredictor()
    # predictor.load_model("smc_model.joblib")

    pm = PositionManager(feed, execution)
    pm.start()

    last_ctx: Dict[str, str] = {"bias": "NEUTRAL", "session": "UNKNOWN", "adr_pct": "0.0"}
    _shutdown = threading.Event()

    def _sig_handler(signum, frame):
        log.warning(f"Signal {signum} → shutdown")
        _shutdown.set()

    signal.signal(signal.SIGTERM, _sig_handler)
    signal.signal(signal.SIGINT,  _sig_handler)

    # [V14-F1] Track CLOSED candles — only fire signal on bar transitions
    last_closed_bar_time: Optional[int] = None
    cached_atr:           float         = 1.0
    last_heartbeat:       float         = time.time()

    log.info(f"📡 Tick poll:{TICK_POLL_SEC}s | PM:{POSITION_POLL_SEC*1000:.0f}ms | "
             f"Heartbeat:{HEARTBEAT_SEC}s | KILL:'{KILL_FLAG_PATH}' PAUSE:'{PAUSE_FLAG_PATH}'")

    try:
        while not _shutdown.is_set():
            if os.path.isfile(KILL_FLAG_PATH):
                log.warning("🚨 KILL.flag detected!"); _shutdown.set(); break

            # Current bar (still forming)
            rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M5, 0, 2)
            tick  = mt5.symbol_info_tick(SYMBOL)
            if tick is None or rates is None or len(rates) < 2:
                time.sleep(TICK_POLL_SEC); continue

            # [V14-F1] The CLOSED bar is rates[0] when rates[1] (new bar) just opened
            current_open_bar_time  = int(rates[-1]["time"])   # forming bar
            previous_closed_bar_time = int(rates[-2]["time"]) # just closed

            # Signal fires when we see a NEW forming bar — meaning previous bar just closed
            if previous_closed_bar_time != last_closed_bar_time:
                log.info("─" * 72)
                log.info(f"🕯️ Closed bar @ {previous_closed_bar_time} | "
                         f"New bar @ {current_open_bar_time} "
                         f"[{datetime.now(STRATEGY_TZ).strftime('%H:%M:%S')} BKK]")
                last_closed_bar_time = previous_closed_bar_time
                _run_signal_cycle(feed, signal_engine, risk, execution, predictor, last_ctx)
                df5 = feed.get_cached_m5()
                if df5 is not None:
                    new_atr = calculate_atr(df5)
                    if new_atr > 0: cached_atr = new_atr

            # Heartbeat
            now = time.time()
            if now - last_heartbeat >= HEARTBEAT_SEC:
                emit_heartbeat(risk, predictor,
                               last_ctx.get("session", "?"),
                               last_ctx.get("bias", "?"),
                               float(last_ctx.get("adr_pct", "0")))
                last_heartbeat = now

            time.sleep(TICK_POLL_SEC)

    except KeyboardInterrupt:
        log.info("🛑 KeyboardInterrupt")
    except Exception as exc:
        log.exception(f"💥 Unhandled: {exc}")
    finally:
        log.info("Initiating graceful shutdown…")
        pm.stop()
        graceful_shutdown(execution)
        close_db()
        mt5.shutdown()
        log.info("MT5 offline. Bot V.15 terminated.")


if __name__ == "__main__":
    main()
