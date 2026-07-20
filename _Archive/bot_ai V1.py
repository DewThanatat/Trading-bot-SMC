import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from scipy.signal import argrelextrema
import json
import time
from datetime import datetime, time as dtime
import pytz
from google import genai
from google.genai import types

# ==========================================
# ⚙️ 1. Configuration (ตั้งค่าหลัก)
# ==========================================
GEMINI_API_KEY = "AIzaSyCUPdUnB0elSQhOjdl8-FsZk2vBTI0a7N8" 
SYMBOL = "XAUUSDm"
LOT_SIZE = 0.01
AI_MODEL = "gemini-2.0-flash"
SPREAD_BUFFER_POINTS = 30 # กัน SL โดนสะบัด

client = genai.Client(api_key=GEMINI_API_KEY)
bkk_tz = pytz.timezone('Asia/Bangkok')

# ==========================================
# 🕒 2. Session & Kill Switch (ระบบกรองข่าว/เวลา)
# ==========================================
def get_session_info():
    now = datetime.now(bkk_tz).time()
    
    # 🔴 Kill Switch: ปิดระบบช่วง NY Open & ข่าวกล่องแดง (19:30 - 20:30 BKK)
    kill_start, kill_end = dtime(19, 25), dtime(20, 35)
    if kill_start <= now <= kill_end:
        return "KILL_SWITCH_ACTIVE", 100 # บังคับหยุดเทรด

    london = (dtime(14, 0), dtime(17, 0))
    ny = (dtime(19, 0), dtime(22, 30))
    asian = (dtime(7, 0), dtime(12, 0))

    if london[0] <= now <= london[1]: return "LONDON_KILLZONE", 80
    elif ny[0] <= now <= ny[1]: return "NEW_YORK_KILLZONE", 80
    elif asian[0] <= now <= asian[1]: return "ASIAN_RANGE", 90
    else: return "OUT_OF_SESSION", 95

# ==========================================
# 📊 3. Core Logic & Major Liquidity
# ==========================================
def fetch_data(symbol, timeframe, num_candles, shift=0):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, shift, num_candles)
    if rates is None or len(rates) == 0: return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df

def get_major_liquidity():
    # ดึงข้อมูล D1 แท่งเมื่อวาน (Shift=1) เพื่อหา PDH / PDL
    d1_df = fetch_data(SYMBOL, mt5.TIMEFRAME_D1, 1, 1)
    if d1_df is None: return "N/A", "N/A"
    return round(d1_df['high'].iloc[0], 3), round(d1_df['low'].iloc[0], 3)

def get_market_structure(df, order=3):
    highs = argrelextrema(df['high'].values, np.greater_equal, order=order)[0]
    lows = argrelextrema(df['low'].values, np.less_equal, order=order)[0]
    if len(highs) >= 2 and len(lows) >= 2:
        if df['high'].iloc[highs[-1]] > df['high'].iloc[highs[-2]]: return "BULLISH (HH)"
        elif df['low'].iloc[lows[-1]] < df['low'].iloc[lows[-2]]: return "BEARISH (LL)"
    return "BULLISH" if df['close'].iloc[-1] > df['close'].iloc[0] else "BEARISH"

def find_swings_and_ote(df, n=5):
    df = df.copy()
    highs_idx = argrelextrema(df['high'].values, np.greater_equal, order=n)[0]
    lows_idx = argrelextrema(df['low'].values, np.less_equal, order=n)[0]
    
    if len(highs_idx) == 0 or len(lows_idx) == 0:
        highs_idx = argrelextrema(df['high'].values, np.greater_equal, order=3)[0]
        lows_idx = argrelextrema(df['low'].values, np.less_equal, order=3)[0]
        if len(highs_idx) == 0 or len(lows_idx) == 0: return None
        
    last_high, last_low = df['high'].iloc[highs_idx[-1]], df['low'].iloc[lows_idx[-1]]
    swing_range = last_high - last_low
    if swing_range <= 0: return None
    
    swing_data = {"last_swing_high": round(last_high, 3), "last_swing_low": round(last_low, 3)}
    swing_data["ote_bullish"] = {"top": round(last_high - (swing_range * 0.618), 3), "bottom": round(last_high - (swing_range * 0.786), 3)}
    swing_data["ote_bearish"] = {"bottom": round(last_low + (swing_range * 0.618), 3), "top": round(last_low + (swing_range * 0.786), 3)}
    return swing_data

def detect_smc_features(df, swings, pdh, pdl):
    df = df.copy()
    smc = {"fvg_bullish": "None", "fvg_bearish": "None", "liquidity_sweep": "None"}
    
    # VWAP
    df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3
    df['vwap'] = (df['typical_price'] * df['tick_volume']).cumsum() / df['tick_volume'].cumsum()
    cur_vwap, cur_p = df['vwap'].iloc[-1], df['close'].iloc[-1]
    smc["vwap"] = f"{'ABOVE' if cur_p > cur_vwap else 'BELOW'} VWAP"

    # FVG (Unmitigated)
    for i in range(len(df)-3, len(df)-20, -1):
        if df['low'].iloc[i+1] > df['high'].iloc[i-1] and min(df['low'].iloc[i+1:]) > df['high'].iloc[i-1]:
            smc["fvg_bullish"] = f"YES ({round(df['high'].iloc[i-1],3)} to {round(df['low'].iloc[i+1],3)})"
            break
        elif df['high'].iloc[i+1] < df['low'].iloc[i-1] and max(df['high'].iloc[i+1:]) < df['low'].iloc[i-1]:
            smc["fvg_bearish"] = f"YES ({round(df['low'].iloc[i-1],3)} to {round(df['high'].iloc[i+1],3)})"
            break

    # Liquidity Sweeps (เช็คทั้ง M5 Swings และ PDH/PDL)
    curr = df.iloc[-1]
    if pdh != "N/A" and curr['high'] > pdh and curr['close'] < pdh: smc["liquidity_sweep"] = "MAJOR PDH SWEPT!"
    elif pdl != "N/A" and curr['low'] < pdl and curr['close'] > pdl: smc["liquidity_sweep"] = "MAJOR PDL SWEPT!"
    elif curr['high'] > swings["last_swing_high"] and curr['close'] < swings["last_swing_high"]: smc["liquidity_sweep"] = "M5 BUYSIDE SWEPT"
    elif curr['low'] < swings["last_swing_low"] and curr['close'] > swings["last_swing_low"]: smc["liquidity_sweep"] = "M5 SELLSIDE SWEPT"
        
    return smc

# ==========================================
# 🎯 4. Smart Execution
# ==========================================
def place_sniper_order(signal, entry_price, sl, tp, symbol, lot_size):
    tick = mt5.symbol_info_tick(symbol)
    if not tick: return False
    
    is_market = False
    if signal == "BUY":
        if tick.ask <= entry_price:
            order_type, entry_price, is_market = mt5.ORDER_TYPE_BUY, tick.ask, True
        else:
            order_type = mt5.ORDER_TYPE_BUY_LIMIT
    else: # SELL
        if tick.bid >= entry_price:
            order_type, entry_price, is_market = mt5.ORDER_TYPE_SELL, tick.bid, True
        else:
            order_type = mt5.ORDER_TYPE_SELL_LIMIT

    request = {
        "action": mt5.TRADE_ACTION_DEAL if is_market else mt5.TRADE_ACTION_PENDING,
        "symbol": symbol, "volume": float(lot_size), "type": order_type,
        "price": float(entry_price), "sl": float(sl), "tp": float(tp),
        "deviation": 20, "magic": 9999, "comment": "Sniper Elite",
        "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    res = mt5.order_send(request)
    if res.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"✅ 🟢 [EXECUTED] {signal} at {entry_price} | Ticket: {res.order}")
    else:
        print(f"❌ 🔴 [FAILED] {res.comment} (Code: {res.retcode})")

# ==========================================
# 🧠 5. AI Brain 
# ==========================================
def run_trading_bot():
    if not mt5.initialize(): return
    
    session, min_conf = get_session_info()
    cur_time_str = datetime.now(bkk_tz).strftime('%H:%M:%S')

    if session == "KILL_SWITCH_ACTIVE":
        print(f"⏳ {cur_time_str} | 🛑 KILL SWITCH ACTIVE (News/NY Open) - พักรบหลบพายุ!")
        mt5.shutdown()
        return

    # ดึง Data 3 Timeframes
    df_h4 = fetch_data(SYMBOL, mt5.TIMEFRAME_H4, 20)
    df_m15 = fetch_data(SYMBOL, mt5.TIMEFRAME_M15, 20)
    df_m5 = fetch_data(SYMBOL, mt5.TIMEFRAME_M5, 200)
    if df_h4 is None or df_m15 is None or df_m5 is None: return

    pdh, pdl = get_major_liquidity()
    swings = find_swings_and_ote(df_m5, n=5)
    
    cur_p = df_m5['close'].iloc[-1]
    
    if swings is None:
        print(f"⏳ {cur_time_str} | Price: {cur_p} | ⚠️ กราฟไม่มีสวิงที่ชัดเจน (รอสร้างโครงสร้าง)")
        mt5.shutdown()
        return

    h4_trend = get_market_structure(df_h4)
    m15_trend = get_market_structure(df_m15, order=2) # เพิ่ม M15 Narrative
    smc = detect_smc_features(df_m5, swings, pdh, pdl)
    atr = (df_m5['high'] - df_m5['low']).rolling(14).mean().iloc[-1]
    
    recent_pa = df_m5[['time', 'open', 'high', 'low', 'close']].tail(8).to_string(index=False)

    rec_buy = smc['fvg_bullish'].split("to ")[-1].replace(")","") if "YES" in smc['fvg_bullish'] else swings['ote_bullish']['top']
    rec_sell = smc['fvg_bearish'].split("to ")[0].split(": ")[-1].replace(")","") if "YES" in smc['fvg_bearish'] else swings['ote_bearish']['bottom']

    # อัปเกรด Prompt เป็นภาษาอังกฤษทั้งหมด เพื่อความแม่นยำ 100% แต่บังคับตอบ JSON เป็นภาษาไทย
    prompt = f"""
    You are an elite, aggressive SMC/ICT pro trader best friend. No fluff. No warnings.
    Analyze the market context using English logic, but output ONLY a valid JSON format with Thai language strings for 'analysis' and 'logic'.

    [MARKET CONTEXT]
    - Price: {cur_p} | Session: {session}
    - HTF Narrative: H4 is {h4_trend}, M15 Order Flow is {m15_trend}
    - Major Liquidity: PDH = {pdh}, PDL = {pdl}
    - M5 SMC: Sweep = {smc['liquidity_sweep']}
    - FVG Status: Bullish = {smc['fvg_bullish']}, Bearish = {smc['fvg_bearish']}
    - Momentum: {smc['vwap']}
    - Buy OTE: {swings['ote_bullish']}, Sell OTE: {swings['ote_bearish']}
    
    [RECENT PRICE ACTION M5]
    {recent_pa}
    
    [EXECUTION RULES - STRICT]
    1. A+ Setup = Major Sweep (PDH/PDL or M5) + FVG + OTE overlap + VWAP confluence.
    2. Minimum confidence for a trade is {min_conf}%. If confluences < 3, output "WAIT".
    3. CRITICAL BUG FIX: If an A+ Setup exists, YOU MUST OUTPUT 'BUY' or 'SELL'. DO NOT output 'WAIT' just because the current price is far from the entry zone. The system will automatically place a LIMIT ORDER at the entry zone to wait for the retracement.
    4. MANDATORY ENTRIES: If BUY, entry_price = {rec_buy}. If SELL, entry_price = {rec_sell}.
    
    JSON Template:
    {{
      "analysis": "[Thai] Aggressive, 2-sentence market analysis",
      "decision": {{
        "signal": "BUY" | "SELL" | "WAIT",
        "confidence": 0,
        "entry_price": 0.0,
        "logic": "[Thai] 1-sentence hardcore reasoning"
      }}
    }}
    """

    try:
        response = client.models.generate_content(
            model=AI_MODEL, contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.0)
        )
        res = json.loads(response.text)
        dec = res['decision']
        
        # กรองการแสดงผล Terminal ให้สะอาดตา
        if dec['signal'] == "WAIT" or dec['confidence'] < min_conf:
            print(f"⏳ {cur_time_str} | Price: {cur_p} | Status: สแกนไม่เจอ Setup / ทับมือ")
        else:
            print(f"\n🔥 {cur_time_str} | Price: {cur_p} | 🎯 SIGNAL: {dec['signal']} (Conf: {dec['confidence']}%)")
            print(f"🗣️ [Pro Friend]: {res['analysis']}")
            print(f"⚡ [Sniper Logic]: {dec['logic']}\n")

            entry_price = float(dec['entry_price'])
            point = mt5.symbol_info(SYMBOL).point
            spread = SPREAD_BUFFER_POINTS * point

            # RRR 1:5 รองรับกลยุทธ์ Run Trend
            if dec['signal'] == "BUY":
                sl = float(swings['last_swing_low']) - (atr * 0.5) - spread
                tp = entry_price + (entry_price - sl) * 5.0 
            else:
                sl = float(swings['last_swing_high']) + (atr * 0.5) + spread
                tp = entry_price - (sl - entry_price) * 5.0 
            
            place_sniper_order(dec['signal'], round(entry_price, 3), round(sl, 3), round(tp, 3), SYMBOL, LOT_SIZE)

    except Exception as e: 
        print(f"⚠️ {cur_time_str} | Error API/Logic: {e}")
    mt5.shutdown()

# ==========================================
# ⏳ 6. Loop อัจฉริยะ (รันทุกการปิดแท่ง 5 นาที)
# ==========================================
def wait_for_next_candle(tf_minutes=5):
    now = datetime.now()
    minutes_passed = now.minute % tf_minutes
    seconds_passed = now.second
    sec_to_wait = (tf_minutes * 60) - ((minutes_passed * 60) + seconds_passed) + 2
    time.sleep(sec_to_wait)

if __name__ == "__main__":
    print(f"\n{'='*50}")
    print(f"🤖 AI SMC/ICT Pro Sniper Bot (V.Final) | {SYMBOL}")
    print(f"🛡️ Features: M15 Narrative, PDH/PDL, Kill Switch")
    print(f"{'='*50}\n")
    while True:
        run_trading_bot()
        wait_for_next_candle()