import MetaTrader5 as mt5

# 1. สั่งเชื่อมต่อกับ MT5 ที่เปิดอยู่
if not mt5.initialize():
    print("❌ เชื่อมต่อ MT5 ไม่สำเร็จ กรุณาตรวจสอบว่าเปิดโปรแกรม MT5 ไว้หรือไม่")
    mt5.shutdown()
    quit()

print("✅ เชื่อมต่อ MT5 สำเร็จแล้ว!")

# 2. ลองดึงข้อมูลของทองคำมาทดสอบ
symbol = "XAUUSDm" # บางโบรคเกอร์อาจจะเป็น XAUUSD.m หรือ GOLD ให้เปลี่ยนตามชื่อใน MT5 ของคุณ
symbol_info = mt5.symbol_info(symbol)

if symbol_info is None:
    print(f"❌ ไม่พบสัญลักษณ์ {symbol} ใน MT5 ของคุณ (ลองเช็คชื่อ Symbol อีกครั้ง)")
else:
    print(f"🎯 ค้นหา {symbol} เจอแล้ว!")
    print(f"💵 ราคาปัจจุบัน (Bid): {symbol_info.bid}")
    print(f"💵 ราคาปัจจุบัน (Ask): {symbol_info.ask}")

# ปิดการเชื่อมต่อ
mt5.shutdown()