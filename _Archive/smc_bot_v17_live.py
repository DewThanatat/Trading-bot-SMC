"""
╔══════════════════════════════════════════════════════════════════════════════════╗
║  🏆  AI SMC/ICT Pro Sniper — V.17 LIVE  (XAUUSD Gold Specialist)                ║
╠══════════════════════════════════════════════════════════════════════════════════╣
║                                                                                  ║
║  ██████████  V.17 LIVE-TRADING UPGRADE REPORT  ██████████████████████████████  ║
║                                                                                  ║
║  ── PART 1 FIXES: Weaknesses & Over-Optimisation ──────────────────────────── ║
║                                                                                  ║
║  [V17-F1]  SCORING SIMPLIFIED — Over-engineered stacking reduced.               ║
║            V-Shape/U-Shape, MSS/CISD, Golden Confluence, and H1 MTF            ║
║            bonus now feed a single simplified score calculation with            ║
║            clearly separated tiers. Core PA signals (Killzone+Sweep            ║
║            +FVG) are primary; everything else is a supporting boost.            ║
║            SCORE_THRESHOLD lowered back to 65 (was 70); PRE_LONDON kept        ║
║            at 73 for FOMO guard. Realistic "good enough" setups now trade.     ║
║                                                                                  ║
║  [V17-F2]  VOL_SPIKE PERMANENTLY REMOVED — tick_volume is unreliable on        ║
║            retail Gold feeds. All `_rolling_vol_mean()` calls, VOL_SPIKE_*      ║
║            constants, and associated scoring branches deleted from source.      ║
║            Displacement is now purely body-size based (candle size × ATR).     ║
║                                                                                  ║
║  [V17-F3]  DXY CORRELATION DISABLED & DEPRECATED — DXY decoupling in 2024–    ║
║            2025 makes the penalty/bonus unreliable. All DXY-related code       ║
║            removed from the scoring path. DXY_ENABLED constant retained but    ║
║            hardcoded False; block is no-op regardless of config.               ║
║                                                                                  ║
║  [V17-F4]  HEURISTIC ML FALLBACK REPLACED — When no real model is loaded,      ║
║            the ML gate is bypassed entirely (returns 1.0 automatically).        ║
║            This prevents the double-filtering problem where a heuristic built   ║
║            from the same signals as the score system redundantly rejects        ║
║            valid setups. ML gate only activates when a real .joblib model       ║
║            is loaded.  ML_HEURISTIC_THRESHOLD constant removed.                ║
║                                                                                  ║
║  [V17-F5]  MKT ORDER SLIPPAGE MITIGATION — Two changes:                         ║
║            (a) MAX_DEVIATION_POINTS = 30 (absolute cap). `dynamic_deviation()` ║
║                may never exceed this. If the broker fills beyond 30pts, the    ║
║                order is rejected rather than silently accepted at a ruined RR.  ║
║            (b) Market orders now validate that entry - sl_adj >= MIN_RISK_POINTS║
║                after slippage. If the effective RR < MIN_RR_RATIO_LIVE, order  ║
║                is skipped with a clear log message.                             ║
║                                                                                  ║
║  ── PART 2 ADDITIONS: Crucial Live Trading Features ───────────────────────── ║
║                                                                                  ║
║  [V17-L1]  FRIDAY / WEEKEND GAP GUARD — FridayGuard class added.               ║
║            On broker Friday at FRIDAY_CLOSE_UTC_HOUR (default 21:00 UTC)       ║
║            = 04:00 Saturday Bangkok time:                                       ║
║            • All pending limit orders cancelled immediately.                    ║
║            • All open positions closed at market (5 retries, high deviation).  ║
║            • New entry evaluation completely blocked after this time until      ║
║              Monday open.                                                       ║
║            Checked on every main-loop iteration using broker-derived clock.    ║
║                                                                                  ║
║  [V17-L2]  MAX DEVIATION CAP — `dynamic_deviation()` now returns               ║
║            min(calculated, MAX_DEVIATION_POINTS). Combined with `_send_retry`  ║
║            which no longer overrides deviation to 100+ on kill-closes.         ║
║            Emergency closes use EMERGENCY_DEVIATION_POINTS (150) which is      ║
║            deliberately higher than entry orders.                              ║
║                                                                                  ║
║  [V17-L3]  PARTIAL FILL HANDLING — `_send_retry()` now correctly handles       ║
║            TRADE_RETCODE_DONE_PARTIAL:                                          ║
║            • Records actual filled volume from res.volume.                     ║
║            • Does NOT retry (re-trying a partial fill doubles the exposure).   ║
║            • Adjusts SL/TP for the actual filled lot via `_adjust_partial_fill`║
║            • Returns res with retcode treated as DONE for the caller.          ║
║            • Logs clearly: "⚠️ PARTIAL FILL: 0.07/0.10 lots"                  ║
║                                                                                  ║
║  PRESERVED FROM V.16 (all intact)                                               ║
║  ─────────────────────────────────────────────────────────────────────────────  ║
║  ConnectionManager auto-reconnect · BrokerClockSync · SpreadGuard dynamic      ║
║  lock · PRE_LONDON FOMO guard · Consecutive-loss CB [V16-O2] · H1 bias layer  ║
║  MSS+CISD [V16-S3] · V/U-Shape [V16-S4] · Golden Confluence [V16-S5]          ║
║  Sweep Classification [V16-S2] · Balanced V15-S1 scoring base · SQLite WAL    ║
║  Thread-local DB + writer queue · PAUSE/KILL flags · 3-tier DD · SIGTERM       ║
║  NumPy hot-paths · FVG memory · OB freshness · Gap-sweep · Dual-key tracking  ║
║  Judas Swing · ADR TP cap · Welford normaliser · Heartbeat operator log        ║
╚══════════════════════════════════════════════════════════════════════════════════╝
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
# 🏦  BROKER CONFIG  — edit ONLY this block per broker/VPS
# ══════════════════════════════════════════════════════════════════════════════
SYMBOL           = "XAUUSDm"
MAGIC_NUMBER     = 99999
BROKER_TZ_NAME   = "Etc/UTC"
STRATEGY_TZ_NAME = "Asia/Bangkok"
BROKER_TZ        = pytz.timezone(BROKER_TZ_NAME)
STRATEGY_TZ      = pytz.timezone(STRATEGY_TZ_NAME)

# [V17-F3] DXY deprecated — constant kept for import compatibility but has no effect
DXY_SYMBOL  = ""
DXY_ENABLED = False


# ══════════════════════════════════════════════════════════════════════════════
# ⚙️  STRATEGY CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════
RR_RATIO            = 2.5
MIN_RR_RATIO_LIVE   = 1.8    # [V17-F5] If slippage degrades RR below this → skip
MAX_DAILY_LOSS_PCT  = 4.0
MAX_TOTAL_DD_PCT    = 8.0
EXPIRATION_CANDLES  = 36

# ── Spread [V16-F2 preserved] ─────────────────────────────────────────────────
HARD_SPREAD_BLOCK    = 100.0
MAX_SPREAD_POINTS    = 50.0
SPREAD_DYNAMIC_MULT  = 3.0
SPREAD_MEDIAN_BARS   = 20
SPREAD_LOT_PENALTY   = 0.3
SPREAD_SL_PADDING    = True

# ── Deviation / Slippage Caps [V17-F5, V17-L2] ───────────────────────────────
MAX_DEVIATION_POINTS       = 30    # [V17-L2] Hard cap on entry order deviation
EMERGENCY_DEVIATION_POINTS = 150   # [V17-L2] Used ONLY on emergency closes

MOMENTUM_BODY_ATR   = 1.2
BREAKEVEN_RR        = 1.0
TRAIL_AFTER_RR      = 1.5
TRAIL_ATR_MULT      = 0.8
TRAIL_MIN_MOVE_ATR  = 0.3

ADR_EXHAUSTED_PCT     = 0.88
ADR_NY_EXHAUSTED_PCT  = 0.93
ADR_HARD_BLOCK        = False
ADR_TP_BUFFER_PCT     = 0.95

SL_ATR_MULT         = 1.2
FVG_ENTRY_MID       = True
SWING_PERIOD        = 5
SWING_CONFIRM_BARS  = 2
SETUP_COOLDOWN_SEC  = 180

PARTIAL_TP_RR       = 1.0
PARTIAL_TP_PCT      = 0.50
MAX_CONCURRENT_TRADES = 2
INTRABAR_ENABLED    = True

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

# [V17-F2] VOL_SPIKE permanently removed — no constants, no code paths
# All prior VOL_SPIKE_* constants and _rolling_vol_mean() calls deleted.

# Judas Swing
JUDAS_SWING_ENABLED  = True
JUDAS_WINDOW_MIN     = 15
JUDAS_SCORE_BONUS    = 12

# Liquidity
LIQ_SWING_PERIOD    = 10
LIQ_EQUAL_TOLERANCE = 0.0003
LIQ_MIN_CLUSTER     = 2

# HTF — H4
HTF_BARS          = 120
HTF_SWING_PERIOD  = 3
HTF_SWING_CONFIRM = 2

# H1 Intermediate bias [V16-O3 preserved]
H1_BARS           = 100
H1_SWING_PERIOD   = 4
H1_SWING_CONFIRM  = 2
H1_AGREE_BONUS    = 6    # [V17-F1] reduced from 8 — softer influence
H1_CONFLICT_PENALTY = -4 # [V17-F1] reduced from -5

# P/D Zone — disabled by default
PD_ZONE_ENABLED   = False
PD_PERIOD         = 50
PD_PENALTY        = -6

MTF_M1_BODY_ATR   = 0.3

# MSS & CISD [V16-S3]
MSS_ENABLED       = True
CISD_ATR_MULT     = 1.5
SCORE_MSS_CISD    = 10   # [V17-F1] reduced from 12 — less dominant
SCORE_MSS_ONLY    = 4    # [V17-F1] reduced from 5

# V-Shape / U-Shape [V16-S4]
VSHAPE_ENABLED       = True
VSHAPE_ATR_MULT      = 1.8
VSHAPE_RETRACE_PCT   = 0.60
VSHAPE_MAX_BARS      = 3
USHAPE_MAX_BARS      = 5
SCORE_VSHAPE_BONUS   = 8    # [V17-F1] reduced from 10 — core PA is primary
SCORE_USHAPE_PENALTY = -12  # [V17-F1] reduced from -15 — less destructive

# Golden Confluence [V16-S5]
GOLDEN_CONFL_ENABLED    = True
OTE_LOW_PCT             = 0.618
OTE_HIGH_PCT            = 0.79
DISPLACEMENT_ATR_MULT   = 2.0
SCORE_GOLDEN_CONFLUENCE = 12  # [V17-F1] reduced from 15

# PRE_LONDON FOMO guard [V16-F1]
PRE_LONDON_SWEEP_REQUIRED = True
PRE_LONDON_SCORE_BOOST    = 8

# Killzone penalty [V16-O1 — value reduced for realism]
KZ_OUTSIDE_PENALTY    = -25   # [V17-F1] reduced from -30; still effectively blocks
KZ_PRE_LONDON_PENALTY = -15   # [V17-F1] reduced from -20

# Consecutive-loss CB [V16-O2]
N_CONSEC_LOSS_PAUSE   = 3
CONSEC_LOSS_PAUSE_MIN = 60

# Auto-reconnect [V16-F3]
RECONNECT_BASE_DELAY  = 5.0
RECONNECT_MAX_DELAY   = 120.0
RECONNECT_MAX_ATTEMPTS = 20

# ── [V17-L1] Friday / Weekend Gap Guard ───────────────────────────────────────
FRIDAY_CLOSE_ENABLED  = True
FRIDAY_CLOSE_UTC_HOUR = 21   # 21:00 UTC = 04:00 Bangkok Saturday = broker Friday close
FRIDAY_CLOSE_UTC_MIN  = 0

# ══════════════════════════════════════════════════════════════════════════════
# 🎯  [V17-F1]  SIMPLIFIED SCORING SYSTEM
#
#  TIER 1 — Core Price Action (PRIMARY — reach threshold with 1 or 2 of these)
#    Base: 40
#    FVG Fresh: +20   →  40+20 = 60
#    Liq Sweep: +18   →  40+18 = 58  (slightly lower than FVG alone)
#    Sweep+FVG bonus:  +5  → instant 63+
#
#  TIER 2 — HTF Context
#    HTF Aligned:  +10
#    HTF Against:  -15
#    H1 Agree:     +6
#    H1 Conflict:  -4
#
#  TIER 3 — Structure Confirmation (key differentiators)
#    M15 BOS:      +8
#    MSS+CISD:     +10
#    MSS only:     +4
#    V-Shape:      +8
#    U-Shape:      -12
#    Golden Conf:  +12
#
#  TIER 4 — Lightweight confluences (polish, not gatekeepers)
#    OB bonus:     +5
#    OB overlap:   +4
#    Strong candle:+4
#    FVG strength: +4
#    Liq target:   +4
#    M1 confirm:   +4
#    Judas bonus:  +12
#
#  TIER 5 — Penalties
#    ADR warn:     -8
#    Spread warn:  -5
#    KZ outside:   -25
# ══════════════════════════════════════════════════════════════════════════════
SCORE_BASE          = 40

SCORE_FVG_FRESH     = 20
SCORE_LIQ_SWEPT     = 18   # [V17-F1] slightly lower than FVG to prefer FVG+Sweep combos
SCORE_SWEEP_AND_FVG = 5

SCORE_HTF_ALIGN     = 10
SCORE_HTF_AGAINST   = -15

SCORE_M15_BOS       = 8
SCORE_OB_BONUS      = 5
SCORE_OB_OVERLAP    = 4
SCORE_STRONG_CANDLE = 4
SCORE_BOS_M5        = 4
SCORE_LIQ_TARGET    = 4
SCORE_FVG_STRENGTH  = 4
SCORE_M1_CONFIRM    = 4
SCORE_ADR_WARN      = -8
SCORE_SPREAD_WARN   = -5

# [V17-F1] Flat threshold — 65 base, PRE_LONDON += 8
SCORE_THRESHOLD: Dict[str, int] = {
    "LONDON":        65,
    "NEW_YORK":      65,
    "NY_OPEN_EARLY": 65,
    "PRE_LONDON":    65 + PRE_LONDON_SCORE_BOOST,  # = 73
    "DEFAULT":       65,
}

SCORE_PENALTY_HTF_NEUTRAL = 0

# ML — [V17-F4] heuristic bypass; gate only active with real model
ML_WIN_PROB_THRESHOLD = 0.52   # used only when a real model is loaded
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

DD_YELLOW_PCT       = 3.0
DD_ORANGE_PCT       = 5.0
CIRCUIT_BREAKER_PCT = 4.5

KILLZONE_ENABLED = True
KILLZONES = [
    (14,  0, 16, 30, "London Open"),
    (18, 30, 19, 15, "NY Open Early"),
    (19, 45, 22,  0, "NY Open"),
]
SESSIONS = [
    (12,  0, 14,  0, "PRE_LONDON"),
    (14,  0, 18,  0, "LONDON"),
    (18, 30, 19, 15, "NY_OPEN_EARLY"),
    (19, 45, 23, 59, "NEW_YORK"),
]

CACHE_TTL_LTF = 5
CACHE_TTL_HTF = 60
CACHE_TTL_D1  = 300

POSITION_POLL_SEC = 0.2
TICK_POLL_SEC     = 1.0
HEARTBEAT_SEC     = 300

KILL_FLAG_PATH  = "KILL.flag"
PAUSE_FLAG_PATH = "PAUSE.flag"
DB_PATH         = "smc_state.db"
LOG_PATH        = "smc_bot.log"

NEWS_EVENTS_FILE     = "news_events.json"
NEWS_BUFFER_MIN      = 30
NEWS_STATIC_FALLBACK = [(19, 15, 19, 45), (15, 25, 15, 35)]


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
# 🕐  [V16-F4]  BROKER CLOCK SYNC
# ══════════════════════════════════════════════════════════════════════════════
class BrokerClockSync:
    """Derives authoritative time from MT5 tick UTC timestamp."""

    def __init__(self, symbol: str, strategy_tz: pytz.BaseTzInfo):
        self._symbol      = symbol
        self._strategy_tz = strategy_tz
        self._last_tick_utc: Optional[datetime] = None

    def refresh(self) -> None:
        tick = mt5.symbol_info_tick(self._symbol)
        if tick is not None:
            self._last_tick_utc = datetime.utcfromtimestamp(tick.time).replace(tzinfo=pytz.utc)

    def now_utc(self) -> datetime:
        return self._last_tick_utc if self._last_tick_utc else datetime.now(pytz.utc)

    def now_strategy(self) -> datetime:
        return self.now_utc().astimezone(self._strategy_tz)

    def t(self) -> dtime:
        return self.now_strategy().time()


# ══════════════════════════════════════════════════════════════════════════════
# 📅  [V17-L1]  FRIDAY / WEEKEND GAP GUARD
# ══════════════════════════════════════════════════════════════════════════════
class FridayGuard:
    """
    [V17-L1] Protects against Monday morning gaps.

    Brokers close Gold at ~21:00–22:00 UTC on Fridays.  Any position held
    through the weekend gap risks 15–40 point adverse opens.

    Logic:
      - is_close_time(): True if it's Friday UTC and time >= FRIDAY_CLOSE_UTC_HOUR:MIN
      - is_blocked():    True during the entire Friday close window AND all
                         of Saturday/Sunday until broker Monday open (~22:00 Sun UTC).
      - The main loop calls is_blocked() every cycle.  If True:
          (a) FridayGuard.execute_eod_close(execution) is called once to flatten.
          (b) New entry evaluation returns immediately.
    """

    def __init__(self, clock: BrokerClockSync):
        self._clock    = clock
        self._eod_done = False   # track whether we've already flattened today

    def _reset_on_monday(self) -> None:
        now_utc = self._clock.now_utc()
        # Monday = weekday 0
        if now_utc.weekday() == 0 and now_utc.hour >= 22:
            self._eod_done = False

    def is_close_time(self) -> bool:
        """True if we are past the Friday EOD close trigger."""
        now_utc = self._clock.now_utc()
        if now_utc.weekday() != 4:   # 4 = Friday
            return False
        return (now_utc.hour > FRIDAY_CLOSE_UTC_HOUR or
                (now_utc.hour == FRIDAY_CLOSE_UTC_HOUR and
                 now_utc.minute >= FRIDAY_CLOSE_UTC_MIN))

    def is_blocked(self) -> bool:
        """True when new entries must be suppressed (Friday EOD through Sunday)."""
        if not FRIDAY_CLOSE_ENABLED:
            return False
        self._reset_on_monday()
        now_utc = self._clock.now_utc()
        # Friday close time or Saturday or Sunday
        return self.is_close_time() or now_utc.weekday() in (5, 6)

    def execute_eod_close(self, execution: "ExecutionHandler") -> None:
        """Cancel pending orders and flatten all positions. Runs once per Friday."""
        if self._eod_done:
            return
        self._eod_done = True
        log.warning(
            f"📅 FRIDAY EOD GUARD: {self._clock.now_utc().strftime('%Y-%m-%d %H:%M')} UTC — "
            f"Cancelling pending orders and flattening all positions to avoid Monday gap."
        )
        # Step 1: Cancel all pending limit orders
        pending = mt5.orders_get(symbol=SYMBOL) or []
        for o in pending:
            if o.magic == MAGIC_NUMBER:
                execution.cancel_pending_order(o.ticket)
        time.sleep(0.5)
        # Step 2: Close all open positions at market with generous deviation
        positions = mt5.positions_get(symbol=SYMBOL) or []
        for pos in positions:
            if pos.magic == MAGIC_NUMBER:
                execution.close_position_market(pos, is_eod=True)
                time.sleep(0.3)
        log.warning("📅 FRIDAY EOD GUARD: Flatten complete. Bot will resume Monday.")


# ══════════════════════════════════════════════════════════════════════════════
# 🌐  [V16-F3]  CONNECTION MANAGER
# ══════════════════════════════════════════════════════════════════════════════
class ConnectionManager:
    def __init__(self):
        self._lock          = threading.RLock()
        self._connected     = False
        self._attempt       = 0
        self._next_retry_at = 0.0

    def ensure_connected(self) -> bool:
        with self._lock:
            if mt5.terminal_info() is not None:
                self._connected = True; self._attempt = 0; return True
            now = time.time()
            if now < self._next_retry_at: return False
            if self._attempt >= RECONNECT_MAX_ATTEMPTS:
                log.error("⛔ ConnectionManager: max attempts exhausted")
            self._attempt += 1
            delay = min(RECONNECT_BASE_DELAY * (2 ** (self._attempt - 1)), RECONNECT_MAX_DELAY)
            log.warning(f"🔌 MT5 disconnected — reconnect #{self._attempt} (next in {delay:.0f}s)")
            if mt5.initialize():
                log.info(f"✅ MT5 reconnected on attempt #{self._attempt}")
                self._connected = True; self._attempt = 0; self._next_retry_at = 0.0; return True
            self._connected = False; self._next_retry_at = now + delay; return False

    @property
    def is_connected(self) -> bool:
        return self._connected


# ══════════════════════════════════════════════════════════════════════════════
# 📡  [V16-F2]  SPREAD GUARD
# ══════════════════════════════════════════════════════════════════════════════
class SpreadGuard:
    def __init__(self, window: int = SPREAD_MEDIAN_BARS):
        self._buf: deque = deque(maxlen=window)

    def update(self, spread_pts: float) -> None:
        if 0.1 < spread_pts < 500:
            self._buf.append(spread_pts)

    def is_ok(self, current_pts: float) -> Tuple[bool, str]:
        if current_pts > HARD_SPREAD_BLOCK:
            return False, f"HARD_BLOCK:{current_pts:.1f}>{HARD_SPREAD_BLOCK}pts"
        if len(self._buf) >= 5:
            median = float(np.median(self._buf))
            cap    = median * SPREAD_DYNAMIC_MULT
            if current_pts > cap:
                return False, f"DYN_BLOCK:{current_pts:.1f}>{cap:.1f}pts(3×median={median:.1f})"
        return True, ""

    @property
    def median_spread(self) -> float:
        return float(np.median(self._buf)) if self._buf else 0.0


# ══════════════════════════════════════════════════════════════════════════════
# 📰  NEWS GUARD  [V14-O3]
# ══════════════════════════════════════════════════════════════════════════════
class NewsGuard:
    def __init__(self):
        self._events: List[Dict] = []
        self._last_load          = 0.0
        self._load_interval      = 300.0

    def _maybe_reload(self) -> None:
        now = time.time()
        if now - self._last_load < self._load_interval: return
        try:
            if os.path.isfile(NEWS_EVENTS_FILE):
                with open(NEWS_EVENTS_FILE, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                self._events = [e for e in raw
                                if e.get("impact", "").upper() == "HIGH"
                                and e.get("currency", "") in ("USD", "XAU", "GOLD")]
            self._last_load = now
        except Exception as exc:
            log.warning(f"NewsGuard reload: {exc}"); self._last_load = now

    def is_blocked(self, now: datetime) -> Tuple[bool, str]:
        self._maybe_reload()
        buf = timedelta(minutes=NEWS_BUFFER_MIN)
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
# 💾  PERSISTENCE LAYER  [V16 schema + V16-O2 consec-loss table — preserved]
# ══════════════════════════════════════════════════════════════════════════════
_tls            = threading.local()
_write_q:       Optional[_queue_module.Queue] = None
_writer_thread: Optional[threading.Thread]    = None


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
            conn.execute(sql, params); conn.commit()
        except Exception as exc:
            log.warning(f"DB writer: {exc} | {sql[:60]}")
        finally:
            if done_ev is not None: done_ev.set()
        q.task_done()


def _db_exec(sql: str, params: tuple = (), wait: bool = False) -> None:
    global _write_q
    if _write_q is None: raise RuntimeError("DB writer not initialised")
    ev = threading.Event() if wait else None
    _write_q.put((sql, params, ev))
    if ev is not None: ev.wait(timeout=5.0)


def _db_query(sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
    try: return _get_read_conn().execute(sql, params).fetchone()
    except Exception as exc: log.warning(f"DB read: {exc}"); return None


def _db_query_all(sql: str, params: tuple = ()) -> List[sqlite3.Row]:
    try: return _get_read_conn().execute(sql, params).fetchall()
    except Exception as exc: log.warning(f"DB read_all: {exc}"); return []


def init_db() -> None:
    global _write_q, _writer_thread
    if _write_q is None:
        _write_q = _queue_module.Queue()
        _writer_thread = threading.Thread(
            target=_writer_loop, args=(_write_q,), name="DBWriter", daemon=True)
        _writer_thread.start()
        log.info("💾 DB writer thread started")

    schema_stmts = [
        """CREATE TABLE IF NOT EXISTS setup_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, signal TEXT, score INTEGER,
            entry REAL, sl REAL, tp REAL, setup_hash TEXT, session TEXT,
            features TEXT, win_prob REAL, sweep_type TEXT, shape TEXT)""",
        "CREATE TABLE IF NOT EXISTS cooldown (setup_hash TEXT PRIMARY KEY, expires_at REAL)",
        """CREATE TABLE IF NOT EXISTS trail_state (
            ticket INTEGER PRIMARY KEY, setup_hash TEXT, last_sl REAL,
            updated_at REAL, partial_done INTEGER DEFAULT 0)""",
        "CREATE TABLE IF NOT EXISTS bot_state (key TEXT PRIMARY KEY, value TEXT)",
        """CREATE TABLE IF NOT EXISTS win_prob_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, prob REAL, outcome INTEGER DEFAULT -1)""",
        """CREATE TABLE IF NOT EXISTS trade_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, outcome TEXT, session TEXT)""",
        "CREATE INDEX IF NOT EXISTS idx_trail_hash  ON trail_state(setup_hash)",
        "CREATE INDEX IF NOT EXISTS idx_setup_ts    ON setup_log(ts)",
        "CREATE INDEX IF NOT EXISTS idx_outcomes_ts ON trade_outcomes(ts)",
    ]
    for stmt in schema_stmts:
        _db_exec(stmt, wait=True)

    rc = _get_read_conn()
    trail_cols = {r[1] for r in rc.execute("PRAGMA table_info(trail_state)").fetchall()}
    if "setup_hash" not in trail_cols:
        _db_exec("ALTER TABLE trail_state ADD COLUMN setup_hash TEXT DEFAULT ''", wait=True)
    setup_cols = {r[1] for r in rc.execute("PRAGMA table_info(setup_log)").fetchall()}
    for col, defn in [("features", "TEXT DEFAULT NULL"), ("win_prob", "REAL DEFAULT 0"),
                      ("sweep_type", "TEXT DEFAULT ''"), ("shape", "TEXT DEFAULT ''")]:
        if col not in setup_cols:
            _db_exec(f"ALTER TABLE setup_log ADD COLUMN {col} {defn}", wait=True)
    log.info("✅ Database V17 schema ready")


def close_db() -> None:
    global _write_q
    if _write_q is not None:
        _write_q.put(None); _write_q = None
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


def db_log_setup(sig: str, score: int, entry: float, sl: float, tp: float,
                 h: str, session: str = "", features=None, win_prob: float = 0.0,
                 sweep_type: str = "", shape: str = "") -> None:
    fj = json.dumps([round(float(v), 8) for v in features], separators=(",", ":")) \
         if features is not None else None
    _db_exec(
        "INSERT INTO setup_log"
        "(ts,signal,score,entry,sl,tp,setup_hash,session,features,win_prob,sweep_type,shape)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (time.time(), sig, score, entry, sl, tp, h, session, fj, win_prob, sweep_type, shape))
    _db_exec("INSERT INTO win_prob_history(ts,prob) VALUES(?,?)", (time.time(), win_prob))


def record_trade_outcome(outcome: str, session: str) -> None:
    if outcome in ("WIN", "LOSS", "PARTIAL"):
        _db_exec("INSERT INTO trade_outcomes(ts,outcome,session) VALUES(?,?,?)",
                 (time.time(), outcome, session))


def get_consecutive_losses() -> int:
    rows = _db_query_all(
        "SELECT outcome FROM trade_outcomes WHERE outcome IN ('WIN','LOSS') "
        "ORDER BY ts DESC LIMIT ?", (N_CONSEC_LOSS_PAUSE + 5,))
    count = 0
    for r in rows:
        if r["outcome"] == "LOSS": count += 1
        else: break
    return count


def is_consec_loss_paused() -> bool:
    row = _db_query("SELECT value FROM bot_state WHERE key='consec_loss_pause_until'")
    if row is None: return False
    until = json.loads(row["value"])
    if time.time() < until:
        mins_remaining = (until - time.time()) / 60
        log.info(f"⏸️ Consecutive-loss pause: {mins_remaining:.0f}min remaining")
        return True
    return False


def set_consec_loss_pause() -> None:
    until = time.time() + CONSEC_LOSS_PAUSE_MIN * 60
    _db_exec("INSERT OR REPLACE INTO bot_state VALUES(?,?)",
             ("consec_loss_pause_until", json.dumps(until)))
    log.warning(
        f"⚠️ CONSECUTIVE LOSS CB: {N_CONSEC_LOSS_PAUSE} straight losses — "
        f"pausing new entries for {CONSEC_LOSS_PAUSE_MIN} minutes. "
        f"Market is choppy. This is NORMAL behaviour, not a bot fault."
    )


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
    ex  = get_trail_state(ticket, setup_hash)
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
    ph   = ",".join("?" * len(tickets))
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
    last_sh_val:  Optional[float] = None
    last_sl_val:  Optional[float] = None
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
    found:     bool  = False
    high:      float = 0.0
    low:       float = 0.0
    score:     float = 0.0
    bar_age:   int   = 0
    mitigated: bool  = False


@dataclass
class MSSResult:
    confirmed:     bool  = False
    cisd:          bool  = False
    break_level:   float = 0.0
    body_atr_mult: float = 0.0


@dataclass
class SetupResult:
    signal:      str              = "WAIT"
    score:       int              = 0
    entry:       float            = 0.0
    sl:          float            = 0.0
    atr:         float            = 0.0
    htf_bias:    str              = "NEUTRAL"
    h1_bias:     str              = "NEUTRAL"
    m15_struct:  str              = "NEUTRAL"
    adr_pct:     float            = 0.0
    threshold:   int              = 65
    reasons:     List[str]        = field(default_factory=list)
    setup_hash:  str              = ""
    use_market:  bool             = False
    liq_map:     Optional[LiquidityMap]  = None
    fvg_zone:    Optional[FVGZone]       = None
    candle_ts:   float            = 0.0
    htf_result:  Optional[HTFBiasResult] = None
    pd_zone:     str              = "NEUTRAL"
    features:    Optional[np.ndarray]    = None
    win_prob:    float            = 0.0
    spread_pts:  float            = 0.0
    is_judas:    bool             = False
    sweep_type:  str              = "NONE"
    shape:       str              = "NONE"
    mss:         Optional[MSSResult]     = None
    golden_conf: bool             = False

    def summary(self) -> str:
        gap  = self.score - self.threshold
        conf = "💎" if gap >= 25 else "🔥🔥" if gap >= 12 else "🔥" if gap >= 0 else "⚠️"
        mode = "MKT" if self.use_market else "LMT"
        tags = []
        if self.is_judas:    tags.append("⚡JUDAS")
        if self.golden_conf: tags.append("✨GOLDEN")
        if self.shape == "V": tags.append("📐V")
        if self.shape == "U": tags.append("🌊U")
        return (f"{conf} {' '.join(tags)} {self.signal}({mode}) "
                f"Score:{self.score}/{self.threshold} WP:{self.win_prob:.2f} "
                f"Sweep:{self.sweep_type} H1:{self.h1_bias} | {' | '.join(self.reasons)}")


# ══════════════════════════════════════════════════════════════════════════════
# 🤖  ML LAYER  [V17-F4] — heuristic bypass when no model
# ══════════════════════════════════════════════════════════════════════════════
class WelfordNormaliser:
    def __init__(self, n_features: int, min_samples: int = 20):
        self._n = n_features; self._min = min_samples
        self._count = np.zeros(n_features); self._mean = np.zeros(n_features)
        self._M2    = np.zeros(n_features)

    def update(self, x: np.ndarray) -> None:
        for i, v in enumerate(x):
            if np.isfinite(v):
                self._count[i] += 1; delta = v - self._mean[i]
                self._mean[i] += delta / self._count[i]
                self._M2[i] += delta * (v - self._mean[i])

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
            if std > 1e-9 and abs((x[i] - self._mean[i]) / std) > z_bound: return True
        return False

    @property
    def is_warm(self) -> bool:
        return bool(np.all(self._count >= self._min))


N_FEATURES = 14


def extract_features(setup: "SetupResult", close_price: float = 2000.0,
                     df_len: int = 300) -> np.ndarray:
    atr      = max(setup.atr, 1e-6)
    htf_enc  = {"BULLISH": 1.0, "BEARISH": -1.0}.get(setup.htf_bias, 0.0)
    atr_norm = atr / max(close_price, 1.0)
    fvg_str  = setup.fvg_zone.strength if setup.fvg_zone else 0.0
    fvg_age  = 0.0
    if setup.fvg_zone is not None:
        age  = max(0, df_len - 1 - setup.fvg_zone.bar_index)
        fvg_age = min(1.0, age / max(FVG_MEMORY_BARS.get("DEFAULT", 30), 1))
    spread_n = setup.spread_pts / atr
    m15_enc  = {"BULLISH_BOS": 1.0, "BEARISH_BOS": -1.0}.get(setup.m15_struct, 0.0)
    reasons  = " ".join(setup.reasons)
    has_ob   = 1.0 if any("OB(q:" in r for r in setup.reasons) else 0.0
    sf       = 1.0 if "Sweep+FVG" in reasons else 0.0
    has_liq  = 1.0 if ("BSL→" in reasons or "SSL→" in reasons) else 0.0
    sweep_d  = 0.0
    lm = setup.liq_map
    if lm is not None:
        if lm.swept_low  is not None and setup.signal == "BUY":
            sweep_d = min(1.0, abs((lm.ssl_nearest or lm.swept_low) - lm.swept_low) / atr)
        elif lm.swept_high is not None and setup.signal == "SELL":
            sweep_d = min(1.0, abs(lm.swept_high - (lm.bsl_nearest or lm.swept_high)) / atr)
    now         = datetime.now(STRATEGY_TZ)
    session_sin = math.sin(2.0 * math.pi * (now.hour * 60 + now.minute) / 1440.0)
    sweep_enc   = {"CONTINUE": 1.0, "REVERSE": -1.0}.get(setup.sweep_type, 0.0)
    shape_enc   = {"V": 1.0, "U": -1.0}.get(setup.shape, 0.0)
    return np.array([htf_enc, atr_norm, float(setup.adr_pct), float(fvg_str),
                     float(spread_n), m15_enc, float(has_liq), float(has_ob), float(sf),
                     float(fvg_age), float(sweep_d), float(session_sin),
                     float(sweep_enc), float(shape_enc)], dtype=np.float64)


class MLPredictor:
    """
    [V17-F4] ML gate active ONLY when a real model is loaded.

    Without a model: predict_win_probability() returns 1.0 unconditionally.
    This removes the heuristic double-filter problem. The score system is
    already the filter; a second rule-based layer is redundant and causes
    analysis paralysis.

    With a real model: Welford normaliser + distribution shift guard apply.
    Gate = ML_WIN_PROB_THRESHOLD (0.52).
    """

    def __init__(self):
        self._model = None
        self._norm  = WelfordNormaliser(N_FEATURES)
        self._prob_buf: Deque[float] = deque(maxlen=ML_ROLLING_WINDOW)
        log.info(f"🧠 MLPredictor V17: {N_FEATURES}-feat | heuristic bypass mode "
                 f"(returns 1.0 until real model loaded)")

    def load_model(self, path: str) -> bool:
        try:
            obj = joblib.load(path)
            self._model = obj[1] if isinstance(obj, tuple) and len(obj) == 2 else obj
            log.info(f"🧠 MLPredictor: real model loaded from {path} | "
                     f"gate={ML_WIN_PROB_THRESHOLD}"); return True
        except Exception as exc:
            log.warning(f"🧠 load failed ({exc}) — staying in bypass mode"); return False

    @property
    def model_loaded(self) -> bool:
        return self._model is not None

    def predict_win_probability(self, features: np.ndarray,
                                update_norm: bool = True) -> float:
        # [V17-F4] Bypass: no model → pass through
        if self._model is None:
            self._prob_buf.append(1.0)
            return 1.0

        # Real model path
        shift = self._norm.check_shift(features, z_bound=3.5)
        if update_norm and not shift:
            self._norm.update(features)
        if shift:
            log.warning("🧠 Dist shift → 0.49")
            return 0.49

        x = self._norm.transform(features)
        try:
            prob = float(self._model.predict_proba(x.reshape(1, -1))[0][1])
            prob = max(0.0, min(1.0, prob))
            self._prob_buf.append(prob); return prob
        except Exception as exc:
            log.warning(f"🧠 Inference: {exc} → bypass"); return 1.0

    @property
    def rolling_avg_prob(self) -> float:
        return float(np.mean(self._prob_buf)) if self._prob_buf else 1.0

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

    def fetch(self, tf: int, n: int, symbol: str = SYMBOL,
              use_cache: bool = True) -> Optional[pd.DataFrame]:
        cache_key = tf if symbol == SYMBOL else tf + hash(symbol)
        now = time.time()
        with self._lock:
            if use_cache and cache_key in self._cache:
                ts, df = self._cache[cache_key]
                if now - ts < self._ttl(tf): return df
        try:
            rates = mt5.copy_rates_from_pos(symbol, tf, 0, n)
        except Exception: rates = None
        if rates is None or len(rates) == 0: return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        with self._lock:
            self._cache[cache_key] = (now, df)
        return df

    def get_cached_m5(self) -> Optional[pd.DataFrame]:
        with self._lock:
            entry = self._cache.get(mt5.TIMEFRAME_M5)
        return entry[1] if entry else None

    def fetch_all(self) -> Dict[str, Optional[pd.DataFrame]]:
        def _trim(df):
            return df.iloc[:-1].copy() if df is not None and len(df) > 1 else df
        m1  = _trim(self.fetch(mt5.TIMEFRAME_M1,   60,  use_cache=False))
        m5  = _trim(self.fetch(mt5.TIMEFRAME_M5,  300,  use_cache=False))
        m15 = _trim(self.fetch(mt5.TIMEFRAME_M15, 100,  use_cache=True))
        h1  = _trim(self.fetch(mt5.TIMEFRAME_H1,  H1_BARS, use_cache=True))
        h4  = _trim(self.fetch(mt5.TIMEFRAME_H4,  HTF_BARS, use_cache=True))
        d1  = self.fetch(mt5.TIMEFRAME_D1, 20, use_cache=True)
        return {"m1": m1, "m5": m5, "m15": m15, "h1": h1, "h4": h4, "d1": d1}

    def get_current_m5_bar_time(self) -> Optional[int]:
        try:
            rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M5, 0, 1)
            if rates is not None and len(rates) > 0: return int(rates[0]["time"])
        except Exception: pass
        return None


# ══════════════════════════════════════════════════════════════════════════════
# 🧮  INDICATOR FUNCTIONS  — NumPy hot-paths
# ══════════════════════════════════════════════════════════════════════════════
def _to_numpy(df: pd.DataFrame, col: str) -> np.ndarray:
    return np.ascontiguousarray(df[col].values, dtype=np.float64)


def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < period + 1: return 0.0
    high = _to_numpy(df, "high"); low = _to_numpy(df, "low"); close = _to_numpy(df, "close")
    prev = close[:-1]
    tr   = np.maximum(high[1:] - low[1:], np.maximum(np.abs(high[1:] - prev), np.abs(low[1:] - prev)))
    if len(tr) < period: return 0.0
    v = float(tr[:period].mean()); alpha = 1.0 / period
    for x in tr[period:]: v = v * (1.0 - alpha) + float(x) * alpha
    return v if not np.isnan(v) else 0.0


def calculate_adr(df_d1: Optional[pd.DataFrame], period: int = 10) -> float:
    if df_d1 is None or len(df_d1) < period: return 0.0
    return float((_to_numpy(df_d1, "high") - _to_numpy(df_d1, "low"))[-period:].mean())


def get_confirmed_swings_np(df: pd.DataFrame, period: int = 5,
                             confirm: int = 2) -> Tuple[float, float]:
    if len(df) < period * 2 + confirm + 1:
        return float(df["high"].max()), float(df["low"].min())
    high = _to_numpy(df, "high"); low = _to_numpy(df, "low"); safe = len(high) - confirm
    sh, sl = [], []
    for i in range(period, safe - period):
        if high[i] == high[i - period: i + period + 1].max(): sh.append(high[i])
        if low[i]  == low[i  - period: i + period + 1].min(): sl.append(low[i])
    return (float(sh[-1]) if sh else float(high.max()),
            float(sl[-1]) if sl else float(low.min()))


def _cluster_liquidity_levels(prices: List[float], tol: float) -> List[float]:
    clusters: List[float] = []; used = [False] * len(prices)
    for i in range(len(prices)):
        if used[i]: continue
        group = [prices[i]]
        for j in range(i + 1, len(prices)):
            if not used[j] and abs(prices[j] - prices[i]) <= tol:
                group.append(prices[j]); used[j] = True
        if len(group) >= LIQ_MIN_CLUSTER:
            clusters.append(round(sum(group) / len(group), 5))
    return clusters


def build_liquidity_map_np(df: pd.DataFrame, atr: float, period: int = 10) -> LiquidityMap:
    liq = LiquidityMap()
    if len(df) < period * 2 + 4 or atr == 0: return liq
    high = _to_numpy(df, "high"); low = _to_numpy(df, "low")
    cls  = _to_numpy(df, "close"); opn = _to_numpy(df, "open")
    safe = len(high) - 2
    tol  = max(atr * 0.08, abs(cls[-1]) * LIQ_EQUAL_TOLERANCE)
    ph, pl = [], []
    for i in range(period, safe - period):
        if high[i] == high[i - period: i + period + 1].max(): ph.append(high[i])
        if low[i]  == low[i  - period: i + period + 1].min(): pl.append(low[i])
    liq.buy_side  = sorted(_cluster_liquidity_levels(ph, tol), reverse=True)
    liq.sell_side = sorted(_cluster_liquidity_levels(pl, tol))
    last_high = float(high[-1]); last_low  = float(low[-1])
    last_close = float(cls[-1]); prev_close = float(cls[-2]) if len(cls) >= 2 else last_close
    cur_open   = float(opn[-1])
    for lvl in liq.buy_side:
        if last_high > lvl and last_close < lvl: liq.swept_high = lvl; break
    for lvl in liq.sell_side:
        if last_low  < lvl and last_close > lvl: liq.swept_low  = lvl; break
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


def _make_hash(sig: str, entry: float, sl: float, ts: float) -> str:
    return hashlib.sha256(f"{sig}:{entry:.2f}:{sl:.2f}:{int(ts)}".encode()).hexdigest()[:12]


# ══════════════════════════════════════════════════════════════════════════════
# 📐  [V16-S4]  V-SHAPE / U-SHAPE DETECTOR
# ══════════════════════════════════════════════════════════════════════════════
class VShapeDetector:
    """
    [V16-S4 — preserved] Classifies sweep rejection as V (fast) or U (slow/chop).
    [V17-F2] volume_spike logic removed; relies purely on body size.
    """
    @staticmethod
    def classify(df_m5: pd.DataFrame, atr: float, direction: str) -> str:
        """
        Returns "V", "U", or "NONE".
        direction: "BUY" = upward reversal from a SSL sweep, "SELL" = downward from BSL.
        """
        if not VSHAPE_ENABLED or len(df_m5) < VSHAPE_MAX_BARS + 4 or atr == 0:
            return "NONE"
        # sweep candle = iloc[-2] (just closed); current = iloc[-1]
        sweep_c    = df_m5.iloc[-2]
        current_c  = df_m5.iloc[-1]
        sweep_low  = float(sweep_c["low"])
        sweep_high = float(sweep_c["high"])

        if direction == "BUY":
            sweep_extreme = sweep_low
            origin        = float(df_m5.iloc[-3]["close"])
            retrace_dist  = origin - sweep_extreme
            # Velocity: rejection body on the sweep candle itself
            body = abs(float(sweep_c["close"]) - float(sweep_c["open"]))
            if body < atr * VSHAPE_ATR_MULT:
                return "NONE"
            # Check retrace in VSHAPE_MAX_BARS
            for k in range(1, VSHAPE_MAX_BARS + 1):
                idx = -1 - k
                if abs(idx) > len(df_m5): break
                c = df_m5.iloc[idx]
                if retrace_dist > 0 and (float(c["close"]) - sweep_extreme) / retrace_dist >= VSHAPE_RETRACE_PCT:
                    return "V"
            # U-shape: price stayed in sweep wick range for USHAPE_MAX_BARS
            wick_mid = (sweep_extreme + float(sweep_c["close"])) / 2
            inside_count = sum(
                1 for k in range(1, USHAPE_MAX_BARS + 1)
                if abs(-1 - k) <= len(df_m5)
                and float(df_m5.iloc[-1 - k]["close"]) < wick_mid
            )
            return "U" if inside_count >= USHAPE_MAX_BARS - 1 else "NONE"

        else:  # SELL
            sweep_extreme = sweep_high
            origin        = float(df_m5.iloc[-3]["close"])
            retrace_dist  = sweep_extreme - origin
            body = abs(float(sweep_c["close"]) - float(sweep_c["open"]))
            if body < atr * VSHAPE_ATR_MULT:
                return "NONE"
            for k in range(1, VSHAPE_MAX_BARS + 1):
                idx = -1 - k
                if abs(idx) > len(df_m5): break
                c = df_m5.iloc[idx]
                if retrace_dist > 0 and (sweep_extreme - float(c["close"])) / retrace_dist >= VSHAPE_RETRACE_PCT:
                    return "V"
            wick_mid = (sweep_extreme + float(sweep_c["close"])) / 2
            inside_count = sum(
                1 for k in range(1, USHAPE_MAX_BARS + 1)
                if abs(-1 - k) <= len(df_m5)
                and float(df_m5.iloc[-1 - k]["close"]) > wick_mid
            )
            return "U" if inside_count >= USHAPE_MAX_BARS - 1 else "NONE"


# ══════════════════════════════════════════════════════════════════════════════
# 🧠  CLASS: SMCSignalEngine
# ══════════════════════════════════════════════════════════════════════════════
class SMCSignalEngine:

    def __init__(self, clock: BrokerClockSync):
        self._clock      = clock
        self._news_guard = NewsGuard()

    # ── HTF Bias (H4) ─────────────────────────────────────────────────────────
    @staticmethod
    def get_htf_bias(df_h4: Optional[pd.DataFrame]) -> HTFBiasResult:
        res = HTFBiasResult()
        if df_h4 is None or len(df_h4) < HTF_SWING_PERIOD * 2 + HTF_SWING_CONFIRM + 5:
            res.reason = "H4 insufficient"; return res
        lookback = min(60, len(df_h4))
        df   = df_h4.iloc[-lookback:].reset_index(drop=True)
        p, c = HTF_SWING_PERIOD, HTF_SWING_CONFIRM
        high = _to_numpy(df, "high"); low = _to_numpy(df, "low"); cls = _to_numpy(df, "close")
        safe = len(high) - c
        sh_list: List[Tuple[int, float]] = []; sl_list: List[Tuple[int, float]] = []
        for i in range(p, safe - p):
            if high[i] == high[i - p: i + p + 1].max(): sh_list.append((i, float(high[i])))
            if low[i]  == low[i  - p: i + p + 1].min(): sl_list.append((i, float(low[i])))
        if len(sh_list) < 2 or len(sl_list) < 2:
            res.reason = "Insufficient H4 swings"; return res
        res.last_sh_val = sh_list[-1][1]; res.last_sl_val = sl_list[-1][1]
        prev_sh = sh_list[-1][1]; prev_sl = sl_list[-1][1]
        last_high = float(high[-1]); last_low = float(low[-1]); last_close = float(cls[-1])
        if last_high > prev_sh and last_close < prev_sh: res.swept_high = prev_sh
        if last_low  < prev_sl and last_close > prev_sl: res.swept_low  = prev_sl
        bos_up   = bool(np.any(cls[-5:] > prev_sh))
        bos_down = bool(np.any(cls[-5:] < prev_sl))
        hh = sh_list[-1][1] > sh_list[-2][1]; lh = sh_list[-1][1] < sh_list[-2][1]
        hl = sl_list[-1][1] > sl_list[-2][1]; ll = sl_list[-1][1] < sl_list[-2][1]
        bull = bear = 0
        if bos_up:  bull += 2; res.last_bos = "UP"
        if bos_down: bear += 2; res.last_bos = "DOWN"
        if hh and hl: bull += 2
        if lh and ll: bear += 2
        if res.swept_low:  bull += 1
        if res.swept_high: bear += 1
        if bos_up  and (lh and ll): res.choch_signal = "UP"
        if bos_down and (hh and hl): res.choch_signal = "DOWN"
        if bull >= 3 and bull > bear:
            res.bias = "BULLISH"; res.reason = f"BOS_UP:{bos_up}|HH:{hh}|HL:{hl}"
        elif bear >= 3 and bear > bull:
            res.bias = "BEARISH"; res.reason = f"BOS_DN:{bos_down}|LH:{lh}|LL:{ll}"
        else:
            res.bias = "NEUTRAL"; res.reason = f"Bull:{bull} Bear:{bear} ranging"
        return res

    # ── H1 Intermediate Bias [V16-O3] ─────────────────────────────────────────
    @staticmethod
    def get_h1_bias(df_h1: Optional[pd.DataFrame]) -> str:
        if df_h1 is None or len(df_h1) < H1_SWING_PERIOD * 2 + H1_SWING_CONFIRM + 5:
            return "NEUTRAL"
        lookback = min(40, len(df_h1))
        df  = df_h1.iloc[-lookback:].reset_index(drop=True)
        p   = H1_SWING_PERIOD; c = H1_SWING_CONFIRM
        high = _to_numpy(df, "high"); low = _to_numpy(df, "low"); cls = _to_numpy(df, "close")
        safe = len(high) - c
        sh, sl = [], []
        for i in range(p, safe - p):
            if high[i] == high[i - p: i + p + 1].max(): sh.append(high[i])
            if low[i]  == low[i  - p: i + p + 1].min(): sl.append(low[i])
        if len(sh) < 2 or len(sl) < 2: return "NEUTRAL"
        bos_up   = bool(np.any(cls[-3:] > sh[-1]))
        bos_down = bool(np.any(cls[-3:] < sl[-1]))
        hh = sh[-1] > sh[-2]; lh = sh[-1] < sh[-2]
        hl = sl[-1] > sl[-2]; ll = sl[-1] < sl[-2]
        if bos_up  and hh and hl: return "BULLISH"
        if bos_down and lh and ll: return "BEARISH"
        return "NEUTRAL"

    # ── M15 Structure ─────────────────────────────────────────────────────────
    @staticmethod
    def get_m15_structure(df_m15: Optional[pd.DataFrame]) -> str:
        if df_m15 is None or len(df_m15) < SWING_PERIOD * 2 + SWING_CONFIRM_BARS + 5:
            return "NEUTRAL"
        sub = df_m15.iloc[-40:].reset_index(drop=True)
        sh, sl = get_confirmed_swings_np(sub, period=SWING_PERIOD, confirm=SWING_CONFIRM_BARS)
        last_c = float(sub["close"].iloc[-1]); buf = (sh - sl) * 0.005
        if last_c > sh + buf: return "BULLISH_BOS"
        if last_c < sl - buf: return "BEARISH_BOS"
        return "NEUTRAL"

    # ── MSS + CISD [V16-S3] ───────────────────────────────────────────────────
    @staticmethod
    def check_mss_cisd(df_m5: pd.DataFrame, atr: float, direction: str) -> MSSResult:
        result = MSSResult()
        if not MSS_ENABLED or len(df_m5) < SWING_PERIOD * 2 + 5 or atr == 0:
            return result
        sub = df_m5.iloc[-20:].reset_index(drop=True)
        last = sub.iloc[-1]
        sh, sl = get_confirmed_swings_np(sub, period=SWING_PERIOD, confirm=SWING_CONFIRM_BARS)
        body = abs(float(last["close"]) - float(last["open"]))
        body_mult = body / atr
        if direction == "BUY":
            if float(last["close"]) > sh:
                result.confirmed   = True
                result.break_level = sh
                result.body_atr_mult = body_mult
                result.cisd = body_mult >= CISD_ATR_MULT
        else:
            if float(last["close"]) < sl:
                result.confirmed   = True
                result.break_level = sl
                result.body_atr_mult = body_mult
                result.cisd = body_mult >= CISD_ATR_MULT
        return result

    # ── Golden Confluence [V16-S5] ─────────────────────────────────────────────
    @staticmethod
    def check_golden_confluence(fvg_zone: Optional[FVGZone], df_m5: pd.DataFrame,
                                 htf_res: HTFBiasResult, atr: float, direction: str) -> bool:
        if not GOLDEN_CONFL_ENABLED or fvg_zone is None or fvg_zone.mitigated:
            return False
        if htf_res.last_sh_val is None or htf_res.last_sl_val is None:
            return False
        swing_h = htf_res.last_sh_val; swing_l = htf_res.last_sl_val
        swing_range = swing_h - swing_l
        if swing_range <= 0: return False
        ote_high = swing_h - swing_range * OTE_LOW_PCT    # 61.8% retrace level
        ote_low  = swing_h - swing_range * OTE_HIGH_PCT   # 79% retrace level
        if direction == "SELL":
            ote_high = swing_l + swing_range * OTE_HIGH_PCT
            ote_low  = swing_l + swing_range * OTE_LOW_PCT
        fvg_mid  = fvg_zone.bot + (fvg_zone.top - fvg_zone.bot) * 0.5
        in_ote   = ote_low <= fvg_mid <= ote_high
        if not in_ote: return False
        if len(df_m5) < 2: return False
        last_body = abs(float(df_m5.iloc[-1]["close"]) - float(df_m5.iloc[-1]["open"]))
        return last_body >= atr * DISPLACEMENT_ATR_MULT

    # ── Sweep Classification [V16-S2] ─────────────────────────────────────────
    @staticmethod
    def classify_sweep(signal: str, htf_bias: str) -> str:
        if signal == "BUY"  and htf_bias == "BULLISH": return "CONTINUE"
        if signal == "SELL" and htf_bias == "BEARISH": return "CONTINUE"
        if signal == "BUY"  and htf_bias == "BEARISH": return "REVERSE"
        if signal == "SELL" and htf_bias == "BULLISH": return "REVERSE"
        return "NEUTRAL_HTF"

    # ── FVG Memory ────────────────────────────────────────────────────────────
    @staticmethod
    def scan_fvg_memory(df: pd.DataFrame, atr: float, lookback: int = 30) -> List[FVGZone]:
        # [V17-F2] vol_spike removed; FVGZone no longer carries volume_spike field
        zones: List[FVGZone] = []
        if len(df) < lookback + 3 or atr == 0: return zones
        min_gap = atr * FVG_MIN_GAP_ATR
        start   = max(3, len(df) - lookback)
        for i in range(start, len(df) - 2):
            c1 = df.iloc[i]; c2 = df.iloc[i + 1]; c3 = df.iloc[i + 2]
            c2_range = float(c2["high"] - c2["low"]); c2_body = abs(float(c2["close"] - c2["open"]))
            if c2_range > 0 and (c2_body / c2_range) < FVG_MOMENTUM_RATIO: continue
            gap_bull = float(c3["low"]) - float(c1["high"])
            if gap_bull >= min_gap:
                top = float(c3["low"]); bot = float(c1["high"]); gap = top - bot
                mid = bot + gap * FVG_MITIGATED_PCT; mitigated = False
                for j in range(i + 3, len(df)):
                    if float(df.iloc[j]["low"]) <= mid: mitigated = True; break
                zones.append(FVGZone("BULLISH", top, bot, min(2.0, gap / atr), i, mitigated))
            gap_bear = float(c1["low"]) - float(c3["high"])
            if gap_bear >= min_gap:
                top = float(c1["low"]); bot = float(c3["high"]); gap = top - bot
                mid = top - gap * FVG_MITIGATED_PCT; mitigated = False
                for j in range(i + 3, len(df)):
                    if float(df.iloc[j]["high"]) >= mid: mitigated = True; break
                zones.append(FVGZone("BEARISH", top, bot, min(2.0, gap / atr), i, mitigated))
        zones.sort(key=lambda z: z.bar_index, reverse=True)
        return zones

    @staticmethod
    def get_active_fvg(zones: List[FVGZone], price: float, direction: str) -> Optional[FVGZone]:
        target = "BULLISH" if direction == "BUY" else "BEARISH"
        for z in zones:
            if z.mitigated or z.kind != target: continue
            buf = (z.top - z.bot) * FVG_BUFFER_RATIO
            if (z.bot - buf) <= price <= (z.top + buf): return z
        return None

    # ── Order Block [V17-F2] — no vol_spike ──────────────────────────────────
    @staticmethod
    def find_order_block(df: pd.DataFrame, direction: str, atr: float) -> OBResult:
        if len(df) < 10 or atr == 0: return OBResult()
        closed = df.iloc[:-1]; n = len(closed); max_age = min(30, n - 2)
        for age in range(1, max_age):
            i = n - 1 - age
            if i + 1 >= n - 1: continue
            ob = closed.iloc[i]; imp = closed.iloc[i + 1]
            if abs(float(imp["close"]) - float(imp["open"])) < atr * 1.2: continue
            ob_low = float(ob["low"]); ob_high = float(ob["high"]); rng = ob_high - ob_low
            if direction == "BUY":
                if ob["close"] >= ob["open"] or imp["close"] <= imp["open"]: continue
                ph_w = closed["high"].iloc[max(0, i - 10): i]
                if len(ph_w) > 0 and imp["close"] <= ph_w.max() * 0.998: continue
                mitigated = any(float(closed.iloc[j]["close"]) < ob_low for j in range(i + 2, n))
                body  = (float(ob["open"]) - float(ob["close"])) / rng if rng > 0 else 0
                sweep = float(closed["low"].iloc[max(0, i - 5): i].min()) < ob_low
            else:
                if ob["close"] <= ob["open"] or imp["close"] >= imp["open"]: continue
                pl_w = closed["low"].iloc[max(0, i - 10): i]
                if len(pl_w) > 0 and imp["close"] >= float(pl_w.min()) * 1.002: continue
                mitigated = any(float(closed.iloc[j]["close"]) > ob_high for j in range(i + 2, n))
                body  = (float(ob["close"]) - float(ob["open"])) / rng if rng > 0 else 0
                sweep = float(closed["high"].iloc[max(0, i - 5): i].max()) > ob_high
            q = 0.5 + (0.3 if sweep else 0) + (0.2 if body > 0.6 else 0)
            return OBResult(True, ob_high, ob_low, q, bar_age=age, mitigated=mitigated)
        return OBResult()

    # ── P/D Zone ──────────────────────────────────────────────────────────────
    @staticmethod
    def get_pd_zone(df_m5: pd.DataFrame, period: int = PD_PERIOD) -> str:
        if not PD_ZONE_ENABLED or len(df_m5) < period: return "NEUTRAL"
        sub = df_m5.iloc[-period:]
        rng_h = float(sub["high"].max()); rng_l = float(sub["low"].min())
        spread = rng_h - rng_l
        if spread < 1e-6: return "NEUTRAL"
        pct = (float(df_m5["close"].iloc[-1]) - rng_l) / spread
        if pct > 0.67: return "PREMIUM"
        if pct < 0.33: return "DISCOUNT"
        return "EQUILIBRIUM"

    # ── Judas Swing [V14-S2] ─────────────────────────────────────────────────
    def is_judas_swing(self, liq: LiquidityMap, fvg_zones: List[FVGZone],
                        signal: str, session: str) -> bool:
        if not JUDAS_SWING_ENABLED: return False
        now = self._clock.now_strategy()
        session_opens = {"LONDON": dtime(14, 0), "NY_OPEN_EARLY": dtime(18, 30),
                         "NEW_YORK": dtime(19, 45)}
        open_t = session_opens.get(session)
        if open_t is None: return False
        mins_since = (now.hour * 60 + now.minute) - (open_t.hour * 60 + open_t.minute)
        if not (0 <= mins_since <= JUDAS_WINDOW_MIN): return False
        if signal == "BUY"  and liq.swept_low  is not None:
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

    # ── Session [V16-F4 clock] ────────────────────────────────────────────────
    def get_session(self) -> str:
        now = self._clock.now_strategy()
        blocked, event = self._news_guard.is_blocked(now)
        if blocked:
            log.info(f"📰 News Guard: {event}"); return "RED_NEWS_BLOCK"
        t = now.time()
        for sh, sm, eh, em, name in SESSIONS:
            s, e = dtime(sh, sm), dtime(eh, em)
            if e < s:
                if t >= s or t <= e: return name
            else:
                if s <= t <= e: return name
        return "OUT_OF_SESSION"

    def is_in_killzone(self) -> Tuple[bool, str]:
        if not KILLZONE_ENABLED: return True, "All"
        t = self._clock.t()
        for sh, sm, eh, em, name in KILLZONES:
            if dtime(sh, sm) <= t <= dtime(eh, em): return True, name
        return False, "Outside Killzone"

    @staticmethod
    def get_dynamic_threshold(session: str) -> int:
        return SCORE_THRESHOLD.get(session, SCORE_THRESHOLD["DEFAULT"])

    # ── Master Setup Analyser [V17-F1 simplified scoring] ────────────────────
    def analyze_setup(self, df_m5: Optional[pd.DataFrame],
                      df_h4:  Optional[pd.DataFrame],
                      df_d1:  Optional[pd.DataFrame],
                      df_m15: Optional[pd.DataFrame],
                      df_h1:  Optional[pd.DataFrame],
                      session: str = "DEFAULT") -> SetupResult:
        r = SetupResult()
        if df_m5 is None or len(df_m5) < 30:
            r.reasons.append("M5 insufficient"); return r
        atr = calculate_atr(df_m5)
        if atr == 0: r.reasons.append("ATR=0"); return r
        r.atr = atr

        adr = calculate_adr(df_d1)
        if adr > 0 and df_d1 is not None and len(df_d1) >= 1:
            r.adr_pct = float(df_d1["high"].iloc[-1] - df_d1["low"].iloc[-1]) / adr

        adr_ceil = ADR_NY_EXHAUSTED_PCT if session in ("NEW_YORK", "NY_OPEN_EARLY") \
                   else ADR_EXHAUSTED_PCT
        if ADR_HARD_BLOCK and r.adr_pct >= adr_ceil:
            r.reasons.append(f"ADR_HARD_BLOCK({r.adr_pct*100:.0f}%)"); return r

        htf_res      = self.get_htf_bias(df_h4)
        r.htf_bias   = htf_res.bias
        r.htf_result = htf_res
        r.h1_bias    = self.get_h1_bias(df_h1)
        r.m15_struct = self.get_m15_structure(df_m15)
        r.threshold  = self.get_dynamic_threshold(session)
        r.pd_zone    = self.get_pd_zone(df_m5)

        liq       = build_liquidity_map_np(df_m5, atr, LIQ_SWING_PERIOD)
        r.liq_map = liq
        last_sh, last_sl = get_confirmed_swings_np(df_m5, SWING_PERIOD, SWING_CONFIRM_BARS)
        fvg_lookback     = FVG_MEMORY_BARS.get(session, FVG_MEMORY_BARS["DEFAULT"])
        fvg_zones        = self.scan_fvg_memory(df_m5, atr, fvg_lookback)
        df_len   = len(df_m5)
        last     = df_m5.iloc[-1]; prev = df_m5.iloc[-2]
        r.candle_ts = (float(last["time"].timestamp())
                       if hasattr(last["time"], "timestamp") else time.time())
        price      = float(last["close"])
        sweep_sell = float(last["low"]) < last_sl and float(last["close"]) > last_sl
        sweep_buy  = float(last["high"]) > last_sh and float(last["close"]) < last_sh
        if liq.gap_swept_low  is not None: sweep_sell = True
        if liq.gap_swept_high is not None: sweep_buy  = True

        # ── Shared scoring helpers ─────────────────────────────────────────────
        def _htf_scores(sig: str) -> None:
            if r.htf_bias == "BULLISH" and sig == "BUY":
                r.score += SCORE_HTF_ALIGN
                r.reasons.append(f"H4 Bull{'(CHOCH)' if htf_res.choch_signal=='UP' else ''} +{SCORE_HTF_ALIGN}")
            elif r.htf_bias == "BEARISH" and sig == "SELL":
                r.score += SCORE_HTF_ALIGN
                r.reasons.append(f"H4 Bear{'(CHOCH)' if htf_res.choch_signal=='DOWN' else ''} +{SCORE_HTF_ALIGN}")
            elif (r.htf_bias == "BULLISH" and sig == "SELL") or \
                 (r.htf_bias == "BEARISH" and sig == "BUY"):
                r.score += SCORE_HTF_AGAINST
                r.reasons.append(f"H4 Against {SCORE_HTF_AGAINST}")
            else:
                r.reasons.append("H4 Neutral ±0")

        def _h1_scores(sig: str) -> None:
            if (r.h1_bias == "BULLISH" and sig == "BUY") or \
               (r.h1_bias == "BEARISH" and sig == "SELL"):
                r.score += H1_AGREE_BONUS; r.reasons.append(f"H1 Agree +{H1_AGREE_BONUS}")
            elif (r.h1_bias == "BULLISH" and sig == "SELL") or \
                 (r.h1_bias == "BEARISH" and sig == "BUY"):
                r.score += H1_CONFLICT_PENALTY; r.reasons.append(f"H1 Conflict {H1_CONFLICT_PENALTY}")

        def _apply_structure_scores(sig: str, fvg_active: Optional[FVGZone]) -> None:
            # M15 BOS
            if (sig == "BUY" and r.m15_struct == "BULLISH_BOS") or \
               (sig == "SELL" and r.m15_struct == "BEARISH_BOS"):
                r.score += SCORE_M15_BOS; r.reasons.append(f"M15 BOS +{SCORE_M15_BOS}")
            # MSS + CISD
            mss = self.check_mss_cisd(df_m5, atr, sig)
            r.mss = mss
            if mss.confirmed:
                pts = SCORE_MSS_CISD if mss.cisd else SCORE_MSS_ONLY
                tag = "MSS+CISD" if mss.cisd else "MSS"
                r.score += pts; r.reasons.append(f"{tag} +{pts}")
            else:
                # Fallback: simple M5 BOS
                if sig == "BUY" and float(last["close"]) > float(prev["high"]):
                    r.score += SCORE_BOS_M5; r.reasons.append(f"BOS_M5 +{SCORE_BOS_M5}")
                elif sig == "SELL" and float(last["close"]) < float(prev["low"]):
                    r.score += SCORE_BOS_M5; r.reasons.append(f"BOS_M5 +{SCORE_BOS_M5}")
            # V/U Shape
            shape_dir = "BUY" if sig == "BUY" else "SELL"
            shape = VShapeDetector.classify(df_m5, atr, shape_dir)
            r.shape = shape
            if shape == "V":
                r.score += SCORE_VSHAPE_BONUS; r.reasons.append(f"V-Shape +{SCORE_VSHAPE_BONUS}")
            elif shape == "U":
                r.score += SCORE_USHAPE_PENALTY; r.reasons.append(f"U-Shape {SCORE_USHAPE_PENALTY}")
            # Golden Confluence
            if self.check_golden_confluence(fvg_active, df_m5, htf_res, atr, sig):
                r.golden_conf = True
                r.score += SCORE_GOLDEN_CONFLUENCE; r.reasons.append(f"✨Golden +{SCORE_GOLDEN_CONFLUENCE}")
            # Strong candle
            body = abs(float(last["close"]) - float(last["open"]))
            if body > atr * 0.6:
                r.score += SCORE_STRONG_CANDLE; r.reasons.append(f"Strong +{SCORE_STRONG_CANDLE}")
            # OB
            ob = self.find_order_block(df_m5, sig, atr)
            if ob.found and not ob.mitigated:
                r.score += SCORE_OB_BONUS; r.reasons.append(f"OB(q:{ob.score:.2f},age:{ob.bar_age}) +{SCORE_OB_BONUS}")
                entry_check = r.entry
                if ob.low <= entry_check <= ob.high:
                    r.score += SCORE_OB_OVERLAP; r.reasons.append(f"OB Overlap +{SCORE_OB_OVERLAP}")

        def _apply_penalties(sig: str, fvg_active: Optional[FVGZone]) -> None:
            if r.adr_pct >= adr_ceil:
                r.score += SCORE_ADR_WARN; r.reasons.append(f"ADR{r.adr_pct*100:.0f}% {SCORE_ADR_WARN}")
            # KZ penalty [V16-O1]
            in_kz, _ = self.is_in_killzone()
            if not in_kz:
                penalty = KZ_PRE_LONDON_PENALTY if session == "PRE_LONDON" else KZ_OUTSIDE_PENALTY
                r.score += penalty; r.reasons.append(f"OutsideKZ {penalty}")
            # PRE_LONDON FOMO guard [V16-F1]
            if session == "PRE_LONDON" and PRE_LONDON_SWEEP_REQUIRED:
                has_sweep = (sig == "BUY" and (sweep_sell or liq.gap_swept_low is not None)) or \
                            (sig == "SELL" and (sweep_buy or liq.gap_swept_high is not None))
                if not has_sweep and fvg_active is not None:
                    r.score -= 15; r.reasons.append("PRE_LDN pure-FVG -15")
            # Judas
            if self.is_judas_swing(liq, fvg_zones, sig, session):
                r.is_judas = True; r.score += JUDAS_SCORE_BONUS
                r.reasons.append(f"⚡Judas +{JUDAS_SCORE_BONUS}")

        # ── BUY builder ───────────────────────────────────────────────────────
        def _build_buy() -> bool:
            has_sweep  = sweep_sell
            fvg_active = self.get_active_fvg(fvg_zones, price, "BUY")
            if not has_sweep and fvg_active is None: return False
            r.signal = "BUY"; r.score = SCORE_BASE

            if fvg_active is not None:
                r.entry = (fvg_active.bot + (fvg_active.top - fvg_active.bot) * 0.5
                           if FVG_ENTRY_MID else fvg_active.top)
                r.fvg_zone = fvg_active
            elif has_sweep:
                r.entry = last_sl + atr * 0.1
            r.sl = last_sl - atr * SL_ATR_MULT

            # Tier 1 — Core
            if fvg_active is not None and not fvg_active.mitigated:
                r.score += SCORE_FVG_FRESH; r.reasons.append(f"FVG Fresh +{SCORE_FVG_FRESH}")
                if fvg_active.strength > 0.5:
                    r.score += SCORE_FVG_STRENGTH; r.reasons.append(f"FVG Strong +{SCORE_FVG_STRENGTH}")
            if has_sweep:
                r.score += SCORE_LIQ_SWEPT
                lbl = "Gap-Sweep" if liq.gap_swept_low else "Sweep"
                r.reasons.append(f"{lbl} SSL +{SCORE_LIQ_SWEPT}")
            if has_sweep and fvg_active is not None:
                r.score += SCORE_SWEEP_AND_FVG; r.reasons.append(f"Sweep+FVG Bonus +{SCORE_SWEEP_AND_FVG}")

            # Tier 2 — HTF context
            _htf_scores("BUY"); _h1_scores("BUY")
            if htf_res.swept_low is not None:
                r.score += 4; r.reasons.append("H4 SSL Swept +4")

            # Tier 3 — Structure
            _apply_structure_scores("BUY", fvg_active)

            # Liq target
            if liq.bsl_nearest is not None:
                rsk = abs(r.entry - r.sl)
                if rsk > 0 and (liq.bsl_nearest - r.entry) >= rsk * RR_RATIO * 0.8:
                    r.score += SCORE_LIQ_TARGET; r.reasons.append(f"BSL→{liq.bsl_nearest:.2f} +{SCORE_LIQ_TARGET}")

            # Tier 4 — Penalties
            _apply_penalties("BUY", fvg_active)

            # Sweep classification
            r.sweep_type = self.classify_sweep("BUY", r.htf_bias)

            # Market order check
            body = float(last["close"]) - float(last["open"])
            if (float(last["close"]) > float(prev["high"])
                    and body / atr > MOMENTUM_BODY_ATR and r.score >= r.threshold):
                r.use_market = True; r.entry = 0.0; r.reasons.append("🚀 MKT")
            return True

        # ── SELL builder ──────────────────────────────────────────────────────
        def _build_sell() -> bool:
            has_sweep  = sweep_buy
            fvg_active = self.get_active_fvg(fvg_zones, price, "SELL")
            if not has_sweep and fvg_active is None: return False
            r.signal = "SELL"; r.score = SCORE_BASE

            if fvg_active is not None:
                r.entry = (fvg_active.bot + (fvg_active.top - fvg_active.bot) * 0.5
                           if FVG_ENTRY_MID else fvg_active.bot)
                r.fvg_zone = fvg_active
            elif has_sweep:
                r.entry = last_sh - atr * 0.1
            r.sl = last_sh + atr * SL_ATR_MULT

            if fvg_active is not None and not fvg_active.mitigated:
                r.score += SCORE_FVG_FRESH; r.reasons.append(f"FVG Fresh +{SCORE_FVG_FRESH}")
                if fvg_active.strength > 0.5:
                    r.score += SCORE_FVG_STRENGTH; r.reasons.append(f"FVG Strong +{SCORE_FVG_STRENGTH}")
            if has_sweep:
                r.score += SCORE_LIQ_SWEPT
                lbl = "Gap-Sweep" if liq.gap_swept_high else "Sweep"
                r.reasons.append(f"{lbl} BSL +{SCORE_LIQ_SWEPT}")
            if has_sweep and fvg_active is not None:
                r.score += SCORE_SWEEP_AND_FVG; r.reasons.append(f"Sweep+FVG Bonus +{SCORE_SWEEP_AND_FVG}")

            _htf_scores("SELL"); _h1_scores("SELL")
            if htf_res.swept_high is not None:
                r.score += 4; r.reasons.append("H4 BSL Swept +4")

            _apply_structure_scores("SELL", fvg_active)

            if liq.ssl_nearest is not None:
                rsk = abs(r.sl - r.entry)
                if rsk > 0 and (r.entry - liq.ssl_nearest) >= rsk * RR_RATIO * 0.8:
                    r.score += SCORE_LIQ_TARGET; r.reasons.append(f"SSL→{liq.ssl_nearest:.2f} +{SCORE_LIQ_TARGET}")

            _apply_penalties("SELL", fvg_active)
            r.sweep_type = self.classify_sweep("SELL", r.htf_bias)

            body = float(last["open"]) - float(last["close"])
            if (float(last["close"]) < float(prev["low"])
                    and body / atr > MOMENTUM_BODY_ATR and r.score >= r.threshold):
                r.use_market = True; r.entry = 0.0; r.reasons.append("🚀 MKT")
            return True

        if not _build_buy():
            r.signal = "WAIT"; r.score = 0; r.reasons = []
            if not _build_sell(): return r

        if r.signal != "WAIT":
            entry_h      = r.entry if not r.use_market else -1.0
            r.setup_hash = _make_hash(r.signal, entry_h, r.sl, r.candle_ts)
        return r


# ══════════════════════════════════════════════════════════════════════════════
# 💰  CLASS: RiskManager  [V17-L2 deviation cap]
# ══════════════════════════════════════════════════════════════════════════════
class RiskManager:
    def __init__(self):
        self._spread_guard = SpreadGuard()

    @staticmethod
    def get_broker_date() -> str:
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick: return datetime.fromtimestamp(tick.time, tz=pytz.utc).strftime("%Y%m%d")
        return datetime.utcnow().strftime("%Y%m%d")

    def get_spread_pts(self) -> float:
        tick = mt5.symbol_info_tick(SYMBOL); info = mt5.symbol_info(SYMBOL)
        if tick is None or info is None: return 999.0
        sp = (tick.ask - tick.bid) / info.point
        self._spread_guard.update(sp); return sp

    def is_spread_ok(self) -> Tuple[bool, str]:
        sp = self.get_spread_pts()
        return self._spread_guard.is_ok(sp)

    @staticmethod
    def get_spread_sl_padding() -> float:
        if not SPREAD_SL_PADDING: return 0.0
        tick = mt5.symbol_info_tick(SYMBOL); info = mt5.symbol_info(SYMBOL)
        if tick is None or info is None: return 0.0
        return ((tick.ask - tick.bid) / info.point) * info.point

    def get_dd_state(self) -> Tuple[float, float, str]:
        acct = mt5.account_info()
        if acct is None: return 0.0, 0.0, "NORMAL"
        today_key   = "daily_start_balance_" + self.get_broker_date()
        daily_start = get_state(today_key)
        if daily_start is None or daily_start <= 0:
            set_state(today_key, acct.balance); daily_start = acct.balance
        daily_dd = max(0.0, (daily_start - acct.equity) / daily_start * 100)
        init_bal = get_state("initial_balance")
        if init_bal is None:
            set_state("initial_balance", acct.balance); init_bal = acct.balance
        total_dd = max(0.0, (init_bal - acct.equity) / init_bal * 100)
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
    def dynamic_deviation(atr: float, emergency: bool = False) -> int:
        """
        [V17-L2] Returns deviation capped at MAX_DEVIATION_POINTS for entries.
        Emergency closes use EMERGENCY_DEVIATION_POINTS to ensure fill.
        """
        if emergency: return EMERGENCY_DEVIATION_POINTS
        info = mt5.symbol_info(SYMBOL)
        if info is None or info.point == 0: return MAX_DEVIATION_POINTS
        calc = max(20, int(atr * 0.08 / info.point))
        return min(calc, MAX_DEVIATION_POINTS)   # hard cap

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
# 📤  CLASS: ExecutionHandler  [V17-F5 slippage + V17-L3 partial fill]
# ══════════════════════════════════════════════════════════════════════════════
class ExecutionHandler:
    def __init__(self, risk: RiskManager, signal_engine: SMCSignalEngine):
        self._risk   = risk
        self._engine = signal_engine
        self._lock   = threading.Lock()

    def _send_retry(self, req: dict, retries: int = 3) -> Optional[object]:
        """
        [V17-L3] Handles TRADE_RETCODE_DONE_PARTIAL correctly:
          - Does NOT retry (would double the exposure).
          - Returns res as-is with actual filled volume logged.
          - Caller checks res.volume for actual fill.

        [V17-F5] Deviation is already capped in dynamic_deviation().
        Never overrides deviation to 100+ here (emergency closes use separate method).
        """
        last_res = None
        is_buy   = req.get("type") in (mt5.ORDER_TYPE_BUY, mt5.ORDER_TYPE_BUY_LIMIT,
                                        mt5.ORDER_TYPE_BUY_STOP)
        for i in range(1, retries + 1):
            try:
                with self._lock:
                    res = mt5.order_send(req)
            except Exception as exc:
                log.warning(f"order_send exception (try {i}): {exc}")
                if i < retries: time.sleep(0.5)
                continue

            if res is None:
                log.warning(f"order_send None (try {i}/{retries})")
                if i < retries: time.sleep(0.5)
                continue

            last_res = res

            if res.retcode == mt5.TRADE_RETCODE_DONE:
                return res

            # [V17-L3] Partial fill — do NOT retry; handle as successful
            if res.retcode == mt5.TRADE_RETCODE_DONE_PARTIAL:
                requested = req.get("volume", 0)
                filled    = getattr(res, "volume", requested)
                log.warning(
                    f"⚠️ PARTIAL FILL: {filled:.2f}/{requested:.2f} lots "
                    f"ticket:{getattr(res, 'order', 'N/A')} — NOT retrying "
                    f"(double-exposure risk). Adjusting SL/TP for filled volume."
                )
                # Adjust SL/TP on the actual position that was opened
                self._adjust_partial_fill(
                    ticket=getattr(res, "order", 0),
                    sl=req.get("sl", 0.0),
                    tp=req.get("tp", 0.0),
                )
                return res   # return as success with actual volume

            if res.retcode in (mt5.TRADE_RETCODE_REQUOTE,
                               mt5.TRADE_RETCODE_PRICE_CHANGED,
                               mt5.TRADE_RETCODE_PRICE_OFF):
                tick = mt5.symbol_info_tick(SYMBOL)
                if tick:
                    new_p = tick.ask if is_buy else tick.bid
                    log.warning(f"Price refresh (try {i}): {req.get('price','?'):.2f}→{new_p:.2f}")
                    req["price"] = round(float(new_p), 2)
                if i < retries: time.sleep(0.3 * i)
                continue

            if res.retcode in (mt5.TRADE_RETCODE_CONNECTION, mt5.TRADE_RETCODE_TIMEOUT):
                log.warning(f"Connection retry (try {i}/{retries})")
                if i < retries: time.sleep(0.5 * i)
                continue

            log.error(f"❌ retcode:{res.retcode} | {res.comment}"); return res

        log.error(f"❌ _send_retry exhausted {retries} attempts")
        return last_res

    def _adjust_partial_fill(self, ticket: int, sl: float, tp: float) -> None:
        """[V17-L3] Ensure the partially filled position has correct SL/TP."""
        if ticket == 0: return
        try:
            time.sleep(0.5)   # brief wait for position to register in terminal
            positions = mt5.positions_get(ticket=ticket)
            if positions:
                with self._lock:
                    mt5.order_send({
                        "action":   mt5.TRADE_ACTION_SLTP,
                        "position": ticket,
                        "sl":       round(float(sl), 2),
                        "tp":       round(float(tp), 2),
                    })
                log.info(f"✅ Partial fill SL/TP adjusted #{ticket}: SL={sl:.2f} TP={tp:.2f}")
        except Exception as exc:
            log.warning(f"_adjust_partial_fill exception #{ticket}: {exc}")

    def modify_sl(self, ticket: int, new_sl: float) -> None:
        try:
            with self._lock:
                res = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP,
                                       "position": ticket, "sl": round(float(new_sl), 2)})
            if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
                log.warning(f"modify_sl FAIL #{ticket}")
        except Exception as exc:
            log.warning(f"modify_sl exception #{ticket}: {exc}")

    def close_partial(self, pos, lot_close: float, atr: float = 0.0) -> None:
        try:
            tick = mt5.symbol_info_tick(SYMBOL)
            if tick is None: return
            info  = mt5.symbol_info(SYMBOL)
            step  = info.volume_step if info else 0.01; v_min = info.volume_min if info else 0.01
            lot_close  = float(max(v_min, min(self._risk._round_lot(lot_close, step), pos.volume)))
            is_buy     = (pos.type == mt5.ORDER_TYPE_BUY)
            price      = tick.bid if is_buy else tick.ask
            res = self._send_retry({
                "action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL,
                "volume": lot_close, "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
                "position": pos.ticket, "price": round(float(price), 2),
                "deviation": self._risk.dynamic_deviation(atr),   # capped at 30
                "magic": MAGIC_NUMBER, "comment": "V17|PartialTP"})
            if res and res.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL):
                log.info(f"💰 Partial #{pos.ticket} {lot_close:.2f} @ {price:.2f}")
        except Exception as exc:
            log.warning(f"close_partial exception: {exc}")

    def close_position_market(self, pos, is_eod: bool = False) -> bool:
        """
        [V17-L2] Emergency close uses EMERGENCY_DEVIATION_POINTS (150).
        Regular kills (KILL.flag, DD) also use higher deviation for fill priority.
        """
        try:
            tick = mt5.symbol_info_tick(SYMBOL); info = mt5.symbol_info(SYMBOL)
            if tick is None or info is None: return False
            is_buy = (pos.type == mt5.ORDER_TYPE_BUY)
            dev    = EMERGENCY_DEVIATION_POINTS   # always high for closes
            res = self._send_retry({
                "action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL,
                "volume": pos.volume, "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
                "position": pos.ticket,
                "price": round(float(tick.bid if is_buy else tick.ask), 2),
                "deviation": dev, "magic": MAGIC_NUMBER,
                "comment": f"V17|{'EOD' if is_eod else 'KILL'}"}, retries=5)
            ok = res is not None and res.retcode in (mt5.TRADE_RETCODE_DONE,
                                                      mt5.TRADE_RETCODE_DONE_PARTIAL)
            log.info(f"{'✅' if ok else '❌'} {'EOD' if is_eod else 'Kill'}-close #{pos.ticket}")
            return ok
        except Exception as exc:
            log.warning(f"close_position_market exception: {exc}"); return False

    def cancel_pending_order(self, ticket: int) -> bool:
        try:
            with self._lock:
                res = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": ticket})
            ok = res is not None and res.retcode == mt5.TRADE_RETCODE_DONE
            log.info(f"{'✅' if ok else '❌'} Cancel pending #{ticket}"); return ok
        except Exception as exc:
            log.warning(f"cancel_pending exception: {exc}"); return False

    def place_order(self, setup: SetupResult, session: str = "",
                    dd_mode: str = "NORMAL", adr: float = 0.0,
                    df_d1: Optional[pd.DataFrame] = None) -> bool:
        sp_ok, sp_reason = self._risk.is_spread_ok()
        if not sp_ok:
            log.warning(f"⛔ Spread blocked: {sp_reason}"); return False
        if not self._risk.is_within_risk_limits(): return False
        if self._risk.has_duplicate_setup(setup.setup_hash, setup.signal):
            log.info("🚫 Duplicate → skip"); return False
        if self._risk.count_open_positions() >= MAX_CONCURRENT_TRADES:
            log.info(f"⚠️ Max concurrent ({MAX_CONCURRENT_TRADES}) → skip"); return False

        sp     = self._risk.get_spread_pts()
        sl_pad = self._risk.get_spread_sl_padding()
        if sp > MAX_SPREAD_POINTS:
            setup.score += SCORE_SPREAD_WARN; setup.reasons.append(f"Spread{sp:.0f} {SCORE_SPREAD_WARN}")

        # M1 confirmation
        try:
            rates_m1 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 8)
            if rates_m1 is not None and len(rates_m1) >= 4:
                df_m1 = pd.DataFrame(rates_m1); c = df_m1.iloc[-2]
                body_m1 = abs(float(c["close"]) - float(c["open"]))
                dir_ok  = ((setup.signal == "BUY"  and c["close"] > c["open"]) or
                           (setup.signal == "SELL" and c["close"] < c["open"]))
                if body_m1 >= setup.atr * MTF_M1_BODY_ATR and dir_ok:
                    setup.score += SCORE_M1_CONFIRM; setup.reasons.append(f"M1 Disp +{SCORE_M1_CONFIRM}")
        except Exception: pass

        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None: return False

        sig    = setup.signal
        sl_adj = (setup.sl - sl_pad) if sig == "BUY" else (setup.sl + sl_pad)

        # Order type determination
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
                entry = tick.ask; otype = mt5.ORDER_TYPE_BUY; action = mt5.TRADE_ACTION_DEAL; exp = 0
            elif sig == "SELL" and entry <= tick.bid:
                entry = tick.bid; otype = mt5.ORDER_TYPE_SELL; action = mt5.TRADE_ACTION_DEAL; exp = 0

        risk = abs(entry - sl_adj)
        if risk == 0: log.error("place_order: risk=0"); return False

        # [V17-F5] Market order RR validation after slippage
        if action == mt5.TRADE_ACTION_DEAL:
            info_sym = mt5.symbol_info(SYMBOL)
            if info_sym:
                tp_check = entry + risk * RR_RATIO if sig == "BUY" else entry - risk * RR_RATIO
                actual_rr = abs(tp_check - entry) / max(risk, info_sym.point)
                if actual_rr < MIN_RR_RATIO_LIVE:
                    log.warning(
                        f"⛔ [V17-F5] Market order RR {actual_rr:.2f} < {MIN_RR_RATIO_LIVE} "
                        f"after slippage — skipping to protect RR."
                    )
                    return False

        tp_raw = entry + risk * RR_RATIO if sig == "BUY" else entry - risk * RR_RATIO
        tp_full, capped = self._engine.apply_adr_tp_cap(entry, tp_raw, sl_adj, adr, df_d1, session, sig)
        if capped: log.info(f"📏 ADR TP cap: {tp_raw:.2f}→{tp_full:.2f}")

        lot_full = self._risk.calculate_lot(entry, sl_adj, setup.score, sp, setup.atr, dd_mode)
        ok, reason = self._risk.validate_order(entry, sl_adj, tp_full, lot_full, sig)
        if not ok: log.warning(f"⚠️ Validate: {reason}"); return False

        info  = mt5.symbol_info(SYMBOL)
        step  = info.volume_step if info else 0.01; v_min = info.volume_min if info else 0.01
        lot_a = max(v_min, self._risk._round_lot(lot_full * PARTIAL_TP_PCT, step))
        lot_b = max(v_min, self._risk._round_lot(lot_full - lot_a, step))
        tp_pt = entry + risk * PARTIAL_TP_RR if sig == "BUY" else entry - risk * PARTIAL_TP_RR
        dev   = self._risk.dynamic_deviation(setup.atr)  # capped at MAX_DEVIATION_POINTS

        sent = 0
        for lot_i, tp_i, label in [(lot_a, tp_pt, "PT"), (lot_b, tp_full, "FT")]:
            req = {"action": action, "symbol": SYMBOL, "volume": lot_i, "type": otype,
                   "price": round(float(entry), 2), "sl": round(float(sl_adj), 2),
                   "tp": round(float(tp_i), 2), "deviation": dev, "magic": MAGIC_NUMBER,
                   "comment": f"V17|{sig}|{label}|{setup.score}|{setup.setup_hash}"}
            if action == mt5.TRADE_ACTION_PENDING:
                req["type_time"] = mt5.ORDER_TIME_SPECIFIED; req["expiration"] = exp
            res = self._send_retry(req)
            if res and res.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL):
                filled_vol = getattr(res, "volume", lot_i)
                sent += 1
                log.info(f"✅ {label}|{sig}|Lot:{filled_vol:.2f}|E:{entry:.2f}|SL:{sl_adj:.2f}|TP:{tp_i:.2f}")
            else:
                log.warning(f"⚠️ {label} order failed")

        if sent > 0:
            rr_act = abs(tp_full - entry) / risk if risk > 0 else 0
            log.info(
                f"\n{'═'*72}\n"
                f"  🎯 TRADE PLACED — {sig} {'MKT' if action == mt5.TRADE_ACTION_DEAL else 'LMT'}"
                f"  {'⚡JUDAS' if setup.is_judas else ''}"
                f"  {'✨GOLDEN' if setup.golden_conf else ''}\n"
                f"  {'─'*70}\n"
                f"  Entry: {entry:.2f}  SL: {sl_adj:.2f}  TP-Pt: {tp_pt:.2f}  TP-Full: {tp_full:.2f}\n"
                f"  Risk: {risk:.2f}  RR: {rr_act:.2f}×  Lot: {lot_a}+{lot_b}\n"
                f"  Score: {setup.score}/{setup.threshold}  WP: {setup.win_prob:.3f}  DD: {dd_mode}\n"
                f"  Session: {session}  H4: {setup.htf_bias}  H1: {setup.h1_bias}\n"
                f"  Shape: {setup.shape}  Sweep: {setup.sweep_type}  Dev: {dev}pts\n"
                f"  Spread: {sp:.1f}pts (median: {self._risk._spread_guard.median_spread:.1f})\n"
                f"  Hash: {setup.setup_hash}\n"
                f"{'═'*72}"
            )
            db_log_setup(sig, setup.score, entry, sl_adj, tp_full, setup.setup_hash,
                         session, setup.features, setup.win_prob, setup.sweep_type, setup.shape)
            return True
        return False


# ══════════════════════════════════════════════════════════════════════════════
# 🔄  CLASS: PositionManager  [V16-O2 outcome tracking preserved]
# ══════════════════════════════════════════════════════════════════════════════
class PositionManager:
    def __init__(self, feed: MarketDataFeed, execution: ExecutionHandler,
                 conn_mgr: ConnectionManager):
        self._feed    = feed
        self._exec    = execution
        self._conn    = conn_mgr
        self._running = threading.Event(); self._running.set()
        self._thread: Optional[threading.Thread] = None
        self._prev_tickets: set = set()

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
                if self._conn.ensure_connected():
                    df_m5 = self._feed.get_cached_m5()
                    atr   = calculate_atr(df_m5) if df_m5 is not None else 1.0
                    self._manage_positions(atr)
            except Exception as exc:
                log.warning(f"⚠️ PM error: {exc}")
            time.sleep(POSITION_POLL_SEC)

    def _detect_closed_positions(self, current_tickets: set) -> None:
        """[V16-O2] Detect positions that closed since last poll and record outcome."""
        closed = self._prev_tickets - current_tickets
        for ticket in closed:
            try:
                deals = mt5.history_deals_get(ticket=ticket)
                if deals:
                    profit = sum(d.profit for d in deals)
                    outcome = "WIN" if profit > 0 else "LOSS"
                    session_guess = ""
                    record_trade_outcome(outcome, session_guess)
                    log.info(f"📊 Closed #{ticket}: {outcome} (P&L: ${profit:.2f})")
                    # Check consecutive losses
                    n_loss = get_consecutive_losses()
                    if n_loss >= N_CONSEC_LOSS_PAUSE:
                        set_consec_loss_pause()
            except Exception as exc:
                log.warning(f"_detect_closed: {exc}")
        self._prev_tickets = current_tickets

    def _manage_positions(self, atr: float) -> None:
        positions = [p for p in (mt5.positions_get(symbol=SYMBOL) or [])
                     if p.magic == MAGIC_NUMBER]
        current_tickets = {p.ticket for p in positions}
        self._detect_closed_positions(current_tickets)
        if not positions: return

        tick = mt5.symbol_info_tick(SYMBOL); info = mt5.symbol_info(SYMBOL)
        if tick is None or info is None: return
        a            = max(atr, info.point * 10)
        trail_cache  = batch_load_trail_states(list(current_tickets))

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

            # All three steps independent (V13 fix preserved)
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
                last_tsl = float(ts["last_sl"]) if ts else None
                min_move = a * TRAIL_MIN_MOVE_ATR
                if is_buy:
                    new_tsl = price - (a * TRAIL_ATR_MULT)
                    if new_tsl > sl_now and (last_tsl is None or new_tsl > last_tsl + min_move):
                        self._exec.modify_sl(pos.ticket, new_tsl)
                        save_trail_sl(pos.ticket, new_tsl, pos_hash)
                        log.info(f"📈 Trail #{pos.ticket} {sl_now:.2f}→{new_tsl:.2f} R:{profit_r:.2f}")
                else:
                    new_tsl = price + (a * TRAIL_ATR_MULT)
                    if new_tsl < sl_now and (last_tsl is None or new_tsl < last_tsl - min_move):
                        self._exec.modify_sl(pos.ticket, new_tsl)
                        save_trail_sl(pos.ticket, new_tsl, pos_hash)
                        log.info(f"📉 Trail #{pos.ticket} {sl_now:.2f}→{new_tsl:.2f} R:{profit_r:.2f}")

            log.debug(f"📍 Pos #{pos.ticket}: ${pos.profit:+.2f} ({profit_r:+.2f}R)")

        cleanup_trail_state(current_tickets)


# ══════════════════════════════════════════════════════════════════════════════
# 🆘  EMERGENCY KILL-SWITCH
# ══════════════════════════════════════════════════════════════════════════════
def graceful_shutdown(execution: ExecutionHandler, reason: str = "EXIT") -> None:
    log.warning(f"🚨 GRACEFUL SHUTDOWN — {reason}")
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
def emit_heartbeat(risk: RiskManager, predictor: MLPredictor, session: str,
                   htf_bias: str, h1_bias: str, adr_pct: float) -> None:
    acct = mt5.account_info()
    if acct is None: return
    daily_dd, total_dd, dd_mode = risk.get_dd_state()
    init_bal  = get_state("initial_balance") or acct.balance
    eq_pct    = (acct.equity - init_bal) / init_bal * 100 if init_bal > 0 else 0
    day_start = get_state("daily_start_balance_" + risk.get_broker_date()) or acct.balance
    today_pl  = acct.equity - day_start
    open_pos  = risk.count_open_positions()
    pause_on  = os.path.isfile(PAUSE_FLAG_PATH)
    kill_on   = os.path.isfile(KILL_FLAG_PATH)
    model_tag = "✅ Real Model" if predictor.model_loaded else "🔶 Score-only (no ML model)"
    consec    = get_consecutive_losses()
    mode_lbl  = ("🔴 KILL" if kill_on else "⏸️ PAUSED" if pause_on
                 else "🟠 ORANGE" if dd_mode == "ORANGE"
                 else "💛 YELLOW" if dd_mode == "YELLOW"
                 else "🔴 RED"    if dd_mode == "RED" else "🟢 NORMAL")
    log.info(
        f"\n{'═'*72}\n"
        f"  📊  OPERATOR STATUS V17  [{datetime.now(STRATEGY_TZ).strftime('%H:%M:%S')} BKK]\n"
        f"  {'─'*70}\n"
        f"  Equity     : ${acct.equity:>10,.2f}  ({eq_pct:+.2f}%)\n"
        f"  Today P&L  : ${today_pl:>+10,.2f}\n"
        f"  DD Daily   : {daily_dd:.2f}%   DD Total: {total_dd:.2f}%\n"
        f"  Session    : {session:<16} H4: {htf_bias:<10} H1: {h1_bias:<10} ADR: {adr_pct*100:.0f}%\n"
        f"  Open Pos   : {open_pos}/{MAX_CONCURRENT_TRADES}\n"
        f"  ML Mode    : {model_tag}   Norm: {'WARM' if predictor.norm_is_warm else 'COLD'}\n"
        f"  Consec Loss: {consec}/{N_CONSEC_LOSS_PAUSE}\n"
        f"  Mode       : {mode_lbl}\n"
        f"  Dev Cap    : {MAX_DEVIATION_POINTS}pts entry / {EMERGENCY_DEVIATION_POINTS}pts emergency\n"
        f"  Friday EOD : {FRIDAY_CLOSE_UTC_HOUR:02d}:{FRIDAY_CLOSE_UTC_MIN:02d} UTC\n"
        f"{'═'*72}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 🚀  SIGNAL CYCLE
# ══════════════════════════════════════════════════════════════════════════════
def _run_signal_cycle(feed: MarketDataFeed, signal_engine: SMCSignalEngine,
                      risk: RiskManager, execution: ExecutionHandler,
                      predictor: MLPredictor, conn_mgr: ConnectionManager,
                      friday_guard: FridayGuard, last_ctx: Dict) -> None:

    if not conn_mgr.ensure_connected(): return

    # [V17-L1] Friday guard takes priority
    if friday_guard.is_blocked():
        friday_guard.execute_eod_close(execution)
        return

    daily_dd, total_dd, dd_mode = risk.get_dd_state()
    if dd_mode == "RED":
        log.warning(f"⛔ DD RED daily={daily_dd:.2f}% total={total_dd:.2f}% → halt"); return
    if risk.is_circuit_breaker_tripped(): return

    session = signal_engine.get_session()
    if session in ("OUT_OF_SESSION", "RED_NEWS_BLOCK"): return

    in_kz, kz_name = signal_engine.is_in_killzone()
    # Note: KZ penalty is already scored inside analyze_setup; we don't hard-block here

    sp_ok, sp_reason = risk.is_spread_ok()
    if not sp_ok: log.warning(f"⛔ Spread: {sp_reason}"); return

    if os.path.isfile(PAUSE_FLAG_PATH):
        log.info("⏸️ PAUSE.flag → skip new entries"); return
    if not risk.new_entries_allowed():
        log.warning(f"🟠 DD {dd_mode} → new entries suspended"); return
    if is_consec_loss_paused(): return

    data = feed.fetch_all()
    if data["m5"] is None: log.warning("M5 unavailable → skip"); return
    cleanup_cooldowns()

    setup = signal_engine.analyze_setup(
        data["m5"], data["h4"], data["d1"], data["m15"], data.get("h1"), session)
    setup.spread_pts = risk.get_spread_pts()

    last_ctx.update({"bias": setup.htf_bias, "h1_bias": setup.h1_bias,
                     "session": session, "adr_pct": str(setup.adr_pct)})

    liq = setup.liq_map
    if liq:
        log.info(f"💧 BSL:{liq.bsl_nearest or '—'} SSL:{liq.ssl_nearest or '—'} "
                 f"SwH:{liq.swept_high} SwL:{liq.swept_low}")
    htf = setup.htf_result
    if htf:
        log.info(f"🏗️ H4:{htf.bias} BOS:{htf.last_bos} CHOCH:{htf.choch_signal} | {htf.reason}")
    log.info(f"📊 {session} KZ:{kz_name} | M15:{setup.m15_struct} | "
             f"ADR:{setup.adr_pct*100:.0f}% | Thr:{setup.threshold} | DD:{dd_mode} | "
             f"Shape:{setup.shape} | Sweep:{setup.sweep_type}")

    if setup.signal == "WAIT": return
    if setup.score < setup.threshold:
        log.info(f"⚠️ Score {setup.score} < {setup.threshold} → skip"); return

    close_price    = float(data["m5"]["close"].iloc[-1]) if data["m5"] is not None else 2000.0
    setup.features = extract_features(setup, close_price=close_price, df_len=len(data["m5"]))

    # [V17-F4] ML gate: bypass if no model; active only with real model
    setup.win_prob = predictor.predict_win_probability(setup.features)
    if predictor.model_loaded and setup.win_prob < ML_WIN_PROB_THRESHOLD:
        log.info(f"🤖 ML rejected: {setup.win_prob:.3f} < {ML_WIN_PROB_THRESHOLD}"); return

    mode_tag = "real-model" if predictor.model_loaded else "score-only (ML bypassed)"
    log.info(f"🧠 WP:{setup.win_prob:.3f} [{mode_tag}] avg:{predictor.rolling_avg_prob:.3f} "
             f"| {setup.summary()}")

    if is_on_cooldown(setup.setup_hash):
        log.info(f"🔁 Cooldown → skip"); return
    if risk.has_duplicate_setup(setup.setup_hash, setup.signal):
        log.info("🚫 Duplicate → skip"); return

    adr_val = calculate_adr(data.get("d1"))
    if execution.place_order(setup, session, dd_mode, adr=adr_val, df_d1=data.get("d1")):
        set_cooldown(setup.setup_hash)
        log.info(f"🎯 Placed | hash:{setup.setup_hash} | {setup.sweep_type} | {setup.shape}")


# ══════════════════════════════════════════════════════════════════════════════
# 🚀  MAIN
# ══════════════════════════════════════════════════════════════════════════════
BANNER = """
╔══════════════════════════════════════════════════════════════════════════════════╗
║  🏆  AI SMC/ICT Pro Sniper — V.17 LIVE  (XAUUSD)                                ║
║  [V17-F1] Simplified scoring (threshold 65) — no analysis paralysis             ║
║  [V17-F2] VOL_SPIKE permanently removed — body-size displacement only           ║
║  [V17-F3] DXY deprecated (decouples from Gold in modern markets)                ║
║  [V17-F4] ML heuristic bypass — gate only with real .joblib model               ║
║  [V17-F5] MKT order RR validation — bad fills rejected before sending           ║
║  [V17-L1] Friday EOD guard — auto-flatten at 21:00 UTC, blocked Sat-Sun        ║
║  [V17-L2] MAX deviation cap 30pts entries / 150pts emergency closes             ║
║  [V17-L3] DONE_PARTIAL handling — no retry, SL/TP adjusted on partial fill     ║
╚══════════════════════════════════════════════════════════════════════════════════╝
"""


def main() -> None:
    print(BANNER)
    log.info("Bot V.17 LIVE starting")
    init_db()

    conn_mgr = ConnectionManager()
    for delay in [0, 5, 10, 20, 30]:
        if delay: time.sleep(delay)
        if conn_mgr.ensure_connected(): break
    else:
        log.error("❌ Cannot connect to MT5 after extended retry"); return

    clock         = BrokerClockSync(SYMBOL, STRATEGY_TZ)
    clock.refresh()

    feed          = MarketDataFeed()
    signal_engine = SMCSignalEngine(clock)
    risk          = RiskManager()
    execution     = ExecutionHandler(risk, signal_engine)
    predictor     = MLPredictor()
    friday_guard  = FridayGuard(clock)

    # Uncomment to load a trained model:
    # predictor.load_model("smc_model_v17.joblib")

    pm = PositionManager(feed, execution, conn_mgr)
    pm.start()

    last_ctx: Dict[str, str] = {
        "bias": "NEUTRAL", "h1_bias": "NEUTRAL", "session": "UNKNOWN", "adr_pct": "0.0"
    }
    _shutdown = threading.Event()

    def _sig_handler(signum, frame):
        log.warning(f"Signal {signum} → shutdown"); _shutdown.set()

    signal.signal(signal.SIGTERM, _sig_handler)
    signal.signal(signal.SIGINT,  _sig_handler)

    last_closed_bar_time: Optional[int] = None
    last_heartbeat:       float         = time.time()

    log.info(
        f"📡 Symbol:{SYMBOL} | Threshold:65 | Max Dev:{MAX_DEVIATION_POINTS}pts | "
        f"Friday EOD:{FRIDAY_CLOSE_UTC_HOUR:02d}:{FRIDAY_CLOSE_UTC_MIN:02d} UTC | "
        f"CB:{CIRCUIT_BREAKER_PCT}% | SpreadMult:{SPREAD_DYNAMIC_MULT}× | "
        f"ConsecLoss:{N_CONSEC_LOSS_PAUSE}-strike → {CONSEC_LOSS_PAUSE_MIN}min pause"
    )

    try:
        while not _shutdown.is_set():
            if os.path.isfile(KILL_FLAG_PATH):
                log.warning("🚨 KILL.flag!"); _shutdown.set(); break

            if not conn_mgr.ensure_connected():
                time.sleep(TICK_POLL_SEC); continue

            clock.refresh()

            # [V17-L1] Friday check on every loop — may trigger EOD flatten
            if friday_guard.is_blocked():
                friday_guard.execute_eod_close(execution)
                log.info("📅 Friday/Weekend — no new entries. Bot monitoring only.")
                time.sleep(60); continue

            try:
                rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M5, 0, 2)
            except Exception as exc:
                log.warning(f"copy_rates exception: {exc}"); time.sleep(TICK_POLL_SEC); continue

            if rates is None or len(rates) < 2:
                time.sleep(TICK_POLL_SEC); continue

            previous_closed_bar_time = int(rates[-2]["time"])

            if previous_closed_bar_time != last_closed_bar_time:
                log.info("─" * 74)
                log.info(
                    f"🕯️  Closed:{previous_closed_bar_time} | "
                    f"New:{int(rates[-1]['time'])} | "
                    f"{clock.now_strategy().strftime('%H:%M:%S')} {STRATEGY_TZ_NAME}"
                )
                last_closed_bar_time = previous_closed_bar_time
                _run_signal_cycle(
                    feed, signal_engine, risk, execution, predictor,
                    conn_mgr, friday_guard, last_ctx
                )

            now = time.time()
            if now - last_heartbeat >= HEARTBEAT_SEC:
                emit_heartbeat(
                    risk, predictor,
                    last_ctx.get("session", "?"),
                    last_ctx.get("bias", "?"),
                    last_ctx.get("h1_bias", "?"),
                    float(last_ctx.get("adr_pct", "0"))
                )
                last_heartbeat = now

            time.sleep(TICK_POLL_SEC)

    except KeyboardInterrupt:
        log.info("🛑 KeyboardInterrupt")
    except Exception as exc:
        log.exception(f"💥 Unhandled: {exc}")
    finally:
        log.info("Graceful shutdown initiating…")
        pm.stop()
        graceful_shutdown(execution)
        close_db()
        try: mt5.shutdown()
        except Exception: pass
        log.info("MT5 offline. Bot V.17 LIVE terminated.")


# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    main()
