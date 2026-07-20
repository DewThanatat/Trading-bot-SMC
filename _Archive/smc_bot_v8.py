"""
╔══════════════════════════════════════════════════════════════════════════╗
║   🚀 AI SMC/ICT Pro Sniper — V.8 PURE SMC                               ║
║                                                                          ║
║   เปลี่ยนแปลงหลักจาก V.7.1:                                             ║
║                                                                          ║
║   [V8-1] HTF Bias: ลบ EMA ทิ้ง → ใช้ BOS/CHOCH + Liquidity Sweep       ║
║          บน H1 แบบ SMC pure ไม่มี retail indicator เลย                  ║
║                                                                          ║
║   [V8-2] Score Rebalance: Sweep+FVG = A+ setup ผ่านได้เลย              ║
║          SCORE_BASE 40→55, threshold ลดลง, penalty อ่อนลง              ║
║                                                                          ║
║   [V8-3] FVG Tuning สำหรับ XAUUSD:                                      ║
║          buffer 0.3→0.6 (Touch & Go), ผ่อน momentum filter             ║
║          FVG Memory แยกตาม session (24–36 แท่ง)                         ║
║                                                                          ║
║   [V8-4] Spread Padding: SL เผื่อ spread จริง, HARD_SPREAD_BLOCK→100   ║
║          Spread สูงลด lot แทนบล็อกไม่ให้เทรด                           ║
║                                                                          ║
║   [V8-5] Real-time Position Manager: thread แยก poll ทุก 1s             ║
║          manage_positions ไม่ขึ้นกับ candle loop อีกต่อไป               ║
║                                                                          ║
║   คงไว้: SQLite/RLock/Decimal lot/Broker server time/Cache TTL          ║
║          Gate system/Liquidity mapping/FVG memory/OB/Duplicate guard    ║
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
from decimal import Decimal, ROUND_DOWN
from typing import Optional, List
import pytz

# ══════════════════════════════════════════════════════════════════
# ⚙️  CONFIGURATION
# ══════════════════════════════════════════════════════════════════
SYMBOL              = "XAUUSDm"
MAGIC_NUMBER        = 99999
RR_RATIO            = 2.5
MAX_DAILY_LOSS_PCT  = 4.0
MAX_TOTAL_DD_PCT    = 8.0
EXPIRATION_CANDLES  = 6

# [V8-4] Spread — Standard account friendly
HARD_SPREAD_BLOCK   = 100.0      # V7: 60 → ไม่ block ง่ายบน Standard
MAX_SPREAD_POINTS   = 50.0       # เริ่ม warn + ลด lot
SPREAD_LOT_PENALTY  = 0.3        # spread>50 pts → ลด lot 30%
SPREAD_SL_PADDING   = True       # เปิด SL padding ตาม spread จริง

MOMENTUM_BODY_ATR   = 1.2        # V7: 1.4 → ผ่อนลงนิด
BREAKEVEN_RR        = 1.0
TRAIL_AFTER_RR      = 2.0
TRAIL_ATR_MULT      = 1.2
TRAIL_MIN_MOVE_ATR  = 0.3
ADR_EXHAUSTED_PCT   = 0.85
SWING_PERIOD        = 5
SWING_CONFIRM_BARS  = 2
SETUP_COOLDOWN_SEC  = 180

# Partial TP
PARTIAL_TP_RR       = 1.0
PARTIAL_TP_PCT      = 0.50

# Intrabar — ใช้ MT5 native Pending Order
INTRABAR_ENABLED    = True

# [V8-3] FVG — XAUUSD tuning
FVG_BUFFER_RATIO    = 0.6        # V7: 0.3 → ขยายรับ Touch & Go
FVG_MOMENTUM_RATIO  = 0.25       # V7: 0.4 → ผ่อน momentum filter
FVG_MITIGATED_PCT   = 0.5

# [V8-3] FVG Memory แยกตาม session (แท่ง M5)
FVG_MEMORY_BARS = {
    "PRE_LONDON":    24,   # 2 ชม.
    "LONDON":        36,   # 3 ชม.
    "NY_OPEN_EARLY": 30,   # 2.5 ชม.
    "NEW_YORK":      36,   # 3 ชม.
    "DEFAULT":       30,
}

# M1 — bonus only
MTF_M1_BODY_ATR     = 0.3

# Liquidity
LIQ_SWING_PERIOD    = 10
LIQ_EQUAL_TOLERANCE = 0.0003
LIQ_MIN_CLUSTER     = 2

# [V8-1] HTF BOS — ใช้แทน EMA
HTF_SWING_PERIOD    = 8          # แท่ง H1 สำหรับหา swing
HTF_SWING_CONFIRM   = 2

# [V8-2] Score Rebalance
# หลักการ: Sweep+FVG คือ A+ Setup ควรผ่านด้วยตัวเอง
SCORE_BASE           = 55    # V7: 40 → เพิ่มให้ core setup มีน้ำหนัก
SCORE_SWEEP_AND_FVG  = 20    # V7: 15 → A+ bonus เพิ่ม
SCORE_HTF_ALIGN      = 12    # V7: 15 → ลดนิด (HTF ใหม่เป็น BOS ไม่ใช่ EMA)
SCORE_HTF_AGAINST    = -8    # V7: -10 → penalty อ่อนลง
SCORE_M15_BOS        = 8
SCORE_STRONG_CANDLE  = 10
SCORE_OB_BONUS       = 10
SCORE_OB_OVERLAP     = 5
SCORE_BOS_M5         = 7
SCORE_FVG_FRESH      = 8     # V7: 10
SCORE_FVG_STRENGTH   = 4
SCORE_LIQ_SWEPT      = 10
SCORE_LIQ_TARGET     = 10
SCORE_M1_CONFIRM     = 5
SCORE_ADR_WARN       = -8    # V7: -10 → penalty อ่อนลง
SCORE_SPREAD_WARN    = -4    # V7: -5

# [V8-2] Dynamic threshold ลดลงเพื่อให้ A+ setup ผ่าน
SCORE_THRESHOLD = {
    "LONDON":        55,   # V7: 50
    "NEW_YORK":      55,   # V7: 50
    "NY_OPEN_EARLY": 58,   # V7: 52
    "PRE_LONDON":    62,   # V7: 56
    "DEFAULT":       60,   # V7: 54
}
SCORE_PENALTY_HTF_NEUTRAL = 3    # V7: 4
SCORE_PENALTY_HIGH_ADR    = 2    # V7: 3

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

# [V8-3] Cache TTL
CACHE_TTL_LTF = 5
CACHE_TTL_HTF = 60
CACHE_TTL_D1  = 300

# [V8-5] Real-time position manager
POSITION_POLL_SEC   = 1.0    # poll ทุก 1 วินาที

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
# 💾  PERSISTENCE — RLock Singleton DB
# ══════════════════════════════════════════════════════════════════
_db_conn: Optional[sqlite3.Connection] = None
_db_lock = threading.RLock()

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
# [V8-1] HTF BIAS — Pure SMC: BOS/CHOCH + Liquidity Sweep บน H1
# ลบ EMA 50/200 ออกทั้งหมด ใช้ Market Structure แทน
# ══════════════════════════════════════════════════════════════════
@dataclass
class HTFBiasResult:
    bias:         str   = "NEUTRAL"   # BULLISH | BEARISH | NEUTRAL
    last_bos:     str   = "NONE"      # UP | DOWN | NONE
    choch_signal: str   = "NONE"      # UP | DOWN | NONE — เปลี่ยน trend
    swept_high:   Optional[float] = None
    swept_low:    Optional[float] = None
    reason:       str   = ""

def get_htf_bias_smc(df_h1: pd.DataFrame) -> HTFBiasResult:
    """
    [V8-1] HTF Bias บน H1 ด้วย Pure SMC:
    1. หา swing High/Low ที่ confirmed
    2. ตรวจ BOS: close เกิน swing เดิม = BOS ทิศนั้น
    3. ตรวจ CHOCH: BOS สวนทาง trend เดิม = เปลี่ยน bias
    4. ตรวจ Liquidity Sweep: wig เกิน swing แล้ว close กลับ
    คืน BULLISH ถ้า BOS UP ล่าสุด / BEARISH ถ้า BOS DOWN / NEUTRAL ถ้าไม่ชัด
    """
    res = HTFBiasResult()
    if df_h1 is None or len(df_h1) < HTF_SWING_PERIOD * 2 + HTF_SWING_CONFIRM + 5:
        res.reason = "H1 ข้อมูลไม่พอ"
        return res

    # สร้าง swing list ย้อนหลัง 60 แท่ง H1
    lookback = min(60, len(df_h1))
    df = df_h1.iloc[-lookback:].reset_index(drop=True)
    p  = HTF_SWING_PERIOD
    c  = HTF_SWING_CONFIRM

    sh_list: List[tuple] = []   # (index, price)
    sl_list: List[tuple] = []

    safe = df.iloc[:-(c)] if len(df) > c else df
    for i in range(p, len(safe) - p):
        wh = safe['high'].iloc[i - p: i + p + 1]
        wl = safe['low'].iloc[i - p: i + p + 1]
        if safe['high'].iloc[i] == wh.max():
            sh_list.append((i, float(safe['high'].iloc[i])))
        if safe['low'].iloc[i] == wl.min():
            sl_list.append((i, float(safe['low'].iloc[i])))

    if len(sh_list) < 2 or len(sl_list) < 2:
        res.reason = "Swing ไม่พอ"
        return res

    # ── Liquidity Sweep ตรวจบนแท่งล่าสุด ───────────────────────
    last = df.iloc[-1]
    prev_sh = sh_list[-1][1]
    prev_sl = sl_list[-1][1]

    if last['high'] > prev_sh and last['close'] < prev_sh:
        res.swept_high = prev_sh   # Sweep BSL → bearish signal
    if last['low'] < prev_sl and last['close'] > prev_sl:
        res.swept_low = prev_sl    # Sweep SSL → bullish signal

    # ── BOS Detection ────────────────────────────────────────────
    # ดู close 5 แท่งล่าสุดเทียบกับ swing ที่ผ่านมา
    recent = df.iloc[-5:]
    bos_up   = any(recent['close'] > prev_sh)
    bos_down = any(recent['close'] < prev_sl)

    # ── CHOCH: เทียบ swing structure ─────────────────────────────
    # Higher High + Higher Low = Bullish structure
    # Lower High + Lower Low   = Bearish structure
    hh = sh_list[-1][1] > sh_list[-2][1]   # Higher High
    lh = sh_list[-1][1] < sh_list[-2][1]   # Lower High
    hl = sl_list[-1][1] > sl_list[-2][1]   # Higher Low
    ll = sl_list[-1][1] < sl_list[-2][1]   # Lower Low

    bull_structure = hh and hl
    bear_structure = lh and ll

    # ── ตัดสิน Bias ──────────────────────────────────────────────
    bull_pts = 0
    bear_pts = 0

    if bos_up:         bull_pts += 2; res.last_bos = "UP"
    if bos_down:       bear_pts += 2; res.last_bos = "DOWN"
    if bull_structure: bull_pts += 2
    if bear_structure: bear_pts += 2
    if res.swept_low:  bull_pts += 1   # SSL sweep → expect bullish
    if res.swept_high: bear_pts += 1   # BSL sweep → expect bearish

    # CHOCH: ถ้า structure สวนทาง BOS
    if bos_up   and bear_structure: res.choch_signal = "UP"
    if bos_down and bull_structure: res.choch_signal = "DOWN"

    if bull_pts >= 3 and bull_pts > bear_pts:
        res.bias = "BULLISH"
        res.reason = f"BOS_UP:{bos_up}|HH:{hh}|HL:{hl}|SwL:{res.swept_low is not None}"
    elif bear_pts >= 3 and bear_pts > bull_pts:
        res.bias = "BEARISH"
        res.reason = f"BOS_DN:{bos_down}|LH:{lh}|LL:{ll}|SwH:{res.swept_high is not None}"
    else:
        res.bias = "NEUTRAL"
        res.reason = f"Bull:{bull_pts} Bear:{bear_pts} ไม่ชัดเจน"

    return res

def get_m15_structure(df_m15: pd.DataFrame) -> str:
    if df_m15 is None or len(df_m15) < 20:
        return "NEUTRAL"
    sh, sl = get_confirmed_swings(df_m15, period=3, confirm=2)
    last = df_m15.iloc[-1]
    if last['close'] > sh: return "BULLISH_BOS"
    if last['close'] < sl: return "BEARISH_BOS"
    return "NEUTRAL"

# ══════════════════════════════════════════════════════════════════
# 🧠  FVG MEMORY — [V8-3] XAUUSD tuned
# ══════════════════════════════════════════════════════════════════
@dataclass
class FVGZone:
    kind:      str
    top:       float
    bot:       float
    strength:  float
    bar_index: int
    mitigated: bool = False

def scan_fvg_memory(df: pd.DataFrame, atr: float,
                    lookback: int = 30) -> List[FVGZone]:
    """
    [V8-3] FVG สำหรับ XAUUSD:
    - FVG_MOMENTUM_RATIO ลดจาก 0.4 → 0.25 รับแท่งที่มีไส้ยาวแต่ displacement ชัด
    - min_gap ลดลงนิดเพื่อจับ gap เล็กที่ยังมีนัยสำคัญ
    """
    zones: List[FVGZone] = []
    if len(df) < lookback + 3 or atr == 0:
        return zones

    min_gap = atr * 0.12          # V7: 0.15 → ผ่อนลง
    overlap = atr * 0.30          # V7: 0.25 → ขยายนิด
    start   = max(3, len(df) - lookback)

    for i in range(start, len(df)):
        c1 = df.iloc[i - 2]
        c2 = df.iloc[i - 1]
        c3 = df.iloc[i]

        c2_range = c2['high'] - c2['low']
        c2_body  = abs(c2['close'] - c2['open'])

        # [V8-3] ผ่อน momentum filter: 0.4 → 0.25
        # ยังกรอง doji แต่ผ่านแท่งที่มี body เล็กพอสมควรแต่ range ใหญ่ (impulse ทอง)
        if c2_range > 0 and (c2_body / c2_range) < FVG_MOMENTUM_RATIO:
            continue

        # Bullish FVG
        if c3['low'] > c1['high'] - overlap:
            top = max(c3['low'], c1['high'])
            bot = min(c3['low'], c1['high'])
            gap = top - bot
            if gap >= min_gap:
                z = FVGZone("BULLISH", top, bot, gap / atr, i)
                mid = bot + gap * FVG_MITIGATED_PCT
                for j in range(i + 1, len(df)):
                    if df.iloc[j]['low'] <= mid:
                        z.mitigated = True; break
                zones.append(z)

        # Bearish FVG
        if c3['high'] < c1['low'] + overlap:
            top = c1['low']
            bot = c3['high']
            gap = top - bot
            if gap >= min_gap:
                z = FVGZone("BEARISH", top, bot, gap / atr, i)
                mid = top - gap * FVG_MITIGATED_PCT
                for j in range(i + 1, len(df)):
                    if df.iloc[j]['high'] >= mid:
                        z.mitigated = True; break
                zones.append(z)

    zones.sort(key=lambda z: z.bar_index, reverse=True)
    return zones

def get_active_fvg(zones: List[FVGZone], price: float,
                   direction: str) -> Optional[FVGZone]:
    """
    [V8-3] buffer ขยายจาก 0.3 → FVG_BUFFER_RATIO (0.6)
    ทองมักแตะขอบแล้วไป (Touch & Go) buffer เล็กทำให้ตกรถ
    """
    target_kind = "BULLISH" if direction == "BUY" else "BEARISH"
    for z in zones:
        if z.mitigated or z.kind != target_kind:
            continue
        buf = (z.top - z.bot) * FVG_BUFFER_RATIO   # [V8-3]
        if (z.bot - buf) <= price <= (z.top + buf):
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
    base = SCORE_THRESHOLD.get(session, SCORE_THRESHOLD["DEFAULT"])
    if htf_bias == "NEUTRAL":
        base += SCORE_PENALTY_HTF_NEUTRAL
    if adr_pct >= ADR_EXHAUSTED_PCT:
        base += SCORE_PENALTY_HIGH_ADR
    return base

# ══════════════════════════════════════════════════════════════════
# 📊  DATA FEED — cache TTL ตาม TF + thread-safe
# ══════════════════════════════════════════════════════════════════
_cache: dict = {}
_cache_lock  = threading.Lock()

def _get_cache_ttl(tf: int) -> float:
    if tf in (mt5.TIMEFRAME_M1, mt5.TIMEFRAME_M5):
        return CACHE_TTL_LTF
    elif tf == mt5.TIMEFRAME_D1:
        return CACHE_TTL_D1
    return CACHE_TTL_HTF

def fetch(tf: int, n: int, use_cache: bool = True) -> Optional[pd.DataFrame]:
    now = time.time()
    with _cache_lock:
        if use_cache and tf in _cache and now - _cache[tf][0] < _get_cache_ttl(tf):
            return _cache[tf][1]
    rates = mt5.copy_rates_from_pos(SYMBOL, tf, 0, n)
    if rates is None or len(rates) == 0:
        log.warning(f"fetch: ไม่ได้ข้อมูล tf={tf}")
        return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    with _cache_lock:
        _cache[tf] = (now, df)
    return df

def fetch_all() -> dict:
    """M1/M5 live, M15/H1 cache 60s, D1 cache 5m"""
    m1  = fetch(mt5.TIMEFRAME_M1,    60, use_cache=False)
    m5  = fetch(mt5.TIMEFRAME_M5,   300, use_cache=False)   # เพิ่มเป็น 300 รับ FVG 36 แท่ง+buffer
    m15 = fetch(mt5.TIMEFRAME_M15,  100, use_cache=True)
    h1  = fetch(mt5.TIMEFRAME_H1,   220, use_cache=True)
    d1  = fetch(mt5.TIMEFRAME_D1,    20, use_cache=True)
    return {
        "m1":  m1.iloc[:-1].copy()  if m1  is not None else None,
        "m5":  m5.iloc[:-1].copy()  if m5  is not None else None,
        "m15": m15.iloc[:-1].copy() if m15 is not None else None,
        "h1":  h1.iloc[:-1].copy()  if h1  is not None else None,
        "d1":  d1                   if d1  is not None else None,
    }

# ══════════════════════════════════════════════════════════════════
# 🎯  SIGNAL ENGINE V.8 — Gate System
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
    threshold:  int   = 60
    reasons:    list  = field(default_factory=list)
    setup_hash: str   = ""
    use_market: bool  = False
    liq_map:    Optional[LiquidityMap] = None
    fvg_zone:   Optional[FVGZone]      = None
    candle_ts:  float = 0.0
    htf_result: Optional[HTFBiasResult] = None

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

    if df_m5 is None or len(df_m5) < 30:
        r.reasons.append("ข้อมูล M5 ไม่พอ"); return r

    atr = calculate_atr(df_m5)
    if atr == 0:
        r.reasons.append("ATR=0"); return r
    r.atr = atr

    adr = calculate_adr(df_d1)
    if adr > 0 and df_d1 is not None and len(df_d1) >= 1:
        r.adr_pct = (df_d1['high'].iloc[-1] - df_d1['low'].iloc[-1]) / adr

    # [V8-1] HTF Bias ด้วย Pure SMC BOS/CHOCH
    htf_res      = get_htf_bias_smc(df_h1)
    r.htf_bias   = htf_res.bias
    r.htf_result = htf_res
    r.m15_struct = get_m15_structure(df_m15)
    r.threshold  = get_dynamic_threshold(session, r.htf_bias, r.adr_pct)

    liq       = build_liquidity_map(df_m5, atr, LIQ_SWING_PERIOD)
    r.liq_map = liq
    last_sh, last_sl = get_confirmed_swings(df_m5, SWING_PERIOD, SWING_CONFIRM_BARS)

    # [V8-3] FVG lookback ตาม session
    fvg_lookback = (FVG_MEMORY_BARS.get(session, FVG_MEMORY_BARS["DEFAULT"])
                    if isinstance(FVG_MEMORY_BARS, dict) else FVG_MEMORY_BARS)
    fvg_zones = scan_fvg_memory(df_m5, atr, fvg_lookback)

    last = df_m5.iloc[-1]
    prev = df_m5.iloc[-2]
    r.candle_ts = (float(last['time'].timestamp())
                   if hasattr(last['time'], 'timestamp') else time.time())

    price      = float(last['close'])
    sweep_sell = last['low'] < last_sl  and last['close'] > last_sl
    sweep_buy  = last['high'] > last_sh and last['close'] < last_sh

    def _build_buy():
        has_sweep  = sweep_sell
        fvg_active = get_active_fvg(fvg_zones, price, "BUY")
        if not has_sweep and fvg_active is None:
            return False

        r.signal = "BUY"
        r.score  = SCORE_BASE    # [V8-2] 55

        if fvg_active is not None:
            r.entry    = fvg_active.top
            r.fvg_zone = fvg_active
        elif has_sweep:
            r.entry = last_sl + (atr * 0.1)
        r.sl = last_sl - (atr * 0.5)

        # Gate 2 bonus
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

        # [V8-1] HTF SMC bias scoring
        if r.htf_bias == "BULLISH":
            r.score += SCORE_HTF_ALIGN
            choch_tag = "(CHOCH)" if htf_res.choch_signal == "UP" else ""
            r.reasons.append(f"HTF Bull{choch_tag} ✓")
        elif r.htf_bias == "BEARISH":
            r.score += SCORE_HTF_AGAINST
            r.reasons.append("HTF Bear ⚠️")
        # SSL sweep บน H1 เสริม bull signal
        if htf_res.swept_low is not None:
            r.score += 4
            r.reasons.append(f"H1 SSL Swept ✓")

        if r.m15_struct == "BULLISH_BOS":
            r.score += SCORE_M15_BOS; r.reasons.append("M15 BOS ✓")

        body = last['close'] - last['open']
        if body > atr * 0.6:
            r.score += SCORE_STRONG_CANDLE; r.reasons.append("Strong ✓")

        ob = find_order_block(df_m5, "BUY", atr)
        if ob.found:
            r.score += int(SCORE_OB_BONUS * ob.score)
            r.reasons.append(f"OB(q:{ob.score:.2f}) ✓")
            if ob.low <= r.entry <= ob.high:
                r.score += SCORE_OB_OVERLAP
                r.reasons.append("OB Overlap ✓")

        if last['close'] > prev['high']:
            r.score += SCORE_BOS_M5; r.reasons.append("BOS ✓")

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
            r.entry = last_sh - (atr * 0.1)
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
            r.score += SCORE_HTF_ALIGN
            choch_tag = "(CHOCH)" if htf_res.choch_signal == "DOWN" else ""
            r.reasons.append(f"HTF Bear{choch_tag} ✓")
        elif r.htf_bias == "BULLISH":
            r.score += SCORE_HTF_AGAINST
            r.reasons.append("HTF Bull ⚠️")
        if htf_res.swept_high is not None:
            r.score += 4
            r.reasons.append(f"H1 BSL Swept ✓")

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

    if not _build_buy():
        r.signal = "WAIT"; r.score = 0; r.reasons = []
        if not _build_sell():
            return r

    if r.signal != "WAIT":
        entry_h = r.entry if not r.use_market else -1.0
        r.setup_hash = _make_hash(r.signal, entry_h, r.sl, r.candle_ts)

    return r

# ══════════════════════════════════════════════════════════════════
# 💰  RISK ENGINE
# [V8-4] Spread Padding + Lot reduction แทนการ block
# ══════════════════════════════════════════════════════════════════
def get_broker_server_date() -> str:
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is not None:
        server_dt = datetime.fromtimestamp(tick.time, tz=pytz.utc)
        return server_dt.strftime("%Y%m%d")
    return datetime.utcnow().strftime("%Y%m%d")

def get_spread_pts() -> float:
    tick = mt5.symbol_info_tick(SYMBOL)
    info = mt5.symbol_info(SYMBOL)
    if tick is None or info is None: return 999.0
    return (tick.ask - tick.bid) / info.point

def is_spread_ok() -> bool:
    sp = get_spread_pts()
    if sp > HARD_SPREAD_BLOCK:
        log.warning(f"⛔ Spread {sp:.1f}pts > HARD_BLOCK {HARD_SPREAD_BLOCK}"); return False
    return True

def get_spread_sl_padding() -> float:
    """
    [V8-4] คำนวณ padding เพิ่มให้ SL ตาม spread จริง
    Standard account: spread อาจ 30-60 pts → SL ต้องถอยออกเพิ่มเท่ากับ spread
    ป้องกัน spread แกว่งกิน SL โดยไม่ตั้งใจ
    """
    if not SPREAD_SL_PADDING: return 0.0
    tick = mt5.symbol_info_tick(SYMBOL)
    info = mt5.symbol_info(SYMBOL)
    if tick is None or info is None: return 0.0
    sp_pts = (tick.ask - tick.bid) / info.point
    # padding = 100% spread (ป้องกัน requote + noise)
    return sp_pts * info.point

def is_within_risk_limits() -> bool:
    acct = mt5.account_info()
    if acct is None: return True
    equity  = acct.equity
    balance = acct.balance

    today_key   = "daily_start_balance_" + get_broker_server_date()
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

def _round_lot(lot: float, step: float) -> float:
    d_lot  = Decimal(str(lot))
    d_step = Decimal(str(step))
    rounded = (d_lot / d_step).to_integral_value(rounding=ROUND_DOWN) * d_step
    return float(rounded)

def calculate_lot(entry: float, sl: float, score: int = 0,
                  spread_pts: float = 0.0) -> float:
    """
    [V8-4] ถ้า spread > MAX_SPREAD_POINTS ลด lot ลง SPREAD_LOT_PENALTY
    แทนการ block ไม่ให้เทรดเลย — ยังได้เทรดแต่ size เล็กลงเพื่อชดเชย cost
    """
    info = mt5.symbol_info(SYMBOL)
    if info is None: return LOT_MIN
    raw_lot = LOT_MIN
    for score_min, tier_lot in LOT_TIERS:
        if score >= score_min:
            raw_lot = tier_lot; break

    # [V8-4] Spread lot penalty
    if spread_pts > MAX_SPREAD_POINTS:
        raw_lot = raw_lot * (1.0 - SPREAD_LOT_PENALTY)
        log.info(f"📉 Spread {spread_pts:.0f}pts → lot ลด {SPREAD_LOT_PENALTY*100:.0f}%")

    step = info.volume_step if info.volume_step > 0 else 0.01
    lot  = _round_lot(raw_lot, step)
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

    d_lot  = Decimal(str(lot))
    d_step = Decimal(str(info.volume_step))
    rem    = d_lot % d_step
    if rem > Decimal("1e-8"): return False, "Lot step ผิด"

    order_type = mt5.ORDER_TYPE_BUY if signal == "BUY" else mt5.ORDER_TYPE_SELL
    margin_req = mt5.order_calc_margin(order_type, SYMBOL, lot, entry)
    if margin_req is None or margin_req > acct.margin_free * 0.9:
        return False, "Margin ไม่พอ"
    return True, "OK"

def has_duplicate_setup(setup_hash: str, signal: str) -> bool:
    positions = mt5.positions_get(symbol=SYMBOL) or []
    for p in positions:
        if p.magic != MAGIC_NUMBER: continue
        if setup_hash in (p.comment or ""):
            return True
    orders = mt5.orders_get(symbol=SYMBOL) or []
    for o in orders:
        if o.magic != MAGIC_NUMBER: continue
        if setup_hash in (o.comment or ""):
            return True
    return False

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
# 📤  PLACE ORDER — [V8-4] SL padding ตาม spread
# ══════════════════════════════════════════════════════════════════
def place_order(setup: SetupResult, session: str = "") -> bool:
    if not is_spread_ok() or not is_within_risk_limits(): return False
    if has_duplicate_setup(setup.setup_hash, setup.signal):
        log.info(f"🚫 Duplicate {setup.setup_hash} → ข้าม"); return False

    sp = get_spread_pts()
    sl_pad = get_spread_sl_padding()   # [V8-4]

    if sp > MAX_SPREAD_POINTS:
        setup.score += SCORE_SPREAD_WARN
        setup.reasons.append(f"Spread{sp:.0f}pts ⚠️")

    # M1 confirm bonus
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

    sig = setup.signal
    # [V8-4] เพิ่ม SL padding เท่ากับ spread จริง
    sl_raw = setup.sl
    if setup.signal == "BUY":
        sl_adjusted = sl_raw - sl_pad   # ขยาย SL ลงอีกเท่าไส้ spread
    else:
        sl_adjusted = sl_raw + sl_pad   # ขยาย SL ขึ้นอีกเท่าไส้ spread
    log.info(f"📏 SL Padding: {sl_raw:.2f} → {sl_adjusted:.2f} (spread={sp:.1f}pts)")

    if setup.use_market or not INTRABAR_ENABLED:
        entry  = tick.ask if sig == "BUY" else tick.bid
        otype  = mt5.ORDER_TYPE_BUY  if sig == "BUY" else mt5.ORDER_TYPE_SELL
        action = mt5.TRADE_ACTION_DEAL; exp = 0
    else:
        entry  = setup.entry
        otype  = mt5.ORDER_TYPE_BUY_LIMIT if sig == "BUY" else mt5.ORDER_TYPE_SELL_LIMIT
        action = mt5.TRADE_ACTION_PENDING
        exp    = int(time.time()) + (EXPIRATION_CANDLES * 5 * 60)
        if sig == "BUY"  and entry >= tick.ask:
            entry = tick.ask; otype = mt5.ORDER_TYPE_BUY
            action = mt5.TRADE_ACTION_DEAL; exp = 0
        elif sig == "SELL" and entry <= tick.bid:
            entry = tick.bid; otype = mt5.ORDER_TYPE_SELL
            action = mt5.TRADE_ACTION_DEAL; exp = 0

    risk = abs(entry - sl_adjusted)
    if risk == 0: log.error("place_order: risk=0"); return False

    tp_full  = (entry + risk * RR_RATIO if sig == "BUY"
                else entry - risk * RR_RATIO)
    lot_full = calculate_lot(entry, sl_adjusted, setup.score, sp)   # [V8-4] ส่ง spread
    ok, reason = validate_order(entry, sl_adjusted, tp_full, lot_full, sig)
    if not ok: log.warning(f"⚠️ Validate: {reason}"); return False

    info   = mt5.symbol_info(SYMBOL)
    v_step = info.volume_step if info else 0.01
    v_min  = info.volume_min  if info else 0.01
    lot_a  = max(v_min, _round_lot(lot_full * PARTIAL_TP_PCT, v_step))
    lot_b  = max(v_min, _round_lot(lot_full - lot_a, v_step))
    if lot_a + lot_b > lot_full + v_step:
        lot_b = max(v_min, _round_lot(lot_full - lot_a, v_step))
    tp_pt  = (entry + risk * PARTIAL_TP_RR if sig == "BUY"
              else entry - risk * PARTIAL_TP_RR)

    sent = 0
    for lot_i, tp_i, label in [(lot_a, tp_pt, "PT"), (lot_b, tp_full, "FT")]:
        req = {
            "action":    action, "symbol": SYMBOL, "volume": lot_i,
            "type":      otype,  "price":  round(float(entry), 2),
            "sl":        round(float(sl_adjusted), 2),
            "tp":        round(float(tp_i), 2),
            "deviation": 20, "magic": MAGIC_NUMBER,
            "comment":   f"V8|{sig}|{label}|{setup.score}|{setup.setup_hash}",
        }
        if action == mt5.TRADE_ACTION_PENDING:
            req["type_time"]  = mt5.ORDER_TIME_SPECIFIED
            req["expiration"] = exp

        res = _send_retry(req)
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            sent += 1
            mode_tag = "MKT" if action == mt5.TRADE_ACTION_DEAL else "LMT"
            log.info(f"✅ {label}|{sig}|{mode_tag}|Lot:{lot_i}|"
                     f"E:{entry:.2f}|SL:{sl_adjusted:.2f}|TP:{tp_i:.2f}")
        else:
            log.warning(f"⚠️ {label} ไม่สำเร็จ")

    if sent > 0:
        mode = "MKT" if action == mt5.TRADE_ACTION_DEAL else "LMT"
        log.info(f"📦 {mode}|{sig}|Score:{setup.score}|Lot:{lot_a}+{lot_b}|{session}")
        db_log_setup(sig, setup.score, entry, sl_adjusted, tp_full,
                     setup.setup_hash, session)
        return True
    return False

# ══════════════════════════════════════════════════════════════════
# 🔧  POSITION MANAGEMENT — logic เดิม V.7.1 คงไว้
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
    lot_close = max(v_min, min(_round_lot(lot_close, step), pos.volume))
    is_buy      = (pos.type == mt5.ORDER_TYPE_BUY)
    close_type  = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
    close_price = tick.bid if is_buy else tick.ask
    res = _send_retry({
        "action":    mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL,
        "volume":    lot_close, "type": close_type,
        "position":  pos.ticket,
        "price":     round(float(close_price), 2),
        "deviation": 20, "magic": MAGIC_NUMBER,
        "comment":   "V8|PartialTP",
    })
    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        log.info(f"💰 Partial #{pos.ticket} Lot:{lot_close:.2f} @ {close_price:.2f}")

def manage_positions(atr: float):
    """ใช้ risk จาก SL จริง (V7.1 fix คงไว้)"""
    positions = [p for p in (mt5.positions_get(symbol=SYMBOL) or [])
                 if p.magic == MAGIC_NUMBER]
    if not positions: return

    tick = mt5.symbol_info_tick(SYMBOL)
    info = mt5.symbol_info(SYMBOL)
    if tick is None or info is None: return

    a = atr if atr > 0 else 1.0
    open_tickets = {p.ticket for p in positions}

    for pos in positions:
        entry  = pos.price_open
        sl_now = pos.sl
        is_buy = (pos.type == mt5.ORDER_TYPE_BUY)

        risk = abs(entry - sl_now)
        if risk == 0:
            risk = a * 1.5

        price    = tick.bid if is_buy else tick.ask
        buf      = info.point * 5
        profit_r = ((price - entry) / risk if is_buy
                    else (entry - price) / risk)

        ts           = get_trail_state(pos.ticket)
        partial_done = ts["partial_done"] if ts else 0

        if not partial_done and profit_r >= PARTIAL_TP_RR:
            _close_partial(pos, pos.volume * PARTIAL_TP_PCT)
            set_partial_done(pos.ticket)
            be_sl = (entry + buf) if is_buy else (entry - buf)
            if (is_buy and sl_now < be_sl) or (not is_buy and sl_now > be_sl):
                _modify_sl(pos.ticket, be_sl)
                log.info(f"🔒 BE+Partial #{pos.ticket} SL→{be_sl:.2f}")
            continue

        if profit_r >= BREAKEVEN_RR:
            be_sl = (entry + buf) if is_buy else (entry - buf)
            if (is_buy and sl_now < be_sl) or (not is_buy and sl_now > be_sl):
                _modify_sl(pos.ticket, be_sl)
                log.info(f"🔒 BE #{pos.ticket} SL→{be_sl:.2f}"); continue

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
# [V8-5] REAL-TIME POSITION MANAGER THREAD
# ██ หัวใจของ V8-5: thread แยกที่ poll ทุก POSITION_POLL_SEC
# ██ manage_positions() ทำงานทุก 1 วินาที โดยไม่ขึ้นกับ candle loop
# ██ ทำให้ Trailing SL / BE / Partial TP ตอบสนอง real-time
# ══════════════════════════════════════════════════════════════════
_pm_running = threading.Event()
_pm_running.set()

def _position_manager_thread():
    """
    [V8-5] Background thread: จัดการ position ทุก 1 วินาที
    - ไม่ block candle loop
    - Trailing SL และ Partial TP ตอบสนองทัน ไม่รอแท่งถัดไป
    - ถ้า MT5 หลุด → sleep รอ reconnect
    """
    log.info("🔄 Position Manager Thread เริ่มทำงาน")
    while _pm_running.is_set():
        try:
            if mt5.terminal_info() is not None:
                # ดึง ATR จาก M5 cache (ไม่ fetch ใหม่ทุกครั้ง)
                with _cache_lock:
                    cached = _cache.get(mt5.TIMEFRAME_M5)
                if cached:
                    _, df_m5c = cached
                    atr = calculate_atr(df_m5c)
                else:
                    atr = 1.0
                manage_positions(atr)
        except Exception as e:
            log.warning(f"⚠️ PM Thread error: {e}")
        time.sleep(POSITION_POLL_SEC)
    log.info("🔄 Position Manager Thread หยุด")

def start_position_manager():
    t = threading.Thread(target=_position_manager_thread,
                         name="PositionManager", daemon=True)
    t.start()
    return t

def stop_position_manager():
    _pm_running.clear()

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
    [V8-5] wait_next_candle ยังคงรอแท่งถัดไปสำหรับ signal detection
    แต่ manage_positions ย้ายไปอยู่ใน PM thread แล้ว ไม่ต้องกังวล
    """
    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M5, 0, 1)
    if rates is not None and len(rates) > 0:
        next_bar = int(rates[0]['time']) + (tf_min * 60)
        wait     = next_bar - int(time.time()) + 3
        if 0 < wait <= tf_min * 60 + 10:
            log.info(f"⏳ รอ {wait:.0f}s (PM thread ทำงานอยู่ระหว่างนี้)")
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
║  🚀 AI SMC/ICT Pro Sniper — V.8 PURE SMC                                ║
║  HTF: BOS/CHOCH/Sweep (no EMA) | FVG: XAUUSD tuned                     ║
║  Score rebalanced | Spread padding | Real-time PM thread                ║
║  Gate1:Hard | Gate2:Sweep OR FVG | Gate3:Dynamic Score                  ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

if __name__ == "__main__":
    print(BANNER)
    log.info("Bot V.8 PURE SMC เริ่มทำงาน")
    init_db()

    if not mt5_connect():
        log.error("❌ ไม่สามารถเชื่อมต่อ MT5"); quit()

    # [V8-5] เริ่ม Position Manager thread แยก
    pm_thread = start_position_manager()

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
                log.warning(f"⛔ {cur} | DD limit → หยุดเทรดวันนี้")
                wait_next_candle(); continue

            # GATE 1c — Session
            session = get_session()
            log.info(f"🕐 {cur} | {session}")
            if session in ("OUT_OF_SESSION", "RED_NEWS_BLOCK"):
                wait_next_candle(); continue

            # GATE 1d — Hard Spread
            if not is_spread_ok():
                log.warning("⚠️ Spread เกิน HARD_BLOCK → รอ")
                wait_next_candle(); continue

            # Fetch ข้อมูล
            data = fetch_all()
            if data["m5"] is None:
                log.warning("M5 ไม่ได้ข้อมูล → ข้ามรอบ")
                wait_next_candle(); continue

            cleanup_cooldowns()

            # GATE 2+3 — Signal + Score
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

            htf = setup.htf_result
            if htf:
                log.info(f"🏗️  HTF SMC | Bias:{htf.bias} | BOS:{htf.last_bos} | "
                         f"CHOCH:{htf.choch_signal} | {htf.reason}")

            log.info(f"📊 M15:{setup.m15_struct} | "
                     f"ADR:{setup.adr_pct*100:.0f}% | "
                     f"Threshold:{setup.threshold}")

            if setup.signal == "WAIT":
                log.info(f"📉 WAIT → {' | '.join(setup.reasons) or 'ไม่พบ setup'}")
                wait_next_candle(); continue

            log.info(f"🔥 {setup.summary()}")

            # GATE 3 — Score
            if setup.score < setup.threshold:
                log.info(f"⚠️ Score {setup.score} < {setup.threshold} → ข้าม")
                wait_next_candle(); continue

            # Cooldown
            if is_on_cooldown(setup.setup_hash):
                log.info(f"🔁 Cooldown ({setup.setup_hash}) → ข้าม")
                wait_next_candle(); continue

            # Duplicate guard
            if has_duplicate_setup(setup.setup_hash, setup.signal):
                log.info(f"🚫 Dup {setup.setup_hash} → ข้าม")
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
        stop_position_manager()
        pm_thread.join(timeout=3)
        close_db()
        mt5.shutdown()
        log.info("MT5 offline. Bot V.8 bye.")
