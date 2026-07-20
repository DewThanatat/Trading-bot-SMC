# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  🧬  SMC CORE V.22  —  Shared Analysis Engine                               ║
║                                                                              ║
║  IMPORTED BY BOTH smc_bot_v22_live.py AND smc_bot_v22_backtest.py           ║
║  The single source of truth for all indicators & setup logic.                ║
║                                                                              ║
║  V.22 FIXES vs V.21:                                                         ║
║  [C1]  Market-Order Entry Bug   — entry=close, SL anchored to structure      ║
║  [C2]  Duplicate Trade Bug      — backtest breaks after first trade per bar  ║
║  [C3]  sl_atr_mult arg bug      — correctly threaded from symbol profile     ║
║  [C4]  ATR Window Bug           — _manage_trade fetches n=20 bars for ATR   ║
║  [C5]  Tick-Value Math          — exact per-asset PnL in backtest            ║
║  [C6]  H4 NEUTRAL penalty       — -8 added to force directional bias        ║
║  [C7]  Score inversion fix      — redundant bonus signals removed           ║
║  [C8]  Session filter hardened  — LONDON & NY_OPEN_EARLY thresholds raised  ║
║  [C9]  Hit & Run fully wired    — partial TP/BE/trail in backtest engine     ║
║  [C10] Min-RR gate pre-entry    — blocks trade if TP target < 2.0R away     ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import hashlib
import math
import time
import warnings
from dataclasses import dataclass, field
from datetime import datetime, time as dtime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import pytz

warnings.filterwarnings("ignore", category=RuntimeWarning)

try:
    from scipy.ndimage import maximum_filter1d as _max_filter1d
    from scipy.ndimage import minimum_filter1d as _min_filter1d
    _SCIPY_AVAILABLE = True
except ImportError:
    _SCIPY_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
#  ⚙️  STRATEGY CONFIG  (edit this block only)
# ─────────────────────────────────────────────────────────────────────────────
STRATEGY_TZ = pytz.timezone("Asia/Bangkok")

# 5-asset universe  — per-symbol tick-value & point are used for exact PnL
ACTIVE_SYMBOLS: Dict[str, Dict] = {
    "XAUUSDm": {
        "spread_block_pts": 80.0,  "sl_atr_mult": 2.5,  "min_lot": 0.01,
        "sim_spread": 25.0,
        # PnL math: 1 lot × 1 point = tick_val / (tick_size / point)
        # XAU: contract=100oz, tick=0.01, tick_val=1.0 → $1/pt/lot
        "tick_val": 1.0,  "pt_size": 0.01,
    },
    "EURUSDm": {
        "spread_block_pts": 20.0,  "sl_atr_mult": 1.8,  "min_lot": 0.01,
        "sim_spread": 10.0,
        # EUR: 100k contract, tick=0.00001, tick_val=1.0 → $1/pt/lot
        "tick_val": 1.0,  "pt_size": 0.00001,
    },
    "USDJPYm": {
        "spread_block_pts": 35.0,  "sl_atr_mult": 2.0,  "min_lot": 0.01,
        "sim_spread": 18.0,
        # JPY: 100k contract, tick=0.001, ~0.0067/pt → verify with broker
        "tick_val": 0.67,  "pt_size": 0.001,
    },
    "USTECm": {
        "spread_block_pts": 200.0,  "sl_atr_mult": 4.5,  "min_lot": 0.1,
        "sim_spread": 150.0,
        # NAS100 mini: 1 pt = $1 on most brokers — VERIFY with:
        # print(mt5.symbol_info("USTECm").trade_tick_value, .point)
        "tick_val": 1.0,  "pt_size": 1.0,
    },
    "BTCUSDm": {
        "spread_block_pts": 2000.0,  "sl_atr_mult": 3.0,  "min_lot": 0.01,
        "sim_spread": 1000.0,
        # BTC micro: 1 lot = 1 BTC, tick=0.01, tick_val=0.01 → $0.01/pt/lot
        "tick_val": 0.01,  "pt_size": 0.01,
    },
}

# ── Trade Management ──────────────────────────────────────────────────────────
RR_RATIO           = 3.0
PARTIAL_TP_RR      = 1.0      # Close 60% here, set BE
PARTIAL_TP_PCT     = 0.60     # [C9] 60% partial (was 50%)
BREAKEVEN_DELAY_RR = 1.0      # Move SL to entry+buf at 1R
TRAIL_AFTER_RR     = 1.5      # Begin trailing at 1.5R
TRAIL_ATR_MULT     = 1.0
TRAIL_MIN_MOVE_ATR = 0.3
MIN_RR_TO_TARGET   = 2.0      # [C10] Hard gate: liquidity target must be ≥2R away

# ── Scoring (V.22 re-calibrated) ─────────────────────────────────────────────
SCORE_BASE          = 40
SCORE_FVG_FRESH     = 20
SCORE_LIQ_SWEPT     = 15
SCORE_SWEEP_AND_FVG = 5
SCORE_HTF_ALIGN     = 10
SCORE_HTF_AGAINST   = -15
SCORE_HTF_NEUTRAL   = -8      # [C6] New: penalise trading without directional conviction
SCORE_M15_BOS       = 8
SCORE_OB_BONUS      = 5
SCORE_LIQ_TARGET    = 4
SCORE_FVG_STRENGTH  = 4
SCORE_M1_CONFIRM    = 4
SCORE_ADR_WARN      = -10
SCORE_SPREAD_WARN   = -5
# [C7] Removed: SCORE_STRONG_CANDLE, SCORE_BOS_M5, SCORE_OB_OVERLAP
#      These were additive noise causing score inflation on weak setups
H1_AGREE_BONUS    = 6
H1_CONFLICT_PENALTY = -4

SCORE_MSS_CISD = 10
SCORE_MSS_ONLY = 4

SCORE_VSHAPE_BONUS   = 4
SCORE_USHAPE_PENALTY = -12
SCORE_GOLDEN_CONFLUENCE = 12

JUDAS_SCORE_BONUS = 20  # [C7] Raised from 12 to reflect actual edge

# ── Session Thresholds (V.22) ─────────────────────────────────────────────────
# [C8] LONDON and NY_OPEN_EARLY thresholds hardened
SCORE_THRESHOLD_IN_SESSION  = 68
SCORE_THRESHOLD_OUT_SESSION = 82
SCORE_THRESHOLD: Dict[str, int] = {
    "PRE_LONDON":    75,    # Pre-session: require sweep evidence
    "LONDON":        82,    # [C8] London bleeds — raise bar significantly
    "NY_OPEN_EARLY": 85,    # [C8] Worst stats session — near-block
    "NEW_YORK":      68,    # Best performing session — keep accessible
    "DEFAULT":       68,
}

# ── Risk Tiers (Kamikaze Kelly) ───────────────────────────────────────────────
RISK_TIERS = [
    (86, 30.00),   # GOD STRIKE
    (80, 15.00),   # SNIPER
    (74,  5.00),   # PREDATOR
    (68,  1.00),   # SCOUT
    ( 0,  0.05),
]
MAX_LOSS_PER_TRADE_USD = 3.00   # [C5] Hard USD cap — micro-account armour

# ── FVG ───────────────────────────────────────────────────────────────────────
MOMENTUM_BODY_ATR  = 1.2
FVG_ENTRY_MID      = True
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
ADR_NY_EXHAUSTED_PCT = 0.93
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
    (14, 0, 16, 30, "London Open"),
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
GLOBAL_MAX_CONCURRENT_TRADES = 2
MAX_TRADES_PER_SYMBOL        = 1
MAX_GLOBAL_EXPOSURE_PCT      = 40.0


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
                f"Score:{self.score}/{self.threshold} | {' | '.join(self.reasons)}")


# ─────────────────────────────────────────────────────────────────────────────
#  VECTORISED PRIMITIVES
# ─────────────────────────────────────────────────────────────────────────────
def _to_numpy(df: pd.DataFrame, col: str) -> np.ndarray:
    return np.ascontiguousarray(df[col].values, dtype=np.float64)

def _sliding_max(arr: np.ndarray, window: int) -> np.ndarray:
    if _SCIPY_AVAILABLE:
        return _max_filter1d(arr, size=window, mode="nearest")
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

def get_confirmed_swings_np(df: pd.DataFrame, period: int = 5, confirm: int = 2) -> Tuple[float, float]:
    if len(df) < period * 2 + confirm + 1:
        return float(df["high"].max()), float(df["low"].min())
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

def get_dynamic_threshold(session: str, in_session: bool) -> int:
    if not in_session: return SCORE_THRESHOLD_OUT_SESSION
    return SCORE_THRESHOLD.get(session, SCORE_THRESHOLD_IN_SESSION)


# ─────────────────────────────────────────────────────────────────────────────
#  MASTER SETUP ANALYSER  V.22
#  Single function — imported identically by both live bot and backtest engine
# ─────────────────────────────────────────────────────────────────────────────
def analyze_setup(
    df_m5:   pd.DataFrame,
    df_h4:   Optional[pd.DataFrame],
    df_d1:   Optional[pd.DataFrame],
    df_m15:  Optional[pd.DataFrame],
    df_h1:   Optional[pd.DataFrame],
    session:  str,
    bar_time: datetime,
    in_kz:    bool,
    spread_pts: float,
    sl_atr_mult: float,   # [C3] Correctly threaded from ACTIVE_SYMBOLS profile
) -> SetupResult:
    r = SetupResult()
    if df_m5 is None or len(df_m5) < 30:
        r.reasons.append("M5 insufficient"); return r
    atr = calculate_atr(df_m5)
    if atr == 0: r.reasons.append("ATR=0"); return r
    r.atr = atr

    adr = calculate_adr(df_d1)
    if adr > 0 and df_d1 is not None and len(df_d1) >= 1:
        r.adr_pct = float(df_d1["high"].iloc[-1] - df_d1["low"].iloc[-1]) / adr

    adr_ceil = ADR_NY_EXHAUSTED_PCT if session in ("NEW_YORK", "NY_OPEN_EARLY") else ADR_EXHAUSTED_PCT
    if ADR_HARD_BLOCK and r.adr_pct >= adr_ceil:
        r.reasons.append(f"ADR_HARD_BLOCK({r.adr_pct*100:.0f}%)"); return r

    htf_res      = get_htf_bias(df_h4)
    r.htf_bias   = htf_res.bias; r.htf_result = htf_res
    r.h1_bias    = get_h1_bias(df_h1)
    r.m15_struct = get_m15_structure(df_m15)
    r.in_session = in_kz
    r.threshold  = get_dynamic_threshold(session, in_kz)

    liq       = build_liquidity_map_np(df_m5, atr, LIQ_SWING_PERIOD); r.liq_map = liq
    last_sh, last_sl = get_confirmed_swings_np(df_m5, SWING_PERIOD, SWING_CONFIRM_BARS)
    fvg_lookback = FVG_MEMORY_BARS.get(session, FVG_MEMORY_BARS["DEFAULT"])
    fvg_zones    = scan_fvg_memory(df_m5, atr, fvg_lookback)

    last = df_m5.iloc[-1]; prev = df_m5.iloc[-2]
    r.candle_ts = float(last["time"].timestamp()) if hasattr(last["time"], "timestamp") else time.time()
    price = float(last["close"])

    SWEEP_WICK_ATR_MULT  = 0.15
    SWEEP_CLOSE_ATR_MULT = 0.10

    _ssl_wick      = last_sl - float(last["low"])
    _ssl_close_gap = float(last["close"]) - last_sl
    sweep_sell = (float(last["low"]) < last_sl
                  and _ssl_wick      >= atr * SWEEP_WICK_ATR_MULT
                  and _ssl_close_gap >= atr * SWEEP_CLOSE_ATR_MULT)

    _bsl_wick      = float(last["high"]) - last_sh
    _bsl_close_gap = last_sh - float(last["close"])
    sweep_buy = (float(last["high"]) > last_sh
                 and _bsl_wick      >= atr * SWEEP_WICK_ATR_MULT
                 and _bsl_close_gap >= atr * SWEEP_CLOSE_ATR_MULT)

    if liq.gap_swept_low  is not None: sweep_sell = True
    if liq.gap_swept_high is not None: sweep_buy  = True

    def _htf_scores(sig: str) -> None:
        if r.htf_bias == "BULLISH" and sig == "BUY":
            r.score += SCORE_HTF_ALIGN
            r.reasons.append(f"H4 Bull{'(CHOCH)' if htf_res.choch_signal=='UP' else ''} +{SCORE_HTF_ALIGN}")
        elif r.htf_bias == "BEARISH" and sig == "SELL":
            r.score += SCORE_HTF_ALIGN
            r.reasons.append(f"H4 Bear{'(CHOCH)' if htf_res.choch_signal=='DOWN' else ''} +{SCORE_HTF_ALIGN}")
        elif ((r.htf_bias == "BULLISH" and sig == "SELL") or
              (r.htf_bias == "BEARISH" and sig == "BUY")):
            r.score += SCORE_HTF_AGAINST
            r.reasons.append(f"H4 Against {SCORE_HTF_AGAINST}")
        else:
            # [C6] NEUTRAL H4 now penalised — forces directional conviction
            r.score += SCORE_HTF_NEUTRAL
            r.reasons.append(f"H4 Neutral {SCORE_HTF_NEUTRAL}")

    def _h1_scores(sig: str) -> None:
        if ((r.h1_bias == "BULLISH" and sig == "BUY") or
                (r.h1_bias == "BEARISH" and sig == "SELL")):
            r.score += H1_AGREE_BONUS; r.reasons.append(f"H1 Agree +{H1_AGREE_BONUS}")
        elif ((r.h1_bias == "BULLISH" and sig == "SELL") or
              (r.h1_bias == "BEARISH" and sig == "BUY")):
            r.score += H1_CONFLICT_PENALTY; r.reasons.append(f"H1 Conflict {H1_CONFLICT_PENALTY}")

    def _apply_structure_scores(sig: str, fvg_active: Optional[FVGZone]) -> None:
        if ((sig == "BUY" and r.m15_struct == "BULLISH_BOS") or
                (sig == "SELL" and r.m15_struct == "BEARISH_BOS")):
            r.score += SCORE_M15_BOS; r.reasons.append(f"M15 BOS +{SCORE_M15_BOS}")
        mss = check_mss_cisd(df_m5, atr, sig); r.mss = mss
        if mss.confirmed:
            pts = SCORE_MSS_CISD if mss.cisd else SCORE_MSS_ONLY
            tag = "MSS+CISD" if mss.cisd else "MSS"
            r.score += pts; r.reasons.append(f"{tag} +{pts}")
        # [C7] Removed BOS_M5 — it was double-counting structure already in M15 BOS
        shape = VShapeDetector.classify(df_m5, atr, sig); r.shape = shape
        if shape == "V": r.score += SCORE_VSHAPE_BONUS; r.reasons.append(f"V-Shape +{SCORE_VSHAPE_BONUS}")
        elif shape == "U": r.score += SCORE_USHAPE_PENALTY; r.reasons.append(f"U-Shape {SCORE_USHAPE_PENALTY}")
        if check_golden_confluence(fvg_active, df_m5, htf_res, atr, sig):
            r.golden_conf = True
            r.score += SCORE_GOLDEN_CONFLUENCE; r.reasons.append(f"✨Golden +{SCORE_GOLDEN_CONFLUENCE}")
        # [C7] Removed SCORE_STRONG_CANDLE — noisy, double-counts momentum FVG already requires
        ob = find_order_block(df_m5, sig, atr)
        if ob.found and not ob.mitigated:
            r.score += SCORE_OB_BONUS; r.reasons.append(f"OB(q:{ob.score:.2f},age:{ob.bar_age}) +{SCORE_OB_BONUS}")
        # [C7] Removed OB_OVERLAP bonus — FVG midpoint inside OB is implied by zone confluence

    def _apply_penalties(sig: str, fvg_active: Optional[FVGZone]) -> None:
        if r.adr_pct >= adr_ceil:
            r.score += SCORE_ADR_WARN; r.reasons.append(f"ADR{r.adr_pct*100:.0f}% {SCORE_ADR_WARN}")
        if not r.in_session:
            r.reasons.append(f"🌙 OOS (thr={r.threshold})")
        else:
            r.reasons.append(f"🎯 InKZ (thr={r.threshold})")
        if session == "PRE_LONDON" and PRE_LONDON_SWEEP_REQUIRED:
            has_sweep = ((sig == "BUY" and (sweep_sell or liq.gap_swept_low is not None)) or
                         (sig == "SELL" and (sweep_buy or liq.gap_swept_high is not None)))
            if not has_sweep and fvg_active is not None:
                r.score -= 15; r.reasons.append("PRE_LDN pure-FVG -15")
        if is_judas_swing(liq, fvg_zones, sig, session, bar_time):
            r.is_judas = True; r.score += JUDAS_SCORE_BONUS
            r.reasons.append(f"⚡Judas +{JUDAS_SCORE_BONUS}")

    def _liq_target_gate(sig: str, entry: float, sl: float) -> bool:
        """[C10] Pre-entry gate: liquidity target must be ≥ MIN_RR_TO_TARGET away."""
        risk = abs(entry - sl)
        if risk == 0: return False
        if sig == "BUY" and liq.bsl_nearest is not None:
            rr_to_target = (liq.bsl_nearest - entry) / risk
            if rr_to_target >= MIN_RR_TO_TARGET:
                r.score += SCORE_LIQ_TARGET
                r.reasons.append(f"BSL→{liq.bsl_nearest:.2f} +{SCORE_LIQ_TARGET}")
            return rr_to_target >= MIN_RR_TO_TARGET or liq.bsl_nearest is None
        if sig == "SELL" and liq.ssl_nearest is not None:
            rr_to_target = (entry - liq.ssl_nearest) / risk
            if rr_to_target >= MIN_RR_TO_TARGET:
                r.score += SCORE_LIQ_TARGET
                r.reasons.append(f"SSL→{liq.ssl_nearest:.2f} +{SCORE_LIQ_TARGET}")
            return rr_to_target >= MIN_RR_TO_TARGET or liq.ssl_nearest is None
        return True  # No nearest level detected — allow (target may be off-chart)

    def _build_buy() -> bool:
        has_sweep  = sweep_sell
        fvg_active = get_active_fvg(fvg_zones, price, "BUY")
        if not has_sweep and fvg_active is None: return False
        r.signal = "BUY"; r.score = SCORE_BASE
        if fvg_active is not None:
            r.entry = (fvg_active.bot + (fvg_active.top - fvg_active.bot) * 0.5
                       if FVG_ENTRY_MID else fvg_active.top)
            r.fvg_zone = fvg_active
        elif has_sweep:
            r.entry = last_sl + atr * 0.1
        r.sl = last_sl - atr * sl_atr_mult  # [C3] uses per-symbol mult
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
        _htf_scores("BUY"); _h1_scores("BUY"); _apply_structure_scores("BUY", fvg_active)
        if htf_res.swept_low is not None:
            r.score += 4; r.reasons.append("H4 SSL Swept +4")
        _liq_target_gate("BUY", r.entry, r.sl)  # [C10] scores or logs
        _apply_penalties("BUY", fvg_active)
        r.sweep_type = classify_sweep("BUY", r.htf_bias)
        body = float(last["close"]) - float(last["open"])
        if (float(last["close"]) > float(prev["high"])
                and body / atr > MOMENTUM_BODY_ATR and r.score >= r.threshold):
            r.use_market = True; r.entry = 0.0; r.reasons.append("🚀 MKT")
        return True

    def _build_sell() -> bool:
        has_sweep  = sweep_buy
        fvg_active = get_active_fvg(fvg_zones, price, "SELL")
        if not has_sweep and fvg_active is None: return False
        r.signal = "SELL"; r.score = SCORE_BASE
        if fvg_active is not None:
            r.entry = (fvg_active.bot + (fvg_active.top - fvg_active.bot) * 0.5
                       if FVG_ENTRY_MID else fvg_active.bot)
            r.fvg_zone = fvg_active
        elif has_sweep:
            r.entry = last_sh - atr * 0.1
        r.sl = last_sh + atr * sl_atr_mult  # [C3]
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
        _htf_scores("SELL"); _h1_scores("SELL"); _apply_structure_scores("SELL", fvg_active)
        if htf_res.swept_high is not None:
            r.score += 4; r.reasons.append("H4 BSL Swept +4")
        _liq_target_gate("SELL", r.entry, r.sl)
        _apply_penalties("SELL", fvg_active)
        r.sweep_type = classify_sweep("SELL", r.htf_bias)
        body = float(last["open"]) - float(last["close"])
        if (float(last["close"]) < float(prev["low"])
                and body / atr > MOMENTUM_BODY_ATR and r.score >= r.threshold):
            r.use_market = True; r.entry = 0.0; r.reasons.append("🚀 MKT")
        return True

    if not _build_buy():
        r.signal = "WAIT"; r.score = 0; r.reasons = []
        if not _build_sell(): return r

    if r.signal != "WAIT":
        entry_h = r.entry if not r.use_market else -1.0
        r.setup_hash = hashlib.sha256(
            f"{r.signal}:{entry_h:.2f}:{r.sl:.2f}:{int(r.candle_ts)}".encode()
        ).hexdigest()[:12]
    return r
