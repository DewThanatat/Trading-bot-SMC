import { useState } from "react";

const FIXES = [
  {
    id: "F01",
    priority: 1,
    file: "smc_bot_v23_live.py",
    category: "EXECUTION",
    title: "ลบ PT/FT Split Loop — บังคับ All-or-Nothing",
    why: "place_order() ยังส่ง 2 orders ทุกครั้ง แม้ PARTIAL_TP_PCT=0.0 ทำให้เสีย margin บน lot_a=0.01 ที่ไม่มีประโยชน์",
    severity: "CRITICAL",
    before: `# บรรทัดประมาณ 420-445 ใน place_order()
lot_a  = max(v_min, risk._round_lot(lot_full * PARTIAL_TP_PCT, step))
lot_b  = max(v_min, risk._round_lot(lot_full - lot_a, step))
tp_pt  = entry + risk * PARTIAL_TP_RR if sig=="BUY" else entry - risk * PARTIAL_TP_RR

sent = 0
for lot_i, tp_i, label in [(lot_a, tp_pt, "PT"), (lot_b, tp_full, "FT")]:
    req = {"action": action, "symbol": symbol, "volume": lot_i, ...}
    res = self._send_retry(req)
    if res and res.retcode in (...):
        sent += 1`,
    after: `# แทนที่ for-loop ทั้งหมดด้วย single order
req = {
    "action": action, "symbol": symbol,
    "volume": lot_full, "type": otype,
    "price": round(float(entry), 2),
    "sl": round(float(sl_adj), 2),
    "tp": round(float(tp_full), 2),
    "deviation": dev, "magic": MAGIC_NUMBER,
    "comment": f"V24|{sig}|{setup.score}|{setup.setup_hash}"
}
if action == mt5.TRADE_ACTION_PENDING:
    req["type_time"] = mt5.ORDER_TIME_SPECIFIED
    req["expiration"] = exp
res = self._send_retry(req)
sent = 1 if res and res.retcode in (
    mt5.TRADE_RETCODE_DONE,
    mt5.TRADE_RETCODE_DONE_PARTIAL
) else 0`,
    test: "ตรวจสอบว่า log แสดง 'V24|BUY|score|hash' เพียงรายการเดียวต่อ signal — ไม่มี PT/FT"
  },
  {
    id: "F02",
    priority: 2,
    file: "smc_bot_v23_live.py",
    category: "EXECUTION",
    title: "ลบ Step 1 Partial TP ออกจาก _manage_positions()",
    why: "แม้แก้ place_order แล้ว แต่ _manage_positions ยังมี Step 1 ที่พยายาม close_partial เมื่อ profit_r >= PARTIAL_TP_RR — ต้องลบออก",
    severity: "CRITICAL",
    before: `# _manage_positions() ประมาณบรรทัด 695-715
# ── [C9] STEP 1: Partial TP @1R — close 50% ──
if not partial_done and profit_r >= PARTIAL_TP_RR:
    info_sym = mt5.symbol_info(symbol)
    step = info_sym.volume_step if info_sym else 0.01
    v_min = info_sym.volume_min if info_sym else 0.01
    lot_to_close = self._exec._risk._round_lot(
        pos.volume * PARTIAL_TP_PCT, step)
    lot_remain = pos.volume - lot_to_close
    if lot_to_close >= v_min and lot_remain >= v_min:
        self._exec.close_partial(pos, lot_to_close, ...)
    set_partial_done(pos.ticket, pos_hash)`,
    after: `# ลบ Step 1 ทั้งหมดออก — เหลือแค่ Step 2 และ Step 3
# ── STEP 2: Delayed Breakeven ──
if profit_r >= BREAKEVEN_DELAY_RR:
    be_sl = (entry + buf) if is_buy else (entry - buf)
    if (is_buy and sl_now < be_sl) or (not is_buy and sl_now > be_sl):
        self._exec.modify_sl(pos.ticket, be_sl)
        log.info(f"🔒 [{symbol}] BE #{pos.ticket}")

# ── STEP 3: Trail SL ──
if profit_r >= TRAIL_AFTER_RR:
    ...  # (ส่วนนี้คงไว้เหมือนเดิม)`,
    test: "รัน _manage_positions 10 รอบ — log ต้องไม่มี 'Partial' หรือ 'PartialTP' เลย"
  },
  {
    id: "F03",
    priority: 3,
    file: "smc_core_v23.py",
    category: "RISK",
    title: "แก้ MAX_LOSS_PER_TRADE_USD และซิงค์ Banner",
    why: "core ตั้ง $5 แต่ banner บอก $3 — ตัวที่ใช้งานจริงคือ $5 = 8.3% ของ $60 ซึ่งอันตราย",
    severity: "CRITICAL",
    before: `# smc_core_v23.py บรรทัดประมาณ 130
MAX_LOSS_PER_TRADE_USD = 5.0   # ใส่เกราะป้องกัน...`,
    after: `# smc_core_v23.py
MAX_LOSS_PER_TRADE_USD = 3.0   # Hard cap: 5% ของ $60 ต่อไม้ — ห้ามเกินเด็ดขาด

# smc_bot_v23_live.py BANNER (แก้ comment ให้ตรง)
# MAX_LOSS_PER_TRADE_USD = $3.00  ✓`,
    test: "เช็ค calculate_lot() ด้วย score=86, balance=$60 — lot ที่คำนวณได้ต้องไม่เกิน $3 risk"
  },
  {
    id: "F04",
    priority: 4,
    file: "smc_core_v23.py",
    category: "SESSION",
    title: "Hard Block LONDON Session ทั้งหมด",
    why: "LONDON PF 0.23 (รายงานแรก 24 ไม้) — ไม่มี threshold ใดที่แก้ session ที่ toxic ได้ ต้องบล็อกที่ระดับ code",
    severity: "CRITICAL",
    before: `# SESSIONS list ยังรวม LONDON ไว้
SESSIONS = [
    (12, 0, 14, 0, "PRE_LONDON"),
    (14, 0, 18, 0, "LONDON"),      # <-- ต้นเหตุ
    (18, 30, 19, 15, "NY_OPEN_EARLY"),
    (19, 45, 23, 59, "NEW_YORK"),
]

# KILLZONES ยังรวม London Open
KILLZONES = [
    (14, 0, 16, 30, "London Open"),  # <-- ต้นเหตุ
    (18, 30, 19, 15, "NY Open Early"),
    (19, 45, 22, 0,  "NY Open"),
]

# SCORE_THRESHOLD
SCORE_THRESHOLD: Dict[str, int] = {
    "LONDON": 85,   # ตั้ง threshold สูงแต่ยังรับ signal`,
    after: `# ลบ LONDON ออกจาก SESSIONS และ KILLZONES
SESSIONS = [
    (12, 0, 14, 0, "PRE_LONDON"),
    # LONDON ถูกลบออก — PF 0.23 ไม่คุ้มค่า
    (18, 30, 19, 15, "NY_OPEN_EARLY"),
    (19, 45, 23, 59, "NEW_YORK"),
]

KILLZONES = [
    # London Open ถูกลบออก
    (18, 30, 19, 15, "NY Open Early"),
    (19, 45, 22, 0,  "NY Open"),
]

# เพิ่ม hard-block ใน analyze_setup() / execute()
# ใน SetupAnalyzer.execute():
if self.session == "LONDON":
    r.reasons.append("LONDON_BLOCKED")
    return r  # return WAIT ทันที`,
    test: "ส่ง bar_time ที่ตรงกับ LONDON session — setup.signal ต้องเป็น 'WAIT' เสมอ"
  },
  {
    id: "F05",
    priority: 5,
    file: "smc_core_v23.py",
    category: "SESSION",
    title: "เปิด PRE_LONDON กลับมา และลด Threshold เป็น 72",
    why: "PRE_LONDON PF 2.63, WR 68.4% คือ Best Session ในรายงานแรก แต่ใน backtest ล่าสุด 0 ไม้ — threshold 75 สูงเกินไป + PRE_LONDON_SWEEP_REQUIRED ปิดกั้น",
    severity: "HIGH",
    before: `SCORE_THRESHOLD: Dict[str, int] = {
    "PRE_LONDON": 75,   # สูงเกินไป
    ...
}
PRE_LONDON_SWEEP_REQUIRED = True  # บล็อกทุก FVG-only setup`,
    after: `SCORE_THRESHOLD: Dict[str, int] = {
    "PRE_LONDON":    72,   # ลดจาก 75 เพื่อเปิดรับ High-quality setups
    "NY_OPEN_EARLY": 78,   # ลดจาก 80 (sample n=2 เล็กเกินสรุป)
    "NEW_YORK":      68,   # เพิ่มจาก 65 (กรอง score 65-67 ออก)
    "DEFAULT":       68,
}
PRE_LONDON_SWEEP_REQUIRED = True  # คงไว้ — sweep required ยังถูกต้อง`,
    test: "ใน PRE_LONDON session: setup ที่มี sweep+FVG+H4 align (score ~72–74) ต้องผ่าน — setup FVG-only ต้องถูก -15 penalty"
  },
  {
    id: "F06",
    priority: 6,
    file: "smc_core_v23.py",
    category: "SCORING",
    title: "ปรับ Score Weights ทั้งระบบ (8 ค่า)",
    why: "จากข้อมูล 39 trades: Score 65-70 ให้ WR 76.2% PF 7.26 ดีที่สุด, Score 75-80 คือ danger zone WR 33% PF 0.04, H4 Neutral คือตัวร้ายหลัก",
    severity: "HIGH",
    before: `SCORE_LIQ_SWEPT     = 40   # dominant เกินไป
SCORE_HTF_ALIGN     = 15
SCORE_HTF_AGAINST   = -50
SCORE_HTF_NEUTRAL   = -10  # ลงโทษน้อยเกิน
SCORE_PA_PINBAR     = 10   # (code) / 8 (backtest actual)
SCORE_PA_DOJI       = 0    # ปิดทิ้ง
SCORE_VSHAPE_BONUS  = 4
JUDAS_SCORE_BONUS   = 20   # สูงเกิน
H1_AGREE_BONUS      = 15`,
    after: `SCORE_LIQ_SWEPT     = 28   # ลด 40→28: sweep ควรเป็น 1 ใน 3 ปัจจัย ไม่ใช่ปัจจัยเดียว
SCORE_HTF_ALIGN     = 18   # เพิ่ม 15→18: H4 align คือ predictor #1 ของ win
SCORE_HTF_AGAINST   = -40  # ผ่อนจาก -50: REVERSAL_OVERRIDE=False คุ้มครองพอแล้ว
SCORE_HTF_NEUTRAL   = -20  # เพิ่มโทษ -10→-20: Neutral H4 = ห้ามเทรดเด็ดขาด
SCORE_PA_PINBAR     = 8    # ลด 10→8: ตาม backtest actual (WR 87.5% ยืนยัน edge)
SCORE_PA_DOJI       = 3    # เปิดจาก 0→3: Doji WR 60% PF 1.74 มี edge อ่อน
SCORE_VSHAPE_BONUS  = 2    # ลด 4→2: V-Shape บน BTC fail — ลดน้ำหนักทั้งระบบ
JUDAS_SCORE_BONUS   = 12   # ลด 20→12: ไม่มี Judas trades ใน backtest ยืนยัน
H1_AGREE_BONUS      = 12   # ลด 15→12: ให้สอดคล้องกับ SCORE_HTF_ALIGN ที่เพิ่มขึ้น`,
    test: "คำนวณ score สมมติ: Base(20)+Sweep(28)+H4_Align(18)+H1(12)+FVG(12)+M15_BOS(10) = 100 ✓ เป็น God-tier จริง"
  },
  {
    id: "F07",
    priority: 7,
    file: "smc_core_v23.py",
    category: "SCORING",
    title: "เพิ่ม Sweep Required Gate สำหรับ Score 68–79",
    why: "Score 75–80 WR 33% PF 0.04 ในข้อมูล backtest — ช่วงนี้ FVG+H1+BOS stack score ขึ้นไปได้โดยไม่มี real sweep",
    severity: "HIGH",
    before: `# ใน _build_buy() และ _build_sell()
# ปัจจุบัน: ไม่มี gate พิเศษสำหรับ mid-score range
if not has_sweep and fvg_active is None: return False`,
    after: `# เพิ่มใน _apply_penalties() หลัง choppy check
MIN_SWEEP_SCORE_FOR_MID = 28  # = SCORE_LIQ_SWEPT ใหม่

if 68 <= r.score < 80:
    # ถ้า score อยู่ใน danger zone ต้องมี sweep จริงๆ
    sweep_pts = SCORE_LIQ_SWEPT if has_sweep else 0
    if sweep_pts < MIN_SWEEP_SCORE_FOR_MID:
        r.score -= 15
        r.reasons.append("⛔ MidScore-NoSweep penalty -15")

# ผลลัพธ์: setup ที่ได้ score 70 จาก FVG+H1+BOS แต่ไม่มี sweep
# จะถูกหัก 15 → เหลือ 55 → ต่ำกว่า threshold → WAIT`,
    test: "ทดสอบ setup: FVG+H1+BOS+OB = score 72, ไม่มี sweep → ต้องถูก -15 → score 57 → WAIT"
  },
  {
    id: "F08",
    priority: 8,
    file: "smc_core_v23.py",
    category: "TRADE_MGMT",
    title: "แก้ Trail Parameters — ขยาย Trail ให้ Runner วิ่งได้",
    why: "Avg winner = 0.90R ทั้งที่ target 2.0R, TP_FULL hit 7.7% เท่านั้น — trail กัดแน่นเกินไป ทำให้ตัดกำไรก่อนเวลา",
    severity: "HIGH",
    before: `BREAKEVEN_DELAY_RR = 0.6   # BE เร็วพอ
TRAIL_AFTER_RR     = 1.0   # เริ่ม trail ช้า → dead zone 0.6–1.0R
TRAIL_ATR_MULT     = 0.8   # แน่นเกิน → สะบัดออกก่อน 2R
TRAIL_MIN_MOVE_ATR = 0.2   # ขยับบ่อยเกิน
RR_RATIO           = 2.0   # TP ที่ราคาไม่ค่อยถึง`,
    after: `BREAKEVEN_DELAY_RR = 0.5   # BE เร็วขึ้นนิดหน่อย (ปกป้องทุนเร็วกว่า)
TRAIL_AFTER_RR     = 0.6   # เริ่ม trail ทันทีหลัง BE (ปิด dead zone)
TRAIL_ATR_MULT     = 1.2   # กว้างขึ้น 0.8→1.2: ให้ราคา breathe ก่อนตัด
TRAIL_MIN_MOVE_ATR = 0.3   # เพิ่มขั้นต่ำ: trail ขยับเฉพาะเมื่อคุ้มค่า
RR_RATIO           = 1.8   # TP จริงที่วัดได้ (max pnl_r ใน backtest = 1.276R)`,
    test: "Paper trade 5 ไม้ — avg winner ต้องเพิ่มจาก 0.90R ขึ้นเป็น ≥1.1R"
  },
  {
    id: "F09",
    priority: 9,
    file: "smc_core_v23.py",
    category: "RISK",
    title: "ปรับ Risk Tiers — ลบ PREDATOR ออก รวม 3% เข้า 2%",
    why: "PREDATOR tier (3%) PF 0.97 ในรายงานแรก = net negative จาก 76 ไม้ ใน backtest ล่าสุดไม่มี PREDATOR tier เลย (ทั้งหมดเป็น SCOUT หรือ 2%)",
    severity: "HIGH",
    before: `RISK_TIERS = [
    (85, 5.00),   # GOD STRIKE
    (75, 3.00),   # HEAVY SNIPER / PREDATOR ← PF 0.97
    (65, 2.00),   # SNIPER
    (60, 1.00),   # SCOUT ← 33 ไม้ใน backtest WR 69.7%
]`,
    after: `RISK_TIERS = [
    (82, 3.50),   # GOD STRIKE: เพดานลดลง (จาก 5% → 3.5%) จนกว่า 30+ God-tier trades พิสูจน์ edge
    (70, 2.00),   # SNIPER: ปรับ threshold จาก 75→70 ให้สอดคล้อง score distribution จริง
    (65, 1.50),   # SCOUT: ลดจาก 2%→1.5% (score 65-69 ยัง WR 76% แต่ลด risk ไว้ก่อน)
    # ลบ tier 60→1% ออก: ห้ามเทรด score <65 เด็ดขาด (BUG-07)
]
MAX_LOSS_PER_TRADE_USD = 3.0  # ยืนยันอีกครั้ง`,
    test: "score=86 → risk 3.5%, score=72 → risk 2.0%, score=66 → risk 1.5%, score=63 → ไม่ผ่าน threshold"
  },
  {
    id: "F10",
    priority: 10,
    file: "smc_core_v23.py",
    category: "SCORING",
    title: "แก้ M1 Confirm: ย้ายเข้า analyze_setup ก่อน threshold check",
    why: "BUG-07: setup.score += SCORE_M1_CONFIRM เกิดขึ้นใน place_order() หลัง threshold check — ทำให้ score 61 ผ่าน gate แล้วได้ +4 กลายเป็น 65",
    severity: "HIGH",
    before: `# smc_bot_v23_live.py ใน place_order() ~บรรทัด 380
# M1 micro-confirmation (เพิ่มหลัง gate check!)
try:
    rates_m1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 8)
    if rates_m1 is not None and len(rates_m1) >= 4:
        ...
        if body_m1 >= setup.atr * MTF_M1_BODY_ATR and dir_ok:
            setup.score += SCORE_M1_CONFIRM  # ← ปัญหาอยู่ที่นี่`,
    after: `# ย้าย M1 check เข้าไปใน SetupAnalyzer._apply_penalties()
# smc_core_v23.py ใน _apply_penalties():
def _apply_m1_confirm(self, sig: str, df_m1: Optional[pd.DataFrame]) -> None:
    if df_m1 is None or len(df_m1) < 4: return
    c = df_m1.iloc[-2]
    body_m1 = abs(float(c["close"]) - float(c["open"]))
    dir_ok = ((sig == "BUY" and c["close"] > c["open"]) or
              (sig == "SELL" and c["close"] < c["open"]))
    if body_m1 >= self.atr * 0.3 and dir_ok:
        self.r.score += SCORE_M1_CONFIRM
        self.r.reasons.append(f"M1 Confirm +{SCORE_M1_CONFIRM}")

# เรียกใน execute() ก่อน threshold evaluation
# จากนั้นลบ M1 block ออกจาก place_order()`,
    test: "setup ที่ score=61 pre-M1 ต้องไม่ผ่าน gate — M1 ต้องถูกนับก่อน threshold เท่านั้น"
  },
  {
    id: "F11",
    priority: 11,
    file: "smc_core_v23.py",
    category: "SYMBOL",
    title: "BTCUSDm: ปิด V-Shape, เพิ่ม threshold เป็น 70, ลด SL mult",
    why: "BTC เม.ย. 2026: 3 ไม้ติดต่อกันแพ้ -1.0R รวม -$19.28 — V-Shape บน BTC M5 คือ noise ไม่ใช่ signal, ATR ใหญ่มาก",
    severity: "HIGH",
    before: `"BTCUSDm": {
    "spread_block_pts": 2500.0,
    "sl_atr_mult": 3.0,    # ← SL กว้างมาก
    "min_lot": 0.01,
    "sim_spread": 2000.0,
    "tick_val": 0.01,
    "pt_size": 0.01,
}`,
    after: `"BTCUSDm": {
    "spread_block_pts": 2500.0,
    "sl_atr_mult": 2.5,        # ลด 3.0→2.5: ลด risk per trade
    "min_lot": 0.01,
    "sim_spread": 2000.0,
    "tick_val": 0.01,
    "pt_size": 0.01,
    "min_score": 70,           # BTC-specific threshold (ปกติ 65)
    "vshape_disabled": True,   # ปิด V-Shape bonus สำหรับ BTC
}

# ใน _apply_structure_scores():
sym_profile = ACTIVE_SYMBOLS.get(self.symbol, {})
if shape == "V" and not sym_profile.get("vshape_disabled", False):
    r.score += SCORE_VSHAPE_BONUS
    r.reasons.append(f"V-Shape +{SCORE_VSHAPE_BONUS}")

# ใน get_dynamic_threshold() หรือ execute():
min_score = sym_profile.get("min_score", 0)
effective_threshold = max(r.threshold, min_score)`,
    test: "BTC setup score=68 ต้องถูกบล็อก (min_score=70) — USTEC score=68 ต้องผ่านปกติ"
  },
  {
    id: "F12",
    priority: 12,
    file: "smc_core_v23.py",
    category: "SYMBOL",
    title: "EURUSDm: เพิ่ม threshold เป็น 72 และ sl_atr_mult เป็น 2.0",
    why: "EURUSDm PF 0.99 — PnL -$0.10 สุทธิ AvgR 0.248 spread ratio กิน edge ไปหมด",
    severity: "MEDIUM",
    before: `"EURUSDm": {
    "spread_block_pts": 50.0,
    "sl_atr_mult": 1.8,   # SL แคบเกิน → ถูกสะบัดก่อน BE
    "min_lot": 0.01,
    ...
}`,
    after: `"EURUSDm": {
    "spread_block_pts": 50.0,
    "sl_atr_mult": 2.0,    # เพิ่ม 1.8→2.0: ให้ SL หายใจได้มากขึ้น
    "min_lot": 0.01,
    "sim_spread": 10.0,
    "tick_val": 1.0,
    "pt_size": 0.00001,
    "min_score": 72,       # EUR-specific threshold
}`,
    test: "EUR setup score=70 ต้องถูกบล็อก — EUR setup score=73 พร้อม sweep+H4 ต้องผ่าน"
  },
  {
    id: "F13",
    priority: 13,
    file: "smc_core_v23.py",
    category: "SYMBOL",
    title: "ลบ score_bonus จาก USTECm",
    why: "USTECm มี 'score_bonus': 5 ที่ซ่อนไว้ใน ACTIVE_SYMBOLS — ยังไม่ถูกใช้งาน แต่เป็น latent code debt อันตราย",
    severity: "MEDIUM",
    before: `"USTECm": {
    "spread_block_pts": 300.0,
    "sl_atr_mult": 4.5,
    "min_lot": 0.1,
    "sim_spread": 150.0,
    "tick_val": 1.0,
    "pt_size": 1.0,
    "score_bonus": 5   # ← ลบออก: stealth inflation ที่ไม่มี edge proof
}`,
    after: `"USTECm": {
    "spread_block_pts": 300.0,
    "sl_atr_mult": 4.5,
    "min_lot": 0.1,
    "sim_spread": 150.0,
    "tick_val": 1.0,
    "pt_size": 1.0,
    # score_bonus ถูกลบออก
}`,
    test: "grep 'score_bonus' ในทั้งสองไฟล์ — ต้องไม่พบ"
  },
  {
    id: "F14",
    priority: 14,
    file: "smc_bot_v23_live.py",
    category: "FREQUENCY",
    title: "ลด SETUP_COOLDOWN_SEC: 180 → 60 วินาที",
    why: "Cooldown 3 นาที บล็อก re-entry หลัง fast sweep — ใน backtest หลายครั้งที่มี 2 signals ในวันเดียว (16 ก.ย. มี 3 ไม้) cooldown เป็นตัวฆ่า frequency",
    severity: "MEDIUM",
    before: `SETUP_COOLDOWN_SEC = 180   # 3 นาที — บล็อก re-entry บนสัญญาณที่ต่างกัน`,
    after: `SETUP_COOLDOWN_SEC = 60    # 1 นาที — hash-based cooldown ป้องกัน duplicate ได้อยู่แล้ว
# หมายเหตุ: cooldown ผูกกับ setup_hash (entry+sl+ts)
# setup ใหม่บน symbol เดิมแต่ต่าง structure = hash ต่างกัน = ผ่านได้`,
    test: "จำลอง 2 signals บน XAUUSD ห่างกัน 90 วินาที ด้วย hash ต่างกัน — ทั้งคู่ต้องผ่าน"
  },
  {
    id: "F15",
    priority: 15,
    file: "smc_core_v23.py",
    category: "FILTER",
    title: "VolatilityFilter: เปลี่ยนจาก penalty เป็น hard WAIT",
    why: "is_choppy() ปัจจุบันหัก -15 pts แต่ setup score=80 ยังเหลือ 65 และผ่านได้ — ต้องบล็อกทันทีเพราะ choppy = fake sweep",
    severity: "MEDIUM",
    before: `# ใน _apply_penalties()
if self.is_choppy:
    r.score -= 15
    r.reasons.append("⚠️ Choppy Regime -15")`,
    after: `# ใน SetupAnalyzer.execute() ก่อน _build_buy/_build_sell
self.is_choppy = VolatilityFilter.is_choppy_regime(self.df_m5, self.atr)
if self.is_choppy:
    r.signal = "WAIT"
    r.reasons.append("⛔ CHOPPY_BLOCK: 5-bar range < 1.5 ATR")
    return r  # hard block ไม่ให้ผ่านไปถึง scoring เลย`,
    test: "ป้อน df_m5 ที่มี 5-bar range = 1.2 ATR — result.signal ต้องเป็น 'WAIT' โดยไม่มี score ใดๆ"
  },
  {
    id: "F16",
    priority: 16,
    file: "smc_core_v23.py",
    category: "FILTER",
    title: "เพิ่ม ADR_EXHAUSTED_PCT: 0.80 → 0.88",
    why: "ADR penalty (-10) ที่ 80% ตัดหลาย session ปลายออก — backtest แสดง XAUUSDm ไม้ที่ ADR 92% ยังได้ +$36.95 (ไม้ที่ 24) ดังนั้น 80% เป็น threshold ที่เข้มเกินไป",
    severity: "LOW",
    before: `ADR_EXHAUSTED_PCT    = 0.80
ADR_NY_EXHAUSTED_PCT = 0.85
ADR_HARD_BLOCK       = False`,
    after: `ADR_EXHAUSTED_PCT    = 0.88   # ผ่อน 0.80→0.88
ADR_NY_EXHAUSTED_PCT = 0.92   # ผ่อน 0.85→0.92 สำหรับ NY session ที่ ADR มักสูง
ADR_HARD_BLOCK       = False  # คงไว้ soft penalty`,
    test: "setup ที่ ADR 85% ต้องไม่ถูก -10 penalty — setup ที่ ADR 93% ต้องยังถูก -10"
  },
  {
    id: "F17",
    priority: 17,
    file: "smc_core_v23.py",
    category: "FILTER",
    title: "GLOBAL_MAX_CONCURRENT_TRADES: 4 → 3",
    why: "บน $60 การมี 4 positions พร้อมกันคือ over-exposure — แม้แต่ 3 ไม้ที่ 1.5% risk = 4.5% floating ซึ่งใกล้ขีดจำกัด",
    severity: "LOW",
    before: `GLOBAL_MAX_CONCURRENT_TRADES = 4
MAX_GLOBAL_EXPOSURE_PCT      = 15.0`,
    after: `GLOBAL_MAX_CONCURRENT_TRADES = 3   # ลด 4→3: ปลอดภัยกว่าสำหรับ $60
MAX_GLOBAL_EXPOSURE_PCT      = 10.0  # ลด 15→10%: hard exposure cap`,
    test: "เมื่อมี 3 positions อยู่ → signal ใหม่ต้องถูก skip แม้ผ่าน threshold"
  },
];

const catColor = {
  EXECUTION:"#e24b4a", RISK:"#ba7517", SESSION:"#185fa5",
  SCORING:"#534ab7", TRADE_MGMT:"#0f6e56", FILTER:"#639922", SYMBOL:"#3c3489", FREQUENCY:"#1d9e75"
};
const catBg = {
  EXECUTION:"#fcebeb", RISK:"#faeeda", SESSION:"#e6f1fb",
  SCORING:"#eeedfe", TRADE_MGMT:"#e1f5ee", FILTER:"#eaf3de", SYMBOL:"#eeedfe", FREQUENCY:"#e1f5ee"
};
const sevColor = {CRITICAL:"#e24b4a",HIGH:"#ba7517",MEDIUM:"#185fa5",LOW:"#639922"};

const CATEGORIES = ["ALL","EXECUTION","RISK","SESSION","SCORING","TRADE_MGMT","FILTER","SYMBOL","FREQUENCY"];
const ORDER = ["CRITICAL","HIGH","MEDIUM","LOW"];

export default function App() {
  const [cat, setCat] = useState("ALL");
  const [exp, setExp] = useState(null);
  const [done, setDone] = useState({});

  const filtered = FIXES.filter(f => cat==="ALL" || f.category===cat);
  const critCount = FIXES.filter(f=>f.severity==="CRITICAL").length;
  const highCount = FIXES.filter(f=>f.severity==="HIGH").length;
  const doneCount = Object.values(done).filter(Boolean).length;

  return (
    <div style={{fontFamily:"var(--font-sans)",padding:"1.5rem 1rem",background:"var(--color-background-primary)",color:"var(--color-text-primary)"}}>
      <h2 style={{fontSize:18,fontWeight:500,margin:"0 0 4px"}}>SMC V24 — แผนแก้ไขฉบับสมบูรณ์</h2>
      <p style={{fontSize:13,color:"var(--color-text-secondary)",margin:"0 0 1rem"}}>17 จุดแก้ไข · 2 ไฟล์ · เรียงลำดับตามความเร่งด่วน</p>

      <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:8,marginBottom:16}}>
        {[
          ["CRITICAL",critCount,"#fcebeb","#e24b4a"],
          ["HIGH",highCount,"#faeeda","#ba7517"],
          ["ทำแล้ว",doneCount,"#e1f5ee","#1d9e75"],
          ["ทั้งหมด",FIXES.length,"var(--color-background-secondary)","var(--color-text-primary)"],
        ].map(([l,v,bg,col])=>(
          <div key={l} style={{background:bg,padding:"8px 12px",borderRadius:"var(--border-radius-md)",textAlign:"center"}}>
            <div style={{fontSize:10,color:col,marginBottom:2}}>{l}</div>
            <div style={{fontSize:22,fontWeight:500,color:col}}>{v}</div>
          </div>
        ))}
      </div>

      <div style={{display:"flex",gap:5,flexWrap:"wrap",marginBottom:16}}>
        {CATEGORIES.map(c=>(
          <button key={c} onClick={()=>setCat(c)}
            style={{padding:"4px 12px",fontSize:11,fontWeight:cat===c?500:400,background:cat===c?(catBg[c]||"var(--color-background-secondary)"):"transparent",color:cat===c?(catColor[c]||"var(--color-text-primary)"):"var(--color-text-secondary)",border:`0.5px solid ${cat===c?(catColor[c]||"var(--color-border-primary)"):"var(--color-border-tertiary)"}`,borderRadius:"var(--border-radius-md)",cursor:"pointer"}}>
            {c}
          </button>
        ))}
      </div>

      {filtered.map(f=>(
        <div key={f.id} style={{marginBottom:10,border:`0.5px solid ${done[f.id]?"#1d9e75":"var(--color-border-tertiary)"}`,borderLeft:`3px solid ${done[f.id]?"#1d9e75":sevColor[f.severity]}`,borderRadius:"var(--border-radius-md)",background:done[f.id]?"#f8fffe":"var(--color-background-primary)",opacity:done[f.id]?0.7:1}}>
          <div style={{padding:"10px 14px",display:"flex",alignItems:"flex-start",gap:10}}>
            <input type="checkbox" checked={!!done[f.id]} onChange={()=>setDone(d=>({...d,[f.id]:!d[f.id]}))}
              style={{marginTop:3,flexShrink:0,cursor:"pointer",width:16,height:16}}/>
            <div style={{flex:1,cursor:"pointer"}} onClick={()=>setExp(exp===f.id?null:f.id)}>
              <div style={{display:"flex",gap:8,alignItems:"center",marginBottom:4,flexWrap:"wrap"}}>
                <span style={{fontSize:11,fontWeight:500,color:"var(--color-text-tertiary)",fontFamily:"monospace"}}>{f.id}</span>
                <span style={{fontSize:11,padding:"1px 8px",background:sevColor[f.severity]+"22",color:sevColor[f.severity],borderRadius:"var(--border-radius-md)",fontWeight:500}}>{f.severity}</span>
                <span style={{fontSize:11,padding:"1px 8px",background:catBg[f.category],color:catColor[f.category],borderRadius:"var(--border-radius-md)"}}>{f.category}</span>
                <span style={{fontSize:11,color:"var(--color-text-tertiary)",fontFamily:"monospace"}}>{f.file}</span>
              </div>
              <div style={{fontSize:13,fontWeight:500,lineHeight:1.4}}>{f.title}</div>
              <div style={{fontSize:12,color:"var(--color-text-secondary)",marginTop:2,lineHeight:1.5}}>{f.why}</div>
            </div>
            <span onClick={()=>setExp(exp===f.id?null:f.id)} style={{fontSize:14,color:"var(--color-text-tertiary)",flexShrink:0,cursor:"pointer",padding:"0 4px"}}>{exp===f.id?"−":"+"}</span>
          </div>

          {exp===f.id && (
            <div style={{padding:"0 14px 14px 40px",borderTop:"0.5px solid var(--color-border-tertiary)"}}>
              <div style={{marginTop:12,marginBottom:8,fontSize:11,fontWeight:500,color:"var(--color-text-secondary)",textTransform:"uppercase",letterSpacing:"0.05em"}}>Code ปัจจุบัน (Before)</div>
              <pre style={{margin:0,padding:"10px 14px",background:"#fcebeb",border:"0.5px solid #e24b4a33",borderRadius:"var(--border-radius-md)",fontSize:11,fontFamily:"monospace",lineHeight:1.7,overflowX:"auto",color:"#501313",whiteSpace:"pre-wrap",wordBreak:"break-word"}}>{f.before}</pre>
              <div style={{marginTop:10,marginBottom:8,fontSize:11,fontWeight:500,color:"#1d9e75",textTransform:"uppercase",letterSpacing:"0.05em"}}>Code ที่แก้แล้ว (After)</div>
              <pre style={{margin:0,padding:"10px 14px",background:"#e1f5ee",border:"0.5px solid #1d9e7533",borderRadius:"var(--border-radius-md)",fontSize:11,fontFamily:"monospace",lineHeight:1.7,overflowX:"auto",color:"#04342c",whiteSpace:"pre-wrap",wordBreak:"break-word"}}>{f.after}</pre>
              <div style={{marginTop:10,padding:"8px 12px",background:"var(--color-background-secondary)",border:"0.5px solid var(--color-border-tertiary)",borderRadius:"var(--border-radius-md)"}}>
                <span style={{fontSize:11,fontWeight:500,color:"#185fa5"}}>TEST: </span>
                <span style={{fontSize:12,color:"var(--color-text-secondary)"}}>{f.test}</span>
              </div>
            </div>
          )}
        </div>
      ))}

      <div style={{marginTop:16,padding:"12px 14px",background:"var(--color-background-secondary)",border:"0.5px solid var(--color-border-tertiary)",borderRadius:"var(--border-radius-md)",fontSize:12,color:"var(--color-text-secondary)",lineHeight:1.8}}>
        <span style={{fontWeight:500,color:"var(--color-text-primary)"}}>ลำดับการแก้ไขที่แนะนำ: </span>
        F01→F02→F03 (Execution ก่อน) → F04→F05 (Session) → F09→F03 (Risk) → F06→F07→F10 (Scoring) → F08 (Trail) → F11→F12→F13 (Symbol) → F14→F15→F16→F17 (Filter/Freq) — Backtest หลังทุก batch ก่อน deploy live
      </div>
    </div>
  );
}
