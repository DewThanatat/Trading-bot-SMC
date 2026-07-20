# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  🧬  SMC CORE V.23  —  LEGENDARY SCALPER EDITION                            ║
║                                                                              ║
║  IMPORTED BY BOTH smc_bot_v23_live.py AND smc_bot_v23_backtest.py           ║
║  The single source of truth for all indicators & setup logic.                ║
║                                                                              ║
║  V.23 UPGRADES vs V.22 (Druckenmiller/CIS/Soros Refactor):                  ║
║  [S1]  PA Detector (NEW)        — Pinbar/Doji detection at swept extremes   ║
║  [S2]  Reversal Override (NEW)  — LTF confluence neutralises HTF penalty    ║
║  [S3]  HTF Against softened     — SCORE_HTF_AGAINST reduced; overridable    ║
║  [S4]  OOS threshold lowered    — God-Tier scores bypass session gate        ║
║  [S5]  SCORE_PA_PINBAR (NEW)    — +18 pts for confirmed wick rejection       ║
║  [S6]  SCORE_PA_DOJI (NEW)      — +10 pts for Doji at swept extreme          ║
║  [S7]  REVERSAL_OVERRIDE (NEW)  — sweep+PA+CHoCH+FVG zeroes HTF penalty    ║
║  [S8]  Absolute Conviction tier — see RISK_TIERS in smc_bot_v23_live.py     ║
║  ── V.22 fixes carried forward unchanged ──                                  ║
║  [C1]-[C10] all retained                                                     ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import hashlib
import math
import time
import warnings
from dataclasses import dataclass, field
from datetime import datetime, time as dtime
from typing import Dict, List, Optional, Tuple

# pyrefly: ignore [missing-import]
import numpy as np
import pandas as pd
import pytz

warnings.filterwarnings("ignore", category=RuntimeWarning)

try:
    # pyrefly: ignore [missing-import]
    from numba import njit
    _NUMBA_AVAILABLE = True
except ImportError:
    _NUMBA_AVAILABLE = False
    # Dummy decorator if numba is missing
    def njit(*args, **kwargs):
        def wrapper(func):
            return func
        if len(args) == 1 and callable(args[0]): return args[0]
        return wrapper

try:
    # pyrefly: ignore [missing-import]
    from scipy.ndimage import maximum_filter1d as _max_filter1d
    # pyrefly: ignore [missing-import]
    from scipy.ndimage import minimum_filter1d as _min_filter1d
    _SCIPY_AVAILABLE = True
except ImportError:
    _SCIPY_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
#  ⚙️  STRATEGY CONFIG  (edit this block only)
# ─────────────────────────────────────────────────────────────────────────────
STRATEGY_TZ = pytz.timezone("Asia/Bangkok")

# ── The Apex Predator Radar (10 Symbols for Max Frequency) ──
ACTIVE_SYMBOLS: dict[str, dict] = {
    "XAUUSDm": {"spread_block_pts": 350.0, "sl_atr_mult": 2.0, "min_lot": 0.01, "sim_spread": 25.0, "tick_val": 1.0, "pt_size": 0.01},
    "EURUSDm": {"spread_block_pts": 50.0, "sl_atr_mult": 2.0, "min_lot": 0.01, "sim_spread": 10.0, "tick_val": 1.0, "pt_size": 0.00001, "min_score": 72},
    "USDJPYm": {"spread_block_pts": 70.0, "sl_atr_mult": 2.4, "min_lot": 0.01, "sim_spread": 18.0, "tick_val": 0.67, "pt_size": 0.001},
    "AUDUSDm": {"spread_block_pts": 50.0, "sl_atr_mult": 2.0, "min_lot": 0.01, "sim_spread": 12.0, "tick_val": 1.0, "pt_size": 0.00001, "min_score": 70},
    "NZDUSDm": {"spread_block_pts": 60.0, "sl_atr_mult": 2.0, "min_lot": 0.01, "sim_spread": 15.0, "tick_val": 1.0, "pt_size": 0.00001, "min_score": 70}, # NEW: โครงสร้าง SMC สวยมาก
    "USTECm":  {"spread_block_pts": 300.0, "sl_atr_mult": 4.5, "min_lot": 0.1, "sim_spread": 150.0, "tick_val": 1.0, "pt_size": 1.0}, # เพิ่ม sl_atr_mult เป็น 4.5
    "US30m":   {"spread_block_pts": 400.0, "sl_atr_mult": 4.5, "min_lot": 0.1, "sim_spread": 200.0, "tick_val": 1.0, "pt_size": 1.0}, # เพิ่ม sl_atr_mult เป็น 4.5
}

# ── Trade Management (Hitman Mode) ───────────────────────────────────────────
RR_RATIO           = 1.8      
PARTIAL_TP_RR      = 1.0      
PARTIAL_TP_PCT     = 0.0      # MUST remain 0.0 for 0.01 lot constraint
BREAKEVEN_DELAY_RR = 0.5      # Secure the microscopic equity instantly
TRAIL_AFTER_RR     = 0.6      # Start choking the price before 1R
TRAIL_ATR_MULT     = 1.2      # Aggressive ratchet; do not let it breathe
TRAIL_MIN_MOVE_ATR = 0.3
MIN_RR_TO_TARGET   = 1.5      # Demand higher liquidity clearance  

# ── Scoring (The Ultimate Confluence) ────────────────────────────────────────
SCORE_BASE          = 18
SCORE_FVG_FRESH     = 10
SCORE_LIQ_SWEPT     = 28       
SCORE_SWEEP_AND_FVG = 5
SCORE_HTF_ALIGN     = 18
SCORE_HTF_AGAINST   = -40      
SCORE_HTF_NEUTRAL   = -20    
SCORE_M15_BOS       = 10

SCORE_OB_BONUS      = 5

SCORE_LIQ_TARGET    = 4
SCORE_FVG_STRENGTH  = 4
SCORE_M1_CONFIRM    = 12
SCORE_ADR_WARN      = -10
SCORE_SPREAD_WARN   = -5
H1_AGREE_BONUS      = 12
H1_CONFLICT_PENALTY = -4

SCORE_MSS_CISD = 10
SCORE_MSS_ONLY = 4

SCORE_VSHAPE_BONUS   = 2
SCORE_USHAPE_PENALTY = -12
SCORE_GOLDEN_CONFLUENCE = 12

JUDAS_SCORE_BONUS = 12  

# ── [S1] Price Action Detector Scores (NEW in V.23) ───────────────────────────
# Awarded when a Pinbar or Doji forms AT a swept liquidity extreme.
# These are the "rejection fingerprints" that Druckenmiller/CIS read as
# ── Price Action Detector ──
SCORE_PA_PINBAR     = 8      
SCORE_PA_DOJI       = 0        

# ── Reversal Override ──
REVERSAL_OVERRIDE_ENABLED = False
REVERSAL_OVERRIDE_BONUS   = 8   
REVERSAL_OVERRIDE_MIN_COND = 4   

# ── Session Thresholds (V.23 Legendary Scalper) ───────────────────────────────
# [S4] OOS threshold lowered: a God-Tier PA+Sweep confluence should fire
# ── Session Thresholds ──
SCORE_THRESHOLD_IN_SESSION  = 62
SCORE_THRESHOLD_OUT_SESSION = 80

# [S4] God-Tier bypass: if score clears this absolute bar, session gate is
#      fully ignored regardless of SCORE_THRESHOLD_OUT_SESSION.
OOS_GOD_TIER_BYPASS_SCORE   = 90

SCORE_THRESHOLD: Dict[str, int] = {
    "LONDON":        82,    # ลดลงนิดหน่อยให้ยิงได้บ้างถ้าสวยจริง
    "PRE_LONDON":    70,    
    "NY_OPEN_EARLY": 75,    
    "NEW_YORK":      64,    # จุด Sweet Spot สำหรับการรัว 2-5 ไม้
    "DEFAULT":       68,
}

# ── Risk Tiers ────────────────────────────────────────────────────────────────
RISK_TIERS = [
    (82, 3.50),   # God-Tier (Absolute Perfection)
    (70, 2.00),   # Sniper
    (65, 1.50),   # Standard Confluence
]

MAX_LOSS_PCT_HARD_CAP = 3.5  # Dynamic compounding hard cap (5% of current equity)
MAX_LOSS_PER_TRADE_USD = 100.0

# ── FVG ───────────────────────────────────────────────────────────────────────
MOMENTUM_BODY_ATR  = 0.8
FVG_ENTRY_MID      = False
FVG_BUFFER_RATIO   = 0.5
FVG_MOMENTUM_RATIO = 0.25
FVG_MITIGATED_PCT  = 0.5
FVG_MIN_GAP_ATR    = 0.15
FVG_MEMORY_BARS: Dict[str, int] = {
    "PRE_LONDON": 24, "LONDON": 36,
    "NY_OPEN_EARLY": 30, "NEW_YORK": 36, "DEFAULT": 30,
}

# ── Judas ─────────────────────────────────────────────────────────────────────
JUDAS_SWING_ENABLED = True
JUDAS_WINDOW_MIN    = 60

# ── Liquidity ─────────────────────────────────────────────────────────────────
LIQ_SWING_PERIOD    = 10
LIQ_EQUAL_TOLERANCE = 0.0003
LIQ_MIN_CLUSTER     = 2

# ── Swing / HTF ───────────────────────────────────────────────────────────────
SWING_PERIOD       = 5
SWING_CONFIRM_BARS = 2
HTF_BARS           = 150
HTF_SWING_PERIOD   = 5
HTF_SWING_CONFIRM  = 2
H1_BARS            = 100
H1_SWING_PERIOD    = 4
H1_SWING_CONFIRM   = 2

# ── ADR ───────────────────────────────────────────────────────────────────────
ADR_EXHAUSTED_PCT    = 0.88
ADR_NY_EXHAUSTED_PCT = 0.92
ADR_HARD_BLOCK       = False
ADR_TP_BUFFER_PCT    = 0.95

# ── MSS / CISD ────────────────────────────────────────────────────────────────
MSS_ENABLED    = True
CISD_ATR_MULT  = 1.5

# ── V/U-Shape ─────────────────────────────────────────────────────────────────
VSHAPE_ENABLED      = True
VSHAPE_ATR_MULT     = 1.8
VSHAPE_RETRACE_PCT  = 0.60
VSHAPE_MAX_BARS     = 3
USHAPE_MAX_BARS     = 5

# ── Golden Confluence ─────────────────────────────────────────────────────────
GOLDEN_CONFL_ENABLED  = True
OTE_LOW_PCT           = 0.618
OTE_HIGH_PCT          = 0.79
DISPLACEMENT_ATR_MULT = 1.2

# ── Sessions / Kill Zones ─────────────────────────────────────────────────────
PRE_LONDON_SWEEP_REQUIRED = True
KILLZONE_ENABLED = True
KILLZONES = [
    (18, 30, 19, 15, "NY Open Early"),
    (19, 45, 22, 0,  "NY Open"),
]
SESSIONS = [
    (12, 0, 14, 0, "PRE_LONDON"),
    (14, 0, 18, 0, "LONDON"),
    (18, 30, 19, 15, "NY_OPEN_EARLY"),
    (19, 45, 23, 59, "NEW_YORK"),
]
NEWS_STATIC_FALLBACK = [(19, 15, 19, 45), (15, 25, 15, 35)]

# Global risk limits
GLOBAL_MAX_CONCURRENT_TRADES = 3  
MAX_TRADES_PER_SYMBOL        = 1    
MAX_GLOBAL_EXPOSURE_PCT      = 12.0


# ─────────────────────────────────────────────────────────────────────────────
#  DATA CLASSES
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class HTFBiasResult:
    bias: str = "NEUTRAL"; last_bos: str = "NONE"; choch_signal: str = "NONE"
    swept_high: Optional[float] = None; swept_low: Optional[float] = None
    last_sh_val: Optional[float] = None; last_sl_val: Optional[float] = None
    reason: str = ""

@dataclass
class FVGZone:
    kind: str; top: float; bot: float; strength: float; bar_index: int
    mitigated: bool = False

@dataclass
class LiquidityMap:
    buy_side: List[float] = field(default_factory=list)
    sell_side: List[float] = field(default_factory=list)
    swept_high: Optional[float] = None; swept_low: Optional[float] = None
    gap_swept_high: Optional[float] = None; gap_swept_low: Optional[float] = None
    bsl_nearest: Optional[float] = None; ssl_nearest: Optional[float] = None

@dataclass
class OBResult:
    found: bool = False; high: float = 0.0; low: float = 0.0
    score: float = 0.0; bar_age: int = 0; mitigated: bool = False

@dataclass
class MSSResult:
    confirmed: bool = False; cisd: bool = False
    break_level: float = 0.0; body_atr_mult: float = 0.0

@dataclass
class SetupResult:
    signal: str = "WAIT"; score: int = 0; entry: float = 0.0; sl: float = 0.0
    atr: float = 0.0; htf_bias: str = "NEUTRAL"; h1_bias: str = "NEUTRAL"
    m15_struct: str = "NEUTRAL"; adr_pct: float = 0.0
    threshold: int = SCORE_THRESHOLD_IN_SESSION
    reasons: List[str] = field(default_factory=list)
    setup_hash: str = ""; use_market: bool = False
    liq_map: Optional[LiquidityMap] = None
    fvg_zone: Optional[FVGZone] = None; candle_ts: float = 0.0
    htf_result: Optional[HTFBiasResult] = None
    pd_zone: str = "NEUTRAL"; win_prob: float = 0.0; spread_pts: float = 0.0
    is_judas: bool = False; sweep_type: str = "NONE"; shape: str = "NONE"
    mss: Optional[MSSResult] = None; golden_conf: bool = False; in_session: bool = True
    pa_result: Optional["PAResult"] = None       # [S1] Price Action detection result
    reversal_override: bool = False              # [S2] Whether HTF penalty was overridden

    def summary(self) -> str:
        gap  = self.score - self.threshold
        conf = "💎" if gap >= 25 else "🔥🔥" if gap >= 12 else "🔥" if gap >= 0 else "⚠️"
        mode = "MKT" if self.use_market else "LMT"
        tags = []
        if self.is_judas:            tags.append("⚡JUDAS")
        if self.golden_conf:         tags.append("✨GOLDEN")
        if self.shape == "V":        tags.append("📐V")
        if self.shape == "U":        tags.append("🌊U")
        if not self.in_session:      tags.append("🌙OOS")
        if self.reversal_override:   tags.append("🔄OVERRIDE")
        if self.pa_result and self.pa_result.pattern == "PINBAR": tags.append("📍PIN")
        if self.pa_result and self.pa_result.pattern == "DOJI":   tags.append("⚖️DOJI")
        return (f"{conf} {' '.join(tags)} {self.signal}({mode}) "
                f"Score:{self.score}/{self.threshold} | {' | '.join(self.reasons)}")


# ─────────────────────────────────────────────────────────────────────────────
#  VECTORISED PRIMITIVES
# ─────────────────────────────────────────────────────────────────────────────
def _to_numpy(df: pd.DataFrame, col: str) -> np.ndarray:
    return np.ascontiguousarray(df[col].values, dtype=np.float64)

@njit(cache=True)
def _numba_sliding_max(arr: np.ndarray, window: int) -> np.ndarray:
    n = len(arr)
    result = np.empty(n, dtype=np.float64)
    if n < window:
        return arr.copy()
    for i in range(n):
        if i < window - 1:
            result[i] = arr[i]
        else:
            m = arr[i]
            for j in range(1, window):
                if arr[i-j] > m: m = arr[i-j]
            result[i] = m
    return result

@njit(cache=True)
def _numba_sliding_min(arr: np.ndarray, window: int) -> np.ndarray:
    n = len(arr)
    result = np.empty(n, dtype=np.float64)
    if n < window:
        return arr.copy()
    for i in range(n):
        if i < window - 1:
            result[i] = arr[i]
        else:
            m = arr[i]
            for j in range(1, window):
                if arr[i-j] < m: m = arr[i-j]
            result[i] = m
    return result

def _sliding_max(arr: np.ndarray, window: int) -> np.ndarray:
    if _NUMBA_AVAILABLE: return _numba_sliding_max(arr.astype(np.float64), window)
    if _SCIPY_AVAILABLE: return _max_filter1d(arr, size=window, mode="nearest")
    n = len(arr)
    if n < window: return arr.copy()
    shape   = (n - window + 1, window)
    strides = (arr.strides[0], arr.strides[0])
    windows = np.lib.stride_tricks.as_strided(arr, shape=shape, strides=strides)
    result  = np.empty(n, dtype=arr.dtype)
    result[:window - 1] = arr[:window - 1]
    result[window - 1:] = windows.max(axis=1)
    return result

def _sliding_min(arr: np.ndarray, window: int) -> np.ndarray:
    if _NUMBA_AVAILABLE: return _numba_sliding_min(arr.astype(np.float64), window)
    if _SCIPY_AVAILABLE: return _min_filter1d(arr, size=window, mode="nearest")
    n = len(arr)
    if n < window: return arr.copy()
    shape   = (n - window + 1, window)
    strides = (arr.strides[0], arr.strides[0])
    windows = np.lib.stride_tricks.as_strided(arr, shape=shape, strides=strides)
    result  = np.empty(n, dtype=arr.dtype)
    result[:window - 1] = arr[:window - 1]
    result[window - 1:] = windows.min(axis=1)
    return result

@njit(cache=True)
def _numba_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> float:
    n = len(high)
    if n < period + 1: return 0.0
    tr = np.zeros(n - 1, dtype=np.float64)
    for i in range(1, n):
        hl = high[i] - low[i]
        hc = np.abs(high[i] - close[i-1])
        lc = np.abs(low[i] - close[i-1])
        m = hl
        if hc > m: m = hc
        if lc > m: m = lc
        tr[i-1] = m
    
    if len(tr) < period: return 0.0
    sum_tr = 0.0
    for i in range(period): sum_tr += tr[i]
    v = sum_tr / period
    alpha = 1.0 / period
    for i in range(period, len(tr)):
        v = v * (1.0 - alpha) + tr[i] * alpha
    return float(v)

def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < period + 1: return 0.0
    if _NUMBA_AVAILABLE:
        return _numba_atr(_to_numpy(df, "high"), _to_numpy(df, "low"), _to_numpy(df, "close"), period)
    high  = _to_numpy(df, "high"); low  = _to_numpy(df, "low"); close = _to_numpy(df, "close")
    prev  = close[:-1]
    tr    = np.maximum(high[1:] - low[1:], np.maximum(np.abs(high[1:] - prev), np.abs(low[1:] - prev)))
    if len(tr) < period: return 0.0
    v = float(tr[:period].mean()); alpha = 1.0 / period
    for x in tr[period:]: v = v * (1.0 - alpha) + float(x) * alpha
    return v if not np.isnan(v) else 0.0

def calculate_adr(df_d1: Optional[pd.DataFrame], period: int = 10) -> float:
    if df_d1 is None or len(df_d1) < period: return 0.0
    return float((_to_numpy(df_d1, "high") - _to_numpy(df_d1, "low"))[-period:].mean())

@njit(cache=True)
def _numba_swings(high: np.ndarray, low: np.ndarray, period: int, confirm: int) -> tuple:
    n = len(high)
    safe = n - confirm
    last_sh = high[0]
    for i in range(1, n):
        if high[i] > last_sh: last_sh = high[i]
    last_sl = low[0]
    for i in range(1, n):
        if low[i] < last_sl: last_sl = low[i]
        
    for i in range(period, safe - period):
        start_idx = max(0, i - period)
        end_idx = min(n, i + period + 1)
        
        is_high = True
        for j in range(start_idx, end_idx):
            if high[j] > high[i]:
                is_high = False
                break
        if is_high:
            last_sh = high[i]
            
        is_low = True
        for j in range(start_idx, end_idx):
            if low[j] < low[i]:
                is_low = False
                break
        if is_low:
            last_sl = low[i]
            
    return float(last_sh), float(last_sl)

def get_confirmed_swings_np(df: pd.DataFrame, period: int = 5, confirm: int = 2) -> Tuple[float, float]:
    if len(df) < period * 2 + confirm + 1:
        return float(df["high"].max()), float(df["low"].min())
    if _NUMBA_AVAILABLE:
        return _numba_swings(_to_numpy(df, "high"), _to_numpy(df, "low"), period, confirm)
    high = _to_numpy(df, "high"); low = _to_numpy(df, "low"); n = len(high)
    safe = n - confirm; sh, sl = [], []
    for i in range(period, safe - period):
        wh = high[max(0, i - period): min(n, i + period + 1)]
        wl = low[max(0, i - period): min(n, i + period + 1)]
        if high[i] == wh.max(): sh.append(high[i])
        if low[i]  == wl.min(): sl.append(low[i])
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
    n = len(high); safe = n - 2
    tol = max(atr * 0.08, abs(cls[-1]) * LIQ_EQUAL_TOLERANCE)
    ph, pl = [], []
    for i in range(period, safe - period):
        wh = high[max(0, i - period): min(n, i + period + 1)]
        wl = low[max(0, i - period): min(n, i + period + 1)]
        if high[i] == wh.max(): ph.append(high[i])
        if low[i]  == wl.min(): pl.append(low[i])
    liq.buy_side  = sorted(_cluster_liquidity_levels(ph, tol), reverse=True)
    liq.sell_side = sorted(_cluster_liquidity_levels(pl, tol))
    last_high = float(high[-1]); last_low = float(low[-1])
    last_close = float(cls[-1]); prev_close = float(cls[-2]) if len(cls) >= 2 else last_close
    cur_open = float(opn[-1])
    for lvl in liq.buy_side:
        if last_high > lvl and last_close < lvl: liq.swept_high = lvl; break
    for lvl in liq.sell_side:
        if last_low  < lvl and last_close > lvl: liq.swept_low  = lvl; break
    for lvl in liq.buy_side:
        if prev_close >= lvl > cur_open: liq.gap_swept_high = lvl; break
    for lvl in liq.sell_side:
        if prev_close <= lvl < cur_open: liq.gap_swept_low  = lvl; break
    above = [l for l in liq.buy_side  if l > last_close]
    below = [l for l in liq.sell_side if l < last_close]
    liq.bsl_nearest = min(above) if above else None
    liq.ssl_nearest = max(below) if below else None
    return liq

def scan_fvg_memory(df: pd.DataFrame, atr: float, lookback: int = 30) -> List[FVGZone]:
    zones: List[FVGZone] = []
    if len(df) < lookback + 3 or atr == 0: return zones
    min_gap = atr * FVG_MIN_GAP_ATR
    start   = max(3, len(df) - lookback)
    high_arr = _to_numpy(df, "high"); low_arr = _to_numpy(df, "low")
    close_arr = _to_numpy(df, "close"); open_arr = _to_numpy(df, "open")
    n = len(df)
    for i in range(start, n - 2):
        c2_range = high_arr[i+1] - low_arr[i+1]
        c2_body  = abs(close_arr[i+1] - open_arr[i+1])
        if c2_range > 0 and (c2_body / c2_range) < FVG_MOMENTUM_RATIO: continue
        gap_bull = low_arr[i+2] - high_arr[i]
        if gap_bull >= min_gap:
            top = low_arr[i+2]; bot = high_arr[i]; gap = top - bot
            mid = bot + gap * FVG_MITIGATED_PCT
            future_lows = low_arr[i+3:] if i+3 < n else np.array([])
            mitigated = bool(len(future_lows) > 0 and future_lows.min() <= mid)
            zones.append(FVGZone("BULLISH", top, bot, min(2.0, gap / atr), i, mitigated))
        gap_bear = low_arr[i] - high_arr[i+2]
        if gap_bear >= min_gap:
            top = low_arr[i]; bot = high_arr[i+2]; gap = top - bot
            mid = top - gap * FVG_MITIGATED_PCT
            future_highs = high_arr[i+3:] if i+3 < n else np.array([])
            mitigated = bool(len(future_highs) > 0 and future_highs.max() >= mid)
            zones.append(FVGZone("BEARISH", top, bot, min(2.0, gap / atr), i, mitigated))
    zones.sort(key=lambda z: z.bar_index, reverse=True)
    return zones

def get_active_fvg(zones: List[FVGZone], price: float, direction: str) -> Optional[FVGZone]:
    target = "BULLISH" if direction == "BUY" else "BEARISH"
    for z in zones:
        if z.mitigated or z.kind != target: continue
        buf = (z.top - z.bot) * FVG_BUFFER_RATIO
        if (z.bot - buf) <= price <= (z.top + buf): return z
    return None

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

class VShapeDetector:
    @staticmethod
    def classify(df_m5: pd.DataFrame, atr: float, direction: str) -> str:
        if not VSHAPE_ENABLED or len(df_m5) < VSHAPE_MAX_BARS + 4 or atr == 0: return "NONE"
        df = df_m5.reset_index(drop=True); n = len(df)
        if n < 4: return "NONE"
        sweep_c = df.iloc[-2]
        if n < 3: return "NONE"
        origin_c = df.iloc[-3]
        if direction == "BUY":
            sweep_extreme = float(sweep_c["low"]); origin = float(origin_c["close"])
            retrace_dist  = origin - sweep_extreme
            body = abs(float(sweep_c["close"]) - float(sweep_c["open"]))
            if body < atr * VSHAPE_ATR_MULT: return "NONE"
            for k in range(1, VSHAPE_MAX_BARS + 1):
                idx = -1 - k
                if abs(idx) > n: break
                c = df.iloc[idx]
                if retrace_dist > 0 and (float(c["close"]) - sweep_extreme) / retrace_dist >= VSHAPE_RETRACE_PCT:
                    return "V"
            wick_mid = (sweep_extreme + float(sweep_c["close"])) / 2
            inside = sum(1 for k in range(1, USHAPE_MAX_BARS + 1)
                         if (1 + k) <= n and float(df.iloc[-1 - k]["close"]) < wick_mid)
            return "U" if inside >= USHAPE_MAX_BARS - 1 else "NONE"
        else:
            sweep_extreme = float(sweep_c["high"]); origin = float(origin_c["close"])
            retrace_dist  = sweep_extreme - origin
            body = abs(float(sweep_c["close"]) - float(sweep_c["open"]))
            if body < atr * VSHAPE_ATR_MULT: return "NONE"
            for k in range(1, VSHAPE_MAX_BARS + 1):
                idx = -1 - k
                if abs(idx) > n: break
                c = df.iloc[idx]
                if retrace_dist > 0 and (sweep_extreme - float(c["close"])) / retrace_dist >= VSHAPE_RETRACE_PCT:
                    return "V"
            wick_mid = (sweep_extreme + float(sweep_c["close"])) / 2
            inside = sum(1 for k in range(1, USHAPE_MAX_BARS + 1)
                         if (1 + k) <= n and float(df.iloc[-1 - k]["close"]) > wick_mid)
            return "U" if inside >= USHAPE_MAX_BARS - 1 else "NONE"

def get_htf_bias(df_h4: Optional[pd.DataFrame]) -> HTFBiasResult:
    res = HTFBiasResult()
    if df_h4 is None or len(df_h4) < HTF_SWING_PERIOD * 2 + HTF_SWING_CONFIRM + 5:
        res.reason = "H4 insufficient"; return res
    lookback = min(HTF_BARS, len(df_h4))
    df = df_h4.iloc[-lookback:].reset_index(drop=True)
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
    bos_up   = bool(np.any(cls[-5:] > prev_sh)); bos_down = bool(np.any(cls[-5:] < prev_sl))
    hh = sh_list[-1][1] > sh_list[-2][1]; lh = sh_list[-1][1] < sh_list[-2][1]
    hl = sl_list[-1][1] > sl_list[-2][1]; ll = sl_list[-1][1] < sl_list[-2][1]
    bull = bear = 0
    if bos_up:   bull += 2; res.last_bos = "UP"
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

def get_h1_bias(df_h1: Optional[pd.DataFrame]) -> str:
    if df_h1 is None or len(df_h1) < H1_SWING_PERIOD * 2 + H1_SWING_CONFIRM + 5: return "NEUTRAL"
    lookback = min(H1_BARS, len(df_h1))
    df = df_h1.iloc[-lookback:].reset_index(drop=True)
    high = _to_numpy(df, "high"); low = _to_numpy(df, "low"); cls = _to_numpy(df, "close")
    safe = len(high) - H1_SWING_CONFIRM; sh, sl = [], []
    for i in range(H1_SWING_PERIOD, safe - H1_SWING_PERIOD):
        if high[i] == high[i - H1_SWING_PERIOD: i + H1_SWING_PERIOD + 1].max(): sh.append(high[i])
        if low[i]  == low[i  - H1_SWING_PERIOD: i + H1_SWING_PERIOD + 1].min(): sl.append(low[i])
    if len(sh) < 2 or len(sl) < 2: return "NEUTRAL"
    bos_up   = bool(np.any(cls[-3:] > sh[-1])); bos_down = bool(np.any(cls[-3:] < sl[-1]))
    hh = sh[-1] > sh[-2]; lh = sh[-1] < sh[-2]
    hl = sl[-1] > sl[-2]; ll = sl[-1] < sl[-2]
    if bos_up  and hh and hl: return "BULLISH"
    if bos_down and lh and ll: return "BEARISH"
    return "NEUTRAL"

def get_m15_structure(df_m15: Optional[pd.DataFrame]) -> str:
    if df_m15 is None or len(df_m15) < SWING_PERIOD * 2 + SWING_CONFIRM_BARS + 5: return "NEUTRAL"
    sub = df_m15.iloc[-40:].reset_index(drop=True)
    sh, sl = get_confirmed_swings_np(sub, SWING_PERIOD, SWING_CONFIRM_BARS)
    last_c = float(sub["close"].iloc[-1]); buf = (sh - sl) * 0.005
    if last_c > sh + buf: return "BULLISH_BOS"
    if last_c < sl - buf: return "BEARISH_BOS"
    return "NEUTRAL"

def check_mss_cisd(df_m5: pd.DataFrame, atr: float, direction: str) -> MSSResult:
    result = MSSResult()
    if not MSS_ENABLED or len(df_m5) < SWING_PERIOD * 2 + 5 or atr == 0: return result
    sub  = df_m5.iloc[-20:].reset_index(drop=True); last = sub.iloc[-1]
    sh, sl = get_confirmed_swings_np(sub, SWING_PERIOD, SWING_CONFIRM_BARS)
    body = abs(float(last["close"]) - float(last["open"])); body_mult = body / atr
    if direction == "BUY":
        if float(last["close"]) > sh:
            result.confirmed = True; result.break_level = sh
            result.body_atr_mult = body_mult; result.cisd = body_mult >= CISD_ATR_MULT
    else:
        if float(last["close"]) < sl:
            result.confirmed = True; result.break_level = sl
            result.body_atr_mult = body_mult; result.cisd = body_mult >= CISD_ATR_MULT
    return result

def check_golden_confluence(fvg_zone: Optional[FVGZone], df_m5: pd.DataFrame,
                              htf_res: HTFBiasResult, atr: float, direction: str) -> bool:
    if not GOLDEN_CONFL_ENABLED or fvg_zone is None or fvg_zone.mitigated: return False
    if htf_res.last_sh_val is None or htf_res.last_sl_val is None: return False
    swing_h = htf_res.last_sh_val; swing_l = htf_res.last_sl_val
    swing_range = swing_h - swing_l
    if swing_range <= 0: return False
    if direction == "BUY":
        ote_high = swing_h - swing_range * OTE_LOW_PCT
        ote_low  = swing_h - swing_range * OTE_HIGH_PCT
    else:
        ote_high = swing_l + swing_range * OTE_HIGH_PCT
        ote_low  = swing_l + swing_range * OTE_LOW_PCT
    fvg_mid = fvg_zone.bot + (fvg_zone.top - fvg_zone.bot) * 0.5
    if not (ote_low <= fvg_mid <= ote_high): return False
    if len(df_m5) < 2: return False
    last_body = abs(float(df_m5.iloc[-1]["close"]) - float(df_m5.iloc[-1]["open"]))
    return last_body >= atr * DISPLACEMENT_ATR_MULT

def classify_sweep(signal: str, htf_bias: str) -> str:
    if signal == "BUY"  and htf_bias == "BULLISH": return "CONTINUE"
    if signal == "SELL" and htf_bias == "BEARISH": return "CONTINUE"
    if signal == "BUY"  and htf_bias == "BEARISH": return "REVERSE"
    if signal == "SELL" and htf_bias == "BULLISH": return "REVERSE"
    return "NEUTRAL_HTF"

def apply_adr_tp_cap(entry: float, tp_raw: float, sl: float, adr: float,
                      df_d1: Optional[pd.DataFrame], session: str, signal: str) -> Tuple[float, bool]:
    if adr <= 0 or df_d1 is None or len(df_d1) < 1: return tp_raw, False
    day_high = float(df_d1["high"].iloc[-1]); day_low = float(df_d1["low"].iloc[-1])
    adr_ceil = ADR_NY_EXHAUSTED_PCT if session in ("NEW_YORK", "NY_OPEN_EARLY") else ADR_EXHAUSTED_PCT
    capped = False; tp_adj = tp_raw
    if signal == "BUY":
        cap = day_low + adr * adr_ceil
        if tp_raw > cap: tp_adj = entry + (cap - entry) * ADR_TP_BUFFER_PCT; capped = True
    elif signal == "SELL":
        cap = day_high - adr * adr_ceil
        if tp_raw < cap: tp_adj = entry - (entry - cap) * ADR_TP_BUFFER_PCT; capped = True
    risk = abs(entry - sl)
    if signal == "BUY":
        if (tp_adj - entry) < risk: tp_adj = tp_raw; capped = False
        if tp_adj <= entry:         tp_adj = tp_raw; capped = False
    if signal == "SELL":
        if (entry - tp_adj) < risk: tp_adj = tp_raw; capped = False
        if tp_adj >= entry:         tp_adj = tp_raw; capped = False
    return tp_adj, capped

def is_judas_swing(liq: LiquidityMap, fvg_zones: List[FVGZone],
                   signal: str, session: str, bar_time: datetime) -> bool:
    if not JUDAS_SWING_ENABLED: return False
    session_opens = {"LONDON": dtime(14, 0), "NY_OPEN_EARLY": dtime(18, 30), "NEW_YORK": dtime(19, 45)}
    open_t = session_opens.get(session)
    if open_t is None: return False
    t = bar_time.astimezone(STRATEGY_TZ).time()
    mins_since = (t.hour * 60 + t.minute) - (open_t.hour * 60 + open_t.minute)
    if not (0 <= mins_since <= JUDAS_WINDOW_MIN): return False
    if signal == "BUY"  and liq.swept_low  is not None:
        return any(z.kind == "BULLISH" and not z.mitigated for z in fvg_zones)
    if signal == "SELL" and liq.swept_high is not None:
        return any(z.kind == "BEARISH" and not z.mitigated for z in fvg_zones)
    return False

def get_session(bar_time: datetime) -> str:
    t = bar_time.astimezone(STRATEGY_TZ).time()
    for sh, sm, eh, em in NEWS_STATIC_FALLBACK:
        if dtime(sh, sm) <= t <= dtime(eh, em): return "RED_NEWS_BLOCK"
    for sh, sm, eh, em, name in SESSIONS:
        s, e = dtime(sh, sm), dtime(eh, em)
        if e < s:
            if t >= s or t <= e: return name
        else:
            if s <= t <= e: return name
    return "OUT_OF_SESSION"

def is_in_killzone(bar_time: datetime) -> Tuple[bool, str]:
    if not KILLZONE_ENABLED: return True, "All"
    t = bar_time.astimezone(STRATEGY_TZ).time()
    for sh, sm, eh, em, name in KILLZONES:
        if dtime(sh, sm) <= t <= dtime(eh, em): return True, name
    return False, "Outside Killzone"

def get_dynamic_threshold(session: str, in_session: bool, score: int = 0) -> int:
    # [S4] God-Tier bypass: an extreme-confluence score ignores the session gate entirely
    if not in_session:
        if score >= OOS_GOD_TIER_BYPASS_SCORE:
            return SCORE_THRESHOLD_IN_SESSION  # use the lower in-session bar
        return SCORE_THRESHOLD_OUT_SESSION
    return SCORE_THRESHOLD.get(session, SCORE_THRESHOLD_IN_SESSION)


# ─────────────────────────────────────────────────────────────────────────────
#  [S1] PRICE ACTION DETECTOR  (NEW in V.23)
#  Detects Pinbar and Doji rejection candles AT a swept liquidity extreme.
#  "The market always leaves a fingerprint at the turning point." — Druckenmiller
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class PAResult:
    pattern: str = "NONE"   # "PINBAR" | "DOJI" | "NONE"
    score: int = 0
    at_swept_level: bool = False
    direction: str = "NONE"  # "BULL_REJECT" | "BEAR_REJECT"
    reason: str = ""

def detect_price_action(
    candle: pd.Series,
    atr: float,
    swept_high: Optional[float],
    swept_low: Optional[float],
    direction: str,          # "BUY" or "SELL" — intended trade direction
) -> PAResult:
    """
    [S1] Pinbar / Doji detector for the most recent closed candle.

    Pinbar (bullish rejection, for BUY):
      - Candle spiked below swept_low (wick pierces it)
      - Lower wick ≥ 2.5× body size
      - Body is in the upper 40% of the candle range
      - Body size < 40% of candle range

    Pinbar (bearish rejection, for SELL):
      - Candle spiked above swept_high (wick pierces it)
      - Upper wick ≥ 2.5× body size
      - Body is in the lower 40% of the candle range
      - Body size < 40% of candle range

    Doji (indecision at extreme):
      - Body < 15% of full candle range
      - Candle high/low touches swept level (within 0.5 ATR)
    """
    res = PAResult()
    if atr == 0:
        return res

    op   = float(candle["open"])
    hi   = float(candle["high"])
    lo   = float(candle["low"])
    cl   = float(candle["close"])

    candle_range = hi - lo
    if candle_range < atr * 0.1:
        # Candle is too small to be meaningful
        return res

    body_size   = abs(cl - op)
    body_top    = max(cl, op)
    body_bot    = min(cl, op)
    body_ratio  = body_size / candle_range  # 0..1, smaller = more indecision

    upper_wick  = hi - body_top
    lower_wick  = body_bot - lo

    PROXIMITY   = atr * 0.5  # How close to swept level counts as "at"

    # ── [S6] DOJI CHECK ──────────────────────────────────────────────────────
    if body_ratio < 0.15:
        if direction == "BUY" and swept_low is not None:
            if abs(lo - swept_low) <= PROXIMITY:
                res.pattern       = "DOJI"
                res.at_swept_level = True
                res.direction     = "BULL_REJECT"
                res.score         = SCORE_PA_DOJI
                res.reason        = (f"Doji@SSL({swept_low:.4f}) "
                                     f"body={body_ratio*100:.0f}%rng")
                return res
        if direction == "SELL" and swept_high is not None:
            if abs(hi - swept_high) <= PROXIMITY:
                res.pattern       = "DOJI"
                res.at_swept_level = True
                res.direction     = "BEAR_REJECT"
                res.score         = SCORE_PA_DOJI
                res.reason        = (f"Doji@BSL({swept_high:.4f}) "
                                     f"body={body_ratio*100:.0f}%rng")
                return res

    # ── [S5] PINBAR CHECK ────────────────────────────────────────────────────
    WICK_BODY_RATIO = 2.0   # Wick must be ≥ 2.0× body
    BODY_MAX_RATIO  = 0.45  # Body ≤ 45% of candle range for a clean pin

    if direction == "BUY" and swept_low is not None:
        # Bullish pinbar: long lower wick rejecting swept SSL
        if (lo < swept_low                              # wick punched through
                and lower_wick >= atr * 0.4            # meaningful wick size
                and body_ratio <= BODY_MAX_RATIO        # small body
                and (body_size == 0                     # body check
                     or lower_wick / body_size >= WICK_BODY_RATIO)):
            res.pattern       = "PINBAR"
            res.at_swept_level = True
            res.direction     = "BULL_REJECT"
            res.score         = SCORE_PA_PINBAR
            res.reason        = (f"Pinbar↑@SSL({swept_low:.4f}) "
                                 f"lwk={lower_wick/atr:.1f}ATR body={body_ratio*100:.0f}%")
            return res

    if direction == "SELL" and swept_high is not None:
        # Bearish pinbar: long upper wick rejecting swept BSL
        if (hi > swept_high                             # wick punched through
                and upper_wick >= atr * 0.4            # meaningful wick
                and body_ratio <= BODY_MAX_RATIO
                and (body_size == 0
                     or upper_wick / body_size >= WICK_BODY_RATIO)):
            res.pattern       = "PINBAR"
            res.at_swept_level = True
            res.direction     = "BEAR_REJECT"
            res.score         = SCORE_PA_PINBAR
            res.reason        = (f"Pinbar↓@BSL({swept_high:.4f}) "
                                 f"uwk={upper_wick/atr:.1f}ATR body={body_ratio*100:.0f}%")
            return res

    return res


def check_reversal_override(
    has_sweep: bool,
    pa_result: PAResult,
    m15_struct: str,
    htf_res: HTFBiasResult,
    fvg_active: Optional[FVGZone],
    direction: str,
) -> Tuple[bool, int]:
    """
    [S2][S7] Reversal Override Engine.

    When the LTF is screaming reversal (sweep + PA + CHoCH/BOS + FVG),
    the lagging H4 counter-trend penalty is zeroed and a conviction
    bonus is applied.  Returns (override_triggered, score_delta).

    score_delta = abs(SCORE_HTF_AGAINST) + REVERSAL_OVERRIDE_BONUS
      i.e. we first cancel the penalty that was already applied, then
      add a positive bonus on top.  Net effect on a counter-trend setup:
        Old V.22: SCORE_HTF_AGAINST = -15   (punished)
        New V.23: +|SCORE_HTF_AGAINST| + REVERSAL_OVERRIDE_BONUS  (rewarded)
    """
    if not REVERSAL_OVERRIDE_ENABLED:
        return False, 0

    # Only fires when we're actually trading against H4
    is_counter = (
        (direction == "BUY"  and htf_res.bias == "BEARISH") or
        (direction == "SELL" and htf_res.bias == "BULLISH")
    )
    if not is_counter:
        return False, 0

    # Score the LTF confluence conditions
    cond_sweep = has_sweep
    cond_pa    = pa_result.pattern == "PINBAR" and pa_result.at_swept_level

    # CHoCH signal at M15 level (structure break opposing H4)
    choch_up   = (m15_struct == "BULLISH_BOS"
                  and htf_res.bias == "BEARISH"
                  and direction == "BUY")
    choch_down = (m15_struct == "BEARISH_BOS"
                  and htf_res.bias == "BULLISH"
                  and direction == "SELL")
    cond_choch = choch_up or choch_down

    # Also accept H4-level CHoCH signal from HTF analyser
    if htf_res.choch_signal == "UP"   and direction == "BUY":  cond_choch = True
    if htf_res.choch_signal == "DOWN" and direction == "SELL": cond_choch = True

    cond_fvg = fvg_active is not None and not fvg_active.mitigated

    conditions_met = sum([cond_sweep, cond_pa, cond_choch, cond_fvg])
    if conditions_met < REVERSAL_OVERRIDE_MIN_COND:
        return False, 0

    # Cancel the penalty already applied + add conviction bonus
    score_delta = abs(SCORE_HTF_AGAINST) + REVERSAL_OVERRIDE_BONUS
    return True, score_delta


# ─────────────────────────────────────────────────────────────────────────────
#  MASTER SETUP ANALYSER  V.22
#  Single function — imported identically by both live bot and backtest engine
# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
#  [S9] FEATURE ENGINE (MACHINE LEARNING PIPELINE)
# ─────────────────────────────────────────────────────────────────────────────
class FeatureEngine:
    """
    Extracts a normalized state vector for future Machine Learning models
    (e.g., LightGBM / XGBoost) to predict setup probability or win rate.
    """
    @staticmethod
    def extract_features(
        setup: SetupResult,
        df_m5: pd.DataFrame,
        atr: float,
        session: str
    ) -> Dict[str, float]:
        features = {}
        if atr == 0 or len(df_m5) < 3: return features
        
        # 1. Volatility & Price metrics
        features["atr_ratio"] = atr / float(df_m5.iloc[-1]["close"]) * 10000
        last_body = abs(float(df_m5.iloc[-1]["close"]) - float(df_m5.iloc[-1]["open"]))
        features["last_body_atr"] = last_body / atr
        
        # 2. Liquidity Distances
        if setup.signal == "BUY" and setup.liq_map and setup.liq_map.bsl_nearest:
            features["target_dist_atr"] = (setup.liq_map.bsl_nearest - setup.entry) / atr
        elif setup.signal == "SELL" and setup.liq_map and setup.liq_map.ssl_nearest:
            features["target_dist_atr"] = (setup.entry - setup.liq_map.ssl_nearest) / atr
        else:
            features["target_dist_atr"] = 0.0
            
        # 3. Contextual Encoding
        features["htf_bullish"] = 1.0 if setup.htf_bias == "BULLISH" else (0.0 if setup.htf_bias == "BEARISH" else 0.5)
        features["h1_bullish"] = 1.0 if setup.h1_bias == "BULLISH" else (0.0 if setup.h1_bias == "BEARISH" else 0.5)
        
        # 4. Session Encoding (One-Hot approximation)
        session_map = {"PRE_LONDON": 0.2, "LONDON": 0.4, "NY_OPEN_EARLY": 0.8, "NEW_YORK": 1.0, "DEFAULT": 0.0}
        features["session_enc"] = session_map.get(session, 0.0)
        
        # 5. Conviction
        features["raw_score"] = float(setup.score)
        
        return features

# ─────────────────────────────────────────────────────────────────────────────
#  [S10] VOLATILITY & MICRO-STRUCTURE MOMENTUM FILTER
# ─────────────────────────────────────────────────────────────────────────────
class VolatilityFilter:
    @staticmethod
    def is_choppy_regime(df_m5: pd.DataFrame, atr: float) -> bool:
        """
        Detects if the market is in a tight, low-momentum consolidation.
        Filters out fake breakouts.
        """
        if len(df_m5) < 6 or atr == 0: return False
        
        # Calculate recent velocity
        closes = _to_numpy(df_m5, "close")[-5:]
        range_5 = np.max(closes) - np.min(closes)
        
        # If the 5-bar range is less than 1.5 ATR, we are stuck in mud
        if range_5 < atr * 1.5:
            return True
        return False

# ─────────────────────────────────────────────────────────────────────────────
#  MASTER SETUP ANALYSER  (CLASS-BASED REFACTOR)
# ─────────────────────────────────────────────────────────────────────────────
class SetupAnalyzer:
    def __init__(self, df_m5: pd.DataFrame, df_h4: Optional[pd.DataFrame],
                 df_d1: Optional[pd.DataFrame], df_m15: Optional[pd.DataFrame],
                 df_h1: Optional[pd.DataFrame], session: str, bar_time: datetime,
                 in_kz: bool, spread_pts: float, sl_atr_mult: float,
                 df_m1: Optional[pd.DataFrame] = None):
        self.df_m5 = df_m5
        self.df_h4 = df_h4
        self.df_d1 = df_d1
        self.df_m15 = df_m15
        self.df_h1 = df_h1
        self.df_m1 = df_m1
        self.session = session
        self.bar_time = bar_time
        self.in_kz = in_kz
        self.spread_pts = spread_pts
        self.sl_atr_mult = sl_atr_mult
        
        self.r = SetupResult()
        
    def execute(self) -> SetupResult:
        r = self.r
        if self.df_m5 is None or len(self.df_m5) < 30:
            r.reasons.append("M5 insufficient"); return r
        
        self.atr = calculate_atr(self.df_m5)
        if self.atr == 0: r.reasons.append("ATR=0"); return r
        r.atr = self.atr

        self.adr = calculate_adr(self.df_d1)
        if self.adr > 0 and self.df_d1 is not None and len(self.df_d1) >= 1:
            r.adr_pct = float(self.df_d1["high"].iloc[-1] - self.df_d1["low"].iloc[-1]) / self.adr

        self.adr_ceil = ADR_NY_EXHAUSTED_PCT if self.session in ("NEW_YORK", "NY_OPEN_EARLY") else ADR_EXHAUSTED_PCT
        if ADR_HARD_BLOCK and r.adr_pct >= self.adr_ceil:
            r.reasons.append(f"ADR_HARD_BLOCK({r.adr_pct*100:.0f}%)"); return r

        self.htf_res = get_htf_bias(self.df_h4)
        r.htf_bias = self.htf_res.bias
        r.htf_result = self.htf_res
        r.h1_bias = get_h1_bias(self.df_h1)
        r.m15_struct = get_m15_structure(self.df_m15)
        r.in_session = self.in_kz
        r.threshold = get_dynamic_threshold(self.session, self.in_kz, score=0)

        self.liq = build_liquidity_map_np(self.df_m5, self.atr, LIQ_SWING_PERIOD)
        r.liq_map = self.liq
        self.last_sh, self.last_sl = get_confirmed_swings_np(self.df_m5, SWING_PERIOD, SWING_CONFIRM_BARS)
        fvg_lookback = FVG_MEMORY_BARS.get(self.session, FVG_MEMORY_BARS["DEFAULT"])
        self.fvg_zones = scan_fvg_memory(self.df_m5, self.atr, fvg_lookback)

        self.last = self.df_m5.iloc[-1]
        self.prev = self.df_m5.iloc[-2]
        r.candle_ts = float(self.last["time"].timestamp()) if hasattr(self.last["time"], "timestamp") else time.time()
        self.price = float(self.last["close"])

        SWEEP_WICK_ATR_MULT  = 0.15
        SWEEP_CLOSE_ATR_MULT = 0.10

        _ssl_wick = self.last_sl - float(self.last["low"])
        _ssl_close_gap = float(self.last["close"]) - self.last_sl
        self.sweep_sell = (float(self.last["low"]) < self.last_sl
                           and _ssl_wick >= self.atr * SWEEP_WICK_ATR_MULT
                           and _ssl_close_gap >= self.atr * SWEEP_CLOSE_ATR_MULT)

        _bsl_wick = float(self.last["high"]) - self.last_sh
        _bsl_close_gap = self.last_sh - float(self.last["close"])
        self.sweep_buy = (float(self.last["high"]) > self.last_sh
                          and _bsl_wick >= self.atr * SWEEP_WICK_ATR_MULT
                          and _bsl_close_gap >= self.atr * SWEEP_CLOSE_ATR_MULT)

        if self.liq.gap_swept_low is not None: self.sweep_sell = True
        if self.liq.gap_swept_high is not None: self.sweep_buy = True

        best_pa_bull, best_pa_bear = PAResult(), PAResult()
        for i in range(1, 4):
            if len(self.df_m5) < i + 1: break
            c = self.df_m5.iloc[-1 - i]
            pa_b = detect_price_action(c, self.atr, swept_high=self.last_sh if self.sweep_buy else None, swept_low=self.last_sl if self.sweep_sell else None, direction="BUY")
            pa_s = detect_price_action(c, self.atr, swept_high=self.last_sh if self.sweep_buy else None, swept_low=self.last_sl if self.sweep_sell else None, direction="SELL")
            if pa_b.score > best_pa_bull.score: best_pa_bull = pa_b
            if pa_s.score > best_pa_bear.score: best_pa_bear = pa_s

        self.pa_bull = best_pa_bull
        self.pa_bear = best_pa_bear

        # Apply Micro-Structure Momentum Filter
        self.is_choppy = VolatilityFilter.is_choppy_regime(self.df_m5, self.atr)
        
        # F15: Choppy Regime Block
        if self.is_choppy:
            r.signal = "WAIT"
            r.reasons.append("⛔ CHOPPY_BLOCK: 5-bar range < 1.5 ATR")
            return r

        if not self._build_buy():
            r.signal = "WAIT"; r.score = 0; r.reasons = []
            if not self._build_sell(): 
                return r

        if r.signal != "WAIT":
            entry_h = r.entry if not r.use_market else -1.0
            r.setup_hash = hashlib.sha256(f"{r.signal}:{entry_h:.2f}:{r.sl:.2f}:{int(r.candle_ts)}".encode()).hexdigest()[:12]
            
            # Extract ML Features
            ml_features = FeatureEngine.extract_features(r, self.df_m5, self.atr, self.session)
            if ml_features:
                r.reasons.append(f"ML_Ready:{len(ml_features)}f")
                
        return r

    def _htf_scores(self, sig: str, fvg_active: Optional[FVGZone], has_sweep: bool, pa_result: PAResult) -> None:
        r = self.r
        if r.htf_bias == "BULLISH" and sig == "BUY":
            r.score += SCORE_HTF_ALIGN
            r.reasons.append(f"H4 Bull{'(CHOCH)' if self.htf_res.choch_signal=='UP' else ''} +{SCORE_HTF_ALIGN}")
        elif r.htf_bias == "BEARISH" and sig == "SELL":
            r.score += SCORE_HTF_ALIGN
            r.reasons.append(f"H4 Bear{'(CHOCH)' if self.htf_res.choch_signal=='DOWN' else ''} +{SCORE_HTF_ALIGN}")
        elif ((r.htf_bias == "BULLISH" and sig == "SELL") or (r.htf_bias == "BEARISH" and sig == "BUY")):
            r.score += SCORE_HTF_AGAINST
            r.reasons.append(f"H4 Against {SCORE_HTF_AGAINST}")
            override, delta = check_reversal_override(has_sweep, pa_result, r.m15_struct, self.htf_res, fvg_active, sig)
            if override:
                r.score += delta
                r.reversal_override = True
                r.reasons.append(f"🔄 ReversalOverride +{delta} (sweep={has_sweep} PA={pa_result.pattern} CHoCH={self.htf_res.choch_signal or r.m15_struct} FVG={fvg_active is not None})")
        else:
            r.score += SCORE_HTF_NEUTRAL
            r.reasons.append(f"H4 Neutral {SCORE_HTF_NEUTRAL}")

    def _h1_scores(self, sig: str) -> None:
        if ((self.r.h1_bias == "BULLISH" and sig == "BUY") or (self.r.h1_bias == "BEARISH" and sig == "SELL")):
            self.r.score += H1_AGREE_BONUS; self.r.reasons.append(f"H1 Agree +{H1_AGREE_BONUS}")
        elif ((self.r.h1_bias == "BULLISH" and sig == "SELL") or (self.r.h1_bias == "BEARISH" and sig == "BUY")):
            self.r.score += H1_CONFLICT_PENALTY; self.r.reasons.append(f"H1 Conflict {H1_CONFLICT_PENALTY}")

    def _apply_structure_scores(self, sig: str, fvg_active: Optional[FVGZone]) -> None:
        r = self.r
        if ((sig == "BUY" and r.m15_struct == "BULLISH_BOS") or (sig == "SELL" and r.m15_struct == "BEARISH_BOS")):
            r.score += SCORE_M15_BOS; r.reasons.append(f"M15 BOS +{SCORE_M15_BOS}")
        mss = check_mss_cisd(self.df_m5, self.atr, sig); r.mss = mss
        if mss.confirmed:
            pts = SCORE_MSS_CISD if mss.cisd else SCORE_MSS_ONLY
            tag = "MSS+CISD" if mss.cisd else "MSS"
            r.score += pts; r.reasons.append(f"{tag} +{pts}")
        shape = VShapeDetector.classify(self.df_m5, self.atr, sig); r.shape = shape
        if shape == "V": r.score += SCORE_VSHAPE_BONUS; r.reasons.append(f"V-Shape +{SCORE_VSHAPE_BONUS}")
        elif shape == "U": r.score += SCORE_USHAPE_PENALTY; r.reasons.append(f"U-Shape {SCORE_USHAPE_PENALTY}")
        if check_golden_confluence(fvg_active, self.df_m5, self.htf_res, self.atr, sig):
            r.golden_conf = True
            r.score += SCORE_GOLDEN_CONFLUENCE; r.reasons.append(f"✨Golden +{SCORE_GOLDEN_CONFLUENCE}")
        ob = find_order_block(self.df_m5, sig, self.atr)
        if ob.found and not ob.mitigated:
            r.score += SCORE_OB_BONUS; r.reasons.append(f"OB(q:{ob.score:.2f},age:{ob.bar_age}) +{SCORE_OB_BONUS}")

    def _apply_penalties(self, sig: str, fvg_active: Optional[FVGZone]) -> None:
        r = self.r
        if r.adr_pct >= self.adr_ceil:
            r.score += SCORE_ADR_WARN; r.reasons.append(f"ADR{r.adr_pct*100:.0f}% {SCORE_ADR_WARN}")
        if not r.in_session:
            r.reasons.append(f"🌙 OOS (thr={r.threshold})")
        else:
            r.reasons.append(f"🎯 InKZ (thr={r.threshold})")
        
        if self.is_choppy:
            r.score -= 15; r.reasons.append("⚠️ Choppy Regime -15")

        if self.session == "PRE_LONDON" and PRE_LONDON_SWEEP_REQUIRED:
            has_sweep = ((sig == "BUY" and (self.sweep_sell or self.liq.gap_swept_low is not None)) or
                         (sig == "SELL" and (self.sweep_buy or self.liq.gap_swept_high is not None)))
            if not has_sweep and fvg_active is not None:
                r.score -= 15; r.reasons.append("PRE_LDN pure-FVG -15")
        if self.session == "NY_OPEN_EARLY" and r.htf_bias == "NEUTRAL":
            r.score -= 20; r.reasons.append("⚠️ NY_Early+Neutral -20")

        # F07: Mid-Score Range No-Sweep Penalty
        if 68 <= r.score < 80:
            has_sweep = ((sig == "BUY" and self.sweep_sell) or (sig == "SELL" and self.sweep_buy))
            sweep_pts = SCORE_LIQ_SWEPT if has_sweep else 0
            if sweep_pts < 28:
                r.score -= 15; r.reasons.append("⛔ MidScore-NoSweep penalty -15")

        # F10: M1 Confirm Check
        self._apply_m1_confirm(sig)

        if is_judas_swing(self.liq, self.fvg_zones, sig, self.session, self.bar_time):
            r.is_judas = True; r.score += JUDAS_SCORE_BONUS
            r.reasons.append(f"⚡Judas +{JUDAS_SCORE_BONUS}")

    def _apply_m1_confirm(self, sig: str) -> None:
        if self.df_m1 is None or len(self.df_m1) < 4: return
        c = self.df_m1.iloc[-2]
        body_m1 = abs(float(c["close"]) - float(c["open"]))
        dir_ok = ((sig == "BUY" and c["close"] > c["open"]) or (sig == "SELL" and c["close"] < c["open"]))
        if body_m1 >= self.atr * 0.3 and dir_ok:
            self.r.score += SCORE_M1_CONFIRM
            self.r.reasons.append(f"M1 Confirm +{SCORE_M1_CONFIRM}")

    def _liq_target_gate(self, sig: str, entry: float, sl: float) -> bool:
        r = self.r
        risk = abs(entry - sl)
        if risk == 0: return False
        if sig == "BUY" and self.liq.bsl_nearest is not None:
            rr_to_target = (self.liq.bsl_nearest - entry) / risk
            if rr_to_target >= MIN_RR_TO_TARGET:
                r.score += SCORE_LIQ_TARGET
                r.reasons.append(f"BSL→{self.liq.bsl_nearest:.2f} +{SCORE_LIQ_TARGET}")
            return rr_to_target >= MIN_RR_TO_TARGET or self.liq.bsl_nearest is None
        if sig == "SELL" and self.liq.ssl_nearest is not None:
            rr_to_target = (entry - self.liq.ssl_nearest) / risk
            if rr_to_target >= MIN_RR_TO_TARGET:
                r.score += SCORE_LIQ_TARGET
                r.reasons.append(f"SSL→{self.liq.ssl_nearest:.2f} +{SCORE_LIQ_TARGET}")
            return rr_to_target >= MIN_RR_TO_TARGET or self.liq.ssl_nearest is None
        return True

    def _build_buy(self) -> bool:
        r = self.r
        has_sweep = self.sweep_sell
        fvg_active = get_active_fvg(self.fvg_zones, self.price, "BUY")
        if not has_sweep and fvg_active is None: return False
        r.signal = "BUY"; r.score = SCORE_BASE

        pa = self.pa_bull
        r.pa_result = pa
        if pa.score > 0:
            r.score += pa.score
            r.reasons.append(f"📍{pa.pattern} +{pa.score} ({pa.reason})")

        if fvg_active is not None:
            r.entry = (fvg_active.bot + (fvg_active.top - fvg_active.bot) * 0.5 if FVG_ENTRY_MID else fvg_active.top)
            r.fvg_zone = fvg_active
        elif has_sweep:
            r.entry = self.last_sl + self.atr * 0.1
        r.sl = self.last_sl - self.atr * self.sl_atr_mult
        if fvg_active is not None and not fvg_active.mitigated:
            age = (len(self.df_m5) - 1) - fvg_active.bar_index
            decay = max(0, SCORE_FVG_FRESH - (age // 3))
            if decay > 0:
                r.score += decay; r.reasons.append(f"FVG Fresh +{decay} (Age {age})")
            if fvg_active.strength > 0.5:
                r.score += SCORE_FVG_STRENGTH; r.reasons.append(f"FVG Strong +{SCORE_FVG_STRENGTH}")
        if has_sweep:
            r.score += SCORE_LIQ_SWEPT
            lbl = "Gap-Sweep" if self.liq.gap_swept_low else "Sweep"
            r.reasons.append(f"{lbl} SSL +{SCORE_LIQ_SWEPT}")
        if has_sweep and fvg_active is not None:
            r.score += SCORE_SWEEP_AND_FVG; r.reasons.append(f"Sweep+FVG Bonus +{SCORE_SWEEP_AND_FVG}")

        self._htf_scores("BUY", fvg_active, has_sweep, pa)
        self._h1_scores("BUY"); self._apply_structure_scores("BUY", fvg_active)
        if self.htf_res.swept_low is not None:
            r.score += 4; r.reasons.append("H4 SSL Swept +4")
        self._liq_target_gate("BUY", r.entry, r.sl)
        self._apply_penalties("BUY", fvg_active)
        r.sweep_type = classify_sweep("BUY", r.htf_bias)
        r.threshold = get_dynamic_threshold(self.session, self.in_kz, score=r.score)
        body = float(self.last["close"]) - float(self.last["open"])
        if (float(self.last["close"]) > float(self.prev["high"]) and body / self.atr > MOMENTUM_BODY_ATR and r.score >= r.threshold):
            r.use_market = True; r.entry = 0.0; r.reasons.append("🚀 MKT")
        return True

    def _build_sell(self) -> bool:
        r = self.r
        has_sweep = self.sweep_buy
        fvg_active = get_active_fvg(self.fvg_zones, self.price, "SELL")
        if not has_sweep and fvg_active is None: return False
        r.signal = "SELL"; r.score = SCORE_BASE

        pa = self.pa_bear
        r.pa_result = pa
        if pa.score > 0:
            r.score += pa.score
            r.reasons.append(f"📍{pa.pattern} +{pa.score} ({pa.reason})")

        if fvg_active is not None:
            r.entry = (fvg_active.bot + (fvg_active.top - fvg_active.bot) * 0.5 if FVG_ENTRY_MID else fvg_active.bot)
            r.fvg_zone = fvg_active
        elif has_sweep:
            r.entry = self.last_sh - self.atr * 0.1
        r.sl = self.last_sh + self.atr * self.sl_atr_mult
        if fvg_active is not None and not fvg_active.mitigated:
            age = (len(self.df_m5) - 1) - fvg_active.bar_index
            decay = max(0, SCORE_FVG_FRESH - (age // 3))
            if decay > 0:
                r.score += decay; r.reasons.append(f"FVG Fresh +{decay} (Age {age})")
            if fvg_active.strength > 0.5:
                r.score += SCORE_FVG_STRENGTH; r.reasons.append(f"FVG Strong +{SCORE_FVG_STRENGTH}")
        if has_sweep:
            r.score += SCORE_LIQ_SWEPT
            lbl = "Gap-Sweep" if self.liq.gap_swept_high else "Sweep"
            r.reasons.append(f"{lbl} BSL +{SCORE_LIQ_SWEPT}")
        if has_sweep and fvg_active is not None:
            r.score += SCORE_SWEEP_AND_FVG; r.reasons.append(f"Sweep+FVG Bonus +{SCORE_SWEEP_AND_FVG}")

        self._htf_scores("SELL", fvg_active, has_sweep, pa)
        self._h1_scores("SELL"); self._apply_structure_scores("SELL", fvg_active)
        if self.htf_res.swept_high is not None:
            r.score += 4; r.reasons.append("H4 BSL Swept +4")
        self._liq_target_gate("SELL", r.entry, r.sl)
        self._apply_penalties("SELL", fvg_active)
        r.sweep_type = classify_sweep("SELL", r.htf_bias)
        r.threshold = get_dynamic_threshold(self.session, self.in_kz, score=r.score)
        body = float(self.last["open"]) - float(self.last["close"])
        if (float(self.last["close"]) < float(self.prev["low"]) and body / self.atr > MOMENTUM_BODY_ATR and r.score >= r.threshold):
            r.use_market = True; r.entry = 0.0; r.reasons.append("🚀 MKT")
        return True

def analyze_setup(df_m5: pd.DataFrame, df_h4: Optional[pd.DataFrame], df_d1: Optional[pd.DataFrame],
                  df_m15: Optional[pd.DataFrame], df_h1: Optional[pd.DataFrame], session: str,
                  bar_time: datetime, in_kz: bool, spread_pts: float, sl_atr_mult: float,
                  df_m1: Optional[pd.DataFrame] = None) -> SetupResult:
    """
    Wrapper function to maintain compatibility with smc_bot_v23_live.py
    and smc_bot_v23_backtest.py. Delegates to SetupAnalyzer.
    """
    analyzer = SetupAnalyzer(df_m5, df_h4, df_d1, df_m15, df_h1, session, bar_time, in_kz, spread_pts, sl_atr_mult, df_m1)
    return analyzer.execute()
