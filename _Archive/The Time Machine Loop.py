import pandas as pd

# 1. โหลดข้อมูลที่เตรียมไว้
df_m5_full = pd.read_csv("xauusd_m5_history.csv")
df_m5_full['time'] = pd.to_datetime(df_m5_full['time'])

# เริ่มลูปตั้งแต่แท่งที่ 500 (เพื่อให้มีข้อมูลย้อนหลังพอคำนวณ EMA200/ATR)
for i in range(500, len(df_m5_full)):
    
    # --- A. ตัดภาพอดีต (Slicing) ---
    # ให้บอทเห็นข้อมูลแค่ถึงแท่งปัจจุบัน (i)
    current_m5_view = df_m5_full.iloc[:i].copy()
    current_candle = current_m5_view.iloc[-1]
    current_time = current_candle['time']
    
    # (ในของจริง คุณต้องตัด df_h1 และ df_d1 ให้เวลาตรงกับ current_time ด้วย)
    
    # --- B. บริหารจัดการออเดอร์เก่า (Check TP/SL) ---
    # ก่อนจะหา Setup ใหม่ ต้องเช็คก่อนว่าแท่งปัจจุบันนี้ ไปชน SL หรือ TP ของไม้ที่เปิดไว้ไหม
    for trade in active_trades[:]: # ใช้ [:] เพื่อ copy list เวลา loop
        if trade['signal'] == 'BUY':
            if current_candle['low'] <= trade['sl']: # ชน SL
                balance -= trade['risk_amount']
                trade['exit_price'] = trade['sl']
                trade['pnl'] = -trade['risk_amount']
                trade_history.append(trade)
                active_trades.remove(trade)
            elif current_candle['high'] >= trade['tp']: # ชน TP
                reward = trade['risk_amount'] * 2.5 # RR 1:2.5
                balance += reward
                trade['exit_price'] = trade['tp']
                trade['pnl'] = reward
                trade_history.append(trade)
                active_trades.remove(trade)
        # (เขียน Logic ฝั่ง SELL คล้ายๆ กัน)

    # --- C. สแกนหา Setup ใหม่ ---
    # โยนข้อมูลจำลองเข้าไปใน V.7.1 Engine
    setup = analyze_setup(current_m5_view, df_h1_view, df_d1_view)
    
    # --- D. จำลองการยิงออเดอร์ ---
    if setup.signal != "WAIT" and setup.score >= 70: # เงื่อนไขคะแนน Gate 3
        # ถ้าคะแนนถึง สร้างออเดอร์จำลองใส่กระเป๋าไว้
        risk_per_trade = balance * 0.01 # เสี่ยง 1%
        
        new_trade = {
            "entry_time": current_time,
            "signal": setup.signal,
            "entry_price": setup.entry,
            "sl": setup.sl,
            "tp": setup.entry + (abs(setup.entry - setup.sl) * 2.5) if setup.signal == 'BUY' else setup.entry - (abs(setup.entry - setup.sl) * 2.5),
            "risk_amount": risk_per_trade,
            "score": setup.score
        }
        active_trades.append(new_trade)
        # หมายเหตุ: เพื่อความง่าย โค้ดนี้จำลองการเข้าแบบ Market Order ทันที
        # ถ้าจะจำลอง Pending Order ต้องเขียนตรรกะรอให้ราคาย่อมาชน setup.entry ในแท่งถัดๆ ไปด้วย