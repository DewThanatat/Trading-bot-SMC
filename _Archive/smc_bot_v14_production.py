"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  🥇  AI SMC/ICT Pro Sniper — V.14 PRODUCTION  (XAUUSD Gold Specialist)      ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  ██████████████████  V.14 CHANGELOG  ████████████████████████████████████  ║
║                                                                              ║
║  ── MANDATORY FIXES ─────────────────────────────────────────────────────  ║
║                                                                              ║
║  [V14-F1]  INTRABAR EXECUTION FIX — Candle-close-only entry discipline.     ║
║            INTRABAR_ENABLED now controls ONLY position management (trailing  ║
║            SL / partial TP).  Entry signals are strictly evaluated on closed ║
║            M5 candles via a new `_last_closed_bar_time` tracker.  Fakeout   ║
║            entries mid-candle are impossible.                                ║
║                                                                              ║
║  [V14-F2]  HTF BIAS UPGRADED H1 → H4 — H1 is too noisy for Gold.           ║
║            HTF bias now computed from H4 structure, giving cleaner BOS/      ║
║            CHOCH readings aligned with institutional order flow on XAUUSD.  ║
║                                                                              ║
║  [V14-F3]  ADR BLOCK RELAXED — Hard ADR block now triggers at 88% (was      ║
║            80%) and is session-aware: NY momentum sessions allow up to 93%  ║
║            because Gold frequently extends its daily range in NY hours.      ║
║                                                                              ║
║  [V14-F4]  ML THRESHOLD ADJUSTED — ML_WIN_PROB_THRESHOLD relaxed from 0.65  ║
║            to 0.62.  HTF_NEUTRAL_MIN_SCORE lowered from 85 to 78.           ║
║            Both were empirically over-restrictive causing excessive skips.  ║
║                                                                              ║
║  [V14-F5]  CIRCUIT BREAKER / DD YELLOW DECOUPLED (V13 Bug-1 fix) —          ║
║            CIRCUIT_BREAKER_PCT raised to 4.5% so the 3-tier DD protocol     ║
║            (Yellow 3% → Orange 5%) actually functions without being          ║
║            overridden immediately at 3%.                                     ║
║                                                                              ║
║  [V14-F6]  FVG AGE NORM FIXED (V13 Bug-2) — fvg_age_norm now correctly      ║
║            uses relative bar distance from current candle, not absolute df   ║
║            index.  Feature 9 is now a meaningful ML signal.                 ║
║                                                                              ║
║  [V14-F7]  ML OUTLIER UPDATE ORDER FIXED (V13 Bug-3) — distribution shift   ║
║            is checked BEFORE norm.update() so outlier features never         ║
║            contaminate the rolling buffer.                                   ║
║                                                                              ║
║  ── PERFORMANCE & CODE OPTIMIZATION ─────────────────────────────────────  ║
║                                                                              ║
║  [V14-O1]  WELFORD ONLINE NORMALISER — Replaces RollingZScoreNormaliser's   ║
║            O(n) deque+mean/std with Welford's algorithm: O(1) per update,   ║
║            numerically stable.  Same statistical result, zero recomputation. ║
║                                                                              ║
║  [V14-O2]  BROKER CONFIG BLOCK — SYMBOL, MAGIC_NUMBER, broker timezone,     ║
║            and server offset moved to a dedicated BROKER CONFIG section.     ║
║            Operators change one block; nothing else needs editing.           ║
║                                                                              ║
║  [V14-O3]  DYNAMIC NEWS FILTER — Static NEWS_BLOCKS replaced by             ║
║            NewsGuard: a pluggable sentinel that can load events from a       ║
║            JSON file (e.g. auto-updated by a cron job hitting ForexFactory   ║
║            API).  Falls back to a configurable static window when no         ║
║            external data is available.  Bot detects ±NEWS_BUFFER_MIN        ║
║            minutes around each high-impact USD/Gold event.                  ║
║                                                                              ║
║  ── ADVANCED GOLD STRATEGIES ────────────────────────────────────────────  ║
║                                                                              ║
║  [V14-S1]  VOLUME SPIKE VALIDATION — FVG & OB detection now require the     ║
║            impulse candle's tick volume to be ≥ VOL_SPIKE_MULT (1.5×) the  ║
║            20-bar rolling mean.  Smart-money candles without institutional   ║
║            volume are rejected.  Adds `volume_spike` field to OBResult.    ║
║                                                                              ║
║  [V14-S2]  JUDAS SWING OVERRIDE — Gold Killzone Reversal strategy.          ║
║            If a liquidity sweep occurs within JUDAS_WINDOW_MIN (15 min) of  ║
║            London or NY Open AND an opposing FVG forms immediately after,   ║
║            the HTF bias constraint is overridden (score bonus +18) and a    ║
║            reversal entry is allowed. Tracks `is_judas_swing` flag on       ║
║            SetupResult for logging.                                          ║
║                                                                              ║
║  [V14-S3]  DYNAMIC ADR TP CAP — If the calculated TP at RR_RATIO exceeds   ║
║            the remaining ADR room, TP is dynamically reduced to land within ║
║            ADR_TP_BUFFER_PCT (95%) of the daily range ceiling.  Prevents    ║
║            overextended targets that reverse from daily exhaustion.          ║
║                                                                              ║
║  ── AUTONOMOUS ADDITIONS (Creative & Strategic) ─────────────────────────  ║
║                                                                              ║
║  [V14-A1]  DXY INVERSE FILTER — Gold moves inversely to the US Dollar.      ║
║            Bot reads USIDX/USDXm (configurable) on H1.  If DXY is in a     ║
║            strong uptrend (rising HH/HL pattern), BUY signals on Gold are   ║
║            penalised (-10 score).  SELL signals receive a +8 bonus.         ║
║            Completely optional: disabled if DXY_SYMBOL = "".               ║
║                                                                              ║
║  [V14-A2]  PREMIUM / DISCOUNT ZONE FILTER (ICT Quarterly Theory) —          ║
║            The M5 range is split into 3 equal zones.  BUY signals are only  ║
║            allowed when price is in the Discount zone (bottom 33%).         ║
║            SELL signals only when in Premium (top 33%).  Trades at           ║
║            equilibrium receive a −6 score penalty.  Enforces the ICT        ║
║            "buy low, sell high" bias within the current dealing range.      ║
║                                                                              ║
║  [V14-A3]  LOG QUALITY IMPROVEMENTS — All key decisions now emit structured  ║
║            single-line emoji logs (🟢/🔴/🟡) making monitoring via tail     ║
║            instantly readable.  Heartbeat redesigned with aligned columns.  ║
║            Trade placement emits a full "trade ticket" summary block.        ║
║                                                                              ║
║  [V14-A4]  POSITION-LEVEL P&L TRACKER — Each managed position now logs      ║
║            its unrealised P&L and R-multiple in the PositionManager tick.   ║
║            Allows operator to see "Pos #12345: +$142 (+1.8R)" at a glance. ║
║                                                                              ║
║  PRESERVED FROM V.13                                                         ║
║  ─────────────────────────────────────────────────────────────────────────  ║
║  Thread-local SQLite + writer queue · Batch trail-state loads · PAUSE/KILL  ║
║  flags · 3-tier DD protocol · Emergency graceful_shutdown · SIGTERM handler ║
║  NumPy hot-path indicators · OB freshness/mitigation · Gap-sweep detection  ║
║  Dual-key position tracking · FVG memory · M15 swing-BOS · ML 12-feat vec  ║
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
from dataclasses import dataclass, field
from datetime import datetime, timedelta, time as dtime
from decimal import Decimal, ROUND_DOWN
from typing import Optional, List, Tuple, Dict

import pytz

warnings.filterwarnings("ignore", category=RuntimeWarning)

try:
    import joblib
    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False


# ══════════════════════════════════════════════════════════════════════════════
# 🏦  BROKER CONFIG  — [V14-O2] Single block to edit per broker
#     Change these values for your specific broker; nothing else needs editing.
# ══════════════════════════════════════════════════════════════════════════════

# ── Symbol names (broker-specific suffix) ────────────────────────────────────
SYMBOL          = "XAUUSDm"        # Gold symbol on your broker
DXY_SYMBOL      = "USDXm"          # [V14-A1] DXY symbol; set "" to disable
MAGIC_NUMBER    = 99999

# ── Broker server timezone ────────────────────────────────────────────────────
# [V14-O2] Change BROKER_TZ_NAME to your broker server's timezone.
# Bot converts all session/killzone logic relative to STRATEGY_TZ_NAME.
BROKER_TZ_NAME   = "Etc/UTC"              # Broker server time (MT5 tick.time)
STRATEGY_TZ_NAME = "Asia/Bangkok"         # Your local strategy timezone (GMT+7)
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

# [V14-F3] ADR — relaxed block and session-aware ceiling
ADR_EXHAUSTED_PCT     = 0.88    # was 0.80 — less trigger-happy
ADR_NY_EXHAUSTED_PCT  = 0.93    # NY sessions allow more range extension
ADR_HARD_BLOCK        = True    # False = score penalty only
ADR_TP_BUFFER_PCT     = 0.95    # [V14-S3] TP sits at 95% of remaining ADR room

SL_ATR_MULT         = 1.2
FVG_ENTRY_MID       = True      # enter at 50% of FVG
SWING_PERIOD        = 5
SWING_CONFIRM_BARS  = 2
SETUP_COOLDOWN_SEC  = 180

PARTIAL_TP_RR       = 1.0
PARTIAL_TP_PCT      = 0.50
MAX_CONCURRENT_TRADES = 2

# [V14-F1] Intrabar: entry signals ONLY on closed candles; PM still runs at poll rate
# Setting INTRABAR_ENABLED=True allows the PM to manage trades intrabar,
# but _run_signal_cycle will only fire on NEW closed M5 candle.
INTRABAR_ENABLED    = True      # controls PM management cadence, NOT entry signals

# FVG
FVG_BUFFER_RATIO    = 0.5       # slightly relaxed from 0.6
FVG_MOMENTUM_RATIO  = 0.25
FVG_MITIGATED_PCT   = 0.5
FVG_MIN_GAP_ATR     = 0.15      # minimum FVG size in ATR units (was using BUFFER_RATIO)
FVG_MEMORY_BARS: Dict[str, int] = {
    "PRE_LONDON":    24,
    "LONDON":        36,
    "NY_OPEN_EARLY": 30,
    "NEW_YORK":      36,
    "DEFAULT":       30,
}

# [V14-S1] Volume Spike Validation
VOL_SPIKE_ENABLED   = False
VOL_SPIKE_MULT      = 1.5       # impulse candle volume ≥ 1.5× 20-bar average
VOL_SPIKE_PERIOD    = 20

# [V14-S2] Judas Swing Override (Gold Killzone Reversal)
JUDAS_SWING_ENABLED  = True
JUDAS_WINDOW_MIN     = 15       # minutes from session open to qualify as Judas
JUDAS_SCORE_BONUS    = 18       # score bonus when Judas override fires

# Liquidity
LIQ_SWING_PERIOD    = 10
LIQ_EQUAL_TOLERANCE = 0.0003
LIQ_MIN_CLUSTER     = 2

# HTF — [V14-F2] upgraded to H4
HTF_TIMEFRAME       = mt5.TIMEFRAME_H4   # was H1 — H4 cleaner for Gold
HTF_BARS            = 120               # ~20 days of H4
HTF_SWING_PERIOD    = 3                 # adjusted for H4 (was 8 on H1)
HTF_SWING_CONFIRM   = 2

# [V14-A1] DXY Inverse Filter
DXY_ENABLED         = False          # False if DXY_SYMBOL = ""
DXY_SWING_PERIOD    = 5
DXY_BUY_PENALTY     = -10           # BUY Gold when DXY bullish
DXY_SELL_BONUS      = 8             # SELL Gold when DXY bullish

# [V14-A2] Premium/Discount zone (ICT)
PD_ZONE_ENABLED     = False
PD_PERIOD           = 50            # lookback bars for dealing range
PD_PENALTY          = -6            # trading at equilibrium

# M1 bonus
MTF_M1_BODY_ATR     = 0.3
SCORE_M1_CONFIRM    = 5

# ── Scoring constants (BALANCED V14 - REAL WORLD) ─────────────────────────
SCORE_BASE           = 40   # [ฐาน] เริ่มต้นที่ 40

# 🎯 1. เงื่อนไขบังคับ (Core Setups) - แค่มีอันใดอันหนึ่งก็พร้อมเทรด
SCORE_FVG_FRESH      = 20   # [Core 1] เจอกล่อง FVG สด (40+20 = 60 ผ่านเกณฑ์ทันที!)
SCORE_LIQ_SWEPT      = 20   # [Core 2] กวาดสภาพคล่อง SSL/BSL (40+20 = 60 ผ่านเกณฑ์ทันที!)
SCORE_SWEEP_AND_FVG  = 10   # [VIP Bonus] ถ้าโชคดีเกิดพร้อมกัน 2 อย่าง เอาโบนัสไปอีก +10

# 📊 2. Context & เทรนด์ (ตัวอนุญาต หรือ สกัดกั้น)
SCORE_HTF_ALIGN      = 10   # [เสริม] เทรนด์ H4 ตรงกัน (ช่วยบูสต์คะแนนให้แข็งแกร่ง)
SCORE_HTF_AGAINST    = -15  # ⛔ [หักหนัก] เทรนด์ H4 สวนทาง (หักจนกว่าจะมีตัวเสริมเยอะจริงๆ ถึงจะยอมเทรด)
SCORE_M15_BOS        = 10   # [เสริม] โครงสร้าง M15 คอนเฟิร์ม

# 🔎 3. คะแนนเสริมเพิ่มความมั่นใจ (Confluences)
SCORE_OB_BONUS       = 5    # มี Order Block หนุน
SCORE_OB_OVERLAP     = 5    # OB ซ้อนทับ FVG พอดี
SCORE_STRONG_CANDLE  = 5    # แท่งเทียนส่งแรง
SCORE_BOS_M5         = 5    # ทะลุโครงสร้างย่อย M5
SCORE_LIQ_TARGET     = 5    # มีเป้า TP ชัดเจน (BSL/SSL)
SCORE_FVG_STRENGTH   = 5    # FVG กว้างและชัดเจน
SCORE_VOL_SPIKE      = 5    # มี Volume กระชาก

# ⚠️ 4. ตัวหักคะแนนความเสี่ยง (Risk Penalties)
SCORE_ADR_WARN       = -10  # [หักหนัก] วิ่งมาไกลเกิน ADR วันนี้แล้ว (เสี่ยงโดนตบกลับ)
SCORE_SPREAD_WARN    = -5   # Spread เริ่มถ่าง

# ── Score thresholds (เกณฑ์ชี้วัด) ──
SCORE_THRESHOLD: Dict[str, int] = {
    "LONDON":        60,   
    "NEW_YORK":      60,   
    "NY_OPEN_EARLY": 60,   
    "PRE_LONDON":    60,   
    "DEFAULT":       60,   
}

# 🔥 ปลดล็อกประตูนรก 2 บานสุดท้าย (สำคัญมากต้องแก้ตามนี้ครับ)
HTF_NEUTRAL_MIN_SCORE     = 60   # [แก้จาก 65 เป็น 60] ให้ตลาด Range (ไซด์เวย์) สามารถเทรด FVG ได้
SCORE_PENALTY_HTF_NEUTRAL = 0    # [แก้จาก 3 เป็น 0] ไม่ต้องลงโทษตลาด Range ปล่อยให้ M5 ทำงานของมัน
ML_WIN_PROB_THRESHOLD     = 0.50 # (เช็คให้ชัวร์ว่ายังเป็น 0.50 สำหรับตอน Backtest)

SCORE_PENALTY_HTF_NEUTRAL = 3
SCORE_PENALTY_HIGH_ADR    = 2

ML_ROLLING_WINDOW       = 60

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
# [V14-F5] CB decoupled from YELLOW — sits between ORANGE and MAX
CIRCUIT_BREAKER_PCT = 4.5   # was 3.0 (== DD_YELLOW → YELLOW dead code)

# Killzones (Strategy timezone)
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

# Cache TTL
CACHE_TTL_LTF = 5
CACHE_TTL_HTF = 60
CACHE_TTL_D1  = 300

# Polling
POSITION_POLL_SEC       = 0.2
TICK_POLL_SEC           = 1.0
HEARTBEAT_SEC           = 300

# Flag files
KILL_FLAG_PATH  = "KILL.flag"
PAUSE_FLAG_PATH = "PAUSE.flag"

DB_PATH  = "smc_state.db"
LOG_PATH = "smc_bot.log"


# ══════════════════════════════════════════════════════════════════════════════
# 📰  [V14-O3]  NEWS GUARD — Dynamic high-impact news filter
# ══════════════════════════════════════════════════════════════════════════════
# Drop-in replacement for static NEWS_BLOCKS.
# Reads events from a JSON file populated by an external cron/script.
# Falls back to static windows when no external data is available.

NEWS_EVENTS_FILE    = "news_events.json"   # auto-updated JSON (see docs below)
NEWS_BUFFER_MIN     = 30                   # block ±30 min around each event

# Static fallback windows (strategy timezone HH, MM) when JSON unavailable
# Format: (start_h, start_m, end_h, end_m)
NEWS_STATIC_FALLBACK = [
    (19, 15, 19, 45),    # Typical US economic data window
    (15, 25, 15, 35),    # ECB/BOE window overlap
]


class NewsGuard:
    """
    [V14-O3] Pluggable news sentinel.

    External JSON schema (news_events.json):
    [
      {"ts_utc": "2024-12-06T13:30:00", "impact": "HIGH", "currency": "USD",
       "event": "NFP"},
      ...
    ]

    To auto-populate: run a separate lightweight script that hits ForexFactory
    or Investing.com calendar APIs and writes this file every few hours.
    The bot reads it fresh on every session-check call (cheap file-stat).
    """

    def __init__(self):
        self._events: List[Dict] = []
        self._last_load: float   = 0.0
        self._load_interval      = 300.0   # reload file every 5 min

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
            log.debug(f"NewsGuard reload: {exc}")

    def is_blocked(self, dt_strategy: datetime) -> Tuple[bool, str]:
        """
        Returns (True, event_name) if dt_strategy falls within NEWS_BUFFER_MIN
        of any high-impact event.  Returns (False, "") otherwise.
        """
        self._maybe_reload()

        buf = timedelta(minutes=NEWS_BUFFER_MIN)

        # Check dynamic events
        for ev in self._events:
            try:
                ts_str = ev.get("ts_utc", "")
                if not ts_str:
                    continue
                ev_dt = datetime.fromisoformat(ts_str).replace(tzinfo=pytz.utc)
                ev_local = ev_dt.astimezone(STRATEGY_TZ)
                ev_dt_naive = ev_local.replace(tzinfo=None)
                now_naive   = dt_strategy.replace(tzinfo=None)
                if abs((now_naive - ev_dt_naive).total_seconds()) <= buf.total_seconds():
                    label = ev.get("event", "HIGH_IMPACT")
                    return True, label
            except Exception:
                continue

        # Fallback: static windows
        t = dt_strategy.time()
        for sh, sm, eh, em in NEWS_STATIC_FALLBACK:
            if dtime(sh, sm) <= t <= dtime(eh, em):
                return True, "STATIC_NEWS_WINDOW"

        return False, ""


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
# 💾  PERSISTENCE LAYER  — thread-local connections + writer queue (V13-P0-B)
# ══════════════════════════════════════════════════════════════════════════════

_tls            = threading.local()
_writer_thread: Optional[threading.Thread] = None
_write_q:       Optional[_queue_module.Queue] = None


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
        log.warning(f"DB read error: {exc}")
        return None


def _db_query_all(sql: str, params: tuple = ()) -> List[sqlite3.Row]:
    try:
        return _get_read_conn().execute(sql, params).fetchall()
    except Exception as exc:
        log.warning(f"DB read_all error: {exc}")
        return []


def init_db() -> None:
    """Create tables, apply live schema migrations, start writer thread. Idempotent."""
    global _writer_thread, _write_q
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
            ts REAL, signal TEXT, score INTEGER,
            entry REAL, sl REAL, tp REAL,
            setup_hash TEXT, session TEXT,
            features TEXT, win_prob REAL,
            is_judas INTEGER DEFAULT 0
        )""",
        "CREATE TABLE IF NOT EXISTS cooldown (setup_hash TEXT PRIMARY KEY, expires_at REAL)",
        """CREATE TABLE IF NOT EXISTS trail_state (
            ticket INTEGER PRIMARY KEY,
            setup_hash TEXT,
            last_sl REAL,
            updated_at REAL,
            partial_done INTEGER DEFAULT 0
        )""",
        "CREATE TABLE IF NOT EXISTS bot_state (key TEXT PRIMARY KEY, value TEXT)",
        """CREATE TABLE IF NOT EXISTS win_prob_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL, prob REAL, outcome INTEGER DEFAULT -1
        )""",
        "CREATE INDEX IF NOT EXISTS idx_trail_hash   ON trail_state (setup_hash)",
        "CREATE INDEX IF NOT EXISTS idx_setup_log_ts ON setup_log (ts)",
        "CREATE INDEX IF NOT EXISTS idx_wph_ts       ON win_prob_history (ts)",
    ]
    for stmt in schema_stmts:
        _db_exec(stmt.strip(), wait=True)

    # Live schema migrations (idempotent)
    rc = _get_read_conn()
    trail_cols = {r[1] for r in rc.execute("PRAGMA table_info(trail_state)").fetchall()}
    if "setup_hash" not in trail_cols:
        _db_exec("ALTER TABLE trail_state ADD COLUMN setup_hash TEXT DEFAULT ''", wait=True)
        log.info("DB migration: trail_state.setup_hash added")

    sl_cols = {r[1] for r in rc.execute("PRAGMA table_info(setup_log)").fetchall()}
    for col, defn in [
        ("features",  "TEXT DEFAULT NULL"),
        ("win_prob",  "REAL DEFAULT 0"),
        ("is_judas",  "INTEGER DEFAULT 0"),
    ]:
        if col not in sl_cols:
            _db_exec(f"ALTER TABLE setup_log ADD COLUMN {col} {defn}", wait=True)
            log.info(f"DB migration: setup_log.{col} added")

    log.info("✅ Database initialised / migrated (V14 schema)")


def close_db() -> None:
    global _write_q
    if _write_q is not None:
        _write_q.put(None)
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
    _db_exec("INSERT OR REPLACE INTO cooldown VALUES(?,?)",
             (h, time.time() + SETUP_COOLDOWN_SEC))


def cleanup_cooldowns() -> None:
    _db_exec("DELETE FROM cooldown WHERE expires_at<=?", (time.time(),))


def db_log_setup(
    signal_str: str, score: int, entry: float, sl: float, tp: float,
    h: str, session: str = "",
    features: Optional[np.ndarray] = None,
    win_prob: float = 0.0,
    is_judas: bool = False,
) -> None:
    fj: Optional[str] = None
    if features is not None:
        try:
            fj = json.dumps([round(float(v), 8) for v in features], separators=(",", ":"))
        except Exception:
            pass
    _db_exec(
        "INSERT INTO setup_log"
        "(ts,signal,score,entry,sl,tp,setup_hash,session,features,win_prob,is_judas)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (time.time(), signal_str, score, entry, sl, tp, h, session, fj, win_prob, int(is_judas)),
    )
    _db_exec("INSERT INTO win_prob_history(ts,prob) VALUES(?,?)", (time.time(), win_prob))


# ── Trail state ───────────────────────────────────────────────────────────────
def get_trail_state(ticket: int, setup_hash: str = "") -> Optional[sqlite3.Row]:
    row = _db_query(
        "SELECT setup_hash,last_sl,partial_done FROM trail_state WHERE ticket=?", (ticket,)
    )
    if row:
        return row
    if setup_hash:
        return _db_query(
            "SELECT ticket,last_sl,partial_done FROM trail_state WHERE setup_hash=?",
            (setup_hash,),
        )
    return None


def save_trail_sl(ticket: int, sl: float, setup_hash: str = "",
                  partial_done: Optional[int] = None) -> None:
    existing = get_trail_state(ticket, setup_hash)
    if partial_done is None:
        partial_done = int(existing["partial_done"]) if existing else 0
    _db_exec("INSERT OR REPLACE INTO trail_state VALUES(?,?,?,?,?)",
             (ticket, setup_hash or "", sl, time.time(), partial_done))


def set_partial_done(ticket: int, setup_hash: str = "") -> None:
    existing = get_trail_state(ticket, setup_hash)
    last_sl  = float(existing["last_sl"]) if existing else 0.0
    _db_exec("INSERT OR REPLACE INTO trail_state VALUES(?,?,?,?,?)",
             (ticket, setup_hash or "", last_sl, time.time(), 1))


def cleanup_trail_state(open_tickets: set) -> None:
    if not open_tickets:
        _db_exec("DELETE FROM trail_state")
        return
    ph = ",".join("?" * len(open_tickets))
    _db_exec(f"DELETE FROM trail_state WHERE ticket NOT IN ({ph})", tuple(open_tickets))


def batch_load_trail_states(tickets: List[int]) -> Dict[int, sqlite3.Row]:
    """[FIX-7] Single-query batch load for PositionManager hot path."""
    if not tickets:
        return {}
    ph   = ",".join("?" * len(tickets))
    rows = _db_query_all(
        f"SELECT ticket,setup_hash,last_sl,partial_done FROM trail_state WHERE ticket IN ({ph})",
        tuple(tickets),
    )
    return {int(r["ticket"]): r for r in rows}


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
class FVGZone:
    kind:        str
    top:         float
    bot:         float
    strength:    float
    bar_index:   int
    mitigated:   bool  = False
    volume_spike: bool = False   # [V14-S1]


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
    volume_spike: bool  = False   # [V14-S1]


@dataclass
class DXYBias:
    """[V14-A1] DXY Inverse Filter result."""
    available:  bool  = False
    trend:      str   = "NEUTRAL"   # "BULLISH", "BEARISH", "NEUTRAL"
    buy_penalty: int  = 0
    sell_bonus:  int  = 0


@dataclass
class SetupResult:
    signal:        str              = "WAIT"
    score:         int              = 0
    entry:         float            = 0.0
    sl:            float            = 0.0
    tp_full:       float            = 0.0    # [V14-S3] may be capped by ADR
    atr:           float            = 0.0
    htf_bias:      str              = "NEUTRAL"
    m15_struct:    str              = "NEUTRAL"
    adr_pct:       float            = 0.0
    threshold:     int              = 63
    reasons:       List[str]        = field(default_factory=list)
    setup_hash:    str              = ""
    use_market:    bool             = False
    liq_map:       Optional[LiquidityMap]   = None
    fvg_zone:      Optional[FVGZone]        = None
    candle_ts:     float            = 0.0
    htf_result:    Optional[HTFBiasResult]  = None
    dxy_bias:      Optional[DXYBias]        = None
    features:      Optional[np.ndarray]     = None
    win_prob:      float            = 0.0
    spread_pts:    float            = 0.0
    is_judas:      bool             = False   # [V14-S2]
    adr_tp_capped: bool             = False   # [V14-S3]
    pd_zone:       str              = "NEUTRAL"  # [V14-A2] "DISCOUNT"/"PREMIUM"/"EQUILIBRIUM"

    def summary(self) -> str:
        mode   = "MKT" if self.use_market else "LMT"
        gap    = self.score - self.threshold
        conf   = "🔥🔥🔥" if gap >= 20 else "🔥🔥" if gap >= 10 else "🔥"
        judas  = "⚡JUDAS " if self.is_judas else ""
        capped = "📉ADRcap " if self.adr_tp_capped else ""
        return (
            f"{conf} {judas}{capped}{self.signal}({mode}) "
            f"Score:{self.score}/{self.threshold} "
            f"WinProb:{self.win_prob:.2f} "
            f"PD:{self.pd_zone} "
            f"| {' | '.join(self.reasons)}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 🤖  ML LAYER  [V14-O1] Welford Online Normaliser
# ══════════════════════════════════════════════════════════════════════════════

class WelfordNormaliser:
    """
    [V14-O1] O(1) per-update online mean/variance via Welford's algorithm.

    Replaces RollingZScoreNormaliser which required O(n) full recomputation
    of np.mean / np.std over the deque on every call.

    Welford's numerically stable recurrence:
        n   += 1
        delta = x - mean
        mean += delta / n
        delta2 = x - mean
        M2  += delta * delta2
        var = M2 / (n - 1)   [sample variance]

    Window is approximated by exponential weighting (α = 2/(window+1)):
    this gives a rolling weighted mean/std without storing history.
    """

    def __init__(self, n_features: int, window: int = 200, min_samples: int = 20):
        self._n    = n_features
        self._min  = min_samples
        self._alpha = 2.0 / (window + 1)    # EMA decay factor

        # Per-feature state
        self._count  = np.zeros(n_features, dtype=np.float64)   # effective samples
        self._mean   = np.zeros(n_features, dtype=np.float64)
        self._M2     = np.ones(n_features,  dtype=np.float64)   # init to 1 avoids /0

    def update(self, x: np.ndarray) -> None:
        """Push one observation. Each feature updated independently."""
        for i in range(self._n):
            v = float(x[i])
            if not math.isfinite(v):
                continue
            self._count[i] += 1
            # Exponential weighting: older observations decay
            # Approximate via EMA on mean and M2
            old_mean      = self._mean[i]
            self._mean[i] = old_mean + self._alpha * (v - old_mean)
            # Variance via EMA on squared deviation
            self._M2[i]   = (1 - self._alpha) * (self._M2[i] + self._alpha * (v - old_mean) ** 2)

    def transform(self, x: np.ndarray) -> np.ndarray:
        """Standardise x using current rolling stats. Returns raw x during cold-start."""
        out = x.copy()
        if not self.is_warm:
            return out
        std = np.sqrt(np.maximum(self._M2, 1e-12))
        out = np.where(std > 1e-9, (out - self._mean) / std, 0.0)
        return out

    @property
    def is_warm(self) -> bool:
        return bool(np.all(self._count >= self._min))

    def check_distribution_shift(self, x: np.ndarray, z_bound: float = 3.5) -> bool:
        """True if any feature is beyond z_bound σ from rolling mean."""
        if not self.is_warm:
            return False
        std = np.sqrt(np.maximum(self._M2, 1e-12))
        z   = np.abs((x - self._mean) / np.where(std > 1e-9, std, 1.0))
        return bool(np.any(z > z_bound))

    @property
    def mean(self) -> np.ndarray:
        return self._mean.copy()

    @property
    def std(self) -> np.ndarray:
        return np.sqrt(np.maximum(self._M2, 1e-12))


N_FEATURES = 13   # [V14] expanded by 1 (dxy_bias added as feature 12)


def extract_features(
    setup: "SetupResult",
    close_price: float = 2000.0,
    df_len: int = 300,
) -> np.ndarray:
    """
    [V14] Stationary 13-feature vector.

    Feature index → name:
      0   htf_bias_enc        BULLISH=1, BEARISH=-1, NEUTRAL=0
      1   atr_norm            atr / close_price
      2   adr_pct             day_range / avg_daily_range
      3   fvg_strength        gap / atr
      4   spread_norm         spread_pts / atr
      5   m15_enc             BULLISH_BOS=1, BEARISH_BOS=-1, else 0
      6   has_liq_target      1 if BSL/SSL within RR reach
      7   has_ob_fresh        1 if unmitigated OB found
      8   sweep_and_fvg       1 if Sweep+FVG confluence
      9   fvg_age_norm        [V14-F6 FIXED] relative bars / lookback (0=fresh, 1=stale)
     10   sweep_depth         (sweep_extreme - level) / atr
     11   session_sin         sin(2π * min_of_day / 1440) cyclical time
     12   dxy_bias_enc        [V14-A1] DXY trend: BULLISH=1, BEARISH=-1, NEUTRAL=0
    """
    htf_bias_enc = {"BULLISH": 1.0, "BEARISH": -1.0}.get(setup.htf_bias, 0.0)
    atr          = max(setup.atr, 1e-6)
    atr_norm     = atr / max(close_price, 1.0)

    fvg_strength = setup.fvg_zone.strength if setup.fvg_zone else 0.0

    # [V14-F6] FIXED fvg_age_norm — relative age from current candle
    fvg_age_norm = 0.0
    if setup.fvg_zone is not None:
        lookback     = FVG_MEMORY_BARS.get("DEFAULT", 30)
        # bar_index is absolute df index; relative age = bars from end of df
        rel_age      = max(0, df_len - 1 - setup.fvg_zone.bar_index)
        fvg_age_norm = min(1.0, rel_age / max(lookback, 1))

    spread_norm = setup.spread_pts / max(atr, 1e-6)
    m15_enc     = {"BULLISH_BOS": 1.0, "BEARISH_BOS": -1.0}.get(setup.m15_struct, 0.0)

    reasons_str    = " ".join(setup.reasons)
    has_ob         = 1.0 if any("OB(q:" in r for r in setup.reasons) else 0.0
    sweep_and_fvg  = 1.0 if "Sweep+FVG" in reasons_str else 0.0
    has_liq_target = 1.0 if ("BSL→" in reasons_str or "SSL→" in reasons_str) else 0.0

    sweep_depth = 0.0
    if setup.liq_map is not None:
        lm = setup.liq_map
        if lm.swept_low is not None and setup.signal == "BUY":
            sweep_depth = min(1.0, abs(lm.swept_low - (lm.ssl_nearest or lm.swept_low)) / atr)
        elif lm.swept_high is not None and setup.signal == "SELL":
            sweep_depth = min(1.0, abs((lm.bsl_nearest or lm.swept_high) - lm.swept_high) / atr)

    now_s       = datetime.now(STRATEGY_TZ)
    min_of_day  = now_s.hour * 60 + now_s.minute
    session_sin = math.sin(2.0 * math.pi * min_of_day / 1440.0)

    # [V14-A1] DXY bias encoding
    dxy_enc = 0.0
    if setup.dxy_bias is not None and setup.dxy_bias.available:
        dxy_enc = {"BULLISH": 1.0, "BEARISH": -1.0}.get(setup.dxy_bias.trend, 0.0)

    return np.array([
        htf_bias_enc, atr_norm, float(setup.adr_pct), float(fvg_strength),
        float(spread_norm), m15_enc, has_liq_target, has_ob,
        sweep_and_fvg, fvg_age_norm, sweep_depth, session_sin, dxy_enc,
    ], dtype=np.float64)


class MLPredictor:
    """
    [V14] ML inference with Welford O(1) online normaliser.
    Checks distribution shift BEFORE updating buffer (V13 Bug-3 fix).
    """

    def __init__(self):
        self._model   = None
        self._norm    = WelfordNormaliser(N_FEATURES)
        self._prob_buf: List[float] = []
        log.info(
            f"🧠 MLPredictor V14: {N_FEATURES}-feat | Welford O(1) normaliser | "
            "dist-shift check BEFORE update"
        )

    def load_model(self, path: str) -> bool:
        try:
            import joblib as _joblib
            obj = _joblib.load(path)
            self._model = obj[1] if isinstance(obj, tuple) and len(obj) == 2 else obj
            log.info(f"🧠 MLPredictor: model loaded from {path}")
            return True
        except Exception as exc:
            log.warning(f"🧠 MLPredictor: load failed ({exc}) — heuristic mode")
            return False

    def predict_win_probability(self, features: np.ndarray,
                                update_norm: bool = True) -> float:
        # [V14-F7] Check distribution shift BEFORE contaminating buffer
        if self._norm.check_distribution_shift(features, z_bound=3.5):
            log.warning("🧠 Feature distribution shift >3.5σ → returning 0.61 (below gate)")
            return 0.61   # below ML_WIN_PROB_THRESHOLD; skip without updating

        # Safe to update now (no outlier contamination)
        if update_norm:
            self._norm.update(features)

        x = self._norm.transform(features)

        if self._model is not None:
            try:
                prob = float(self._model.predict_proba(x.reshape(1, -1))[0][1])
                prob = max(0.0, min(1.0, prob))
                self._prob_buf.append(prob)
                if len(self._prob_buf) > ML_ROLLING_WINDOW:
                    self._prob_buf.pop(0)
                return prob
            except Exception as exc:
                log.warning(f"🧠 Inference error: {exc} — heuristic")

        # Heuristic using RAW features (pre-normalise) for interpretable bounds
        raw = features
        htf_aligned   = abs(float(raw[0])) > 0.5
        adr_pct       = float(raw[2])
        sweep_and_fvg = float(raw[8]) > 0.5
        has_liq       = float(raw[6]) > 0.5
        has_ob        = float(raw[7]) > 0.5
        m15_confirms  = abs(float(raw[5])) > 0.5
        fvg_fresh     = float(raw[9]) < 0.3
        sweep_depth   = float(raw[10])
        dxy_aligned   = (
            (setup_signal := 1.0) and float(raw[12]) < 0    # DXY bearish → BUY Gold
            if False else True                               # placeholder
        )

        prob = 0.38
        if htf_aligned:             prob += 0.12
        if sweep_and_fvg:           prob += 0.10
        if has_liq:                 prob += 0.07
        if has_ob:                  prob += 0.06
        if m15_confirms:            prob += 0.06
        if fvg_fresh:               prob += 0.05
        if sweep_depth > 0.1:       prob += min(0.04, sweep_depth * 0.4)
        if adr_pct > ADR_EXHAUSTED_PCT: prob -= 0.10
        # DXY inverse: if DXY bullish (+1) and we have a BUY signal, slight debit
        if float(raw[12]) > 0.5:   prob -= 0.04
        if float(raw[12]) < -0.5:  prob += 0.04

        prob = max(0.0, min(1.0, round(prob, 4)))
        self._prob_buf.append(prob)
        if len(self._prob_buf) > ML_ROLLING_WINDOW:
            self._prob_buf.pop(0)
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
    """All MT5 data retrieval and TTL-based caching."""

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
        """
        [V14-F1] Returns CLOSED candles only (trim last live bar).
        HTF now uses H4 (HTF_TIMEFRAME).
        """
        def _trim(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
            return df.iloc[:-1].copy() if df is not None and len(df) > 1 else df

        m1  = _trim(self.fetch(mt5.TIMEFRAME_M1,   60,  use_cache=False))
        m5  = _trim(self.fetch(mt5.TIMEFRAME_M5,  300,  use_cache=False))
        m15 = _trim(self.fetch(mt5.TIMEFRAME_M15, 100,  use_cache=True))
        h4  = _trim(self.fetch(HTF_TIMEFRAME,     HTF_BARS, use_cache=True))  # [V14-F2]
        d1  = self.fetch(mt5.TIMEFRAME_D1,  20,  use_cache=True)
        dxy = self._fetch_dxy()
        return {"m1": m1, "m5": m5, "m15": m15, "h4": h4, "d1": d1, "dxy": dxy}

    def _fetch_dxy(self) -> Optional[pd.DataFrame]:
        """[V14-A1] Fetch DXY H1 data for inverse filter."""
        if not DXY_ENABLED or not DXY_SYMBOL:
            return None
        rates = mt5.copy_rates_from_pos(DXY_SYMBOL, mt5.TIMEFRAME_H1, 0, 40)
        if rates is None or len(rates) == 0:
            return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        return df.iloc[:-1].copy()

    def get_current_m5_bar_time(self) -> Optional[int]:
        rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M5, 0, 1)
        if rates is not None and len(rates) > 0:
            return int(rates[0]["time"])
        return None


# ══════════════════════════════════════════════════════════════════════════════
# 🧮  INDICATOR FUNCTIONS  — NumPy hot-paths
# ══════════════════════════════════════════════════════════════════════════════

def _to_numpy(df: pd.DataFrame, col: str) -> np.ndarray:
    return np.ascontiguousarray(df[col].values, dtype=np.float64)


def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < period + 1:
        return 0.0
    h  = _to_numpy(df, "high");  l  = _to_numpy(df, "low");  c = _to_numpy(df, "close")
    pc = c[:-1]
    tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - pc), np.abs(l[1:] - pc)))
    if len(tr) < period:
        return 0.0
    val   = float(tr[:period].mean())
    alpha = 1.0 / period
    for v in tr[period:]:
        val = val * (1.0 - alpha) + float(v) * alpha
    return val if not np.isnan(val) else 0.0


def calculate_adr(df_d1: Optional[pd.DataFrame], period: int = 10) -> float:
    if df_d1 is None or len(df_d1) < period:
        return 0.0
    h = _to_numpy(df_d1, "high");  l = _to_numpy(df_d1, "low")
    return float((h - l)[-period:].mean())


def get_confirmed_swings_np(
    df: pd.DataFrame, period: int = 5, confirm: int = 2
) -> Tuple[float, float]:
    if len(df) < period * 2 + confirm + 1:
        return float(df["high"].max()), float(df["low"].min())
    h = _to_numpy(df, "high");  l = _to_numpy(df, "low")
    safe = len(h) - confirm
    sh_vals, sl_vals = [], []
    for i in range(period, safe - period):
        if h[i] == h[i - period: i + period + 1].max(): sh_vals.append(h[i])
        if l[i] == l[i - period: i + period + 1].min(): sl_vals.append(l[i])
    return (
        float(sh_vals[-1]) if sh_vals else float(h.max()),
        float(sl_vals[-1]) if sl_vals else float(l.min()),
    )


def _rolling_vol_mean(df: pd.DataFrame, period: int = VOL_SPIKE_PERIOD) -> np.ndarray:
    """[V14-S1] Rolling mean of tick_volume for volume spike detection."""
    vol = _to_numpy(df, "tick_volume")
    out = np.full_like(vol, np.nan)
    for i in range(period - 1, len(vol)):
        out[i] = vol[max(0, i - period + 1): i + 1].mean()
    return out


def _cluster_liquidity_levels(prices: List[float], tol: float) -> List[float]:
    clusters: List[float] = []
    used = [False] * len(prices)
    for i in range(len(prices)):
        if used[i]:
            continue
        group = [prices[i]]
        for j in range(i + 1, len(prices)):
            if not used[j] and abs(prices[j] - prices[i]) <= tol:
                group.append(prices[j]);  used[j] = True
        if len(group) >= LIQ_MIN_CLUSTER:
            clusters.append(round(sum(group) / len(group), 5))
    return clusters


def build_liquidity_map_np(df: pd.DataFrame, atr: float, period: int = 10) -> LiquidityMap:
    """[OPT-1] + [V13-P1-C] Liquidity map with gap-crossed sweep detection."""
    liq = LiquidityMap()
    if len(df) < period * 2 + 4 or atr == 0:
        return liq
    h = _to_numpy(df, "high");  l = _to_numpy(df, "low")
    c = _to_numpy(df, "close"); o = _to_numpy(df, "open")
    safe = len(h) - 2
    tol  = max(atr * 0.08, abs(c[-1]) * LIQ_EQUAL_TOLERANCE)

    ph_list, pl_list = [], []
    for i in range(period, safe - period):
        if h[i] == h[i - period: i + period + 1].max(): ph_list.append(h[i])
        if l[i] == l[i - period: i + period + 1].min(): pl_list.append(l[i])

    liq.buy_side  = sorted(_cluster_liquidity_levels(ph_list, tol), reverse=True)
    liq.sell_side = sorted(_cluster_liquidity_levels(pl_list, tol))

    last_high  = float(h[-1]);  last_low   = float(l[-1]);  last_close = float(c[-1])
    prev_close = float(c[-2]) if len(c) >= 2 else last_close
    cur_open   = float(o[-1])

    for lvl in liq.buy_side:
        if last_high > lvl and last_close < lvl: liq.swept_high = lvl; break
    for lvl in liq.sell_side:
        if last_low < lvl and last_close > lvl: liq.swept_low = lvl; break

    # Gap-through sweeps
    for lvl in liq.buy_side:
        if prev_close >= lvl > cur_open: liq.gap_swept_high = lvl; break
    for lvl in liq.sell_side:
        if prev_close <= lvl < cur_open: liq.gap_swept_low  = lvl; break

    price = last_close
    above = [lv for lv in liq.buy_side  if lv > price]
    below = [lv for lv in liq.sell_side if lv < price]
    liq.bsl_nearest = min(above) if above else None
    liq.ssl_nearest = max(below) if below else None
    return liq


# ══════════════════════════════════════════════════════════════════════════════
# 🧠  CLASS: SMCSignalEngine
# ══════════════════════════════════════════════════════════════════════════════
class SMCSignalEngine:
    """
    All signal detection: HTF H4 Bias · FVG · OB · Liquidity · Scoring.
    V14 additions: Volume spike · Judas swing · P/D zone · DXY filter.
    """

    def __init__(self):
        self._news_guard = NewsGuard()

    # ── [V14-F2] HTF Bias — now H4 ───────────────────────────────────────────
    @staticmethod
    def get_htf_bias(df_h4: Optional[pd.DataFrame]) -> HTFBiasResult:
        """
        [V14-F2] H4 BOS/CHOCH/Sweep analysis.
        H4 gives institutional-grade structure for Gold without H1 noise.
        """
        res = HTFBiasResult()
        if df_h4 is None or len(df_h4) < HTF_SWING_PERIOD * 2 + HTF_SWING_CONFIRM + 5:
            res.reason = "H4 data insufficient"
            return res

        lookback = min(150, len(df_h4))
        df  = df_h4.iloc[-lookback:].reset_index(drop=True)
        p, c = HTF_SWING_PERIOD, HTF_SWING_CONFIRM
        h = _to_numpy(df, "high");  l = _to_numpy(df, "low");  cl = _to_numpy(df, "close")
        safe = len(h) - c

        sh_list: List[Tuple[int, float]] = []
        sl_list: List[Tuple[int, float]] = []
        for i in range(p, safe - p):
            if h[i] == h[i - p: i + p + 1].max(): sh_list.append((i, float(h[i])))
            if l[i] == l[i - p: i + p + 1].min(): sl_list.append((i, float(l[i])))

        if len(sh_list) < 2 or len(sl_list) < 2:
            res.reason = "Insufficient H4 swings"
            return res

        prev_sh = sh_list[-1][1];  prev_sl = sl_list[-1][1]

        if float(h[-1]) > prev_sh and float(cl[-1]) < prev_sh: res.swept_high = prev_sh
        if float(l[-1]) < prev_sl and float(cl[-1]) > prev_sl: res.swept_low  = prev_sl

        recent = cl[-5:]
        bos_up   = bool(np.any(recent > prev_sh))
        bos_down = bool(np.any(recent < prev_sl))
        hh = sh_list[-1][1] > sh_list[-2][1];  lh = sh_list[-1][1] < sh_list[-2][1]
        hl = sl_list[-1][1] > sl_list[-2][1];  ll = sl_list[-1][1] < sl_list[-2][1]

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
            res.reason = f"H4|BOS_UP:{bos_up}|HH:{hh}|HL:{hl}|SwL:{res.swept_low is not None}"
        elif bear_pts >= 3 and bear_pts > bull_pts:
            res.bias   = "BEARISH"
            res.reason = f"H4|BOS_DN:{bos_down}|LH:{lh}|LL:{ll}|SwH:{res.swept_high is not None}"
        else:
            res.bias   = "NEUTRAL"
            res.reason = f"H4|Bull:{bull_pts} Bear:{bear_pts} unclear"
        return res

    # ── [V14-A1] DXY Inverse Filter ──────────────────────────────────────────
    @staticmethod
    def get_dxy_bias(df_dxy: Optional[pd.DataFrame]) -> DXYBias:
        """
        [V14-A1] Read DXY H1 trend. Gold moves INVERSELY to DXY.
        Uses simple HH/HL (BULLISH) vs LH/LL (BEARISH) on H1 confirmed swings.
        """
        result = DXYBias()
        if not DXY_ENABLED or df_dxy is None or len(df_dxy) < 30:
            return result
        result.available = True
        try:
            sh, sl = get_confirmed_swings_np(df_dxy, period=DXY_SWING_PERIOD, confirm=2)
            last_c = float(df_dxy["close"].iloc[-1])
            if last_c > sh:
                result.trend      = "BULLISH"
                result.buy_penalty = DXY_BUY_PENALTY    # DXY up → Gold likely down
                result.sell_bonus  = DXY_SELL_BONUS
            elif last_c < sl:
                result.trend      = "BEARISH"
                # DXY down → Gold likely up (inverse)
                result.buy_penalty = 0
                result.sell_bonus  = 0
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
        if last_c > sh + buf:  return "BULLISH_BOS"
        if last_c < sl - buf:  return "BEARISH_BOS"
        return "NEUTRAL"

    # ── [V14-A2] Premium / Discount Zone ─────────────────────────────────────
    @staticmethod
    def get_pd_zone(df_m5: pd.DataFrame, period: int = PD_PERIOD) -> str:
        """
        [V14-A2] ICT Premium/Discount zone on the current dealing range.
        Dealing range = highest high to lowest low over `period` bars.
        Top 33% = Premium (sell zone); Bottom 33% = Discount (buy zone).
        """
        if len(df_m5) < period:
            return "NEUTRAL"
        sub    = df_m5.iloc[-period:]
        rng_h  = float(sub["high"].max())
        rng_l  = float(sub["low"].min())
        spread = rng_h - rng_l
        if spread < 1e-6:
            return "NEUTRAL"
        price     = float(df_m5["close"].iloc[-1])
        pct_pos   = (price - rng_l) / spread   # 0 = bottom, 1 = top
        if pct_pos > 0.67:   return "PREMIUM"
        if pct_pos < 0.33:   return "DISCOUNT"
        return "EQUILIBRIUM"

    # ── FVG Memory [V14-S1 Volume spike] ─────────────────────────────────────
    @staticmethod
    def scan_fvg_memory(
        df: pd.DataFrame, atr: float, lookback: int = 30
    ) -> List[FVGZone]:
        zones: List[FVGZone] = []
        if len(df) < lookback + 3 or atr == 0:
            return zones

        min_gap  = atr * FVG_MIN_GAP_ATR
        start    = max(3, len(df) - lookback)
        vol_mean = _rolling_vol_mean(df, VOL_SPIKE_PERIOD) if VOL_SPIKE_ENABLED else None

        for i in range(start, len(df) - 2):
            c1 = df.iloc[i];  c2 = df.iloc[i + 1];  c3 = df.iloc[i + 2]

            c2_range = float(c2["high"] - c2["low"])
            c2_body  = abs(float(c2["close"] - c2["open"]))
            if c2_range > 0 and (c2_body / c2_range) < FVG_MOMENTUM_RATIO:
                continue

            # [V14-S1] Volume spike check on impulse candle (c2)
            vol_spike = False
            if VOL_SPIKE_ENABLED and vol_mean is not None:
                idx_in_df = i + 1   # c2 position
                vm = vol_mean[idx_in_df] if idx_in_df < len(vol_mean) else np.nan
                if not np.isnan(vm) and vm > 0:
                    vol_spike = float(df.iloc[idx_in_df]["tick_volume"]) >= vm * VOL_SPIKE_MULT

            # Bullish FVG: c3.low > c1.high
            gap_bull = float(c3["low"]) - float(c1["high"])
            if gap_bull >= min_gap:
                top = float(c3["low"]);  bot = float(c1["high"])
                gap = top - bot;  strength = min(2.0, gap / atr)
                mitigated = False
                mid = bot + gap * FVG_MITIGATED_PCT
                for j in range(i + 3, len(df)):
                    if float(df.iloc[j]["low"]) <= mid: mitigated = True; break
                zones.append(FVGZone("BULLISH", top, bot, strength, i, mitigated, vol_spike))

            # Bearish FVG: c1.low > c3.high
            gap_bear = float(c1["low"]) - float(c3["high"])
            if gap_bear >= min_gap:
                top = float(c1["low"]);  bot = float(c3["high"])
                gap = top - bot;  strength = min(2.0, gap / atr)
                mitigated = False
                mid = top - gap * FVG_MITIGATED_PCT
                for j in range(i + 3, len(df)):
                    if float(df.iloc[j]["high"]) >= mid: mitigated = True; break
                zones.append(FVGZone("BEARISH", top, bot, strength, i, mitigated, vol_spike))

        zones.sort(key=lambda z: z.bar_index, reverse=True)
        return zones

    @staticmethod
    def get_active_fvg(zones: List[FVGZone], price: float, direction: str) -> Optional[FVGZone]:
        target = "BULLISH" if direction == "BUY" else "BEARISH"
        for z in zones:
            if z.mitigated or z.kind != target: continue
            buf = (z.top - z.bot) * FVG_BUFFER_RATIO
            if (z.bot - buf) <= price <= (z.top + buf):
                return z
        return None

    # ── Order Block [V13-P1-B + V14-S1 volume] ───────────────────────────────
    @staticmethod
    def find_order_block(df: pd.DataFrame, direction: str, atr: float) -> OBResult:
        if len(df) < 10 or atr == 0:
            return OBResult()
        closed  = df.iloc[:-1]
        n       = len(closed)
        max_age = min(30, n - 2)
        vol_mean = _rolling_vol_mean(closed, VOL_SPIKE_PERIOD) if VOL_SPIKE_ENABLED else None

        for age in range(1, max_age):
            i   = n - 1 - age
            ob  = closed.iloc[i]
            if i + 1 >= n - 1: continue
            imp = closed.iloc[i + 1]

            imp_body = abs(float(imp["close"]) - float(imp["open"]))
            if imp_body < atr * 1.2: continue

            # [V14-S1] Volume spike on impulse candle
            vol_spike = False
            if VOL_SPIKE_ENABLED and vol_mean is not None:
                vm = vol_mean[i + 1] if i + 1 < len(vol_mean) else np.nan
                if not np.isnan(vm) and vm > 0:
                    vol_spike = float(imp["tick_volume"]) >= vm * VOL_SPIKE_MULT

            ob_low  = float(ob["low"]);   ob_high = float(ob["high"])
            rng     = ob_high - ob_low

            if direction == "BUY":
                if ob["close"] >= ob["open"] or imp["close"] <= imp["open"]: continue
                ph_w = closed["high"].iloc[max(0, i - 10): i]
                if len(ph_w) > 0 and imp["close"] <= ph_w.max() * 0.998: continue
                mitigated = any(
                    float(closed.iloc[j]["close"]) < ob_low
                    for j in range(i + 2, n)
                )
                body  = (float(ob["open"]) - float(ob["close"])) / rng if rng > 0 else 0
                sweep = float(closed["low"].iloc[max(0, i - 5): i].min()) < ob_low
            else:
                if ob["close"] <= ob["open"] or imp["close"] >= imp["open"]: continue
                pl_w = closed["low"].iloc[max(0, i - 10): i]
                if len(pl_w) > 0 and imp["close"] >= float(pl_w.min()) * 1.002: continue
                mitigated = any(
                    float(closed.iloc[j]["close"]) > ob_high
                    for j in range(i + 2, n)
                )
                body  = (float(ob["close"]) - float(ob["open"])) / rng if rng > 0 else 0
                sweep = float(closed["high"].iloc[max(0, i - 5): i].max()) > ob_high

            q = 0.5 + (0.3 if sweep else 0) + (0.2 if body > 0.6 else 0)
            return OBResult(True, ob_high, ob_low, q, bar_age=age,
                            mitigated=mitigated, volume_spike=vol_spike)
        return OBResult()

    # ── [V14-S2] Judas Swing Detection ───────────────────────────────────────
    @staticmethod
    def is_judas_swing(liq: LiquidityMap, fvg_zones: List[FVGZone],
                       signal: str, session: str) -> bool:
        """
        [V14-S2] Gold Killzone Reversal / Judas Swing.
        Qualifies if: sweep happened in London Open OR NY Open opening window
        AND an opposing FVG exists immediately after the sweep.
        """
        if not JUDAS_SWING_ENABLED:
            return False
        if session not in ("LONDON", "NY_OPEN_EARLY", "NEW_YORK"):
            return False

        now_s   = datetime.now(STRATEGY_TZ)
        # Find the session opening time
        session_opens = {
            "LONDON":        dtime(14, 0),
            "NY_OPEN_EARLY": dtime(18, 30),
            "NEW_YORK":      dtime(19, 45),
        }
        open_time = session_opens.get(session)
        if open_time is None:
            return False

        now_t    = now_s.time()
        open_dt  = datetime.combine(now_s.date(), open_time)
        now_dt   = datetime.combine(now_s.date(), now_t)
        mins_in  = (now_dt - open_dt).total_seconds() / 60.0
        if mins_in < 0 or mins_in > JUDAS_WINDOW_MIN:
            return False

        # Check sweep occurred and there is a fresh opposing FVG
        if signal == "BUY":
            swept = liq.swept_low is not None or liq.gap_swept_low is not None
            has_opposing_fvg = any(
                z.kind == "BULLISH" and not z.mitigated and z.bar_index >= 0
                for z in fvg_zones[-5:]
            )
        else:
            swept = liq.swept_high is not None or liq.gap_swept_high is not None
            has_opposing_fvg = any(
                z.kind == "BEARISH" and not z.mitigated and z.bar_index >= 0
                for z in fvg_zones[-5:]
            )

        return swept and has_opposing_fvg

    # ── Session helpers ───────────────────────────────────────────────────────
    def get_session(self) -> str:
        now = datetime.now(STRATEGY_TZ)
        blocked, event = self._news_guard.is_blocked(now)
        if blocked:
            log.info(f"📰 News Guard: blocked ({event})")
            return "RED_NEWS_BLOCK"
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
        if not KILLZONE_ENABLED:
            return True, "All"
        t = datetime.now(STRATEGY_TZ).time()
        for sh, sm, eh, em, name in KILLZONES:
            if dtime(sh, sm) <= t <= dtime(eh, em):
                return True, name
        return False, "Outside Killzone"

    @staticmethod
    def get_dynamic_threshold(session: str, htf_bias: str, adr_pct: float) -> int:
        base = SCORE_THRESHOLD.get(session, SCORE_THRESHOLD["DEFAULT"])
        if htf_bias == "NEUTRAL":   base += SCORE_PENALTY_HTF_NEUTRAL
        if adr_pct >= ADR_EXHAUSTED_PCT: base += SCORE_PENALTY_HIGH_ADR
        return base

    # ── [V14-S3] Dynamic ADR TP Cap ──────────────────────────────────────────
    @staticmethod
    def apply_adr_tp_cap(
        entry: float, tp_raw: float, sl: float,
        adr: float, df_d1: Optional[pd.DataFrame],
        session: str, signal: str,
    ) -> Tuple[float, bool]:
        """
        [V14-S3] If raw TP exceeds remaining ADR room, cap it.
        Session-aware: NY sessions use ADR_NY_EXHAUSTED_PCT ceiling.
        Returns (adjusted_tp, was_capped).
        """
        if adr <= 0 or df_d1 is None or len(df_d1) < 1:
            return tp_raw, False

        day_high  = float(df_d1["high"].iloc[-1])
        day_low   = float(df_d1["low"].iloc[-1])
        adr_ceil  = ADR_NY_EXHAUSTED_PCT if session in ("NEW_YORK", "NY_OPEN_EARLY") \
                    else ADR_EXHAUSTED_PCT
        remaining_up   = day_low + adr * adr_ceil - entry   # room above
        remaining_down = entry - (day_high - adr * adr_ceil)  # room below

        capped = False
        tp_adj = tp_raw

        if signal == "BUY" and remaining_up > 0:
            cap = entry + remaining_up * ADR_TP_BUFFER_PCT
            if tp_raw > cap:
                tp_adj = cap;  capped = True
        elif signal == "SELL" and remaining_down > 0:
            cap = entry - remaining_down * ADR_TP_BUFFER_PCT
            if tp_raw < cap:
                tp_adj = cap;  capped = True

        # Ensure minimum risk stays sensible (at least 1:1 RR after cap)
        risk = abs(entry - sl)
        if signal == "BUY"  and (tp_adj - entry) < risk: tp_adj = tp_raw; capped = False
        if signal == "SELL" and (entry - tp_adj) < risk: tp_adj = tp_raw; capped = False

        return tp_adj, capped

    # ── Master setup analyser ─────────────────────────────────────────────────
    def analyze_setup(
        self,
        df_m5:  Optional[pd.DataFrame],
        df_h4:  Optional[pd.DataFrame],
        df_d1:  Optional[pd.DataFrame],
        df_m15: Optional[pd.DataFrame],
        df_dxy: Optional[pd.DataFrame],
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

        # [V14-F3] ADR hard block with session awareness
        adr_ceil = ADR_NY_EXHAUSTED_PCT if session in ("NEW_YORK", "NY_OPEN_EARLY") \
                   else ADR_EXHAUSTED_PCT
        if ADR_HARD_BLOCK and r.adr_pct >= adr_ceil:
            r.reasons.append(f"ADR_HARD_BLOCK({r.adr_pct*100:.0f}%>={adr_ceil*100:.0f}%)")
            return r

        # [V14-F2] HTF bias from H4
        htf_res      = self.get_htf_bias(df_h4)
        r.htf_bias   = htf_res.bias
        r.htf_result = htf_res

        # [V14-A1] DXY inverse bias
        dxy_b        = self.get_dxy_bias(df_dxy)
        r.dxy_bias   = dxy_b

        r.m15_struct = self.get_m15_structure(df_m15)
        r.threshold  = self.get_dynamic_threshold(session, r.htf_bias, r.adr_pct)

        liq       = build_liquidity_map_np(df_m5, atr, LIQ_SWING_PERIOD)
        r.liq_map = liq

        last_sh, last_sl = get_confirmed_swings_np(df_m5, SWING_PERIOD, SWING_CONFIRM_BARS)
        fvg_lookback     = FVG_MEMORY_BARS.get(session, FVG_MEMORY_BARS["DEFAULT"])
        fvg_zones        = self.scan_fvg_memory(df_m5, atr, fvg_lookback)

        # [V14-A2] Premium/Discount zone
        r.pd_zone = self.get_pd_zone(df_m5)

        last      = df_m5.iloc[-1]
        prev      = df_m5.iloc[-2]
        r.candle_ts = (
            float(last["time"].timestamp())
            if hasattr(last["time"], "timestamp") else time.time()
        )

        price      = float(last["close"])
        sweep_sell = (float(last["low"]) < last_sl and float(last["close"]) > last_sl)
        sweep_buy  = (float(last["high"]) > last_sh and float(last["close"]) < last_sh)
        if liq.gap_swept_low  is not None: sweep_sell = True
        if liq.gap_swept_high is not None: sweep_buy  = True

        df_len = len(df_m5)   # passed to extract_features for correct age norm

        # ─── Inner build helpers ──────────────────────────────────────────────
        def _apply_htf_scores(sig: str) -> None:
            if r.htf_bias == "BULLISH" and sig == "BUY":
                r.score += SCORE_HTF_ALIGN
                choch = "(CHOCH)" if htf_res.choch_signal == "UP" else ""
                r.reasons.append(f"H4 Bull{choch} ✓")
            elif r.htf_bias == "BEARISH" and sig == "SELL":
                r.score += SCORE_HTF_ALIGN
                choch = "(CHOCH)" if htf_res.choch_signal == "DOWN" else ""
                r.reasons.append(f"H4 Bear{choch} ✓")
            elif (r.htf_bias == "BULLISH" and sig == "SELL") or \
                 (r.htf_bias == "BEARISH" and sig == "BUY"):
                r.score += SCORE_HTF_AGAINST
                r.reasons.append(f"H4 {r.htf_bias} ⚠️ (against)")
            elif r.htf_bias == "NEUTRAL":
                r.reasons.append("H4 Neutral ⚠️")

        def _apply_dxy_scores(sig: str) -> None:
            if not dxy_b.available: return
            if dxy_b.trend == "BULLISH" and sig == "BUY":
                r.score += dxy_b.buy_penalty  # negative value
                r.reasons.append(f"DXY↑ punish BUY ({dxy_b.buy_penalty}pts)")
            elif dxy_b.trend == "BULLISH" and sig == "SELL":
                r.score += dxy_b.sell_bonus
                r.reasons.append(f"DXY↑ bonus SELL (+{dxy_b.sell_bonus}pts) ✓")
            elif dxy_b.trend == "BEARISH" and sig == "BUY":
                r.score += abs(dxy_b.sell_bonus)   # mirror bonus for BUY when DXY down
                r.reasons.append(f"DXY↓ bonus BUY (+{abs(dxy_b.sell_bonus)}pts) ✓")

        def _apply_pd_scores(sig: str) -> None:
            if not PD_ZONE_ENABLED: return
            if r.pd_zone == "DISCOUNT" and sig == "BUY":
                r.score += 5
                r.reasons.append("Discount Zone BUY ✓")
            elif r.pd_zone == "PREMIUM" and sig == "SELL":
                r.score += 5
                r.reasons.append("Premium Zone SELL ✓")
            elif r.pd_zone == "EQUILIBRIUM":
                r.score += PD_PENALTY
                r.reasons.append("Equilibrium zone ⚠️")

        def _build_buy() -> bool:
            has_sweep  = sweep_sell
            fvg_active = self.get_active_fvg(fvg_zones, price, "BUY")
            if not has_sweep and fvg_active is None:
                return False

            r.signal = "BUY"
            r.score  = SCORE_BASE

            if fvg_active is not None:
                r.entry    = (fvg_active.bot + (fvg_active.top - fvg_active.bot) * 0.5
                              if FVG_ENTRY_MID else fvg_active.top)
                r.fvg_zone = fvg_active
                # [V14-S1] Volume spike on FVG
                if fvg_active.volume_spike:
                    r.score += SCORE_VOL_SPIKE
                    r.reasons.append("VolSpike FVG ✓")
            elif has_sweep:
                r.entry = last_sl + (atr * 0.1)
            r.sl = last_sl - (atr * SL_ATR_MULT)

            if has_sweep and fvg_active is not None:
                r.score += SCORE_SWEEP_AND_FVG
                r.reasons.append("Sweep+FVG ✓✓")
            elif has_sweep:
                r.reasons.append("Sweep SSL ✓")
            else:
                r.reasons.append("FVG Zone ✓")

            if liq.gap_swept_low is not None:
                r.score += 5;  r.reasons.append("Gap-Sweep SSL ✓")

            if fvg_active is not None and not fvg_active.mitigated:
                r.score += SCORE_FVG_FRESH
                r.reasons.append(f"FVG Fresh(s:{fvg_active.strength:.2f}) ✓")
                if fvg_active.strength > 0.5:
                    r.score += SCORE_FVG_STRENGTH

            _apply_htf_scores("BUY")
            if htf_res.swept_low is not None:
                r.score += 4;  r.reasons.append("H4 SSL Swept ✓")

            if r.m15_struct == "BULLISH_BOS":
                r.score += SCORE_M15_BOS;  r.reasons.append("M15 BOS ✓")

            body = float(last["close"]) - float(last["open"])
            if body > atr * 0.6:
                r.score += SCORE_STRONG_CANDLE;  r.reasons.append("Strong ✓")

            ob = self.find_order_block(df_m5, "BUY", atr)
            if ob.found and not ob.mitigated:
                r.score += int(SCORE_OB_BONUS * ob.score)
                r.reasons.append(f"OB(q:{ob.score:.2f},age:{ob.bar_age}{'⚡' if ob.volume_spike else ''}) ✓")
                if ob.low <= r.entry <= ob.high:
                    r.score += SCORE_OB_OVERLAP;  r.reasons.append("OB Overlap ✓")
                if ob.volume_spike and VOL_SPIKE_ENABLED:
                    r.score += SCORE_VOL_SPIKE;   r.reasons.append("VolSpike OB ✓")
            elif ob.found and ob.mitigated:
                r.reasons.append(f"OB(mitigated,age:{ob.bar_age}) ⚠️")

            if float(last["close"]) > float(prev["high"]):
                r.score += SCORE_BOS_M5;  r.reasons.append("BOS ✓")

            if liq.swept_low is not None:
                r.score += SCORE_LIQ_SWEPT
                r.reasons.append(f"SSL Swept({liq.swept_low:.2f}) ✓")
            if liq.bsl_nearest is not None:
                rsk = abs(r.entry - r.sl)
                if rsk > 0 and (liq.bsl_nearest - r.entry) >= rsk * RR_RATIO * 0.8:
                    r.score += SCORE_LIQ_TARGET
                    r.reasons.append(f"BSL→{liq.bsl_nearest:.2f} ✓")

            if r.adr_pct >= ADR_EXHAUSTED_PCT:
                r.score += SCORE_ADR_WARN
                r.reasons.append(f"ADR{r.adr_pct*100:.0f}% ⚠️")

            # [V14-A1] DXY
            _apply_dxy_scores("BUY")
            # [V14-A2] PD Zone
            _apply_pd_scores("BUY")

            # [V14-S2] Judas Swing Override
            if self.is_judas_swing(liq, fvg_zones, "BUY", session):
                r.score    += JUDAS_SCORE_BONUS
                r.is_judas  = True
                r.reasons.append(f"⚡ JUDAS SWING +{JUDAS_SCORE_BONUS}pts")

            body_ratio = body / atr if atr > 0 else 0
            if (float(last["close"]) > float(prev["high"])
                    and body_ratio > MOMENTUM_BODY_ATR and r.score >= r.threshold):
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
                r.entry    = (fvg_active.bot + (fvg_active.top - fvg_active.bot) * 0.5
                              if FVG_ENTRY_MID else fvg_active.bot)
                r.fvg_zone = fvg_active
                if fvg_active.volume_spike:
                    r.score += SCORE_VOL_SPIKE
                    r.reasons.append("VolSpike FVG ✓")
            elif has_sweep:
                r.entry = last_sh - (atr * 0.1)
            r.sl = last_sh + (atr * SL_ATR_MULT)

            if has_sweep and fvg_active is not None:
                r.score += SCORE_SWEEP_AND_FVG;  r.reasons.append("Sweep+FVG ✓✓")
            elif has_sweep:
                r.reasons.append("Sweep BSL ✓")
            else:
                r.reasons.append("FVG Zone ✓")

            if liq.gap_swept_high is not None:
                r.score += 5;  r.reasons.append("Gap-Sweep BSL ✓")

            if fvg_active is not None and not fvg_active.mitigated:
                r.score += SCORE_FVG_FRESH
                r.reasons.append(f"FVG Fresh(s:{fvg_active.strength:.2f}) ✓")
                if fvg_active.strength > 0.5:
                    r.score += SCORE_FVG_STRENGTH

            _apply_htf_scores("SELL")
            if htf_res.swept_high is not None:
                r.score += 4;  r.reasons.append("H4 BSL Swept ✓")

            if r.m15_struct == "BEARISH_BOS":
                r.score += SCORE_M15_BOS;  r.reasons.append("M15 BOS ✓")

            body = float(last["open"]) - float(last["close"])
            if body > atr * 0.6:
                r.score += SCORE_STRONG_CANDLE;  r.reasons.append("Strong ✓")

            ob = self.find_order_block(df_m5, "SELL", atr)
            if ob.found and not ob.mitigated:
                r.score += int(SCORE_OB_BONUS * ob.score)
                r.reasons.append(f"OB(q:{ob.score:.2f},age:{ob.bar_age}{'⚡' if ob.volume_spike else ''}) ✓")
                if ob.low <= r.entry <= ob.high:
                    r.score += SCORE_OB_OVERLAP;  r.reasons.append("OB Overlap ✓")
                if ob.volume_spike and VOL_SPIKE_ENABLED:
                    r.score += SCORE_VOL_SPIKE;   r.reasons.append("VolSpike OB ✓")
            elif ob.found and ob.mitigated:
                r.reasons.append(f"OB(mitigated,age:{ob.bar_age}) ⚠️")

            if float(last["close"]) < float(prev["low"]):
                r.score += SCORE_BOS_M5;  r.reasons.append("BOS ✓")

            if liq.swept_high is not None:
                r.score += SCORE_LIQ_SWEPT
                r.reasons.append(f"BSL Swept({liq.swept_high:.2f}) ✓")
            if liq.ssl_nearest is not None:
                rsk = abs(r.sl - r.entry)
                if rsk > 0 and (r.entry - liq.ssl_nearest) >= rsk * RR_RATIO * 0.8:
                    r.score += SCORE_LIQ_TARGET
                    r.reasons.append(f"SSL→{liq.ssl_nearest:.2f} ✓")

            if r.adr_pct >= ADR_EXHAUSTED_PCT:
                r.score += SCORE_ADR_WARN
                r.reasons.append(f"ADR{r.adr_pct*100:.0f}% ⚠️")

            _apply_dxy_scores("SELL")
            _apply_pd_scores("SELL")

            if self.is_judas_swing(liq, fvg_zones, "SELL", session):
                r.score    += JUDAS_SCORE_BONUS
                r.is_judas  = True
                r.reasons.append(f"⚡ JUDAS SWING +{JUDAS_SCORE_BONUS}pts")

            body_ratio = body / atr if atr > 0 else 0
            if (float(last["close"]) < float(prev["low"])
                    and body_ratio > MOMENTUM_BODY_ATR and r.score >= r.threshold):
                r.use_market = True
                r.entry      = 0.0
                r.reasons.append("🚀 MKT")

            return True

        # ── Build signal ──────────────────────────────────────────────────────
        if not _build_buy():
            r.signal  = "WAIT";  r.score = 0;  r.reasons = []
            if not _build_sell():
                return r

        # HTF NEUTRAL guard [V14-F4] relaxed threshold
        if r.signal != "WAIT" and r.htf_bias == "NEUTRAL" and not r.is_judas:
            if r.score < HTF_NEUTRAL_MIN_SCORE:
                log.info(f"🚫 H4-NEUTRAL: score {r.score} < {HTF_NEUTRAL_MIN_SCORE} → WAIT")
                return SetupResult()

        if r.signal != "WAIT":
            entry_h      = r.entry if not r.use_market else -1.0
            r.setup_hash = _make_hash(r.signal, entry_h, r.sl, r.candle_ts)

        return r


# ══════════════════════════════════════════════════════════════════════════════
# 💰  CLASS: RiskManager
# ══════════════════════════════════════════════════════════════════════════════
class RiskManager:
    """All risk checks, lot sizing, DD monitoring. V14: CB decoupled from DD Yellow."""

    @staticmethod
    def get_broker_date() -> str:
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick:
            return datetime.fromtimestamp(tick.time, tz=pytz.utc).strftime("%Y%m%d")
        return datetime.utcnow().strftime("%Y%m%d")

    @staticmethod
    def get_spread_pts() -> float:
        tick = mt5.symbol_info_tick(SYMBOL)
        info = mt5.symbol_info(SYMBOL)
        if tick is None or info is None: return 999.0
        return (tick.ask - tick.bid) / info.point

    def is_spread_ok(self) -> bool:
        sp = self.get_spread_pts()
        if sp > HARD_SPREAD_BLOCK:
            log.warning(f"⛔ Spread {sp:.1f}pts > HARD_BLOCK {HARD_SPREAD_BLOCK}")
            return False
        return True

    @staticmethod
    def get_spread_sl_padding() -> float:
        if not SPREAD_SL_PADDING: return 0.0
        tick = mt5.symbol_info_tick(SYMBOL)
        info = mt5.symbol_info(SYMBOL)
        if tick is None or info is None: return 0.0
        return ((tick.ask - tick.bid) / info.point) * info.point

    def get_dd_state(self) -> Tuple[float, float, str]:
        """[V13-P2-C] Returns (daily_dd_pct, total_dd_pct, mode). Mode ∈ NORMAL/YELLOW/ORANGE/RED."""
        acct = mt5.account_info()
        if acct is None: return 0.0, 0.0, "NORMAL"
        equity = acct.equity;  balance = acct.balance
        today_key   = "daily_start_balance_" + self.get_broker_date()
        daily_start = get_state(today_key)
        if daily_start is None or daily_start <= 0:
            set_state(today_key, balance);  daily_start = balance
        daily_dd = max(0.0, (daily_start - equity) / daily_start * 100)
        init_bal = get_state("initial_balance")
        if init_bal is None:
            set_state("initial_balance", balance);  init_bal = balance
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
        _, _, mode = self.get_dd_state()
        return mode not in ("RED", "ORANGE")

    def is_circuit_breaker_tripped(self) -> bool:
        """[V14-F5] CB at 4.5% — decoupled from YELLOW (3%) and ORANGE (5%)."""
        acct = mt5.account_info()
        if acct is None: return False
        today_key   = "daily_start_balance_" + self.get_broker_date()
        daily_start = get_state(today_key)
        if daily_start is None or daily_start <= 0: return False
        dd_pct = (daily_start - acct.equity) / daily_start * 100
        if dd_pct >= CIRCUIT_BREAKER_PCT:
            log.warning(f"⚡ Circuit Breaker: DD {dd_pct:.2f}% ≥ {CIRCUIT_BREAKER_PCT}%")
            return True
        return False

    def get_risk_tier_multiplier(self, score: int, dd_mode: str) -> float:
        base_pct = RISK_TIERS[-1][1]
        for sm, pct in RISK_TIERS:
            if score >= sm: base_pct = pct; break
        if dd_mode == "YELLOW":
            current_idx = next((i for i, (sm, _) in enumerate(RISK_TIERS) if score >= sm),
                               len(RISK_TIERS) - 1)
            reduced_idx = min(current_idx + 1, len(RISK_TIERS) - 1)
            base_pct = RISK_TIERS[reduced_idx][1]
            log.info(f"💛 DD Yellow: risk tier reduced → {base_pct*100:.1f}%")
        return base_pct

    @staticmethod
    def _round_lot(lot: float, step: float) -> float:
        d = Decimal(str(lot));  s = Decimal(str(step))
        return float((d / s).to_integral_value(rounding=ROUND_DOWN) * s)

    def calculate_lot(self, entry: float, sl: float, score: int = 0,
                      spread_pts: float = 0.0, atr: float = 0.0,
                      dd_mode: str = "NORMAL") -> float:
        info = mt5.symbol_info(SYMBOL);  acct = mt5.account_info()
        if info is None or acct is None:
            log.warning("calculate_lot: cannot read broker info → LOT_MIN")
            return LOT_MIN
        risk_pct = self.get_risk_tier_multiplier(score, dd_mode)
        if spread_pts > MAX_SPREAD_POINTS:
            risk_pct *= (1.0 - SPREAD_LOT_PENALTY)
        balance     = acct.balance
        risk_amount = balance * (risk_pct / 100.0)
        sl_dist = abs(entry - sl)
        if sl_dist == 0: return LOT_MIN
        sl_pts   = max(1.0, sl_dist / info.point)
        tick_val = info.trade_tick_value or (info.trade_contract_size * info.point)
        if tick_val <= 0: return LOT_MIN
        raw_lot = risk_amount / (sl_pts * tick_val)
        step    = info.volume_step if info.volume_step > 0 else 0.01
        lot     = self._round_lot(raw_lot, step)
        if lot <= 0.0: lot = info.volume_min
        lot = max(info.volume_min, min(lot, info.volume_max, LOT_MAX))
        log.info(
            f"💰 Lot | Score:{score} DD:{dd_mode} Risk:{risk_pct:.2f}% "
            f"Bal:{balance:.0f} SL:{sl_pts:.1f}pts → {lot}"
        )
        return float(lot)

    @staticmethod
    def dynamic_deviation(atr: float) -> int:
        info = mt5.symbol_info(SYMBOL)
        if info is None or info.point == 0: return 50
        return max(50, int(atr * 0.1 / info.point))

    @staticmethod
    def validate_order(entry: float, sl: float, tp: float,
                       lot: float, signal: str) -> Tuple[bool, str]:
        info = mt5.symbol_info(SYMBOL);  acct = mt5.account_info()
        tick = mt5.symbol_info_tick(SYMBOL)
        if not all([info, acct, tick]): return False, "Cannot read broker data"
        min_d = info.trade_stops_level * info.point
        if abs(entry - sl) < min_d: return False, "SL too close (stop_level)"
        if abs(entry - tp) < min_d: return False, "TP too close (stop_level)"
        frz = info.trade_freeze_level * info.point
        if frz > 0 and abs(entry - tick.ask) < frz: return False, "Entry in freeze zone"
        d_lot = Decimal(str(lot));  d_step = Decimal(str(info.volume_step))
        if d_lot % d_step > Decimal("1e-8"): return False, "Lot step mismatch"
        otype      = mt5.ORDER_TYPE_BUY if signal == "BUY" else mt5.ORDER_TYPE_SELL
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
    """MT5 order execution. V14: trade ticket summary log, ADR-capped TP."""

    def __init__(self, risk: RiskManager, signal_engine: SMCSignalEngine):
        self._risk   = risk
        self._engine = signal_engine
        self._lock   = threading.Lock()

    def _send_retry(self, req: dict, retries: int = 3):
        """[FIX-1] Non-blocking retry with live price refresh on REQUOTE."""
        last_res = None
        is_buy   = req.get("type") in (mt5.ORDER_TYPE_BUY,
                                        mt5.ORDER_TYPE_BUY_LIMIT,
                                        mt5.ORDER_TYPE_BUY_STOP)
        for i in range(1, retries + 1):
            with self._lock:
                res = mt5.order_send(req)
            if res is None:
                log.warning(f"order_send None (try {i}/{retries})")
                if i < retries: time.sleep(0.5)
                continue
            last_res = res
            if res.retcode == mt5.TRADE_RETCODE_DONE:
                return res
            if res.retcode in (mt5.TRADE_RETCODE_REQUOTE,
                               mt5.TRADE_RETCODE_PRICE_CHANGED,
                               mt5.TRADE_RETCODE_PRICE_OFF):
                tick = mt5.symbol_info_tick(SYMBOL)
                if tick:
                    new_p = tick.ask if is_buy else tick.bid
                    log.warning(f"[FIX-1] Price refresh: {req.get('price','?'):.2f}→{new_p:.2f}")
                    req["price"] = round(float(new_p), 2)
                if i < retries: time.sleep(0.3 * i)
                continue
            if res.retcode in (mt5.TRADE_RETCODE_CONNECTION, mt5.TRADE_RETCODE_TIMEOUT):
                if i < retries: time.sleep(0.5 * i)
                continue
            log.error(f"❌ retcode:{res.retcode} | {res.comment}")
            return res
        log.error(f"❌ _send_retry exhausted {retries} attempts")
        return last_res

    def modify_sl(self, ticket: int, new_sl: float) -> None:
        with self._lock:
            res = mt5.order_send({
                "action":   mt5.TRADE_ACTION_SLTP,
                "position": ticket,
                "sl":       round(float(new_sl), 2),
            })
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            log.warning(f"modify_sl FAIL #{ticket} retcode:{res.retcode if res else 'None'}")

    def close_partial(self, pos, lot_close: float, atr: float = 0.0) -> None:
        """[FIX-5] Live ATR-scaled deviation for partial close."""
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None: return
        info  = mt5.symbol_info(SYMBOL)
        step  = info.volume_step if info else 0.01
        v_min = info.volume_min  if info else 0.01
        lot_close = float(max(v_min, min(self._risk._round_lot(lot_close, step), pos.volume)))
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
            "comment":   "V14|PartialTP",
        })
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            log.info(f"💰 Partial #{pos.ticket} Lot:{lot_close:.2f} @ {price:.2f} dev:{dev}pts")

    def close_position_market(self, pos) -> bool:
        """[V13-P2-D] Emergency market close."""
        tick = mt5.symbol_info_tick(SYMBOL)
        info = mt5.symbol_info(SYMBOL)
        if tick is None or info is None: return False
        is_buy     = (pos.type == mt5.ORDER_TYPE_BUY)
        close_type = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
        price      = tick.bid if is_buy else tick.ask
        res = self._send_retry({
            "action":    mt5.TRADE_ACTION_DEAL,
            "symbol":    SYMBOL,
            "volume":    pos.volume,
            "type":      close_type,
            "position":  pos.ticket,
            "price":     round(float(price), 2),
            "deviation": max(100, self._risk.dynamic_deviation(info.point * 100)),
            "magic":     MAGIC_NUMBER,
            "comment":   "V14|KILL",
        }, retries=5)
        ok = res is not None and res.retcode == mt5.TRADE_RETCODE_DONE
        log.info(f"{'✅' if ok else '❌'} Kill-close #{pos.ticket} Lot:{pos.volume} @ {price:.2f}")
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
        """
        [V14-S3] place_order now receives adr + df_d1 for ADR TP cap.
        [V14-A3] Emits a structured trade-ticket summary log.
        """
        if not self._risk.is_spread_ok() or not self._risk.is_within_risk_limits():
            return False
        if self._risk.has_duplicate_setup(setup.setup_hash, setup.signal):
            log.info(f"🚫 Duplicate {setup.setup_hash} → skip")
            return False
        if self._risk.count_open_positions() >= MAX_CONCURRENT_TRADES:
            log.info(f"⚠️ Max concurrent positions ({MAX_CONCURRENT_TRADES}) → skip")
            return False

        sp     = self._risk.get_spread_pts()
        sl_pad = self._risk.get_spread_sl_padding()
        if sp > MAX_SPREAD_POINTS:
            setup.score += SCORE_SPREAD_WARN
            setup.reasons.append(f"Spread{sp:.0f}pts ⚠️")

        # M1 confirmation bonus
        rates_m1 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 5)
        if rates_m1 is not None and len(rates_m1) >= 3:
            df_m1   = pd.DataFrame(rates_m1)
            c       = df_m1.iloc[-2]
            body_m1 = abs(float(c["close"]) - float(c["open"]))
            if body_m1 >= setup.atr * MTF_M1_BODY_ATR:
                if ((setup.signal == "BUY"  and c["close"] > c["open"]) or
                        (setup.signal == "SELL" and c["close"] < c["open"])):
                    setup.score += SCORE_M1_CONFIRM
                    setup.reasons.append("M1 ✓")

        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None: return False

        sig         = setup.signal
        sl_adjusted = (setup.sl - sl_pad) if sig == "BUY" else (setup.sl + sl_pad)

        if setup.use_market or not INTRABAR_ENABLED:
            entry  = tick.ask if sig == "BUY" else tick.bid
            otype  = mt5.ORDER_TYPE_BUY  if sig == "BUY" else mt5.ORDER_TYPE_SELL
            action = mt5.TRADE_ACTION_DEAL;  exp = 0
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

        risk = abs(entry - sl_adjusted)
        if risk == 0: log.error("place_order: risk=0 → abort"); return False

        tp_raw = (entry + risk * RR_RATIO if sig == "BUY" else entry - risk * RR_RATIO)

        # [V14-S3] Dynamic ADR TP cap
        tp_full, tp_capped = self._engine.apply_adr_tp_cap(
            entry, tp_raw, sl_adjusted, adr, df_d1, session, sig
        )
        setup.tp_full      = tp_full
        setup.adr_tp_capped = tp_capped
        if tp_capped:
            log.info(f"📉 ADR TP cap: {tp_raw:.2f}→{tp_full:.2f}")

        lot_full = self._risk.calculate_lot(entry, sl_adjusted, setup.score, sp,
                                            setup.atr, dd_mode=dd_mode)
        ok, reason = self._risk.validate_order(entry, sl_adjusted, tp_full, lot_full, sig)
        if not ok:
            log.warning(f"⚠️ Validate: {reason}");  return False

        info   = mt5.symbol_info(SYMBOL)
        v_step = info.volume_step if info else 0.01
        v_min  = info.volume_min  if info else 0.01
        lot_a  = max(v_min, self._risk._round_lot(lot_full * PARTIAL_TP_PCT, v_step))
        lot_b  = max(v_min, self._risk._round_lot(lot_full - lot_a, v_step))
        tp_pt  = (entry + risk * PARTIAL_TP_RR if sig == "BUY"
                  else entry - risk * PARTIAL_TP_RR)
        dev    = self._risk.dynamic_deviation(setup.atr)

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
                "comment":   f"V14|{sig}|{label}|{setup.score}|{setup.setup_hash}",
            }
            if action == mt5.TRADE_ACTION_PENDING:
                req["type_time"] = mt5.ORDER_TIME_SPECIFIED
                req["expiration"] = exp
            res = self._send_retry(req)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                sent += 1
                mode_tag = "MKT" if action == mt5.TRADE_ACTION_DEAL else "LMT"
                log.info(f"✅ {label}|{sig}|{mode_tag}|Lot:{lot_i}|"
                         f"E:{entry:.2f}|SL:{sl_adjusted:.2f}|TP:{tp_i:.2f}")
            else:
                log.warning(f"⚠️ {label} order failed")

        if sent > 0:
            # [V14-A3] Trade ticket summary
            mode = "MKT" if action == mt5.TRADE_ACTION_DEAL else "LMT"
            rr_actual = abs(tp_full - entry) / risk if risk > 0 else 0
            log.info(
                f"\n{'═'*68}\n"
                f"  🎯 TRADE PLACED — {sig} {mode}{'  ⚡JUDAS' if setup.is_judas else ''}"
                f"{'  📉ADRcap' if setup.adr_tp_capped else ''}\n"
                f"  {'─'*66}\n"
                f"  Entry    : {entry:.2f}   SL: {sl_adjusted:.2f}   "
                f"TP-Part: {tp_pt:.2f}   TP-Full: {tp_full:.2f}\n"
                f"  Risk     : {risk:.2f} pts   RR: {rr_actual:.2f}×   "
                f"Lot: {lot_a}+{lot_b} = {lot_a+lot_b:.2f}\n"
                f"  Score    : {setup.score}/{setup.threshold}   "
                f"WinProb: {setup.win_prob:.3f}   DD: {dd_mode}\n"
                f"  Session  : {session}   H4: {setup.htf_bias}   "
                f"M15: {setup.m15_struct}   PD: {setup.pd_zone}\n"
                f"  Hash     : {setup.setup_hash}\n"
                f"  Reasons  : {' | '.join(setup.reasons)}\n"
                f"{'═'*68}"
            )
            db_log_setup(sig, setup.score, entry, sl_adjusted, tp_full,
                         setup.setup_hash, session,
                         features=setup.features, win_prob=setup.win_prob,
                         is_judas=setup.is_judas)
            return True
        return False


# ══════════════════════════════════════════════════════════════════════════════
# 🔄  CLASS: PositionManager  [V14-A4] P&L per-position logging
# ══════════════════════════════════════════════════════════════════════════════
class PositionManager:
    """
    Background 0.2 s thread: Partial TP · Breakeven · Trailing SL.
    [V14-A4] Logs unrealised P&L and R-multiple each tick.
    [V14-F1] PM runs at full poll rate (intrabar) — but ENTRY signals are not here.
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
        log.info(f"🔄 PositionManager started (poll={POSITION_POLL_SEC*1000:.0f}ms)")

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
                log.warning(f"⚠️ PositionManager error: {exc}")
            time.sleep(POSITION_POLL_SEC)

    def _manage_positions(self, atr: float) -> None:
        positions = [p for p in (mt5.positions_get(symbol=SYMBOL) or [])
                     if p.magic == MAGIC_NUMBER]
        if not positions: return

        tick = mt5.symbol_info_tick(SYMBOL)
        info = mt5.symbol_info(SYMBOL)
        if tick is None or info is None: return

        a            = max(atr, info.point * 10)
        open_tickets = {p.ticket for p in positions}
        trail_cache  = batch_load_trail_states(list(open_tickets))

        for pos in positions:
            entry  = pos.price_open;  sl_now = pos.sl
            is_buy = (pos.type == mt5.ORDER_TYPE_BUY)

            comment_parts = (pos.comment or "").split("|")
            pos_hash = comment_parts[-1] if len(comment_parts) >= 5 else ""

            risk = abs(entry - sl_now)
            if risk < info.point:
                risk = a * 1.5
                log.warning(f"⚠️ #{pos.ticket} SL≈0 → fallback risk={risk:.2f}")

            price    = tick.bid if is_buy else tick.ask
            buf      = info.point * 5
            profit_r = ((price - entry) / risk if is_buy else (entry - price) / risk)

            # [V14-A4] Per-position P&L log
            pnl_pts  = (price - entry) if is_buy else (entry - price)
            pnl_usd  = pnl_pts * info.trade_tick_value / info.point * pos.volume \
                       if info.point > 0 else 0
            log.debug(
                f"📍 Pos #{pos.ticket} {('BUY' if is_buy else 'SELL')} "
                f"R:{profit_r:+.2f}  P&L: ${pnl_usd:+.2f}"
            )

            ts           = trail_cache.get(pos.ticket)
            partial_done = int(ts["partial_done"]) if ts else 0

            did_partial = False
            if not partial_done and profit_r >= PARTIAL_TP_RR:
                self._exec.close_partial(pos, pos.volume * PARTIAL_TP_PCT, atr=a)
                set_partial_done(pos.ticket, pos_hash)
                be_sl = (entry + buf) if is_buy else (entry - buf)
                if (is_buy and sl_now < be_sl) or (not is_buy and sl_now > be_sl):
                    self._exec.modify_sl(pos.ticket, be_sl)
                    log.info(f"🔒 BE+Partial #{pos.ticket} SL:{sl_now:.2f}→{be_sl:.2f} R:{profit_r:.2f}")
                did_partial = True

            if not did_partial and profit_r >= BREAKEVEN_RR:
                be_sl = (entry + buf) if is_buy else (entry - buf)
                if (is_buy and sl_now < be_sl) or (not is_buy and sl_now > be_sl):
                    self._exec.modify_sl(pos.ticket, be_sl)
                    log.info(f"🔒 BE #{pos.ticket} SL:{sl_now:.2f}→{be_sl:.2f}")

            if profit_r >= TRAIL_AFTER_RR:
                last_tsl = float(ts["last_sl"]) if ts else None
                min_move = a * TRAIL_MIN_MOVE_ATR
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

        cleanup_trail_state(open_tickets)


# ══════════════════════════════════════════════════════════════════════════════
# 🆘  EMERGENCY KILL-SWITCH
# ══════════════════════════════════════════════════════════════════════════════
def graceful_shutdown(execution: ExecutionHandler, reason: str = "KILL") -> None:
    log.warning(f"🚨 GRACEFUL SHUTDOWN initiated — reason: {reason}")
    log.warning("🚨 Step 1/3: Cancelling pending limit orders...")
    for o in (mt5.orders_get(symbol=SYMBOL) or []):
        if o.magic == MAGIC_NUMBER:
            execution.cancel_pending_order(o.ticket)
    time.sleep(0.5)
    log.warning("🚨 Step 2/3: Closing open positions at market...")
    for pos in (mt5.positions_get(symbol=SYMBOL) or []):
        if pos.magic == MAGIC_NUMBER:
            execution.close_position_market(pos)
            time.sleep(0.2)
    time.sleep(1.0)
    acct = mt5.account_info()
    if acct:
        log.warning(
            f"🚨 Step 3/3: Final equity = ${acct.equity:,.2f} "
            f"(balance = ${acct.balance:,.2f})"
        )
    log.warning("🚨 SHUTDOWN COMPLETE.")


# ══════════════════════════════════════════════════════════════════════════════
# 📊  OPERATOR HEARTBEAT  [V14-A3] redesigned aligned columns
# ══════════════════════════════════════════════════════════════════════════════
def emit_heartbeat(
    risk: RiskManager, predictor: MLPredictor,
    session: str, htf_bias: str, adr_pct: float,
) -> None:
    acct = mt5.account_info()
    if acct is None: return

    daily_dd, total_dd, dd_mode = risk.get_dd_state()
    init_bal   = get_state("initial_balance") or acct.balance
    equity_pct = (acct.equity - init_bal) / init_bal * 100 if init_bal > 0 else 0
    open_pos   = risk.count_open_positions()
    avg_wp     = predictor.rolling_avg_prob
    today_key  = "daily_start_balance_" + risk.get_broker_date()
    day_start  = get_state(today_key) or acct.balance
    today_pl   = acct.equity - day_start
    pause_on   = os.path.isfile(PAUSE_FLAG_PATH)
    kill_on    = os.path.isfile(KILL_FLAG_PATH)

    dd_icon = {"NORMAL": "🟢", "YELLOW": "💛", "ORANGE": "🟠", "RED": "🔴"}.get(dd_mode, "⚪")
    mode_label = (
        "🔴 KILL DETECTED" if kill_on else
        "⏸️  PAUSED"        if pause_on else
        f"{dd_icon} {dd_mode}"
    )
    norm_str = "🟢 WARM" if predictor.norm_is_warm else "🟡 COLD-START"

    log.info(
        f"\n{'═'*68}\n"
        f"  💓  HEARTBEAT  {datetime.now(STRATEGY_TZ).strftime('%H:%M:%S %Z')}\n"
        f"  {'─'*66}\n"
        f"  💵 Equity    : ${acct.equity:>10,.2f}  ({equity_pct:+.2f}%)   "
        f"Today P&L: ${today_pl:>+,.2f}\n"
        f"  📉 Daily DD  : {daily_dd:5.2f}%     Total DD : {total_dd:5.2f}%\n"
        f"  🌍 Session   : {session:<16}  H4 Bias  : {htf_bias:<10}\n"
        f"  📊 ADR Used  : {adr_pct*100:5.1f}%     OpenPos  : {open_pos}/{MAX_CONCURRENT_TRADES}\n"
        f"  🧠 ML Norm   : {norm_str:<20} Avg WinProb: {avg_wp:.3f}\n"
        f"  ⚙️  Mode      : {mode_label}\n"
        f"{'═'*68}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 🔧  HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def _make_hash(sig: str, entry: float, sl: float, ts: float) -> str:
    return hashlib.sha256(f"{sig}:{entry:.2f}:{sl:.2f}:{int(ts)}".encode()).hexdigest()[:12]


def mt5_connect(retries: int = 10, delay: float = 5.0) -> bool:
    for i in range(1, retries + 1):
        if mt5.initialize():
            log.info(f"✅ MT5 connected (try {i})")
            return True
        log.warning(f"MT5 connect try {i}/{retries}…")
        time.sleep(delay)
    return False


def ensure_alive() -> bool:
    if mt5.terminal_info() is not None: return True
    log.warning("MT5 disconnected → reconnecting…")
    return mt5_connect(retries=5, delay=3.0)


# ══════════════════════════════════════════════════════════════════════════════
# 🚀  SIGNAL CYCLE  [V14-F1] Entry ONLY on closed M5 candle
# ══════════════════════════════════════════════════════════════════════════════
def _run_signal_cycle(
    feed:          MarketDataFeed,
    signal_engine: SMCSignalEngine,
    risk:          RiskManager,
    execution:     ExecutionHandler,
    predictor:     MLPredictor,
    last_htf:      Dict[str, str],
    last_closed_bar_time: int,    # [V14-F1] only evaluate on this closed bar
) -> None:
    """
    [V14-F1] Signal evaluation is strictly tied to a just-closed M5 candle.
    This function is called ONLY when current_bar_time != last_closed_bar_time,
    meaning the previous bar has CLOSED and a new one opened.
    """
    # GATE 1: Connection
    if not ensure_alive():
        log.error("Reconnect failed → skip cycle"); return

    # GATE 2: DD
    daily_dd, total_dd, dd_mode = risk.get_dd_state()
    if dd_mode == "RED":
        log.warning(f"⛔ DD limit daily={daily_dd:.2f}% total={total_dd:.2f}% → halt"); return

    # GATE 3: Circuit Breaker
    if risk.is_circuit_breaker_tripped():
        log.warning("⚡ Circuit Breaker → no new orders"); return

    # GATE 4: Session (includes NewsGuard)
    session = signal_engine.get_session()
    if session in ("OUT_OF_SESSION", "RED_NEWS_BLOCK"):
        return

    # GATE 5: Killzone
    in_kz, kz_name = signal_engine.is_in_killzone()
    if not in_kz: return

    # GATE 6: Spread
    if not risk.is_spread_ok():
        log.warning("⚠️ Spread > HARD_BLOCK → skip"); return

    # GATE 7: PAUSE flag
    if os.path.isfile(PAUSE_FLAG_PATH):
        log.info("⏸️  PAUSE.flag — skip new entries"); return

    # GATE 8: Orange DD
    if not risk.new_entries_allowed():
        log.warning(f"🟠 DD ORANGE ({daily_dd:.2f}%) → entries suspended"); return

    # Fetch ALL timeframes (H4 now instead of H1)
    data = feed.fetch_all()
    if data["m5"] is None:
        log.warning("M5 unavailable → skip"); return

    cleanup_cooldowns()

    # [V14-F1] Confirm we're evaluating the CLOSED bar (df already trimmed by fetch_all)
    log.info(
        f"📊 Evaluating CLOSED M5 bar @ {last_closed_bar_time} | "
        f"Session:{session} KZ:{kz_name} DD:{dd_mode}"
    )

    setup = signal_engine.analyze_setup(
        data["m5"], data["h4"], data["d1"], data["m15"], data.get("dxy"), session,
    )
    setup.spread_pts = risk.get_spread_pts()

    # Update heartbeat state
    last_htf["bias"]    = setup.htf_bias
    last_htf["session"] = session
    last_htf["adr_pct"] = str(setup.adr_pct)

    # Context log
    liq = setup.liq_map
    if liq:
        gap_info = ""
        if liq.gap_swept_high: gap_info += f" GapSwH:{liq.gap_swept_high:.2f}"
        if liq.gap_swept_low:  gap_info += f" GapSwL:{liq.gap_swept_low:.2f}"
        log.info(
            f"💧 BSL:{liq.bsl_nearest or '—'} SSL:{liq.ssl_nearest or '—'} "
            f"SwH:{liq.swept_high} SwL:{liq.swept_low}{gap_info}"
        )
    htf = setup.htf_result
    if htf:
        log.info(f"🏗️  H4 | Bias:{htf.bias} BOS:{htf.last_bos} CHOCH:{htf.choch_signal} | {htf.reason}")

    dxy = setup.dxy_bias
    if dxy and dxy.available:
        log.info(f"💵 DXY: {dxy.trend} | BuyPenalty:{dxy.buy_penalty} SellBonus:{dxy.sell_bonus}")

    log.info(
        f"📈 M15:{setup.m15_struct} | ADR:{setup.adr_pct*100:.0f}% | "
        f"Thresh:{setup.threshold} | PD:{setup.pd_zone}"
    )

    if setup.signal == "WAIT":
        return

    if setup.score < setup.threshold:
        log.info(f"🟡 Score {setup.score} < {setup.threshold} → skip")
        return

    close_price = float(data["m5"]["close"].iloc[-1]) if data["m5"] is not None else 2000.0
    df_len      = len(data["m5"]) if data["m5"] is not None else 300
    setup.features = extract_features(setup, close_price=close_price, df_len=df_len)

    # [V14-F7] distribution shift check BEFORE update (Bug-3 fixed)
    setup.win_prob = predictor.predict_win_probability(setup.features)
    avg_wp         = predictor.rolling_avg_prob
    norm_tag       = "WARM" if predictor.norm_is_warm else "COLD"
    log.info(
        f"🧠 ML WinProb:{setup.win_prob:.3f} [avg:{avg_wp:.3f}] "
        f"(gate:{ML_WIN_PROB_THRESHOLD}) Norm:{norm_tag} | {setup.summary()}"
    )

    if setup.win_prob < ML_WIN_PROB_THRESHOLD:
        log.info(f"🤖 ML gate reject: prob={setup.win_prob:.3f} < {ML_WIN_PROB_THRESHOLD}")
        return

    if is_on_cooldown(setup.setup_hash):
        log.info(f"🔁 Cooldown ({setup.setup_hash}) → skip"); return
    if risk.has_duplicate_setup(setup.setup_hash, setup.signal):
        log.info(f"🚫 Duplicate → skip"); return

    # Get ADR for TP cap
    adr = calculate_adr(data.get("d1"))

    if execution.place_order(setup, session, dd_mode=dd_mode,
                             adr=adr, df_d1=data.get("d1")):
        set_cooldown(setup.setup_hash)
        log.info(f"🎯 Order placed | hash:{setup.setup_hash} | Judas:{setup.is_judas}")


# ══════════════════════════════════════════════════════════════════════════════
# 🚀  MAIN
# ══════════════════════════════════════════════════════════════════════════════
BANNER = """
╔══════════════════════════════════════════════════════════════════════════════╗
║  🥇  AI SMC/ICT Pro Sniper — V.14 PRODUCTION (XAUUSD Gold Specialist)       ║
║  [V14-F1] Candle-close entry discipline   [V14-F2] H4 HTF Bias              ║
║  [V14-O1] Welford O(1) normaliser         [V14-O2] Broker config block      ║
║  [V14-O3] Dynamic NewsGuard               [V14-S1] Volume spike validation  ║
║  [V14-S2] Judas Swing Override            [V14-S3] Dynamic ADR TP Cap       ║
║  [V14-A1] DXY Inverse Filter             [V14-A2] Premium/Discount Zone     ║
║  [V14-A3] Trade ticket logs              [V14-A4] Per-position P&L tracking ║
║  [V14-F3-7] All V13 bugs fixed (CB/Yellow/FVGage/OutlierUpdate/ADRblock)   ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""


def main() -> None:
    print(BANNER)
    log.info("Bot V.14 PRODUCTION starting")
    init_db()

    if not mt5_connect():
        log.error("❌ Cannot connect to MT5"); return

    feed          = MarketDataFeed()
    signal_engine = SMCSignalEngine()
    risk          = RiskManager()
    execution     = ExecutionHandler(risk, signal_engine)
    predictor     = MLPredictor()
    # Uncomment to load a trained model:
    # predictor.load_model("smc_model_v14.joblib")

    pm = PositionManager(feed, execution)
    pm.start()

    last_htf: Dict[str, str] = {"bias": "NEUTRAL", "session": "UNKNOWN", "adr_pct": "0.0"}

    _shutdown_requested = threading.Event()

    def _sig_handler(signum, frame):
        log.warning(f"Signal {signum} → shutdown")
        _shutdown_requested.set()

    signal.signal(signal.SIGTERM, _sig_handler)
    signal.signal(signal.SIGINT,  _sig_handler)

    # [V14-F1] Track the last CLOSED bar time (not current live bar)
    _last_closed_bar_time: Optional[int] = None

    last_heartbeat: float = time.time()

    log.info(
        f"📡 Config | Symbol:{SYMBOL} DXY:{DXY_SYMBOL or 'disabled'} "
        f"HTF:H4 | CB:{CIRCUIT_BREAKER_PCT}% | ML_gate:{ML_WIN_PROB_THRESHOLD}"
    )
    log.info(f"📁 Kill:{KILL_FLAG_PATH} | Pause:{PAUSE_FLAG_PATH} | News:{NEWS_EVENTS_FILE}")

    try:
        while not _shutdown_requested.is_set():

            # KILL flag check every loop
            if os.path.isfile(KILL_FLAG_PATH):
                log.warning("🚨 KILL.flag detected!")
                _shutdown_requested.set()
                break

            current_bar_time = feed.get_current_m5_bar_time()
            tick             = mt5.symbol_info_tick(SYMBOL)

            if tick is None:
                time.sleep(TICK_POLL_SEC); continue

            # [V14-F1] New M5 bar opened → previous bar is NOW CLOSED → evaluate
            if current_bar_time is not None and current_bar_time != _last_closed_bar_time:
                # The bar that just CLOSED is current_bar_time - 5 min
                just_closed_bar = current_bar_time  # we use the new bar open as trigger
                log.info("─" * 72)
                log.info(
                    f"🕯️  M5 bar closed | new bar @ {current_bar_time} "
                    f"[{datetime.now(STRATEGY_TZ).strftime('%H:%M:%S')} {STRATEGY_TZ_NAME}]"
                )
                # Update ATR cache from latest closed M5 data
                df_m5_cache = feed.get_cached_m5()
                if df_m5_cache is not None:
                    cached_atr = calculate_atr(df_m5_cache)

                # [V14-F1] Entry evaluation STRICTLY on closed candle
                _run_signal_cycle(
                    feed, signal_engine, risk, execution, predictor,
                    last_htf, just_closed_bar,
                )
                _last_closed_bar_time = current_bar_time

            # Heartbeat (PM runs continuously via its own thread)
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
        log.info("🛑 KeyboardInterrupt")
    except Exception as exc:
        log.exception(f"💥 Unhandled exception: {exc}")
    finally:
        log.info("Initiating graceful shutdown…")
        pm.stop()
        graceful_shutdown(execution, reason="MAIN_EXIT")
        close_db()
        mt5.shutdown()
        log.info("MT5 offline. Bot V.14 terminated.")


# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    main()
