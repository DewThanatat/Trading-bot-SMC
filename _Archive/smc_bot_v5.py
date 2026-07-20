import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import sqlite3
import json
import time
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, time as dtime
from typing import Optional
import pytz

# ══════════════════════════════════════════════════════════════════
# ⚙️  CONFIGURATION  (แก้ค่าที่นี่)
# ══════════════════════════════════════════════════════════════════
SYMBOL             = "XAUUSDm"
MAGIC_NUMBER       = 99999
RISK_PERCENT       = 1.0       # % ของ Balance ต่อไม้
RR_RATIO           = 2.5
MAX_DAILY_LOSS_PCT = 4.0       # % equity drawdown / วัน (Prop Firm)
MAX_TOTAL_DD_PCT   = 8.0       # % total max drawdown
MIN_SCORE          = 55        # ลด threshold → ออกไม้ถี่ขึ้น
EXPIRATION_CANDLES = 6         # แท่ง M5 ก่อน Pending หมดอายุ
MAX_SPREAD_POINTS  = 40.0      # spread สูงสุดที่ยอมรับ (point)
MOMENTUM_BODY_ATR  = 1.4       # body > ATR*mult → Market order mode
BREAKEVEN_RR       = 1.0
TRAIL_AFTER_RR     = 2.0
TRAIL_ATR_MULT     = 1.2
TRAIL_MIN_MOVE_ATR = 0.3
ADR_EXHAUSTED_PCT  = 0.85      # warn เมื่อ > 85% (ไม่ block)
SWING_PERIOD       = 5
SWING_CONFIRM_BARS = 2
SETUP_COOLDOWN_SEC = 300
DB_PATH            = "smc_state.db"
LOG_PATH           = "smc_bot.log"

# Scoring weights
SCORE_BASE         = 40
SCORE_HTF_ALIGN    = 15
SCORE_HTF_AGAINST  = -10
SCORE_STRONG_CANDLE= 15
SCORE_OB_ZONE      = 15
SCORE_BOS          = 10
SCORE_ADR_WARN     = -10

# Sessions (Bangkok time) — wider than before
SESSIONS = [
    (12,  0,  14,  0, "PRE_LONDON"),
    (14,  0,  18,  0, "LONDON"),
    (18, 30,  19, 15, "NY_OPEN_EARLY"),
    (19, 45,  23, 59, "NEW_YORK"),
]
NEWS_BLOCKS = [(19, 15, 19, 45)]   # Hard block ช่วงข่าว

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
# 💾  PERSISTENCE  (SQLite)
# ══════════════════════════════════════════════════════════════════
def _db() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with _db() as c:
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
            ticket INTEGER PRIMARY KEY, last_sl REAL, updated_at REAL
        );
        CREATE TABLE IF NOT EXISTS bot_state (
            key TEXT PRIMARY KEY, value TEXT
        );
        """)

def is_on_cooldown(h: str) -> bool:
    with _db() as c:
        row = c.execute("SELECT expires_at FROM cooldown WHERE setup_hash=?", (h,)).fetchone()
    return bool(row and row["expires_at"] > time.time())

def set_cooldown(h: str):
    with _db() as c:
        c.execute("INSERT OR REPLACE INTO cooldown VALUES(?,?)", (h, time.time() + SETUP_COOLDOWN_SEC))

def cleanup_cooldowns():
    with _db() as c:
        c.execute("DELETE FROM cooldown WHERE expires_at<=?", (time.time(),))

def db_log_setup(signal, score, entry, sl, tp, h):
    with _db() as c:
        c.execute("INSERT INTO setup_log(ts,signal,score,entry,sl,tp,setup_hash) VALUES(?,?,?,?,?,?,?)",
                  (time.time(), signal, score, entry, sl, tp, h))

def get_trail_sl(ticket: int):
    with _db() as c:
        row = c.execute("SELECT last_sl FROM trail_state WHERE ticket=?", (ticket,)).fetchone()
    return float(row["last_sl"]) if row else None

def save_trail_sl(ticket: int, sl: float):
    with _db() as c:
        c.execute("INSERT OR REPLACE INTO trail_state VALUES(?,?,?)", (ticket, sl, time.time()))

def remove_trail_sl(ticket: int):
    with _db() as c:
        c.execute("DELETE FROM trail_state WHERE ticket=?", (ticket,))

def get_state(key: str, default=None):
    with _db() as c:
        row = c.execute("SELECT value FROM bot_state WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default

def set_state(key: str, value):
    with _db() as c:
        c.execute("INSERT OR REPLACE INTO bot_state VALUES(?,?)", (key, json.dumps(value)))

# ══════════════════════════════════════════════════════════════════
# 📐  INDICATORS
# ══════════════════════════════════════════════════════════════════
def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """True Range ATR — รวม gap ข้ามคืน"""
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
    """
    Confirmed Swing — ไม่มี look-ahead / repaint
    ตัด `confirm` แท่งขวาออกก่อนหา pivot
    """
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

@dataclass
class FVGResult:
    kind: str = "NONE"
    top:  float = 0.0
    bot:  float = 0.0
    strength: float = 0.0

def check_fvg(df: pd.DataFrame, atr: float) -> FVGResult:
    """
    FVG แบบผ่อน — อนุญาต overlap เล็กน้อย + ต้อง body dominance
    Caller ต้องส่ง df ที่ตัด live candle ออกแล้ว
    """
    if len(df) < 3 or atr == 0:
        return FVGResult()
    c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    # Body dominance on middle candle
    c2_range = c2['high'] - c2['low']
    c2_body  = abs(c2['close'] - c2['open'])
    if c2_range > 0 and (c2_body / c2_range) < 0.4:
        return FVGResult()
    min_gap = atr * 0.15
    overlap = atr * 0.25
    # Bullish FVG
    if c3['low'] > c1['high'] - overlap:
        top = c3['low']; bot = c1['high']
        if top < bot: top, bot = bot, top
        if (top - bot) >= min_gap:
            return FVGResult("BULLISH", top, bot, (top - bot) / atr)
    # Bearish FVG
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
    """
    ICT Order Block:
    1. OB candle (opposite color)
    2. Displacement ≥ ATR*1.2
    3. Break of Structure after displacement
    4. Liquidity sweep context
    """
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
            if ob['close'] >= ob['open']: continue   # ต้องเป็น bearish candle
            if imp['close'] <= imp['open']: continue  # impulse ต้องเป็น bullish
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
    """HTF Bias — ใช้เป็น soft score ไม่ใช่ hard filter"""
    if df_h1 is None or len(df_h1) < 210:
        return "NEUTRAL"
    ema50  = df_h1['close'].ewm(span=50,  adjust=False).mean()
    ema200 = df_h1['close'].ewm(span=200, adjust=False).mean()
    p  = float(df_h1['close'].iloc[-1])
    e50  = float(ema50.iloc[-1])
    e200 = float(ema200.iloc[-1])
    bull = (1 if e50 > e200 else 0) + (1 if p > e50 else 0) + (1 if p > e200 else 0)
    bear = (1 if e50 < e200 else 0) + (1 if p < e50 else 0) + (1 if p < e200 else 0)
    if bull >= 3: return "BULLISH"
    if bear >= 3: return "BEARISH"
    return "NEUTRAL"

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
# 📊  DATA FEED  (with cache)
# ══════════════════════════════════════════════════════════════════
_cache: dict = {}
CACHE_TTL = 20

def fetch(tf: int, n: int, use_cache: bool = True) -> pd.DataFrame | None:
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
    m5 = fetch(mt5.TIMEFRAME_M5, 200, False)
    h1 = fetch(mt5.TIMEFRAME_H1, 220, False)
    d1 = fetch(mt5.TIMEFRAME_D1,  20, False)
    return {
        "m5":  m5.iloc[:-1].copy() if m5 is not None else None,
        "h1":  h1.iloc[:-1].copy() if h1 is not None else None,
        "d1":  d1              if d1 is not None else None,
        "m5_raw": m5,
    }

# ══════════════════════════════════════════════════════════════════
# 🎯  SIGNAL ENGINE
# ══════════════════════════════════════════════════════════════════
@dataclass
class SetupResult:
    signal:     str   = "WAIT"
    score:      int   = 0
    entry:      float = 0.0
    sl:         float = 0.0
    atr:        float = 0.0
    htf_bias:   str   = "NEUTRAL"
    adr_pct:    float = 0.0
    reasons:    list  = field(default_factory=list)
    setup_hash: str   = ""
    use_market: bool  = False

    def summary(self) -> str:
        mode = "MKT" if self.use_market else "LMT"
        return f"{self.signal}({mode}) Score:{self.score} | {' | '.join(self.reasons)}"

def _make_hash(sig: str, entry: float, sl: float) -> str:
    return hashlib.md5(f"{sig}:{entry:.2f}:{sl:.2f}".encode()).hexdigest()[:10]

def analyze_setup(df_m5, df_h1, df_d1) -> SetupResult:
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
    
    # HTF Bias (soft)
    r.htf_bias = get_htf_bias(df_h1)

    # Swing (confirmed, no repaint)
    last_sh, last_sl = get_confirmed_swings(df_m5, SWING_PERIOD, SWING_CONFIRM_BARS)

    # FVG
    fvg = check_fvg(df_m5, atr)

    last = df_m5.iloc[-1]
    prev = df_m5.iloc[-2]

    sweep_sell = (last['low'] < last_sl)  and (last['close'] > last_sl)
    sweep_buy  = (last['high'] > last_sh) and (last['close'] < last_sh)

    # ── BUY ──────────────────────────────────────────────────────
    if sweep_sell and fvg.kind == "BULLISH":
        r.signal = "BUY"
        r.entry  = fvg.top
        r.sl     = last_sl - (atr * 0.5)
        r.score  = SCORE_BASE
        r.reasons.append("Sweep Sell ✓")
        r.reasons.append(f"BFVG(s:{fvg.strength:.2f}) ✓")

        # HTF soft scoring
        if r.htf_bias == "BULLISH":
            r.score += SCORE_HTF_ALIGN;   r.reasons.append("HTF Bull ✓")
        elif r.htf_bias == "BEARISH":
            r.score += SCORE_HTF_AGAINST; r.reasons.append("HTF Bear ⚠️")

        body = last['close'] - last['open']
        if body > atr * 0.7:
            r.score += SCORE_STRONG_CANDLE; r.reasons.append("Strong ✓")

        ob = find_order_block(df_m5, "BUY", atr)
        if ob.found and ob.low <= r.entry <= ob.high:
            bonus = int(SCORE_OB_ZONE * ob.score)
            r.score += bonus; r.reasons.append(f"OB(q:{ob.score:.2f}) ✓")

        if last['close'] > prev['high']:
            r.score += SCORE_BOS; r.reasons.append("BOS ✓")

        if r.adr_pct >= ADR_EXHAUSTED_PCT:
            r.score += SCORE_ADR_WARN; r.reasons.append(f"ADR{r.adr_pct*100:.0f}% ⚠️")

        if fvg.strength > 0.5:
            r.score += 5; r.reasons.append("FVG+ ✓")

        # Momentum Market mode
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
        r.reasons.append("Sweep Buy ✓")
        r.reasons.append(f"SFVG(s:{fvg.strength:.2f}) ✓")

        if r.htf_bias == "BEARISH":
            r.score += SCORE_HTF_ALIGN;   r.reasons.append("HTF Bear ✓")
        elif r.htf_bias == "BULLISH":
            r.score += SCORE_HTF_AGAINST; r.reasons.append("HTF Bull ⚠️")

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

        body_ratio = body / atr if atr > 0 else 0
        if last['close'] < prev['low'] and body_ratio > MOMENTUM_BODY_ATR and r.score >= MIN_SCORE:
            r.use_market = True; r.entry = 0.0
            r.reasons.append("🚀 MKT")

    if r.signal != "WAIT":
        r.setup_hash = _make_hash(r.signal, r.entry, r.sl)
    return r

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
    # Daily equity drawdown
    daily_dd = (balance - equity) / balance * 100 if balance > 0 else 0
    if daily_dd >= MAX_DAILY_LOSS_PCT:
        log.warning(f"🛑 Daily DD {daily_dd:.2f}% ≥ {MAX_DAILY_LOSS_PCT}%"); return False
    # Total drawdown
    init_bal = get_state("initial_balance")
    if init_bal is None:
        set_state("initial_balance", balance); init_bal = balance
    total_dd = (init_bal - equity) / init_bal * 100 if init_bal > 0 else 0
    if total_dd >= MAX_TOTAL_DD_PCT:
        log.warning(f"🛑 Total DD {total_dd:.2f}% ≥ {MAX_TOTAL_DD_PCT}%"); return False
    return True

def calculate_lot(entry: float, sl: float) -> float:
    acct = mt5.account_info()
    info = mt5.symbol_info(SYMBOL)
    if acct is None or info is None: return 0.01
    risk_amount = acct.balance * (RISK_PERCENT / 100)
    sl_pts = abs(entry - sl) / info.point
    if sl_pts == 0: return info.volume_min
    tv = info.trade_tick_value / info.trade_tick_size
    lot = risk_amount / (sl_pts * tv)
    step = info.volume_step
    lot = round(lot / step) * step
    return float(max(info.volume_min, min(lot, info.volume_max)))

def validate_order(entry: float, sl: float, tp: float, lot: float) -> tuple:
    info = mt5.symbol_info(SYMBOL)
    acct = mt5.account_info()
    tick = mt5.symbol_info_tick(SYMBOL)
    if not all([info, acct, tick]): return False, "อ่านข้อมูล broker ไม่ได้"
    min_d = info.trade_stops_level * info.point
    if abs(entry - sl) < min_d: return False, f"SL ใกล้เกิน stop_level"
    if abs(entry - tp) < min_d: return False, f"TP ใกล้เกิน stop_level"
    frz = info.trade_freeze_level * info.point
    if frz > 0 and abs(entry - tick.ask) < frz: return False, "Entry ใน freeze zone"
    step = info.volume_step
    if abs(round(lot / step) * step - lot) > 1e-8: return False, "Lot step ผิด"
    margin_req = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, SYMBOL, lot, entry)
    if margin_req is None or margin_req > acct.margin_free * 0.9:
        return False, "Margin ไม่พอ"
    return True, "OK"

def has_active_trade() -> bool:
    """ตรวจเฉพาะ symbol + magic number ของ bot นี้"""
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
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None: return False
    sig = setup.signal; sl = setup.sl
    if setup.use_market:
        entry = tick.ask if sig == "BUY" else tick.bid
        otype = mt5.ORDER_TYPE_BUY  if sig == "BUY" else mt5.ORDER_TYPE_SELL
        action = mt5.TRADE_ACTION_DEAL; exp = 0
    else:
        entry = setup.entry
        otype = mt5.ORDER_TYPE_BUY_LIMIT if sig == "BUY" else mt5.ORDER_TYPE_SELL_LIMIT
        action = mt5.TRADE_ACTION_PENDING
        exp = int(time.time()) + (EXPIRATION_CANDLES * 5 * 60)
    risk = abs(entry - sl)
    if risk == 0: log.error("place_order: risk=0"); return False
    tp  = entry + (risk * RR_RATIO) if sig == "BUY" else entry - (risk * RR_RATIO)
    lot = calculate_lot(entry, sl)
    ok, reason = validate_order(entry, sl, tp, lot)
    if not ok: log.warning(f"⚠️ Validate fail: {reason}"); return False
    req = {
        "action": action, "symbol": SYMBOL, "volume": lot, "type": otype,
        "price": round(float(entry), 2), "sl": round(float(sl), 2),
        "tp": round(float(tp), 2), "deviation": 20, "magic": MAGIC_NUMBER,
        "comment": f"V5|{sig}|{setup.score}",
    }
    if action == mt5.TRADE_ACTION_PENDING:
        req["type_time"] = mt5.ORDER_TIME_SPECIFIED; req["expiration"] = exp
    res = _send_retry(req)
    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        mode = "MKT" if setup.use_market else "LMT"
        log.info(f"✅ {mode}|{sig}|Lot:{lot}|Entry:{entry:.2f}|SL:{sl:.2f}|TP:{tp:.2f}|S:{setup.score}")
        db_log_setup(sig, setup.score, entry, sl, tp, setup.setup_hash)
        return True
    return False

def _modify_sl(ticket: int, new_sl: float):
    res = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": ticket,
                          "sl": round(float(new_sl), 2)})
    if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
        log.warning(f"_modify_sl FAIL #{ticket} retcode:{res.retcode if res else 'None'}")

def manage_positions(atr: float):
    positions = [p for p in (mt5.positions_get(symbol=SYMBOL) or []) if p.magic == MAGIC_NUMBER]
    if not positions: return
    tick = mt5.symbol_info_tick(SYMBOL)
    info = mt5.symbol_info(SYMBOL)
    if tick is None or info is None: return
    a = atr if atr > 0 else 1.0
    open_tickets = {p.ticket for p in positions}

    for pos in positions:
        entry = pos.price_open; sl_now = pos.sl; tp = pos.tp
        risk  = abs(tp - entry) / RR_RATIO if RR_RATIO > 0 else abs(entry - sl_now)
        if risk == 0: continue
        is_buy = (pos.type == mt5.ORDER_TYPE_BUY)
        price  = tick.bid if is_buy else tick.ask
        buf    = info.point * 5
        profit_r = ((price - entry) / risk) if is_buy else ((entry - price) / risk)

        # Break-Even
        if profit_r >= BREAKEVEN_RR:
            be_sl = (entry + buf) if is_buy else (entry - buf)
            if (is_buy and sl_now < be_sl) or (not is_buy and sl_now > be_sl):
                _modify_sl(pos.ticket, be_sl)
                log.info(f"🔒 BE #{pos.ticket} SL→{be_sl:.2f}"); continue

        # Trailing
        if profit_r >= TRAIL_AFTER_RR:
            last_tsl = get_trail_sl(pos.ticket)
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

    # Cleanup trail state ของ position ที่ปิดแล้ว
    with _db() as c:
        rows = c.execute("SELECT ticket FROM trail_state").fetchall()
        for row in rows:
            if row["ticket"] not in open_tickets:
                remove_trail_sl(row["ticket"])

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

def wait_candle(tf_min: int = 5):
    now = datetime.now(bkk_tz)
    elapsed = (now.minute % tf_min) * 60 + now.second
    wait    = (tf_min * 60) - elapsed + 2
    if wait <= 0 or wait > tf_min * 60: wait = tf_min * 60 + 2
    log.info(f"⏳ รอ {wait:.0f}s")
    time.sleep(wait)

# ══════════════════════════════════════════════════════════════════
# 🔄  MAIN LOOP
# ══════════════════════════════════════════════════════════════════
BANNER = f"""
╔══════════════════════════════════════════════════════════════════╗
║   🚀 AI SMC/ICT Pro Sniper — V.5 | {SYMBOL:<12}              ║
║   Risk:{RISK_PERCENT}% | RR:1:{RR_RATIO} | MinScore:{MIN_SCORE} | Spread≤{MAX_SPREAD_POINTS:.0f}pts   ║
║   DailyDD:{MAX_DAILY_LOSS_PCT}% | TotalDD:{MAX_TOTAL_DD_PCT}% | BE@{BREAKEVEN_RR}R | Trail@{TRAIL_AFTER_RR}R     ║
╚══════════════════════════════════════════════════════════════════╝
"""

if __name__ == "__main__":
    print(BANNER)
    log.info("Bot เริ่มทำงาน")
    init_db()

    if not mt5_connect():
        log.error("❌ ไม่สามารถเชื่อมต่อ MT5"); quit()

    try:
        while True:
            cur = datetime.now(bkk_tz).strftime('%H:%M:%S')
            log.info("─" * 55)

            # 1. Connection guard
            if not ensure_alive():
                log.error("Reconnect ล้มเหลว → รอ 60s"); time.sleep(60); continue

            # 2. Risk guard
            if not is_within_risk_limits():
                log.warning(f"⛔ {cur} | DD limit → หยุดเทรด")
                data = fetch_all()
                if data["m5"] is not None:
                    manage_positions(calculate_atr(data["m5"]))
                wait_candle(); continue

            # 3. Session
            session = get_session()
            log.info(f"🕐 {cur} | {session}")
            if session in ("OUT_OF_SESSION", "RED_NEWS_BLOCK"):
                data = fetch_all()
                if data["m5"] is not None:
                    manage_positions(calculate_atr(data["m5"]))
                wait_candle(); continue

            # 4. Fetch data
            data = fetch_all()
            if data["m5"] is None:
                log.warning("M5 ไม่ได้ข้อมูล → ข้ามรอบ"); wait_candle(); continue

            # 5. Manage positions
            atr = calculate_atr(data["m5"])
            manage_positions(atr)

            # 6. Cleanup cooldowns
            cleanup_cooldowns()

            # 7. Active trade check (symbol + magic only)
            if has_active_trade():
                log.info("💼 มี trade อยู่แล้ว → ทับมือ"); wait_candle(); continue

            # 8. Analyze
            setup = analyze_setup(data["m5"], data["h1"], data["d1"])
            log.info(f"📊 HTF:{setup.htf_bias} | ADR:{setup.adr_pct*100:.0f}%")

            if setup.signal == "WAIT":
                log.info(f"📉 WAIT → {' | '.join(setup.reasons) or 'ไม่พบ setup'}")
                wait_candle(); continue

            # 9. Score gate
            log.info(f"🔥 {setup.summary()}")
            if setup.score < MIN_SCORE:
                log.info(f"⚠️ Score {setup.score} < {MIN_SCORE} → ทับมือ"); wait_candle(); continue

            # 10. Duplicate check
            if is_on_cooldown(setup.setup_hash):
                log.info(f"🔁 Duplicate ({setup.setup_hash}) → ข้าม"); wait_candle(); continue

            # 11. Execute
            if place_order(setup):
                set_cooldown(setup.setup_hash)

            wait_candle()

    except KeyboardInterrupt:
        log.info("🛑 หยุดโดยผู้ใช้")
    except Exception as e:
        log.exception(f"💥 {e}")
    finally:
        mt5.shutdown()
        log.info("MT5 disconnected. Goodbye.")