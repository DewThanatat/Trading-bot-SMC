"""
╔══════════════════════════════════════════════════════════════════════╗
║   🚀 AI SMC/ICT Pro Sniper — V.6 ULTRA                              ║
║   • Intrabar Trigger (tick-level execution, no late entry)           ║
║   • Multi-TF Execution (M1 confirmation → M5/M15/H1 context)        ║
║   • Liquidity Mapping (EQH/EQL, buy-side / sell-side liquidity)      ║
║   • Partial TP (50% @ 1R, trail remainder)                           ║
║   • Fix: DB singleton, daily DD snapshot, hash collision, margin    ║
╚══════════════════════════════════════════════════════════════════════╝
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
from typing import Optional
import pytz

# ══════════════════════════════════════════════════════════════════
# ⚙️  CONFIGURATION
# ══════════════════════════════════════════════════════════════════
SYMBOL              = "BTCUSDm"
MAGIC_NUMBER        = 99999
RISK_PERCENT        = 1.0        # % ของ Balance ต่อไม้
RR_RATIO            = 2.5
MAX_DAILY_LOSS_PCT  = 4.0        # % equity drawdown / วัน
MAX_TOTAL_DD_PCT    = 8.0        # % total max drawdown
MIN_SCORE           = 55
EXPIRATION_CANDLES  = 6          # แท่ง M5 ก่อน Pending หมดอายุ
MAX_SPREAD_POINTS   = 40.0
MOMENTUM_BODY_ATR   = 1.4
BREAKEVEN_RR        = 1.0
TRAIL_AFTER_RR      = 2.0
TRAIL_ATR_MULT      = 1.2
TRAIL_MIN_MOVE_ATR  = 0.3
ADR_EXHAUSTED_PCT   = 0.85
SWING_PERIOD        = 5
SWING_CONFIRM_BARS  = 2
SETUP_COOLDOWN_SEC  = 300

# Partial TP
PARTIAL_TP_RR       = 1.0        # TP บางส่วนที่ 1R
PARTIAL_TP_PCT      = 0.50       # ปิด 50% ที่ partial TP

# Intrabar — tick polling
INTRABAR_ENABLED    = True
INTRABAR_POLL_SEC   = 0.5        # ตรวจทุก 0.5 วินาที
INTRABAR_TIMEOUT_SEC= 290        # รอสูงสุด ~1 แท่ง M5

# Multi-TF confirmation
MTF_M1_CONFIRM      = True       # ต้องการ M1 candle confirm ก่อน execute
MTF_M1_BODY_ATR     = 0.4        # body M1 > ATR*0.4 ถือว่า confirm

# Liquidity
LIQ_SWING_PERIOD    = 10         # หา EQH/EQL ใน 10 แท่ง
LIQ_EQUAL_TOLERANCE = 0.0003     # 0.03% ถือว่า "equal" highs/lows
LIQ_MIN_CLUSTER     = 2          # ต้องมีอย่างน้อย 2 จุดถึงเป็น cluster

DB_PATH             = "smc_state.db"
LOG_PATH            = "smc_bot.log"

# Score-based Lot Sizing (Exness unlimited leverage)
# Bot จะเพิ่ม lot ตาม confidence score อัตโนมัติ
LOT_MIN   = 0.01   # lot ขั้นต่ำ (ไม่มั่นใจ / score ต่ำ)
LOT_TIERS = [
    # (score_ขั้นต่ำ, lot) — เรียงจากสูงไปต่ำ
    (90, 0.05),   # 🔥🔥🔥 มั่นใจสูงมาก
    (80, 0.04),   # 🔥🔥
    (70, 0.03),   # 🔥
    (62, 0.02),   # พอใช้
    (0,  0.01),   # default / ไม่มั่นใจ
]

# Scoring weights
SCORE_BASE          = 40
SCORE_HTF_ALIGN     = 15
SCORE_HTF_AGAINST   = -10
SCORE_STRONG_CANDLE = 15
SCORE_OB_ZONE       = 15
SCORE_BOS           = 10
SCORE_ADR_WARN      = -10
SCORE_LIQ_ABOVE     = 12        # ราคาใกล้ liquidity zone (เป้าหมาย)
SCORE_LIQ_SWEPT     = 10        # liquidity ถูก sweep แล้ว
SCORE_M1_CONFIRM    = 8         # M1 structure confirm

# Sessions (Bangkok time)
SESSIONS = [
    (12,  0, 14,  0, "PRE_LONDON"),
    (14,  0, 18,  0, "LONDON"),
    (18, 30, 19, 15, "NY_OPEN_EARLY"),
    (19, 45, 23, 59, "NEW_YORK"),
]
NEWS_BLOCKS = [(19, 15, 19, 45)]

bkk_tz = pytz.timezone('Asia/Bangkok')

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
# 💾  PERSISTENCE — Singleton DB Connection (fix #1)
# ══════════════════════════════════════════════════════════════════
_db_conn: Optional[sqlite3.Connection] = None
_db_lock = threading.Lock()

def get_db() -> sqlite3.Connection:
    """Singleton connection — เปิดครั้งเดียว thread-safe"""
    global _db_conn
    with _db_lock:
        if _db_conn is None:
            _db_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            _db_conn.row_factory = sqlite3.Row
            _db_conn.execute("PRAGMA journal_mode=WAL")   # ลด lock contention
            _db_conn.execute("PRAGMA synchronous=NORMAL")
        return _db_conn

def close_db():
    """ปิด singleton connection อย่างปลอดภัย"""
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
            entry REAL, sl REAL, tp REAL, setup_hash TEXT
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

def _db_query_all(sql: str, params: tuple = ()):
    with _db_lock:
        return get_db().execute(sql, params).fetchall()

def is_on_cooldown(h: str) -> bool:
    row = _db_query("SELECT expires_at FROM cooldown WHERE setup_hash=?", (h,))
    return bool(row and row["expires_at"] > time.time())

def set_cooldown(h: str):
    _db_exec("INSERT OR REPLACE INTO cooldown VALUES(?,?)", (h, time.time() + SETUP_COOLDOWN_SEC))

def cleanup_cooldowns():
    _db_exec("DELETE FROM cooldown WHERE expires_at<=?", (time.time(),))

def db_log_setup(signal, score, entry, sl, tp, h):
    _db_exec(
        "INSERT INTO setup_log(ts,signal,score,entry,sl,tp,setup_hash) VALUES(?,?,?,?,?,?,?)",
        (time.time(), signal, score, entry, sl, tp, h)
    )

def get_trail_state(ticket: int):
    return _db_query("SELECT last_sl, partial_done FROM trail_state WHERE ticket=?", (ticket,))

def save_trail_sl(ticket: int, sl: float, partial_done: int = None):
    existing = get_trail_state(ticket)
    if partial_done is None:
        partial_done = existing["partial_done"] if existing else 0
    _db_exec(
        "INSERT OR REPLACE INTO trail_state VALUES(?,?,?,?)",
        (ticket, sl, time.time(), partial_done)
    )

def set_partial_done(ticket: int):
    existing = get_trail_state(ticket)
    last_sl = existing["last_sl"] if existing else 0.0
    _db_exec(
        "INSERT OR REPLACE INTO trail_state VALUES(?,?,?,?)",
        (ticket, last_sl, time.time(), 1)
    )

def remove_trail_state(ticket: int):
    _db_exec("DELETE FROM trail_state WHERE ticket=?", (ticket,))

def cleanup_trail_state(open_tickets: set):
    """Bulk delete ใน SQL ตรงๆ แทน loop Python (fix #5)"""
    if not open_tickets:
        _db_exec("DELETE FROM trail_state")
        return
    placeholders = ",".join("?" * len(open_tickets))
    _db_exec(
        f"DELETE FROM trail_state WHERE ticket NOT IN ({placeholders})",
        tuple(open_tickets)
    )

def get_state(key: str, default=None):
    row = _db_query("SELECT value FROM bot_state WHERE key=?", (key,))
    return json.loads(row["value"]) if row else default

def set_state(key: str, value):
    _db_exec("INSERT OR REPLACE INTO bot_state VALUES(?,?)", (key, json.dumps(value)))

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
    dr  = df_d1['high'] - df_d1['low']
    val = dr.rolling(period).mean().iloc[-1]
    return float(val) if not np.isnan(val) else 0.0

def get_confirmed_swings(df: pd.DataFrame, period: int = 5, confirm: int = 2):
    """Confirmed Swing — ไม่มี look-ahead / repaint"""
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
# 💧  LIQUIDITY MAPPING (ใหม่)
# ══════════════════════════════════════════════════════════════════
@dataclass
class LiquidityMap:
    buy_side:   list = field(default_factory=list)   # EQH clusters (sell-side target)
    sell_side:  list = field(default_factory=list)   # EQL clusters (buy-side target)
    swept_high: Optional[float] = None               # ล่าสุดที่ถูก sweep
    swept_low:  Optional[float] = None
    bsl_nearest: Optional[float] = None              # BSL ที่ใกล้ราคาปัจจุบันที่สุด
    ssl_nearest: Optional[float] = None              # SSL ที่ใกล้ราคาปัจจุบันที่สุด

def build_liquidity_map(df: pd.DataFrame, atr: float, period: int = 10) -> LiquidityMap:
    """
    ระบุ Equal Highs (EQH) และ Equal Lows (EQL)
    — หลักการ ICT: ราคามักวิ่งไป "grab" liquidity ก่อนกลับทิศ

    Algorithm:
    1. หา swing highs/lows ใน window
    2. กลุ่มที่ราคา high/low ใกล้เคียงกัน (tolerance) = Equal → liquidity pool
    3. ถ้า candle ล่าสุด wick ผ่านแต่ close กลับ = swept
    """
    liq = LiquidityMap()
    if len(df) < period * 2 + 4 or atr == 0:
        return liq

    safe = df.iloc[:-2]   # ตัด live + 1 ออก
    tol  = atr * LIQ_EQUAL_TOLERANCE / (atr * 0.0001 + 1e-9) * atr * 0.0001
    # ปรับ tolerance ตาม ATR จริง
    tol  = max(atr * 0.08, abs(df['close'].iloc[-1]) * LIQ_EQUAL_TOLERANCE)

    # หา pivot highs / lows
    ph_list, pl_list = [], []
    for i in range(period, len(safe) - period):
        w_h = safe['high'].iloc[i - period: i + period + 1]
        w_l = safe['low'].iloc[i - period: i + period + 1]
        if safe['high'].iloc[i] == w_h.max():
            ph_list.append(float(safe['high'].iloc[i]))
        if safe['low'].iloc[i] == w_l.min():
            pl_list.append(float(safe['low'].iloc[i]))

    # Cluster equal highs → Buy-side Liquidity (EQH)
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

    liq.buy_side  = sorted(cluster(ph_list, tol), reverse=True)   # EQH → BSL
    liq.sell_side = sorted(cluster(pl_list, tol))                   # EQL → SSL

    last = df.iloc[-1]
    prev = df.iloc[-2]

    # ตรวจ sweep: wick ผ่าน level แต่ close กลับมา
    for lvl in liq.buy_side:
        if last['high'] > lvl and last['close'] < lvl:
            liq.swept_high = lvl; break
    for lvl in liq.sell_side:
        if last['low'] < lvl and last['close'] > lvl:
            liq.swept_low = lvl; break

    # หา nearest
    price = float(last['close'])
    above = [l for l in liq.buy_side  if l > price]
    below = [l for l in liq.sell_side if l < price]
    liq.bsl_nearest = min(above) if above else None
    liq.ssl_nearest = max(below) if below else None

    return liq

# ══════════════════════════════════════════════════════════════════
# 📐  INDICATORS (ต่อ)
# ══════════════════════════════════════════════════════════════════
@dataclass
class FVGResult:
    kind: str = "NONE"
    top:  float = 0.0
    bot:  float = 0.0
    strength: float = 0.0

def check_fvg(df: pd.DataFrame, atr: float) -> FVGResult:
    if len(df) < 3 or atr == 0:
        return FVGResult()
    c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    c2_range = c2['high'] - c2['low']
    c2_body  = abs(c2['close'] - c2['open'])
    if c2_range > 0 and (c2_body / c2_range) < 0.4:
        return FVGResult()
    min_gap = atr * 0.15
    overlap = atr * 0.25
    if c3['low'] > c1['high'] - overlap:
        top = c3['low']; bot = c1['high']
        if top < bot: top, bot = bot, top
        if (top - bot) >= min_gap:
            return FVGResult("BULLISH", top, bot, (top - bot) / atr)
    if c3['high'] < c1['low'] + overlap:
        top = c1['low']; bot = c3['high']
        if top < bot: top, bot = bot, top
        if (top - bot) >= min_gap:
            return FVGResult("BEARISH", top, bot, (top - bot) / atr)
    return FVGResult()

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
        imp_body = abs(imp['close'] - imp['open'])
        if imp_body < atr * 1.2:
            continue
        if direction == "BUY":
            if ob['close'] >= ob['open']: continue
            if imp['close'] <= imp['open']: continue
            prior_high = closed['high'].iloc[max(0, i-10): i].max()
            if imp['close'] <= prior_high * 0.998: continue
            prior_low  = closed['low'].iloc[max(0, i-5): i].min()
            has_sweep  = prior_low < ob['low']
            ob_range   = ob['high'] - ob['low']
            ob_body    = (ob['open'] - ob['close']) / ob_range if ob_range > 0 else 0
            q = 0.5 + (0.3 if has_sweep else 0) + (0.2 if ob_body > 0.6 else 0)
            return OBResult(True, float(ob['high']), float(ob['low']), q)
        elif direction == "SELL":
            if ob['close'] <= ob['open']: continue
            if imp['close'] >= imp['open']: continue
            prior_low  = closed['low'].iloc[max(0, i-10): i].min()
            if imp['close'] >= prior_low * 1.002: continue
            prior_high = closed['high'].iloc[max(0, i-5): i].max()
            has_sweep  = prior_high > ob['high']
            ob_range   = ob['high'] - ob['low']
            ob_body    = (ob['close'] - ob['open']) / ob_range if ob_range > 0 else 0
            q = 0.5 + (0.3 if has_sweep else 0) + (0.2 if ob_body > 0.6 else 0)
            return OBResult(True, float(ob['high']), float(ob['low']), q)
    return OBResult()

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
    """
    M15 Market Structure — CHoCH / BOS detection
    ใช้เป็น confluence เพิ่มเติม
    """
    if df_m15 is None or len(df_m15) < 20:
        return "NEUTRAL"
    sh, sl = get_confirmed_swings(df_m15, period=3, confirm=2)
    last = df_m15.iloc[-1]
    if last['close'] > sh: return "BULLISH_BOS"
    if last['close'] < sl: return "BEARISH_BOS"
    return "NEUTRAL"

# ══════════════════════════════════════════════════════════════════
# 🔍  MULTI-TF M1 CONFIRMATION (ใหม่)
# ══════════════════════════════════════════════════════════════════
def get_m1_confirmation(direction: str, atr_m5: float) -> bool:
    """
    ดึง M1 ล่าสุด ตรวจ candle structure ว่า confirm ทิศทางหรือไม่
    BUY  → ต้องการ bullish engulf / strong close บน M1
    SELL → bearish engulf / strong close ล่าง M1
    """
    if not MTF_M1_CONFIRM:
        return True
    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 5)
    if rates is None or len(rates) < 3:
        return False
    df = pd.DataFrame(rates)
    c  = df.iloc[-2]   # candle ล่าสุดที่ปิดแล้ว
    body   = abs(c['close'] - c['open'])
    rng    = c['high'] - c['low']
    # ต้องการ body ≥ threshold ของ ATR M5
    min_body = atr_m5 * MTF_M1_BODY_ATR
    if body < min_body:
        return False
    # ทิศทางถูกต้อง
    if direction == "BUY"  and c['close'] > c['open']: return True
    if direction == "SELL" and c['close'] < c['open']: return True
    return False

# ══════════════════════════════════════════════════════════════════
# 🕒  SESSION
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

# ══════════════════════════════════════════════════════════════════
# 📊  DATA FEED
# ══════════════════════════════════════════════════════════════════
_cache: dict = {}
CACHE_TTL = 20

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
    m1  = fetch(mt5.TIMEFRAME_M1,  60, False)
    m5  = fetch(mt5.TIMEFRAME_M5,  200, False)
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
# 🎯  SIGNAL ENGINE
# ══════════════════════════════════════════════════════════════════
@dataclass
class SetupResult:
    signal:      str   = "WAIT"
    score:       int   = 0
    entry:       float = 0.0
    sl:          float = 0.0
    atr:         float = 0.0
    htf_bias:    str   = "NEUTRAL"
    m15_struct:  str   = "NEUTRAL"
    adr_pct:     float = 0.0
    reasons:     list  = field(default_factory=list)
    setup_hash:  str   = ""
    use_market:  bool  = False
    liq_map:     Optional[object] = None  # LiquidityMap
    candle_ts:   float = 0.0              # timestamp ของ candle ที่ trigger

    def summary(self) -> str:
        mode = "MKT" if self.use_market else "LMT"
        return f"{self.signal}({mode}) Score:{self.score} | {' | '.join(self.reasons)}"

def _make_hash(sig: str, entry: float, sl: float, ts: float) -> str:
    """
    Hash รวม timestamp ของแท่งเทียน — ป้องกัน collision (fix #3)
    """
    raw = f"{sig}:{entry:.2f}:{sl:.2f}:{int(ts)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]

def analyze_setup(df_m5, df_h1, df_d1, df_m15=None) -> SetupResult:
    r = SetupResult()
    if df_m5 is None or len(df_m5) < 30:
        r.reasons.append("ข้อมูล M5 ไม่พอ"); return r

    atr = calculate_atr(df_m5)
    if atr == 0:
        r.reasons.append("ATR=0"); return r
    r.atr = atr

    # ADR
    adr = calculate_adr(df_d1) if df_d1 is not None and len(df_d1) >= 10 else 0.0
    if df_d1 is not None and len(df_d1) >= 1 and adr > 0:
        r.adr_pct = (df_d1['high'].iloc[-1] - df_d1['low'].iloc[-1]) / adr

    # HTF Bias
    r.htf_bias   = get_htf_bias(df_h1)
    r.m15_struct = get_m15_structure(df_m15)

    # Liquidity Map
    liq = build_liquidity_map(df_m5, atr, LIQ_SWING_PERIOD)
    r.liq_map = liq

    # Swing (confirmed)
    last_sh, last_sl = get_confirmed_swings(df_m5, SWING_PERIOD, SWING_CONFIRM_BARS)

    # FVG
    fvg = check_fvg(df_m5, atr)

    last = df_m5.iloc[-1]
    prev = df_m5.iloc[-2]
    r.candle_ts = float(last['time'].timestamp()) if hasattr(last['time'], 'timestamp') else time.time()

    sweep_sell = (last['low'] < last_sl)  and (last['close'] > last_sl)
    sweep_buy  = (last['high'] > last_sh) and (last['close'] < last_sh)

    # ── BUY ──────────────────────────────────────────────────────
    if sweep_sell and fvg.kind == "BULLISH":
        r.signal = "BUY"
        r.entry  = fvg.top
        r.sl     = last_sl - (atr * 0.5)
        r.score  = SCORE_BASE
        r.reasons.append("Sweep SSL ✓")
        r.reasons.append(f"BFVG(s:{fvg.strength:.2f}) ✓")

        # HTF
        if r.htf_bias == "BULLISH":
            r.score += SCORE_HTF_ALIGN;   r.reasons.append("HTF Bull ✓")
        elif r.htf_bias == "BEARISH":
            r.score += SCORE_HTF_AGAINST; r.reasons.append("HTF Bear ⚠️")

        # M15 Structure
        if r.m15_struct == "BULLISH_BOS":
            r.score += 8; r.reasons.append("M15 BOS ✓")

        # Strong candle
        body = last['close'] - last['open']
        if body > atr * 0.7:
            r.score += SCORE_STRONG_CANDLE; r.reasons.append("Strong ✓")

        # OB
        ob = find_order_block(df_m5, "BUY", atr)
        if ob.found and ob.low <= r.entry <= ob.high:
            bonus = int(SCORE_OB_ZONE * ob.score)
            r.score += bonus; r.reasons.append(f"OB(q:{ob.score:.2f}) ✓")

        # BOS
        if last['close'] > prev['high']:
            r.score += SCORE_BOS; r.reasons.append("BOS ✓")

        # ADR
        if r.adr_pct >= ADR_EXHAUSTED_PCT:
            r.score += SCORE_ADR_WARN; r.reasons.append(f"ADR{r.adr_pct*100:.0f}% ⚠️")

        # FVG bonus
        if fvg.strength > 0.5:
            r.score += 5; r.reasons.append("FVG+ ✓")

        # Liquidity scoring
        if liq.swept_low is not None:
            r.score += SCORE_LIQ_SWEPT; r.reasons.append(f"SSL Swept({liq.swept_low:.2f}) ✓")
        if liq.bsl_nearest is not None:
            risk = abs(r.entry - r.sl)
            if risk > 0 and (liq.bsl_nearest - r.entry) >= risk * RR_RATIO * 0.8:
                r.score += SCORE_LIQ_ABOVE; r.reasons.append(f"BSL Target({liq.bsl_nearest:.2f}) ✓")

        # Market mode
        body_ratio = body / atr if atr > 0 else 0
        if last['close'] > prev['high'] and body_ratio > MOMENTUM_BODY_ATR and r.score >= MIN_SCORE:
            r.use_market = True; r.entry = 0.0
            r.reasons.append("🚀 MKT")

    # ── SELL ─────────────────────────────────────────────────────
    elif sweep_buy and fvg.kind == "BEARISH":
        r.signal = "SELL"
        r.entry  = fvg.bot
        r.sl     = last_sh + (atr * 0.5)
        r.score  = SCORE_BASE
        r.reasons.append("Sweep BSL ✓")
        r.reasons.append(f"SFVG(s:{fvg.strength:.2f}) ✓")

        if r.htf_bias == "BEARISH":
            r.score += SCORE_HTF_ALIGN;   r.reasons.append("HTF Bear ✓")
        elif r.htf_bias == "BULLISH":
            r.score += SCORE_HTF_AGAINST; r.reasons.append("HTF Bull ⚠️")

        if r.m15_struct == "BEARISH_BOS":
            r.score += 8; r.reasons.append("M15 BOS ✓")

        body = last['open'] - last['close']
        if body > atr * 0.7:
            r.score += SCORE_STRONG_CANDLE; r.reasons.append("Strong ✓")

        ob = find_order_block(df_m5, "SELL", atr)
        if ob.found and ob.low <= r.entry <= ob.high:
            bonus = int(SCORE_OB_ZONE * ob.score)
            r.score += bonus; r.reasons.append(f"OB(q:{ob.score:.2f}) ✓")

        if last['close'] < prev['low']:
            r.score += SCORE_BOS; r.reasons.append("BOS ✓")

        if r.adr_pct >= ADR_EXHAUSTED_PCT:
            r.score += SCORE_ADR_WARN; r.reasons.append(f"ADR{r.adr_pct*100:.0f}% ⚠️")

        if fvg.strength > 0.5:
            r.score += 5; r.reasons.append("FVG+ ✓")

        if liq.swept_high is not None:
            r.score += SCORE_LIQ_SWEPT; r.reasons.append(f"BSL Swept({liq.swept_high:.2f}) ✓")
        if liq.ssl_nearest is not None:
            risk = abs(r.sl - r.entry)
            if risk > 0 and (r.entry - liq.ssl_nearest) >= risk * RR_RATIO * 0.8:
                r.score += SCORE_LIQ_ABOVE; r.reasons.append(f"SSL Target({liq.ssl_nearest:.2f}) ✓")

        body_ratio = body / atr if atr > 0 else 0
        if last['close'] < prev['low'] and body_ratio > MOMENTUM_BODY_ATR and r.score >= MIN_SCORE:
            r.use_market = True; r.entry = 0.0
            r.reasons.append("🚀 MKT")

    if r.signal != "WAIT":
        entry_for_hash = r.entry if not r.use_market else -1.0
        r.setup_hash = _make_hash(r.signal, entry_for_hash, r.sl, r.candle_ts)

    return r

# ══════════════════════════════════════════════════════════════════
# ⚡  INTRABAR TRIGGER (ใหม่)
# ══════════════════════════════════════════════════════════════════
def wait_for_price_touch(setup: SetupResult) -> bool:
    """
    แทนการรอ candle ปิดแล้วค่อย execute
    → poll ทุก INTRABAR_POLL_SEC ว่า bid/ask แตะ entry หรือยัง
    ใช้เฉพาะ Limit mode (Market mode ไม่จำเป็น)

    Return True เมื่อแตะ entry (ควร execute ได้)
    Return False เมื่อ timeout หรือ signal เสีย
    """
    if setup.use_market or not INTRABAR_ENABLED:
        return True   # Market order — execute ทันที

    target = setup.entry
    sig    = setup.signal
    deadline = time.time() + INTRABAR_TIMEOUT_SEC

    log.info(f"⏱ Intrabar watch: {sig} @ {target:.2f} (timeout {INTRABAR_TIMEOUT_SEC}s)")

    while time.time() < deadline:
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None:
            time.sleep(INTRABAR_POLL_SEC); continue

        # ตรวจว่า setup ยังสมเหตุสมผล (SL ไม่ถูกกิน)
        if sig == "BUY"  and tick.bid < setup.sl:
            log.info("⚠️ Intrabar: SL ถูกกินก่อน entry → ยกเลิก")
            return False
        if sig == "SELL" and tick.ask > setup.sl:
            log.info("⚠️ Intrabar: SL ถูกกินก่อน entry → ยกเลิก")
            return False

        # ตรวจ spread ก่อน execute
        info = mt5.symbol_info(SYMBOL)
        if info:
            spread_now = (tick.ask - tick.bid) / info.point
            if spread_now > MAX_SPREAD_POINTS:
                time.sleep(INTRABAR_POLL_SEC); continue

        # Price touched entry zone (±5 points slippage)
        slippage_pts = (info.point * 5) if info else 0
        if sig == "BUY"  and tick.ask <= target + slippage_pts:
            log.info(f"✅ Intrabar trigger BUY  @ ask:{tick.ask:.2f} (target:{target:.2f})")
            return True
        if sig == "SELL" and tick.bid >= target - slippage_pts:
            log.info(f"✅ Intrabar trigger SELL @ bid:{tick.bid:.2f} (target:{target:.2f})")
            return True

        time.sleep(INTRABAR_POLL_SEC)

    log.info(f"⏰ Intrabar: timeout — entry ไม่ถูกแตะใน {INTRABAR_TIMEOUT_SEC}s")
    return False

# ══════════════════════════════════════════════════════════════════
# 💰  RISK + EXECUTION ENGINE
# ══════════════════════════════════════════════════════════════════
def is_spread_ok() -> bool:
    tick = mt5.symbol_info_tick(SYMBOL)
    info = mt5.symbol_info(SYMBOL)
    if tick is None or info is None: return False
    spread = (tick.ask - tick.bid) / info.point
    if spread > MAX_SPREAD_POINTS:
        log.warning(f"⚠️ Spread {spread:.1f}pts > {MAX_SPREAD_POINTS} → ข้าม")
        return False
    return True

def is_within_risk_limits() -> bool:
    acct = mt5.account_info()
    if acct is None: return True
    equity  = acct.equity
    balance = acct.balance

    # Daily DD — ใช้ daily_start_balance (fix #2)
    today_key = "daily_start_balance_" + datetime.now(bkk_tz).strftime("%Y%m%d")
    daily_start = get_state(today_key)
    if daily_start is None:
        set_state(today_key, balance); daily_start = balance

    daily_dd = (daily_start - equity) / daily_start * 100 if daily_start > 0 else 0
    if daily_dd >= MAX_DAILY_LOSS_PCT:
        log.warning(f"🛑 Daily DD {daily_dd:.2f}% ≥ {MAX_DAILY_LOSS_PCT}%"); return False

    # Total DD
    init_bal = get_state("initial_balance")
    if init_bal is None:
        set_state("initial_balance", balance); init_bal = balance
    total_dd = (init_bal - equity) / init_bal * 100 if init_bal > 0 else 0
    if total_dd >= MAX_TOTAL_DD_PCT:
        log.warning(f"🛑 Total DD {total_dd:.2f}% ≥ {MAX_TOTAL_DD_PCT}%"); return False

    return True

def calculate_lot(entry: float, sl: float, score: int = 0) -> float:
    """
    Score-based lot sizing:
    - score สูง -> lot มากขึ้นตาม LOT_TIERS
    - clamp ด้วย volume_min / volume_max ของ broker เสมอ
    """
    info = mt5.symbol_info(SYMBOL)
    if info is None:
        return LOT_MIN
    lot = LOT_MIN
    for score_min, tier_lot in LOT_TIERS:
        if score >= score_min:
            lot = tier_lot
            break
    step = info.volume_step if info.volume_step > 0 else 0.01
    lot  = round(lot / step) * step
    return float(max(info.volume_min, min(lot, info.volume_max)))

def validate_order(entry: float, sl: float, tp: float, lot: float, signal: str) -> tuple:
    """fix #6 — ส่ง correct order type ตาม signal"""
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

    # fix #6 — ใช้ order type ตาม signal
    order_type = mt5.ORDER_TYPE_BUY if signal == "BUY" else mt5.ORDER_TYPE_SELL
    margin_req = mt5.order_calc_margin(order_type, SYMBOL, lot, entry)
    if margin_req is None or margin_req > acct.margin_free * 0.9:
        return False, "Margin ไม่พอ"
    return True, "OK"

def has_active_trade() -> bool:
    orders    = mt5.orders_get(symbol=SYMBOL)    or []
    positions = mt5.positions_get(symbol=SYMBOL) or []
    return any(o.magic == MAGIC_NUMBER for o in orders) or \
           any(p.magic == MAGIC_NUMBER for p in positions)

def _send_retry(req: dict, retries: int = 3):
    for i in range(1, retries + 1):
        res = mt5.order_send(req)
        if res is None:
            log.warning(f"order_send None (try {i})"); time.sleep(0.5); continue
        if res.retcode == mt5.TRADE_RETCODE_DONE: return res
        if res.retcode in (mt5.TRADE_RETCODE_REQUOTE, mt5.TRADE_RETCODE_PRICE_CHANGED,
                           mt5.TRADE_RETCODE_CONNECTION, mt5.TRADE_RETCODE_TIMEOUT):
            log.warning(f"Retry retcode:{res.retcode} (try {i})"); time.sleep(0.5 * i); continue
        log.error(f"❌ retcode:{res.retcode} | {res.comment}"); return res
    return None

def place_order(setup: SetupResult) -> bool:
    if not is_spread_ok() or not is_within_risk_limits(): return False

    # Multi-TF M1 Confirmation (ใหม่)
    if not get_m1_confirmation(setup.signal, setup.atr):
        log.info("⏳ M1 ยังไม่ confirm → รอ Intrabar")
        # ยังให้ผ่านแต่บันทึก
        setup.reasons.append("M1 skip")
    else:
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

    tp_full = entry + (risk * RR_RATIO) if sig == "BUY" else entry - (risk * RR_RATIO)
    lot_full = calculate_lot(entry, sl, setup.score)

    ok, reason = validate_order(entry, sl, tp_full, lot_full, sig)
    if not ok: log.warning(f"⚠️ Validate fail: {reason}"); return False

    # ─── Partial TP setup ───────────────────────────────────────
    # แบ่ง lot: 50% ปิดที่ 1R, 50% trail ไปที่ full TP
    info   = mt5.symbol_info(SYMBOL)
    lot_a  = round(lot_full * PARTIAL_TP_PCT / info.volume_step) * info.volume_step
    lot_b  = round((lot_full - lot_a) / info.volume_step) * info.volume_step
    lot_a  = max(info.volume_min, lot_a)
    lot_b  = max(info.volume_min, lot_b)

    tp_partial = entry + (risk * PARTIAL_TP_RR) if sig == "BUY" else entry - (risk * PARTIAL_TP_RR)

    orders_sent = []
    for lot_i, tp_i, label in [(lot_a, tp_partial, "PT"), (lot_b, tp_full, "FT")]:
        req = {
            "action": action, "symbol": SYMBOL, "volume": lot_i,
            "type": otype, "price": round(float(entry), 2),
            "sl": round(float(sl), 2), "tp": round(float(tp_i), 2),
            "deviation": 20, "magic": MAGIC_NUMBER,
            "comment": f"V6|{sig}|{label}|{setup.score}",
        }
        if action == mt5.TRADE_ACTION_PENDING:
            req["type_time"]  = mt5.ORDER_TIME_SPECIFIED
            req["expiration"] = exp

        res = _send_retry(req)
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            orders_sent.append((res, lot_i, tp_i, label))
            log.info(f"✅ {label}|{sig}|Lot:{lot_i}|Entry:{entry:.2f}|SL:{sl:.2f}|TP:{tp_i:.2f}")
        else:
            log.warning(f"⚠️ {label} order ไม่สำเร็จ")

    if orders_sent:
        mode = "MKT" if setup.use_market else "LMT"
        log.info(f"📦 {mode}|{sig}|Score:{setup.score}|LotA:{lot_a}+LotB:{lot_b}")
        db_log_setup(sig, setup.score, entry, sl, tp_full, setup.setup_hash)
        return True
    return False

# ══════════════════════════════════════════════════════════════════
# 🔧  POSITION MANAGEMENT (Partial TP + Trailing)
# ══════════════════════════════════════════════════════════════════
def _modify_sl(ticket: int, new_sl: float):
    res = mt5.order_send({
        "action":   mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "sl":       round(float(new_sl), 2),
    })
    if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
        log.warning(f"_modify_sl FAIL #{ticket} retcode:{res.retcode if res else 'None'}")

def _close_partial(pos, lot_close: float):
    """ปิด position บางส่วน"""
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None: return
    info = mt5.symbol_info(SYMBOL)
    step = info.volume_step if info else 0.01
    lot_close = round(lot_close / step) * step
    lot_close = max(info.volume_min if info else 0.01, min(lot_close, pos.volume))

    is_buy = (pos.type == mt5.ORDER_TYPE_BUY)
    close_type  = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
    close_price = tick.bid if is_buy else tick.ask

    req = {
        "action":   mt5.TRADE_ACTION_DEAL,
        "symbol":   SYMBOL,
        "volume":   lot_close,
        "type":     close_type,
        "position": pos.ticket,
        "price":    round(float(close_price), 2),
        "deviation":20,
        "magic":    MAGIC_NUMBER,
        "comment":  "V6|PartialTP",
    }
    res = _send_retry(req)
    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        log.info(f"💰 Partial Close #{pos.ticket} Lot:{lot_close:.2f} @ {close_price:.2f}")
    else:
        log.warning(f"⚠️ Partial close fail #{pos.ticket}")

def manage_positions(atr: float):
    positions = [p for p in (mt5.positions_get(symbol=SYMBOL) or []) if p.magic == MAGIC_NUMBER]
    if not positions: return

    tick = mt5.symbol_info_tick(SYMBOL)
    info = mt5.symbol_info(SYMBOL)
    if tick is None or info is None: return

    a = atr if atr > 0 else 1.0
    open_tickets = {p.ticket for p in positions}

    for pos in positions:
        entry  = pos.price_open
        sl_now = pos.sl
        tp     = pos.tp
        risk   = abs(tp - entry) / RR_RATIO if RR_RATIO > 0 else abs(entry - sl_now)
        if risk == 0: continue

        is_buy  = (pos.type == mt5.ORDER_TYPE_BUY)
        price   = tick.bid if is_buy else tick.ask
        buf     = info.point * 5
        profit_r = ((price - entry) / risk) if is_buy else ((entry - price) / risk)

        ts = get_trail_state(pos.ticket)
        partial_done = ts["partial_done"] if ts else 0

        # ── Partial TP (ใหม่) ──────────────────────────────────
        if not partial_done and profit_r >= PARTIAL_TP_RR:
            # ปิด 50% ของที่ยังเปิดอยู่
            close_lot = round(pos.volume * PARTIAL_TP_PCT / info.volume_step) * info.volume_step
            close_lot = max(info.volume_min, close_lot)
            _close_partial(pos, close_lot)
            set_partial_done(pos.ticket)
            # เลื่อน SL ขึ้น BE หลัง partial
            be_sl = (entry + buf) if is_buy else (entry - buf)
            if (is_buy and sl_now < be_sl) or (not is_buy and sl_now > be_sl):
                _modify_sl(pos.ticket, be_sl)
                log.info(f"🔒 BE after Partial #{pos.ticket} SL→{be_sl:.2f}")
            continue

        # ── Break-Even ─────────────────────────────────────────
        if profit_r >= BREAKEVEN_RR:
            be_sl = (entry + buf) if is_buy else (entry - buf)
            if (is_buy and sl_now < be_sl) or (not is_buy and sl_now > be_sl):
                _modify_sl(pos.ticket, be_sl)
                log.info(f"🔒 BE #{pos.ticket} SL→{be_sl:.2f}"); continue

        # ── Trailing Stop ──────────────────────────────────────
        if profit_r >= TRAIL_AFTER_RR:
            last_tsl = ts["last_sl"] if ts else None
            if is_buy:
                new_tsl  = price - (a * TRAIL_ATR_MULT)
                min_move = a * TRAIL_MIN_MOVE_ATR
                if new_tsl > sl_now and (last_tsl is None or new_tsl > last_tsl + min_move):
                    _modify_sl(pos.ticket, new_tsl)
                    save_trail_sl(pos.ticket, new_tsl)
                    log.info(f"📈 Trail #{pos.ticket} SL→{new_tsl:.2f}")
            else:
                new_tsl  = price + (a * TRAIL_ATR_MULT)
                min_move = a * TRAIL_MIN_MOVE_ATR
                if new_tsl < sl_now and (last_tsl is None or new_tsl < last_tsl - min_move):
                    _modify_sl(pos.ticket, new_tsl)
                    save_trail_sl(pos.ticket, new_tsl)
                    log.info(f"📉 Trail #{pos.ticket} SL→{new_tsl:.2f}")

    # Cleanup trail state ใน SQL โดยตรง (fix #5)
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
    """
    รอ candle ใหม่ โดยตรวจ broker server time จาก MT5 terminal
    แทนการใช้ local clock เพียงอย่างเดียว (fix #7)
    """
    # ดึงเวลา bar ปัจจุบันจาก broker
    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M5, 0, 1)
    if rates is not None and len(rates) > 0:
        last_bar_time = int(rates[0]['time'])
        next_bar_time = last_bar_time + (tf_min * 60)
        # เวลา broker (UTC) vs local
        now_utc = int(time.time())
        wait    = next_bar_time - now_utc + 3   # +3s buffer
        if 0 < wait <= tf_min * 60 + 10:
            log.info(f"⏳ รอ {wait:.0f}s (broker sync)")
            time.sleep(wait)
            return
    # fallback: ใช้ local time
    now     = datetime.now(bkk_tz)
    elapsed = (now.minute % tf_min) * 60 + now.second
    wait    = (tf_min * 60) - elapsed + 3
    if wait <= 0 or wait > tf_min * 60: wait = tf_min * 60 + 3
    log.info(f"⏳ รอ {wait:.0f}s (local fallback)")
    time.sleep(wait)

# ══════════════════════════════════════════════════════════════════
# 🔄  MAIN LOOP
# ══════════════════════════════════════════════════════════════════
BANNER = f"""
╔══════════════════════════════════════════════════════════════════════╗
║  🚀 AI SMC/ICT Pro Sniper — V.6 ULTRA  | {SYMBOL:<12}              ║
║  Risk:{RISK_PERCENT}% | RR:1:{RR_RATIO} | MinScore:{MIN_SCORE} | Spread≤{MAX_SPREAD_POINTS:.0f}pts        ║
║  DailyDD:{MAX_DAILY_LOSS_PCT}% | TotalDD:{MAX_TOTAL_DD_PCT}% | BE@{BREAKEVEN_RR}R | Trail@{TRAIL_AFTER_RR}R       ║
║  Intrabar:{INTRABAR_ENABLED} | PartialTP:{PARTIAL_TP_PCT*100:.0f}%@{PARTIAL_TP_RR}R | M1Confirm:{MTF_M1_CONFIRM}  ║
╚══════════════════════════════════════════════════════════════════════╝
"""

if __name__ == "__main__":
    print(BANNER)
    log.info("Bot V.6 เริ่มทำงาน")
    init_db()

    if not mt5_connect():
        log.error("❌ ไม่สามารถเชื่อมต่อ MT5"); quit()

    try:
        while True:
            cur = datetime.now(bkk_tz).strftime('%H:%M:%S')
            log.info("─" * 60)

            # 1. Connection guard
            if not ensure_alive():
                log.error("Reconnect ล้มเหลว → รอ 60s"); time.sleep(60); continue

            # 2. Risk guard
            if not is_within_risk_limits():
                log.warning(f"⛔ {cur} | DD limit → หยุดเทรด")
                data = fetch_all()
                if data["m5"] is not None:
                    manage_positions(calculate_atr(data["m5"]))
                wait_next_candle(); continue

            # 3. Session
            session = get_session()
            log.info(f"🕐 {cur} | {session}")
            if session in ("OUT_OF_SESSION", "RED_NEWS_BLOCK"):
                data = fetch_all()
                if data["m5"] is not None:
                    manage_positions(calculate_atr(data["m5"]))
                wait_next_candle(); continue

            # 4. Fetch data (M1, M5, M15, H1, D1)
            data = fetch_all()
            if data["m5"] is None:
                log.warning("M5 ไม่ได้ข้อมูล → ข้ามรอบ"); wait_next_candle(); continue

            # 5. Manage positions (Partial TP + Trailing)
            atr = calculate_atr(data["m5"])
            manage_positions(atr)

            # 6. Cleanup cooldowns
            cleanup_cooldowns()

            # 7. Active trade check
            if has_active_trade():
                log.info("💼 มี trade อยู่แล้ว → ทับมือ"); wait_next_candle(); continue

            # 8. Analyze (M5 + M15 + H1 + Liquidity)
            setup = analyze_setup(data["m5"], data["h1"], data["d1"], data["m15"])
            liq   = setup.liq_map

            # Log liquidity levels
            if liq:
                bsl_str = f"{liq.bsl_nearest:.2f}" if liq.bsl_nearest else "—"
                ssl_str = f"{liq.ssl_nearest:.2f}" if liq.ssl_nearest else "—"
                log.info(f"💧 BSL:{bsl_str} | SSL:{ssl_str} | SweptH:{liq.swept_high} | SweptL:{liq.swept_low}")

            log.info(f"📊 HTF:{setup.htf_bias} | M15:{setup.m15_struct} | ADR:{setup.adr_pct*100:.0f}%")

            if setup.signal == "WAIT":
                log.info(f"📉 WAIT → {' | '.join(setup.reasons) or 'ไม่พบ setup'}")
                wait_next_candle(); continue

            # 9. Score gate
            log.info(f"🔥 {setup.summary()}")
            if setup.score < MIN_SCORE:
                log.info(f"⚠️ Score {setup.score} < {MIN_SCORE} → ทับมือ"); wait_next_candle(); continue

            # 10. Duplicate check
            if is_on_cooldown(setup.setup_hash):
                log.info(f"🔁 Duplicate ({setup.setup_hash}) → ข้าม"); wait_next_candle(); continue

            # 11. Intrabar Trigger — รอราคาแตะ entry จริงๆ (ใหม่)
            if not setup.use_market:
                touched = wait_for_price_touch(setup)
                if not touched:
                    log.info("⏰ Intrabar: ไม่แตะ entry → ข้ามรอบ")
                    wait_next_candle(); continue
                # Re-check risk & spread หลัง wait
                if not is_within_risk_limits() or not is_spread_ok():
                    log.info("⚠️ Risk/Spread เปลี่ยนหลัง Intrabar wait → ข้าม")
                    wait_next_candle(); continue

            # 12. Execute
            if place_order(setup):
                set_cooldown(setup.setup_hash)
                log.info(f"🎯 Trade placed — cooldown set ({setup.setup_hash})")

            wait_next_candle()

    except KeyboardInterrupt:
        log.info("🛑 หยุดโดยผู้ใช้")
    except Exception as e:
        log.exception(f"💥 Unhandled: {e}")
    finally:
        # ปิด DB connection
        close_db()
        mt5.shutdown()
        log.info("MT5 disconnected. Bot V.6 offline.")
