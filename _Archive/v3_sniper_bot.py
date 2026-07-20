import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import time
from datetime import datetime, time as dtime
import pytz

# ==========================================
# ⚙️ 1. CONFIGURATION (ตั้งค่าระบบ)
# ==========================================
SYMBOL = "XAUUSDm"        # ชื่อคู่เงิน
MAGIC_NUMBER = 99999      # รหัสประจำตัวบอท
RISK_PERCENT = 1.0        # เสี่ยง 1% ของพอร์ตต่อ 1 ไม้ (Dynamic Lot)
RR_RATIO = 3.0            # Risk:Reward Ratio (เช่น 1:3)
EXPIRATION_CANDLES = 5    # ยกเลิก Pending Order ถ้าไม่แมตช์ภายใน 5 แท่ง

bkk_tz = pytz.timezone('Asia/Bangkok')

# ==========================================
# 🕒 2. SESSION MANAGER (Deterministic Rules)
# ==========================================
def get_trading_session():
    now = datetime.now(bkk_tz).time()
    # ช่วงเวลาหลบข่าวแรง (19:15 - 19:45)
    news_kill_start, news_kill_end = dtime(19, 15), dtime(19, 45)
    if news_kill_start <= now <= news_kill_end: return "RED_NEWS_BLOCK"
    
    # ช่วงเวลาเทรดหลัก
    if dtime(14, 0) <= now <= dtime(18, 0): return "LONDON"
    if dtime(19, 0) <= now <= dtime(23, 0): return "NEW_YORK"
    return "OUT_OF_SESSION"

# ==========================================
# 📊 3. DATA & SMC MATH ENGINE
# ==========================================
def fetch_data(timeframe, num_candles):
    rates = mt5.copy_rates_from_pos(SYMBOL, timeframe, 0, num_candles)
    if rates is None: return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df

def calculate_atr(df, period=14):
    high_low = df['high'] - df['low']
    return high_low.rolling(period).mean().iloc[-1]

def get_swings(df, period=5):
    """ หา Swing High/Low ล่าสุด """
    highs = df['high'].rolling(window=period*2+1, center=True).max()
    lows = df['low'].rolling(window=period*2+1, center=True).min()
    
    swing_highs = df[df['high'] == highs]
    swing_lows = df[df['low'] == lows]
    
    last_sh = swing_highs['high'].dropna().iloc[-1] if not swing_highs.empty else df['high'].max()
    last_sl = swing_lows['low'].dropna().iloc[-1] if not swing_lows.empty else df['low'].min()
    return last_sh, last_sl

def check_fvg(df):
    """ หา FVG สดใหม่ใน 3 แท่งล่าสุด """
    last_3 = df.tail(3)
    bullish_fvg = last_3['low'].iloc[2] > last_3['high'].iloc[0]
    bearish_fvg = last_3['high'].iloc[2] < last_3['low'].iloc[0]
    
    if bullish_fvg: return "BULLISH", last_3['high'].iloc[0], last_3['low'].iloc[2]
    if bearish_fvg: return "BEARISH", last_3['high'].iloc[2], last_3['low'].iloc[0]
    return "NONE", 0, 0

# ==========================================
# 🎯 4. LOGIC TIER: Mandatory & Scoring
# ==========================================
def analyze_setup():
    df = fetch_data(mt5.TIMEFRAME_M5, 100)
    if df is None: return None
    
    current_price = df['close'].iloc[-1]
    last_sh, last_sl = get_swings(df)
    atr = calculate_atr(df)
    
    # 📌 TIER 1: Mandatory Checks
    last_candle = df.iloc[-2] # ใช้แท่งที่ปิดแล้ว
    
    sweep_sellside = last_candle['low'] < last_sl and last_candle['close'] > last_sl
    sweep_buyside = last_candle['high'] > last_sh and last_candle['close'] < last_sh
    
    fvg_type, fvg_bottom, fvg_top = check_fvg(df)
    
    # 📌 TIER 2: Scoring Engine
    score = 0
    signal = "WAIT"
    entry, sl = 0.0, 0.0
    
    if sweep_sellside and fvg_type == "BULLISH":
        signal = "BUY"
        score += 40 # Mandatory Passed
        entry = fvg_top 
        sl = last_sl - (atr * 0.5) 
        
        # Confluence Boosters
        if last_candle['close'] > last_sh: score += 30 
        if (last_candle['close'] - last_candle['open']) > atr: score += 20 
        
    elif sweep_buyside and fvg_type == "BEARISH":
        signal = "SELL"
        score += 40
        entry = fvg_bottom
        sl = last_sh + (atr * 0.5)
        
        if last_candle['close'] < last_sl: score += 30
        if (last_candle['open'] - last_candle['close']) > atr: score += 20

    return {"signal": signal, "score": score, "entry": entry, "sl": sl, "atr": atr}

# ==========================================
# 💸 5. SMART EXECUTION (Money Management)
# ==========================================
def calculate_dynamic_lot(entry, sl):
    account_info = mt5.account_info()
    if account_info is None: return 0.01
    
    risk_amount = account_info.balance * (RISK_PERCENT / 100)
    tick = mt5.symbol_info(SYMBOL)
    sl_points = abs(entry - sl) / tick.point
    if sl_points == 0: return 0.01
    
    lot = risk_amount / (sl_points * (tick.trade_tick_value / tick.trade_tick_size))
    step = tick.volume_step
    return max(tick.volume_min, min(round(lot / step) * step, tick.volume_max))

def place_pending_order(setup):
    sig, entry, sl = setup['signal'], setup['entry'], setup['sl']
    lot = calculate_dynamic_lot(entry, sl)
    
    risk = abs(entry - sl)
    tp = entry + (risk * RR_RATIO) if sig == "BUY" else entry - (risk * RR_RATIO)
    
    order_type = mt5.ORDER_TYPE_BUY_LIMIT if sig == "BUY" else mt5.ORDER_TYPE_SELL_LIMIT
    expiration = int(time.time()) + (EXPIRATION_CANDLES * 5 * 60)
    
    request = {
        "action": mt5.TRADE_ACTION_PENDING,
        "symbol": SYMBOL, "volume": float(lot), "type": order_type,
        "price": float(entry), "sl": float(sl), "tp": float(tp),
        "deviation": 20, "magic": MAGIC_NUMBER, "comment": "V3 Raw Logic",
        "type_time": mt5.ORDER_TIME_SPECIFIED, "expiration": expiration,
    }
    
    res = mt5.order_send(request)
    if res.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"✅ [LIMIT PLACED] {sig} Lot: {lot} | Entry: {entry:.2f} | SL: {sl:.2f} | TP: {tp:.2f}")
    else:
        print(f"❌ [FAILED] Error Code: {res.retcode} | {res.comment}")

# ==========================================
# 🔄 6. MAIN LOOP
# ==========================================
def wait_for_next_candle(tf_minutes=5):
    now = datetime.now()
    minutes_passed = now.minute % tf_minutes
    seconds_passed = now.second
    sec_to_wait = (tf_minutes * 60) - ((minutes_passed * 60) + seconds_passed) + 2
    time.sleep(sec_to_wait)

if __name__ == "__main__":
    print(f"\n{'='*50}")
    print(f"🚀 AI SMC/ICT Pro Sniper (V.3 Raw Logic) | {SYMBOL}")
    print(f"{'='*50}\n")
    
    if not mt5.initialize():
        print("❌ ไม่สามารถเชื่อมต่อ MT5 ได้")
        quit()
    
    while True:
        cur_time = datetime.now(bkk_tz).strftime('%H:%M:%S')
            
        # 1. เช็ค Session (เวลาเทรด)
        session = get_trading_session()
        if session in ["OUT_OF_SESSION", "RED_NEWS_BLOCK"]:
            print(f"⏳ {cur_time} | 💤 นอกเวลาทำการ หรือ ติดข่าวแดง ({session})")
            wait_for_next_candle(5)
            continue
            
        # 2. วิเคราะห์ Setup & ให้คะแนน
        setup = analyze_setup()
        if setup and setup['signal'] != "WAIT":
            print(f"🔥 {cur_time} | 🎯 ตรวจพบ Setup: {setup['signal']} (Score: {setup['score']}/100)")
            
            # 3. ต้องได้คะแนนเกิน 70 ถึงจะยิง
            if setup['score'] >= 70:
                active_orders = mt5.orders_total()
                active_positions = mt5.positions_total()
                
                if active_orders == 0 and active_positions == 0:
                    place_pending_order(setup)
                else:
                    print(f"⏳ {cur_time} | 💼 มีออเดอร์/โพสิชันทำงานอยู่แล้ว -> ทับมือ")
            else:
                print(f"⏳ {cur_time} | ⚠️ คะแนนไม่ถึงเกณฑ์ -> ทับมือ")
        else:
            print(f"⏳ {cur_time} | 📉 สแกนไม่เจอ Setup -> รอแท่งต่อไป")
            
        # รอให้ปิดแท่งเทียน 5 นาที
        wait_for_next_candle(5)