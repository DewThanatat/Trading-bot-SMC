import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import time
import logging
from datetime import datetime, time as dtime
import pytz

# ==========================================
# ⚙️ 1. CONFIGURATION
# ==========================================
SYMBOL            = "XAUUSDm"
MAGIC_NUMBER      = 99999
RISK_PERCENT      = 1.0        # % ของ Balance ต่อ 1 ไม้
RR_RATIO          = 3.0        # Risk:Reward (1:3)
EXPIRATION_CANDLES= 5          # แท่ง M5 ก่อน Pending หมดอายุ
MIN_SCORE         = 70         # คะแนนขั้นต่ำก่อนยิง
MAX_DAILY_LOSS_PCT= 3.0        # หยุดเทรดถ้าขาดทุนเกิน 3% ต่อวัน
BREAKEVEN_RR      = 1.0        # ย้าย SL → Entry เมื่อกำไร = 1R
TRAIL_AFTER_RR    = 1.5        # เริ่ม Trailing หลังกำไร = 1.5R
TRAIL_ATR_MULT    = 0.8        # Trailing SL = price - (ATR * mult)
ADR_MIN_PCT       = 0.3        # ถ้าราคาวิ่งไปแล้ว > 80% ของ ADR → หยุด (ดู ADR filter)

bkk_tz = pytz.timezone('Asia/Bangkok')

# ==========================================
# 📋 2. LOGGING SETUP
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler("smc_bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ==========================================
# 🕒 3. SESSION MANAGER
# ==========================================
def get_trading_session() -> str:
    now = datetime.now(bkk_tz).time()
    # ช่วงหลบข่าวแรง
    if dtime(19, 15) <= now <= dtime(19, 45):
        return "RED_NEWS_BLOCK"
    # Session หลัก
    if dtime(14,  0) <= now <= dtime(18,  0): return "LONDON"
    if dtime(19,  0) <= now <= dtime(23,  0): return "NEW_YORK"
    return "OUT_OF_SESSION"

# ==========================================
# 📊 4. DATA ENGINE
# ==========================================
def fetch_data(timeframe: int, num_candles: int) -> pd.DataFrame | None:
    rates = mt5.copy_rates_from_pos(SYMBOL, timeframe, 0, num_candles)
    if rates is None or len(rates) == 0:
        log.warning(f"fetch_data: ไม่ได้ข้อมูล tf={timeframe}")
        return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df

# ==========================================
# 📐 5. INDICATOR ENGINE (Correct Math)
# ==========================================
def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """ATR ที่ถูกต้อง — ใช้ True Range (รวม Gap ข้ามคืน)"""
    high  = df['high']
    low   = df['low']
    close = df['close'].shift(1)
    tr = pd.concat([
        high - low,
        (high - close).abs(),
        (low  - close).abs()
    ], axis=1).max(axis=1)
    atr_val = tr.rolling(period).mean().iloc[-1]
    return float(atr_val) if not np.isnan(atr_val) else 0.0

def calculate_adr(df_daily: pd.DataFrame, period: int = 14) -> float:
    """Average Daily Range — ใช้กรอง setup ที่ราคาวิ่งไปมากแล้ว"""
    daily_range = df_daily['high'] - df_daily['low']
    return float(daily_range.rolling(period).mean().iloc[-1])

def get_swings(df: pd.DataFrame, period: int = 5):
    """
    Swing High / Low ที่ถูกต้อง
    — หลีกเลี่ยง NaN ที่ขอบของ rolling(center=True)
    — ใช้ argrelextrema แทน
    """
    from scipy.signal import argrelextrema
    h = df['high'].values
    l = df['low'].values

    swing_h_idx = argrelextrema(h, np.greater_equal, order=period)[0]
    swing_l_idx = argrelextrema(l, np.less_equal,    order=period)[0]

    last_sh = float(h[swing_h_idx[-1]]) if len(swing_h_idx) > 0 else float(df['high'].max())
    last_sl = float(l[swing_l_idx[-1]]) if len(swing_l_idx) > 0 else float(df['low'].min())
    return last_sh, last_sl

def check_fvg(df: pd.DataFrame):
    """
    FVG บนชุดข้อมูลที่ส่งมา
    ** สำคัญ: caller ต้องส่ง df ที่ตัดแท่ง live ออกแล้ว (iloc[:-1]) **
    """
    if len(df) < 3:
        return "NONE", 0.0, 0.0
    c1, _, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    if c3['low']  > c1['high']: return "BULLISH", float(c1['high']), float(c3['low'])
    if c3['high'] < c1['low']:  return "BEARISH", float(c3['high']), float(c1['low'])
    return "NONE", 0.0, 0.0

# ==========================================
# 🏦 6. HTF BIAS (H1 Trend Filter)
# ==========================================
def get_htf_bias() -> str:
    """
    อ่าน H1 เพื่อกำหนดทิศทางหลัก
    — ใช้ EMA 50 vs EMA 200 + แนวโน้ม Swing
    """
    df_h1 = fetch_data(mt5.TIMEFRAME_H1, 220)
    if df_h1 is None:
        return "NEUTRAL"

    ema50  = df_h1['close'].ewm(span=50,  adjust=False).mean().iloc[-1]
    ema200 = df_h1['close'].ewm(span=200, adjust=False).mean().iloc[-1]

    last_sh_h1, last_sl_h1 = get_swings(df_h1, period=10)
    price = df_h1['close'].iloc[-1]

    bullish_ema   = ema50 > ema200
    bullish_price = price > ema50
    bearish_ema   = ema50 < ema200
    bearish_price = price < ema50

    if bullish_ema and bullish_price:  return "BULLISH"
    if bearish_ema and bearish_price:  return "BEARISH"
    return "NEUTRAL"

# ==========================================
# 🧱 7. ORDER BLOCK DETECTION
# ==========================================
def find_order_block(df: pd.DataFrame, direction: str):
    """
    หา OB ล่าสุดก่อนการ Break of Structure
    Bullish OB = แท่งแดงก่อนหน้าที่ราคา impulse ขึ้น
    Bearish OB = แท่งเขียวก่อนหน้าที่ราคา impulse ลง
    คืนค่า (ob_high, ob_low) หรือ None
    """
    closed = df.iloc[:-1]  # ตัดแท่ง live ออก
    if len(closed) < 5:
        return None

    for i in range(len(closed) - 2, 2, -1):
        candle = closed.iloc[i]
        if direction == "BUY":
            # แท่งแดง (bearish candle) → ถัดไปเป็น impulse ขึ้น
            if candle['close'] < candle['open']:
                next_move = closed.iloc[i+1]['close'] - closed.iloc[i+1]['open']
                atr_val = calculate_atr(closed.iloc[:i+2])
                if next_move > atr_val * 0.8:
                    return float(candle['high']), float(candle['low'])
        elif direction == "SELL":
            # แท่งเขียว → ถัดไปเป็น impulse ลง
            if candle['close'] > candle['open']:
                next_move = closed.iloc[i+1]['open'] - closed.iloc[i+1]['close']
                atr_val = calculate_atr(closed.iloc[:i+2])
                if next_move > atr_val * 0.8:
                    return float(candle['high']), float(candle['low'])
    return None

# ==========================================
# 🎯 8. SETUP ANALYZER (Mandatory + Scoring)
# ==========================================
def analyze_setup(htf_bias: str) -> dict | None:
    df_m5 = fetch_data(mt5.TIMEFRAME_M5, 150)
    if df_m5 is None:
        return None

    # ✅ ใช้ df ที่ตัดแท่ง live ออกสำหรับ FVG
    df_closed = df_m5.iloc[:-1]

    last_candle  = df_closed.iloc[-1]   # แท่งที่ปิดสมบูรณ์ล่าสุด
    prev_candle  = df_closed.iloc[-2]

    last_sh, last_sl = get_swings(df_closed, period=5)
    atr              = calculate_atr(df_closed)
    if atr == 0:
        return None

    fvg_type, fvg_bottom, fvg_top = check_fvg(df_closed)

    # ADR Filter — ป้องกันเข้าตอนราคาวิ่งมากแล้ว
    df_daily = fetch_data(mt5.TIMEFRAME_D1, 20)
    adr = calculate_adr(df_daily) if df_daily is not None else 0.0
    today_range = df_daily['high'].iloc[-1] - df_daily['low'].iloc[-1] if df_daily is not None else 0.0
    adr_exhausted = (adr > 0) and (today_range / adr > (1.0 - ADR_MIN_PCT))

    # ── Sweep Detection ──
    sweep_sellside = (last_candle['low'] < last_sl) and (last_candle['close'] > last_sl)
    sweep_buyside  = (last_candle['high'] > last_sh) and (last_candle['close'] < last_sh)

    score  = 0
    signal = "WAIT"
    entry  = 0.0
    sl     = 0.0
    reason = []

    # ── BUY Setup ──
    if sweep_sellside and fvg_type == "BULLISH":
        # HTF Bias ต้องไม่ขัด
        if htf_bias == "BEARISH":
            return {"signal": "WAIT", "score": 0, "entry": 0, "sl": 0, "atr": atr, "reason": ["HTF Bias ขัด (Bearish)"]}

        signal  = "BUY"
        entry   = fvg_top
        sl      = last_sl - (atr * 0.5)
        score  += 40
        reason.append("Sweep Sellside + Bullish FVG")

        # Confluence Boosters
        if htf_bias == "BULLISH":
            score += 20; reason.append("HTF Bias Bullish ✓")
        body_size = last_candle['close'] - last_candle['open']
        if body_size > atr * 0.8:
            score += 15; reason.append("Strong Bullish Candle ✓")
        # OB Confluence
        ob = find_order_block(df_closed, "BUY")
        if ob and ob[1] <= entry <= ob[0]:
            score += 15; reason.append("Entry อยู่ใน Bullish OB ✓")
        # BOS — Break of prior swing (momentum confirm)
        if last_candle['close'] > prev_candle['high']:
            score += 10; reason.append("BOS Confirm ✓")

    # ── SELL Setup ──
    elif sweep_buyside and fvg_type == "BEARISH":
        if htf_bias == "BULLISH":
            return {"signal": "WAIT", "score": 0, "entry": 0, "sl": 0, "atr": atr, "reason": ["HTF Bias ขัด (Bullish)"]}

        signal  = "SELL"
        entry   = fvg_bottom
        sl      = last_sh + (atr * 0.5)
        score  += 40
        reason.append("Sweep Buyside + Bearish FVG")

        if htf_bias == "BEARISH":
            score += 20; reason.append("HTF Bias Bearish ✓")
        body_size = last_candle['open'] - last_candle['close']
        if body_size > atr * 0.8:
            score += 15; reason.append("Strong Bearish Candle ✓")
        ob = find_order_block(df_closed, "SELL")
        if ob and ob[1] <= entry <= ob[0]:
            score += 15; reason.append("Entry อยู่ใน Bearish OB ✓")
        if last_candle['close'] < prev_candle['low']:
            score += 10; reason.append("BOS Confirm ✓")

    # ADR Exhaustion override
    if adr_exhausted and signal != "WAIT":
        score = max(0, score - 20)
        reason.append("⚠️ ADR Exhausted (-20)")

    return {
        "signal": signal, "score": score,
        "entry": entry,   "sl": sl,
        "atr": atr,       "reason": reason,
        "adr_exhausted": adr_exhausted
    }

# ==========================================
# 💰 9. MONEY MANAGEMENT
# ==========================================
def calculate_dynamic_lot(entry: float, sl: float) -> float:
    account = mt5.account_info()
    if account is None:
        return 0.01
    tick = mt5.symbol_info(SYMBOL)
    if tick is None:
        return 0.01

    risk_amount = account.balance * (RISK_PERCENT / 100)
    sl_points   = abs(entry - sl) / tick.point
    if sl_points == 0:
        return 0.01

    tick_value_per_lot = tick.trade_tick_value / tick.trade_tick_size
    lot  = risk_amount / (sl_points * tick_value_per_lot)
    step = tick.volume_step
    lot  = round(lot / step) * step
    return float(max(tick.volume_min, min(lot, tick.volume_max)))

def check_daily_loss_limit() -> bool:
    """คืน True ถ้าขาดทุนเกิน MAX_DAILY_LOSS_PCT → หยุดเทรด"""
    account = mt5.account_info()
    if account is None:
        return False
    deals = mt5.history_deals_get(
        datetime.now(bkk_tz).replace(hour=0, minute=0, second=0, microsecond=0),
        datetime.now(bkk_tz)
    )
    if deals is None or len(deals) == 0:
        return False
    daily_pnl = sum(d.profit for d in deals if d.magic == MAGIC_NUMBER)
    loss_pct  = abs(daily_pnl) / account.balance * 100 if daily_pnl < 0 else 0
    if loss_pct >= MAX_DAILY_LOSS_PCT:
        log.warning(f"🛑 Daily Loss Limit ถึงแล้ว ({loss_pct:.2f}%) → หยุดเทรดวันนี้")
        return True
    return False

# ==========================================
# 📤 10. ORDER EXECUTION
# ==========================================
def place_pending_order(setup: dict) -> bool:
    sig   = setup['signal']
    entry = setup['entry']
    sl    = setup['sl']
    atr   = setup['atr']

    lot   = calculate_dynamic_lot(entry, sl)
    risk  = abs(entry - sl)
    if risk == 0:
        log.error("place_pending_order: risk = 0 → ยกเลิก")
        return False

    tp         = entry + (risk * RR_RATIO) if sig == "BUY" else entry - (risk * RR_RATIO)
    order_type = mt5.ORDER_TYPE_BUY_LIMIT if sig == "BUY" else mt5.ORDER_TYPE_SELL_LIMIT
    expiration = int(time.time()) + (EXPIRATION_CANDLES * 5 * 60)

    request = {
        "action":     mt5.TRADE_ACTION_PENDING,
        "symbol":     SYMBOL,
        "volume":     lot,
        "type":       order_type,
        "price":      round(float(entry), 2),
        "sl":         round(float(sl),    2),
        "tp":         round(float(tp),    2),
        "deviation":  20,
        "magic":      MAGIC_NUMBER,
        "comment":    f"V4|{sig}|{setup['score']}",
        "type_time":  mt5.ORDER_TIME_SPECIFIED,
        "expiration": expiration,
    }

    res = mt5.order_send(request)
    if res is None:
        log.error("place_pending_order: order_send คืนค่า None (MT5 ไม่ตอบสนอง)")
        return False
    if res.retcode == mt5.TRADE_RETCODE_DONE:
        log.info(f"✅ LIMIT PLACED | {sig} | Lot:{lot} | Entry:{entry:.2f} | SL:{sl:.2f} | TP:{tp:.2f}")
        return True
    else:
        log.error(f"❌ ORDER FAILED | retcode:{res.retcode} | {res.comment}")
        return False

# ==========================================
# 🔧 11. POSITION MANAGEMENT
#         Break-Even + Trailing Stop
# ==========================================
def manage_open_positions():
    positions = mt5.positions_get(symbol=SYMBOL)
    if not positions:
        return

    for pos in positions:
        if pos.magic != MAGIC_NUMBER:
            continue

        price_now = mt5.symbol_info_tick(SYMBOL)
        if price_now is None:
            continue

        current = price_now.bid if pos.type == mt5.ORDER_TYPE_BUY else price_now.ask
        entry   = pos.price_open
        sl_now  = pos.sl
        tp      = pos.tp
        risk    = abs(tp - entry) / RR_RATIO if RR_RATIO != 0 else abs(entry - sl_now)

        df_m5 = fetch_data(mt5.TIMEFRAME_M5, 20)
        atr   = calculate_atr(df_m5) if df_m5 is not None else risk * 0.2

        # ── Break-Even ──
        if pos.type == mt5.ORDER_TYPE_BUY:
            profit_r = (current - entry) / risk if risk > 0 else 0
            be_sl    = entry + mt5.symbol_info(SYMBOL).point * 5  # +5 point buffer
            if profit_r >= BREAKEVEN_RR and sl_now < be_sl:
                _modify_sl(pos.ticket, be_sl)
                log.info(f"🔒 Break-Even | #{pos.ticket} | SL → {be_sl:.2f}")

            # ── Trailing Stop ──
            if profit_r >= TRAIL_AFTER_RR:
                trail_sl = current - (atr * TRAIL_ATR_MULT)
                if trail_sl > sl_now:
                    _modify_sl(pos.ticket, trail_sl)
                    log.info(f"📈 Trailing SL | #{pos.ticket} | SL → {trail_sl:.2f}")

        elif pos.type == mt5.ORDER_TYPE_SELL:
            profit_r = (entry - current) / risk if risk > 0 else 0
            be_sl    = entry - mt5.symbol_info(SYMBOL).point * 5
            if profit_r >= BREAKEVEN_RR and sl_now > be_sl:
                _modify_sl(pos.ticket, be_sl)
                log.info(f"🔒 Break-Even | #{pos.ticket} | SL → {be_sl:.2f}")

            if profit_r >= TRAIL_AFTER_RR:
                trail_sl = current + (atr * TRAIL_ATR_MULT)
                if trail_sl < sl_now:
                    _modify_sl(pos.ticket, trail_sl)
                    log.info(f"📉 Trailing SL | #{pos.ticket} | SL → {trail_sl:.2f}")

def _modify_sl(ticket: int, new_sl: float):
    request = {
        "action":   mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "sl":       round(float(new_sl), 2),
    }
    res = mt5.order_send(request)
    if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
        retcode = res.retcode if res else "None"
        log.warning(f"_modify_sl FAILED | ticket:{ticket} | retcode:{retcode}")

# ==========================================
# 🔌 12. MT5 CONNECTION WITH RETRY
# ==========================================
def ensure_mt5_connected(max_retries: int = 5) -> bool:
    for attempt in range(1, max_retries + 1):
        if mt5.initialize():
            return True
        log.warning(f"MT5 reconnect attempt {attempt}/{max_retries}...")
        time.sleep(5)
    return False

# ==========================================
# ⏱️ 13. CANDLE TIMER
# ==========================================
def wait_for_next_candle(tf_minutes: int = 5):
    now             = datetime.now(bkk_tz)          # ✅ มี timezone สอดคล้องกัน
    minutes_passed  = now.minute % tf_minutes
    seconds_passed  = now.second
    sec_to_wait     = (tf_minutes * 60) - (minutes_passed * 60 + seconds_passed) + 2
    log.info(f"⏳ รอแท่งถัดไป {sec_to_wait:.0f} วินาที...")
    time.sleep(sec_to_wait)

# ==========================================
# 🔄 14. MAIN LOOP
# ==========================================
if __name__ == "__main__":
    BANNER = f"""
{'='*60}
  🚀 AI SMC/ICT Pro Sniper — V.4 FINAL | {SYMBOL}
  Risk: {RISK_PERCENT}% | RR: 1:{RR_RATIO} | MinScore: {MIN_SCORE}
  MaxDailyLoss: {MAX_DAILY_LOSS_PCT}% | BE@{BREAKEVEN_RR}R | Trail@{TRAIL_AFTER_RR}R
{'='*60}
"""
    print(BANNER)
    log.info("Bot เริ่มทำงาน")

    if not ensure_mt5_connected():
        log.error("❌ ไม่สามารถเชื่อมต่อ MT5 ได้ หยุดโปรแกรม")
        quit()

    try:
        while True:
            cur_time = datetime.now(bkk_tz).strftime('%H:%M:%S')

            # ── Reconnect Guard ──
            if not mt5.terminal_info():
                log.warning("MT5 หลุด → กำลัง reconnect...")
                if not ensure_mt5_connected():
                    log.error("Reconnect ล้มเหลว → หยุด 60 วิ")
                    time.sleep(60)
                    continue

            # ── Daily Loss Limit ──
            if check_daily_loss_limit():
                wait_for_next_candle(5)
                continue

            # ── Session Check ──
            session = get_trading_session()
            if session in ("OUT_OF_SESSION", "RED_NEWS_BLOCK"):
                log.info(f"💤 {cur_time} | {session}")
                # ยังจัดการ position เดิมได้แม้นอก session
                manage_open_positions()
                wait_for_next_candle(5)
                continue

            # ── Manage Existing Positions ──
            manage_open_positions()

            # ── HTF Bias ──
            htf_bias = get_htf_bias()
            log.info(f"🧭 {cur_time} | Session: {session} | HTF Bias: {htf_bias}")

            # ── Analyze Setup ──
            setup = analyze_setup(htf_bias)
            if setup is None:
                log.warning("analyze_setup คืนค่า None → ข้ามรอบ")
                wait_for_next_candle(5)
                continue

            if setup['signal'] != "WAIT":
                reason_str = " | ".join(setup['reason'])
                log.info(f"🔥 {cur_time} | {setup['signal']} Score:{setup['score']}/100 | {reason_str}")

                if setup['score'] >= MIN_SCORE:
                    active_orders    = mt5.orders_total()
                    active_positions = mt5.positions_total()

                    if active_orders == 0 and active_positions == 0:
                        place_pending_order(setup)
                    else:
                        log.info(f"💼 มีออเดอร์/โพสิชัน ({active_orders}O/{active_positions}P) → ทับมือ")
                else:
                    log.info(f"⚠️ Score {setup['score']} < {MIN_SCORE} → ทับมือ")
            else:
                reason_str = " | ".join(setup.get('reason', []))
                log.info(f"📉 {cur_time} | ไม่พบ Setup{(' — ' + reason_str) if reason_str else ''}")

            wait_for_next_candle(5)

    except KeyboardInterrupt:
        log.info("🛑 หยุดโปรแกรมโดยผู้ใช้ (Ctrl+C)")
    except Exception as e:
        log.exception(f"💥 Unhandled Exception: {e}")
    finally:
        mt5.shutdown()          # ✅ ปิดการเชื่อมต่อ MT5 เสมอ
        log.info("MT5 disconnected. Goodbye.")
