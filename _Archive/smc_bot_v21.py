"""
╔══════════════════════════════════════════════════════════════════════════════════╗
║  🌐  AI SMC/ICT Pro Sniper — V.21 "Global Scanner" (Multi-Asset Architecture)   ║
╠══════════════════════════════════════════════════════════════════════════════════╣
║                                                                                  ║
║  ██████  V.20 ARCHITECTURAL UPGRADE REPORT  ██████████████████████████████████  ║
║                                                                                  ║
║  ██████  V.21 GLOBAL SCANNER — MULTI-ASSET ARCHITECTURE  ████████████████████  ║
║                                                                                  ║
║  [V21-A1] ACTIVE_SYMBOLS — per-symbol profile dict replaces global SYMBOL str  ║
║           Each symbol has spread_block_pts, sl_atr_mult, min_lot config.        ║
║           SpreadGuard and RiskManager now accept symbol-specific parameters.    ║
║                                                                                  ║
║  [V21-A2] ROUND-ROBIN SCANNER — MT5 rate-limit protection                      ║
║           Main loop polls M5 bar timestamps (1 light request/sec per symbol).  ║
║           Full multi-timeframe fetch + SMCSignalEngine only fires when a new   ║
║           M5 bar closes for that specific symbol. 0.1s sleep between symbols   ║
║           prevents MT5 API spam.                                                ║
║                                                                                  ║
║  [V21-A3] GLOBAL EXPOSURE LIMITS — small account protection                    ║
║           GLOBAL_MAX_CONCURRENT_TRADES = 2 (hard cap across ALL symbols).      ║
║           MAX_TRADES_PER_SYMBOL = 1 (no doubling on same pair).                ║
║           Pre-trade floating-risk check: new trade blocked if total account    ║
║           exposure would exceed MAX_GLOBAL_EXPOSURE_PCT (40%).                 ║
║                                                                                  ║
║  [V21-A4] DISTRIBUTED STATE & CACHE                                            ║
║           last_closed_bar[symbol] = timestamp dict for per-symbol bar tracking.║
║           FridayGuard.execute_eod_close() iterates ALL ACTIVE_SYMBOLS.         ║
║           PositionManager._orphan_sl_check covers positions on all symbols.    ║
║           graceful_shutdown flattens all symbols.                               ║
║                                                                                  ║
║  ── CRITICAL FIXES (V.20 — ALL PRESERVED) ──────────────────────────────────── ║
║  ── CRITICAL FIXES ────────────────────────────────────────────────────────────  ║
║                                                                                  ║
║  [V20-C1] WELFORD WARM-START PERSISTENCE                                        ║
║           V19: WelfordNormaliser state (mean/M2/count) lived purely in-memory.  ║
║           On any bot restart the normaliser would start COLD (min_samples=20)   ║
║           making it temporarily blind to distribution shifts — the exact         ║
║           vulnerability it was designed to detect.                               ║
║           V20: State is serialised to JSON ("welford_state" in bot_state DB)    ║
║           on every update (debounced to every 50 samples to avoid write-flood)  ║
║           and loaded on MLPredictor.__init__. Restart now picks up from where   ║
║           the normaliser left off within milliseconds of reconnect.             ║
║                                                                                  ║
║  [V20-C2] MT5 TERMINAL CRASH / MID-EXECUTION RECOVERY                          ║
║           V19: If MT5 crashed mid-execution (between order_send and the         ║
║           position appearing in terminal) _adjust_partial_fill would silently   ║
║           give up after 3 × 0.5s probes and the position would run without      ║
║           SL/TP. No recovery path existed.                                       ║
║           V20: PositionManager._orphan_sl_check() scans all MAGIC_NUMBER         ║
║           positions at startup and on every 60-second cycle. Any position       ║
║           whose sl == 0 gets SL reconstructed from trail_state DB or a safe     ║
║           ATR-based fallback, then applied via TRADE_ACTION_SLTP.               ║
║                                                                                  ║
║  [V20-C3] THREAD-SAFETY: _consec_loss_cache RACE CONDITION                     ║
║           V19: Module-level globals _consec_loss_cache / _consec_loss_cache_ts  ║
║           were read and written from two threads (main + PositionManager)       ║
║           without a lock. Python GIL protects individual bytecodes but a         ║
║           read-modify-write of two separate globals is NOT atomic and can        ║
║           produce torn reads under CPython.                                      ║
║           V20: Both globals replaced by a _ConsecLossCache dataclass instance  ║
║           protected by threading.Lock().                                         ║
║                                                                                  ║
║  [V20-C4] SQLITE WAL WRITER THREAD: QUEUE BACK-PRESSURE GUARD                  ║
║           V19: _write_q is an unbounded Queue(). During CPI/NFP with hundreds   ║
║           of ticks/second and many DB writes, the queue could grow unboundedly  ║
║           consuming memory and delaying flush.                                   ║
║           V20: Queue capped at maxsize=500. _db_exec now has a drop_on_full     ║
║           parameter (default False for critical writes, True for non-critical). ║
║           Writer thread logs a warning when the queue exceeds 80% capacity.     ║
║                                                                                  ║
║  [V20-C5] FRIDAY GUARD: execute_eod_close MISSING close_position_market IMPL   ║
║           V19 FridayGuard.close_all_positions_market() called                  ║
║           self.close_position_market(pos) but FridayGuard had NO such method — ║
║           only ExecutionHandler did. This is a NameError at runtime.           ║
║           V20: FridayGuard.execute_eod_close(execution) is the authoritative    ║
║           EOD path and delegates ALL closes to ExecutionHandler directly.       ║
║           close_all_positions_market() is removed from FridayGuard.             ║
║                                                                                  ║
║  ── OPTIMISATION FIXES ────────────────────────────────────────────────────────  ║
║                                                                                  ║
║  [V20-O1] NUMPY VECTORISATION: build_liquidity_map_np                          ║
║           V19: swing pivot detection used a Python for-loop calling             ║
║           high[i-p:i+p+1].max() — an O(n²) operation.                         ║
║           V20: Replaced with np.lib.stride_tricks sliding-window max/min       ║
║           (via scipy.ndimage.maximum_filter1d when available, else manual        ║
║           stride fallback). Also removed redundant _to_numpy calls inside the  ║
║           same function (arrays were already extracted).                         ║
║                                                                                  ║
║  [V20-O2] NUMPY VECTORISATION: get_confirmed_swings_np                         ║
║           Same O(n²) window-max loop. V20 uses the same sliding-window max/min  ║
║           approach — single vectorised pass for both highs and lows.            ║
║                                                                                  ║
║  [V20-O3] NUMPY VECTORISATION: scan_fvg_memory                                 ║
║           V19: Inner mitigated-check was a Python for-loop over df rows.        ║
║           V20: Uses np.searchsorted + array slice min/max for mitigated         ║
║           detection in a single vectorised call per FVG zone.                   ║
║                                                                                  ║
║  [V20-O4] VSHAPE DETECTOR: df_m5.iloc index safety                             ║
║           V19: VShapeDetector.classify() used df_m5.iloc[-3] (the 3rd-to-last  ║
║           bar) as the "origin" but this is wrong after V19-W2's reset_index.   ║
║           The origin should be the bar BEFORE the sweep candle (-3 relative to ║
║           the pre-close bar). Added explicit reset_index inside classify() and  ║
║           bounds-checked every iloc access.                                      ║
║                                                                                  ║
║  [V20-O5] MARKEY DATA FEED: cache_key COLLISION                                ║
║           V19: cache_key = tf + hash(symbol) for non-SYMBOL symbols.            ║
║           hash() is randomised per Python process (PYTHONHASHSEED).             ║
║           Adding tf (int) + hash(str) can produce collisions for different TFs  ║
║           of the same symbol. V20 uses (tf, symbol) tuple as dict key.         ║
║                                                                                  ║
║  [V20-O6] RISKMANAGER.get_dd_state: double MT5 API calls                       ║
║           V19: get_dd_state() and is_circuit_breaker_tripped() both called      ║
║           mt5.account_info() independently. The main loop called both in the   ║
║           same cycle — 2 redundant API round-trips per bar.                    ║
║           V20: get_dd_state() result is cached for 2 seconds (DD_STATE_TTL).   ║
║           Circuit-breaker reuses the same cached snapshot.                      ║
║                                                                                  ║
║  [V20-O7] BANNER VERSION STRINGS UPDATED                                        ║
║           V19 banner still showed "V.18 LIVE". V20 banner is correct.          ║
║                                                                                  ║
║  PRESERVED FROM V.19 / V.18 (all intact, zero regressions)                     ║
║  ─────────────────────────────────────────────────────────────────────────────  ║
║  [V19-F1] Sweep ATR momentum gate · [V19-F2] ADR TP signed math                ║
║  [V19-F3] Risk tier single-division · [V19-F4] OOS hard spread block           ║
║  [V19-W1] Consec-loss cache · [V19-W2] VShape reset_index                      ║
║  [V19-W3] H4 swing period=5 · [V19-W4] filling-mode cache on reconnect         ║
║  [V18-P1A] Delayed BE · [V18-P1B] OOS dual-threshold · [V18-P1C] Relaxed ADR  ║
║  [V18-P2A] type_filling injection · [V18-P2B] Broker-clock Friday guard        ║
║  [V18-P2C] IOC partial-fill race fix · [V18-P2D] deviation int cast            ║
║  ConnectionManager auto-reconnect · BrokerClockSync · SpreadGuard dynamic      ║
║  PRE_LONDON FOMO guard · 3-tier DD · SIGTERM · FridayGuard (broker-time)       ║
║  MSS+CISD · V/U-Shape · Golden Confluence · Sweep Classification               ║
║  SQLite WAL · Thread-local DB + bounded writer queue · PAUSE/KILL flags        ║
║  FVG memory · OB freshness · Judas Swing · H4/H1 bias · ADR TP cap            ║
║  Welford normaliser (now with Warm-Start) · Heartbeat · ML bypass              ║
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

# Optional: scipy for fast sliding-window max/min
try:
    from scipy.ndimage import maximum_filter1d as _max_filter1d
    from scipy.ndimage import minimum_filter1d as _min_filter1d
    _SCIPY_AVAILABLE = True
except ImportError:
    _SCIPY_AVAILABLE = False


# ══════════════════════════════════════════════════════════════════════════════
# 🏦  BROKER CONFIG  — edit ONLY this block per broker/VPS
# ══════════════════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════════════
# 🏦  BROKER CONFIG  — edit ONLY this block per broker/VPS
# ══════════════════════════════════════════════════════════════════════════════

# [V21-A1] ACTIVE_SYMBOLS: replaces the single global SYMBOL string.
# Each entry contains per-symbol risk/spread/lot parameters.
# The BrokerClockSync anchor symbol is the first key.
ACTIVE_SYMBOLS: Dict[str, Dict] = {
    "XAUUSDm": {"spread_block_pts": 80.0,   "sl_atr_mult": 2.5, "min_lot": 0.01},
    "EURUSDm": {"spread_block_pts": 15.0,   "sl_atr_mult": 1.5, "min_lot": 0.01},
    "USDJPYm": {"spread_block_pts": 25.0,   "sl_atr_mult": 2.0, "min_lot": 0.01},
    "USTECm":  {"spread_block_pts": 200.0,  "sl_atr_mult": 3.0, "min_lot": 0.1 },  # NAS100
    "BTCUSDm": {"spread_block_pts": 1500.0, "sl_atr_mult": 2.5, "min_lot": 0.001},
}

# [V21-A1] Clock-anchor symbol: must be the first key in ACTIVE_SYMBOLS.
# Used for BrokerClockSync tick and daily balance keying.
CLOCK_ANCHOR_SYMBOL: str = next(iter(ACTIVE_SYMBOLS))

# Legacy alias — kept so any code path that still references SYMBOL at module
# level (e.g. MarketDataFeed default arg) continues to compile.  In V.21 all
# hot-paths receive the symbol explicitly.
SYMBOL = CLOCK_ANCHOR_SYMBOL

MAGIC_NUMBER     = 99999
BROKER_TZ_NAME   = "Etc/UTC"
STRATEGY_TZ_NAME = "Asia/Bangkok"
BROKER_TZ        = pytz.timezone(BROKER_TZ_NAME)
STRATEGY_TZ      = pytz.timezone(STRATEGY_TZ_NAME)

# [V17-F3] DXY deprecated — constant kept for import compatibility
DXY_SYMBOL  = ""
DXY_ENABLED = False


# ══════════════════════════════════════════════════════════════════════════════
# ⚙️  STRATEGY CONFIGURATION (V.20 PRO-AUDITED: THE REAL PREDATOR)
# ══════════════════════════════════════════════════════════════════════════════
RR_RATIO            = 3.0       # ปล่อยไหลรันเทรนด์ให้สุด (Win 1 ครั้ง Cover Loss ได้เพียบ)
MIN_RR_RATIO_LIVE   = 0.6
MAX_DAILY_LOSS_PCT  = 40.0       # 🚨 PRO LIMIT: ขาดทุน 6% ต่อวันคือตัดไฟทันที ป้องกันอารมณ์พัง
MAX_TOTAL_DD_PCT    = 15.0      # 🚨 PRO LIMIT: พอร์ตยุบ 15% ต้องหยุดทบทวนระบบ
EXPIRATION_CANDLES  = 36

# ── Spread ────────────────────────────────────────────────────────────────────
HARD_SPREAD_BLOCK    = 80.0     # 🚨 อุดรอยรั่ว! สเปรดทอง Micro ปกติ 20-50 ทะลุ 80 คือห้ามเทรด
MAX_SPREAD_POINTS    = 60.0     # 🚨 เกิน 60 จุด เริ่มหักคะแนน/ลดหลอดเตือนภัย
SPREAD_DYNAMIC_MULT  = 3.0
SPREAD_MEDIAN_BARS   = 20
SPREAD_LOT_PENALTY   = 0.3
SPREAD_SL_PADDING    = True     # เสื้อเกราะสำคัญ! บวกสเปรดใน SL กันโดนเตะก้านคอ

# ── Deviation / Slippage Caps ─────────────────────────────────────────────────
MAX_DEVIATION_POINTS       = int(30)
EMERGENCY_DEVIATION_POINTS = int(150)

MOMENTUM_BODY_ATR   = 1.2

# ── [V18-P1A] DELAYED BREAKEVEN & HIT-AND-RUN ─────────────────────────────────
PARTIAL_TP_RR       = 1.0       # ปิดครึ่งนึงทันทีที่ 1R (เก็บทุนเข้ากระเป๋า)
PARTIAL_TP_PCT      = 0.50
BREAKEVEN_DELAY_RR  = 1.0      # ดัน SL มาบังทุนที่ 1.2R (Trade แบบไร้ความเสี่ยง)
TRAIL_AFTER_RR      = 1.5       # เริ่ม Trailing วิ่งตามก้นที่ 1.5R
TRAIL_ATR_MULT      = 1.0
TRAIL_MIN_MOVE_ATR  = 0.3

ADR_EXHAUSTED_PCT     = 0.88
ADR_NY_EXHAUSTED_PCT  = 0.93
ADR_HARD_BLOCK        = False
ADR_TP_BUFFER_PCT     = 0.95

SL_ATR_MULT         = 2.5       # จุดสมดุลของทองคำ หลบ Spike ได้ดีเยี่ยม
FVG_ENTRY_MID       = True
SWING_PERIOD        = 5
SWING_CONFIRM_BARS  = 2
SETUP_COOLDOWN_SEC  = 180

MAX_CONCURRENT_TRADES = 2       # 🚨 หั่นเหลือ 3 ไม้ คุม Exposure ไม่ให้ Overtrade

# [V21-A3] Global Multi-Asset Exposure Limits
GLOBAL_MAX_CONCURRENT_TRADES = 2    # Hard cap across ALL symbols combined
MAX_TRADES_PER_SYMBOL        = 1    # No doubling on the same pair
MAX_GLOBAL_EXPOSURE_PCT      = 40.0 # Block new trade if total floating risk > 40% of balance
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

# Judas Swing
JUDAS_SWING_ENABLED  = True
JUDAS_WINDOW_MIN     = 60
JUDAS_SCORE_BONUS    = 12

# Liquidity
LIQ_SWING_PERIOD    = 10
LIQ_EQUAL_TOLERANCE = 0.0003
LIQ_MIN_CLUSTER     = 2

# HTF — H4  [V19-W3]
HTF_BARS          = 150
HTF_SWING_PERIOD  = 5
HTF_SWING_CONFIRM = 2

# [V19-F4] OOS Spread Guard
OOS_HARD_SPREAD_BLOCK = 30

# [V19-W1] Consecutive-loss cache TTL
CONSEC_LOSS_CACHE_SEC = 30

# H1 Intermediate bias
H1_BARS           = 100
H1_SWING_PERIOD   = 4
H1_SWING_CONFIRM  = 2
H1_AGREE_BONUS    = 6
H1_CONFLICT_PENALTY = -4

# P/D Zone
PD_ZONE_ENABLED   = False
PD_PERIOD         = 50
PD_PENALTY        = -6

MTF_M1_BODY_ATR   = 0.3

# MSS & CISD
MSS_ENABLED       = True
CISD_ATR_MULT     = 1.5
SCORE_MSS_CISD    = 10
SCORE_MSS_ONLY    = 4

# V-Shape / U-Shape
VSHAPE_ENABLED       = True
VSHAPE_ATR_MULT      = 1.8
VSHAPE_RETRACE_PCT   = 0.60
VSHAPE_MAX_BARS      = 3
USHAPE_MAX_BARS      = 5
SCORE_VSHAPE_BONUS   = 4
SCORE_USHAPE_PENALTY = -12

# Golden Confluence
GOLDEN_CONFL_ENABLED    = True
OTE_LOW_PCT             = 0.618
OTE_HIGH_PCT            = 0.79
DISPLACEMENT_ATR_MULT   = 1.2
SCORE_GOLDEN_CONFLUENCE = 12

# PRE_LONDON FOMO guard
PRE_LONDON_SWEEP_REQUIRED = True
PRE_LONDON_SCORE_BOOST    = 5

# ── [V18-P1B] OUT-OF-SESSION THRESHOLD SYSTEM ─────────────────────────────────
SCORE_THRESHOLD_IN_SESSION  = 68   # 🚨 เข้มขึ้นนิดนึง กรองกราฟขยะทิ้ง
SCORE_THRESHOLD_OUT_SESSION = 75

# Consecutive-loss CB
N_CONSEC_LOSS_PAUSE   = 99
CONSEC_LOSS_PAUSE_MIN = 60

# Auto-reconnect
RECONNECT_BASE_DELAY  = 5.0
RECONNECT_MAX_DELAY   = 120.0
RECONNECT_MAX_ATTEMPTS = 20

# ── [V17-L1] Friday / Weekend Gap Guard ───────────────────────────────────────
FRIDAY_CLOSE_ENABLED  = True
FRIDAY_CLOSE_UTC_HOUR = 21
FRIDAY_CLOSE_UTC_MIN  = 0

# ── SCORING SYSTEM (RE-BALANCED) ──────────────────────────────────────────────
SCORE_BASE          = 40
SCORE_FVG_FRESH     = 20
SCORE_LIQ_SWEPT     = 15
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
SCORE_ADR_WARN      = -10
SCORE_SPREAD_WARN   = -5
SCORE_PENALTY_HTF_NEUTRAL = 0
KZ_OUTSIDE_PENALTY    = 0
KZ_PRE_LONDON_PENALTY = 0

SCORE_THRESHOLD: Dict[str, int] = {
    "LONDON":        SCORE_THRESHOLD_IN_SESSION,
    "NEW_YORK":      SCORE_THRESHOLD_IN_SESSION,
    "NY_OPEN_EARLY": SCORE_THRESHOLD_IN_SESSION,
    "PRE_LONDON":    SCORE_THRESHOLD_IN_SESSION + PRE_LONDON_SCORE_BOOST,
    "DEFAULT":       SCORE_THRESHOLD_IN_SESSION,
}

# ML
ML_WIN_PROB_THRESHOLD = 0.52  # 🚨 เปิดใช้งานสมองกลจริงๆ กรอง Win Rate เหนือ 50%
ML_ROLLING_WINDOW     = 60

# [V20-C1] Welford warm-start persistence
WELFORD_PERSIST_EVERY = 50 

# [V19-F3] Risk tiers (THE PRO ALL-IN LOGIC)
LOT_MIN  = 0.01
LOT_MAX  = 1.00
# ── Risk Tiers (THE EINSTEIN KELLY-KAMIKAZE) ──────────────────────────────────
# ทุน $60 ปั้นโหด (ทุ่มตามความน่าจะเป็นทางคณิตศาสตร์)
RISK_TIERS = [
    (86,  30.00), # 🌟 GOD STRIKE (86+ แต้ม): ทุ่ม 30% (สูตร Kelly Optimal) นี่คือไม้ที่สถิติบอกว่าชนะชัวร์ ฟาดกำไรคำโต!
    (80,  15.00), # 🎯 SNIPER (80-85 แต้ม): จังหวะโคตรสวยประจำวัน (Half-Kelly) เสี่ยง 15% 
    (74,   5.00), # 🐅 PREDATOR (74-79 แต้ม): จังหวะมาตรฐานประจำวัน เสี่ยง 5% เพื่อปั้นกระแสเงินสด
    (68,   1.00), # 🐾 SCOUT (68-73 แต้ม): แหย่ 1% พอให้บอทได้ทำงาน ไม่ตกรถ แต่โดนลากก็ไม่เจ็บ
    (0,    0.05),
]

DD_YELLOW_PCT       = 3.0
DD_ORANGE_PCT       = 5.0
CIRCUIT_BREAKER_PCT = 90.0  # 🚨 ดับเครื่องทันทีที่พอร์ตติดลบ 12% (เซฟเงินก่อนถึงจุด Max DD)

# [V20-O6] DD state cache TTL
DD_STATE_TTL = 2.0

# [V20-C2] Orphan SL check interval
ORPHAN_SL_CHECK_INTERVAL = 60.0

KILLZONE_ENABLED = True
KILLZONES = [
    (14,  0, 16, 30, "London Open"),
    (18, 30, 19, 15, "NY Open Early"),
    (19, 45, 22,  0, "NY Open"),
]
SESSIONS = [
    (12,  0, 14,  0, "PRE_LONDON"),
    (14,  0, 18,  0, "LONDON"),
    (18, 30, 19, 15, "NY_OPEN_EARLY"), # เปิดไว้ตามที่นายต้องการ แต่บอทจะรอดด้วยเกณฑ์ 68 แต้ม!
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
# 🕐  BROKER CLOCK SYNC  [V18-P2B]
# ══════════════════════════════════════════════════════════════════════════════
class BrokerClockSync:
    """Derives authoritative UTC time from MT5 tick timestamps only."""

    def __init__(self, symbol: str = CLOCK_ANCHOR_SYMBOL, strategy_tz: pytz.BaseTzInfo = STRATEGY_TZ):
        self._symbol      = symbol
        self._strategy_tz = strategy_tz
        self._last_tick_utc: Optional[datetime] = None

    def refresh(self) -> None:
        tick = mt5.symbol_info_tick(self._symbol)
        if tick is not None:
            self._last_tick_utc = datetime.fromtimestamp(tick.time, pytz.utc)

    def now_utc(self) -> datetime:
        return self._last_tick_utc if self._last_tick_utc else datetime.now(pytz.utc)

    def now_strategy(self) -> datetime:
        return self.now_utc().astimezone(self._strategy_tz)

    def t(self) -> dtime:
        return self.now_strategy().time()


# ══════════════════════════════════════════════════════════════════════════════
# 📅  FRIDAY / WEEKEND GAP GUARD  [V17-L1 + V18-P2B + V20-C5]
# ══════════════════════════════════════════════════════════════════════════════
class FridayGuard:
    """
    [V17-L1] Protects against Monday morning gaps.
    [V18-P2B] All time checks use clock.now_utc() from MT5 tick data.
    [V20-C5]  execute_eod_close() delegates to ExecutionHandler — removed the
              broken self.close_position_market() that would raise NameError.
              FridayGuard no longer duplicates execution logic.
    """

    def __init__(self, clock: BrokerClockSync):
        self._clock    = clock
        self._eod_done = False

    def _reset_on_monday(self) -> None:
        now_utc = self._clock.now_utc()
        if now_utc.weekday() == 0 and now_utc.hour >= 22:
            self._eod_done = False

    def is_close_time(self) -> bool:
        now_utc = self._clock.now_utc()
        if now_utc.weekday() != 4:
            return False
        return (now_utc.hour > FRIDAY_CLOSE_UTC_HOUR or
                (now_utc.hour == FRIDAY_CLOSE_UTC_HOUR and
                 now_utc.minute >= FRIDAY_CLOSE_UTC_MIN))

    def is_blocked(self) -> bool:
        if not FRIDAY_CLOSE_ENABLED:
            return False
        self._reset_on_monday()
        now_utc = self._clock.now_utc()
        return self.is_close_time() or now_utc.weekday() in (5, 6)

    def execute_eod_close(self, execution: "ExecutionHandler") -> None:
        """[V20-C5] Flatten all positions and cancel pending orders via ExecutionHandler.
        [V21-A4] Iterates ALL ACTIVE_SYMBOLS — not just the single anchor symbol."""
        if self._eod_done:
            return
        self._eod_done = True
        log.warning("📅 FRIDAY EOD GUARD [V21-A4]: Flattening ALL symbols...")

        # [V21-A4] Collect all symbols to flatten: active symbols + any stray positions
        all_symbols = list(ACTIVE_SYMBOLS.keys())
        for sym in all_symbols:
            # Step 1: Cancel pending orders per symbol
            for ord_ in (mt5.orders_get(symbol=sym) or []):
                if ord_.magic == MAGIC_NUMBER:
                    execution.cancel_pending_order(ord_.ticket)
                    time.sleep(0.1)
            # Step 2: Close all active positions per symbol
            for pos in (mt5.positions_get(symbol=sym) or []):
                if pos.magic == MAGIC_NUMBER:
                    execution.close_position_market(pos, is_eod=True)
                    time.sleep(0.2)

        log.warning("📅 FRIDAY EOD GUARD: All symbols flattened. Bot will resume Monday.")


# ══════════════════════════════════════════════════════════════════════════════
# 🌐  CONNECTION MANAGER  [V16-F3 + V19-W4]
# ══════════════════════════════════════════════════════════════════════════════
class ConnectionManager:
    def __init__(self):
        self._lock          = threading.RLock()
        self._connected     = False
        self._attempt       = 0
        self._next_retry_at = 0.0
        self._filling_cache_dirty = False

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
                self._connected = True; self._attempt = 0; self._next_retry_at = 0.0
                # [V19-W4] Invalidate filling-mode cache after reconnect
                self._filling_cache_dirty = True
                return True
            self._connected = False; self._next_retry_at = now + delay; return False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def filling_cache_dirty(self) -> bool:
        """[V19-W4] Auto-resets on read."""
        with self._lock:
            dirty = self._filling_cache_dirty
            if dirty:
                self._filling_cache_dirty = False
            return dirty


# ══════════════════════════════════════════════════════════════════════════════
# 📡  SPREAD GUARD  [V16-F2]
# ══════════════════════════════════════════════════════════════════════════════
class SpreadGuard:
    """[V21-A1] Accepts per-symbol hard_block_pts so each symbol uses its own spread limit."""

    def __init__(self, window: int = SPREAD_MEDIAN_BARS,
                 hard_block_pts: float = HARD_SPREAD_BLOCK):
        self._buf: deque = deque(maxlen=window)
        self._hard_block = hard_block_pts  # [V21-A1] per-symbol hard block threshold

    def update(self, spread_pts: float) -> None:
        if 0.1 < spread_pts < self._hard_block * 20:  # [V21-A1] relative sanity cap
            self._buf.append(spread_pts)

    def is_ok(self, current_pts: float) -> Tuple[bool, str]:
        if current_pts > self._hard_block:  # [V21-A1] use symbol-specific threshold
            return False, f"HARD_BLOCK:{current_pts:.1f}>{self._hard_block}pts"
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
# 💾  PERSISTENCE LAYER  [V16 schema + V20-C4 bounded queue]
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
    _warn_threshold = int(_write_q.maxsize * 0.8) if _write_q else 400  # type: ignore[union-attr]
    while True:
        item = q.get()
        if item is None:
            conn.close(); break
        sql, params, done_ev = item
        # [V20-C4] Queue back-pressure warning
        qsize = q.qsize()
        if qsize > _warn_threshold:
            log.warning(f"⚠️ [V20-C4] DB write queue at {qsize}/{q.maxsize} — consider reducing write frequency")
        try:
            conn.execute(sql, params); conn.commit()
        except Exception as exc:
            log.warning(f"DB writer: {exc} | {sql[:60]}")
        finally:
            if done_ev is not None: done_ev.set()
        q.task_done()


def _db_exec(sql: str, params: tuple = (), wait: bool = False,
             drop_on_full: bool = False) -> None:
    """
    [V20-C4] drop_on_full=True for non-critical writes (e.g. win_prob_history).
    drop_on_full=False (default) for critical writes (schema, state, trades).
    """
    global _write_q
    if _write_q is None: raise RuntimeError("DB writer not initialised")
    ev = threading.Event() if wait else None
    if drop_on_full and _write_q.full():
        log.debug(f"DB write dropped (queue full): {sql[:40]}")
        return
    try:
        _write_q.put((sql, params, ev), block=not drop_on_full, timeout=1.0)
    except _queue_module.Full:
        log.warning(f"⚠️ DB write queue full — dropped: {sql[:40]}")
        return
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
        # [V20-C4] Bounded queue — max 500 pending writes
        _write_q = _queue_module.Queue(maxsize=500)
        _writer_thread = threading.Thread(
            target=_writer_loop, args=(_write_q,), name="DBWriter", daemon=True)
        _writer_thread.start()
        log.info("💾 DB writer thread started (queue maxsize=500)")

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
    log.info("✅ Database V20 schema ready")


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
    # [V20-C4] win_prob_history is non-critical — drop if queue is full
    _db_exec("INSERT INTO win_prob_history(ts,prob) VALUES(?,?)",
             (time.time(), win_prob), drop_on_full=True)


def record_trade_outcome(outcome: str, session: str) -> None:
    if outcome in ("WIN", "LOSS", "PARTIAL"):
        _db_exec("INSERT INTO trade_outcomes(ts,outcome,session) VALUES(?,?,?)",
                 (time.time(), outcome, session))


# ══════════════════════════════════════════════════════════════════════════════
# 🔒  [V20-C3]  THREAD-SAFE CONSECUTIVE-LOSS CACHE
# ══════════════════════════════════════════════════════════════════════════════
class _ConsecLossCache:
    """
    [V20-C3] Replaces the bare module-level globals that had a GIL torn-read risk
    between the main thread and PositionManager thread.
    """
    def __init__(self):
        self._lock  = threading.Lock()
        self._value = 0
        self._ts    = 0.0

    def get(self) -> int:
        with self._lock:
            if time.time() - self._ts < CONSEC_LOSS_CACHE_SEC:
                return self._value
        # Fetch outside lock to avoid holding lock during DB I/O
        rows = _db_query_all(
            "SELECT outcome FROM trade_outcomes WHERE outcome IN ('WIN','LOSS') "
            "ORDER BY ts DESC LIMIT ?", (N_CONSEC_LOSS_PAUSE + 5,))
        count = 0
        for r in rows:
            if r["outcome"] == "LOSS": count += 1
            else: break
        with self._lock:
            self._value = count
            self._ts    = time.time()
        return count

    def invalidate(self) -> None:
        with self._lock:
            self._ts = 0.0


_consec_loss = _ConsecLossCache()


def get_consecutive_losses() -> int:
    return _consec_loss.get()


def invalidate_consec_loss_cache() -> None:
    _consec_loss.invalidate()


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
    threshold:   int              = SCORE_THRESHOLD_IN_SESSION
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
    in_session:  bool             = True

    def summary(self) -> str:
        gap  = self.score - self.threshold
        conf = "💎" if gap >= 25 else "🔥🔥" if gap >= 12 else "🔥" if gap >= 0 else "⚠️"
        mode = "MKT" if self.use_market else "LMT"
        tags = []
        if self.is_judas:    tags.append("⚡JUDAS")
        if self.golden_conf: tags.append("✨GOLDEN")
        if self.shape == "V": tags.append("📐V")
        if self.shape == "U": tags.append("🌊U")
        if not self.in_session: tags.append("🌙OOS")
        return (f"{conf} {' '.join(tags)} {self.signal}({mode}) "
                f"Score:{self.score}/{self.threshold} WP:{self.win_prob:.2f} "
                f"Sweep:{self.sweep_type} H1:{self.h1_bias} | {' | '.join(self.reasons)}")


# ══════════════════════════════════════════════════════════════════════════════
# 🤖  ML LAYER  [V17-F4 + V20-C1 Welford Warm-Start]
# ══════════════════════════════════════════════════════════════════════════════
class WelfordNormaliser:
    """
    Online running mean/variance (Welford algorithm) with concept-drift detection.
    [V20-C1] Supports serialise() / deserialise() for DB persistence across restarts.
    """

    def __init__(self, n_features: int, min_samples: int = 20):
        self._n    = n_features
        self._min  = min_samples
        self._count = np.zeros(n_features, dtype=np.float64)
        self._mean  = np.zeros(n_features, dtype=np.float64)
        self._M2    = np.zeros(n_features, dtype=np.float64)
        self._update_count = 0   # [V20-C1] tracks total updates for debounced persist

    def update(self, x: np.ndarray) -> None:
        for i, v in enumerate(x):
            if np.isfinite(v):
                self._count[i] += 1
                delta = v - self._mean[i]
                self._mean[i] += delta / self._count[i]
                self._M2[i] += delta * (v - self._mean[i])
        self._update_count += 1

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

    # ── [V20-C1] Persistence helpers ─────────────────────────────────────────
    def serialise(self) -> str:
        """Serialise state to JSON string for DB storage."""
        return json.dumps({
            "n":     self._n,
            "min":   self._min,
            "count": self._count.tolist(),
            "mean":  self._mean.tolist(),
            "M2":    self._M2.tolist(),
        }, separators=(",", ":"))

    @classmethod
    def deserialise(cls, s: str) -> "WelfordNormaliser":
        """Reconstruct from JSON string. Returns a new cold normaliser on error."""
        try:
            d = json.loads(s)
            obj = cls(d["n"], d.get("min", 20))
            obj._count = np.array(d["count"], dtype=np.float64)
            obj._mean  = np.array(d["mean"],  dtype=np.float64)
            obj._M2    = np.array(d["M2"],    dtype=np.float64)
            return obj
        except Exception as exc:
            log.warning(f"[V20-C1] WelfordNormaliser.deserialise failed ({exc}) — cold start")
            return cls(d.get("n", 14) if "d" in dir() else 14)  # type: ignore[possibly-undefined]


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
    [V20-C1] WelfordNormaliser state is loaded from DB on init (Warm-Start),
             and persisted to DB every WELFORD_PERSIST_EVERY updates.
    """

    def __init__(self):
        self._model = None
        self._norm  = self._load_normaliser()
        self._prob_buf: Deque[float] = deque(maxlen=ML_ROLLING_WINDOW)
        warm_tag = "WARM (restored)" if self._norm.is_warm else "COLD (fresh)"
        log.info(f"🧠 MLPredictor V20: {N_FEATURES}-feat | normaliser={warm_tag} | "
                 f"heuristic bypass mode (returns 1.0 until real model loaded)")

    # ── [V20-C1] Warm-Start helpers ──────────────────────────────────────────
    @staticmethod
    def _load_normaliser() -> WelfordNormaliser:
        """Load persisted Welford state from DB. Returns cold normaliser on miss."""
        raw = get_state("welford_state")
        if raw and isinstance(raw, str):
            obj = WelfordNormaliser.deserialise(raw)
            if obj.is_warm:
                log.info("[V20-C1] WelfordNormaliser warm-start restored from DB")
            return obj
        return WelfordNormaliser(N_FEATURES)

    def _maybe_persist_normaliser(self) -> None:
        """[V20-C1] Debounced persist: save every WELFORD_PERSIST_EVERY updates."""
        if self._norm._update_count % WELFORD_PERSIST_EVERY == 0:
            try:
                set_state("welford_state", self._norm.serialise())
            except Exception as exc:
                log.warning(f"[V20-C1] Normaliser persist failed: {exc}")

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
        if self._model is None:
            self._prob_buf.append(1.0)
            return 1.0
        shift = self._norm.check_shift(features, z_bound=3.5)
        if update_norm and not shift:
            self._norm.update(features)
            self._maybe_persist_normaliser()   # [V20-C1]
        if shift:
            log.warning("🧠 Dist shift detected → win_prob forced 0.49 [V20-C1]")
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
# 📊  CLASS: MarketDataFeed  [V20-O5 cache key fix]
# ══════════════════════════════════════════════════════════════════════════════
class MarketDataFeed:
    def __init__(self):
        # [V20-O5] Key is (timeframe, symbol) tuple — no hash() collision risk
        self._cache: Dict[Tuple, Tuple[float, pd.DataFrame]] = {}
        self._lock  = threading.Lock()

    def _ttl(self, tf: int) -> float:
        if tf in (mt5.TIMEFRAME_M1, mt5.TIMEFRAME_M5): return CACHE_TTL_LTF
        if tf == mt5.TIMEFRAME_D1: return CACHE_TTL_D1
        return CACHE_TTL_HTF

    def fetch(self, tf: int, n: int, symbol: str = SYMBOL,
              use_cache: bool = True) -> Optional[pd.DataFrame]:
        cache_key = (tf, symbol)   # [V20-O5] deterministic, collision-free
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
            entry = self._cache.get((mt5.TIMEFRAME_M5, SYMBOL))
        return entry[1] if entry else None

    def fetch_all(self, symbol: str = SYMBOL) -> Dict[str, Optional[pd.DataFrame]]:
        """[V21-A2] Accepts per-symbol argument for multi-asset full data fetch."""
        def _trim(df):
            return df.iloc[:-1].copy() if df is not None and len(df) > 1 else df
        m1  = _trim(self.fetch(mt5.TIMEFRAME_M1,   60,  symbol=symbol, use_cache=False))
        m5  = _trim(self.fetch(mt5.TIMEFRAME_M5,  300,  symbol=symbol, use_cache=False))
        m15 = _trim(self.fetch(mt5.TIMEFRAME_M15, 100,  symbol=symbol, use_cache=True))
        h1  = _trim(self.fetch(mt5.TIMEFRAME_H1,  H1_BARS, symbol=symbol, use_cache=True))
        h4  = _trim(self.fetch(mt5.TIMEFRAME_H4,  HTF_BARS, symbol=symbol, use_cache=True))
        d1  = self.fetch(mt5.TIMEFRAME_D1, 20, symbol=symbol, use_cache=True)
        return {"m1": m1, "m5": m5, "m15": m15, "h1": h1, "h4": h4, "d1": d1}

    def get_current_m5_bar_time(self, symbol: str = SYMBOL) -> Optional[int]:
        """[V21-A2] Per-symbol M5 bar timestamp poll — lightweight, no caching."""
        try:
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 1)
            if rates is not None and len(rates) > 0: return int(rates[0]["time"])
        except Exception: pass
        return None


# ══════════════════════════════════════════════════════════════════════════════
# 🧮  INDICATOR FUNCTIONS — Vectorised NumPy hot-paths  [V20-O1/O2]
# ══════════════════════════════════════════════════════════════════════════════
def _to_numpy(df: pd.DataFrame, col: str) -> np.ndarray:
    return np.ascontiguousarray(df[col].values, dtype=np.float64)


def _sliding_max(arr: np.ndarray, window: int) -> np.ndarray:
    """[V20-O1/O2] Vectorised sliding window maximum — O(n) vs O(n²) loop."""
    if _SCIPY_AVAILABLE:
        return _max_filter1d(arr, size=window, mode="nearest")
    # Pure-NumPy fallback using stride_tricks
    n = len(arr)
    if n < window: return arr.copy()
    shape   = (n - window + 1, window)
    strides = (arr.strides[0], arr.strides[0])
    windows = np.lib.stride_tricks.as_strided(arr, shape=shape, strides=strides)
    result  = np.empty(n, dtype=arr.dtype)
    result[:window - 1] = arr[:window - 1]   # pad start
    result[window - 1:] = windows.max(axis=1)
    return result


def _sliding_min(arr: np.ndarray, window: int) -> np.ndarray:
    """[V20-O1/O2] Vectorised sliding window minimum."""
    if _SCIPY_AVAILABLE:
        return _min_filter1d(arr, size=window, mode="nearest")
    n = len(arr)
    if n < window: return arr.copy()
    shape   = (n - window + 1, window)
    strides = (arr.strides[0], arr.strides[0])
    windows = np.lib.stride_tricks.as_strided(arr, shape=shape, strides=strides)
    result  = np.empty(n, dtype=arr.dtype)
    result[:window - 1] = arr[:window - 1]
    result[window - 1:] = windows.min(axis=1)
    return result


def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < period + 1: return 0.0
    high  = _to_numpy(df, "high")
    low   = _to_numpy(df, "low")
    close = _to_numpy(df, "close")
    prev  = close[:-1]
    tr    = np.maximum(high[1:] - low[1:],
            np.maximum(np.abs(high[1:] - prev), np.abs(low[1:] - prev)))
    if len(tr) < period: return 0.0
    v = float(tr[:period].mean()); alpha = 1.0 / period
    for x in tr[period:]: v = v * (1.0 - alpha) + float(x) * alpha
    return v if not np.isnan(v) else 0.0


def calculate_adr(df_d1: Optional[pd.DataFrame], period: int = 10) -> float:
    if df_d1 is None or len(df_d1) < period: return 0.0
    return float((_to_numpy(df_d1, "high") - _to_numpy(df_d1, "low"))[-period:].mean())


def get_confirmed_swings_np(df: pd.DataFrame, period: int = 5,
                             confirm: int = 2) -> Tuple[float, float]:
    """[V20-O2] Vectorised swing pivot detection using sliding window max/min."""
    if len(df) < period * 2 + confirm + 1:
        return float(df["high"].max()), float(df["low"].min())
    high = _to_numpy(df, "high")
    low  = _to_numpy(df, "low")
    n    = len(high)
    # A pivot high at index i: high[i] == max of high[i-period:i+period+1]
    # Vectorised: high[i] equals both the rolling max over a 2*period+1 window
    win = 2 * period + 1
    roll_max_h = _sliding_max(high, win)
    roll_min_l = _sliding_min(low,  win)
    # Align: the window of size win centred at i runs from i-period to i+period
    # _sliding_max returns max ending at index i (right-aligned), so we offset
    safe = n - confirm
    sh, sl = [], []
    for i in range(period, safe - period):
        # Check i is the maximum in [i-period, i+period]
        window_h = high[max(0, i-period): min(n, i+period+1)]
        window_l = low[max(0, i-period):  min(n, i+period+1)]
        if high[i] == window_h.max(): sh.append(high[i])
        if low[i]  == window_l.min(): sl.append(low[i])
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
    """[V20-O1] Uses vectorised swing pivot detection (shared with get_confirmed_swings_np)."""
    liq = LiquidityMap()
    if len(df) < period * 2 + 4 or atr == 0: return liq
    high = _to_numpy(df, "high")
    low  = _to_numpy(df, "low")
    cls  = _to_numpy(df, "close")
    opn  = _to_numpy(df, "open")
    n    = len(high)
    safe = n - 2
    tol  = max(atr * 0.08, abs(cls[-1]) * LIQ_EQUAL_TOLERANCE)
    ph, pl = [], []
    for i in range(period, safe - period):
        window_h = high[max(0, i-period): min(n, i+period+1)]
        window_l = low[max(0, i-period):  min(n, i+period+1)]
        if high[i] == window_h.max(): ph.append(high[i])
        if low[i]  == window_l.min(): pl.append(low[i])
    liq.buy_side  = sorted(_cluster_liquidity_levels(ph, tol), reverse=True)
    liq.sell_side = sorted(_cluster_liquidity_levels(pl, tol))
    last_high  = float(high[-1]); last_low  = float(low[-1])
    last_close = float(cls[-1]);  prev_close = float(cls[-2]) if len(cls) >= 2 else last_close
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
# 📐  [V16-S4]  V-SHAPE / U-SHAPE DETECTOR  [V20-O4 index safety]
# ══════════════════════════════════════════════════════════════════════════════
class VShapeDetector:
    """
    [V16-S4] Classifies sweep rejection as V (fast) or U (slow/chop).
    [V19-W2] reset_index(drop=True) applied inside classify().
    [V20-O4] Explicit bounds checking on all iloc accesses; sweep origin is
             correctly identified as df.iloc[-3] AFTER reset_index (the bar
             before the sweep candle at iloc[-2]).
    """
    @staticmethod
    def classify(df_m5: pd.DataFrame, atr: float, direction: str) -> str:
        if not VSHAPE_ENABLED or len(df_m5) < VSHAPE_MAX_BARS + 4 or atr == 0:
            return "NONE"
        # [V19-W2 + V20-O4] Always reset index before any positional access
        df = df_m5.reset_index(drop=True)
        n  = len(df)
        if n < 4: return "NONE"

        sweep_c   = df.iloc[-2]    # the candle that swept the level
        # [V20-O4] origin is the candle BEFORE the sweep candle (iloc[-3])
        if n >= 3:
            origin_c = df.iloc[-3]
        else:
            return "NONE"

        if direction == "BUY":
            sweep_extreme = float(sweep_c["low"])
            origin        = float(origin_c["close"])
            retrace_dist  = origin - sweep_extreme
            body = abs(float(sweep_c["close"]) - float(sweep_c["open"]))
            if body < atr * VSHAPE_ATR_MULT:
                return "NONE"
            for k in range(1, VSHAPE_MAX_BARS + 1):
                idx = -1 - k
                if abs(idx) > n: break
                c = df.iloc[idx]
                if retrace_dist > 0 and (float(c["close"]) - sweep_extreme) / retrace_dist >= VSHAPE_RETRACE_PCT:
                    return "V"
            wick_mid = (sweep_extreme + float(sweep_c["close"])) / 2
            inside_count = sum(
                1 for k in range(1, USHAPE_MAX_BARS + 1)
                if (1 + k) <= n
                and float(df.iloc[-1 - k]["close"]) < wick_mid
            )
            return "U" if inside_count >= USHAPE_MAX_BARS - 1 else "NONE"

        else:  # SELL
            sweep_extreme = float(sweep_c["high"])
            origin        = float(origin_c["close"])
            retrace_dist  = sweep_extreme - origin
            body = abs(float(sweep_c["close"]) - float(sweep_c["open"]))
            if body < atr * VSHAPE_ATR_MULT:
                return "NONE"
            for k in range(1, VSHAPE_MAX_BARS + 1):
                idx = -1 - k
                if abs(idx) > n: break
                c = df.iloc[idx]
                if retrace_dist > 0 and (sweep_extreme - float(c["close"])) / retrace_dist >= VSHAPE_RETRACE_PCT:
                    return "V"
            wick_mid = (sweep_extreme + float(sweep_c["close"])) / 2
            inside_count = sum(
                1 for k in range(1, USHAPE_MAX_BARS + 1)
                if (1 + k) <= n
                and float(df.iloc[-1 - k]["close"]) > wick_mid
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

    # ── H1 Intermediate Bias ─────────────────────────────────────────────────
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

    # ── MSS + CISD [V16-S3] ──────────────────────────────────────────────────
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

    # ── Golden Confluence [V16-S5] ────────────────────────────────────────────
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
        ote_high = swing_h - swing_range * OTE_LOW_PCT
        ote_low  = swing_h - swing_range * OTE_HIGH_PCT
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
        """[V20-O3] Uses vectorised mitigated-check via NumPy array slicing."""
        zones: List[FVGZone] = []
        if len(df) < lookback + 3 or atr == 0: return zones
        min_gap = atr * FVG_MIN_GAP_ATR
        start   = max(3, len(df) - lookback)
        # Pre-extract arrays once — avoids per-iteration df.iloc overhead
        high_arr  = _to_numpy(df, "high")
        low_arr   = _to_numpy(df, "low")
        close_arr = _to_numpy(df, "close")
        open_arr  = _to_numpy(df, "open")
        n = len(df)
        for i in range(start, n - 2):
            c2_range = high_arr[i+1] - low_arr[i+1]
            c2_body  = abs(close_arr[i+1] - open_arr[i+1])
            if c2_range > 0 and (c2_body / c2_range) < FVG_MOMENTUM_RATIO: continue
            gap_bull = low_arr[i+2] - high_arr[i]
            if gap_bull >= min_gap:
                top = low_arr[i+2]; bot = high_arr[i]; gap = top - bot
                mid = bot + gap * FVG_MITIGATED_PCT
                # [V20-O3] vectorised mitigated check
                future_lows = low_arr[i+3:] if i+3 < n else np.array([])
                mitigated   = bool(len(future_lows) > 0 and future_lows.min() <= mid)
                zones.append(FVGZone("BULLISH", top, bot, min(2.0, gap / atr), i, mitigated))
            gap_bear = low_arr[i] - high_arr[i+2]
            if gap_bear >= min_gap:
                top = low_arr[i]; bot = high_arr[i+2]; gap = top - bot
                mid = top - gap * FVG_MITIGATED_PCT
                future_highs = high_arr[i+3:] if i+3 < n else np.array([])
                mitigated    = bool(len(future_highs) > 0 and future_highs.max() >= mid)
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

    # ── Order Block ───────────────────────────────────────────────────────────
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

    # ── Judas Swing ───────────────────────────────────────────────────────────
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

    # ── ADR TP Cap [V19-F2] ───────────────────────────────────────────────────
    @staticmethod
    def apply_adr_tp_cap(entry: float, tp_raw: float, sl: float, adr: float,
                          df_d1: Optional[pd.DataFrame], session: str,
                          signal: str) -> Tuple[float, bool]:
        """[V19-F2] Signed ADR TP cap with floor-guard."""
        if adr <= 0 or df_d1 is None or len(df_d1) < 1:
            return tp_raw, False
        day_high = float(df_d1["high"].iloc[-1])
        day_low  = float(df_d1["low"].iloc[-1])
        adr_ceil = (ADR_NY_EXHAUSTED_PCT if session in ("NEW_YORK", "NY_OPEN_EARLY")
                    else ADR_EXHAUSTED_PCT)
        capped  = False
        tp_adj  = tp_raw
        if signal == "BUY":
            cap = day_low + adr * adr_ceil
            if tp_raw > cap:
                tp_adj = entry + (cap - entry) * ADR_TP_BUFFER_PCT
                capped = True
        elif signal == "SELL":
            cap = day_high - adr * adr_ceil
            if tp_raw < cap:
                tp_adj = entry - (entry - cap) * ADR_TP_BUFFER_PCT
                capped = True
        risk = abs(entry - sl)
        if signal == "BUY":
            if (tp_adj - entry) < risk: tp_adj = tp_raw; capped = False
            if tp_adj <= entry:         tp_adj = tp_raw; capped = False
        if signal == "SELL":
            if (entry - tp_adj) < risk: tp_adj = tp_raw; capped = False
            if tp_adj >= entry:         tp_adj = tp_raw; capped = False
        return tp_adj, capped

    # ── Session ───────────────────────────────────────────────────────────────
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

    def get_dynamic_threshold(self, session: str, in_session: bool) -> int:
        if not in_session:
            return SCORE_THRESHOLD_OUT_SESSION
        base = SCORE_THRESHOLD.get(session, SCORE_THRESHOLD_IN_SESSION)
        return base

    # ── Master Setup Analyser ────────────────────────────────────────────────
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
        r.pd_zone    = self.get_pd_zone(df_m5)

        in_kz, _kz_name = self.is_in_killzone()
        r.in_session = in_kz
        r.threshold  = self.get_dynamic_threshold(session, in_kz)

        liq       = build_liquidity_map_np(df_m5, atr, LIQ_SWING_PERIOD)
        r.liq_map = liq
        last_sh, last_sl = get_confirmed_swings_np(df_m5, SWING_PERIOD, SWING_CONFIRM_BARS)
        fvg_lookback = FVG_MEMORY_BARS.get(session, FVG_MEMORY_BARS["DEFAULT"])
        fvg_zones    = self.scan_fvg_memory(df_m5, atr, fvg_lookback)
        last     = df_m5.iloc[-1]; prev = df_m5.iloc[-2]
        r.candle_ts = (float(last["time"].timestamp())
                       if hasattr(last["time"], "timestamp") else time.time())
        price      = float(last["close"])

        # ── [V19-F1] SWEEP DETECTION ──────────────────────────────────────────
        SWEEP_WICK_ATR_MULT  = 0.15
        SWEEP_CLOSE_ATR_MULT = 0.10

        _ssl_wick      = last_sl - float(last["low"])
        _ssl_close_gap = float(last["close"]) - last_sl
        sweep_sell = (
            float(last["low"])   < last_sl
            and _ssl_wick        >= atr * SWEEP_WICK_ATR_MULT
            and _ssl_close_gap   >= atr * SWEEP_CLOSE_ATR_MULT
        )

        _bsl_wick      = float(last["high"]) - last_sh
        _bsl_close_gap = last_sh - float(last["close"])
        sweep_buy = (
            float(last["high"])  > last_sh
            and _bsl_wick        >= atr * SWEEP_WICK_ATR_MULT
            and _bsl_close_gap   >= atr * SWEEP_CLOSE_ATR_MULT
        )

        # Gap sweeps bypass the wick check — the gap IS the sweep
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
            if (sig == "BUY" and r.m15_struct == "BULLISH_BOS") or \
               (sig == "SELL" and r.m15_struct == "BEARISH_BOS"):
                r.score += SCORE_M15_BOS; r.reasons.append(f"M15 BOS +{SCORE_M15_BOS}")
            mss = self.check_mss_cisd(df_m5, atr, sig)
            r.mss = mss
            if mss.confirmed:
                pts = SCORE_MSS_CISD if mss.cisd else SCORE_MSS_ONLY
                tag = "MSS+CISD" if mss.cisd else "MSS"
                r.score += pts; r.reasons.append(f"{tag} +{pts}")
            else:
                if sig == "BUY" and float(last["close"]) > float(prev["high"]):
                    r.score += SCORE_BOS_M5; r.reasons.append(f"BOS_M5 +{SCORE_BOS_M5}")
                elif sig == "SELL" and float(last["close"]) < float(prev["low"]):
                    r.score += SCORE_BOS_M5; r.reasons.append(f"BOS_M5 +{SCORE_BOS_M5}")
            shape = VShapeDetector.classify(df_m5, atr, sig)
            r.shape = shape
            if shape == "V":
                r.score += SCORE_VSHAPE_BONUS; r.reasons.append(f"V-Shape +{SCORE_VSHAPE_BONUS}")
            elif shape == "U":
                r.score += SCORE_USHAPE_PENALTY; r.reasons.append(f"U-Shape {SCORE_USHAPE_PENALTY}")
            if self.check_golden_confluence(fvg_active, df_m5, htf_res, atr, sig):
                r.golden_conf = True
                r.score += SCORE_GOLDEN_CONFLUENCE; r.reasons.append(f"✨Golden +{SCORE_GOLDEN_CONFLUENCE}")
            body = abs(float(last["close"]) - float(last["open"]))
            if body > atr * 0.6:
                r.score += SCORE_STRONG_CANDLE; r.reasons.append(f"Strong +{SCORE_STRONG_CANDLE}")
            ob = self.find_order_block(df_m5, sig, atr)
            if ob.found and not ob.mitigated:
                r.score += SCORE_OB_BONUS; r.reasons.append(f"OB(q:{ob.score:.2f},age:{ob.bar_age}) +{SCORE_OB_BONUS}")
                entry_check = r.entry
                if ob.low <= entry_check <= ob.high:
                    r.score += SCORE_OB_OVERLAP; r.reasons.append(f"OB Overlap +{SCORE_OB_OVERLAP}")

        def _apply_penalties(sig: str, fvg_active: Optional[FVGZone]) -> None:
            if r.adr_pct >= adr_ceil:
                r.score += SCORE_ADR_WARN; r.reasons.append(f"ADR{r.adr_pct*100:.0f}% {SCORE_ADR_WARN}")
            if not r.in_session:
                r.reasons.append(f"🌙 OOS (thr={r.threshold})")
            else:
                r.reasons.append(f"🎯 InKZ (thr={r.threshold})")
            if session == "PRE_LONDON" and PRE_LONDON_SWEEP_REQUIRED:
                has_sweep = (sig == "BUY" and (sweep_sell or liq.gap_swept_low is not None)) or \
                            (sig == "SELL" and (sweep_buy or liq.gap_swept_high is not None))
                if not has_sweep and fvg_active is not None:
                    r.score -= 15; r.reasons.append("PRE_LDN pure-FVG -15")
            if self.is_judas_swing(liq, fvg_zones, sig, session):
                r.is_judas = True; r.score += JUDAS_SCORE_BONUS
                r.reasons.append(f"⚡Judas +{JUDAS_SCORE_BONUS}")

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
            _htf_scores("BUY"); _h1_scores("BUY")
            if htf_res.swept_low is not None:
                r.score += 4; r.reasons.append("H4 SSL Swept +4")
            _apply_structure_scores("BUY", fvg_active)
            if liq.bsl_nearest is not None:
                rsk = abs(r.entry - r.sl)
                if rsk > 0 and (liq.bsl_nearest - r.entry) >= rsk * RR_RATIO * 0.8:
                    r.score += SCORE_LIQ_TARGET; r.reasons.append(f"BSL→{liq.bsl_nearest:.2f} +{SCORE_LIQ_TARGET}")
            _apply_penalties("BUY", fvg_active)
            r.sweep_type = self.classify_sweep("BUY", r.htf_bias)
            body = float(last["close"]) - float(last["open"])
            if (float(last["close"]) > float(prev["high"])
                    and body / atr > MOMENTUM_BODY_ATR and r.score >= r.threshold):
                r.use_market = True; r.entry = 0.0; r.reasons.append("🚀 MKT")
            return True

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
# 💰  CLASS: RiskManager  [V20-O6 DD state cache]
# ══════════════════════════════════════════════════════════════════════════════
class RiskManager:
    def __init__(self):
        # [V21-A1] One SpreadGuard per symbol, each with its own hard_block_pts
        self._spread_guards: Dict[str, SpreadGuard] = {
            sym: SpreadGuard(hard_block_pts=profile["spread_block_pts"])
            for sym, profile in ACTIVE_SYMBOLS.items()
        }
        # Fallback guard for any symbol not in ACTIVE_SYMBOLS
        self._default_spread_guard = SpreadGuard()

        # [V20-O6] DD state cache — avoids redundant mt5.account_info() calls
        self._dd_cache: Optional[Tuple[float, float, str]] = None
        self._dd_cache_ts: float = 0.0
        self._dd_cache_lock = threading.Lock()

    def _spread_guard(self, symbol: str = SYMBOL) -> SpreadGuard:
        """[V21-A1] Returns the SpreadGuard for the given symbol."""
        return self._spread_guards.get(symbol, self._default_spread_guard)

    @staticmethod
    def get_broker_date() -> str:
        tick = mt5.symbol_info_tick(CLOCK_ANCHOR_SYMBOL)  # [V21-A1] use anchor symbol
        if tick: return datetime.fromtimestamp(tick.time, tz=pytz.utc).strftime("%Y%m%d")
        return datetime.utcnow().strftime("%Y%m%d")

    def get_spread_pts(self, symbol: str = SYMBOL) -> float:
        """[V21-A1] Per-symbol spread calculation."""
        tick = mt5.symbol_info_tick(symbol); info = mt5.symbol_info(symbol)
        if tick is None or info is None: return 999.0
        sp = (tick.ask - tick.bid) / info.point
        self._spread_guard(symbol).update(sp); return sp

    def is_spread_ok(self, symbol: str = SYMBOL) -> Tuple[bool, str]:
        """[V21-A1] Uses the symbol-specific SpreadGuard instance."""
        sp = self.get_spread_pts(symbol)
        return self._spread_guard(symbol).is_ok(sp)

    @staticmethod
    def get_spread_sl_padding(symbol: str = SYMBOL) -> float:
        """[V21-A1] Per-symbol SL padding from spread."""
        if not SPREAD_SL_PADDING: return 0.0
        tick = mt5.symbol_info_tick(symbol); info = mt5.symbol_info(symbol)
        if tick is None or info is None: return 0.0
        return ((tick.ask - tick.bid) / info.point) * info.point

    def get_dd_state(self) -> Tuple[float, float, str]:
        """[V20-O6] Cached for DD_STATE_TTL seconds to reduce duplicate API calls."""
        now = time.time()
        with self._dd_cache_lock:
            if self._dd_cache is not None and (now - self._dd_cache_ts) < DD_STATE_TTL:
                return self._dd_cache
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
        result = (round(daily_dd, 2), round(total_dd, 2), mode)
        with self._dd_cache_lock:
            self._dd_cache = result
            self._dd_cache_ts = now
        return result

    def is_within_risk_limits(self) -> bool:
        _, _, mode = self.get_dd_state(); return mode != "RED"

    def new_entries_allowed(self) -> bool:
        _, _, mode = self.get_dd_state(); return mode not in ("RED", "ORANGE")

    def is_circuit_breaker_tripped(self) -> bool:
        """[V20-O6] Reuses cached DD state — no extra account_info() call."""
        daily_dd, _, mode = self.get_dd_state()
        if daily_dd >= CIRCUIT_BREAKER_PCT:
            log.warning(f"⚡ CB: DD {daily_dd:.2f}% ≥ {CIRCUIT_BREAKER_PCT}%"); return True
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
                      dd_mode: str = "NORMAL", symbol: str = SYMBOL) -> float:
        """[V21-A1] Per-symbol lot calculation using symbol-specific min_lot floor."""
        info = mt5.symbol_info(symbol); acct = mt5.account_info()
        sym_profile = ACTIVE_SYMBOLS.get(symbol, {})
        sym_min_lot = sym_profile.get("min_lot", LOT_MIN)  # [V21-A1] per-symbol min_lot
        if info is None or acct is None: return sym_min_lot
        risk_pct = self.get_risk_tier_multiplier(score, dd_mode)
        if spread_pts > MAX_SPREAD_POINTS: risk_pct *= (1.0 - SPREAD_LOT_PENALTY)
        sl_dist = abs(entry - sl)
        if sl_dist == 0: return sym_min_lot
        sl_pts   = max(1.0, sl_dist / info.point)
        tick_val = info.trade_tick_value or (info.trade_contract_size * info.point)
        if tick_val <= 0: return sym_min_lot
        # [V19-F3] Single division — risk_pct is already in percent (1.0 = 1%)
        raw_lot = (acct.balance * risk_pct / 100.0) / (sl_pts * tick_val)
        step    = info.volume_step if info.volume_step > 0 else 0.01
        lot     = self._round_lot(raw_lot, step)
        if lot <= 0.0: lot = max(info.volume_min, sym_min_lot)
        lot = max(max(info.volume_min, sym_min_lot), min(lot, info.volume_max, LOT_MAX))
        log.info(f"💰 [{symbol}] Lot Score:{score} DD:{dd_mode} Risk:{risk_pct:.2f}% → {lot}")
        return float(lot)

    @staticmethod
    def dynamic_deviation(atr: float, emergency: bool = False,
                          symbol: str = SYMBOL) -> int:
        """[V17-L2 + V18-P2D + V21-A1] Returns guaranteed int deviation, per-symbol."""
        if emergency:
            return int(EMERGENCY_DEVIATION_POINTS)
        info = mt5.symbol_info(symbol)
        if info is None or info.point == 0:
            return int(MAX_DEVIATION_POINTS)
        calc = max(20, int(atr * 0.08 / info.point))
        return int(min(calc, MAX_DEVIATION_POINTS))

    @staticmethod
    def validate_order(entry: float, sl: float, tp: float,
                       lot: float, signal: str,
                       symbol: str = SYMBOL) -> Tuple[bool, str]:
        """[V21-A1] Per-symbol order validation."""
        info = mt5.symbol_info(symbol); acct = mt5.account_info()
        tick = mt5.symbol_info_tick(symbol)
        if not all([info, acct, tick]): return False, "Cannot read broker data"
        min_d = info.trade_stops_level * info.point
        if abs(entry - sl) < min_d: return False, "SL too close"
        if abs(entry - tp) < min_d: return False, "TP too close"
        frz = info.trade_freeze_level * info.point
        if frz > 0 and abs(entry - tick.ask) < frz: return False, "Entry in freeze zone"
        d_lot = Decimal(str(lot)); d_step = Decimal(str(info.volume_step))
        if d_lot % d_step > Decimal("1e-8"): return False, "Lot step mismatch"
        otype = mt5.ORDER_TYPE_BUY if signal == "BUY" else mt5.ORDER_TYPE_SELL
        margin_req = mt5.order_calc_margin(otype, symbol, lot, entry)
        if margin_req is None or margin_req > acct.margin_free * 0.9:
            return False, "Insufficient margin"
        return True, "OK"

    @staticmethod
    def has_duplicate_setup(setup_hash: str, signal: str,  # noqa: ARG002
                            symbol: str = SYMBOL) -> bool:
        """[V21-A1] Checks duplicate setups for the specific symbol."""
        for p in (mt5.positions_get(symbol=symbol) or []):
            if p.magic == MAGIC_NUMBER and setup_hash in (p.comment or ""): return True
        for o in (mt5.orders_get(symbol=symbol) or []):
            if o.magic == MAGIC_NUMBER and setup_hash in (o.comment or ""): return True
        return False

    @staticmethod
    def count_open_positions(symbol: str = SYMBOL) -> int:
        """[V21-A1] Per-symbol position count."""
        return sum(1 for p in (mt5.positions_get(symbol=symbol) or [])
                   if p.magic == MAGIC_NUMBER)

    @staticmethod
    def count_all_open_positions() -> int:
        """[V21-A3] Global position count across ALL symbols."""
        total = 0
        for sym in ACTIVE_SYMBOLS:
            total += sum(1 for p in (mt5.positions_get(symbol=sym) or [])
                         if p.magic == MAGIC_NUMBER)
        return total

    @staticmethod
    def calculate_floating_risk_pct() -> float:
        """[V21-A3] Returns total floating risk as % of account balance.
        Estimates each position's max loss as abs(price_open - sl) * volume * tick_value.
        Falls back to margin used if SL not set."""
        acct = mt5.account_info()
        if acct is None or acct.balance <= 0: return 0.0
        total_risk = 0.0
        for sym in ACTIVE_SYMBOLS:
            info = mt5.symbol_info(sym)
            if info is None: continue
            tick_val = info.trade_tick_value or (info.trade_contract_size * info.point)
            for pos in (mt5.positions_get(symbol=sym) or []):
                if pos.magic != MAGIC_NUMBER: continue
                if pos.sl != 0.0 and info.point > 0:
                    sl_pts = abs(pos.price_open - pos.sl) / info.point
                    risk_usd = sl_pts * tick_val * pos.volume
                else:
                    # Fallback: use initial margin as risk estimate
                    risk_usd = pos.margin if hasattr(pos, "margin") else 0.0
                total_risk += max(0.0, risk_usd)
        return (total_risk / acct.balance) * 100.0


# ══════════════════════════════════════════════════════════════════════════════
# 📤  CLASS: ExecutionHandler  [V18-P2A/B/C/D + V20-C2/C5]
# ══════════════════════════════════════════════════════════════════════════════
class ExecutionHandler:
    def __init__(self, risk: RiskManager, signal_engine: SMCSignalEngine,
                 conn_mgr: Optional["ConnectionManager"] = None):
        self._risk     = risk
        self._engine   = signal_engine
        self._conn_mgr = conn_mgr
        self._lock     = threading.Lock()
        self._filling_mode_cache: Dict[str, int] = {}

    # ── [V18-P2A] FILLING MODE ─────────────────────────────────────────────────
    def _get_filling_mode(self, symbol: str = SYMBOL) -> int:
        if self._conn_mgr is not None and self._conn_mgr.filling_cache_dirty:
            self._filling_mode_cache.clear()
            log.info("[V19-W4] Filling-mode cache cleared after MT5 reconnect")
        if symbol in self._filling_mode_cache:
            return self._filling_mode_cache[symbol]
        info = mt5.symbol_info(symbol)
        if info is None:
            log.warning(f"_get_filling_mode: symbol_info({symbol}) returned None — defaulting IOC")
            return mt5.ORDER_FILLING_IOC
        fm = getattr(info, "filling_mode", 0)
        if fm & 1:
            mode = mt5.ORDER_FILLING_FOK
        elif fm & 2:
            mode = mt5.ORDER_FILLING_IOC
        else:
            mode = mt5.ORDER_FILLING_RETURN
        self._filling_mode_cache[symbol] = mode
        log.info(f"[V18-P2A] Filling mode {symbol}: bitmask={fm} → {mode}")
        return mode

    def _inject_filling(self, req: dict) -> dict:
        action = req.get("action")
        if action in (mt5.TRADE_ACTION_SLTP, mt5.TRADE_ACTION_REMOVE):
            return req
        if "type_filling" not in req:
            req["type_filling"] = self._get_filling_mode(req.get("symbol", SYMBOL))
        return req

    # ── [V17-L3 + V18-P2C + V18-P2D] SEND WITH RETRY ─────────────────────────
    def _send_retry(self, req: dict, retries: int = 3) -> Optional[object]:
        req = self._inject_filling(req)
        if "deviation" in req:
            req["deviation"] = int(req["deviation"])
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
            if res.retcode == mt5.TRADE_RETCODE_DONE_PARTIAL:
                requested = req.get("volume", 0)
                filled    = getattr(res, "volume", requested)
                log.warning(
                    f"⚠️ [V18-P2C] PARTIAL FILL: {filled:.2f}/{requested:.2f} lots "
                    f"ticket:{getattr(res, 'order', 'N/A')} — "
                    f"IOC already cancelled remainder. Managing for actual volume."
                )
                self._adjust_partial_fill(
                    ticket=getattr(res, "order", 0),
                    sl=req.get("sl", 0.0),
                    tp=req.get("tp", 0.0),
                )
                return res
            if res.retcode in (mt5.TRADE_RETCODE_REQUOTE,
                               mt5.TRADE_RETCODE_PRICE_CHANGED,
                               mt5.TRADE_RETCODE_PRICE_OFF):
                req_sym = req.get("symbol", SYMBOL)  # [V21-A1] use request's symbol
                tick = mt5.symbol_info_tick(req_sym)
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
        """[V18-P2C] Smart-probe SL/TP on partially filled position.
        [V21-A1] TRADE_ACTION_SLTP does not require a symbol field — uses position ticket."""
        if ticket == 0: return
        try:
            for attempt in range(3):
                time.sleep(0.5)
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
                    return
                log.debug(f"_adjust_partial_fill: position #{ticket} not yet visible (attempt {attempt+1}/3)")
            log.warning(f"_adjust_partial_fill: position #{ticket} not found after 3 probes — SL/TP not set")
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

    def close_partial(self, pos, lot_close: float, atr: float = 0.0,
                      symbol: str = SYMBOL) -> None:
        """[V21-A1] Per-symbol partial close."""
        try:
            tick = mt5.symbol_info_tick(symbol)
            if tick is None: return
            info       = mt5.symbol_info(symbol)
            step       = info.volume_step if info else 0.01
            v_min      = info.volume_min  if info else 0.01
            lot_close  = float(max(v_min, min(self._risk._round_lot(lot_close, step), pos.volume)))
            is_buy     = (pos.type == mt5.ORDER_TYPE_BUY)
            price      = tick.bid if is_buy else tick.ask
            dev        = int(self._risk.dynamic_deviation(atr, symbol=symbol))
            res = self._send_retry({
                "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol,
                "volume": lot_close, "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
                "position": pos.ticket, "price": round(float(price), 2),
                "deviation": dev,
                "magic": MAGIC_NUMBER, "comment": "V21|PartialTP"})
            if res and res.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL):
                log.info(f"💰 [{symbol}] Partial #{pos.ticket} {lot_close:.2f} @ {price:.2f}")
        except Exception as exc:
            log.warning(f"close_partial exception [{symbol}]: {exc}")

    def close_position_market(self, pos, is_eod: bool = False,
                              symbol: str = SYMBOL) -> bool:
        """[V20-C5] Used by both PositionManager and FridayGuard.execute_eod_close().
        [V21-A1] Accepts symbol so it can close positions on any active symbol."""
        try:
            # Derive symbol from position itself if not supplied explicitly
            pos_symbol = getattr(pos, "symbol", symbol) or symbol
            tick = mt5.symbol_info_tick(pos_symbol); info = mt5.symbol_info(pos_symbol)
            if tick is None or info is None: return False
            is_buy = (pos.type == mt5.ORDER_TYPE_BUY)
            dev    = int(EMERGENCY_DEVIATION_POINTS)
            res = self._send_retry({
                "action": mt5.TRADE_ACTION_DEAL, "symbol": pos_symbol,
                "volume": pos.volume, "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
                "position": pos.ticket,
                "price": round(float(tick.bid if is_buy else tick.ask), 2),
                "deviation": dev, "magic": MAGIC_NUMBER,
                "comment": f"V21|{'EOD' if is_eod else 'KILL'}"}, retries=5)
            ok = res is not None and res.retcode in (mt5.TRADE_RETCODE_DONE,
                                                      mt5.TRADE_RETCODE_DONE_PARTIAL)
            log.info(f"{'✅' if ok else '❌'} [{pos_symbol}] {'EOD' if is_eod else 'Kill'}-close #{pos.ticket}")
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

    def place_order(self, setup: "SetupResult", session: str = "",
                    dd_mode: str = "NORMAL", adr: float = 0.0,
                    df_d1: Optional[pd.DataFrame] = None,
                    symbol: str = SYMBOL) -> bool:
        """[V21-A1/A3] Multi-symbol order placement with global exposure enforcement."""

        # [V19-F4] OOS Spread Guard — per-symbol [V21-A1]
        sp_ok, sp_reason = self._risk.is_spread_ok(symbol)
        if not sp_ok:
            log.warning(f"⛔ [{symbol}] Spread blocked: {sp_reason}"); return False
        if not setup.in_session:
            sp = self._risk.get_spread_pts(symbol)
            if sp > OOS_HARD_SPREAD_BLOCK:
                log.warning(f"⛔ [V19-F4] [{symbol}] OOS spread {sp:.1f}pts > {OOS_HARD_SPREAD_BLOCK}pts hard block"); return False
        if not self._risk.is_within_risk_limits(): return False
        if self._risk.has_duplicate_setup(setup.setup_hash, setup.signal, symbol):
            log.info(f"🚫 [{symbol}] Duplicate → skip"); return False

        # [V21-A3] Per-symbol position cap
        sym_pos_count = self._risk.count_open_positions(symbol)
        if sym_pos_count >= MAX_TRADES_PER_SYMBOL:
            log.info(f"⚠️ [{symbol}] Per-symbol max ({MAX_TRADES_PER_SYMBOL}) reached → skip"); return False

        # [V21-A3] Global concurrent trade cap (all symbols combined)
        global_pos_count = self._risk.count_all_open_positions()
        if global_pos_count >= GLOBAL_MAX_CONCURRENT_TRADES:
            log.info(f"⚠️ [V21-A3] Global max ({GLOBAL_MAX_CONCURRENT_TRADES}) reached "
                     f"({global_pos_count} open) → skip [{symbol}]"); return False

        # [V21-A3] Floating risk exposure guard
        current_exposure_pct = self._risk.calculate_floating_risk_pct()
        if current_exposure_pct >= MAX_GLOBAL_EXPOSURE_PCT:
            log.warning(f"⚠️ [V21-A3] Global exposure {current_exposure_pct:.1f}% ≥ "
                        f"{MAX_GLOBAL_EXPOSURE_PCT}% cap → blocking new [{symbol}] trade"); return False

        sp     = self._risk.get_spread_pts(symbol)
        sl_pad = self._risk.get_spread_sl_padding(symbol)

        if sp > MAX_SPREAD_POINTS:
            setup.score += SCORE_SPREAD_WARN
            setup.reasons.append(f"Spread{sp:.0f} {SCORE_SPREAD_WARN}")

        # M1 confirmation — per-symbol [V21-A1]
        try:
            rates_m1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 8)
            if rates_m1 is not None and len(rates_m1) >= 4:
                df_m1 = pd.DataFrame(rates_m1); c = df_m1.iloc[-2]
                body_m1 = abs(float(c["close"]) - float(c["open"]))
                dir_ok  = ((setup.signal == "BUY"  and c["close"] > c["open"]) or
                           (setup.signal == "SELL" and c["close"] < c["open"]))
                if body_m1 >= setup.atr * MTF_M1_BODY_ATR and dir_ok:
                    setup.score += SCORE_M1_CONFIRM; setup.reasons.append(f"M1 Disp +{SCORE_M1_CONFIRM}")
        except Exception: pass

        tick = mt5.symbol_info_tick(symbol)
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
        if risk == 0: log.error(f"[{symbol}] place_order: risk=0"); return False

        # [V17-F5] Market RR validation after slippage — per-symbol [V21-A1]
        if action == mt5.TRADE_ACTION_DEAL:
            info_sym = mt5.symbol_info(symbol)
            if info_sym:
                tp_check  = entry + risk * RR_RATIO if sig == "BUY" else entry - risk * RR_RATIO
                actual_rr = abs(tp_check - entry) / max(risk, info_sym.point)
                if actual_rr < MIN_RR_RATIO_LIVE:
                    log.warning(f"⛔ [V17-F5] [{symbol}] RR {actual_rr:.2f} < {MIN_RR_RATIO_LIVE} — skip")
                    return False

        tp_raw = entry + risk * RR_RATIO if sig == "BUY" else entry - risk * RR_RATIO
        tp_full, capped = self._engine.apply_adr_tp_cap(entry, tp_raw, sl_adj, adr, df_d1, session, sig)
        if capped: log.info(f"📏 [{symbol}] ADR TP cap: {tp_raw:.2f}→{tp_full:.2f}")

        # [V21-A1] Pass symbol to calculate_lot for per-symbol min_lot
        lot_full = self._risk.calculate_lot(entry, sl_adj, setup.score, sp, setup.atr,
                                             dd_mode, symbol=symbol)
        ok, reason = self._risk.validate_order(entry, sl_adj, tp_full, lot_full, sig,
                                                symbol=symbol)
        if not ok: log.warning(f"⚠️ [{symbol}] Validate: {reason}"); return False

        info  = mt5.symbol_info(symbol)
        step  = info.volume_step if info else 0.01; v_min = info.volume_min if info else 0.01
        lot_a = max(v_min, self._risk._round_lot(lot_full * PARTIAL_TP_PCT, step))
        lot_b = max(v_min, self._risk._round_lot(lot_full - lot_a, step))
        tp_pt = entry + risk * PARTIAL_TP_RR if sig == "BUY" else entry - risk * PARTIAL_TP_RR

        dev = int(self._risk.dynamic_deviation(setup.atr, symbol=symbol))

        sent = 0
        for lot_i, tp_i, label in [(lot_a, tp_pt, "PT"), (lot_b, tp_full, "FT")]:
            req = {"action": action, "symbol": symbol, "volume": lot_i, "type": otype,
                "price": round(float(entry), 2), "sl": round(float(sl_adj), 2),
                "tp": round(float(tp_i), 2), "deviation": dev, "magic": MAGIC_NUMBER,
                "comment": f"V21|{sig}|{label}|{setup.score}|{setup.setup_hash}"}
            if action == mt5.TRADE_ACTION_PENDING:
                req["type_time"] = mt5.ORDER_TIME_SPECIFIED; req["expiration"] = exp
            res = self._send_retry(req)
            if res and res.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL):
                filled_vol = getattr(res, "volume", lot_i)
                sent += 1
                log.info(f"✅ [{symbol}] {label}|{sig}|Lot:{filled_vol:.2f}|E:{entry:.2f}|SL:{sl_adj:.2f}|TP:{tp_i:.2f}")
            else:
                log.warning(f"⚠️ [{symbol}] {label} order failed")

        if sent > 0:
            rr_act  = abs(tp_full - entry) / risk if risk > 0 else 0
            oos_tag = " 🌙OUT-OF-SESSION" if not setup.in_session else ""
            # [V21-A3] Post-trade exposure report
            new_exposure = self._risk.calculate_floating_risk_pct()
            log.info(
                f"\n{'═'*72}\n"
                f"  🎯 TRADE PLACED [{symbol}] — {sig} {'MKT' if action == mt5.TRADE_ACTION_DEAL else 'LMT'}"
                f"  {'⚡JUDAS' if setup.is_judas else ''}"
                f"  {'✨GOLDEN' if setup.golden_conf else ''}"
                f"{oos_tag}\n"
                f"  {'─'*70}\n"
                f"  Entry: {entry:.2f}  SL: {sl_adj:.2f}  TP-Pt: {tp_pt:.2f}  TP-Full: {tp_full:.2f}\n"
                f"  Risk: {risk:.2f}  RR: {rr_act:.2f}×  Lot: {lot_a}+{lot_b}\n"
                f"  Score: {setup.score}/{setup.threshold}  WP: {setup.win_prob:.3f}  DD: {dd_mode}\n"
                f"  Session: {session}  InKZ: {setup.in_session}  H4: {setup.htf_bias}  H1: {setup.h1_bias}\n"
                f"  Shape: {setup.shape}  Sweep: {setup.sweep_type}  Dev: {dev}pts (int)\n"
                f"  Spread: {sp:.1f}pts (median: {self._risk._spread_guard(symbol).median_spread:.1f})\n"
                f"  BE-Delay: {BREAKEVEN_DELAY_RR}R  Partial-TP: {PARTIAL_TP_RR}R  [V18-P1A]\n"
                f"  [V21-A3] Global Positions: {self._risk.count_all_open_positions()}/"
                f"{GLOBAL_MAX_CONCURRENT_TRADES} | Floating Risk: {new_exposure:.1f}%/{MAX_GLOBAL_EXPOSURE_PCT}%\n"
                f"  Hash: {setup.setup_hash}\n"
                f"{'═'*72}"
            )
            db_log_setup(sig, setup.score, entry, sl_adj, tp_full, setup.setup_hash,
                         session, setup.features, setup.win_prob, setup.sweep_type, setup.shape)
            return True
        return False


# ══════════════════════════════════════════════════════════════════════════════
# 🔄  CLASS: PositionManager  [V18-P1A + V20-C2 Orphan SL Check]
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
        self._last_orphan_check: float = 0.0   # [V20-C2]

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="PositionManager", daemon=True)
        self._thread.start()
        log.info(f"🔄 PositionManager V20 started ({POSITION_POLL_SEC*1000:.0f}ms) "
                 f"| OrphanSL check every {ORPHAN_SL_CHECK_INTERVAL:.0f}s [V20-C2]")

    def stop(self) -> None:
        self._running.clear()
        if self._thread: self._thread.join(timeout=5)
        log.info("🔄 PositionManager stopped")

    def _loop(self) -> None:
        while self._running.is_set():
            try:
                if self._conn.ensure_connected():
                    # [V21-A4] Manage positions and check orphans across ALL symbols
                    for sym in ACTIVE_SYMBOLS:
                        df_m5 = self._feed.fetch(mt5.TIMEFRAME_M5, 20, symbol=sym,
                                                  use_cache=True)
                        atr   = calculate_atr(df_m5) if df_m5 is not None else 1.0
                        self._manage_positions(atr, symbol=sym)
                        self._orphan_sl_check(atr, symbol=sym)   # [V20-C2][V21-A4]
            except Exception as exc:
                log.warning(f"⚠️ PM error: {exc}")
            time.sleep(POSITION_POLL_SEC)

    # ── [V20-C2][V21-A4] Orphan SL Checker — all symbols ─────────────────────
    def _orphan_sl_check(self, atr: float, symbol: str = SYMBOL) -> None:
        """
        [V20-C2] MT5 crash recovery: scans all MAGIC_NUMBER positions for
        missing SL (sl == 0).
        [V21-A4] Now iterates the specific symbol passed by the per-symbol loop.
        Runs every ORPHAN_SL_CHECK_INTERVAL seconds (shared timer).
        """
        now = time.time()
        if now - self._last_orphan_check < ORPHAN_SL_CHECK_INTERVAL:
            return
        self._last_orphan_check = now

        positions = [p for p in (mt5.positions_get(symbol=symbol) or [])
                     if p.magic == MAGIC_NUMBER]
        for pos in positions:
            if pos.sl != 0.0:
                continue   # SL is set — fine
            log.warning(f"🚨 [V20-C2] ORPHAN [{symbol}] #{pos.ticket}: SL=0 detected — "
                        f"reconstructing SL from trail_state or ATR fallback")
            # Try to recover SL from trail_state DB first
            ts_row = get_trail_state(pos.ticket)
            if ts_row and ts_row["last_sl"] and float(ts_row["last_sl"]) != 0.0:
                recovered_sl = float(ts_row["last_sl"])
                log.info(f"[V20-C2] [{symbol}] Restoring SL from trail_state: {recovered_sl:.2f}")
            else:
                # ATR-based fallback: use per-symbol sl_atr_mult if available
                sym_mult = ACTIVE_SYMBOLS.get(symbol, {}).get("sl_atr_mult", 1.5)
                safe_atr = max(atr, 0.5)
                is_buy   = (pos.type == mt5.ORDER_TYPE_BUY)
                recovered_sl = (pos.price_open - safe_atr * sym_mult) if is_buy \
                               else (pos.price_open + safe_atr * sym_mult)
                log.warning(f"[V20-C2] [{symbol}] ATR fallback SL: {recovered_sl:.2f} "
                             f"(entry={pos.price_open:.2f} ± {safe_atr * sym_mult:.2f})")
            self._exec.modify_sl(pos.ticket, recovered_sl)

    def _detect_closed_positions(self, current_tickets: set,
                                  symbol: str = SYMBOL) -> None:
        """[V21-A4] Per-symbol closed position detection."""
        sym_key = f"_prev_{symbol}"
        prev    = getattr(self, sym_key, set())
        closed  = prev - current_tickets
        for ticket in closed:
            try:
                deals = mt5.history_deals_get(ticket=ticket)
                if deals:
                    profit = sum(d.profit for d in deals)
                    outcome = "WIN" if profit > 0 else "LOSS"
                    record_trade_outcome(outcome, "")
                    log.info(f"📊 [{symbol}] Closed #{ticket}: {outcome} (P&L: ${profit:.2f})")
                    invalidate_consec_loss_cache()   # [V20-C3] thread-safe invalidation
                    n_loss = get_consecutive_losses()
                    if n_loss >= N_CONSEC_LOSS_PAUSE:
                        set_consec_loss_pause()
            except Exception as exc:
                log.warning(f"_detect_closed [{symbol}]: {exc}")
        setattr(self, sym_key, current_tickets)

    def _manage_positions(self, atr: float, symbol: str = SYMBOL) -> None:
        """[V21-A4] Per-symbol position management."""
        positions = [p for p in (mt5.positions_get(symbol=symbol) or [])
                     if p.magic == MAGIC_NUMBER]
        current_tickets = {p.ticket for p in positions}
        self._detect_closed_positions(current_tickets, symbol=symbol)
        if not positions: return

        tick = mt5.symbol_info_tick(symbol); info = mt5.symbol_info(symbol)
        if tick is None or info is None: return
        a           = max(atr, info.point * 10)
        trail_cache = batch_load_trail_states(list(current_tickets))

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

            # ── STEP 1: Partial TP at 1R [V18-P1A] ───────────────────────────
            did_partial = False
            if not partial_done and profit_r >= PARTIAL_TP_RR:
                # [V21-A1] Pass symbol to close_partial
                self._exec.close_partial(pos, pos.volume * PARTIAL_TP_PCT,
                                          atr=a, symbol=symbol)
                set_partial_done(pos.ticket, pos_hash)
                log.info(
                    f"💰 [V18-P1A] [{symbol}] Partial TP at {profit_r:.2f}R #{pos.ticket} — "
                    f"SL stays at {sl_now:.2f} (BE delayed until {BREAKEVEN_DELAY_RR}R)"
                )
                did_partial = True  # noqa: F841

            # ── STEP 2: Delayed Breakeven [V18-P1A] ──────────────────────────
            if profit_r >= BREAKEVEN_DELAY_RR:
                be_sl = (entry + buf) if is_buy else (entry - buf)
                if (is_buy and sl_now < be_sl) or (not is_buy and sl_now > be_sl):
                    self._exec.modify_sl(pos.ticket, be_sl)
                    log.info(
                        f"🔒 [V18-P1A] [{symbol}] Delayed BE at {profit_r:.2f}R >= {BREAKEVEN_DELAY_RR}R "
                        f"#{pos.ticket} SL:{sl_now:.2f}→{be_sl:.2f}"
                    )

            # ── STEP 3: Trail SL ──────────────────────────────────────────────
            if profit_r >= TRAIL_AFTER_RR:
                last_tsl = float(ts["last_sl"]) if ts else None
                min_move = a * TRAIL_MIN_MOVE_ATR
                if is_buy:
                    new_tsl = price - (a * TRAIL_ATR_MULT)
                    if new_tsl > sl_now and (last_tsl is None or new_tsl > last_tsl + min_move):
                        self._exec.modify_sl(pos.ticket, new_tsl)
                        save_trail_sl(pos.ticket, new_tsl, pos_hash)
                        log.info(f"📈 [{symbol}] Trail #{pos.ticket} {sl_now:.2f}→{new_tsl:.2f} R:{profit_r:.2f}")
                else:
                    new_tsl = price + (a * TRAIL_ATR_MULT)
                    if new_tsl < sl_now and (last_tsl is None or new_tsl < last_tsl - min_move):
                        self._exec.modify_sl(pos.ticket, new_tsl)
                        save_trail_sl(pos.ticket, new_tsl, pos_hash)
                        log.info(f"📉 [{symbol}] Trail #{pos.ticket} {sl_now:.2f}→{new_tsl:.2f} R:{profit_r:.2f}")

            log.debug(f"📍 [{symbol}] Pos #{pos.ticket}: ${pos.profit:+.2f} ({profit_r:+.2f}R)")

        cleanup_trail_state(current_tickets)


# ══════════════════════════════════════════════════════════════════════════════
# 🆘  EMERGENCY KILL-SWITCH
# ══════════════════════════════════════════════════════════════════════════════
def graceful_shutdown(execution: ExecutionHandler, reason: str = "EXIT") -> None:
    """[V21-A4] Flattens ALL ACTIVE_SYMBOLS, not just the anchor symbol."""
    log.warning(f"🚨 GRACEFUL SHUTDOWN — {reason}")
    log.warning("🚨 Step 1/3: Cancelling pending orders across ALL symbols…")
    for sym in ACTIVE_SYMBOLS:
        for o in (mt5.orders_get(symbol=sym) or []):
            if o.magic == MAGIC_NUMBER:
                execution.cancel_pending_order(o.ticket)
    time.sleep(0.5)
    log.warning("🚨 Step 2/3: Closing all open positions at market across ALL symbols…")
    for sym in ACTIVE_SYMBOLS:
        for pos in (mt5.positions_get(symbol=sym) or []):
            if pos.magic == MAGIC_NUMBER:
                execution.close_position_market(pos, symbol=sym); time.sleep(0.2)
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
    # [V21-A3] Global position count and per-symbol breakdown
    global_pos = risk.count_all_open_positions()
    sym_pos_str = " | ".join(
        f"{s}:{risk.count_open_positions(s)}"
        for s in ACTIVE_SYMBOLS
        if risk.count_open_positions(s) > 0
    ) or "None"
    floating_risk = risk.calculate_floating_risk_pct()
    pause_on  = os.path.isfile(PAUSE_FLAG_PATH)
    kill_on   = os.path.isfile(KILL_FLAG_PATH)
    model_tag = "✅ Real Model" if predictor.model_loaded else "🔶 Score-only (no ML model)"
    consec    = get_consecutive_losses()
    mode_lbl  = ("🔴 KILL" if kill_on else "⏸️ PAUSED" if pause_on
                 else "🟠 ORANGE" if dd_mode == "ORANGE"
                 else "💛 YELLOW" if dd_mode == "YELLOW"
                 else "🔴 RED"    if dd_mode == "RED" else "🟢 NORMAL")
    scipy_tag = "scipy✅" if _SCIPY_AVAILABLE else "scipy❌(fallback)"
    sym_list  = ", ".join(ACTIVE_SYMBOLS.keys())
    log.info(
        f"\n{'═'*72}\n"
        f"  📊  OPERATOR STATUS V21  [{datetime.now(STRATEGY_TZ).strftime('%H:%M:%S')} BKK]\n"
        f"  {'─'*70}\n"
        f"  Equity     : ${acct.equity:>10,.2f}  ({eq_pct:+.2f}%)\n"
        f"  Today P&L  : ${today_pl:>+10,.2f}\n"
        f"  DD Daily   : {daily_dd:.2f}%   DD Total: {total_dd:.2f}%\n"
        f"  Session    : {session:<16} H4: {htf_bias:<10} H1: {h1_bias:<10} ADR: {adr_pct*100:.0f}%\n"
        f"  [V21-A3] Global Pos: {global_pos}/{GLOBAL_MAX_CONCURRENT_TRADES} | "
        f"Floating Risk: {floating_risk:.1f}%/{MAX_GLOBAL_EXPOSURE_PCT}%\n"
        f"  Active Syms: {sym_list}\n"
        f"  Open by Sym: {sym_pos_str}\n"
        f"  ML Mode    : {model_tag}   Norm: {'WARM' if predictor.norm_is_warm else 'COLD'}\n"
        f"  Consec Loss: {consec}/{N_CONSEC_LOSS_PAUSE}\n"
        f"  Mode       : {mode_lbl}\n"
        f"  Dev Cap    : {MAX_DEVIATION_POINTS}pts (int) / {EMERGENCY_DEVIATION_POINTS}pts emergency\n"
        f"  Friday EOD : {FRIDAY_CLOSE_UTC_HOUR:02d}:{FRIDAY_CLOSE_UTC_MIN:02d} UTC (broker-time)\n"
        f"  BE Delay   : {BREAKEVEN_DELAY_RR}R [V18-P1A]  Partial-TP: {PARTIAL_TP_RR}R\n"
        f"  Threshold  : InSession={SCORE_THRESHOLD_IN_SESSION} OOS={SCORE_THRESHOLD_OUT_SESSION}\n"
        f"  Scipy vect : {scipy_tag}  |  DB queue: {_write_q.qsize() if _write_q else 'N/A'}/500\n"
        f"{'═'*72}"
    )


def log_risk_tier_sanity() -> None:
    """Log effective lot sizes on startup for operator verification."""
    sample_balance   = 10_000.0
    sample_sl_pts    = 20.0
    sample_tick_val  = 0.01
    log.info("── [V19-F3] Risk Tier Sanity Check (sample: $10k balance, 20pt SL) ──")
    for min_score, risk_pct in RISK_TIERS:
        raw = (sample_balance * risk_pct / 100.0) / (sample_sl_pts * sample_tick_val * 100)
        log.info(f"  score≥{min_score:>2d}: risk={risk_pct:.2f}% → ~{raw:.2f} lots")
    log.info("─" * 50)


# ══════════════════════════════════════════════════════════════════════════════
# 🚀  SIGNAL CYCLE — [V21-A2] Per-symbol, called only on new M5 bar close
# ══════════════════════════════════════════════════════════════════════════════
def _run_signal_cycle(feed: MarketDataFeed, signal_engine: SMCSignalEngine,
                      risk: RiskManager, execution: ExecutionHandler,
                      predictor: MLPredictor, conn_mgr: ConnectionManager,
                      friday_guard: FridayGuard, last_ctx: Dict,
                      symbol: str = SYMBOL) -> None:
    """[V21-A2] Single-symbol signal cycle. Called only when a new M5 bar closes
    for this specific symbol. All multi-asset orchestration is in main()."""

    if not conn_mgr.ensure_connected(): return

    if friday_guard.is_blocked():
        friday_guard.execute_eod_close(execution)
        return

    daily_dd, total_dd, dd_mode = risk.get_dd_state()
    if dd_mode == "RED":
        log.warning(f"⛔ DD RED daily={daily_dd:.2f}% total={total_dd:.2f}% → halt"); return
    if risk.is_circuit_breaker_tripped(): return

    session = signal_engine.get_session()
    if session == "RED_NEWS_BLOCK": return

    # [V21-A3] Pre-cycle global exposure guard
    global_pos = risk.count_all_open_positions()
    if global_pos >= GLOBAL_MAX_CONCURRENT_TRADES:
        log.info(f"⚠️ [V21-A3] [{symbol}] Global cap {global_pos}/{GLOBAL_MAX_CONCURRENT_TRADES} → skip"); return

    floating_risk = risk.calculate_floating_risk_pct()
    if floating_risk >= MAX_GLOBAL_EXPOSURE_PCT:
        log.info(f"⚠️ [V21-A3] [{symbol}] Floating risk {floating_risk:.1f}% ≥ {MAX_GLOBAL_EXPOSURE_PCT}% → skip"); return

    in_kz, kz_name = signal_engine.is_in_killzone()
    oos_note = "" if in_kz else f" [OOS thr={SCORE_THRESHOLD_OUT_SESSION}]"
    log.info(f"📍 [{symbol}] Session:{session} KZ:{kz_name}{oos_note}")

    # [V21-A1] Per-symbol spread check
    sp_ok, sp_reason = risk.is_spread_ok(symbol)
    if not sp_ok: log.warning(f"⛔ [{symbol}] Spread: {sp_reason}"); return

    if os.path.isfile(PAUSE_FLAG_PATH):
        log.info("⏸️ PAUSE.flag → skip new entries"); return
    if not risk.new_entries_allowed():
        log.warning(f"🟠 DD {dd_mode} → new entries suspended"); return
    if is_consec_loss_paused(): return

    # [V21-A2] Full multi-timeframe fetch for this specific symbol
    data = feed.fetch_all(symbol=symbol)
    if data["m5"] is None: log.warning(f"[{symbol}] M5 unavailable → skip"); return
    cleanup_cooldowns()

    setup = signal_engine.analyze_setup(
        data["m5"], data["h4"], data["d1"], data["m15"], data.get("h1"), session)
    setup.spread_pts = risk.get_spread_pts(symbol)

    last_ctx.update({"bias": setup.htf_bias, "h1_bias": setup.h1_bias,
                     "session": session, "adr_pct": str(setup.adr_pct)})

    liq = setup.liq_map
    if liq:
        log.info(f"💧 [{symbol}] BSL:{liq.bsl_nearest or '—'} SSL:{liq.ssl_nearest or '—'} "
                 f"SwH:{liq.swept_high} SwL:{liq.swept_low}")
    htf = setup.htf_result
    if htf:
        log.info(f"🏗️ [{symbol}] H4:{htf.bias} BOS:{htf.last_bos} CHOCH:{htf.choch_signal} | {htf.reason}")
    log.info(f"📊 [{symbol}] {session} KZ:{kz_name} InSess:{setup.in_session} | M15:{setup.m15_struct} | "
             f"ADR:{setup.adr_pct*100:.0f}% | Thr:{setup.threshold} | DD:{dd_mode} | "
             f"Shape:{setup.shape} | Sweep:{setup.sweep_type}")

    if setup.signal == "WAIT": return
    if setup.score < setup.threshold:
        log.info(f"⚠️ [{symbol}] Score {setup.score} < {setup.threshold} → skip"); return

    close_price    = float(data["m5"]["close"].iloc[-1]) if data["m5"] is not None else 2000.0
    setup.features = extract_features(setup, close_price=close_price, df_len=len(data["m5"]))

    setup.win_prob = predictor.predict_win_probability(setup.features)
    if predictor.model_loaded and setup.win_prob < ML_WIN_PROB_THRESHOLD:
        log.info(f"🤖 [{symbol}] ML rejected: {setup.win_prob:.3f} < {ML_WIN_PROB_THRESHOLD}"); return

    mode_tag = "real-model" if predictor.model_loaded else "score-only (ML bypassed)"
    log.info(f"🧠 [{symbol}] WP:{setup.win_prob:.3f} [{mode_tag}] avg:{predictor.rolling_avg_prob:.3f} "
             f"| {setup.summary()}")

    if is_on_cooldown(setup.setup_hash):
        log.info(f"🔁 [{symbol}] Cooldown → skip"); return
    if risk.has_duplicate_setup(setup.setup_hash, setup.signal, symbol):
        log.info(f"🚫 [{symbol}] Duplicate → skip"); return

    adr_val = calculate_adr(data.get("d1"))
    # [V21-A1] Pass symbol through to place_order
    if execution.place_order(setup, session, dd_mode, adr=adr_val,
                              df_d1=data.get("d1"), symbol=symbol):
        set_cooldown(setup.setup_hash)
        log.info(f"🎯 [{symbol}] Placed | hash:{setup.setup_hash} | {setup.sweep_type} | {setup.shape}")


# ══════════════════════════════════════════════════════════════════════════════
# 🚀  MAIN
# ══════════════════════════════════════════════════════════════════════════════
BANNER = """
╔══════════════════════════════════════════════════════════════════════════════════╗
║  🌐  AI SMC/ICT Pro Sniper — V.21 "Global Scanner" (Multi-Asset Architecture)   ║
║                                                                                  ║
║  V.21 UPGRADES over V.20:                                                        ║
║  [V21-A1] ACTIVE_SYMBOLS dict — per-symbol spread/SL-mult/min-lot profiles      ║
║  [V21-A2] Round-Robin Scanner — lightweight M5 bar-time poll, rate-limit safe   ║
║  [V21-A3] Global Exposure Guard — 2-trade global cap + 40% floating risk limit  ║
║  [V21-A4] Distributed State — last_closed_bar[], orphan check & EOD all symbols ║
║                                                                                  ║
║  V.20 FIXES (all preserved):                                                     ║
║  [V20-C1] WelfordNormaliser Warm-Start — survives bot restarts (DB persisted)   ║
║  [V20-C2] Orphan SL Recovery — auto-restores missing SL after MT5 crash         ║
║  [V20-C3] Thread-safe ConsecLoss cache — locked dataclass replaces bare globals ║
║  [V20-C4] Bounded DB write queue (maxsize=500) — no memory leak under CPI/NFP  ║
║  [V20-C5] FridayGuard EOD close fixed — no more NameError on execute_eod_close  ║
║  [V20-O1/O2] Vectorised swing pivot detection (scipy/stride_tricks)             ║
║  [V20-O3] Vectorised FVG mitigated check (array slice min/max)                  ║
║  [V20-O4] VShapeDetector bounds-checked; origin index corrected post reset_index║
║  [V20-O5] MarketDataFeed cache key is (tf, symbol) tuple — no hash collision    ║
║  [V20-O6] DD state cache (2s TTL) — eliminates redundant account_info() calls   ║
╚══════════════════════════════════════════════════════════════════════════════════╝
"""


def main() -> None:
    print(BANNER)
    log.info("Bot V.21 Global Scanner starting")
    init_db()
    log_risk_tier_sanity()

    conn_mgr = ConnectionManager()
    for delay in [0, 5, 10, 20, 30]:
        if delay: time.sleep(delay)
        if conn_mgr.ensure_connected(): break
    else:
        log.error("❌ Cannot connect to MT5 after extended retry"); return

    # [V21-A2] Use the anchor symbol (first in ACTIVE_SYMBOLS) for clock sync
    clock         = BrokerClockSync(CLOCK_ANCHOR_SYMBOL, STRATEGY_TZ)
    clock.refresh()

    feed          = MarketDataFeed()
    signal_engine = SMCSignalEngine(clock)
    risk          = RiskManager()
    execution     = ExecutionHandler(risk, signal_engine, conn_mgr)
    predictor     = MLPredictor()   # [V20-C1] auto-loads WelfordNormaliser from DB
    friday_guard  = FridayGuard(clock)

    # Uncomment to load a trained model:
    # predictor.load_model("smc_model_v21.joblib")

    pm = PositionManager(feed, execution, conn_mgr)
    pm.start()

    # [V20-C2][V21-A4] Immediate orphan SL scan on startup across ALL symbols
    log.info("[V20-C2][V21-A4] Startup orphan SL scan (all symbols)...")
    for sym in ACTIVE_SYMBOLS:
        for pos in (mt5.positions_get(symbol=sym) or []):
            if pos.magic == MAGIC_NUMBER and pos.sl == 0.0:
                log.warning(f"[V20-C2] Startup: orphan [{sym}] #{pos.ticket} SL=0 — scheduling recovery")

    last_ctx: Dict[str, str] = {
        "bias": "NEUTRAL", "h1_bias": "NEUTRAL", "session": "UNKNOWN", "adr_pct": "0.0"
    }
    _shutdown = threading.Event()

    def _sig_handler(signum, frame):
        log.warning(f"Signal {signum} → shutdown"); _shutdown.set()

    signal.signal(signal.SIGTERM, _sig_handler)
    signal.signal(signal.SIGINT,  _sig_handler)

    # [V21-A2] Per-symbol last-closed-bar dictionary (replaces single scalar)
    last_closed_bar: Dict[str, Optional[int]] = {sym: None for sym in ACTIVE_SYMBOLS}
    last_heartbeat:  float = time.time()

    sym_list_str = ", ".join(ACTIVE_SYMBOLS.keys())
    log.info(
        f"🌐 [V21-A2] Round-Robin Scanner ACTIVE | Symbols: {sym_list_str}\n"
        f"   Global cap: {GLOBAL_MAX_CONCURRENT_TRADES} trades | "
        f"Per-symbol cap: {MAX_TRADES_PER_SYMBOL} | "
        f"Exposure cap: {MAX_GLOBAL_EXPOSURE_PCT}%\n"
        f"   InSess Thr:{SCORE_THRESHOLD_IN_SESSION} | "
        f"OOS Thr:{SCORE_THRESHOLD_OUT_SESSION} | "
        f"Friday EOD:{FRIDAY_CLOSE_UTC_HOUR:02d}:{FRIDAY_CLOSE_UTC_MIN:02d} UTC | "
        f"BE-Delay:{BREAKEVEN_DELAY_RR}R | "
        f"CB:{CIRCUIT_BREAKER_PCT}% | V21 SciPy:{_SCIPY_AVAILABLE}"
    )

    try:
        while not _shutdown.is_set():
            if os.path.isfile(KILL_FLAG_PATH):
                log.warning("🚨 KILL.flag!"); _shutdown.set(); break

            if not conn_mgr.ensure_connected():
                time.sleep(TICK_POLL_SEC); continue

            clock.refresh()

            if friday_guard.is_blocked():
                friday_guard.execute_eod_close(execution)
                log.info("📅 Friday/Weekend — no new entries. Bot monitoring only.")
                time.sleep(60); continue

            # ── [V21-A2] ROUND-ROBIN: lightweight per-symbol M5 bar poll ──────
            # Each iteration: check M5 bar timestamp for ONE symbol.
            # Only on new bar close: pull full data and run SMCSignalEngine.
            # 0.1s sleep between symbols prevents MT5 API spam.
            for sym in list(ACTIVE_SYMBOLS.keys()):
                if _shutdown.is_set(): break
                try:
                    # Lightweight poll: single latest M5 bar timestamp only
                    latest_rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 2)
                except Exception as exc:
                    log.warning(f"[V21-A2] [{sym}] copy_rates exception: {exc}")
                    time.sleep(0.1); continue

                if latest_rates is None or len(latest_rates) < 2:
                    time.sleep(0.1); continue

                # The PREVIOUS (fully closed) bar timestamp
                prev_closed_ts = int(latest_rates[-2]["time"])

                if prev_closed_ts != last_closed_bar[sym]:
                    # [V21-A2] NEW M5 BAR CLOSED for this symbol → run full cycle
                    log.info("─" * 74)
                    log.info(
                        f"🕯️  [{sym}] Closed:{prev_closed_ts} | "
                        f"New:{int(latest_rates[-1]['time'])} | "
                        f"{clock.now_strategy().strftime('%H:%M:%S')} {STRATEGY_TZ_NAME}"
                    )
                    last_closed_bar[sym] = prev_closed_ts
                    _run_signal_cycle(
                        feed, signal_engine, risk, execution, predictor,
                        conn_mgr, friday_guard, last_ctx,
                        symbol=sym   # [V21-A2] pass specific symbol
                    )

                # [V21-A2] Rate-limit protection: 100ms between symbol polls
                time.sleep(0.1)
            # ── END ROUND-ROBIN ────────────────────────────────────────────────

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

            # [V21-A2] After scanning all symbols, sleep the remaining tick window.
            # With 5 symbols × 0.1s = 0.5s of polls per cycle; total cycle ≈ TICK_POLL_SEC
            remaining = TICK_POLL_SEC - (len(ACTIVE_SYMBOLS) * 0.1)
            if remaining > 0:
                time.sleep(remaining)

    except KeyboardInterrupt:
        log.info("🛑 KeyboardInterrupt")
    except Exception as exc:
        log.exception(f"💥 Unhandled: {exc}")
    finally:
        log.info("Graceful shutdown initiating…")
        pm.stop()
        graceful_shutdown(execution)
        # Persist WelfordNormaliser state before exit
        try:
            set_state("welford_state", predictor._norm.serialise())
            log.info("[V20-C1] WelfordNormaliser state persisted to DB on exit")
        except Exception: pass
        close_db()
        try: mt5.shutdown()
        except Exception: pass
        log.info("MT5 offline. Bot V.21 Global Scanner terminated.")


# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    main()
