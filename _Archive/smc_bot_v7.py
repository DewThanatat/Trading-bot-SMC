"""
╔══════════════════════════════════════════════════════════════════════════╗
║   🚀 AI SMC/ICT Pro Sniper — V.7 BALANCED                               ║
║                                                                          ║
║   ระบบเงื่อนไขใหม่ (Gate System):                                        ║
║   GATE 1 — Hard Block  : Session / News / Spread / DD / Connection      ║
║   GATE 2 — Signal Core : Sweep OR FVG zone (OR logic ไม่บังคับพร้อมกัน) ║
║   GATE 3 — Dynamic Score ≥ threshold ตาม session volatility             ║
║                                                                          ║
║   ออกไม้ได้ไม่จำกัดครั้งต่อวัน ถ้าผ่านเงื่อนไขและ score พอ            ║
║   FVG Memory 15 แท่ง — จำ zone ไว้ ไม่บังคับเกิดพร้อม Sweep            ║
║   M1 confirm เป็น bonus ไม่ใช่ block                                    ║
║   Score-based lot sizing (Exness unlimited leverage)                     ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import sqlite3
import json
import time
import hashlib
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, time as dtime
from typing import Optional, List
import pytz

# ══════════════════════════════════════════════════════════════════
# ⚙️  CONFIGURATION — แก้ค่าที่นี่
# ══════════════════════════════════════════════════════════════════
SYMBOL              = "XAUUSDm"
MAGIC_NUMBER        = 99999
RR_RATIO            = 2.5
MAX_DAILY_LOSS_PCT  = 4.0
MAX_TOTAL_DD_PCT    = 8.0
EXPIRATION_CANDLES  = 6
MAX_SPREAD_POINTS   = 40.0
HARD_SPREAD_BLOCK   = 60.0       # block เด็ดขาด ไม่ว่าสถานการณ์ไหน
MOMENTUM_BODY_ATR   = 1.4
BREAKEVEN_RR        = 1.0
TRAIL_AFTER_RR      = 2.0
TRAIL_ATR_MULT      = 1.2
TRAIL_MIN_MOVE_ATR  = 0.3
ADR_EXHAUSTED_PCT   = 0.85
SWING_PERIOD        = 5
SWING_CONFIRM_BARS  = 2
SETUP_COOLDOWN_SEC  = 180        # ลดจาก 300 → 180 ให้ re-entry เร็วขึ้น

# Partial TP
PARTIAL_TP_RR       = 1.0
PARTIAL_TP_PCT      = 0.50

# Intrabar
INTRABAR_ENABLED    = True
INTRABAR_POLL_SEC   = 0.5
INTRABAR_TIMEOUT_SEC= 180        # ลดจาก 290 → 180

# FVG Memory
FVG_MEMORY_BARS     = 15         # จำ FVG zone ย้อนหลังกี่แท่ง
FVG_MITIGATED_PCT   = 0.5        # ถ้าราคาเข้า zone เกิน 50% ถือว่า mitigated

# M1 — bonus only ไม่ block
MTF_M1_BODY_ATR     = 0.3        # ลด threshold เพื่อ confirm ง่ายขึ้น

# Liquidity
LIQ_SWING_PERIOD    = 10
LIQ_EQUAL_TOLERANCE = 0.0003
LIQ_MIN_CLUSTER     = 2

# Dynamic Score Threshold ตาม session
SCORE_THRESHOLD = {
    "LONDON":        50,   # volatile สูง → ผ่อนเกณฑ์
    "NEW_YORK":      50,
    "NY_OPEN_EARLY": 52,
    "PRE_LONDON":    56,   # volatile ต่ำ → เข้มขึ้น
    "DEFAULT":       54,
}
# ปรับ threshold เพิ่มเมื่อ HTF NEUTRAL หรือ ADR สูง
SCORE_PENALTY_HTF_NEUTRAL = 4
SCORE_PENALTY_HIGH_ADR    = 3

# Score-based Lot Sizing
LOT_MIN   = 0.01
LOT_TIERS = [
    (95, 0.08),
    (88, 0.06),
    (80, 0.05),
    (72, 0.04),
    (64, 0.03),
    (56, 0.02),
    (0,  0.01),
]

# ══════════════════════════════════════════════════════════════════
# SCORING WEIGHTS
# ══════════════════════════════════════════════════════════════════
SCORE_BASE           = 40   # ได้เมื่อผ่าน Gate 2
# Confluence bonus
SCORE_SWEEP_AND_FVG  = 15   # มีทั้ง Sweep + FVG (ไม่ต้องพร้อมกัน)
SCORE_HTF_ALIGN      = 15
SCORE_HTF_AGAINST    = -10
SCORE_M15_BOS        = 10
SCORE_STRONG_CANDLE  = 12
SCORE_OB_BONUS       = 12   # OB พบ — ไม่บังคับครอบ entry
SCORE_OB_OVERLAP     = 6    # OB ครอบ entry ด้วย → bonus เพิ่ม
SCORE_BOS_M5         = 8
SCORE_FVG_FRESH      = 10   # FVG ที่ยังไม่ถูก mitigate
SCORE_FVG_STRENGTH   = 5    # FVG strength > 0.5
SCORE_LIQ_SWEPT      = 10
SCORE_LIQ_TARGET     = 12
SCORE_M1_CONFIRM     = 5    # bonus ไม่ block
SCORE_ADR_WARN       = -10
SCORE_SPREAD_WARN    = -5   # spread > 25pts แต่ไม่ถึง hard block

# Sessions (Bangkok time)
SESSIONS = [
    (12,  0, 14,  0, "PRE_LONDON"),
    (14,  0, 18,  0, "LONDON"),
    (18, 30, 19, 15, "NY_OPEN_EARLY"),
    (19, 45, 23, 59, "NEW_YORK"),
]
NEWS_BLOCKS = [(19, 15, 19, 45)]

DB_PATH  = "smc_state.db"
LOG_PATH = "smc_bot.log"
bkk_tz   = pytz.timezone('Asia/Bangkok')

# ══════════════════════════════════════════════════════════════════
# 📋  LOGGING
# ══════════════════════════════════════════════════════════════════
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

# ══════════════════════════════════════════════════════════════════
# 💾  PERSISTENCE — Singleton DB
# ══════════════════════════════════════════════════════════════════
_db_conn: Optional[sqlite3.Connection] = None
_db_lock = threading.Lock()

def get_db() -> sqlite3.Connection:
    global _db_conn
    with _db_lock:
        if _db_conn is None:
            _db_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            _db_conn.row_factory = sqlite3.Row
            _db_conn.execute("PRAGMA journal_mode=WAL")
            _db_conn.execute("PRAGMA synchronous=NORMAL")
        return _db_conn

def close_db():
    global _db_conn
    with _db_lock:
        if _db_conn is not None:
            _db_conn.close()
            _db_conn = None

def init_db():
    c = get_db()
    with _db_lock:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS setup_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL, signal TEXT, score INTEGER,
            entry REAL, sl REAL, tp REAL,
            setup_hash TEXT, session TEXT
        );
        CREATE TABLE IF NOT EXISTS cooldown (
            setup_hash TEXT PRIMARY KEY, expires_at REAL
        );
        CREATE TABLE IF NOT EXISTS trail_state (
            ticket INTEGER PRIMARY KEY,
            last_sl REAL, updated_at REAL,
            partial_done INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS bot_state (
            key TEXT PRIMARY KEY, value TEXT
        );
        """)
        c.commit()

def _db_exec(sql: str, params: tuple = ()):
    with _db_lock:
        get_db().execute(sql, params)
        get_db().commit()

def _db_query(sql: str, params: tuple = ()):
    with _db_lock:
        return get_db().execute(sql, params).fetchone()

def is_on_cooldown(h: str) -> bool:
    row = _db_query("SELECT expires_at FROM cooldown WHERE setup_hash=?", (h,))
    return bool(row and row["expires_at"] > time.time())

def set_cooldown(h: str):
    _db_exec("INSERT OR REPLACE INTO cooldown VALUES(?,?)",
             (h, time.time() + SETUP_COOLDOWN_SEC))

def cleanup_cooldowns():
    _db_exec("DELETE FROM cooldown WHERE expires_at<=?", (time.time(),))

def db_log_setup(signal, score, entry, sl, tp, h, session=""):
    _db_exec(
        "INSERT INTO setup_log(ts,signal,score,entry,sl,tp,setup_hash,session)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (time.time(), signal, score, entry, sl, tp, h, session)
    )

def get_trail_state(ticket: int):
    return _db_query(
        "SELECT last_sl, partial_done FROM trail_state WHERE ticket=?", (ticket,))

def save_trail_sl(ticket: int, sl: float, partial_done: int = None):
    existing = get_trail_state(ticket)
    if partial_done is None:
        partial_done = existing["partial_done"] if existing else 0
    _db_exec("INSERT OR REPLACE INTO trail_state VALUES(?,?,?,?)",
             (ticket, sl, time.time(), partial_done))

def set_partial_done(ticket: int):
    existing = get_trail_state(ticket)
    last_sl = existing["last_sl"] if existing else 0.0
    _db_exec("INSERT OR REPLACE INTO trail_state VALUES(?,?,?,?)",
             (ticket, last_sl, time.time(), 1))

def cleanup_trail_state(open_tickets: set):
    if not open_tickets:
        _db_exec("DELETE FROM trail_state"); return
    ph = ",".join("?" * len(open_tickets))
    _db_exec(f"DELETE FROM trail_state WHERE ticket NOT IN ({ph})",
             tuple(open_tickets))

def get_state(key: str, default=None):
    row = _db_query("SELECT value FROM bot_state WHERE key=?", (key,))
    return json.loads(row["value"]) if row else default

def set_state(key: str, value):
    _db_exec("INSERT OR REPLACE INTO bot_state VALUES(?,?)",
             (key, json.dumps(value)))

# ══════════════════════════════════════════════════════════════════
# 📐  INDICATORS
# ══════════════════════════════════════════════════════════════════
def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < period + 1:
        return 0.0
    prev = df['close'].shift(1)
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - prev).abs(),
        (df['low']  - prev).abs(),
    ], axis=1).max(axis=1)
    val = tr.rolling(period).mean().iloc[-1]
    return float(val) if not np.isnan(val) else 0.0

def calculate_adr(df_d1: pd.DataFrame, period: int = 10) -> float:
    if df_d1 is None or len(df_d1) < period:
        return 0.0
    dr  = df_d1['high'] - df_d1['low']
    val = dr.rolling(period).mean().iloc[-1]
    return float(val) if not np.isnan(val) else 0.0

def get_confirmed_swings(df: pd.DataFrame, period: int = 5, confirm: int = 2):
    if len(df) < period * 2 + confirm + 1:
        return float(df['high'].max()), float(df['low'].min())
    safe = df.iloc[:-(confirm)]
    swing_h, swing_l = [], []
    for i in range(period, len(safe) - period):
        wh = safe['high'].iloc[i - period: i + period + 1]
        wl = safe['low'].iloc[i - period: i + period + 1]
        if safe['high'].iloc[i] == wh.max():
            swing_h.append(float(safe['high'].iloc[i]))
        if safe['low'].iloc[i] == wl.min():
            swing_l.append(float(safe['low'].iloc[i]))
    last_sh = swing_h[-1] if swing_h else float(df['high'].max())
    last_sl = swing_l[-1] if swing_l else float(df['low'].min())
    return last_sh, last_sl

# ══════════════════════════════════════════════════════════════════
# 🧠  FVG MEMORY — จำ zone ย้อนหลัง 15 แท่ง (หัวใจหลัก V.7)
# ══════════════════════════════════════════════════════════════════
@dataclass
class FVGZone:
    kind:       str    # "BULLISH" | "BEARISH"
    top:        float
    bot:        float
    strength:   float
    bar_index:  int    # แท่งที่เกิด (index ใน df)
    mitigated:  bool   = False

def scan_fvg_memory(df: pd.DataFrame, atr: float,
                    lookback: int = 15) -> List[FVGZone]:
    """
    สแกน FVG ย้อนหลัง `lookback` แท่ง
    คืน list ของ zone ที่ยังไม่ mitigated เรียงจากใหม่ไปเก่า
    """
    zones: List[FVGZone] = []
    if len(df) < lookback + 3 or atr == 0:
        return zones

    min_gap = atr * 0.15
    overlap = atr * 0.25
    start   = max(3, len(df) - lookback)

    for i in range(start, len(df)):
        c1 = df.iloc[i - 2]
        c2 = df.iloc[i - 1]
        c3 = df.iloc[i]

        c2_range = c2['high'] - c2['low']
        c2_body  = abs(c2['close'] - c2['open'])
        if c2_range > 0 and (c2_body / c2_range) < 0.4:
            continue

        # Bullish FVG
        if c3['low'] > c1['high'] - overlap:
            top = max(c3['low'], c1['high'])
            bot = min(c3['low'], c1['high'])
            gap = top - bot
            if gap >= min_gap:
                z = FVGZone("BULLISH", top, bot, gap / atr, i)
                # ตรวจ mitigation: candle หลังจากนี้ดันราคาเข้า zone ≥ 50%
                mid = bot + gap * FVG_MITIGATED_PCT
                for j in range(i + 1, len(df)):
                    if df.iloc[j]['low'] <= mid:
                        z.mitigated = True; break
                zones.append(z)

        # Bearish FVG
        if c3['high'] < c1['low'] + overlap:
            top = max(c1['low'], c3['high'])
            bot = min(c1['low'], c3['high'])
            gap = top - bot
            if gap >= min_gap:
                z = FVGZone("BEARISH", top, bot, gap / atr, i)
                mid = top - gap * FVG_MITIGATED_PCT
                for j in range(i + 1, len(df)):
                    if df.iloc[j]['high'] >= mid:
                        z.mitigated = True; break
                zones.append(z)

    # เรียงใหม่ไปเก่า
    zones.sort(key=lambda z: z.bar_index, reverse=True)
    return zones

def get_active_fvg(zones: List[FVGZone], price: float,
                   direction: str) -> Optional[FVGZone]:
    """
    หา FVG zone ที่ active (ไม่ mitigated) และ
    ราคาปัจจุบันอยู่ใน zone หรือใกล้จะเข้า zone
    direction: "BUY" → ต้องการ BULLISH zone
               "SELL" → ต้องการ BEARISH zone
    """
    target_kind = "BULLISH" if direction == "BUY" else "BEARISH"
    for z in zones:
        if z.mitigated:
            continue
        if z.kind != target_kind:
            continue
        # ราคาอยู่ใน zone หรืออยู่เหนือ/ใต้ zone เล็กน้อย (slippage buffer)
        buffer = (z.top - z.bot) * 0.3
        if direction == "BUY"  and z.bot - buffer <= price <= z.top + buffer:
            return z
        if direction == "SELL" and z.bot - buffer <= price <= z.top + buffer:
            return z
    return None

# ══════════════════════════════════════════════════════════════════
# 💧  LIQUIDITY MAPPING
# ══════════════════════════════════════════════════════════════════
@dataclass
class LiquidityMap:
    buy_side:    list = field(default_factory=list)
    sell_side:   list = field(default_factory=list)
    swept_high:  Optional[float] = None
    swept_low:   Optional[float] = None
    bsl_nearest: Optional[float] = None
    ssl_nearest: Optional[float] = None

def build_liquidity_map(df: pd.DataFrame, atr: float,
                        period: int = 10) -> LiquidityMap:
    liq = LiquidityMap()
    if len(df) < period * 2 + 4 or atr == 0:
        return liq

    safe = df.iloc[:-2]
    tol  = max(atr * 0.08, abs(df['close'].iloc[-1]) * LIQ_EQUAL_TOLERANCE)

    ph_list, pl_list = [], []
    for i in range(period, len(safe) - period):
        w_h = safe['high'].iloc[i - period: i + period + 1]
        w_l = safe['low'].iloc[i - period: i + period + 1]
        if safe['high'].iloc[i] == w_h.max():
            ph_list.append(float(safe['high'].iloc[i]))
        if safe['low'].iloc[i] == w_l.min():
            pl_list.append(float(safe['low'].iloc[i]))

    def cluster(prices, tol):
        clusters = []
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

    liq.buy_side  = sorted(cluster(ph_list, tol), reverse=True)
    liq.sell_side = sorted(cluster(pl_list, tol))

    last = df.iloc[-1]
    for lvl in liq.buy_side:
        if last['high'] > lvl and last['close'] < lvl:
            liq.swept_high = lvl; break
    for lvl in liq.sell_side:
        if last['low'] < lvl and last['close'] > lvl:
            liq.swept_low = lvl; break

    price = float(last['close'])
    above = [l for l in liq.buy_side  if l > price]
    below = [l for l in liq.sell_side if l < price]
    liq.bsl_nearest = min(above) if above else None
    liq.ssl_nearest = max(below) if below else None
    return liq

# ══════════════════════════════════════════════════════════════════
# 📐  ORDER BLOCK
# ══════════════════════════════════════════════════════════════════
@dataclass
class OBResult:
    found: bool  = False
    high:  float = 0.0
    low:   float = 0.0
    score: float = 0.0

def find_order_block(df: pd.DataFrame, direction: str, atr: float) -> OBResult:
    if len(df) < 10 or atr == 0:
        return OBResult()
    closed = df.iloc[:-1]
    for i in range(len(closed) - 3, 3, -1):
        ob  = closed.iloc[i]
        imp = closed.iloc[i + 1]
        if abs(imp['close'] - imp['open']) < atr * 1.2:
            continue
        if direction == "BUY":
            if ob['close'] >= ob['open']: continue
            if imp['close'] <= imp['open']: continue
            ph = closed['high'].iloc[max(0, i-10): i].max()
            if imp['close'] <= ph * 0.998: continue
            pl    = closed['low'].iloc[max(0, i-5): i].min()
            sweep = pl < ob['low']
            rng   = ob['high'] - ob['low']
            body  = (ob['open'] - ob['close']) / rng if rng > 0 else 0
            q = 0.5 + (0.3 if sweep else 0) + (0.2 if body > 0.6 else 0)
            return OBResult(True, float(ob['high']), float(ob['low']), q)
        elif direction == "SELL":
            if ob['close'] <= ob['open']: continue
            if imp['close'] >= imp['open']: continue
            pl = closed['low'].iloc[max(0, i-10): i].min()
            if imp['close'] >= pl * 1.002: continue
            ph    = closed['high'].iloc[max(0, i-5): i].max()
            sweep = ph > ob['high']
            rng   = ob['high'] - ob['low']
            body  = (ob['close'] - ob['open']) / rng if rng > 0 else 0
            q = 0.5 + (0.3 if sweep else 0) + (0.2 if body > 0.6 else 0)
            return OBResult(True, float(ob['high']), float(ob['low']), q)
    return OBResult()

# ══════════════════════════════════════════════════════════════════
# 📊  HTF + M15 STRUCTURE
# ══════════════════════════════════════════════════════════════════
def get_htf_bias(df_h1: pd.DataFrame) -> str:
    if df_h1 is None or len(df_h1) < 210:
        return "NEUTRAL"
    ema50  = df_h1['close'].ewm(span=50,  adjust=False).mean()
    ema200 = df_h1['close'].ewm(span=200, adjust=False).mean()
    p    = float(df_h1['close'].iloc[-1])
    e50  = float(ema50.iloc[-1])
    e200 = float(ema200.iloc[-1])
    bull = (1 if e50 > e200 else 0) + (1 if p > e50 else 0) + (1 if p > e200 else 0)
    bear = (1 if e50 < e200 else 0) + (1 if p < e50 else 0) + (1 if p < e200 else 0)
    if bull >= 3: return "BULLISH"
    if bear >= 3: return "BEARISH"
    return "NEUTRAL"

def get_m15_structure(df_m15: pd.DataFrame) -> str:
    if df_m15 is None or len(df_m15) < 20:
        return "NEUTRAL"
    sh, sl = get_confirmed_swings(df_m15, period=3, confirm=2)
    last = df_m15.iloc[-1]
    if last['close'] > sh: return "BULLISH_BOS"
    if last['close'] < sl: return "BEARISH_BOS"
    return "NEUTRAL"

# ══════════════════════════════════════════════════════════════════
# 🕒  SESSION + DYNAMIC THRESHOLD
# ══════════════════════════════════════════════════════════════════
def get_session() -> str:
    now = datetime.now(bkk_tz).time()
    for sh, sm, eh, em in NEWS_BLOCKS:
        if dtime(sh, sm) <= now <= dtime(eh, em):
            return "RED_NEWS_BLOCK"
    for sh, sm, eh, em, name in SESSIONS:
        s, e = dtime(sh, sm), dtime(eh, em)
        if e < s:
            if now >= s or now <= e: return name
        else:
            if s <= now <= e: return name
    return "OUT_OF_SESSION"

def get_dynamic_threshold(session: str, htf_bias: str, adr_pct: float) -> int:
    """
    ปรับ threshold ตาม market condition แบบ real-time
    Session volatile → ลด threshold (ออกไม้ง่ายขึ้น)
    HTF neutral หรือ ADR สูง → เพิ่ม threshold (ระมัดระวัง)
    """
    base = SCORE_THRESHOLD.get(session, SCORE_THRESHOLD["DEFAULT"])
    if htf_bias == "NEUTRAL":
        base += SCORE_PENALTY_HTF_NEUTRAL
    if adr_pct >= ADR_EXHAUSTED_PCT:
        base += SCORE_PENALTY_HIGH_ADR
    return base

# ══════════════════════════════════════════════════════════════════
# 📊  DATA FEED
# ══════════════════════════════════════════════════════════════════
_cache: dict = {}
CACHE_TTL = 15

def fetch(tf: int, n: int, use_cache: bool = True) -> Optional[pd.DataFrame]:
    now = time.time()
    if use_cache and tf in _cache and now - _cache[tf][0] < CACHE_TTL:
        return _cache[tf][1]
    rates = mt5.copy_rates_from_pos(SYMBOL, tf, 0, n)
    if rates is None or len(rates) == 0:
        log.warning(f"fetch: ไม่ได้ข้อมูล tf={tf}")
        return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    _cache[tf] = (now, df)
    return df

def fetch_all() -> dict:
    _cache.clear()
    m1  = fetch(mt5.TIMEFRAME_M1,   60, False)
    m5  = fetch(mt5.TIMEFRAME_M5,  220, False)
    m15 = fetch(mt5.TIMEFRAME_M15, 100, False)
    h1  = fetch(mt5.TIMEFRAME_H1,  220, False)
    d1  = fetch(mt5.TIMEFRAME_D1,   20, False)
    return {
        "m1":     m1.iloc[:-1].copy()  if m1  is not None else None,
        "m5":     m5.iloc[:-1].copy()  if m5  is not None else None,
        "m15":    m15.iloc[:-1].copy() if m15 is not None else None,
        "h1":     h1.iloc[:-1].copy()  if h1  is not None else None,
        "d1":     d1                   if d1  is not None else None,
        "m5_raw": m5,
    }

# ══════════════════════════════════════════════════════════════════
# 🎯  SIGNAL ENGINE V.7 — Gate System
# ══════════════════════════════════════════════════════════════════
@dataclass
class SetupResult:
    signal:     str   = "WAIT"
    score:      int   = 0
    entry:      float = 0.0
    sl:         float = 0.0
    atr:        float = 0.0
    htf_bias:   str   = "NEUTRAL"
    m15_struct: str   = "NEUTRAL"
    adr_pct:    float = 0.0
    threshold:  int   = 54
    reasons:    list  = field(default_factory=list)
    setup_hash: str   = ""
    use_market: bool  = False
    liq_map:    Optional[LiquidityMap] = None
    fvg_zone:   Optional[FVGZone]      = None
    candle_ts:  float = 0.0

    def summary(self) -> str:
        mode = "MKT" if self.use_market else "LMT"
        gap  = self.score - self.threshold
        conf = "🔥🔥🔥" if gap >= 20 else "🔥🔥" if gap >= 10 else "🔥"
        return (f"{conf} {self.signal}({mode}) "
                f"Score:{self.score}/{self.threshold} "
                f"| {' | '.join(self.reasons)}")

def _make_hash(sig: str, entry: float, sl: float, ts: float) -> str:
    raw = f"{sig}:{entry:.2f}:{sl:.2f}:{int(ts)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]

def analyze_setup(df_m5, df_h1, df_d1, df_m15=None,
                  session: str = "DEFAULT") -> SetupResult:
    r = SetupResult()

    # ── ข้อมูลพื้นฐาน ────────────────────────────────────────────
    if df_m5 is None or len(df_m5) < 30:
        r.reasons.append("ข้อมูล M5 ไม่พอ"); return r

    atr = calculate_atr(df_m5)
    if atr == 0:
        r.reasons.append("ATR=0"); return r
    r.atr = atr

    adr = calculate_adr(df_d1)
    if adr > 0 and df_d1 is not None and len(df_d1) >= 1:
        r.adr_pct = (df_d1['high'].iloc[-1] - df_d1['low'].iloc[-1]) / adr

    r.htf_bias   = get_htf_bias(df_h1)
    r.m15_struct = get_m15_structure(df_m15)
    r.threshold  = get_dynamic_threshold(session, r.htf_bias, r.adr_pct)

    # Liquidity + Swing + FVG Memory
    liq       = build_liquidity_map(df_m5, atr, LIQ_SWING_PERIOD)
    r.liq_map = liq
    last_sh, last_sl = get_confirmed_swings(df_m5, SWING_PERIOD, SWING_CONFIRM_BARS)
    fvg_zones = scan_fvg_memory(df_m5, atr, FVG_MEMORY_BARS)

    last = df_m5.iloc[-1]
    prev = df_m5.iloc[-2]
    r.candle_ts = (float(last['time'].timestamp())
                   if hasattr(last['time'], 'timestamp') else time.time())

    price       = float(last['close'])
    sweep_sell  = last['low'] < last_sl  and last['close'] > last_sl
    sweep_buy   = last['high'] > last_sh and last['close'] < last_sh

    # ══════════════════════════════════════════════════════════════
    # GATE 2 — Signal Core (OR logic)
    # ต้องการ: Sweep OR ราคาอยู่ใน FVG zone
    # ถ้ามีทั้งคู่ → bonus
    # ══════════════════════════════════════════════════════════════
    def _build_buy():
        has_sweep  = sweep_sell
        fvg_active = get_active_fvg(fvg_zones, price, "BUY")

        # ต้องมีอย่างน้อย 1 อย่าง
        if not has_sweep and fvg_active is None:
            return False

        r.signal = "BUY"
        r.score  = SCORE_BASE

        # กำหนด entry / SL
        if fvg_active is not None:
            r.entry    = fvg_active.top
            r.fvg_zone = fvg_active
        elif has_sweep:
            # ไม่มี FVG → ใช้ swing low เป็น entry zone
            r.entry = last_sh  # entry บริเวณ swing break
        r.sl = last_sl - (atr * 0.5)

        # ── Reasons + Scoring ────────────────────────────────
        if has_sweep and fvg_active is not None:
            r.score += SCORE_SWEEP_AND_FVG
            r.reasons.append("Sweep+FVG ✓✓")
        elif has_sweep:
            r.reasons.append("Sweep SSL ✓")
        else:
            r.reasons.append("FVG Zone ✓")

        if fvg_active is not None and not fvg_active.mitigated:
            r.score += SCORE_FVG_FRESH
            r.reasons.append(f"FVG Fresh(s:{fvg_active.strength:.2f}) ✓")
            if fvg_active.strength > 0.5:
                r.score += SCORE_FVG_STRENGTH

        # HTF
        if r.htf_bias == "BULLISH":
            r.score += SCORE_HTF_ALIGN;   r.reasons.append("HTF Bull ✓")
        elif r.htf_bias == "BEARISH":
            r.score += SCORE_HTF_AGAINST; r.reasons.append("HTF Bear ⚠️")

        # M15
        if r.m15_struct == "BULLISH_BOS":
            r.score += SCORE_M15_BOS; r.reasons.append("M15 BOS ✓")

        # Strong candle
        body = last['close'] - last['open']
        if body > atr * 0.6:
            r.score += SCORE_STRONG_CANDLE; r.reasons.append("Strong ✓")

        # OB — bonus ไม่บังคับตำแหน่ง
        ob = find_order_block(df_m5, "BUY", atr)
        if ob.found:
            r.score += int(SCORE_OB_BONUS * ob.score)
            r.reasons.append(f"OB(q:{ob.score:.2f}) ✓")
            if ob.low <= r.entry <= ob.high:
                r.score += SCORE_OB_OVERLAP
                r.reasons.append("OB Overlap ✓")

        # BOS M5
        if last['close'] > prev['high']:
            r.score += SCORE_BOS_M5; r.reasons.append("BOS ✓")

        # Liquidity
        if liq.swept_low is not None:
            r.score += SCORE_LIQ_SWEPT
            r.reasons.append(f"SSL Swept({liq.swept_low:.2f}) ✓")
        if liq.bsl_nearest is not None:
            risk = abs(r.entry - r.sl)
            if risk > 0 and (liq.bsl_nearest - r.entry) >= risk * RR_RATIO * 0.8:
                r.score += SCORE_LIQ_TARGET
                r.reasons.append(f"BSL→{liq.bsl_nearest:.2f} ✓")

        # ADR
        if r.adr_pct >= ADR_EXHAUSTED_PCT:
            r.score += SCORE_ADR_WARN
            r.reasons.append(f"ADR{r.adr_pct*100:.0f}% ⚠️")

        # Market mode
        body_ratio = body / atr if atr > 0 else 0
        if (last['close'] > prev['high']
                and body_ratio > MOMENTUM_BODY_ATR
                and r.score >= r.threshold):
            r.use_market = True; r.entry = 0.0
            r.reasons.append("🚀 MKT")

        return True

    def _build_sell():
        has_sweep  = sweep_buy
        fvg_active = get_active_fvg(fvg_zones, price, "SELL")

        if not has_sweep and fvg_active is None:
            return False

        r.signal = "SELL"
        r.score  = SCORE_BASE

        if fvg_active is not None:
            r.entry    = fvg_active.bot
            r.fvg_zone = fvg_active
        elif has_sweep:
            r.entry = last_sl
        r.sl = last_sh + (atr * 0.5)

        if has_sweep and fvg_active is not None:
            r.score += SCORE_SWEEP_AND_FVG
            r.reasons.append("Sweep+FVG ✓✓")
        elif has_sweep:
            r.reasons.append("Sweep BSL ✓")
        else:
            r.reasons.append("FVG Zone ✓")

        if fvg_active is not None and not fvg_active.mitigated:
            r.score += SCORE_FVG_FRESH
            r.reasons.append(f"FVG Fresh(s:{fvg_active.strength:.2f}) ✓")
            if fvg_active.strength > 0.5:
                r.score += SCORE_FVG_STRENGTH

        if r.htf_bias == "BEARISH":
            r.score += SCORE_HTF_ALIGN;   r.reasons.append("HTF Bear ✓")
        elif r.htf_bias == "BULLISH":
            r.score += SCORE_HTF_AGAINST; r.reasons.append("HTF Bull ⚠️")

        if r.m15_struct == "BEARISH_BOS":
            r.score += SCORE_M15_BOS; r.reasons.append("M15 BOS ✓")

        body = last['open'] - last['close']
        if body > atr * 0.6:
            r.score += SCORE_STRONG_CANDLE; r.reasons.append("Strong ✓")

        ob = find_order_block(df_m5, "SELL", atr)
        if ob.found:
            r.score += int(SCORE_OB_BONUS * ob.score)
            r.reasons.append(f"OB(q:{ob.score:.2f}) ✓")
            if ob.low <= r.entry <= ob.high:
                r.score += SCORE_OB_OVERLAP
                r.reasons.append("OB Overlap ✓")

        if last['close'] < prev['low']:
            r.score += SCORE_BOS_M5; r.reasons.append("BOS ✓")

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
        if (last['close'] < prev['low']
                and body_ratio > MOMENTUM_BODY_ATR
                and r.score >= r.threshold):
            r.use_market = True; r.entry = 0.0
            r.reasons.append("🚀 MKT")

        return True

    # ลอง BUY ก่อน ถ้าไม่ได้ลอง SELL
    if not _build_buy():
        r.signal = "WAIT"; r.score = 0; r.reasons = []
        if not _build_sell():
            return r

    if r.signal != "WAIT":
        entry_h = r.entry if not r.use_market else -1.0
        r.setup_hash = _make_hash(r.signal, entry_h, r.sl, r.candle_ts)

    return r

# ══════════════════════════════════════════════════════════════════
# ⚡  INTRABAR TRIGGER
# ══════════════════════════════════════════════════════════════════
def wait_for_price_touch(setup: SetupResult) -> bool:
    if setup.use_market or not INTRABAR_ENABLED:
        return True

    target   = setup.entry
    sig      = setup.signal
    deadline = time.time() + INTRABAR_TIMEOUT_SEC
    log.info(f"⏱ Intrabar: {sig} @ {target:.2f} (timeout {INTRABAR_TIMEOUT_SEC}s)")

    while time.time() < deadline:
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None:
            time.sleep(INTRABAR_POLL_SEC); continue

        # SL invalidation check
        if sig == "BUY"  and tick.bid < setup.sl:
            log.info("⚠️ Intrabar: SL ถูกกินก่อน entry → ยกเลิก"); return False
        if sig == "SELL" and tick.ask > setup.sl:
            log.info("⚠️ Intrabar: SL ถูกกินก่อน entry → ยกเลิก"); return False

        info = mt5.symbol_info(SYMBOL)
        if info:
            spread_now = (tick.ask - tick.bid) / info.point
            if spread_now > HARD_SPREAD_BLOCK:
                time.sleep(INTRABAR_POLL_SEC); continue

        slip = (info.point * 8) if info else 0
        if sig == "BUY"  and tick.ask <= target + slip:
            log.info(f"✅ Intrabar BUY  @ {tick.ask:.2f}"); return True
        if sig == "SELL" and tick.bid >= target - slip:
            log.info(f"✅ Intrabar SELL @ {tick.bid:.2f}"); return True

        time.sleep(INTRABAR_POLL_SEC)

    log.info(f"⏰ Intrabar: timeout"); return False

# ══════════════════════════════════════════════════════════════════
# 💰  RISK ENGINE
# ══════════════════════════════════════════════════════════════════
def get_spread_pts() -> float:
    tick = mt5.symbol_info_tick(SYMBOL)
    info = mt5.symbol_info(SYMBOL)
    if tick is None or info is None: return 999.0
    return (tick.ask - tick.bid) / info.point

def is_spread_ok() -> bool:
    sp = get_spread_pts()
    if sp > HARD_SPREAD_BLOCK:
        log.warning(f"⛔ Spread {sp:.1f}pts > hard block {HARD_SPREAD_BLOCK}"); return False
    return True

def is_within_risk_limits() -> bool:
    acct = mt5.account_info()
    if acct is None: return True
    equity  = acct.equity
    balance = acct.balance

    today_key   = "daily_start_balance_" + datetime.now(bkk_tz).strftime("%Y%m%d")
    daily_start = get_state(today_key)
    if daily_start is None:
        set_state(today_key, balance); daily_start = balance

    daily_dd = (daily_start - equity) / daily_start * 100 if daily_start > 0 else 0
    if daily_dd >= MAX_DAILY_LOSS_PCT:
        log.warning(f"🛑 Daily DD {daily_dd:.2f}% ≥ {MAX_DAILY_LOSS_PCT}%"); return False

    init_bal = get_state("initial_balance")
    if init_bal is None:
        set_state("initial_balance", balance); init_bal = balance
    total_dd = (init_bal - equity) / init_bal * 100 if init_bal > 0 else 0
    if total_dd >= MAX_TOTAL_DD_PCT:
        log.warning(f"🛑 Total DD {total_dd:.2f}% ≥ {MAX_TOTAL_DD_PCT}%"); return False

    return True

def calculate_lot(entry: float, sl: float, score: int = 0) -> float:
    info = mt5.symbol_info(SYMBOL)
    if info is None: return LOT_MIN
    lot = LOT_MIN
    for score_min, tier_lot in LOT_TIERS:
        if score >= score_min:
            lot = tier_lot; break
    step = info.volume_step if info.volume_step > 0 else 0.01
    lot  = round(lot / step) * step
    return float(max(info.volume_min, min(lot, info.volume_max)))

def validate_order(entry: float, sl: float, tp: float,
                   lot: float, signal: str) -> tuple:
    info = mt5.symbol_info(SYMBOL)
    acct = mt5.account_info()
    tick = mt5.symbol_info_tick(SYMBOL)
    if not all([info, acct, tick]): return False, "อ่านข้อมูล broker ไม่ได้"

    min_d = info.trade_stops_level * info.point
    if abs(entry - sl) < min_d: return False, "SL ใกล้เกิน stop_level"
    if abs(entry - tp) < min_d: return False, "TP ใกล้เกิน stop_level"

    frz = info.trade_freeze_level * info.point
    if frz > 0 and abs(entry - tick.ask) < frz: return False, "Entry ใน freeze zone"

    step = info.volume_step
    if abs(round(lot / step) * step - lot) > 1e-8: return False, "Lot step ผิด"

    order_type = mt5.ORDER_TYPE_BUY if signal == "BUY" else mt5.ORDER_TYPE_SELL
    margin_req = mt5.order_calc_margin(order_type, SYMBOL, lot, entry)
    if margin_req is None or margin_req > acct.margin_free * 0.9:
        return False, "Margin ไม่พอ"
    return True, "OK"

def has_active_trade() -> bool:
    orders    = mt5.orders_get(symbol=SYMBOL)    or []
    positions = mt5.positions_get(symbol=SYMBOL) or []
    return (any(o.magic == MAGIC_NUMBER for o in orders) or
            any(p.magic == MAGIC_NUMBER for p in positions))

def _send_retry(req: dict, retries: int = 3):
    for i in range(1, retries + 1):
        res = mt5.order_send(req)
        if res is None:
            log.warning(f"order_send None (try {i})"); time.sleep(0.5); continue
        if res.retcode == mt5.TRADE_RETCODE_DONE: return res
        if res.retcode in (mt5.TRADE_RETCODE_REQUOTE,
                           mt5.TRADE_RETCODE_PRICE_CHANGED,
                           mt5.TRADE_RETCODE_CONNECTION,
                           mt5.TRADE_RETCODE_TIMEOUT):
            log.warning(f"Retry retcode:{res.retcode} (try {i})")
            time.sleep(0.5 * i); continue
        log.error(f"❌ retcode:{res.retcode} | {res.comment}"); return res
    return None

# ══════════════════════════════════════════════════════════════════
# 📤  PLACE ORDER
# ══════════════════════════════════════════════════════════════════
def place_order(setup: SetupResult, session: str = "") -> bool:
    if not is_spread_ok() or not is_within_risk_limits(): return False

    # M1 confirm → bonus score (ไม่ block)
    sp = get_spread_pts()
    if sp > MAX_SPREAD_POINTS:
        setup.score += SCORE_SPREAD_WARN
        setup.reasons.append(f"Spread{sp:.0f}pts ⚠️")

    rates_m1 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 5)
    if rates_m1 is not None and len(rates_m1) >= 3:
        df_m1 = pd.DataFrame(rates_m1)
        c = df_m1.iloc[-2]
        body_m1 = abs(c['close'] - c['open'])
        if body_m1 >= setup.atr * MTF_M1_BODY_ATR:
            if (setup.signal == "BUY"  and c['close'] > c['open']) or \
               (setup.signal == "SELL" and c['close'] < c['open']):
                setup.score += SCORE_M1_CONFIRM
                setup.reasons.append("M1 ✓")

    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None: return False

    sig = setup.signal; sl = setup.sl
    if setup.use_market:
        entry  = tick.ask if sig == "BUY" else tick.bid
        otype  = mt5.ORDER_TYPE_BUY  if sig == "BUY" else mt5.ORDER_TYPE_SELL
        action = mt5.TRADE_ACTION_DEAL; exp = 0
    else:
        entry  = setup.entry
        otype  = mt5.ORDER_TYPE_BUY_LIMIT if sig == "BUY" else mt5.ORDER_TYPE_SELL_LIMIT
        action = mt5.TRADE_ACTION_PENDING
        exp    = int(time.time()) + (EXPIRATION_CANDLES * 5 * 60)

    risk = abs(entry - sl)
    if risk == 0: log.error("place_order: risk=0"); return False

    tp_full    = (entry + risk * RR_RATIO if sig == "BUY"
                  else entry - risk * RR_RATIO)
    lot_full   = calculate_lot(entry, sl, setup.score)
    ok, reason = validate_order(entry, sl, tp_full, lot_full, sig)
    if not ok: log.warning(f"⚠️ Validate: {reason}"); return False

    # Partial TP split
    info   = mt5.symbol_info(SYMBOL)
    v_step = info.volume_step if info else 0.01
    v_min  = info.volume_min  if info else 0.01
    lot_a  = max(v_min, round(lot_full * PARTIAL_TP_PCT / v_step) * v_step)
    lot_b  = max(v_min, round((lot_full - lot_a) / v_step) * v_step)
    tp_pt  = (entry + risk * PARTIAL_TP_RR if sig == "BUY"
              else entry - risk * PARTIAL_TP_RR)

    sent = 0
    for lot_i, tp_i, label in [(lot_a, tp_pt, "PT"), (lot_b, tp_full, "FT")]:
        req = {
            "action": action, "symbol": SYMBOL, "volume": lot_i,
            "type": otype, "price": round(float(entry), 2),
            "sl": round(float(sl), 2), "tp": round(float(tp_i), 2),
            "deviation": 20, "magic": MAGIC_NUMBER,
            "comment": f"V7|{sig}|{label}|{setup.score}",
        }
        if action == mt5.TRADE_ACTION_PENDING:
            req["type_time"]  = mt5.ORDER_TIME_SPECIFIED
            req["expiration"] = exp

        res = _send_retry(req)
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            sent += 1
            log.info(f"✅ {label}|{sig}|Lot:{lot_i}|"
                     f"E:{entry:.2f}|SL:{sl:.2f}|TP:{tp_i:.2f}")
        else:
            log.warning(f"⚠️ {label} order ไม่สำเร็จ")

    if sent > 0:
        mode = "MKT" if setup.use_market else "LMT"
        log.info(f"📦 {mode}|{sig}|Score:{setup.score}|"
                 f"LotA:{lot_a}+LotB:{lot_b}|Session:{session}")
        db_log_setup(sig, setup.score, entry, sl, tp_full,
                     setup.setup_hash, session)
        return True
    return False

# ══════════════════════════════════════════════════════════════════
# 🔧  POSITION MANAGEMENT
# ══════════════════════════════════════════════════════════════════
def _modify_sl(ticket: int, new_sl: float):
    res = mt5.order_send({
        "action":   mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "sl":       round(float(new_sl), 2),
    })
    if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
        log.warning(f"_modify_sl FAIL #{ticket} "
                    f"retcode:{res.retcode if res else 'None'}")

def _close_partial(pos, lot_close: float):
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None: return
    info  = mt5.symbol_info(SYMBOL)
    step  = info.volume_step if info else 0.01
    v_min = info.volume_min  if info else 0.01
    lot_close = max(v_min, min(
        round(lot_close / step) * step, pos.volume))

    is_buy      = (pos.type == mt5.ORDER_TYPE_BUY)
    close_type  = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
    close_price = tick.bid if is_buy else tick.ask

    res = _send_retry({
        "action":   mt5.TRADE_ACTION_DEAL,
        "symbol":   SYMBOL,
        "volume":   lot_close,
        "type":     close_type,
        "position": pos.ticket,
        "price":    round(float(close_price), 2),
        "deviation":20,
        "magic":    MAGIC_NUMBER,
        "comment":  "V7|PartialTP",
    })
    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        log.info(f"💰 Partial #{pos.ticket} Lot:{lot_close:.2f} @ {close_price:.2f}")

def manage_positions(atr: float):
    positions = [p for p in (mt5.positions_get(symbol=SYMBOL) or [])
                 if p.magic == MAGIC_NUMBER]
    if not positions: return

    tick = mt5.symbol_info_tick(SYMBOL)
    info = mt5.symbol_info(SYMBOL)
    if tick is None or info is None: return

    a = atr if atr > 0 else 1.0
    open_tickets = {p.ticket for p in positions}

    for pos in positions:
        entry    = pos.price_open
        sl_now   = pos.sl
        tp       = pos.tp
        risk     = (abs(tp - entry) / RR_RATIO
                    if RR_RATIO > 0 else abs(entry - sl_now))
        if risk == 0: continue

        is_buy   = (pos.type == mt5.ORDER_TYPE_BUY)
        price    = tick.bid if is_buy else tick.ask
        buf      = info.point * 5
        profit_r = ((price - entry) / risk if is_buy
                    else (entry - price) / risk)

        ts           = get_trail_state(pos.ticket)
        partial_done = ts["partial_done"] if ts else 0

        # Partial TP
        if not partial_done and profit_r >= PARTIAL_TP_RR:
            _close_partial(pos, pos.volume * PARTIAL_TP_PCT)
            set_partial_done(pos.ticket)
            be_sl = (entry + buf) if is_buy else (entry - buf)
            if (is_buy and sl_now < be_sl) or (not is_buy and sl_now > be_sl):
                _modify_sl(pos.ticket, be_sl)
                log.info(f"🔒 BE+Partial #{pos.ticket} SL→{be_sl:.2f}")
            continue

        # Break-Even
        if profit_r >= BREAKEVEN_RR:
            be_sl = (entry + buf) if is_buy else (entry - buf)
            if (is_buy and sl_now < be_sl) or (not is_buy and sl_now > be_sl):
                _modify_sl(pos.ticket, be_sl)
                log.info(f"🔒 BE #{pos.ticket} SL→{be_sl:.2f}"); continue

        # Trailing
        if profit_r >= TRAIL_AFTER_RR:
            last_tsl = ts["last_sl"] if ts else None
            min_move = a * TRAIL_MIN_MOVE_ATR
            if is_buy:
                new_tsl = price - (a * TRAIL_ATR_MULT)
                if (new_tsl > sl_now and
                        (last_tsl is None or new_tsl > last_tsl + min_move)):
                    _modify_sl(pos.ticket, new_tsl)
                    save_trail_sl(pos.ticket, new_tsl)
                    log.info(f"📈 Trail #{pos.ticket} SL→{new_tsl:.2f}")
            else:
                new_tsl = price + (a * TRAIL_ATR_MULT)
                if (new_tsl < sl_now and
                        (last_tsl is None or new_tsl < last_tsl - min_move)):
                    _modify_sl(pos.ticket, new_tsl)
                    save_trail_sl(pos.ticket, new_tsl)
                    log.info(f"📉 Trail #{pos.ticket} SL→{new_tsl:.2f}")

    cleanup_trail_state(open_tickets)

# ══════════════════════════════════════════════════════════════════
# 🔌  MT5 MANAGER
# ══════════════════════════════════════════════════════════════════
def mt5_connect(retries: int = 10, delay: float = 5.0) -> bool:
    for i in range(1, retries + 1):
        if mt5.initialize():
            log.info(f"✅ MT5 connected (try {i})"); return True
        log.warning(f"MT5 connect try {i}/{retries}..."); time.sleep(delay)
    return False

def mt5_alive() -> bool:
    return mt5.terminal_info() is not None

def ensure_alive() -> bool:
    if mt5_alive(): return True
    log.warning("MT5 หลุด → reconnect")
    return mt5_connect(retries=5, delay=3.0)

def wait_next_candle(tf_min: int = 5):
    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M5, 0, 1)
    if rates is not None and len(rates) > 0:
        next_bar = int(rates[0]['time']) + (tf_min * 60)
        wait     = next_bar - int(time.time()) + 3
        if 0 < wait <= tf_min * 60 + 10:
            log.info(f"⏳ รอ {wait:.0f}s")
            time.sleep(wait); return
    now     = datetime.now(bkk_tz)
    elapsed = (now.minute % tf_min) * 60 + now.second
    wait    = (tf_min * 60) - elapsed + 3
    if wait <= 0 or wait > tf_min * 60: wait = tf_min * 60 + 3
    log.info(f"⏳ รอ {wait:.0f}s (fallback)")
    time.sleep(wait)

# ══════════════════════════════════════════════════════════════════
# 🔄  MAIN LOOP
# ══════════════════════════════════════════════════════════════════
BANNER = """
╔══════════════════════════════════════════════════════════════════════════╗
║  🚀 AI SMC/ICT Pro Sniper — V.7 BALANCED                                ║
║  Gate1:Hard | Gate2:Sweep OR FVG | Gate3:Dynamic Score                  ║
║  FVG Memory 15 bars | Unlimited trades/day | Score-based lot            ║
║  Partial TP 50%@1R | Trail @2R | Intrabar 180s                         ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

if __name__ == "__main__":
    print(BANNER)
    log.info("Bot V.7 BALANCED เริ่มทำงาน")
    init_db()

    if not mt5_connect():
        log.error("❌ ไม่สามารถเชื่อมต่อ MT5"); quit()

    try:
        while True:
            cur = datetime.now(bkk_tz).strftime('%H:%M:%S')
            log.info("─" * 65)

            # GATE 1a — Connection
            if not ensure_alive():
                log.error("Reconnect ล้มเหลว → รอ 60s")
                time.sleep(60); continue

            # GATE 1b — Risk
            if not is_within_risk_limits():
                log.warning(f"⛔ {cur} | DD limit → หยุดเทรด วันนี้")
                data = fetch_all()
                if data["m5"] is not None:
                    manage_positions(calculate_atr(data["m5"]))
                wait_next_candle(); continue

            # GATE 1c — Session
            session = get_session()
            log.info(f"🕐 {cur} | {session}")
            if session in ("OUT_OF_SESSION", "RED_NEWS_BLOCK"):
                data = fetch_all()
                if data["m5"] is not None:
                    manage_positions(calculate_atr(data["m5"]))
                wait_next_candle(); continue

            # GATE 1d — Hard Spread
            if not is_spread_ok():
                log.warning("⚠️ Spread เกิน hard block → รอ")
                wait_next_candle(); continue

            # Fetch ข้อมูลทุก TF
            data = fetch_all()
            if data["m5"] is None:
                log.warning("M5 ไม่ได้ข้อมูล → ข้ามรอบ")
                wait_next_candle(); continue

            # Manage positions
            atr = calculate_atr(data["m5"])
            manage_positions(atr)
            cleanup_cooldowns()

            # GATE 2+3 — Signal + Score
            # ไม่มี has_active_trade() block → ออกไม้ได้เรื่อยๆ
            setup = analyze_setup(
                data["m5"], data["h1"], data["d1"],
                data["m15"], session
            )

            # Log สถานะ
            liq = setup.liq_map
            if liq:
                log.info(f"💧 BSL:{liq.bsl_nearest or '—'} | "
                         f"SSL:{liq.ssl_nearest or '—'} | "
                         f"SwH:{liq.swept_high} | SwL:{liq.swept_low}")
            log.info(f"📊 HTF:{setup.htf_bias} | M15:{setup.m15_struct} | "
                     f"ADR:{setup.adr_pct*100:.0f}% | "
                     f"Threshold:{setup.threshold}")

            if setup.signal == "WAIT":
                log.info(f"📉 WAIT → {' | '.join(setup.reasons) or 'ไม่พบ setup'}")
                wait_next_candle(); continue

            log.info(f"🔥 {setup.summary()}")

            # GATE 3 — Dynamic Score
            if setup.score < setup.threshold:
                log.info(f"⚠️ Score {setup.score} < {setup.threshold} → ข้าม")
                wait_next_candle(); continue

            # Duplicate check (cooldown สั้นลง 180s)
            if is_on_cooldown(setup.setup_hash):
                log.info(f"🔁 Cooldown ({setup.setup_hash}) → ข้าม")
                wait_next_candle(); continue

            # Intrabar Trigger
            if not setup.use_market:
                if not wait_for_price_touch(setup):
                    log.info("⏰ Intrabar miss → ข้ามรอบ")
                    wait_next_candle(); continue
                if not is_within_risk_limits() or not is_spread_ok():
                    log.info("⚠️ Risk/Spread เปลี่ยนหลัง wait → ข้าม")
                    wait_next_candle(); continue

            # Execute
            if place_order(setup, session):
                set_cooldown(setup.setup_hash)
                log.info(f"🎯 Placed | hash:{setup.setup_hash}")

            wait_next_candle()

    except KeyboardInterrupt:
        log.info("🛑 หยุดโดยผู้ใช้")
    except Exception as e:
        log.exception(f"💥 {e}")
    finally:
        close_db()
        mt5.shutdown()
        log.info("MT5 offline. Bot V.7 bye.")