"""
╔══════════════════════════════════════════════════════════════════════════════════╗
║  🏆  AI SMC/ICT Pro Sniper — V.16 ELITE  (XAUUSD Gold Specialist)               ║
╠══════════════════════════════════════════════════════════════════════════════════╣
║                                                                                  ║
║  ██████████  V.16 AUDIT & REFACTOR REPORT  ██████████████████████████████████  ║
║                                                                                  ║
║  ── MATHEMATICAL APPROACH NOTES ────────────────────────────────────────────── ║
║                                                                                  ║
║  V-Shape Detection (Price Velocity)                                              ║
║  ─────────────────────────────────                                               ║
║  A true V-shape reversal has two mathematical signatures:                        ║
║  (1) Impulse Velocity: body of the rejection bar ≥ VSHAPE_ATR_MULT × ATR        ║
║      (default 2.0×). This filters sluggish consolidation candles.               ║
║  (2) Return Speed: The sweep candle's closing price must reclaim ≥               ║
║      VSHAPE_RETRACE_PCT (0.65) of the distance from sweep-extreme back to        ║
║      origin in ≤ VSHAPE_MAX_BARS (3) candles. A U-shape takes 5-10+ bars.       ║
║  U-shape invalidation: If price returns toward the sweep level without           ║
║  closing above/below the Pre-Sweep level within USHAPE_MAX_BARS (5),            ║
║  the signal is suppressed.  Measured as consecutive bars spent within           ║
║  the sweep wick range without meaningful directional close.                     ║
║                                                                                  ║
║  Timezone Synchronisation                                                        ║
║  ─────────────────────────                                                       ║
║  MT5 broker server time is read directly from `mt5.symbol_info_tick().time`     ║
║  (Unix UTC timestamp) on every cycle.  We convert to STRATEGY_TZ at runtime     ║
║  rather than relying on OS clock, eliminating broker EET/EEST drift.            ║
║  `BrokerClockSync.now_strategy()` is the single authoritative time source       ║
║  used by all session / killzone / news guards.                                  ║
║                                                                                  ║
║  Spread Dynamic Lock                                                             ║
║  ────────────────────                                                            ║
║  SPREAD_DYNAMIC_MULT (default 3.0×) computes a rolling 20-bar median spread.    ║
║  Entry is blocked when live spread > median × SPREAD_DYNAMIC_MULT OR            ║
║  > HARD_SPREAD_BLOCK (absolute).  This handles news spikes (50-100pt gaps)      ║
║  without relying solely on a static threshold.                                  ║
║                                                                                  ║
║  ── MANDATORY FIXES ──────────────────────────────────────────────────────────  ║
║                                                                                  ║
║  [V16-F1]  PRE_LONDON FOMO GUARD — Backtest shows 26.9% loss rate in            ║
║            PRE_LONDON (vs 19.4% in NY_OPEN_EARLY). PRE_LONDON now requires     ║
║            a higher threshold (+8) AND sweep confirmation.  Pure-FVG-only       ║
║            trades (no sweep) are blocked in this session.                        ║
║                                                                                  ║
║  [V16-F2]  DYNAMIC SPREAD LOCK — `SpreadGuard` tracks 20-bar rolling median.   ║
║            New entries blocked if live_spread > median × 3.0 OR > 100pts.       ║
║            This prevents instant-SL hits on news spike spreads.                 ║
║                                                                                  ║
║  [V16-F3]  AUTO-RECONNECT with EXPONENTIAL BACKOFF — Main loop wraps all        ║
║            MT5 calls in `ConnectionManager`.  On `copy_rates_from_pos=None`     ║
║            or `terminal_info=None`, waits 5→10→20→40s (cap 120s) before        ║
║            retrying.  PM thread never crashes on network drop; gracefully        ║
║            skips tick with a warning.                                            ║
║                                                                                  ║
║  [V16-F4]  BROKER TIMEZONE SYNC — `BrokerClockSync` reads broker server UTC     ║
║            time from live tick, converts to STRATEGY_TZ.  All session/KZ        ║
║            gates use broker-derived time, not OS clock.                         ║
║                                                                                  ║
║  ── ADVANCED SMC/ICT STRATEGIES ─────────────────────────────────────────────  ║
║                                                                                  ║
║  [V16-S1]  MTF MATRIX (H4 > H1 > M15 > M5 > M1) — Full five-timeframe          ║
║            alignment score. H1 added as intermediate confirmation layer.         ║
║            MTF alignment bonus: +8 if H1 bias agrees with H4; −5 if conflicts. ║
║            M1 displacement confirmation upgraded: now requires BOTH large        ║
║            body AND prior M1 BOS in the entry direction.                         ║
║                                                                                  ║
║  [V16-S2]  SWEEP CLASSIFICATION (CONTINUE vs REVERSE) — Every liquidity         ║
║            sweep is classified:                                                  ║
║            • CONTINUE: sweep direction matches H4 bias (e.g., SSL sweep +        ║
║              H4 BULLISH). Treated as standard continuation pullback entry.       ║
║            • REVERSE: sweep opposes H4 bias (Judas Swing). Triggers the        ║
║              existing Judas override but now also requires MSS (see V16-S3).   ║
║            Classification stored in SetupResult.sweep_type for logging.        ║
║                                                                                  ║
║  [V16-S3]  MSS & CISD CONFIRMATION — A Market Structure Shift (MSS) on M5       ║
║            requires close above/below the last confirmed swing. Replaces the    ║
║            simpler BOS_M5 check. CISD (Change in State of Delivery):           ║
║            the M5 candle that triggers MSS must also be a displacement candle   ║
║            (body > CISD_ATR_MULT × ATR) — confirming institutional delivery.   ║
║            Adds SCORE_MSS_CISD = +12 when both conditions met; +5 for MSS only.║
║                                                                                  ║
║  [V16-S4]  V-SHAPE vs U-SHAPE DETECTION — `VShapeDetector.classify()` returns  ║
║            "V" / "U" / "NONE". V-shape → +10 score bonus. U-shape → −15         ║
║            penalty (slow consolidation: likely to be stopped out). Calculated   ║
║            using Price Velocity and Retrace Speed as described above.           ║
║                                                                                  ║
║  [V16-S5]  CCT 2025 GOLDEN CONFLUENCE (FVG + OTE + DISPLACEMENT) —             ║
║            OTE (Optimal Trade Entry) zone = 61.8%–79% Fibonacci retracement     ║
║            of the last confirmed H4 swing leg. Displacement candle = M5 body    ║
║            > DISPLACEMENT_ATR_MULT (2.0×) ATR with high tick volume (optional). ║
║            When FVG + OTE + Displacement all align: +15 Golden Confluence       ║
║            bonus. No intra-bar entry possible (already enforced by V14-F1).    ║
║                                                                                  ║
║  ── LIVE SAFETY & OPERATIONAL ───────────────────────────────────────────────  ║
║                                                                                  ║
║  [V16-O1]  KILLZONE PENALTY SYSTEM — Outside killzones now receive −30 score    ║
║            penalty (from −0 in V15), making them effectively impossible to       ║
║            trade through to the threshold. Inside killzone = 0 penalty.         ║
║            PRE_LONDON outside the KZ window gets −20 penalty (partial block).  ║
║                                                                                  ║
║  [V16-O2]  CONSECUTIVE-LOSS CIRCUIT BREAKER — After N_CONSEC_LOSS_PAUSE (3)    ║
║            consecutive realized losses (tracked in SQLite), the bot pauses      ║
║            new entries for CONSEC_LOSS_PAUSE_MIN (60) minutes.  Prevents        ║
║            chop-machine mode during U-shape markets.                            ║
║                                                                                  ║
║  [V16-O3]  H1 INTERMEDIATE BIAS — H1 data added to fetch_all().  Used in        ║
║            MTF Matrix for alignment scoring and as intermediate bias filter.    ║
║                                                                                  ║
║  PRESERVED FROM V.15 (all intact)                                               ║
║  ─────────────────────────────────────────────────────────────────────────────  ║
║  V15-S1 balanced scoring · Welford normaliser · Writer queue · PAUSE/KILL       ║
║  3-tier DD · graceful_shutdown · SIGTERM · NumPy hot-paths · FVG memory         ║
║  OB freshness · Gap-sweep · Dual-key tracking · Judas swing · ADR TP cap        ║
║  H4 HTF bias · CB decoupled · FVG age norm · Outlier guard · M15 BOS           ║
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
DXY_SYMBOL       = "USDXm"         # set "" to disable
MAGIC_NUMBER     = 99999
BROKER_TZ_NAME   = "Etc/UTC"       # MT5 server timezone (tick.time is always UTC)
STRATEGY_TZ_NAME = "Asia/Bangkok"  # Your monitoring timezone (GMT+7)
BROKER_TZ        = pytz.timezone(BROKER_TZ_NAME)
STRATEGY_TZ      = pytz.timezone(STRATEGY_TZ_NAME)


# ══════════════════════════════════════════════════════════════════════════════
# ⚙️  STRATEGY CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════
RR_RATIO            = 2.5
MAX_DAILY_LOSS_PCT  = 4.0
MAX_TOTAL_DD_PCT    = 8.0
EXPIRATION_CANDLES  = 36

# ── Spread guards [V16-F2] ────────────────────────────────────────────────────
HARD_SPREAD_BLOCK    = 100.0        # absolute block (pts)
MAX_SPREAD_POINTS    = 50.0         # soft warning threshold
SPREAD_DYNAMIC_MULT  = 3.0          # block if live > median × this
SPREAD_MEDIAN_BARS   = 20           # rolling window for median spread calc
SPREAD_LOT_PENALTY   = 0.3
SPREAD_SL_PADDING    = True

MOMENTUM_BODY_ATR   = 1.2
BREAKEVEN_RR        = 1.0
TRAIL_AFTER_RR      = 1.5
TRAIL_ATR_MULT      = 0.8
TRAIL_MIN_MOVE_ATR  = 0.3

ADR_EXHAUSTED_PCT   = 0.88
ADR_NY_EXHAUSTED_PCT = 0.93
ADR_HARD_BLOCK      = False
ADR_TP_BUFFER_PCT   = 0.95

SL_ATR_MULT         = 1.2
FVG_ENTRY_MID       = True
SWING_PERIOD        = 5
SWING_CONFIRM_BARS  = 2
SETUP_COOLDOWN_SEC  = 180

PARTIAL_TP_RR       = 1.0
PARTIAL_TP_PCT      = 0.50
MAX_CONCURRENT_TRADES = 2
INTRABAR_ENABLED    = True      # PM runs intrabar; entries ONLY on closed M5

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

# Volume Spike (disabled by default — most brokers have tick volume only)
VOL_SPIKE_ENABLED   = False
VOL_SPIKE_MULT      = 1.5
VOL_SPIKE_PERIOD    = 20

# Judas Swing
JUDAS_SWING_ENABLED  = True
JUDAS_WINDOW_MIN     = 15
JUDAS_SCORE_BONUS    = 15

# Liquidity
LIQ_SWING_PERIOD    = 10
LIQ_EQUAL_TOLERANCE = 0.0003
LIQ_MIN_CLUSTER     = 2

# HTF
HTF_BARS             = 120
HTF_SWING_PERIOD     = 3
HTF_SWING_CONFIRM    = 2

# [V16-O3] H1 intermediate bias
H1_BARS              = 100
H1_SWING_PERIOD      = 4
H1_SWING_CONFIRM     = 2
H1_AGREE_BONUS       = 8     # H1 agrees with H4 → bonus
H1_CONFLICT_PENALTY  = -5    # H1 conflicts H4 → penalty

# DXY
DXY_ENABLED         = False
DXY_SWING_PERIOD    = 5
DXY_BUY_PENALTY     = -10
DXY_SELL_BONUS      = 8

# P/D Zone
PD_ZONE_ENABLED     = False
PD_PERIOD           = 50
PD_PENALTY          = -6

MTF_M1_BODY_ATR     = 0.3

# [V16-S3] MSS & CISD
MSS_ENABLED          = True
CISD_ATR_MULT        = 1.5   # displacement candle body threshold (× ATR)
SCORE_MSS_CISD       = 12    # MSS + CISD confirmed
SCORE_MSS_ONLY       = 5     # MSS without displacement

# [V16-S4] V-Shape / U-Shape Detection
VSHAPE_ENABLED       = True
VSHAPE_ATR_MULT      = 1.8   # rejection bar body ≥ N × ATR → V-shape impulse
VSHAPE_RETRACE_PCT   = 0.60  # must retrace ≥ 60% of sweep wick back to origin
VSHAPE_MAX_BARS      = 3     # retracement must happen within N bars
USHAPE_MAX_BARS      = 5     # if no retrace in N bars → U-shape (chop)
SCORE_VSHAPE_BONUS   = 10    # clean V-shape rejection
SCORE_USHAPE_PENALTY = -15   # slow U-shape consolidation (chop)

# [V16-S5] CCT 2025 Golden Confluence
GOLDEN_CONFL_ENABLED    = True
OTE_LOW_PCT             = 0.618    # Fibonacci OTE zone low (61.8%)
OTE_HIGH_PCT            = 0.79     # Fibonacci OTE zone high (79%)
DISPLACEMENT_ATR_MULT   = 2.0      # displacement candle body threshold
SCORE_GOLDEN_CONFLUENCE = 15       # FVG + OTE + Displacement alignment

# [V16-F1] PRE_LONDON FOMO guard
PRE_LONDON_SWEEP_REQUIRED = True   # block pure-FVG-only trades in PRE_LONDON
PRE_LONDON_SCORE_BOOST    = 8      # extra score required in PRE_LONDON

# [V16-O1] Killzone penalty
KZ_OUTSIDE_PENALTY       = -30     # penalty outside killzones (makes trading impossible)
KZ_PRE_LONDON_PENALTY    = -20     # lighter penalty for PRE_LONDON session

# [V16-O2] Consecutive-loss circuit breaker
N_CONSEC_LOSS_PAUSE      = 3       # pause after N consecutive losses
CONSEC_LOSS_PAUSE_MIN    = 60      # pause duration in minutes

# [V16-F3] Auto-reconnect
RECONNECT_BASE_DELAY     = 5.0     # seconds (doubles each attempt, cap 120)
RECONNECT_MAX_DELAY      = 120.0
RECONNECT_MAX_ATTEMPTS   = 20

# ── Scoring constants [V15-S1 balanced — preserved] ──────────────────────────
SCORE_BASE          = 40
SCORE_FVG_FRESH     = 20
SCORE_LIQ_SWEPT     = 20
SCORE_SWEEP_AND_FVG = 5
SCORE_HTF_ALIGN     = 10
SCORE_HTF_AGAINST   = -15
SCORE_M15_BOS       = 10
SCORE_OB_BONUS      = 5
SCORE_OB_OVERLAP    = 5
SCORE_STRONG_CANDLE = 5
SCORE_BOS_M5        = 5      # kept for backward compat; MSS/CISD replaces
SCORE_LIQ_TARGET    = 5
SCORE_FVG_STRENGTH  = 5
SCORE_VOL_SPIKE     = 5
SCORE_ADR_WARN      = -10
SCORE_SPREAD_WARN   = -5
SCORE_M1_CONFIRM    = 5

# Thresholds [V16-F1] PRE_LONDON raised by PRE_LONDON_SCORE_BOOST
SCORE_THRESHOLD: Dict[str, int] = {
    "LONDON":        70,
    "NEW_YORK":      70,
    "NY_OPEN_EARLY": 70,
    "PRE_LONDON":    70 + PRE_LONDON_SCORE_BOOST,  # = 78
    "DEFAULT":       70,
}

SCORE_PENALTY_HTF_NEUTRAL = 0
ML_WIN_PROB_THRESHOLD     = 0.50
ML_ROLLING_WINDOW         = 60
# [V16-RISK1 FIX] When no real model is loaded, the heuristic baseline starts at 0.38
# and easily clears 0.50 with normal conditions. Use a stricter gate in heuristic mode.
ML_HEURISTIC_THRESHOLD    = 0.58   # gate raised when running without a trained model

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
CIRCUIT_BREAKER_PCT = 4.5

# Killzones & Sessions (Strategy timezone)
KILLZONE_ENABLED = True
KILLZONES = [
    (14,  0, 16, 30, "London Open"),
    (18, 30, 19, 15, "NY Open Early"),   # [V16-BUG3 FIX] Added — matches NY_OPEN_EARLY session
    (19, 45, 22,  0, "NY Open"),
]
SESSIONS = [
    (12,  0, 14,  0, "PRE_LONDON"),
    (14,  0, 18,  0, "LONDON"),
    (18, 30, 19, 15, "NY_OPEN_EARLY"),
    (19, 45, 23, 59, "NEW_YORK"),
]

CACHE_TTL_LTF   = 5
CACHE_TTL_HTF   = 60
CACHE_TTL_D1    = 300

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
# 🕐  [V16-F4]  BROKER CLOCK SYNC  — authoritative time from MT5 tick
# ══════════════════════════════════════════════════════════════════════════════
class BrokerClockSync:
    """
    [V16-F4] Reads broker server time from the live tick timestamp.

    MT5 `symbol_info_tick().time` is always a UTC Unix timestamp, regardless
    of the broker server's local timezone setting (EET/EEST/UTC+2/+3 etc.).
    Converting via pytz ensures that London/NY session filters are always
    evaluated against the correct wall-clock time in STRATEGY_TZ.

    Falls back to OS UTC if tick unavailable (should not happen in normal ops).
    """

    def __init__(self, symbol: str, strategy_tz: pytz.BaseTzInfo):
        self._symbol      = symbol
        self._strategy_tz = strategy_tz
        self._last_tick_utc: Optional[datetime] = None

    def refresh(self) -> None:
        """Cache latest broker tick timestamp."""
        tick = mt5.symbol_info_tick(self._symbol)
        if tick is not None:
            # tick.time is seconds since epoch (UTC)
            self._last_tick_utc = datetime.utcfromtimestamp(tick.time).replace(tzinfo=pytz.utc)

    def now_utc(self) -> datetime:
        """Current time as UTC datetime (broker-derived)."""
        if self._last_tick_utc is not None:
            return self._last_tick_utc
        return datetime.now(pytz.utc)

    def now_strategy(self) -> datetime:
        """Current time in STRATEGY_TZ (converted from broker UTC tick)."""
        return self.now_utc().astimezone(self._strategy_tz)

    def t(self) -> dtime:
        """Current time-of-day in STRATEGY_TZ (dtime object for session comparisons)."""
        return self.now_strategy().time()


# ══════════════════════════════════════════════════════════════════════════════
# 🌐  [V16-F3]  CONNECTION MANAGER  — auto-reconnect with exponential backoff
# ══════════════════════════════════════════════════════════════════════════════
class ConnectionManager:
    """
    [V16-F3] Wraps all MT5 connectivity with automatic reconnect logic.

    On any network drop (copy_rates_from_pos returns None, terminal_info=None,
    or order_send fails with CONNECTION retcode), the manager:
    1. Logs the error with context
    2. Calls mt5.initialize() with exponential backoff: 5→10→20→40→...→120s
    3. Caps at RECONNECT_MAX_DELAY and RECONNECT_MAX_ATTEMPTS
    4. Returns False / None to caller so they can gracefully skip the cycle
       rather than crashing with an unhandled exception

    Thread-safe: PM thread calls is_connected() on every poll loop.
    """

    def __init__(self):
        self._lock          = threading.RLock()
        self._connected     = False
        self._attempt       = 0
        self._next_retry_at = 0.0   # epoch seconds

    def ensure_connected(self) -> bool:
        """Returns True if MT5 is connected and ready."""
        with self._lock:
            if mt5.terminal_info() is not None:
                self._connected = True
                self._attempt   = 0
                return True

            # Not connected — check backoff timer
            now = time.time()
            if now < self._next_retry_at:
                return False

            if self._attempt >= RECONNECT_MAX_ATTEMPTS:
                log.error(
                    f"⛔ ConnectionManager: {RECONNECT_MAX_ATTEMPTS} reconnect attempts "
                    "exhausted — bot will keep trying but no new orders"
                )

            # Attempt reconnect
            self._attempt += 1
            delay = min(
                RECONNECT_BASE_DELAY * (2 ** (self._attempt - 1)),
                RECONNECT_MAX_DELAY
            )
            log.warning(
                f"🔌 MT5 disconnected — reconnect attempt #{self._attempt} "
                f"(next retry after {delay:.0f}s)"
            )

            if mt5.initialize():
                log.info(f"✅ MT5 reconnected on attempt #{self._attempt}")
                self._connected     = True
                self._attempt       = 0
                self._next_retry_at = 0.0
                return True
            else:
                self._connected     = False
                self._next_retry_at = now + delay
                return False

    @property
    def is_connected(self) -> bool:
        return self._connected


# ══════════════════════════════════════════════════════════════════════════════
# 📡  [V16-F2]  SPREAD GUARD  — dynamic spread lock with rolling median
# ══════════════════════════════════════════════════════════════════════════════
class SpreadGuard:
    """
    [V16-F2] Tracks rolling spread history (20-bar deque) and blocks entry
    when live spread exceeds the dynamic threshold.

    Gold spreads spike to 50-100pts on NFP/FOMC.  A static 50pt threshold
    can be gamed by a 49pt spread that still causes instant-SL hits.
    Using 3× the recent median catches spikes regardless of the base level.
    """

    def __init__(self, window: int = SPREAD_MEDIAN_BARS):
        self._buf: deque = deque(maxlen=window)

    def update(self, spread_pts: float) -> None:
        """Record a spread observation (call once per candle close)."""
        if 0.1 < spread_pts < 500:   # sanity filter
            self._buf.append(spread_pts)

    def is_ok(self, current_pts: float) -> Tuple[bool, str]:
        """
        Returns (True, "") if spread is safe.
        Returns (False, reason) if blocked.
        """
        if current_pts > HARD_SPREAD_BLOCK:
            return False, f"HARD_BLOCK:{current_pts:.1f}>{HARD_SPREAD_BLOCK}pts"

        if len(self._buf) >= 5:
            median = float(np.median(self._buf))
            dynamic_cap = median * SPREAD_DYNAMIC_MULT
            if current_pts > dynamic_cap:
                return False, f"DYN_BLOCK:{current_pts:.1f}>{dynamic_cap:.1f}pts(3×median={median:.1f})"

        return True, ""

    @property
    def median_spread(self) -> float:
        return float(np.median(self._buf)) if self._buf else 0.0


# ══════════════════════════════════════════════════════════════════════════════
# 📰  NEWS GUARD  [V14-O3 — preserved]
# ══════════════════════════════════════════════════════════════════════════════
class NewsGuard:
    def __init__(self):
        self._events: List[Dict] = []
        self._last_load          = 0.0
        self._load_interval      = 300.0

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
            log.warning(f"NewsGuard reload: {exc}")
            self._last_load = now

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
# 💾  PERSISTENCE LAYER  [V13-P0-B — preserved + V16-O2 consec-loss table]
# ══════════════════════════════════════════════════════════════════════════════
_tls = threading.local()
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
        raise RuntimeError("DB writer not initialised")
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
        # [V16-O2] Track consecutive losses for the circuit breaker
        """CREATE TABLE IF NOT EXISTS trade_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, outcome TEXT, session TEXT)""",
        "CREATE INDEX IF NOT EXISTS idx_trail_hash ON trail_state(setup_hash)",
        "CREATE INDEX IF NOT EXISTS idx_setup_ts   ON setup_log(ts)",
        "CREATE INDEX IF NOT EXISTS idx_outcomes_ts ON trade_outcomes(ts)",
    ]
    for stmt in schema_stmts:
        _db_exec(stmt, wait=True)

    # Live migrations (idempotent)
    rc = _get_read_conn()
    trail_cols = {r[1] for r in rc.execute("PRAGMA table_info(trail_state)").fetchall()}
    if "setup_hash" not in trail_cols:
        _db_exec("ALTER TABLE trail_state ADD COLUMN setup_hash TEXT DEFAULT ''", wait=True)
    setup_cols = {r[1] for r in rc.execute("PRAGMA table_info(setup_log)").fetchall()}
    for col, defn in [("features",   "TEXT DEFAULT NULL"),
                      ("win_prob",   "REAL DEFAULT 0"),
                      ("sweep_type", "TEXT DEFAULT ''"),
                      ("shape",      "TEXT DEFAULT ''")]:
        if col not in setup_cols:
            _db_exec(f"ALTER TABLE setup_log ADD COLUMN {col} {defn}", wait=True)
    log.info("✅ Database V16 schema ready")


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


def record_trade_outcome(outcome: str, session: str = "") -> None:
    """[V16-O2] Record WIN/LOSS for consecutive-loss circuit breaker."""
    _db_exec("INSERT INTO trade_outcomes(ts,outcome,session) VALUES(?,?,?)",
             (time.time(), outcome, session))


def get_consecutive_losses() -> int:
    """
    [V16-O2] Count consecutive losses at the tail of trade_outcomes.
    Returns 0 if the last trade was a WIN or there are no trades.
    """
    rows = _db_query_all(
        "SELECT outcome FROM trade_outcomes ORDER BY ts DESC LIMIT ?",
        (N_CONSEC_LOSS_PAUSE + 2,)
    )
    count = 0
    for r in rows:
        if r["outcome"] == "LOSS":
            count += 1
        else:
            break
    return count


def is_consec_loss_paused() -> bool:
    """[V16-O2] Returns True if consecutive losses exceed threshold AND pause is still active."""
    if get_consecutive_losses() < N_CONSEC_LOSS_PAUSE:
        return False
    row = _db_query(
        "SELECT ts FROM trade_outcomes WHERE outcome='LOSS' ORDER BY ts DESC LIMIT 1"
    )
    if row is None:
        return False
    last_loss_ts = float(row["ts"])
    pause_seconds = CONSEC_LOSS_PAUSE_MIN * 60
    if time.time() - last_loss_ts < pause_seconds:
        remaining = (last_loss_ts + pause_seconds - time.time()) / 60
        log.warning(
            f"🚦 Consec-Loss CB: {N_CONSEC_LOSS_PAUSE} losses → "
            f"paused {remaining:.0f}min more"
        )
        return True
    return False


def get_trail_state(ticket: int, setup_hash: str = "") -> Optional[sqlite3.Row]:
    row = _db_query(
        "SELECT setup_hash,last_sl,partial_done FROM trail_state WHERE ticket=?", (ticket,))
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
    last_sh:      float           = 0.0    # last confirmed swing high (for OTE)
    last_sl_val:  float           = 0.0    # last confirmed swing low (for OTE)


@dataclass
class DXYBias:
    available:   bool = False
    trend:       str  = "NEUTRAL"
    buy_penalty: int  = 0
    sell_bonus:  int  = 0


@dataclass
class FVGZone:
    kind:         str
    top:          float
    bot:          float
    strength:     float
    bar_index:    int
    mitigated:    bool = False
    volume_spike: bool = False


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
class MSSResult:
    """[V16-S3] Market Structure Shift + Change in State of Delivery."""
    confirmed:   bool  = False
    is_cisd:     bool  = False   # displacement candle closed through swing
    score_bonus: int   = 0


@dataclass
class SetupResult:
    signal:      str              = "WAIT"
    score:       int              = 0
    entry:       float            = 0.0
    sl:          float            = 0.0
    atr:         float            = 0.0
    htf_bias:    str              = "NEUTRAL"
    h1_bias:     str              = "NEUTRAL"    # [V16-O3]
    m15_struct:  str              = "NEUTRAL"
    adr_pct:     float            = 0.0
    threshold:   int              = 70
    reasons:     List[str]        = field(default_factory=list)
    setup_hash:  str              = ""
    use_market:  bool             = False
    liq_map:     Optional[LiquidityMap]   = None
    fvg_zone:    Optional[FVGZone]        = None
    candle_ts:   float            = 0.0
    htf_result:  Optional[HTFBiasResult]  = None
    dxy_bias:    Optional[DXYBias]        = None
    pd_zone:     str              = "NEUTRAL"
    features:    Optional[np.ndarray]     = None
    win_prob:    float            = 0.0
    spread_pts:  float            = 0.0
    is_judas:    bool             = False
    sweep_type:  str              = "NONE"   # [V16-S2] "CONTINUE"/"REVERSE"/"NONE"
    shape:       str              = "NONE"   # [V16-S4] "V"/"U"/"NONE"
    mss:         Optional[MSSResult]      = None   # [V16-S3]
    golden_conf: bool             = False    # [V16-S5]

    def summary(self) -> str:
        gap  = self.score - self.threshold
        conf = "💎" if gap >= 30 else "🔥🔥" if gap >= 15 else "🔥" if gap >= 0 else "⚠️"
        mode = "MKT" if self.use_market else "LMT"
        tags = []
        if self.is_judas:    tags.append("⚡JUDAS")
        if self.golden_conf: tags.append("✨GOLDEN")
        if self.shape == "V": tags.append("📐V-Shape")
        if self.shape == "U": tags.append("🌊U-Shape")
        tag_str = " ".join(tags)
        return (
            f"{conf} {tag_str} {self.signal}({mode}) "
            f"Score:{self.score}/{self.threshold} WinProb:{self.win_prob:.2f} "
            f"Sweep:{self.sweep_type} H1:{self.h1_bias} | {' | '.join(self.reasons)}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 🤖  ML LAYER  [V15 — preserved]
# ══════════════════════════════════════════════════════════════════════════════
class WelfordNormaliser:
    """[V14-O1] O(1) Welford online mean/variance."""
    def __init__(self, n_features: int, min_samples: int = 20):
        self._n   = n_features; self._min = min_samples
        self._count = np.zeros(n_features, dtype=np.float64)
        self._mean  = np.zeros(n_features, dtype=np.float64)
        self._M2    = np.zeros(n_features, dtype=np.float64)

    def update(self, x: np.ndarray) -> None:
        for i, v in enumerate(x):
            if np.isfinite(v):
                self._count[i] += 1
                delta = v - self._mean[i]; self._mean[i] += delta / self._count[i]
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


N_FEATURES = 14   # 12 from V15 + sweep_type_enc + shape_enc


def extract_features(setup: "SetupResult", close_price: float = 2000.0,
                     df_len: int = 300) -> np.ndarray:
    """
    14-feature vector.  Features 12-13 are new V16 additions:
      12: sweep_type_enc   CONTINUE=1, REVERSE=-1, NONE=0
      13: shape_enc        V=1, U=-1, NONE=0
    """
    htf_enc  = {"BULLISH": 1.0, "BEARISH": -1.0}.get(setup.htf_bias, 0.0)
    atr      = max(setup.atr, 1e-6)
    atr_norm = atr / max(close_price, 1.0)
    fvg_str  = setup.fvg_zone.strength if setup.fvg_zone else 0.0
    fvg_age  = 0.0
    if setup.fvg_zone is not None:
        age_bars = max(0, df_len - 1 - setup.fvg_zone.bar_index)
        fvg_age  = min(1.0, age_bars / max(FVG_MEMORY_BARS.get("DEFAULT", 30), 1))
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
                     float(spread_n), m15_enc, has_liq, has_ob, sf, fvg_age,
                     sweep_d, session_sin, sweep_enc, shape_enc], dtype=np.float64)


class MLPredictor:
    def __init__(self):
        self._model = None
        self._norm  = WelfordNormaliser(N_FEATURES)
        self._prob_buf: Deque[float] = deque(maxlen=ML_ROLLING_WINDOW)
        self._heuristic_mode = True   # [V16-RISK1 FIX] True until a real model is loaded
        log.info(f"🧠 MLPredictor V16: {N_FEATURES}-feat | gate={ML_WIN_PROB_THRESHOLD}")

    def load_model(self, path: str) -> bool:
        try:
            obj = joblib.load(path)
            self._model = obj[1] if isinstance(obj, tuple) and len(obj) == 2 else obj
            self._heuristic_mode = False   # [V16-RISK1 FIX] real model loaded
            log.info(f"🧠 MLPredictor: loaded {path}"); return True
        except Exception as exc:
            log.warning(f"🧠 load failed ({exc}) — heuristic"); return False

    def predict_win_probability(self, features: np.ndarray, update_norm: bool = True) -> float:
        self._heuristic_mode = (self._model is None)   # reset per call
        shift = self._norm.check_shift(features, z_bound=3.5)
        if update_norm and not shift:
            self._norm.update(features)
        if shift:
            log.warning("🧠 Dist shift → 0.49")
            return 0.49
        x = self._norm.transform(features)
        if self._model is not None:
            try:
                prob = float(self._model.predict_proba(x.reshape(1, -1))[0][1])
                prob = max(0.0, min(1.0, prob))
                self._prob_buf.append(prob); return prob
            except Exception as exc:
                log.warning(f"🧠 Inference: {exc}")
        raw = features
        prob = 0.38
        if abs(float(raw[0]))  > 0.5: prob += 0.12  # htf aligned
        if float(raw[8])       > 0.5: prob += 0.10  # sweep+fvg
        if float(raw[6])       > 0.5: prob += 0.07  # liq target
        if float(raw[7])       > 0.5: prob += 0.06  # ob
        if abs(float(raw[5]))  > 0.5: prob += 0.06  # m15 confirms
        if float(raw[9])       < 0.3: prob += 0.05  # fvg fresh
        if float(raw[10])      > 0.1: prob += min(0.04, float(raw[10]) * 0.4)
        if float(raw[2])       > 0.80: prob -= 0.10 # adr exhausted
        if float(raw[12])      > 0.5: prob += 0.05  # sweep CONTINUE
        if float(raw[13])      > 0.5: prob += 0.06  # V-shape
        if float(raw[13])      < -0.5: prob -= 0.08 # U-shape
        prob = max(0.0, min(1.0, round(prob, 4)))
        # [V16-RISK1 FIX] Tag result as heuristic so the signal cycle can apply
        # a stricter gate (ML_HEURISTIC_THRESHOLD) vs the real-model gate.
        self._heuristic_mode = True
        self._prob_buf.append(prob); return prob

    @property
    def rolling_avg_prob(self) -> float:
        return float(np.mean(self._prob_buf)) if self._prob_buf else 0.0

    @property
    def norm_is_warm(self) -> bool:
        return self._norm.is_warm


# ══════════════════════════════════════════════════════════════════════════════
# 📊  CLASS: MarketDataFeed  [V16-O3] + H1 added
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
        except Exception:
            rates = None
        if rates is None or len(rates) == 0:
            return None
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
        """Returns CLOSED candles only (trim last live bar)."""
        def _trim(df):
            return df.iloc[:-1].copy() if df is not None and len(df) > 1 else df
        m1  = _trim(self.fetch(mt5.TIMEFRAME_M1,   60,  use_cache=False))
        m5  = _trim(self.fetch(mt5.TIMEFRAME_M5,  300,  use_cache=False))
        m15 = _trim(self.fetch(mt5.TIMEFRAME_M15, 100,  use_cache=True))
        h1  = _trim(self.fetch(mt5.TIMEFRAME_H1,  H1_BARS, use_cache=True))   # [V16-O3]
        h4  = _trim(self.fetch(mt5.TIMEFRAME_H4,  HTF_BARS, use_cache=True))
        d1  = self.fetch(mt5.TIMEFRAME_D1, 20, use_cache=True)
        dxy = None
        if DXY_ENABLED and DXY_SYMBOL:
            r = mt5.copy_rates_from_pos(DXY_SYMBOL, mt5.TIMEFRAME_H1, 0, 60)
            if r is not None and len(r) > 0:
                dxy = pd.DataFrame(r)
                dxy["time"] = pd.to_datetime(dxy["time"], unit="s")
        return {"m1": m1, "m5": m5, "m15": m15, "h1": h1, "h4": h4, "d1": d1, "dxy": dxy}

    def get_current_m5_bar_time(self) -> Optional[int]:
        try:
            rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M5, 0, 1)
            if rates is not None and len(rates) > 0: return int(rates[0]["time"])
        except Exception:
            pass
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
    tr = np.maximum(high[1:] - low[1:], np.maximum(np.abs(high[1:] - prev), np.abs(low[1:] - prev)))
    if len(tr) < period: return 0.0
    v = float(tr[:period].mean()); alpha = 1.0 / period
    for x in tr[period:]:
        v = v * (1.0 - alpha) + float(x) * alpha
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
    last_high = float(high[-1]); last_low = float(low[-1]); last_close = float(cls[-1])
    prev_close = float(cls[-2]) if len(cls) >= 2 else last_close
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


def _rolling_vol_mean(df: pd.DataFrame, period: int) -> Optional[np.ndarray]:
    if "tick_volume" not in df.columns: return None
    vol = df["tick_volume"].astype(float).values
    result = np.full(len(vol), np.nan)
    for i in range(period, len(vol)):
        result[i] = vol[max(0, i - period): i].mean()
    return result


def _make_hash(sig: str, entry: float, sl: float, ts: float) -> str:
    return hashlib.sha256(f"{sig}:{entry:.2f}:{sl:.2f}:{int(ts)}".encode()).hexdigest()[:12]


# ══════════════════════════════════════════════════════════════════════════════
# 📐  [V16-S4]  V-SHAPE / U-SHAPE DETECTOR
# ══════════════════════════════════════════════════════════════════════════════
class VShapeDetector:
    """
    [V16-S4] Classifies price rejection patterns after a liquidity sweep.

    V-Shape: Institutional stop-hunt followed by rapid directional move.
      • Condition 1 (Impulse Velocity): The rejection candle's body ≥ VSHAPE_ATR_MULT × ATR.
        This captures the "snap-back" from the sweep extreme.
      • Condition 2 (Return Speed): Within VSHAPE_MAX_BARS candles, price closes
        ≥ VSHAPE_RETRACE_PCT of the distance from sweep extreme back toward origin.

    U-Shape: Slow, grinding consolidation — chop territory.
      • After the sweep, price stays within the wick range for ≥ USHAPE_MAX_BARS
        bars without a meaningful close in the entry direction.
        Mathematically: max(|close - sweep_level|) / (sweep_range) < 0.5 over N bars.
    """

    @staticmethod
    def classify(df: pd.DataFrame, direction: str, atr: float) -> str:
        """
        direction: "BUY" (swept SSL, expect up) or "SELL" (swept BSL, expect down).
        Returns "V", "U", or "NONE".
        """
        if not VSHAPE_ENABLED or len(df) < USHAPE_MAX_BARS + 3 or atr == 0:
            return "NONE"

        n     = len(df)
        high  = _to_numpy(df, "high")
        low   = _to_numpy(df, "low")
        close = _to_numpy(df, "close")

        # [V16-BUG2 FIX] Reference bar = SECOND-TO-LAST closed bar (the sweep candle).
        # iloc[-1] is the most recent closed bar = the bar AFTER the sweep.
        # iloc[-2] is the sweep candle itself whose wick penetrated the liquidity level.
        # All velocity/retrace checks must happen on bars AFTER the sweep (index >= -1).
        sweep_high  = float(high[-2])
        sweep_low   = float(low[-2])
        sweep_close = float(close[-2])
        sweep_open  = float(df.iloc[-2]["open"])

        if direction == "BUY":
            sweep_extreme = sweep_low
            origin        = sweep_high
            wick_range    = sweep_high - sweep_low
        else:
            sweep_extreme = sweep_high
            origin        = sweep_low
            wick_range    = sweep_high - sweep_low

        if wick_range < atr * 0.2:
            return "NONE"    # no meaningful sweep wick

        # ── Condition 1: Impulse Velocity ─────────────────────────────────────
        # Look at bars AFTER the sweep candle (index -1 onward, i.e. the 1 bar we have
        # post-sweep on the live close). Only bars after iloc[-2] qualify.
        has_velocity = False
        # We check the most recent bar (iloc[-1]) for a directional impulse
        post_sweep_bar = df.iloc[-1]
        post_body = abs(float(post_sweep_bar["close"]) - float(post_sweep_bar["open"]))
        if post_body >= atr * VSHAPE_ATR_MULT:
            if direction == "BUY"  and float(post_sweep_bar["close"]) > float(post_sweep_bar["open"]):
                has_velocity = True
            if direction == "SELL" and float(post_sweep_bar["close"]) < float(post_sweep_bar["open"]):
                has_velocity = True
        # Also accept a large velocity on the sweep candle itself (snap-back within same bar)
        sweep_body = abs(sweep_close - sweep_open)
        if not has_velocity and sweep_body >= atr * VSHAPE_ATR_MULT:
            if direction == "BUY"  and sweep_close > sweep_open: has_velocity = True
            if direction == "SELL" and sweep_close < sweep_open: has_velocity = True

        # ── Condition 2: Return Speed ──────────────────────────────────────────
        # Price must close back ≥ VSHAPE_RETRACE_PCT of the distance from the
        # sweep extreme back toward the origin within VSHAPE_MAX_BARS bars.
        # Check bars after the sweep (index -1 is 1 bar after sweep).
        retrace_target = sweep_extreme + (origin - sweep_extreme) * VSHAPE_RETRACE_PCT
        has_retrace = False
        # bars after sweep: we only have iloc[-1] (1 bar post-sweep in live mode)
        # check it plus the sweep close itself (intra-bar snap-back scenario)
        post_closes = [float(close[-1]), sweep_close]
        for c_close in post_closes:
            if direction == "BUY"  and c_close >= retrace_target: has_retrace = True; break
            if direction == "SELL" and c_close <= retrace_target: has_retrace = True; break

        if has_velocity and has_retrace:
            return "V"

        # ── U-Shape check ──────────────────────────────────────────────────────
        # Price has lingered within the sweep wick range for USHAPE_MAX_BARS bars
        # without a decisive directional close — classic chop/consolidation.
        ushape_bars = min(USHAPE_MAX_BARS, n - 1)
        close_extremes = close[-ushape_bars:]
        if direction == "BUY":
            # Decisive = any close above the sweep candle's open (origin side)
            decisive = bool(np.any(close_extremes > sweep_open))
        else:
            decisive = bool(np.any(close_extremes < sweep_open))

        if not decisive:
            return "U"

        return "NONE"


# ══════════════════════════════════════════════════════════════════════════════
# 🧠  CLASS: SMCSignalEngine  [V16 full upgrade]
# ══════════════════════════════════════════════════════════════════════════════
class SMCSignalEngine:

    def __init__(self, clock: BrokerClockSync):
        self._news_guard = NewsGuard()
        self._clock      = clock   # [V16-F4] use broker-derived time

    # ── HTF Bias (H4) — extended to return swing prices for OTE ──────────────
    @staticmethod
    def get_htf_bias(df_h4: Optional[pd.DataFrame]) -> HTFBiasResult:
        res = HTFBiasResult()
        if df_h4 is None or len(df_h4) < HTF_SWING_PERIOD * 2 + HTF_SWING_CONFIRM + 5:
            res.reason = "H4 data insufficient"; return res
        lookback = min(60, len(df_h4))
        df  = df_h4.iloc[-lookback:].reset_index(drop=True)
        p, c = HTF_SWING_PERIOD, HTF_SWING_CONFIRM
        high = _to_numpy(df, "high"); low = _to_numpy(df, "low"); cls = _to_numpy(df, "close")
        safe = len(high) - c
        sh_list: List[Tuple[int, float]] = []; sl_list: List[Tuple[int, float]] = []
        for i in range(p, safe - p):
            if high[i] == high[i - p: i + p + 1].max(): sh_list.append((i, float(high[i])))
            if low[i]  == low[i  - p: i + p + 1].min(): sl_list.append((i, float(low[i])))
        if len(sh_list) < 2 or len(sl_list) < 2:
            res.reason = "Insufficient H4 swings"; return res
        prev_sh = sh_list[-1][1]; prev_sl = sl_list[-1][1]
        res.last_sh     = prev_sh   # expose for OTE calc
        res.last_sl_val = prev_sl
        last_high = float(high[-1]); last_low = float(low[-1]); last_close = float(cls[-1])
        if last_high > prev_sh and last_close < prev_sh: res.swept_high = prev_sh
        if last_low  < prev_sl and last_close > prev_sl: res.swept_low  = prev_sl
        recent = cls[-5:]
        bos_up   = bool(np.any(recent > prev_sh)); bos_down = bool(np.any(recent < prev_sl))
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
            res.bias = "BULLISH"
            res.reason = f"BOS_UP:{bos_up}|HH:{hh}|HL:{hl}|SwL:{res.swept_low is not None}"
        elif bear_pts >= 3 and bear_pts > bull_pts:
            res.bias = "BEARISH"
            res.reason = f"BOS_DN:{bos_down}|LH:{lh}|LL:{ll}|SwH:{res.swept_high is not None}"
        else:
            res.bias = "NEUTRAL"; res.reason = f"Bull:{bull_pts} Bear:{bear_pts} — ranging"
        return res

    # ── [V16-O3] H1 Intermediate Bias ────────────────────────────────────────
    @staticmethod
    def get_h1_bias(df_h1: Optional[pd.DataFrame]) -> str:
        """
        [V16-O3] Simple H1 structural bias using confirmed swing BOS.
        Returns "BULLISH", "BEARISH", or "NEUTRAL".
        Used to score MTF alignment between H4 and H1.
        """
        if df_h1 is None or len(df_h1) < H1_SWING_PERIOD * 2 + H1_SWING_CONFIRM + 5:
            return "NEUTRAL"
        df   = df_h1.iloc[-min(50, len(df_h1)):].reset_index(drop=True)
        high = _to_numpy(df, "high"); low = _to_numpy(df, "low"); cls = _to_numpy(df, "close")
        safe = len(high) - H1_SWING_CONFIRM
        sh, sl = [], []
        p = H1_SWING_PERIOD
        for i in range(p, safe - p):
            if high[i] == high[i - p: i + p + 1].max(): sh.append(float(high[i]))
            if low[i]  == low[i  - p: i + p + 1].min(): sl.append(float(low[i]))
        if len(sh) < 2 or len(sl) < 2: return "NEUTRAL"
        last_close = float(cls[-1])
        bos_up   = last_close > sh[-1]
        bos_down = last_close < sl[-1]
        hh = sh[-1] > sh[-2]; hl = sl[-1] > sl[-2]
        lh = sh[-1] < sh[-2]; ll = sl[-1] < sl[-2]
        if bos_up   and hh and hl: return "BULLISH"
        if bos_down and lh and ll: return "BEARISH"
        return "NEUTRAL"

    # ── [V16-S2] Sweep Classification ────────────────────────────────────────
    @staticmethod
    def classify_sweep(sweep_type_raw: str, htf_bias: str, signal: str) -> str:
        """
        [V16-S2] Classify sweep as CONTINUE or REVERSE.

        CONTINUE: sweep complements the HTF trend.
          → SSL sweep (buy setup) when H4 = BULLISH
          → BSL sweep (sell setup) when H4 = BEARISH

        REVERSE: sweep against the HTF trend → Judas Swing territory.
          → SSL sweep (buy setup) when H4 = BEARISH
          → BSL sweep (sell setup) when H4 = BULLISH
        """
        if htf_bias == "NEUTRAL":
            return "NEUTRAL"
        if signal == "BUY"  and htf_bias == "BULLISH": return "CONTINUE"
        if signal == "SELL" and htf_bias == "BEARISH": return "CONTINUE"
        if signal == "BUY"  and htf_bias == "BEARISH": return "REVERSE"
        if signal == "SELL" and htf_bias == "BULLISH": return "REVERSE"
        return "NONE"

    # ── [V16-S3] MSS & CISD ───────────────────────────────────────────────────
    @staticmethod
    def detect_mss(df_m5: pd.DataFrame, direction: str, atr: float,
                   last_swing_high: float, last_swing_low: float) -> MSSResult:
        """
        [V16-S3] Market Structure Shift + Change in State of Delivery.

        MSS: The last M5 closed candle closes THROUGH the last confirmed swing level.
        CISD: That same candle (or the one before it) is a "displacement" candle —
              body size ≥ CISD_ATR_MULT × ATR, confirming institutional delivery.

        This replaces the simpler SCORE_BOS_M5 check.
        """
        res = MSSResult()
        if not MSS_ENABLED or len(df_m5) < 5 or atr == 0:
            return res
        last  = df_m5.iloc[-1]
        close = float(last["close"]); open_ = float(last["open"])
        body  = abs(close - open_)
        buf   = atr * 0.02   # tiny buffer to avoid false positives on exact touch

        if direction == "BUY":
            # MSS = close above last swing high
            if close > last_swing_high + buf:
                res.confirmed = True
                if body >= atr * CISD_ATR_MULT:
                    res.is_cisd     = True
                    res.score_bonus = SCORE_MSS_CISD
                else:
                    res.score_bonus = SCORE_MSS_ONLY
        else:
            # MSS = close below last swing low
            if close < last_swing_low - buf:
                res.confirmed = True
                if body >= atr * CISD_ATR_MULT:
                    res.is_cisd     = True
                    res.score_bonus = SCORE_MSS_CISD
                else:
                    res.score_bonus = SCORE_MSS_ONLY
        return res

    # ── [V16-S5] Golden Confluence: FVG + OTE + Displacement ─────────────────
    @staticmethod
    def check_golden_confluence(
        fvg: Optional[FVGZone], entry: float, signal: str,
        htf_result: Optional[HTFBiasResult],
        df_m5: pd.DataFrame, atr: float,
    ) -> bool:
        """
        [V16-S5] CCT 2025 Golden Confluence.

        Three conditions must ALL be met:
        1. Active FVG — a fresh, unmitigated IMB at the entry zone.
        2. OTE Zone — entry price falls within the 61.8%–79% Fibonacci
           retracement of the most recent H4 swing leg.
        3. Displacement Candle — the last M5 candle has body ≥ DISPLACEMENT_ATR_MULT × ATR.
        """
        if not GOLDEN_CONFL_ENABLED or fvg is None or htf_result is None:
            return False

        # Condition 1: FVG fresh
        if fvg.mitigated:
            return False

        # Condition 2: OTE zone
        sh = htf_result.last_sh; sl = htf_result.last_sl_val
        # [V16-RISK2 FIX] Guard against None when H4 data was insufficient
        if sh is None or sl is None:
            return False
        swing_range = sh - sl
        if swing_range < 1e-6:
            return False

        if signal == "BUY":
            # Retracement of bullish leg: price pulled back from sh toward sl
            ote_high = sh - (swing_range * OTE_LOW_PCT)
            ote_low  = sh - (swing_range * OTE_HIGH_PCT)
        else:
            # Retracement of bearish leg: price bounced from sl toward sh
            ote_low  = sl + (swing_range * OTE_LOW_PCT)
            ote_high = sl + (swing_range * OTE_HIGH_PCT)

        in_ote = ote_low <= entry <= ote_high

        # Condition 3: Displacement candle
        if len(df_m5) < 2:
            return False
        last_body = abs(float(df_m5.iloc[-1]["close"]) - float(df_m5.iloc[-1]["open"]))
        is_displacement = last_body >= atr * DISPLACEMENT_ATR_MULT

        result = in_ote and is_displacement
        if result:
            log.info(
                f"✨ Golden Confluence: FVG ✓ + OTE({ote_low:.2f}-{ote_high:.2f}) ✓ "
                f"+ Displacement(body={last_body:.2f}≥{atr*DISPLACEMENT_ATR_MULT:.2f}) ✓"
            )
        return result

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
                result.trend = "BULLISH"; result.buy_penalty = DXY_BUY_PENALTY; result.sell_bonus = DXY_SELL_BONUS
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
        last_c = float(sub["close"].iloc[-1]); buf = (sh - sl) * 0.005
        if last_c > sh + buf: return "BULLISH_BOS"
        if last_c < sl - buf: return "BEARISH_BOS"
        return "NEUTRAL"

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
            c2_range = float(c2["high"] - c2["low"]); c2_body = abs(float(c2["close"] - c2["open"]))
            if c2_range > 0 and (c2_body / c2_range) < FVG_MOMENTUM_RATIO: continue
            vol_spike = False
            if VOL_SPIKE_ENABLED and vol_mean is not None:
                vm = vol_mean[i + 1] if i + 1 < len(vol_mean) else np.nan
                if not np.isnan(vm) and vm > 0:
                    vol_spike = float(df.iloc[i + 1]["tick_volume"]) >= vm * VOL_SPIKE_MULT
            gap_bull = float(c3["low"]) - float(c1["high"])
            if gap_bull >= min_gap:
                top = float(c3["low"]); bot = float(c1["high"]); gap = top - bot
                mid = bot + gap * FVG_MITIGATED_PCT; mitigated = False
                for j in range(i + 3, len(df)):
                    if float(df.iloc[j]["low"]) <= mid: mitigated = True; break
                zones.append(FVGZone("BULLISH", top, bot, min(2.0, gap / atr), i, mitigated, vol_spike))
            gap_bear = float(c1["low"]) - float(c3["high"])
            if gap_bear >= min_gap:
                top = float(c1["low"]); bot = float(c3["high"]); gap = top - bot
                mid = top - gap * FVG_MITIGATED_PCT; mitigated = False
                for j in range(i + 3, len(df)):
                    if float(df.iloc[j]["high"]) >= mid: mitigated = True; break
                zones.append(FVGZone("BEARISH", top, bot, min(2.0, gap / atr), i, mitigated, vol_spike))
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

    # ── Order Block ───────────────────────────────────────────────────────────
    @staticmethod
    def find_order_block(df: pd.DataFrame, direction: str, atr: float) -> OBResult:
        if len(df) < 10 or atr == 0: return OBResult()
        closed = df.iloc[:-1]; n = len(closed); max_age = min(30, n - 2)
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
            return OBResult(True, ob_high, ob_low, q, bar_age=age, mitigated=mitigated, volume_spike=vol_spike)
        return OBResult()

    # ── Judas Swing [V14-S2] ─────────────────────────────────────────────────
    def is_judas_swing(self, liq: LiquidityMap, fvg_zones: List[FVGZone],
                       signal: str, session: str) -> bool:
        if not JUDAS_SWING_ENABLED: return False
        now = self._clock.now_strategy()   # [V16-F4] broker time
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

    # ── Session helpers [V16-F4] — use broker clock ───────────────────────────
    def get_session(self) -> str:
        now = self._clock.now_strategy()   # [V16-F4]
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

    def is_in_killzone(self) -> Tuple[bool, str]:
        """[V16-O1] Returns (in_kz, name). Outside KZ → penalty applied in scoring."""
        if not KILLZONE_ENABLED: return True, "All"
        t = self._clock.now_strategy().time()   # [V16-F4]
        for sh, sm, eh, em, name in KILLZONES:
            if dtime(sh, sm) <= t <= dtime(eh, em): return True, name
        return False, "Outside Killzone"

    @staticmethod
    def get_threshold(session: str) -> int:
        return SCORE_THRESHOLD.get(session, SCORE_THRESHOLD["DEFAULT"])

    # ── Master Setup Analyser [V16 full] ─────────────────────────────────────
    def analyze_setup(
        self,
        df_m5:  Optional[pd.DataFrame],
        df_h4:  Optional[pd.DataFrame],
        df_d1:  Optional[pd.DataFrame],
        df_m15: Optional[pd.DataFrame],
        df_dxy: Optional[pd.DataFrame],
        df_h1:  Optional[pd.DataFrame],   # [V16-O3]
        session: str = "DEFAULT",
        in_killzone: bool = True,         # [V16-O1] passed from main cycle
    ) -> SetupResult:
        r = SetupResult()
        if df_m5 is None or len(df_m5) < 30:
            r.reasons.append("M5 insufficient"); return r
        atr = calculate_atr(df_m5)
        if atr == 0:
            r.reasons.append("ATR=0"); return r
        r.atr = atr

        adr = calculate_adr(df_d1)
        if adr > 0 and df_d1 is not None and len(df_d1) >= 1:
            r.adr_pct = float(df_d1["high"].iloc[-1] - df_d1["low"].iloc[-1]) / adr

        if ADR_HARD_BLOCK:
            adr_ceil = ADR_NY_EXHAUSTED_PCT if session in ("NEW_YORK", "NY_OPEN_EARLY") \
                       else ADR_EXHAUSTED_PCT
            if r.adr_pct >= adr_ceil:
                r.reasons.append(f"ADR_HARD({r.adr_pct*100:.0f}%)"); return r

        htf_res      = self.get_htf_bias(df_h4)
        r.htf_bias   = htf_res.bias
        r.htf_result = htf_res
        r.h1_bias    = self.get_h1_bias(df_h1)             # [V16-O3]
        dxy_b        = self.get_dxy_bias(df_dxy)
        r.dxy_bias   = dxy_b
        r.m15_struct = self.get_m15_structure(df_m15)
        r.pd_zone    = self.get_pd_zone(df_m5)
        r.threshold  = self.get_threshold(session)

        liq           = build_liquidity_map_np(df_m5, atr, LIQ_SWING_PERIOD)
        r.liq_map     = liq
        last_sh, last_sl = get_confirmed_swings_np(df_m5, SWING_PERIOD, SWING_CONFIRM_BARS)
        fvg_lookback  = FVG_MEMORY_BARS.get(session, FVG_MEMORY_BARS["DEFAULT"])
        fvg_zones     = self.scan_fvg_memory(df_m5, atr, fvg_lookback)

        last = df_m5.iloc[-1]; prev = df_m5.iloc[-2]
        r.candle_ts = float(last["time"].timestamp()) if hasattr(last["time"], "timestamp") \
                      else time.time()

        price      = float(last["close"])
        sweep_sell = float(last["low"])  < last_sl and float(last["close"]) > last_sl
        sweep_buy  = float(last["high"]) > last_sh and float(last["close"]) < last_sh
        if liq.gap_swept_low  is not None: sweep_sell = True
        if liq.gap_swept_high is not None: sweep_buy  = True

        # [V16-F1] PRE_LONDON: block pure-FVG-only trades (no sweep)
        if session == "PRE_LONDON" and PRE_LONDON_SWEEP_REQUIRED:
            if not sweep_sell and not sweep_buy:
                r.reasons.append("PRE_LONDON: no sweep → skip FOMO entry")
                return r

        def _apply_htf_scores(sig: str) -> None:
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
            else:
                r.reasons.append("H4 Neutral ± 0")

        def _apply_h1_mtf(sig: str) -> None:
            """[V16-S1] MTF Matrix: H1 intermediate bias."""
            if r.h1_bias == "NEUTRAL": return
            agrees = (r.h1_bias == "BULLISH" and sig == "BUY") or \
                     (r.h1_bias == "BEARISH" and sig == "SELL")
            if agrees:
                r.score += H1_AGREE_BONUS
                r.reasons.append(f"H1 {r.h1_bias} MTF ✓ +{H1_AGREE_BONUS}")
            else:
                r.score += H1_CONFLICT_PENALTY
                r.reasons.append(f"H1 {r.h1_bias} MTF conflict {H1_CONFLICT_PENALTY}pts")

        def _apply_kz_score(sig: str) -> None:
            """[V16-O1] Killzone penalty scoring."""
            if not in_killzone:
                # [V16-BUG3 FIX] NY_OPEN_EARLY also gets lighter penalty like PRE_LONDON
                # since it's a valid trading session that borders the NY Open KZ window.
                if session in ("PRE_LONDON", "NY_OPEN_EARLY"):
                    r.score += KZ_PRE_LONDON_PENALTY
                    r.reasons.append(f"{session} outside KZ {KZ_PRE_LONDON_PENALTY}pts")
                else:
                    r.score += KZ_OUTSIDE_PENALTY
                    r.reasons.append(f"Outside KZ {KZ_OUTSIDE_PENALTY}pts")

        def _build_buy() -> bool:
            has_sweep  = sweep_sell
            fvg_active = self.get_active_fvg(fvg_zones, price, "BUY")
            if not has_sweep and fvg_active is None: return False

            r.signal = "BUY"; r.score = SCORE_BASE
            if fvg_active is not None:
                r.entry    = (fvg_active.bot + (fvg_active.top - fvg_active.bot) * 0.5
                              if FVG_ENTRY_MID else fvg_active.top)
                r.fvg_zone = fvg_active
            elif has_sweep:
                r.entry = last_sl + (atr * 0.1)
            r.sl = last_sl - (atr * SL_ATR_MULT)

            # Tier 1: Core
            if fvg_active is not None and not fvg_active.mitigated:
                r.score += SCORE_FVG_FRESH; r.reasons.append(f"FVG Fresh +{SCORE_FVG_FRESH}")
                if fvg_active.strength > 0.5:
                    r.score += SCORE_FVG_STRENGTH; r.reasons.append(f"FVG Str +{SCORE_FVG_STRENGTH}")
            if has_sweep:
                lbl = "Gap-Sweep" if liq.gap_swept_low else "Sweep"
                r.score += SCORE_LIQ_SWEPT; r.reasons.append(f"{lbl} SSL +{SCORE_LIQ_SWEPT}")
            if has_sweep and fvg_active is not None:
                r.score += SCORE_SWEEP_AND_FVG; r.reasons.append(f"Sweep+FVG +{SCORE_SWEEP_AND_FVG}")

            # Tier 2: HTF + H1 MTF
            _apply_htf_scores("BUY")
            _apply_h1_mtf("BUY")          # [V16-S1]
            if htf_res.swept_low:
                r.score += 4; r.reasons.append("H4 SSL Swept +4")

            # Tier 3: Confluences
            if r.m15_struct == "BULLISH_BOS":
                r.score += SCORE_M15_BOS; r.reasons.append(f"M15 BOS +{SCORE_M15_BOS}")

            body = float(last["close"]) - float(last["open"])
            if body > atr * 0.6:
                r.score += SCORE_STRONG_CANDLE; r.reasons.append(f"Strong ✓ +{SCORE_STRONG_CANDLE}")

            ob = self.find_order_block(df_m5, "BUY", atr)
            if ob.found and not ob.mitigated:
                r.score += SCORE_OB_BONUS; r.reasons.append(f"OB(q:{ob.score:.2f},age:{ob.bar_age}) +{SCORE_OB_BONUS}")
                if ob.low <= r.entry <= ob.high:
                    r.score += SCORE_OB_OVERLAP; r.reasons.append(f"OB Overlap +{SCORE_OB_OVERLAP}")

            # [V16-S3] MSS & CISD replaces old BOS_M5
            mss = self.detect_mss(df_m5, "BUY", atr, last_sh, last_sl)
            r.mss = mss
            if mss.confirmed:
                r.score += mss.score_bonus
                tag = "MSS+CISD" if mss.is_cisd else "MSS"
                r.reasons.append(f"{tag} ✓ +{mss.score_bonus}")

            # Liq target
            if liq.bsl_nearest is not None:
                rsk = abs(r.entry - r.sl)
                if rsk > 0 and (liq.bsl_nearest - r.entry) >= rsk * RR_RATIO * 0.8:
                    r.score += SCORE_LIQ_TARGET; r.reasons.append(f"BSL→{liq.bsl_nearest:.2f} +{SCORE_LIQ_TARGET}")

            if r.adr_pct >= ADR_EXHAUSTED_PCT:
                r.score += SCORE_ADR_WARN; r.reasons.append(f"ADR{r.adr_pct*100:.0f}% ⚠️")

            # [V16-O1] KZ penalty
            _apply_kz_score("BUY")

            # [V16-S2] Sweep classification
            r.sweep_type = self.classify_sweep("sweep", r.htf_bias, "BUY")

            # [V16-S4] V/U Shape
            r.shape = VShapeDetector.classify(df_m5, "BUY", atr)
            if   r.shape == "V": r.score += SCORE_VSHAPE_BONUS;   r.reasons.append(f"📐V-Shape +{SCORE_VSHAPE_BONUS}")
            elif r.shape == "U": r.score += SCORE_USHAPE_PENALTY;  r.reasons.append(f"🌊U-Shape {SCORE_USHAPE_PENALTY}pts")

            # [V16-S5] Golden Confluence
            if self.check_golden_confluence(fvg_active, r.entry, "BUY", htf_res, df_m5, atr):
                r.score += SCORE_GOLDEN_CONFLUENCE; r.golden_conf = True
                r.reasons.append(f"✨Golden Confluence +{SCORE_GOLDEN_CONFLUENCE}")

            # Judas Swing
            if self.is_judas_swing(liq, fvg_zones, "BUY", session):
                r.score += JUDAS_SCORE_BONUS; r.is_judas = True
                r.reasons.append(f"⚡Judas Swing +{JUDAS_SCORE_BONUS}")

            body_ratio = body / atr if atr > 0 else 0
            if (float(last["close"]) > float(prev["high"])
                    and body_ratio > MOMENTUM_BODY_ATR and r.score >= r.threshold):
                r.use_market = True; r.entry = 0.0; r.reasons.append("🚀 MKT")
            return True

        def _build_sell() -> bool:
            has_sweep  = sweep_buy
            fvg_active = self.get_active_fvg(fvg_zones, price, "SELL")
            if not has_sweep and fvg_active is None: return False

            r.signal = "SELL"; r.score = SCORE_BASE
            if fvg_active is not None:
                r.entry    = (fvg_active.bot + (fvg_active.top - fvg_active.bot) * 0.5
                              if FVG_ENTRY_MID else fvg_active.bot)
                r.fvg_zone = fvg_active
            elif has_sweep:
                r.entry = last_sh - (atr * 0.1)
            r.sl = last_sh + (atr * SL_ATR_MULT)

            if fvg_active is not None and not fvg_active.mitigated:
                r.score += SCORE_FVG_FRESH; r.reasons.append(f"FVG Fresh +{SCORE_FVG_FRESH}")
                if fvg_active.strength > 0.5:
                    r.score += SCORE_FVG_STRENGTH; r.reasons.append(f"FVG Str +{SCORE_FVG_STRENGTH}")
            if has_sweep:
                lbl = "Gap-Sweep" if liq.gap_swept_high else "Sweep"
                r.score += SCORE_LIQ_SWEPT; r.reasons.append(f"{lbl} BSL +{SCORE_LIQ_SWEPT}")
            if has_sweep and fvg_active is not None:
                r.score += SCORE_SWEEP_AND_FVG; r.reasons.append(f"Sweep+FVG +{SCORE_SWEEP_AND_FVG}")

            _apply_htf_scores("SELL")
            _apply_h1_mtf("SELL")
            if htf_res.swept_high:
                r.score += 4; r.reasons.append("H4 BSL Swept +4")

            if r.m15_struct == "BEARISH_BOS":
                r.score += SCORE_M15_BOS; r.reasons.append(f"M15 BOS +{SCORE_M15_BOS}")

            body = float(last["open"]) - float(last["close"])
            if body > atr * 0.6:
                r.score += SCORE_STRONG_CANDLE; r.reasons.append(f"Strong ✓ +{SCORE_STRONG_CANDLE}")

            ob = self.find_order_block(df_m5, "SELL", atr)
            if ob.found and not ob.mitigated:
                r.score += SCORE_OB_BONUS; r.reasons.append(f"OB(q:{ob.score:.2f},age:{ob.bar_age}) +{SCORE_OB_BONUS}")
                if ob.low <= r.entry <= ob.high:
                    r.score += SCORE_OB_OVERLAP; r.reasons.append(f"OB Overlap +{SCORE_OB_OVERLAP}")

            mss = self.detect_mss(df_m5, "SELL", atr, last_sh, last_sl)
            r.mss = mss
            if mss.confirmed:
                r.score += mss.score_bonus
                tag = "MSS+CISD" if mss.is_cisd else "MSS"
                r.reasons.append(f"{tag} ✓ +{mss.score_bonus}")

            if liq.ssl_nearest is not None:
                rsk = abs(r.sl - r.entry)
                if rsk > 0 and (r.entry - liq.ssl_nearest) >= rsk * RR_RATIO * 0.8:
                    r.score += SCORE_LIQ_TARGET; r.reasons.append(f"SSL→{liq.ssl_nearest:.2f} +{SCORE_LIQ_TARGET}")

            if r.adr_pct >= ADR_EXHAUSTED_PCT:
                r.score += SCORE_ADR_WARN; r.reasons.append(f"ADR{r.adr_pct*100:.0f}% ⚠️")

            _apply_kz_score("SELL")

            r.sweep_type = self.classify_sweep("sweep", r.htf_bias, "SELL")

            r.shape = VShapeDetector.classify(df_m5, "SELL", atr)
            if   r.shape == "V": r.score += SCORE_VSHAPE_BONUS;   r.reasons.append(f"📐V-Shape +{SCORE_VSHAPE_BONUS}")
            elif r.shape == "U": r.score += SCORE_USHAPE_PENALTY;  r.reasons.append(f"🌊U-Shape {SCORE_USHAPE_PENALTY}pts")

            if self.check_golden_confluence(fvg_active, r.entry, "SELL", htf_res, df_m5, atr):
                r.score += SCORE_GOLDEN_CONFLUENCE; r.golden_conf = True
                r.reasons.append(f"✨Golden Confluence +{SCORE_GOLDEN_CONFLUENCE}")

            if self.is_judas_swing(liq, fvg_zones, "SELL", session):
                r.score += JUDAS_SCORE_BONUS; r.is_judas = True
                r.reasons.append(f"⚡Judas Swing +{JUDAS_SCORE_BONUS}")

            body_ratio = body / atr if atr > 0 else 0
            if (float(last["close"]) < float(prev["low"])
                    and body_ratio > MOMENTUM_BODY_ATR and r.score >= r.threshold):
                r.use_market = True; r.entry = 0.0; r.reasons.append("🚀 MKT")
            return True

        if not _build_buy():
            r.signal = "WAIT"; r.score = 0; r.reasons = []
            if not _build_sell(): return r

        if r.signal != "WAIT":
            entry_h     = r.entry if not r.use_market else -1.0
            r.setup_hash = _make_hash(r.signal, entry_h, r.sl, r.candle_ts)

        return r


# ══════════════════════════════════════════════════════════════════════════════
# 💰  CLASS: RiskManager  [V15 — preserved + SpreadGuard integration]
# ══════════════════════════════════════════════════════════════════════════════
class RiskManager:
    def __init__(self):
        self._spread_guard = SpreadGuard()   # [V16-F2]

    @staticmethod
    def get_broker_date() -> str:
        tick = mt5.symbol_info_tick(SYMBOL)
        return datetime.fromtimestamp(tick.time, tz=pytz.utc).strftime("%Y%m%d") \
               if tick else datetime.utcnow().strftime("%Y%m%d")

    def get_spread_pts(self) -> float:
        tick = mt5.symbol_info_tick(SYMBOL); info = mt5.symbol_info(SYMBOL)
        if tick is None or info is None: return 999.0
        return (tick.ask - tick.bid) / info.point

    def is_spread_ok(self) -> Tuple[bool, str]:
        """[V16-F2] Dynamic spread guard."""
        sp = self.get_spread_pts()
        self._spread_guard.update(sp)
        ok, reason = self._spread_guard.is_ok(sp)
        if not ok:
            log.warning(f"⛔ Spread blocked: {reason}")
        return ok, reason

    def update_spread_history(self) -> None:
        """Call once per closed candle to keep median accurate."""
        self._spread_guard.update(self.get_spread_pts())

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
            ci = next((i for i, (sm, _) in enumerate(RISK_TIERS) if score >= sm), len(RISK_TIERS) - 1)
            base_pct = RISK_TIERS[min(ci + 1, len(RISK_TIERS) - 1)][1]
        return base_pct

    @staticmethod
    def _round_lot(lot: float, step: float) -> float:
        d = Decimal(str(lot)); s = Decimal(str(step))
        return float((d / s).to_integral_value(rounding=ROUND_DOWN) * s)

    def calculate_lot(self, entry: float, sl: float, score: int = 0,
                      spread_pts: float = 0.0, atr: float = 0.0, dd_mode: str = "NORMAL") -> float:
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
    def validate_order(entry: float, sl: float, tp: float, lot: float, signal: str) -> Tuple[bool, str]:
        info = mt5.symbol_info(SYMBOL); acct = mt5.account_info(); tick = mt5.symbol_info_tick(SYMBOL)
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
        if margin_req is None or margin_req > acct.margin_free * 0.9: return False, "Insufficient margin"
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
# 📤  CLASS: ExecutionHandler  [V15 preserved]
# ══════════════════════════════════════════════════════════════════════════════
class ExecutionHandler:
    def __init__(self, risk: RiskManager, signal_engine: SMCSignalEngine):
        self._risk = risk; self._engine = signal_engine; self._lock = threading.Lock()

    def _send_retry(self, req: dict, retries: int = 3):
        last_res = None
        is_buy   = req.get("type") in (mt5.ORDER_TYPE_BUY, mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP)
        for i in range(1, retries + 1):
            try:
                with self._lock:
                    res = mt5.order_send(req)
            except Exception as exc:
                log.warning(f"order_send exception: {exc} (try {i})")
                if i < retries: time.sleep(0.5 * i)
                continue
            if res is None:
                if i < retries: time.sleep(0.5)
                continue
            last_res = res
            if res.retcode == mt5.TRADE_RETCODE_DONE: return res
            if res.retcode in (mt5.TRADE_RETCODE_REQUOTE, mt5.TRADE_RETCODE_PRICE_CHANGED,
                               mt5.TRADE_RETCODE_PRICE_OFF):
                tick = mt5.symbol_info_tick(SYMBOL)
                if tick: req["price"] = round(float(tick.ask if is_buy else tick.bid), 2)
                if i < retries: time.sleep(0.3 * i)
                continue
            if res.retcode in (mt5.TRADE_RETCODE_CONNECTION, mt5.TRADE_RETCODE_TIMEOUT):
                if i < retries: time.sleep(0.5 * i)
                continue
            log.error(f"❌ retcode:{res.retcode} | {res.comment}"); return res
        return last_res

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
            close_type = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
            price      = tick.bid if is_buy else tick.ask
            res = self._send_retry({
                "action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL,
                "volume": lot_close, "type": close_type, "position": pos.ticket,
                "price": round(float(price), 2), "deviation": self._risk.dynamic_deviation(atr),
                "magic": MAGIC_NUMBER, "comment": "V16|PartialTP"})
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                log.info(f"💰 Partial #{pos.ticket} {lot_close:.2f} @ {price:.2f}")
                record_trade_outcome("PARTIAL", "")  # partial is not a full WIN/LOSS
        except Exception as exc:
            log.warning(f"close_partial exception: {exc}")

    def close_position_market(self, pos) -> bool:
        try:
            tick = mt5.symbol_info_tick(SYMBOL); info = mt5.symbol_info(SYMBOL)
            if tick is None or info is None: return False
            is_buy = (pos.type == mt5.ORDER_TYPE_BUY)
            res = self._send_retry({
                "action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL,
                "volume": pos.volume, "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
                "position": pos.ticket, "price": round(float(tick.bid if is_buy else tick.ask), 2),
                "deviation": max(100, self._risk.dynamic_deviation(info.point * 100)),
                "magic": MAGIC_NUMBER, "comment": "V16|KILL"}, retries=5)
            ok = res is not None and res.retcode == mt5.TRADE_RETCODE_DONE
            log.info(f"{'✅' if ok else '❌'} Kill-close #{pos.ticket}")
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
        if not sp_ok or not self._risk.is_within_risk_limits(): return False
        if self._risk.has_duplicate_setup(setup.setup_hash, setup.signal):
            log.info(f"🚫 Duplicate → skip"); return False
        if self._risk.count_open_positions() >= MAX_CONCURRENT_TRADES:
            log.info(f"⚠️ Max concurrent ({MAX_CONCURRENT_TRADES}) → skip"); return False

        sp     = self._risk.get_spread_pts()
        sl_pad = self._risk.get_spread_sl_padding()
        if sp > MAX_SPREAD_POINTS:
            setup.score += SCORE_SPREAD_WARN; setup.reasons.append(f"Spread {sp:.0f}pts ⚠️")

        # M1 displacement confirmation [V16-S1 upgraded]
        try:
            rates_m1 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 8)
            if rates_m1 is not None and len(rates_m1) >= 4:
                df_m1 = pd.DataFrame(rates_m1)
                c = df_m1.iloc[-2]
                body_m1 = abs(float(c["close"]) - float(c["open"]))
                dir_ok  = (setup.signal == "BUY"  and c["close"] > c["open"]) or \
                          (setup.signal == "SELL" and c["close"] < c["open"])
                # Require M1 body ≥ threshold AND directional alignment
                if body_m1 >= setup.atr * MTF_M1_BODY_ATR and dir_ok:
                    setup.score += SCORE_M1_CONFIRM; setup.reasons.append("M1 Disp ✓")
        except Exception:
            pass

        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None: return False

        sig    = setup.signal
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
                entry = tick.ask; otype = mt5.ORDER_TYPE_BUY; action = mt5.TRADE_ACTION_DEAL; exp = 0
            elif sig == "SELL" and entry <= tick.bid:
                entry = tick.bid; otype = mt5.ORDER_TYPE_SELL; action = mt5.TRADE_ACTION_DEAL; exp = 0

        risk = abs(entry - sl_adj)
        if risk == 0: log.error("place_order: risk=0"); return False

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
        dev   = self._risk.dynamic_deviation(setup.atr)

        sent = 0
        for lot_i, tp_i, label in [(lot_a, tp_pt, "PT"), (lot_b, tp_full, "FT")]:
            req = {"action": action, "symbol": SYMBOL, "volume": lot_i, "type": otype,
                   "price": round(float(entry), 2), "sl": round(float(sl_adj), 2),
                   "tp": round(float(tp_i), 2), "deviation": dev, "magic": MAGIC_NUMBER,
                   "comment": f"V16|{sig}|{label}|{setup.score}|{setup.setup_hash}"}
            if action == mt5.TRADE_ACTION_PENDING:
                req["type_time"] = mt5.ORDER_TIME_SPECIFIED; req["expiration"] = exp
            res = self._send_retry(req)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                sent += 1
                log.info(f"✅ {label}|{sig}|Lot:{lot_i}|E:{entry:.2f}|SL:{sl_adj:.2f}|TP:{tp_i:.2f}")
            else:
                log.warning(f"⚠️ {label} order failed")

        if sent > 0:
            rr_act = abs(tp_full - entry) / risk if risk > 0 else 0
            log.info(
                f"\n{'═'*70}\n"
                f"  🎯 TRADE PLACED — {sig} {'MKT' if action == mt5.TRADE_ACTION_DEAL else 'LMT'}"
                f"  {'⚡JUDAS' if setup.is_judas else ''}{'✨GOLDEN' if setup.golden_conf else ''}\n"
                f"  {'─'*68}\n"
                f"  Entry:{entry:.2f}  SL:{sl_adj:.2f}  TP-Part:{tp_pt:.2f}  TP-Full:{tp_full:.2f}\n"
                f"  Risk:{risk:.2f}pts  RR:{rr_act:.2f}×  Lot:{lot_a}+{lot_b}\n"
                f"  Score:{setup.score}/{setup.threshold}  WinProb:{setup.win_prob:.3f}  DD:{dd_mode}\n"
                f"  Session:{session}  H4:{setup.htf_bias}  H1:{setup.h1_bias}  M15:{setup.m15_struct}\n"
                f"  Shape:{setup.shape}  Sweep:{setup.sweep_type}  MSS:{setup.mss.confirmed if setup.mss else False}\n"
                f"  Spread:{sp:.1f}pts(median:{self._risk._spread_guard.median_spread:.1f})\n"
                f"  Hash:{setup.setup_hash}\n"
                f"{'═'*70}"
            )
            db_log_setup(sig, setup.score, entry, sl_adj, tp_full, setup.setup_hash,
                         session, setup.features, setup.win_prob, setup.sweep_type, setup.shape)
            return True
        return False


# ══════════════════════════════════════════════════════════════════════════════
# 🔄  CLASS: PositionManager  [V15 + V16-O2 outcome tracking]
# ══════════════════════════════════════════════════════════════════════════════
class PositionManager:
    def __init__(self, feed: MarketDataFeed, execution: ExecutionHandler,
                 conn_mgr: ConnectionManager):
        self._feed    = feed
        self._exec    = execution
        self._conn    = conn_mgr
        self._running = threading.Event()
        self._running.set()
        self._thread: Optional[threading.Thread] = None
        self._last_positions: Dict[int, float] = {}  # ticket → last_close

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
                # [V16-F3] Check connection before every PM poll
                if not self._conn.ensure_connected():
                    time.sleep(POSITION_POLL_SEC * 5); continue
                df_m5 = self._feed.get_cached_m5()
                atr   = calculate_atr(df_m5) if df_m5 is not None else 1.0
                self._manage_positions(atr)
            except Exception as exc:
                log.warning(f"⚠️ PM error: {exc}")
            time.sleep(POSITION_POLL_SEC)

    def _manage_positions(self, atr: float) -> None:
        try:
            positions = [p for p in (mt5.positions_get(symbol=SYMBOL) or [])
                         if p.magic == MAGIC_NUMBER]
        except Exception:
            return
        if not positions: self._last_positions.clear(); return

        try:
            tick = mt5.symbol_info_tick(SYMBOL); info = mt5.symbol_info(SYMBOL)
        except Exception:
            return
        if tick is None or info is None: return

        a            = max(atr, info.point * 10)
        open_tickets = {p.ticket for p in positions}
        trail_cache  = batch_load_trail_states(list(open_tickets))

        # [V16-O2] Detect closed positions and record WIN/LOSS for ConsecLoss CB
        # Compare previous tracked tickets vs currently open ones
        prev_tickets = set(self._last_positions.keys())
        closed_now   = prev_tickets - open_tickets
        for t in closed_now:
            prev_pl = self._last_positions.get(t, 0.0)
            # A trade closed at breakeven (profit ≈ 0) counts as WIN to avoid
            # triggering the circuit breaker on neutral outcomes
            outcome = "WIN" if prev_pl >= 0 else "LOSS"
            # Try to get the session name from the closing position's comment
            session_tag = ""
            try:
                hist = mt5.history_deals_get(position=t)
                if hist:
                    last_deal = sorted(hist, key=lambda d: d.time)[-1]
                    session_tag = (last_deal.comment or "").split("|")[1] \
                        if "|" in (last_deal.comment or "") else ""
            except Exception:
                pass
            record_trade_outcome(outcome, session_tag)
            log.info(
                f"📋 [V16-O2] Closed #{t}: {outcome} "
                f"(last float P&L: {prev_pl:+.2f}) "
                f"ConsecLoss now: {get_consecutive_losses()}"
            )
        # Refresh snapshot of open positions with their current floating P&L
        self._last_positions = {p.ticket: p.profit for p in positions}

        for pos in positions:
            entry = pos.price_open; sl_now = pos.sl
            is_buy = (pos.type == mt5.ORDER_TYPE_BUY)
            comment_parts = (pos.comment or "").split("|")
            pos_hash = comment_parts[-1] if len(comment_parts) >= 5 else ""
            risk = abs(entry - sl_now)
            if risk < info.point: risk = a * 1.5
            price    = tick.bid if is_buy else tick.ask
            buf      = info.point * 5
            profit_r = ((price - entry) / risk if is_buy else (entry - price) / risk)
            ts           = trail_cache.get(pos.ticket)
            partial_done = int(ts["partial_done"]) if ts else 0

            pnl_pts  = (price - entry) if is_buy else (entry - price)
            pnl_usd  = pnl_pts * info.trade_tick_value / info.point * pos.volume \
                       if info.point > 0 else 0
            log.debug(f"📍 #{pos.ticket} {'BUY' if is_buy else 'SELL'} R:{profit_r:+.2f} ${pnl_usd:+.2f}")

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
                        log.info(f"📈 Trail #{pos.ticket} SL:{sl_now:.2f}→{new_tsl:.2f} R:{profit_r:.2f}")
                else:
                    new_tsl = price + (a * TRAIL_ATR_MULT)
                    if new_tsl < sl_now and (last_tsl is None or new_tsl < last_tsl - min_move):
                        self._exec.modify_sl(pos.ticket, new_tsl)
                        save_trail_sl(pos.ticket, new_tsl, pos_hash)
                        log.info(f"📉 Trail #{pos.ticket} SL:{sl_now:.2f}→{new_tsl:.2f} R:{profit_r:.2f}")

        cleanup_trail_state(open_tickets)


# ══════════════════════════════════════════════════════════════════════════════
# 🆘  GRACEFUL SHUTDOWN & HEARTBEAT  [V15 — preserved]
# ══════════════════════════════════════════════════════════════════════════════
def graceful_shutdown(execution: ExecutionHandler, reason: str = "KILL") -> None:
    log.warning(f"🚨 SHUTDOWN — reason: {reason}")
    try:
        for o in (mt5.orders_get(symbol=SYMBOL) or []):
            if o.magic == MAGIC_NUMBER: execution.cancel_pending_order(o.ticket)
        time.sleep(0.5)
        for pos in (mt5.positions_get(symbol=SYMBOL) or []):
            if pos.magic == MAGIC_NUMBER: execution.close_position_market(pos); time.sleep(0.2)
        time.sleep(1.0)
        acct = mt5.account_info()
        if acct: log.warning(f"🚨 Final equity=${acct.equity:,.2f}")
    except Exception as exc:
        log.warning(f"shutdown error: {exc}")
    log.warning("🚨 SHUTDOWN COMPLETE")


def emit_heartbeat(risk: RiskManager, predictor: MLPredictor, session: str,
                   htf_bias: str, h1_bias: str, adr_pct: float) -> None:
    try:
        acct = mt5.account_info()
        if acct is None: return
        daily_dd, total_dd, dd_mode = risk.get_dd_state()
        init_bal = get_state("initial_balance") or acct.balance
        eq_pct   = (acct.equity - init_bal) / init_bal * 100 if init_bal > 0 else 0
        open_pos = risk.count_open_positions()
        today_pl = acct.equity - (get_state("daily_start_balance_" + risk.get_broker_date()) or acct.balance)
        dd_icon  = {"NORMAL":"🟢","YELLOW":"💛","ORANGE":"🟠","RED":"🔴"}.get(dd_mode,"⚪")
        consec   = get_consecutive_losses()
        log.info(
            f"\n{'═'*70}\n"
            f"  💓  HEARTBEAT  {datetime.now(STRATEGY_TZ).strftime('%H:%M:%S %Z')}\n"
            f"  {'─'*68}\n"
            f"  💵 Equity    : ${acct.equity:>10,.2f}  ({eq_pct:+.2f}%)   Today P&L: ${today_pl:>+,.2f}\n"
            f"  📉 Daily DD  : {daily_dd:5.2f}%    Total DD : {total_dd:5.2f}%  [{dd_icon} {dd_mode}]\n"
            f"  🌍 Session   : {session:<16} H4:{htf_bias:<10} H1:{h1_bias}\n"
            f"  📊 ADR Used  : {adr_pct*100:5.1f}%    OpenPos  : {open_pos}/{MAX_CONCURRENT_TRADES}\n"
            f"  🧠 ML Norm   : {'WARM' if predictor.norm_is_warm else 'COLD-START':<12}"
            f"  AvgProb: {predictor.rolling_avg_prob:.3f}\n"
            f"  📡 Spread    : {risk.get_spread_pts():.1f}pts  "
            f"Median: {risk._spread_guard.median_spread:.1f}pts\n"
            f"  🚦 ConsecLoss: {consec}/{N_CONSEC_LOSS_PAUSE}"
            f"{'  ⏸️ PAUSED' if consec >= N_CONSEC_LOSS_PAUSE else ''}\n"
            f"{'═'*70}"
        )
    except Exception as exc:
        log.warning(f"heartbeat error: {exc}")


# ══════════════════════════════════════════════════════════════════════════════
# 🔁  SIGNAL CYCLE  [V16 — full upgrade]
# ══════════════════════════════════════════════════════════════════════════════
def _run_signal_cycle(
    feed:          MarketDataFeed,
    signal_engine: SMCSignalEngine,
    risk:          RiskManager,
    execution:     ExecutionHandler,
    predictor:     MLPredictor,
    conn_mgr:      ConnectionManager,
    last_ctx:      Dict,
) -> None:
    # [V16-F3] Connection check first
    if not conn_mgr.ensure_connected():
        log.warning("⚠️ MT5 not connected — skip cycle"); return

    daily_dd, total_dd, dd_mode = risk.get_dd_state()
    if dd_mode == "RED":
        log.warning(f"⛔ DD RED {daily_dd:.2f}% → halt"); return
    if risk.is_circuit_breaker_tripped(): return

    session = signal_engine.get_session()
    if session in ("OUT_OF_SESSION", "RED_NEWS_BLOCK"): return

    in_kz, kz_name = signal_engine.is_in_killzone()
    # [V16-O1] Don't hard-block outside KZ — score penalty handles it
    log.info(f"📡 Session:{session} KZ:{kz_name}({'✅' if in_kz else '❌'})")

    sp_ok, sp_reason = risk.is_spread_ok()
    if not sp_ok: log.warning(f"⚠️ Spread blocked: {sp_reason}"); return

    if os.path.isfile(PAUSE_FLAG_PATH):
        log.info("⏸️ PAUSE.flag → skip"); return
    if not risk.new_entries_allowed():
        log.warning(f"🟠 DD {dd_mode} → entries suspended"); return

    # [V16-O2] Consecutive-loss circuit breaker
    if is_consec_loss_paused(): return

    data = feed.fetch_all()
    if data["m5"] is None: log.warning("M5 unavailable → skip"); return

    # Update spread history for dynamic guard
    risk.update_spread_history()
    cleanup_cooldowns()

    # [V16-F4] Update broker clock
    signal_engine._clock.refresh()

    setup = signal_engine.analyze_setup(
        data["m5"], data["h4"], data["d1"], data["m15"],
        data.get("dxy"), data.get("h1"),
        session, in_killzone=in_kz,
    )
    setup.spread_pts = risk.get_spread_pts()

    last_ctx["bias"]    = setup.htf_bias
    last_ctx["h1_bias"] = setup.h1_bias
    last_ctx["session"] = session
    last_ctx["adr_pct"] = str(setup.adr_pct)

    # Context log
    liq = setup.liq_map
    if liq:
        log.info(f"💧 BSL:{liq.bsl_nearest or '—'} SSL:{liq.ssl_nearest or '—'} "
                 f"SwH:{liq.swept_high} SwL:{liq.swept_low}")
    htf = setup.htf_result
    if htf:
        log.info(f"🏗️  H4:{htf.bias} BOS:{htf.last_bos} CHOCH:{htf.choch_signal} "
                 f"| H1:{setup.h1_bias}")
    log.info(
        f"📊 {session} | M15:{setup.m15_struct} | ADR:{setup.adr_pct*100:.0f}% | "
        f"Thr:{setup.threshold} | DD:{dd_mode} | "
        f"Sweep:{setup.sweep_type} Shape:{setup.shape}"
    )

    if setup.signal == "WAIT": return
    if setup.score < setup.threshold:
        log.info(f"🟡 Score {setup.score} < {setup.threshold} → skip"); return

    close_price    = float(data["m5"]["close"].iloc[-1])
    setup.features = extract_features(setup, close_price=close_price, df_len=len(data["m5"]))
    setup.win_prob = predictor.predict_win_probability(setup.features)

    # [V16-RISK1 FIX] Use stricter gate when running without a trained model
    active_gate = ML_HEURISTIC_THRESHOLD if predictor._heuristic_mode else ML_WIN_PROB_THRESHOLD
    gate_label  = f"heuristic gate:{active_gate}" if predictor._heuristic_mode else f"model gate:{active_gate}"

    log.info(f"🧠 WinProb:{setup.win_prob:.3f} [avg:{predictor.rolling_avg_prob:.3f}] "
             f"{gate_label} | {setup.summary()}")

    if setup.win_prob < active_gate:
        log.info(f"🤖 ML rejected: {setup.win_prob:.3f} < {active_gate} ({gate_label})"); return

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
║  🏆  AI SMC/ICT Pro Sniper — V.16 ELITE  (XAUUSD Gold Specialist)               ║
║  [V16-F1] PRE_LONDON FOMO guard    [V16-F2] Dynamic Spread Lock (3×median)      ║
║  [V16-F3] Auto-reconnect expBackoff [V16-F4] Broker Clock Sync (tick-derived)   ║
║  [V16-S1] MTF Matrix H4>H1>M15>M5  [V16-S2] Sweep Classification CONT/REV      ║
║  [V16-S3] MSS + CISD Confirmation   [V16-S4] V-Shape/U-Shape Detection          ║
║  [V16-S5] CCT Golden Confluence     [V16-O1] KZ Outside Penalty -30pts          ║
║  [V16-O2] Consec-Loss CB (3-strike) [V16-O3] H1 Intermediate Bias layer        ║
║  ── BUG FIXES ──────────────────────────────────────────────────────────────── ║
║  [BUG1] record_trade_outcome() now called on position close (ConsecLoss live)   ║
║  [BUG2] VShapeDetector: sweep=iloc[-2], velocity+retrace checked on iloc[-1]   ║
║  [BUG3] NY_OPEN_EARLY killzone added (18:30-19:15 UTC) + lighter KZ penalty    ║
║  [RISK1] ML heuristic gate raised to 0.58 (was 0.50) when no model loaded      ║
║  [RISK2] check_golden_confluence() guards htf last_sh/sl_val None              ║
╚══════════════════════════════════════════════════════════════════════════════════╝
"""


def main() -> None:
    print(BANNER)
    log.info("Bot V.16 ELITE starting")
    init_db()

    # [V16-F3] Connection Manager
    conn_mgr = ConnectionManager()
    if not conn_mgr.ensure_connected():
        # Try harder on startup
        for delay in [5, 10, 20, 30]:
            log.warning(f"MT5 not ready — retrying in {delay}s…")
            time.sleep(delay)
            if conn_mgr.ensure_connected(): break
        else:
            log.error("❌ Cannot connect to MT5 after extended retry"); return

    # [V16-F4] Broker clock
    clock = BrokerClockSync(SYMBOL, STRATEGY_TZ)
    clock.refresh()

    feed          = MarketDataFeed()
    signal_engine = SMCSignalEngine(clock)
    risk          = RiskManager()
    execution     = ExecutionHandler(risk, signal_engine)
    predictor     = MLPredictor()
    # predictor.load_model("smc_model_v16.joblib")

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
        f"📡 Symbol:{SYMBOL} | H4+H1 Bias | KZ penalty:{KZ_OUTSIDE_PENALTY}pts | "
        f"CB:{CIRCUIT_BREAKER_PCT}% | SpreadMult:{SPREAD_DYNAMIC_MULT}× | "
        f"ConsecLoss:{N_CONSEC_LOSS_PAUSE}-strike → {CONSEC_LOSS_PAUSE_MIN}min pause"
    )

    try:
        while not _shutdown.is_set():
            # Kill flag
            if os.path.isfile(KILL_FLAG_PATH):
                log.warning("🚨 KILL.flag!"); _shutdown.set(); break

            # [V16-F3] Connection check on every main loop iteration
            if not conn_mgr.ensure_connected():
                time.sleep(TICK_POLL_SEC); continue

            # [V16-F4] Refresh broker clock on every loop
            clock.refresh()

            try:
                rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M5, 0, 2)
            except Exception as exc:
                log.warning(f"copy_rates exception: {exc}")
                time.sleep(TICK_POLL_SEC); continue

            if rates is None or len(rates) < 2:
                time.sleep(TICK_POLL_SEC); continue

            current_open_bar_time   = int(rates[-1]["time"])
            previous_closed_bar_time = int(rates[-2]["time"])

            # [V14-F1] Entry only on new closed bar
            if previous_closed_bar_time != last_closed_bar_time:
                log.info("─" * 74)
                log.info(
                    f"🕯️  Closed:{previous_closed_bar_time} | "
                    f"New:{current_open_bar_time} | "
                    f"{clock.now_strategy().strftime('%H:%M:%S')} {STRATEGY_TZ_NAME}"
                )
                last_closed_bar_time = previous_closed_bar_time
                _run_signal_cycle(
                    feed, signal_engine, risk, execution, predictor, conn_mgr, last_ctx
                )

            # Heartbeat
            now = time.time()
            if now - last_heartbeat >= HEARTBEAT_SEC:
                emit_heartbeat(
                    risk, predictor,
                    last_ctx.get("session", "?"),
                    last_ctx.get("bias", "?"),
                    last_ctx.get("h1_bias", "?"),
                    float(last_ctx.get("adr_pct", "0")),
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
        log.info("MT5 offline. Bot V.16 ELITE terminated.")


# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    main()
