import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from scipy.signal import argrelextrema
import json
import time
import os
from datetime import datetime, time as dtime
import pytz
from google import genai
from google.genai import types
import mplfinance as mpf
from PIL import Image

# ==========================================
# ⚙️ 1. Configuration 
# ==========================================
GEMINI_API_KEY = "" 
SYMBOL = "XAUUSDm"
LOT_SIZE = 0.01 
AI_MODEL = "gemini-2.5-flash"
SPREAD_BUFFER_POINTS = 30 
RISK_REWARD_RATIO = 2.0 # 🎯 เพิ่ม RR = 1:2 เพื่อการเติบโตของพอร์ต

client = genai.Client(api_key=GEMINI_API_KEY)
bkk_tz = pytz.timezone('Asia/Bangkok')

# ==========================================
# 🕒 2. Kill Switch & Session
# ==========================================
def get_session_info():
    now = datetime.now(bkk_tz).time()
    kill_start, kill_end = dtime(19, 25), dtime(20, 35)
    if kill_start <= now <= kill_end: return "KILL_SWITCH_ACTIVE"
    
    # ขยายขอบเขตช่วงเวลาเทรดหลักที่มี Volume
    london = (dtime(14, 0), dtime(18, 0))
    ny = (dtime(19, 0), dtime(23, 0))
    asian = (dtime(7, 0), dtime(12, 0))
    
    if london[0] <= now <= london[1]: return "LONDON_KILLZONE"
    elif ny[0] <= now <= ny[1]: return "NEW_YORK_KILLZONE"
    elif asian[0] <= now <= asian[1]: return "ASIAN_RANGE"
    return "OUT_OF_SESSION"

# ==========================================
# 📊 3. Core Math & Strict Structure
# ==========================================
def fetch_data(symbol, timeframe, num_candles, shift=0):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, shift, num_candles)
    if rates is None or len(rates) == 0: return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('time', inplace=True)
    return df

def get_market_structure(df, order=3):
    highs = argrelextrema(df['high'].values, np.greater_equal, order=order)[0]
    lows = argrelextrema(df['low'].values, np.less_equal, order=order)[0]
    
    if len(highs) >= 2 and len(lows) >= 2:
        hh = df['high'].iloc[highs[-1]] > df['high'].iloc[highs[-2]]
        hl = df['low'].iloc[lows[-1]] > df['low'].iloc[lows[-2]]
        lh = df['high'].iloc[highs[-1]] < df['high'].iloc[highs[-2]]
        ll = df['low'].iloc[lows[-1]] < df['low'].iloc[lows[-2]]
        
        if hh and hl: return "BULLISH"
        elif lh and ll: return "BEARISH"
    return "RANGING" # 🛡️ ไม่เทรดถ้าโครงสร้างไม่ชัดเจน

def extract_smc_data(df_m5, h4_trend, m15_trend):
    df_m5['typical_price'] = (df_m5['high'] + df_m5['low'] + df_m5['close']) / 3
    df_m5['vwap'] = (df_m5['typical_price'] * df_m5['tick_volume']).cumsum() / df_m5['tick_volume'].cumsum()
    cur_p = df_m5['close'].iloc[-1]
    cur_vwap = df_m5['vwap'].iloc[-1]

    highs_idx = argrelextrema(df_m5['high'].values, np.greater_equal, order=5)[0]
    lows_idx = argrelextrema(df_m5['low'].values, np.less_equal, order=5)[0]
    if len(highs_idx) == 0 or len(lows_idx) == 0: return None
    
    last_high, last_low = df_m5['high'].iloc[highs_idx[-1]], df_m5['low'].iloc[lows_idx[-1]]
    swing_range = last_high - last_low
    if swing_range <= 0: return None

    # 🎯 ค้นหา Fresh FVG (ที่ยังไม่ถูก Mitigate)
    fvg_bullish_zone, fvg_bearish_zone = None, None
    for i in range(len(df_m5)-3, len(df_m5)-30, -1):
        # Bullish FVG
        if df_m5['low'].iloc[i+1] > df_m5['high'].iloc[i-1]:
            fvg_top, fvg_bottom = df_m5['low'].iloc[i+1], df_m5['high'].iloc[i-1]
            # Check Mitigation
            if df_m5['low'].iloc[i+2:].min() > fvg_bottom:
                fvg_bullish_zone = (fvg_bottom, fvg_top)
                break
        # Bearish FVG
        elif df_m5['high'].iloc[i+1] < df_m5['low'].iloc[i-1]:
            fvg_top, fvg_bottom = df_m5['low'].iloc[i-1], df_m5['high'].iloc[i+1]
            # Check Mitigation
            if df_m5['high'].iloc[i+2:].max() < fvg_top:
                fvg_bearish_zone = (fvg_bottom, fvg_top)
                break

    # 🎯 OTE Zones (0.618 - 0.786)
    ote_bullish_zone = (last_high - (swing_range * 0.786), last_high - (swing_range * 0.618))
    ote_bearish_zone = (last_low + (swing_range * 0.618), last_low + (swing_range * 0.786))

    pre_signal, zone_upper, zone_lower, sl, zone_type = "WAIT", 0.0, 0.0, 0.0, "NONE"

    # 🛡️ เงื่อนไข Trend Alignment
    if h4_trend == "BULLISH" and m15_trend == "BULLISH" and cur_p > cur_vwap:
        if fvg_bullish_zone and cur_p <= fvg_bullish_zone[1] + (swing_range*0.1): 
            pre_signal, zone_lower, zone_upper, sl, zone_type = "BUY", fvg_bullish_zone[0], fvg_bullish_zone[1], last_low, "FVG"
        elif cur_p <= ote_bullish_zone[1]:
            pre_signal, zone_lower, zone_upper, sl, zone_type = "BUY", ote_bullish_zone[0], ote_bullish_zone[1], last_low, "OTE"

    elif h4_trend == "BEARISH" and m15_trend == "BEARISH" and cur_p < cur_vwap:
        if fvg_bearish_zone and cur_p >= fvg_bearish_zone[0] - (swing_range*0.1):
            pre_signal, zone_lower, zone_upper, sl, zone_type = "SELL", fvg_bearish_zone[0], fvg_bearish_zone[1], last_high, "FVG"
        elif cur_p >= ote_bearish_zone[0]:
            pre_signal, zone_lower, zone_upper, sl, zone_type = "SELL", ote_bearish_zone[0], ote_bearish_zone[1], last_high, "OTE"

    # 🧮 คำนวณความแม่นยำให้ AI
    is_in_zone = False
    if pre_signal == "BUY" and (zone_lower <= df_m5['low'].iloc[-1] <= zone_upper or zone_lower <= df_m5['close'].iloc[-1] <= zone_upper):
        is_in_zone = True
    elif pre_signal == "SELL" and (zone_lower <= df_m5['high'].iloc[-1] <= zone_upper or zone_lower <= df_m5['close'].iloc[-1] <= zone_upper):
        is_in_zone = True

    return {
        "pre_signal": pre_signal, "zone_upper": zone_upper, "zone_lower": zone_lower, 
        "sl": sl, "zone_type": zone_type, "is_in_zone": is_in_zone
    }

# ==========================================
# 📸 4. AI Vision
# ==========================================
def create_chart_image(df, zone_upper, zone_lower, sl):
    filename = "temp_chart.png"
    df_plot = df.iloc[-60:] # 📈 ขยายเป็น 60 แท่ง ให้ AI เห็นสวิงทั้งหมด
    
    # วาดโซนด้วยเส้นทึบสองเส้น (ขอบบนและขอบล่างของโซน)
    line_config = dict(hlines=[zone_upper, zone_lower, sl], 
                       colors=['magenta', 'magenta', 'cyan'], 
                       linestyle=['-', '-', '--'], linewidths=[1.5, 1.5, 2])
    
    mpf.plot(df_plot, type='candle', style='charles', hlines=line_config, savefig=filename)
    return filename

# ==========================================
# 🎯 5. Execution & Trailing
# ==========================================
def place_sniper_order(signal, entry_price, sl, symbol):
    tick = mt5.symbol_info_tick(symbol)
    point = mt5.symbol_info(symbol).point
    spread = SPREAD_BUFFER_POINTS * point

    sl = sl - spread if signal == "BUY" else sl + spread
    
    price = tick.ask if signal == "BUY" else tick.bid
    risk = abs(price - sl)
    
    # 🎯 คำนวณ Take Profit ด้วย Risk/Reward 
    tp = price + (risk * RISK_REWARD_RATIO) if signal == "BUY" else price - (risk * RISK_REWARD_RATIO)
    
    order_type = mt5.ORDER_TYPE_BUY if signal == "BUY" else mt5.ORDER_TYPE_SELL

    request = {
        "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": float(LOT_SIZE), 
        "type": order_type, "price": float(price), "sl": float(sl), "tp": float(tp),
        "deviation": 20, "magic": 9999, "comment": "AI Sniper Pro",
        "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    res = mt5.order_send(request)
    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"✅ [EXECUTED] {signal} | Lot: {LOT_SIZE} | SL: {sl:.3f} | TP: {tp:.3f} | Ticket: {res.order}")
    else:
        print(f"❌ [FAILED] {res.comment if res else 'Unknown'} (Code: {res.retcode if res else 'None'})")

def trailing_stop(symbol, trail_points=500):
    positions = mt5.positions_get(symbol=symbol)
    if not positions: return
    point = mt5.symbol_info(symbol).point
    tick = mt5.symbol_info_tick(symbol)

    for pos in positions:
        if pos.magic != 9999: continue
        new_sl = pos.sl
        if pos.type == mt5.ORDER_TYPE_BUY and tick.bid - pos.price_open > trail_points * point:
            new_sl = tick.bid - (trail_points * point)
        elif pos.type == mt5.ORDER_TYPE_SELL and pos.price_open - tick.ask > trail_points * point:
            new_sl = tick.ask + (trail_points * point)
                
        if (pos.type == mt5.ORDER_TYPE_BUY and new_sl > pos.sl) or (pos.type == mt5.ORDER_TYPE_SELL and (new_sl < pos.sl or pos.sl == 0.0)):
            mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "symbol": symbol, "position": pos.ticket, "sl": new_sl, "tp": pos.tp})
            print(f"🛡️ ขยับ SL บังทุน ล็อกกำไรไม้ {pos.ticket}")

# ==========================================
# 🧠 6. AI Brain 
# ==========================================
def run_trading_bot():
    if not mt5.initialize(): return
    session = get_session_info()
    cur_time_str = datetime.now(bkk_tz).strftime('%H:%M:%S')

    trailing_stop(SYMBOL, trail_points=500) 

    if session == "KILL_SWITCH_ACTIVE":
        print(f"⏳ {cur_time_str} | 🛑 KILL SWITCH - พักรบ")
        mt5.shutdown(); return
        
    # 🛡️ บังคับเทรดเฉพาะช่วงที่มี Volume (London / NY)
    if session not in ["LONDON_KILLZONE", "NEW_YORK_KILLZONE"]:
        print(f"⏳ {cur_time_str} | 💤 อยู่นอกช่วง Killzone (Session: {session}) -> ทับมือ")
        mt5.shutdown(); return

    positions = mt5.positions_get(symbol=SYMBOL)
    if positions is not None and any(p.magic == 9999 for p in positions):
        print(f"⏳ {cur_time_str} | 💼 มีออเดอร์เปิดอยู่แล้ว กำลังบริหารจัดการไม้ -> ทับมือ")
        mt5.shutdown(); return

    df_h4 = fetch_data(SYMBOL, mt5.TIMEFRAME_H4, 20)
    df_m15 = fetch_data(SYMBOL, mt5.TIMEFRAME_M15, 50)
    df_m5 = fetch_data(SYMBOL, mt5.TIMEFRAME_M5, 200)
    if df_h4 is None or df_m15 is None or df_m5 is None: return

    h4_trend = get_market_structure(df_h4)
    m15_trend = get_market_structure(df_m15, order=2)
    
    if h4_trend == "RANGING" or m15_trend == "RANGING":
        print(f"⏳ {cur_time_str} | 📉 โครงสร้างราคา RANGING ไม่ชัดเจน -> ทับมือ")
        mt5.shutdown(); return

    smc_data = extract_smc_data(df_m5, h4_trend, m15_trend)

    if smc_data is None or smc_data['pre_signal'] == "WAIT":
        print(f"⏳ {cur_time_str} | ทรงยังไม่ได้ (รอ M15/VWAP/Zone คอนเฟิร์ม) -> ทับมือ")
        mt5.shutdown(); return

    # คำนวณข้อมูล % แท่งเทียนส่งให้ AI
    last_3 = df_m5.tail(3).copy()
    last_3['total_range'] = last_3['high'] - last_3['low']
    last_3['total_range'].replace(0, 0.001, inplace=True)
    
    last_3['upper_wick_%'] = ((last_3['high'] - last_3[['open', 'close']].max(axis=1)) / last_3['total_range'] * 100).round(1)
    last_3['lower_wick_%'] = ((last_3[['open', 'close']].min(axis=1) - last_3['low']) / last_3['total_range'] * 100).round(1)
    last_3['body_%'] = (abs(last_3['open'] - last_3['close']) / last_3['total_range'] * 100).round(1)
    
    price_context_str = last_3[['open', 'high', 'low', 'close', 'upper_wick_%', 'lower_wick_%', 'body_%']].to_string()
    
    entry_price = smc_data['zone_upper'] if smc_data['pre_signal'] == "BUY" else smc_data['zone_lower']

    chart_image_path = create_chart_image(df_m5, smc_data['zone_upper'], smc_data['zone_lower'], smc_data['sl'])
    img = Image.open(chart_image_path)

    print(f"👁️ โครงสร้างเป๊ะ! โยนกราฟให้ AI ประเมิน {smc_data['pre_signal']} ที่โซน...")

    # 🎯 อัปเดต Prompt ตัดการให้ AI กะระยะด้วยตาเปล่า ใช้ตัวแปร IS_IN_ZONE 
    prompt = f"""
    You are an elite SMC/ICT algorithm. 
    Python has verified all mathematical conditions. Your job is to confirm the Entry Trigger based on Price Action.

    [NUMERICAL CONTEXT (Last 3 M5 Candles)]
    {price_context_str}
    - Python Verified "IS_IN_ZONE": {smc_data['is_in_zone']} (True = Price has successfully tapped the zone)

    [CHART LEGEND]
    - Setup Direction: {smc_data['pre_signal']}
    - Two Solid Magenta Lines: The Entry Zone ({smc_data['zone_type']}).
    - Cyan Dashed Line: Stop Loss.
    
    [EXECUTION RULES - STRICT]
    1. If "IS_IN_ZONE" is False: Output "WAIT". Do not enter early.
    2. If Direction is BUY & "IS_IN_ZONE" is True:
       - Output "BUY" IF the rightmost candle shows strong rejection (lower_wick_% > 40%) OR is a bullish engulfing body closing upwards.
    3. If Direction is SELL & "IS_IN_ZONE" is True:
       - Output "SELL" IF the rightmost candle shows strong rejection (upper_wick_% > 40%) OR is a bearish engulfing body closing downwards.
    4. Output "WAIT" if the price breaks aggressively through the zone towards the Stop Loss with no sign of rejection.

    [OUTPUT FORMAT]
    Write the content for 'analysis' and 'logic' in THAI language. Output ONLY valid JSON:
    {{
      "analysis": "2-sentence objective analysis combining price action and the zone.",
      "decision": {{
        "signal": "BUY" | "SELL" | "WAIT",
        "logic": "1-sentence precise reasoning."
      }}
    }}
    """

    try:
        response = client.models.generate_content(
            model=AI_MODEL, contents=[prompt, img],
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.0)
        )
        res = json.loads(response.text)
        dec = res['decision']
        
        if dec['signal'] == "WAIT":
            print(f"🛑 AI สั่งเบรก! ทับมือ! | เหตุผล: {dec['logic']}\n")
        else:
            print(f"\n🔥 {cur_time_str} | 🎯 LETS GO SIGNAL: {dec['signal']}")
            print(f"🗣️ [AI Analysis]: {res['analysis']}")
            print(f"⚡ [Logic]: {dec['logic']}\n")
            
            place_sniper_order(dec['signal'], entry_price, smc_data['sl'], SYMBOL)

    except Exception as e: 
        print(f"⚠️ {cur_time_str} | API Error: {e}")
    finally:
        if os.path.exists(chart_image_path): os.remove(chart_image_path)
    mt5.shutdown()

def wait_for_next_candle(tf_minutes=5):
    now = datetime.now()
    sec_to_wait = (tf_minutes * 60) - ((now.minute % tf_minutes * 60) + now.second) + 2
    time.sleep(sec_to_wait)

if __name__ == "__main__":
    while True:
        run_trading_bot()
        wait_for_next_candle()