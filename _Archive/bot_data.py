import MetaTrader5 as mt5
import pandas as pd

# 1. เชื่อมต่อ MT5
if not mt5.initialize():
    print("❌ เชื่อมต่อ MT5 ไม่สำเร็จ")
    quit()

symbol = "XAUUSDm" # ใช้ชื่อ Symbol ที่คุณหาเจอเมื่อกี้

# 2. ฟังก์ชันสำหรับดึงข้อมูลแท่งเทียน
def get_candle_data(symbol, timeframe, num_candles):
    # ดึงข้อมูลจากปัจจุบันย้อนหลังไป num_candles แท่ง
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, num_candles)
    
    if rates is None:
        print(f"❌ ดึงข้อมูล {symbol} ไม่สำเร็จ")
        return None
        
    # แปลงข้อมูลเป็นตาราง (DataFrame) ให้อ่านง่าย
    df = pd.DataFrame(rates)
    # แปลงเวลาจากวินาที (Timestamp) ให้เป็นเวลาที่มนุษย์อ่านเข้าใจ
    df['time'] = pd.to_datetime(df['time'], unit='s') 
    
    # เลือกมาเฉพาะคอลัมน์ที่จำเป็น
    df = df[['time', 'open', 'high', 'low', 'close']]
    return df

# 3. ลองดึงข้อมูล Timeframe M5 ย้อนหลัง 5 แท่งล่าสุด
print("⏳ กำลังดึงข้อมูลแท่งเทียน...")
df_m5 = get_candle_data(symbol, mt5.TIMEFRAME_M5, 5)

if df_m5 is not None:
    print(f"\n📊 ข้อมูลแท่งเทียน M5 (5 แท่งล่าสุด) ของ {symbol}:")
    print(df_m5)

# ปิดการเชื่อมต่อ
mt5.shutdown()