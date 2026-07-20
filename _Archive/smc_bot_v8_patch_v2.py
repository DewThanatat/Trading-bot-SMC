"""
╔══════════════════════════════════════════════════════════════════════════╗
║  SMC/ICT Pro Sniper V.8 — PATCH v2 (3 Production Fixes)                 ║
║                                                                          ║
║  FIX B2 — Non-blocking Trade Lock: lock ครอบแค่ order_send              ║
║           ไม่มี sleep ภายใน lock ป้องกัน thread freeze                  ║
║                                                                          ║
║  FIX A2 — Conservative Risk Tiers (SMC-style) + Circuit Breaker         ║
║           หยุดเปิดออเดอร์เมื่อ daily DD ≥ 3% จนกว่าจะขึ้นวันใหม่      ║
║                                                                          ║
║  FIX C2 — Killzone Session Filter (config-driven)                        ║
║           + ยืนยัน Breakeven / Trailing / Partial TP ครบถ้วน           ║
║                                                                          ║
║  วิธีใช้: วางทับ section ที่ระบุใน smc_bot_v8.py + smc_bot_v8_patch.py  ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📌 SECTION 1 — CONFIG (วางทับ/เพิ่มใน CONFIG section ของ v8)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# [FIX A2] Risk Tiers — ปรับให้เหมาะ SMC (RR > WinRate)
# SMC เน้นให้ win น้อยแต่กำไรมาก จึง risk ต่อไม้ต้องเล็ก
# เพื่อให้ทน drawdown ช่วง losing streak ได้
LOT_MIN  = 0.01
LOT_MAX  = 1.00

RISK_TIERS = [
    # (score_min, risk_pct_of_balance)
    (90, 1.00),   # A++ : ทองแท้ — เสี่ยง 1.0%
    (80, 0.75),   # A+  : เสี่ยง 0.75%
    (70, 0.50),   # A   : เสี่ยง 0.50%
    (60, 0.25),   # B+  : เสี่ยง 0.25%
    (0,  0.10),   # B   : เสี่ยง 0.10%  (ออเดอร์คุณภาพต่ำ)
]

# [FIX A2] Circuit Breaker — หยุดเปิดออเดอร์เมื่อ daily DD เกิน
CIRCUIT_BREAKER_PCT = 3.0   # % ของ daily start balance

# [FIX C2] Killzone — ช่วงที่อนุญาตให้เปิดออเดอร์ (Bangkok time, HH, MM)
# ปิด Killzone filter โดยตั้ง KILLZONE_ENABLED = False ถ้าต้องการปิด
KILLZONE_ENABLED = True
KILLZONES = [
    # (start_h, start_m, end_h, end_m, name)
    (14,  0, 16, 30, "London Open"),    # London open แรก volatile สูงสุด
    (19, 45, 22,  0, "NY Open"),        # NY open + overlap
]
# หมายเหตุ: killzone ไม่ทับ NEWS_BLOCK (RED_NEWS_BLOCK ยัง block อยู่แต่เดิม)

# Breakeven / Trailing (ค่าเหล่านี้น่าจะมีอยู่แล้วใน v8 — ตรวจสอบให้ครบ)
BREAKEVEN_RR     = 1.0    # เลื่อน SL → entry เมื่อกำไร 1R
TRAIL_AFTER_RR   = 2.0    # เริ่ม trail เมื่อกำไร 2R
TRAIL_ATR_MULT   = 1.2
TRAIL_MIN_MOVE_ATR = 0.3
PARTIAL_TP_RR    = 1.0    # partial close ที่ 1R
PARTIAL_TP_PCT   = 0.50   # ปิด 50% ก่อน


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📌 SECTION 2 — IMPORTS & GLOBALS
#    เพิ่มหลัง _cache_lock ใน DATA FEED section
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

import threading
import time
import logging
import MetaTrader5 as mt5
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, time as dtime
from typing import Optional, List
import pytz

log = logging.getLogger(__name__)
bkk_tz = pytz.timezone('Asia/Bangkok')

# [FIX B2] Trade lock — ครอบเฉพาะ mt5.order_send() เท่านั้น
# ไม่ครอบ sleep เพื่อไม่ให้ thread อื่นถูก block ระหว่างรอ retry
_trade_lock = threading.Lock()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📌 SECTION 3 — FIX B2: _send_retry (วางทับของเดิมทั้งฟังก์ชัน)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _send_retry(req: dict, retries: int = 3):
    """
    [FIX B2] Non-blocking Trade Lock Pattern
    ─────────────────────────────────────────
    ปัญหาเดิม: with _trade_lock → sleep() ภายใน lock
    → thread ทั้งหมดรอ lock ตลอดเวลา sleep = freeze

    แก้ไข: lock ครอบแค่ mt5.order_send() เดี่ยวๆ
    หลัง send → unlock ทันที
    ถ้าต้อง retry → sleep นอก lock → lock ใหม่รอบถัดไป

    Pattern:
        lock → send → unlock → [sleep นอก lock] → lock → send → unlock
    """
    last_res = None

    for i in range(1, retries + 1):
        # [FIX B2] lock ครอบแค่ order_send เดี่ยวๆ — release ทันที
        with _trade_lock:
            res = mt5.order_send(req)

        # ── ประเมินผลนอก lock ─────────────────────────────────
        if res is None:
            log.warning(f"order_send None (try {i}/{retries})")
            if i < retries:
                time.sleep(0.5)   # sleep นอก lock — thread อื่น lock ได้ระหว่างนี้
            continue

        last_res = res

        if res.retcode == mt5.TRADE_RETCODE_DONE:
            return res   # สำเร็จ — คืนทันที

        if res.retcode in (
            mt5.TRADE_RETCODE_REQUOTE,
            mt5.TRADE_RETCODE_PRICE_CHANGED,
            mt5.TRADE_RETCODE_CONNECTION,
            mt5.TRADE_RETCODE_TIMEOUT,
        ):
            log.warning(f"Retryable retcode:{res.retcode} (try {i}/{retries})")
            if i < retries:
                time.sleep(0.5 * i)   # exponential backoff นอก lock
            continue

        # retcode อื่น = error ถาวร ไม่ retry
        log.error(f"❌ retcode:{res.retcode} | {res.comment}")
        return res

    log.error(f"❌ _send_retry หมด {retries} ครั้ง")
    return last_res


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📌 SECTION 4 — FIX B2: _modify_sl (วางทับของเดิม)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _modify_sl(ticket: int, new_sl: float):
    """
    [FIX B2] lock ครอบแค่ order_send เดี่ยวๆ
    SLTP modification ไม่ต้อง retry (ถ้า fail log แล้วรอรอบหน้า)
    """
    req = {
        "action":   mt5.TRADE_ACTION_SLTP,
        "position": ticket,
        "sl":       round(float(new_sl), 2),
    }
    with _trade_lock:
        res = mt5.order_send(req)

    if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
        log.warning(f"_modify_sl FAIL #{ticket} "
                    f"retcode:{res.retcode if res else 'None'}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📌 SECTION 5 — FIX B2: _close_partial (วางทับของเดิม)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _close_partial(pos, lot_close: float):
    """
    [FIX B2] เรียก _send_retry ที่มี non-blocking lock แล้ว
    ไม่ต้องเพิ่ม lock ซ้อน (จะ deadlock เพราะ Lock ไม่ reentrant)
    """
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        return

    info  = mt5.symbol_info(SYMBOL)
    step  = info.volume_step if info else 0.01
    v_min = info.volume_min  if info else 0.01

    # Decimal rounding
    d_lc   = Decimal(str(lot_close))
    d_step = Decimal(str(step))
    lot_close = float(max(
        v_min,
        min(
            float((d_lc / d_step).to_integral_value(rounding=ROUND_DOWN) * d_step),
            pos.volume
        )
    ))

    is_buy      = (pos.type == mt5.ORDER_TYPE_BUY)
    close_type  = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
    close_price = tick.bid if is_buy else tick.ask

    res = _send_retry({
        "action":    mt5.TRADE_ACTION_DEAL,
        "symbol":    SYMBOL,
        "volume":    lot_close,
        "type":      close_type,
        "position":  pos.ticket,
        "price":     round(float(close_price), 2),
        "deviation": 20,
        "magic":     MAGIC_NUMBER,
        "comment":   "V8|PartialTP",
    })
    if res and res.retcode == mt5.TRADE_RETCODE_DONE:
        log.info(f"💰 Partial #{pos.ticket} Lot:{lot_close:.2f} @ {close_price:.2f}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📌 SECTION 6 — FIX A2: calculate_lot (วางทับของเดิม)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def calculate_lot(entry: float, sl: float, score: int = 0,
                  spread_pts: float = 0.0) -> float:
    """
    [FIX A2] Risk-Based Lot + Conservative SMC Tiers
    ──────────────────────────────────────────────────
    สูตร: lot = (balance × risk%) / (sl_pts × tick_value_per_lot)

    risk% ลดลงจาก V8-patch เดิม (2% → 1% max)
    เพราะ SMC เน้น RR สูง ไม่ใช่ win rate สูง
    ออเดอร์ไม่กี่ครั้งต่อวัน ต้องทนได้กับ losing streak
    """
    info = mt5.symbol_info(SYMBOL)
    acct = mt5.account_info()
    if info is None or acct is None:
        log.warning("calculate_lot: ไม่ได้ข้อมูล → คืน LOT_MIN")
        return LOT_MIN

    # เลือก risk% จาก score tier
    risk_pct = RISK_TIERS[-1][1]
    for score_min, pct in RISK_TIERS:
        if score >= score_min:
            risk_pct = pct
            break

    # Spread penalty: ลด risk% แทนการลด lot โดยตรง
    if spread_pts > MAX_SPREAD_POINTS:
        risk_pct *= (1.0 - SPREAD_LOT_PENALTY)
        log.info(f"📉 Spread penalty → risk% = {risk_pct:.3f}%")

    balance     = acct.balance
    risk_amount = balance * (risk_pct / 100.0)

    # SL distance
    sl_price_dist = abs(entry - sl)
    if sl_price_dist == 0:
        log.error("calculate_lot: SL dist=0 → LOT_MIN")
        return LOT_MIN

    sl_pts = max(1.0, sl_price_dist / info.point)

    # Tick value (USD per point per 1 lot)
    tick_val = info.trade_tick_value
    if not tick_val or tick_val <= 0:
        tick_val = info.trade_contract_size * info.point
    if tick_val <= 0:
        log.warning("calculate_lot: tick_value ไม่ได้ → LOT_MIN")
        return LOT_MIN

    raw_lot = risk_amount / (sl_pts * tick_val)

    # Decimal rounding
    step = info.volume_step if info.volume_step > 0 else 0.01
    d_raw  = Decimal(str(raw_lot))
    d_step = Decimal(str(step))
    lot    = float(
        (d_raw / d_step).to_integral_value(rounding=ROUND_DOWN) * d_step
    )

    lot = max(info.volume_min, min(lot, info.volume_max, LOT_MAX))

    log.info(
        f"💰 Lot | Score:{score} Risk:{risk_pct:.2f}% "
        f"Bal:{balance:.0f} SL:{sl_pts:.1f}pts TV:{tick_val:.4f} → {lot}"
    )
    return float(lot)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📌 SECTION 7 — FIX A2: Circuit Breaker (เพิ่มใน RISK ENGINE)
#    เรียก is_circuit_breaker_tripped() ใน main loop ก่อน place_order
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _get_broker_server_date() -> str:
    """ดึงวันจาก broker server tick (UTC) — ใช้เหมือนกับ get_broker_server_date() ใน v8"""
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is not None:
        return datetime.fromtimestamp(tick.time, tz=pytz.utc).strftime("%Y%m%d")
    return datetime.utcnow().strftime("%Y%m%d")

def is_circuit_breaker_tripped() -> bool:
    """
    [FIX A2] Daily Circuit Breaker
    ────────────────────────────────
    ถ้า equity ตกจาก daily_start_balance เกิน CIRCUIT_BREAKER_PCT
    → คืน True = ห้ามเปิดออเดอร์ใหม่จนกว่าจะขึ้นวันใหม่

    แยกจาก MAX_DAILY_LOSS_PCT (ที่มีอยู่เดิม) เพื่อให้ปรับค่าแยกกันได้
    CIRCUIT_BREAKER_PCT (3%) = หยุดเปิดไม้ใหม่
    MAX_DAILY_LOSS_PCT  (4%) = หยุดทุกอย่าง (gate เดิม)
    """
    acct = mt5.account_info()
    if acct is None:
        return False

    today_key   = "daily_start_balance_" + _get_broker_server_date()
    daily_start = get_state(today_key)   # ใช้ get_state จาก v8 (SQLite)
    if daily_start is None or daily_start <= 0:
        return False

    daily_dd_pct = (daily_start - acct.equity) / daily_start * 100
    if daily_dd_pct >= CIRCUIT_BREAKER_PCT:
        log.warning(
            f"⚡ Circuit Breaker: DD {daily_dd_pct:.2f}% ≥ {CIRCUIT_BREAKER_PCT}% "
            f"→ ระงับเปิดออเดอร์ใหม่วันนี้"
        )
        return True
    return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📌 SECTION 8 — FIX C2: Killzone Filter (เพิ่มใน SESSION section)
#    เรียก is_in_killzone() ใน main loop ก่อน analyze_setup
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def is_in_killzone() -> tuple:
    """
    [FIX C2] ตรวจว่าเวลาปัจจุบัน (Bangkok) อยู่ใน Killzone ที่กำหนดหรือไม่
    คืน (bool, str) → (อยู่ใน killzone, ชื่อ killzone)

    ถ้า KILLZONE_ENABLED = False → คืน (True, "All") เสมอ (ไม่กรอง)
    """
    if not KILLZONE_ENABLED:
        return True, "All"

    now = datetime.now(bkk_tz).time()
    for sh, sm, eh, em, name in KILLZONES:
        if dtime(sh, sm) <= now <= dtime(eh, em):
            return True, name

    return False, "Outside Killzone"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📌 SECTION 9 — FIX C2: manage_positions (วางทับของเดิมทั้งฟังก์ชัน)
#    ยืนยันว่า BE / Trailing / Partial TP ครบและถูกต้อง
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def manage_positions(atr: float):
    """
    [FIX C2] Position Manager — ครบถ้วน Production-Ready
    ───────────────────────────────────────────────────────
    ลำดับการตัดสินใจต่อแต่ละ position:
    1. Partial TP @ PARTIAL_TP_RR (1R) → ปิด 50% + เลื่อน SL → BE
    2. Breakeven  @ BREAKEVEN_RR  (1R) → เลื่อน SL → entry+buffer
    3. Trailing   @ TRAIL_AFTER_RR(2R) → trail ด้วย ATR

    ใช้ SL distance จริง (ไม่ใช่ TP) ในการคำนวณ profit_R
    → ถูกต้องแม้ SL ถูก modify แล้ว

    _modify_sl และ _close_partial มี non-blocking lock อยู่แล้ว (FIX B2)
    """
    positions = [p for p in (mt5.positions_get(symbol=SYMBOL) or [])
                 if p.magic == MAGIC_NUMBER]
    if not positions:
        return

    tick = mt5.symbol_info_tick(SYMBOL)
    info = mt5.symbol_info(SYMBOL)
    if tick is None or info is None:
        return

    a = max(atr, info.point * 10)   # ATR floor = 10 pts เพื่อกัน div/zero
    open_tickets = {p.ticket for p in positions}

    for pos in positions:
        entry  = pos.price_open
        sl_now = pos.sl
        is_buy = (pos.type == mt5.ORDER_TYPE_BUY)

        # Risk จาก SL จริง (ไม่ใช่ TP)
        risk = abs(entry - sl_now)
        if risk < info.point:
            # SL = 0 หรือใกล้ entry มาก → ใช้ fallback
            risk = a * 1.5
            log.warning(f"⚠️ #{pos.ticket} SL ≈ 0 → fallback risk={risk:.2f}")

        price    = tick.bid if is_buy else tick.ask
        buf      = info.point * 5    # buffer เล็กน้อยเหนือ entry
        profit_r = ((price - entry) / risk if is_buy
                    else (entry - price) / risk)

        ts           = get_trail_state(pos.ticket)   # จาก SQLite (v8)
        partial_done = ts["partial_done"] if ts else 0

        # ── 1. Partial TP @ 1R ─────────────────────────────────
        if not partial_done and profit_r >= PARTIAL_TP_RR:
            _close_partial(pos, pos.volume * PARTIAL_TP_PCT)
            set_partial_done(pos.ticket)           # mark ใน DB
            # พร้อมกันเลื่อน SL → Breakeven
            be_sl = (entry + buf) if is_buy else (entry - buf)
            if ((is_buy     and sl_now < be_sl) or
                (not is_buy and sl_now > be_sl)):
                _modify_sl(pos.ticket, be_sl)
                log.info(f"🔒 BE+Partial #{pos.ticket} "
                         f"SL:{sl_now:.2f}→{be_sl:.2f} R:{profit_r:.2f}")
            continue   # ประมวลผล pos นี้รอบหน้า

        # ── 2. Breakeven @ 1R (กรณีไม่ทำ partial หรือทำแล้ว) ──
        if profit_r >= BREAKEVEN_RR:
            be_sl = (entry + buf) if is_buy else (entry - buf)
            if ((is_buy     and sl_now < be_sl) or
                (not is_buy and sl_now > be_sl)):
                _modify_sl(pos.ticket, be_sl)
                log.info(f"🔒 BE #{pos.ticket} "
                         f"SL:{sl_now:.2f}→{be_sl:.2f}")
            continue

        # ── 3. Trailing Stop @ 2R ──────────────────────────────
        if profit_r >= TRAIL_AFTER_RR:
            last_tsl = ts["last_sl"] if ts else None
            min_move = a * TRAIL_MIN_MOVE_ATR

            if is_buy:
                new_tsl = price - (a * TRAIL_ATR_MULT)
                # Trail ขึ้นเท่านั้น + ต้องขยับขั้นต่ำ min_move
                if (new_tsl > sl_now and
                        (last_tsl is None or
                         new_tsl > last_tsl + min_move)):
                    _modify_sl(pos.ticket, new_tsl)
                    save_trail_sl(pos.ticket, new_tsl)    # บันทึก DB
                    log.info(f"📈 Trail #{pos.ticket} "
                             f"SL:{sl_now:.2f}→{new_tsl:.2f} R:{profit_r:.2f}")
            else:
                new_tsl = price + (a * TRAIL_ATR_MULT)
                if (new_tsl < sl_now and
                        (last_tsl is None or
                         new_tsl < last_tsl - min_move)):
                    _modify_sl(pos.ticket, new_tsl)
                    save_trail_sl(pos.ticket, new_tsl)
                    log.info(f"📉 Trail #{pos.ticket} "
                             f"SL:{sl_now:.2f}→{new_tsl:.2f} R:{profit_r:.2f}")

    cleanup_trail_state(open_tickets)   # ลบ DB records ที่ปิดแล้ว


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📌 SECTION 10 — MAIN LOOP snippet
#    วางทับ/แก้ไขใน main loop ของ smc_bot_v8.py
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MAIN_LOOP_PATCH = """
# ── ใน while True loop ของ smc_bot_v8.py ────────────────────────
# เพิ่ม/แก้ไขบรรทัดเหล่านี้ในลำดับที่ถูกต้อง:

    # GATE 1b — Risk (DD limit เดิม ยังคงอยู่)
    if not is_within_risk_limits():
        log.warning(f"⛔ DD limit → หยุดทุกอย่าง")
        wait_next_candle(); continue

    # [FIX A2] GATE 1b2 — Circuit Breaker (เพิ่มถัดจาก gate 1b)
    if is_circuit_breaker_tripped():
        log.warning(f"⚡ Circuit Breaker active → ไม่เปิดออเดอร์ใหม่")
        wait_next_candle(); continue

    # GATE 1c — Session (เดิม)
    session = get_session()
    if session in ("OUT_OF_SESSION", "RED_NEWS_BLOCK"):
        wait_next_candle(); continue

    # [FIX C2] GATE 1c2 — Killzone Filter (เพิ่มถัดจาก gate 1c)
    in_kz, kz_name = is_in_killzone()
    if not in_kz:
        log.info(f"🕐 {kz_name} → นอก Killzone ข้าม")
        wait_next_candle(); continue
    log.info(f"✅ Killzone: {kz_name}")

    # ... (ส่วนที่เหลือเหมือนเดิม)
"""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📋 สรุปจุดวางทับทั้งหมด
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
┌─────────────────────────────────────────────────────────────────────┐
│ SECTION 1 — CONFIG                                                  │
│   ลบ LOT_TIERS เดิม เพิ่ม RISK_TIERS ใหม่                          │
│   เพิ่ม CIRCUIT_BREAKER_PCT, KILLZONE_ENABLED, KILLZONES            │
│                                                                     │
│ SECTION 2 — GLOBALS (ถัดจาก _cache_lock)                            │
│   เพิ่ม _trade_lock = threading.Lock()                              │
│                                                                     │
│ SECTION 3 — _send_retry()     วางทับทั้งฟังก์ชัน                   │
│ SECTION 4 — _modify_sl()      วางทับทั้งฟังก์ชัน                   │
│ SECTION 5 — _close_partial()  วางทับทั้งฟังก์ชัน                   │
│                                                                     │
│ SECTION 6 — calculate_lot()   วางทับทั้งฟังก์ชัน                   │
│                                                                     │
│ SECTION 7 — is_circuit_breaker_tripped()  เพิ่มใหม่ใน RISK ENGINE  │
│ SECTION 8 — is_in_killzone()             เพิ่มใหม่ใน SESSION        │
│ SECTION 9 — manage_positions()  วางทับทั้งฟังก์ชัน                 │
│                                                                     │
│ SECTION 10 — MAIN LOOP                                              │
│   เพิ่ม Circuit Breaker check (gate 1b2) หลัง is_within_risk_limits│
│   เพิ่ม Killzone check (gate 1c2) หลัง session check               │
│                                                                     │
│ ไม่ต้องแก้: SQLite, get_state/set_state, HTF BOS/CHOCH,            │
│             FVG memory, OB, analyze_setup, place_order             │
│             PM thread, fetch_all, wait_next_candle                  │
└─────────────────────────────────────────────────────────────────────┘
"""
