# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════════╗
║  🌐  SMC/ICT PRO SNIPER  —  V.22  "Perfected Kamikaze Scanner"                  ║
║                                                                                  ║
║  CRITICAL FIXES vs V.21:                                                         ║
║  [C1]  Market-Order Entry Bug   — entry=tick.ask/bid, SL structurally anchored   ║
║  [C3]  sl_atr_mult arg          — always read from ACTIVE_SYMBOLS profile        ║
║  [C4]  ATR Window               — PositionManager fetches n=20 for trail ATR     ║
║  [C6]  H4 NEUTRAL penalty       — in smc_core_v22 score system                  ║
║  [C7]  Score inflation removed  — in smc_core_v22 (no redundant bonuses)        ║
║  [C8]  Session thresholds       — LONDON=82, NY_OPEN_EARLY=85                   ║
║  [C9]  Hit & Run                — 60% partial @1R, BE, trail @1.5R              ║
║  [C10] Min-RR gate              — liquidity target ≥2R required                 ║
║                                                                                  ║
║  SHARED WITH BACKTEST via smc_core_v22.py:                                       ║
║  analyze_setup, all indicators, ACTIVE_SYMBOLS, scoring constants                ║
╚══════════════════════════════════════════════════════════════════════════════════╝
"""

import hashlib
import json
import logging
import math
import os
import queue as _queue_module
import signal
import sqlite3
import threading
import time
import warnings
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, time as dtime
from decimal import Decimal, ROUND_DOWN
from typing import Deque, Dict, List, Optional, Tuple

import MetaTrader5 as mt5
import numpy as np
import pandas as pd
import pytz

warnings.filterwarnings("ignore", category=RuntimeWarning)

try:
    import joblib
    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False

# ── Import the shared core (same analysis logic as backtest) ──────────────────
from smc_core_v22 import (
    ACTIVE_SYMBOLS, GLOBAL_MAX_CONCURRENT_TRADES, MAX_TRADES_PER_SYMBOL,
    MAX_GLOBAL_EXPOSURE_PCT, RISK_TIERS, MAX_LOSS_PER_TRADE_USD,
    STRATEGY_TZ,
    RR_RATIO, PARTIAL_TP_RR, PARTIAL_TP_PCT, BREAKEVEN_DELAY_RR,
    TRAIL_AFTER_RR, TRAIL_ATR_MULT, TRAIL_MIN_MOVE_ATR,
    HTF_BARS, H1_BARS,
    SCORE_THRESHOLD_IN_SESSION, SCORE_THRESHOLD_OUT_SESSION,
    FVG_MEMORY_BARS,
    analyze_setup, calculate_atr, calculate_adr, apply_adr_tp_cap,
    SetupResult,
)

# ─────────────────────────────────────────────────────────────────────────────
#  BROKER / BOT CONFIG
# ─────────────────────────────────────────────────────────────────────────────
MAGIC_NUMBER     = 99922
BROKER_TZ_NAME   = "Etc/UTC"
BROKER_TZ        = pytz.timezone(BROKER_TZ_NAME)
CLOCK_ANCHOR_SYMBOL: str = next(iter(ACTIVE_SYMBOLS))
SYMBOL = CLOCK_ANCHOR_SYMBOL   # legacy alias

MAX_DEVIATION_POINTS       = int(30)
EMERGENCY_DEVIATION_POINTS = int(150)
MIN_RR_RATIO_LIVE          = 0.6
MAX_DAILY_LOSS_PCT         = 40.0
MAX_TOTAL_DD_PCT           = 15.0
EXPIRATION_CANDLES         = 36

HARD_SPREAD_BLOCK   = 80.0
MAX_SPREAD_POINTS   = 60.0
SPREAD_DYNAMIC_MULT = 3.0
SPREAD_MEDIAN_BARS  = 20
SPREAD_LOT_PENALTY  = 0.3
SPREAD_SL_PADDING   = True

MTF_M1_BODY_ATR = 0.3

OOS_HARD_SPREAD_BLOCK = 30
SETUP_COOLDOWN_SEC    = 180
MOMENTUM_BODY_ATR     = 1.2

RECONNECT_BASE_DELAY   = 5.0
RECONNECT_MAX_DELAY    = 120.0
RECONNECT_MAX_ATTEMPTS = 20

FRIDAY_CLOSE_ENABLED  = True
FRIDAY_CLOSE_UTC_HOUR = 21
FRIDAY_CLOSE_UTC_MIN  = 0

N_CONSEC_LOSS_PAUSE   = 99
CONSEC_LOSS_PAUSE_MIN = 60
CONSEC_LOSS_CACHE_SEC = 30

DD_YELLOW_PCT       = 3.0
DD_ORANGE_PCT       = 5.0
CIRCUIT_BREAKER_PCT = 90.0
DD_STATE_TTL        = 2.0
ORPHAN_SL_CHECK_INTERVAL = 60.0
WELFORD_PERSIST_EVERY    = 50

CACHE_TTL_LTF = 5; CACHE_TTL_HTF = 60; CACHE_TTL_D1 = 300
POSITION_POLL_SEC = 0.2
TICK_POLL_SEC     = 1.0
HEARTBEAT_SEC     = 300

KILL_FLAG_PATH  = "KILL.flag"
PAUSE_FLAG_PATH = "PAUSE.flag"
DB_PATH         = "smc_state_v22.db"
LOG_PATH        = "smc_bot_v22.log"
NEWS_EVENTS_FILE     = "news_events.json"
NEWS_BUFFER_MIN      = 30
NEWS_STATIC_FALLBACK = [(19, 15, 19, 45), (15, 25, 15, 35)]

# ─────────────────────────────────────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────────────────────
#  BROKER CLOCK SYNC
# ─────────────────────────────────────────────────────────────────────────────
class BrokerClockSync:
    def __init__(self, symbol: str = CLOCK_ANCHOR_SYMBOL):
        self._symbol         = symbol
        self._last_tick_utc: Optional[datetime] = None

    def refresh(self) -> None:
        tick = mt5.symbol_info_tick(self._symbol)
        if tick: self._last_tick_utc = datetime.fromtimestamp(tick.time, pytz.utc)

    def now_utc(self) -> datetime:
        return self._last_tick_utc if self._last_tick_utc else datetime.now(pytz.utc)

    def now_strategy(self) -> datetime:
        return self.now_utc().astimezone(STRATEGY_TZ)

    def t(self) -> dtime:
        return self.now_strategy().time()


# ─────────────────────────────────────────────────────────────────────────────
#  FRIDAY GUARD
# ─────────────────────────────────────────────────────────────────────────────
class FridayGuard:
    def __init__(self, clock: BrokerClockSync):
        self._clock = clock; self._eod_done = False

    def _reset_on_monday(self) -> None:
        now = self._clock.now_utc()
        if now.weekday() == 0 and now.hour >= 22: self._eod_done = False

    def is_close_time(self) -> bool:
        now = self._clock.now_utc()
        if now.weekday() != 4: return False
        return (now.hour > FRIDAY_CLOSE_UTC_HOUR or
                (now.hour == FRIDAY_CLOSE_UTC_HOUR and now.minute >= FRIDAY_CLOSE_UTC_MIN))

    def is_blocked(self) -> bool:
        if not FRIDAY_CLOSE_ENABLED: return False
        self._reset_on_monday()
        now = self._clock.now_utc()
        return self.is_close_time() or now.weekday() in (5, 6)

    def execute_eod_close(self, execution: "ExecutionHandler") -> None:
        if self._eod_done: return
        self._eod_done = True
        log.warning("📅 FRIDAY EOD: Flattening ALL symbols…")
        for sym in ACTIVE_SYMBOLS:
            for ord_ in (mt5.orders_get(symbol=sym) or []):
                if ord_.magic == MAGIC_NUMBER:
                    execution.cancel_pending_order(ord_.ticket); time.sleep(0.1)
            for pos in (mt5.positions_get(symbol=sym) or []):
                if pos.magic == MAGIC_NUMBER:
                    execution.close_position_market(pos, is_eod=True); time.sleep(0.2)
        log.warning("📅 FRIDAY EOD: Done.")


# ─────────────────────────────────────────────────────────────────────────────
#  CONNECTION MANAGER
# ─────────────────────────────────────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self._lock = threading.RLock(); self._connected = False
        self._attempt = 0; self._next_retry_at = 0.0
        self._filling_cache_dirty = False

    def ensure_connected(self) -> bool:
        with self._lock:
            if mt5.terminal_info() is not None:
                self._connected = True; self._attempt = 0; return True
            now = time.time()
            if now < self._next_retry_at: return False
            if self._attempt >= RECONNECT_MAX_ATTEMPTS:
                log.error("⛔ Max reconnect attempts"); return False
            self._attempt += 1
            delay = min(RECONNECT_BASE_DELAY * (2 ** (self._attempt - 1)), RECONNECT_MAX_DELAY)
            log.warning(f"🔌 Reconnect #{self._attempt} in {delay:.0f}s")
            if mt5.initialize():
                log.info(f"✅ Reconnected on attempt #{self._attempt}")
                self._connected = True; self._attempt = 0; self._next_retry_at = 0.0
                self._filling_cache_dirty = True; return True
            self._connected = False; self._next_retry_at = now + delay; return False

    @property
    def is_connected(self) -> bool: return self._connected

    @property
    def filling_cache_dirty(self) -> bool:
        with self._lock:
            dirty = self._filling_cache_dirty
            if dirty: self._filling_cache_dirty = False
        return dirty


# ─────────────────────────────────────────────────────────────────────────────
#  SPREAD GUARD
# ─────────────────────────────────────────────────────────────────────────────
class SpreadGuard:
    def __init__(self, window: int = SPREAD_MEDIAN_BARS, hard_block_pts: float = HARD_SPREAD_BLOCK):
        self._buf: deque = deque(maxlen=window)
        self._hard_block = hard_block_pts

    def update(self, spread_pts: float) -> None:
        if 0.1 < spread_pts < self._hard_block * 20: self._buf.append(spread_pts)

    def is_ok(self, current_pts: float) -> Tuple[bool, str]:
        if current_pts > self._hard_block:
            return False, f"HARD_BLOCK:{current_pts:.1f}>{self._hard_block}pts"
        if len(self._buf) >= 5:
            median = float(np.median(self._buf)); cap = median * SPREAD_DYNAMIC_MULT
            if current_pts > cap:
                return False, f"DYN_BLOCK:{current_pts:.1f}>{cap:.1f}pts"
        return True, ""

    @property
    def median_spread(self) -> float:
        return float(np.median(self._buf)) if self._buf else 0.0


# ─────────────────────────────────────────────────────────────────────────────
#  NEWS GUARD
# ─────────────────────────────────────────────────────────────────────────────
class NewsGuard:
    def __init__(self):
        self._events: List[Dict] = []; self._last_load = 0.0

    def _maybe_reload(self) -> None:
        if time.time() - self._last_load < 300: return
        try:
            if os.path.isfile(NEWS_EVENTS_FILE):
                with open(NEWS_EVENTS_FILE, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                self._events = [e for e in raw
                                if e.get("impact", "").upper() == "HIGH"
                                and e.get("currency", "") in ("USD", "XAU", "GOLD")]
            self._last_load = time.time()
        except Exception as exc:
            log.warning(f"NewsGuard reload: {exc}"); self._last_load = time.time()

    def is_blocked(self, now: datetime) -> Tuple[bool, str]:
        self._maybe_reload()
        buf = timedelta(minutes=NEWS_BUFFER_MIN)
        for ev in self._events:
            try:
                ts = datetime.fromisoformat(ev["ts_utc"]).replace(tzinfo=pytz.utc)
                ts_local = ts.astimezone(STRATEGY_TZ)
                if ts_local - buf <= now <= ts_local + buf:
                    return True, ev.get("event", "HIGH-IMPACT")
            except Exception:
                continue
        t = now.time()
        for sh, sm, eh, em in NEWS_STATIC_FALLBACK:
            if dtime(sh, sm) <= t <= dtime(eh, em): return True, "StaticNewsBlock"
        return False, ""


# ─────────────────────────────────────────────────────────────────────────────
#  DATABASE LAYER
# ─────────────────────────────────────────────────────────────────────────────
_tls            = threading.local()
_write_q:       Optional[_queue_module.Queue] = None
_writer_thread: Optional[threading.Thread]    = None


def _get_read_conn() -> sqlite3.Connection:
    if not hasattr(_tls, "conn") or _tls.conn is None:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-4000")
        _tls.conn = conn
    return _tls.conn


def _writer_loop(q: _queue_module.Queue) -> None:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL"); conn.execute("PRAGMA synchronous=NORMAL")
    warn_threshold = int(q.maxsize * 0.8)
    while True:
        item = q.get()
        if item is None: conn.close(); break
        sql, params, done_ev = item
        if q.qsize() > warn_threshold:
            log.warning(f"⚠️ DB queue at {q.qsize()}/{q.maxsize}")
        try:
            conn.execute(sql, params); conn.commit()
        except Exception as exc:
            log.warning(f"DB writer: {exc} | {sql[:60]}")
        finally:
            if done_ev: done_ev.set()
        q.task_done()


def _db_exec(sql: str, params: tuple = (), wait: bool = False,
             drop_on_full: bool = False) -> None:
    global _write_q
    if _write_q is None: raise RuntimeError("DB writer not init")
    ev = threading.Event() if wait else None
    if drop_on_full and _write_q.full():
        return
    try:
        _write_q.put((sql, params, ev), block=not drop_on_full, timeout=1.0)
    except _queue_module.Full:
        log.warning(f"⚠️ DB full — dropped: {sql[:40]}"); return
    if ev: ev.wait(timeout=5.0)


def _db_query(sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
    try: return _get_read_conn().execute(sql, params).fetchone()
    except Exception as exc: log.warning(f"DB read: {exc}"); return None


def _db_query_all(sql: str, params: tuple = ()) -> List[sqlite3.Row]:
    try: return _get_read_conn().execute(sql, params).fetchall()
    except Exception: return []


def init_db() -> None:
    global _write_q, _writer_thread
    if _write_q is None:
        _write_q = _queue_module.Queue(maxsize=500)
        _writer_thread = threading.Thread(
            target=_writer_loop, args=(_write_q,), name="DBWriter", daemon=True)
        _writer_thread.start()
    schema_stmts = [
        """CREATE TABLE IF NOT EXISTS setup_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, signal TEXT, score INTEGER,
            entry REAL, sl REAL, tp REAL, setup_hash TEXT, session TEXT,
            win_prob REAL, sweep_type TEXT, shape TEXT, symbol TEXT)""",
        "CREATE TABLE IF NOT EXISTS cooldown (setup_hash TEXT PRIMARY KEY, expires_at REAL)",
        """CREATE TABLE IF NOT EXISTS trail_state (
            ticket INTEGER PRIMARY KEY, setup_hash TEXT, last_sl REAL,
            updated_at REAL, partial_done INTEGER DEFAULT 0)""",
        "CREATE TABLE IF NOT EXISTS bot_state (key TEXT PRIMARY KEY, value TEXT)",
        """CREATE TABLE IF NOT EXISTS trade_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, outcome TEXT, session TEXT)""",
        "CREATE INDEX IF NOT EXISTS idx_setup_ts ON setup_log(ts)",
        "CREATE INDEX IF NOT EXISTS idx_outcomes_ts ON trade_outcomes(ts)",
    ]
    for stmt in schema_stmts:
        _db_exec(stmt, wait=True)
    log.info("✅ DB V22 schema ready")


def close_db() -> None:
    global _write_q
    if _write_q: _write_q.put(None); _write_q = None
    if hasattr(_tls, "conn") and _tls.conn:
        try: _tls.conn.close()
        except Exception: pass
        _tls.conn = None


def is_on_cooldown(h: str) -> bool:
    row = _db_query("SELECT expires_at FROM cooldown WHERE setup_hash=?", (h,))
    return bool(row and row["expires_at"] > time.time())


def set_cooldown(h: str) -> None:
    _db_exec("INSERT OR REPLACE INTO cooldown VALUES(?,?)", (h, time.time() + SETUP_COOLDOWN_SEC))


def cleanup_cooldowns() -> None:
    _db_exec("DELETE FROM cooldown WHERE expires_at<=?", (time.time(),))


def db_log_setup(sig: str, score: int, entry: float, sl: float, tp: float,
                 h: str, session: str = "", win_prob: float = 0.0,
                 sweep_type: str = "", shape: str = "", symbol: str = "") -> None:
    _db_exec(
        "INSERT INTO setup_log(ts,signal,score,entry,sl,tp,setup_hash,session,"
        "win_prob,sweep_type,shape,symbol) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (time.time(), sig, score, entry, sl, tp, h, session, win_prob, sweep_type, shape, symbol))


def get_trail_state(ticket: int, setup_hash: str = "") -> Optional[sqlite3.Row]:
    row = _db_query("SELECT setup_hash,last_sl,partial_done FROM trail_state WHERE ticket=?", (ticket,))
    if row: return row
    if setup_hash:
        return _db_query("SELECT ticket,last_sl,partial_done FROM trail_state WHERE setup_hash=?",
                         (setup_hash,))
    return None


def save_trail_sl(ticket: int, sl: float, setup_hash: str = "",
                  partial_done: Optional[int] = None) -> None:
    ex  = get_trail_state(ticket, setup_hash)
    pd_ = int(ex["partial_done"]) if ex else 0
    if partial_done is not None: pd_ = partial_done
    _db_exec("INSERT OR REPLACE INTO trail_state VALUES(?,?,?,?,?)",
             (ticket, setup_hash or "", sl, time.time(), pd_))


def set_partial_done(ticket: int, setup_hash: str = "") -> None:
    ex = get_trail_state(ticket, setup_hash)
    ls = float(ex["last_sl"]) if ex else 0.0
    _db_exec("INSERT OR REPLACE INTO trail_state VALUES(?,?,?,?,?)",
             (ticket, setup_hash or "", ls, time.time(), 1))


def batch_load_trail_states(tickets: List[int]) -> Dict[int, sqlite3.Row]:
    if not tickets: return {}
    ph   = ",".join("?" * len(tickets))
    rows = _db_query_all(
        f"SELECT ticket,setup_hash,last_sl,partial_done FROM trail_state WHERE ticket IN ({ph})",
        tuple(tickets))
    return {int(r["ticket"]): r for r in rows}


def cleanup_trail_state(open_tickets: set) -> None:
    if not open_tickets: _db_exec("DELETE FROM trail_state"); return
    ph = ",".join("?" * len(open_tickets))
    _db_exec(f"DELETE FROM trail_state WHERE ticket NOT IN ({ph})", tuple(open_tickets))


def record_trade_outcome(outcome: str, session: str) -> None:
    if outcome in ("WIN", "LOSS", "PARTIAL"):
        _db_exec("INSERT INTO trade_outcomes(ts,outcome,session) VALUES(?,?,?)",
                 (time.time(), outcome, session))


def get_state(key: str, default=None):
    row = _db_query("SELECT value FROM bot_state WHERE key=?", (key,))
    return json.loads(row["value"]) if row else default


def set_state(key: str, value) -> None:
    _db_exec("INSERT OR REPLACE INTO bot_state VALUES(?,?)", (key, json.dumps(value)))


# ─────────────────────────────────────────────────────────────────────────────
#  CONSECUTIVE LOSS CACHE (thread-safe)
# ─────────────────────────────────────────────────────────────────────────────
class _ConsecLossCache:
    def __init__(self):
        self._lock = threading.Lock(); self._value = 0; self._ts = 0.0

    def get(self) -> int:
        with self._lock:
            if time.time() - self._ts < CONSEC_LOSS_CACHE_SEC: return self._value
        rows = _db_query_all(
            "SELECT outcome FROM trade_outcomes WHERE outcome IN ('WIN','LOSS') "
            "ORDER BY ts DESC LIMIT ?", (N_CONSEC_LOSS_PAUSE + 5,))
        count = 0
        for r in rows:
            if r["outcome"] == "LOSS": count += 1
            else: break
        with self._lock:
            self._value = count; self._ts = time.time()
        return count

    def invalidate(self) -> None:
        with self._lock: self._ts = 0.0


_consec_loss = _ConsecLossCache()

def get_consecutive_losses() -> int: return _consec_loss.get()
def invalidate_consec_loss_cache() -> None: _consec_loss.invalidate()

def is_consec_loss_paused() -> bool:
    row = _db_query("SELECT value FROM bot_state WHERE key='consec_loss_pause_until'")
    if row is None: return False
    until = json.loads(row["value"])
    if time.time() < until:
        log.info(f"⏸️ Consec-loss pause: {(until - time.time())/60:.0f}min remaining")
        return True
    return False

def set_consec_loss_pause() -> None:
    until = time.time() + CONSEC_LOSS_PAUSE_MIN * 60
    _db_exec("INSERT OR REPLACE INTO bot_state VALUES(?,?)",
             ("consec_loss_pause_until", json.dumps(until)))
    log.warning(f"⚠️ {N_CONSEC_LOSS_PAUSE} losses — pausing {CONSEC_LOSS_PAUSE_MIN}min")


# ─────────────────────────────────────────────────────────────────────────────
#  MARKET DATA FEED
# ─────────────────────────────────────────────────────────────────────────────
class MarketDataFeed:
    def __init__(self):
        self._cache: Dict[Tuple, Tuple[float, pd.DataFrame]] = {}
        self._lock  = threading.Lock()

    def _ttl(self, tf: int) -> float:
        if tf in (mt5.TIMEFRAME_M1, mt5.TIMEFRAME_M5): return CACHE_TTL_LTF
        if tf == mt5.TIMEFRAME_D1:  return CACHE_TTL_D1
        return CACHE_TTL_HTF

    def fetch(self, tf: int, n: int, symbol: str = SYMBOL,
              use_cache: bool = True) -> Optional[pd.DataFrame]:
        key = (tf, symbol); now = time.time()
        with self._lock:
            if use_cache and key in self._cache:
                ts, df = self._cache[key]
                if now - ts < self._ttl(tf): return df
        try:
            rates = mt5.copy_rates_from_pos(symbol, tf, 0, n)
        except Exception: rates = None
        if rates is None or len(rates) == 0: return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        with self._lock: self._cache[key] = (now, df)
        return df

    def fetch_all(self, symbol: str = SYMBOL) -> Dict[str, Optional[pd.DataFrame]]:
        def _trim(df):
            return df.iloc[:-1].copy() if df is not None and len(df) > 1 else df
        return {
            "m5":  _trim(self.fetch(mt5.TIMEFRAME_M5,   300, symbol, use_cache=False)),
            "m15": _trim(self.fetch(mt5.TIMEFRAME_M15,  100, symbol, use_cache=True)),
            "h1":  _trim(self.fetch(mt5.TIMEFRAME_H1,  H1_BARS, symbol, use_cache=True)),
            "h4":  _trim(self.fetch(mt5.TIMEFRAME_H4,  HTF_BARS, symbol, use_cache=True)),
            "d1":       self.fetch(mt5.TIMEFRAME_D1,    20, symbol, use_cache=True),
        }

    def get_current_m5_bar_time(self, symbol: str = SYMBOL) -> Optional[int]:
        try:
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 1)
            if rates is not None and len(rates) > 0: return int(rates[0]["time"])
        except Exception: pass
        return None


# ─────────────────────────────────────────────────────────────────────────────
#  RISK MANAGER
# ─────────────────────────────────────────────────────────────────────────────
class RiskManager:
    def __init__(self):
        self._spread_guards: Dict[str, SpreadGuard] = {
            sym: SpreadGuard(hard_block_pts=profile["spread_block_pts"])
            for sym, profile in ACTIVE_SYMBOLS.items()
        }
        self._default_sg = SpreadGuard()
        self._dd_cache: Optional[Tuple[float, float, str]] = None
        self._dd_cache_ts: float = 0.0
        self._dd_lock = threading.Lock()

    def _sg(self, sym: str) -> SpreadGuard:
        return self._spread_guards.get(sym, self._default_sg)

    @staticmethod
    def get_broker_date() -> str:
        tick = mt5.symbol_info_tick(CLOCK_ANCHOR_SYMBOL)
        if tick: return datetime.fromtimestamp(tick.time, tz=pytz.utc).strftime("%Y%m%d")
        return datetime.utcnow().strftime("%Y%m%d")

    def get_spread_pts(self, symbol: str = SYMBOL) -> float:
        tick = mt5.symbol_info_tick(symbol); info = mt5.symbol_info(symbol)
        if tick is None or info is None: return 999.0
        sp = (tick.ask - tick.bid) / info.point
        self._sg(symbol).update(sp); return sp

    def is_spread_ok(self, symbol: str = SYMBOL) -> Tuple[bool, str]:
        sp = self.get_spread_pts(symbol)
        return self._sg(symbol).is_ok(sp)

    @staticmethod
    def get_spread_sl_padding(symbol: str = SYMBOL) -> float:
        if not SPREAD_SL_PADDING: return 0.0
        tick = mt5.symbol_info_tick(symbol); info = mt5.symbol_info(symbol)
        if tick is None or info is None: return 0.0
        return ((tick.ask - tick.bid) / info.point) * info.point

    def get_dd_state(self) -> Tuple[float, float, str]:
        now = time.time()
        with self._dd_lock:
            if self._dd_cache is not None and (now - self._dd_cache_ts) < DD_STATE_TTL:
                return self._dd_cache
        acct = mt5.account_info()
        if acct is None: return 0.0, 0.0, "NORMAL"
        today_key   = "daily_start_balance_" + self.get_broker_date()
        daily_start = get_state(today_key)
        if daily_start is None or daily_start <= 0:
            set_state(today_key, acct.balance); daily_start = acct.balance
        daily_dd = max(0.0, (daily_start - acct.equity) / daily_start * 100)
        init_bal  = get_state("initial_balance")
        if init_bal is None:
            set_state("initial_balance", acct.balance); init_bal = acct.balance
        total_dd = max(0.0, (init_bal - acct.equity) / init_bal * 100)
        if daily_dd >= MAX_DAILY_LOSS_PCT or total_dd >= MAX_TOTAL_DD_PCT: mode = "RED"
        elif daily_dd >= DD_ORANGE_PCT: mode = "ORANGE"
        elif daily_dd >= DD_YELLOW_PCT: mode = "YELLOW"
        else: mode = "NORMAL"
        result = (round(daily_dd, 2), round(total_dd, 2), mode)
        with self._dd_lock: self._dd_cache = result; self._dd_cache_ts = now
        return result

    def is_within_risk_limits(self) -> bool:
        _, _, mode = self.get_dd_state(); return mode != "RED"

    def new_entries_allowed(self) -> bool:
        _, _, mode = self.get_dd_state(); return mode not in ("RED", "ORANGE")

    def is_circuit_breaker_tripped(self) -> bool:
        daily_dd, _, _ = self.get_dd_state()
        if daily_dd >= CIRCUIT_BREAKER_PCT:
            log.warning(f"⚡ CB: DD {daily_dd:.2f}%"); return True
        return False

    def get_risk_pct(self, score: int, dd_mode: str) -> float:
        base = RISK_TIERS[-1][1]
        for sm, pct in RISK_TIERS:
            if score >= sm: base = pct; break
        if dd_mode == "YELLOW":
            ci = next((i for i, (sm, _) in enumerate(RISK_TIERS) if score >= sm),
                      len(RISK_TIERS) - 1)
            base = RISK_TIERS[min(ci + 1, len(RISK_TIERS) - 1)][1]
        return base

    @staticmethod
    def _round_lot(lot: float, step: float) -> float:
        d = Decimal(str(lot)); s = Decimal(str(step))
        return float((d / s).to_integral_value(rounding=ROUND_DOWN) * s)

    def calculate_lot(self, entry: float, sl: float, score: int = 0,
                      spread_pts: float = 0.0, atr: float = 0.0,
                      dd_mode: str = "NORMAL", symbol: str = SYMBOL) -> float:
        info = mt5.symbol_info(symbol); acct = mt5.account_info()
        sym_profile = ACTIVE_SYMBOLS.get(symbol, {})
        sym_min_lot = sym_profile.get("min_lot", 0.01)
        if info is None or acct is None: return sym_min_lot
        risk_pct = self.get_risk_pct(score, dd_mode)
        if spread_pts > MAX_SPREAD_POINTS: risk_pct *= (1.0 - SPREAD_LOT_PENALTY)
        # [C5] Use live tick value from MT5 (exact broker value)
        tick_val = info.trade_tick_value or (info.trade_contract_size * info.point)
        if tick_val <= 0: return sym_min_lot
        sl_dist = abs(entry - sl)
        if sl_dist == 0: return sym_min_lot
        sl_pts  = max(1.0, sl_dist / info.point)
        # [C5] Hard USD cap on risk per trade
        risk_amount = min(
            acct.balance * risk_pct / 100.0,
            MAX_LOSS_PER_TRADE_USD
        )
        raw_lot = risk_amount / (sl_pts * tick_val)
        step    = info.volume_step if info.volume_step > 0 else 0.01
        lot     = self._round_lot(raw_lot, step)
        if lot <= 0.0: lot = max(info.volume_min, sym_min_lot)
        lot = max(max(info.volume_min, sym_min_lot), min(lot, info.volume_max, 100.0))
        log.info(f"💰 [{symbol}] Score:{score} DD:{dd_mode} Risk:{risk_pct:.2f}% → {lot} lots")
        return float(lot)

    @staticmethod
    def dynamic_deviation(atr: float, emergency: bool = False, symbol: str = SYMBOL) -> int:
        if emergency: return int(EMERGENCY_DEVIATION_POINTS)
        info = mt5.symbol_info(symbol)
        if info is None or info.point == 0: return int(MAX_DEVIATION_POINTS)
        return int(min(max(20, int(atr * 0.08 / info.point)), MAX_DEVIATION_POINTS))

    @staticmethod
    def validate_order(entry: float, sl: float, tp: float, lot: float,
                       signal: str, symbol: str = SYMBOL) -> Tuple[bool, str]:
        info = mt5.symbol_info(symbol); acct = mt5.account_info(); tick = mt5.symbol_info_tick(symbol)
        if not all([info, acct, tick]): return False, "Cannot read broker data"
        min_d = info.trade_stops_level * info.point
        if abs(entry - sl) < min_d: return False, "SL too close"
        if abs(entry - tp) < min_d: return False, "TP too close"
        otype = mt5.ORDER_TYPE_BUY if signal == "BUY" else mt5.ORDER_TYPE_SELL
        margin_req = mt5.order_calc_margin(otype, symbol, lot, entry)
        if margin_req is None or margin_req > acct.margin_free * 0.9:
            return False, "Insufficient margin"
        return True, "OK"

    @staticmethod
    def has_duplicate_setup(setup_hash: str, symbol: str = SYMBOL) -> bool:
        for p in (mt5.positions_get(symbol=symbol) or []):
            if p.magic == MAGIC_NUMBER and setup_hash in (p.comment or ""): return True
        for o in (mt5.orders_get(symbol=symbol) or []):
            if o.magic == MAGIC_NUMBER and setup_hash in (o.comment or ""): return True
        return False

    @staticmethod
    def count_open_positions(symbol: str = SYMBOL) -> int:
        return sum(1 for p in (mt5.positions_get(symbol=symbol) or [])
                   if p.magic == MAGIC_NUMBER)

    @staticmethod
    def count_all_open_positions() -> int:
        return sum(
            1 for sym in ACTIVE_SYMBOLS
            for p in (mt5.positions_get(symbol=sym) or [])
            if p.magic == MAGIC_NUMBER
        )

    @staticmethod
    def calculate_floating_risk_pct() -> float:
        acct = mt5.account_info()
        if acct is None or acct.balance <= 0: return 0.0
        total_risk = 0.0
        for sym in ACTIVE_SYMBOLS:
            info = mt5.symbol_info(sym)
            if info is None: continue
            tick_val = info.trade_tick_value or (info.trade_contract_size * info.point)
            for pos in (mt5.positions_get(symbol=sym) or []):
                if pos.magic != MAGIC_NUMBER: continue
                if pos.sl != 0.0 and info.point > 0:
                    sl_pts    = abs(pos.price_open - pos.sl) / info.point
                    risk_usd  = sl_pts * tick_val * pos.volume
                else:
                    risk_usd  = getattr(pos, "margin", 0.0)
                total_risk += max(0.0, risk_usd)
        return (total_risk / acct.balance) * 100.0


# ─────────────────────────────────────────────────────────────────────────────
#  EXECUTION HANDLER
# ─────────────────────────────────────────────────────────────────────────────
class ExecutionHandler:
    def __init__(self, risk: RiskManager, conn_mgr: Optional[ConnectionManager] = None):
        self._risk     = risk
        self._conn_mgr = conn_mgr
        self._lock     = threading.Lock()
        self._filling_mode_cache: Dict[str, int] = {}

    def _get_filling_mode(self, symbol: str = SYMBOL) -> int:
        if self._conn_mgr is not None and self._conn_mgr.filling_cache_dirty:
            self._filling_mode_cache.clear()
        if symbol in self._filling_mode_cache:
            return self._filling_mode_cache[symbol]
        info = mt5.symbol_info(symbol)
        if info is None: return mt5.ORDER_FILLING_IOC
        fm = getattr(info, "filling_mode", 0)
        if fm & 1:   mode = mt5.ORDER_FILLING_FOK
        elif fm & 2: mode = mt5.ORDER_FILLING_IOC
        else:        mode = mt5.ORDER_FILLING_RETURN
        self._filling_mode_cache[symbol] = mode
        return mode

    def _inject_filling(self, req: dict) -> dict:
        if req.get("action") in (mt5.TRADE_ACTION_SLTP, mt5.TRADE_ACTION_REMOVE):
            return req
        if "type_filling" not in req:
            req["type_filling"] = self._get_filling_mode(req.get("symbol", SYMBOL))
        return req

    def _send_retry(self, req: dict, retries: int = 3) -> Optional[object]:
        req = self._inject_filling(req)
        if "deviation" in req: req["deviation"] = int(req["deviation"])
        last_res = None
        is_buy   = req.get("type") in (mt5.ORDER_TYPE_BUY, mt5.ORDER_TYPE_BUY_LIMIT,
                                        mt5.ORDER_TYPE_BUY_STOP)
        for i in range(1, retries + 1):
            try:
                with self._lock: res = mt5.order_send(req)
            except Exception as exc:
                log.warning(f"order_send exc (try {i}): {exc}")
                if i < retries: time.sleep(0.5); continue
            if res is None:
                if i < retries: time.sleep(0.5); continue
            last_res = res
            if res.retcode == mt5.TRADE_RETCODE_DONE: return res
            if res.retcode == mt5.TRADE_RETCODE_DONE_PARTIAL:
                self._adjust_partial_fill(getattr(res, "order", 0),
                                           req.get("sl", 0.0), req.get("tp", 0.0))
                return res
            if res.retcode in (mt5.TRADE_RETCODE_REQUOTE,
                               mt5.TRADE_RETCODE_PRICE_CHANGED,
                               mt5.TRADE_RETCODE_PRICE_OFF):
                req_sym = req.get("symbol", SYMBOL)
                tick = mt5.symbol_info_tick(req_sym)
                if tick:
                    new_p = tick.ask if is_buy else tick.bid
                    req["price"] = round(float(new_p), 2)
                if i < retries: time.sleep(0.3 * i); continue
            if res.retcode in (mt5.TRADE_RETCODE_CONNECTION, mt5.TRADE_RETCODE_TIMEOUT):
                if i < retries: time.sleep(0.5 * i); continue
            log.error(f"❌ retcode:{res.retcode} | {res.comment}"); return res
        log.error(f"❌ _send_retry exhausted"); return last_res

    def _adjust_partial_fill(self, ticket: int, sl: float, tp: float) -> None:
        if ticket == 0: return
        for _ in range(3):
            time.sleep(0.5)
            if mt5.positions_get(ticket=ticket):
                with self._lock:
                    mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": ticket,
                                    "sl": round(float(sl), 2), "tp": round(float(tp), 2)})
                return

    def modify_sl(self, ticket: int, new_sl: float) -> None:
        try:
            with self._lock:
                res = mt5.order_send({"action": mt5.TRADE_ACTION_SLTP,
                                       "position": ticket, "sl": round(float(new_sl), 2)})
            if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
                log.warning(f"modify_sl FAIL #{ticket}")
        except Exception as exc:
            log.warning(f"modify_sl exc #{ticket}: {exc}")

    def close_partial(self, pos, lot_close: float, atr: float = 0.0,
                      symbol: str = SYMBOL) -> None:
        try:
            tick = mt5.symbol_info_tick(symbol)
            if tick is None: return
            info      = mt5.symbol_info(symbol)
            step      = info.volume_step if info else 0.01
            v_min     = info.volume_min  if info else 0.01
            lot_close = float(max(v_min, min(self._risk._round_lot(lot_close, step), pos.volume)))
            is_buy    = (pos.type == mt5.ORDER_TYPE_BUY)
            price     = tick.bid if is_buy else tick.ask
            dev       = int(self._risk.dynamic_deviation(atr, symbol=symbol))
            res = self._send_retry({
                "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol,
                "volume": lot_close, "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
                "position": pos.ticket, "price": round(float(price), 2),
                "deviation": dev, "magic": MAGIC_NUMBER, "comment": "V22|PartialTP"})
            if res and res.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL):
                log.info(f"💰 [{symbol}] PartialTP #{pos.ticket} {lot_close:.3f}@{price:.2f}")
        except Exception as exc:
            log.warning(f"close_partial exc [{symbol}]: {exc}")

    def close_position_market(self, pos, is_eod: bool = False,
                              symbol: str = SYMBOL) -> bool:
        try:
            pos_symbol = getattr(pos, "symbol", symbol) or symbol
            tick = mt5.symbol_info_tick(pos_symbol); info = mt5.symbol_info(pos_symbol)
            if tick is None or info is None: return False
            is_buy = (pos.type == mt5.ORDER_TYPE_BUY)
            res = self._send_retry({
                "action": mt5.TRADE_ACTION_DEAL, "symbol": pos_symbol,
                "volume": pos.volume,
                "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
                "position": pos.ticket,
                "price": round(float(tick.bid if is_buy else tick.ask), 2),
                "deviation": int(EMERGENCY_DEVIATION_POINTS), "magic": MAGIC_NUMBER,
                "comment": f"V22|{'EOD' if is_eod else 'KILL'}"}, retries=5)
            ok = res is not None and res.retcode in (mt5.TRADE_RETCODE_DONE,
                                                      mt5.TRADE_RETCODE_DONE_PARTIAL)
            log.info(f"{'✅' if ok else '❌'} [{pos_symbol}] {'EOD' if is_eod else 'Kill'} #{pos.ticket}")
            return ok
        except Exception as exc:
            log.warning(f"close_market exc: {exc}"); return False

    def cancel_pending_order(self, ticket: int) -> bool:
        try:
            with self._lock:
                res = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": ticket})
            ok = res is not None and res.retcode == mt5.TRADE_RETCODE_DONE
            log.info(f"{'✅' if ok else '❌'} Cancel #{ticket}"); return ok
        except Exception as exc:
            log.warning(f"cancel exc: {exc}"); return False

    def place_order(self, setup: SetupResult, session: str = "",
                    dd_mode: str = "NORMAL", adr: float = 0.0,
                    df_d1=None, symbol: str = SYMBOL) -> bool:
        sp_ok, sp_reason = self._risk.is_spread_ok(symbol)
        if not sp_ok:
            log.warning(f"⛔ [{symbol}] Spread: {sp_reason}"); return False
        if not setup.in_session:
            sp = self._risk.get_spread_pts(symbol)
            if sp > OOS_HARD_SPREAD_BLOCK:
                log.warning(f"⛔ [{symbol}] OOS spread {sp:.1f}pts > {OOS_HARD_SPREAD_BLOCK}"); return False
        if not self._risk.is_within_risk_limits(): return False
        if self._risk.has_duplicate_setup(setup.setup_hash, symbol):
            log.info(f"🚫 [{symbol}] Duplicate → skip"); return False
        if self._risk.count_open_positions(symbol) >= MAX_TRADES_PER_SYMBOL:
            log.info(f"⚠️ [{symbol}] Per-symbol cap reached → skip"); return False
        if self._risk.count_all_open_positions() >= GLOBAL_MAX_CONCURRENT_TRADES:
            log.info(f"⚠️ Global cap → skip [{symbol}]"); return False
        if self._risk.calculate_floating_risk_pct() >= MAX_GLOBAL_EXPOSURE_PCT:
            log.warning(f"⚠️ [{symbol}] Exposure cap → skip"); return False

        sp     = self._risk.get_spread_pts(symbol)
        sl_pad = self._risk.get_spread_sl_padding(symbol)

        # M1 micro-confirmation
        try:
            rates_m1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 8)
            if rates_m1 is not None and len(rates_m1) >= 4:
                df_m1 = pd.DataFrame(rates_m1); c = df_m1.iloc[-2]
                body_m1 = abs(float(c["close"]) - float(c["open"]))
                dir_ok  = ((setup.signal == "BUY"  and c["close"] > c["open"]) or
                           (setup.signal == "SELL" and c["close"] < c["open"]))
                from smc_core_v22 import SCORE_M1_CONFIRM
                if body_m1 >= setup.atr * MTF_M1_BODY_ATR and dir_ok:
                    setup.score += SCORE_M1_CONFIRM
                    setup.reasons.append(f"M1 Disp +{SCORE_M1_CONFIRM}")
        except Exception: pass

        tick = mt5.symbol_info_tick(symbol)
        if tick is None: return False

        sig    = setup.signal
        sl_adj = (setup.sl - sl_pad) if sig == "BUY" else (setup.sl + sl_pad)

        # [C1] Market order: use live tick price, anchor SL to structure
        if setup.use_market:
            entry  = tick.ask if sig == "BUY" else tick.bid
            # [C1] Recalculate SL from live entry preserving structural distance
            sym_mult = ACTIVE_SYMBOLS[symbol]["sl_atr_mult"]
            sl_adj   = (min(setup.sl, entry - setup.atr * sym_mult) if sig == "BUY"
                        else max(setup.sl, entry + setup.atr * sym_mult))
            otype  = mt5.ORDER_TYPE_BUY if sig == "BUY" else mt5.ORDER_TYPE_SELL
            action = mt5.TRADE_ACTION_DEAL; exp = 0
        else:
            entry = setup.entry
            otype  = mt5.ORDER_TYPE_BUY_LIMIT if sig == "BUY" else mt5.ORDER_TYPE_SELL_LIMIT
            action = mt5.TRADE_ACTION_PENDING
            exp    = int(time.time()) + (EXPIRATION_CANDLES * 5 * 60)
            if sig == "BUY" and entry >= tick.ask:
                entry = tick.ask; otype = mt5.ORDER_TYPE_BUY; action = mt5.TRADE_ACTION_DEAL; exp = 0
            elif sig == "SELL" and entry <= tick.bid:
                entry = tick.bid; otype = mt5.ORDER_TYPE_SELL; action = mt5.TRADE_ACTION_DEAL; exp = 0

        risk = abs(entry - sl_adj)
        if risk == 0: log.error(f"[{symbol}] risk=0"); return False

        # RR floor check (live)
        if action == mt5.TRADE_ACTION_DEAL:
            info_sym = mt5.symbol_info(symbol)
            if info_sym:
                tp_check  = entry + risk * RR_RATIO if sig == "BUY" else entry - risk * RR_RATIO
                actual_rr = abs(tp_check - entry) / max(risk, info_sym.point)
                if actual_rr < MIN_RR_RATIO_LIVE:
                    log.warning(f"⛔ [{symbol}] RR {actual_rr:.2f} < {MIN_RR_RATIO_LIVE}"); return False

        tp_raw  = entry + risk * RR_RATIO if sig == "BUY" else entry - risk * RR_RATIO
        tp_full, capped = apply_adr_tp_cap(entry, tp_raw, sl_adj, adr, df_d1, session, sig)

        lot_full = self._risk.calculate_lot(entry, sl_adj, setup.score, sp, setup.atr,
                                             dd_mode, symbol=symbol)
        ok, reason = self._risk.validate_order(entry, sl_adj, tp_full, lot_full, sig, symbol)
        if not ok: log.warning(f"⚠️ [{symbol}] Validate: {reason}"); return False

        info   = mt5.symbol_info(symbol)
        step   = info.volume_step if info else 0.01; v_min = info.volume_min if info else 0.01
        # [C9] Split: 60% partial, 40% run
        lot_a  = max(v_min, self._risk._round_lot(lot_full * PARTIAL_TP_PCT, step))
        lot_b  = max(v_min, self._risk._round_lot(lot_full - lot_a, step))
        tp_pt  = entry + risk * PARTIAL_TP_RR if sig == "BUY" else entry - risk * PARTIAL_TP_RR
        dev    = int(self._risk.dynamic_deviation(setup.atr, symbol=symbol))

        sent = 0
        for lot_i, tp_i, label in [(lot_a, tp_pt, "PT"), (lot_b, tp_full, "FT")]:
            req = {"action": action, "symbol": symbol, "volume": lot_i, "type": otype,
                   "price": round(float(entry), 2), "sl": round(float(sl_adj), 2),
                   "tp": round(float(tp_i), 2), "deviation": dev, "magic": MAGIC_NUMBER,
                   "comment": f"V22|{sig}|{label}|{setup.score}|{setup.setup_hash}"}
            if action == mt5.TRADE_ACTION_PENDING:
                req["type_time"] = mt5.ORDER_TIME_SPECIFIED; req["expiration"] = exp
            res = self._send_retry(req)
            if res and res.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL):
                sent += 1
                log.info(f"✅ [{symbol}] {label}|{sig}|Lot:{lot_i:.3f}|E:{entry:.2f}|"
                         f"SL:{sl_adj:.2f}|TP:{tp_i:.2f}")
            else:
                log.warning(f"⚠️ [{symbol}] {label} order failed")

        if sent > 0:
            log.info(
                f"\n{'═'*70}\n"
                f"  🎯 TRADE V22 [{symbol}] — {sig} {'MKT' if setup.use_market else 'LMT'}"
                f"  {'⚡JUDAS' if setup.is_judas else ''}  {'✨GOLDEN' if setup.golden_conf else ''}\n"
                f"  {'─'*68}\n"
                f"  Entry:{entry:.2f}  SL:{sl_adj:.2f}  TP-Pt:{tp_pt:.2f}  TP-Full:{tp_full:.2f}\n"
                f"  Risk:{risk:.2f}  Lot:{lot_a}+{lot_b}  Score:{setup.score}/{setup.threshold}\n"
                f"  Session:{session}  H4:{setup.htf_bias}  H1:{setup.h1_bias}  Shape:{setup.shape}\n"
                f"  Spread:{sp:.1f}pts  Global:{self._risk.count_all_open_positions()}/"
                f"{GLOBAL_MAX_CONCURRENT_TRADES}  Exp:{self._risk.calculate_floating_risk_pct():.1f}%\n"
                f"  Hash:{setup.setup_hash}\n{'═'*70}"
            )
            db_log_setup(sig, setup.score, entry, sl_adj, tp_full,
                         setup.setup_hash, session, 0.0, setup.sweep_type, setup.shape, symbol)
            return True
        return False


# ─────────────────────────────────────────────────────────────────────────────
#  POSITION MANAGER  (Hit & Run + orphan recovery)
# ─────────────────────────────────────────────────────────────────────────────
class PositionManager:
    def __init__(self, feed: MarketDataFeed, execution: ExecutionHandler,
                 conn_mgr: ConnectionManager):
        self._feed = feed; self._exec = execution; self._conn = conn_mgr
        self._running = threading.Event(); self._running.set()
        self._thread: Optional[threading.Thread] = None
        self._last_orphan_check: float = 0.0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="PM", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        if self._thread: self._thread.join(timeout=5)

    def _loop(self) -> None:
        while self._running.is_set():
            try:
                if self._conn.ensure_connected():
                    for sym in ACTIVE_SYMBOLS:
                        # [C4] fetch 20 bars to guarantee ATR != 0
                        df_m5 = self._feed.fetch(mt5.TIMEFRAME_M5, 20, symbol=sym, use_cache=True)
                        atr   = calculate_atr(df_m5) if df_m5 is not None else 1.0
                        self._manage_positions(atr, symbol=sym)
                        self._orphan_sl_check(atr, symbol=sym)
            except Exception as exc:
                log.warning(f"⚠️ PM error: {exc}")
            time.sleep(POSITION_POLL_SEC)

    def _orphan_sl_check(self, atr: float, symbol: str = SYMBOL) -> None:
        now = time.time()
        if now - self._last_orphan_check < ORPHAN_SL_CHECK_INTERVAL: return
        self._last_orphan_check = now
        for pos in (mt5.positions_get(symbol=symbol) or []):
            if pos.magic != MAGIC_NUMBER or pos.sl != 0.0: continue
            log.warning(f"🚨 ORPHAN [{symbol}] #{pos.ticket}: SL=0 — reconstructing")
            ts_row = None
            try: ts_row = get_trail_state(pos.ticket)
            except Exception: pass
            if ts_row and float(ts_row["last_sl"]) != 0.0:
                recovered_sl = float(ts_row["last_sl"])
            else:
                sym_mult = ACTIVE_SYMBOLS.get(symbol, {}).get("sl_atr_mult", 1.5)
                safe_atr = max(atr, 0.5)
                is_buy   = (pos.type == mt5.ORDER_TYPE_BUY)
                recovered_sl = ((pos.price_open - safe_atr * sym_mult) if is_buy
                                else (pos.price_open + safe_atr * sym_mult))
            self._exec.modify_sl(pos.ticket, recovered_sl)

    def _detect_closed_positions(self, current_tickets: set, symbol: str = SYMBOL) -> None:
        sym_key = f"_prev_{symbol}"
        prev    = getattr(self, sym_key, set())
        closed  = prev - current_tickets
        for ticket in closed:
            try:
                deals = mt5.history_deals_get(ticket=ticket)
                if deals:
                    profit  = sum(d.profit for d in deals)
                    outcome = "WIN" if profit > 0 else "LOSS"
                    record_trade_outcome(outcome, "")
                    log.info(f"📊 [{symbol}] Closed #{ticket}: {outcome} (${profit:.2f})")
                    invalidate_consec_loss_cache()
                    if get_consecutive_losses() >= N_CONSEC_LOSS_PAUSE:
                        set_consec_loss_pause()
            except Exception as exc:
                log.warning(f"_detect_closed [{symbol}]: {exc}")
        setattr(self, sym_key, current_tickets)

    def _manage_positions(self, atr: float, symbol: str = SYMBOL) -> None:
        positions = [p for p in (mt5.positions_get(symbol=symbol) or [])
                     if p.magic == MAGIC_NUMBER]
        current_tickets = {p.ticket for p in positions}
        self._detect_closed_positions(current_tickets, symbol)
        if not positions: return

        tick = mt5.symbol_info_tick(symbol); info = mt5.symbol_info(symbol)
        if tick is None or info is None: return
        a           = max(atr, info.point * 10)
        trail_cache = batch_load_trail_states(list(current_tickets))

        for pos in positions:
            entry = pos.price_open; sl_now = pos.sl
            is_buy = (pos.type == mt5.ORDER_TYPE_BUY)
            parts  = (pos.comment or "").split("|")
            pos_hash = parts[-1] if len(parts) >= 5 else ""
            risk = abs(entry - sl_now)
            if risk < info.point: risk = a * 1.5
            price    = tick.bid if is_buy else tick.ask
            buf      = info.point * 5
            profit_r = (price - entry) / risk if is_buy else (entry - price) / risk
            ts       = trail_cache.get(pos.ticket)
            partial_done = int(ts["partial_done"]) if ts else 0

            # ── [C9] STEP 1: Partial TP @1R — close 60% ──────────────────────
            if not partial_done and profit_r >= PARTIAL_TP_RR:
                self._exec.close_partial(pos, pos.volume * PARTIAL_TP_PCT,
                                          atr=a, symbol=symbol)
                set_partial_done(pos.ticket, pos_hash)
                log.info(f"💰 [{symbol}] Partial @{profit_r:.2f}R #{pos.ticket}")

            # ── STEP 2: Delayed Breakeven ──────────────────────────────────────
            if profit_r >= BREAKEVEN_DELAY_RR:
                be_sl = (entry + buf) if is_buy else (entry - buf)
                if (is_buy and sl_now < be_sl) or (not is_buy and sl_now > be_sl):
                    self._exec.modify_sl(pos.ticket, be_sl)
                    log.info(f"🔒 [{symbol}] BE #{pos.ticket} SL:{sl_now:.2f}→{be_sl:.2f}")

            # ── STEP 3: Trail SL ───────────────────────────────────────────────
            if profit_r >= TRAIL_AFTER_RR:
                last_tsl = float(ts["last_sl"]) if ts else None
                min_move = a * TRAIL_MIN_MOVE_ATR
                if is_buy:
                    new_tsl = price - (a * TRAIL_ATR_MULT)
                    if new_tsl > sl_now and (last_tsl is None or new_tsl > last_tsl + min_move):
                        self._exec.modify_sl(pos.ticket, new_tsl)
                        save_trail_sl(pos.ticket, new_tsl, pos_hash)
                        log.info(f"📈 [{symbol}] Trail #{pos.ticket} {sl_now:.2f}→{new_tsl:.2f}")
                else:
                    new_tsl = price + (a * TRAIL_ATR_MULT)
                    if new_tsl < sl_now and (last_tsl is None or new_tsl < last_tsl - min_move):
                        self._exec.modify_sl(pos.ticket, new_tsl)
                        save_trail_sl(pos.ticket, new_tsl, pos_hash)
                        log.info(f"📉 [{symbol}] Trail #{pos.ticket} {sl_now:.2f}→{new_tsl:.2f}")

            log.debug(f"📍 [{symbol}] #{pos.ticket}: ${pos.profit:+.2f} ({profit_r:+.2f}R)")

        cleanup_trail_state(current_tickets)


# ─────────────────────────────────────────────────────────────────────────────
#  SESSION HELPERS (live version uses clock)
# ─────────────────────────────────────────────────────────────────────────────
class SessionHelper:
    def __init__(self, clock: BrokerClockSync, news_guard: NewsGuard):
        self._clock = clock; self._news_guard = news_guard

    def get_session(self) -> str:
        now = self._clock.now_strategy()
        blocked, event = self._news_guard.is_blocked(now)
        if blocked: log.info(f"📰 News: {event}"); return "RED_NEWS_BLOCK"
        from smc_core_v22 import SESSIONS, NEWS_STATIC_FALLBACK
        t = now.time()
        for sh, sm, eh, em in NEWS_STATIC_FALLBACK:
            if dtime(sh, sm) <= t <= dtime(eh, em): return "RED_NEWS_BLOCK"
        for sh, sm, eh, em, name in SESSIONS:
            s, e = dtime(sh, sm), dtime(eh, em)
            if e < s:
                if t >= s or t <= e: return name
            else:
                if s <= t <= e: return name
        return "OUT_OF_SESSION"

    def is_in_killzone(self) -> Tuple[bool, str]:
        from smc_core_v22 import KILLZONES
        t = self._clock.t()
        for sh, sm, eh, em, name in KILLZONES:
            if dtime(sh, sm) <= t <= dtime(eh, em): return True, name
        return False, "Outside KZ"


# ─────────────────────────────────────────────────────────────────────────────
#  GRACEFUL SHUTDOWN
# ─────────────────────────────────────────────────────────────────────────────
def graceful_shutdown(execution: ExecutionHandler, reason: str = "EXIT") -> None:
    log.warning(f"🚨 SHUTDOWN — {reason}")
    for sym in ACTIVE_SYMBOLS:
        for o in (mt5.orders_get(symbol=sym) or []):
            if o.magic == MAGIC_NUMBER: execution.cancel_pending_order(o.ticket)
    time.sleep(0.5)
    for sym in ACTIVE_SYMBOLS:
        for pos in (mt5.positions_get(symbol=sym) or []):
            if pos.magic == MAGIC_NUMBER:
                execution.close_position_market(pos, symbol=sym); time.sleep(0.2)
    acct = mt5.account_info()
    if acct: log.warning(f"🚨 Final: equity${acct.equity:,.2f} balance${acct.balance:,.2f}")
    log.warning("🚨 SHUTDOWN COMPLETE.")


# ─────────────────────────────────────────────────────────────────────────────
#  SIGNAL CYCLE (per-symbol, called on new M5 bar close only)
# ─────────────────────────────────────────────────────────────────────────────
def _run_signal_cycle(
    feed: MarketDataFeed, sess_helper: SessionHelper,
    risk: RiskManager, execution: ExecutionHandler,
    conn_mgr: ConnectionManager, friday_guard: FridayGuard,
    last_ctx: Dict, symbol: str = SYMBOL,
) -> None:
    if not conn_mgr.ensure_connected(): return
    if friday_guard.is_blocked():
        friday_guard.execute_eod_close(execution); return

    daily_dd, total_dd, dd_mode = risk.get_dd_state()
    if dd_mode == "RED":
        log.warning(f"⛔ DD RED daily={daily_dd:.2f}% total={total_dd:.2f}%"); return
    if risk.is_circuit_breaker_tripped(): return

    session = sess_helper.get_session()
    if session == "RED_NEWS_BLOCK": return

    if risk.count_all_open_positions() >= GLOBAL_MAX_CONCURRENT_TRADES:
        log.info(f"⚠️ [{symbol}] Global cap → skip"); return
    if risk.calculate_floating_risk_pct() >= MAX_GLOBAL_EXPOSURE_PCT:
        log.info(f"⚠️ [{symbol}] Exposure cap → skip"); return

    in_kz, kz_name = sess_helper.is_in_killzone()
    log.info(f"📍 [{symbol}] Session:{session} KZ:{kz_name}")

    sp_ok, sp_reason = risk.is_spread_ok(symbol)
    if not sp_ok: log.warning(f"⛔ [{symbol}] Spread: {sp_reason}"); return

    if os.path.isfile(PAUSE_FLAG_PATH): log.info("⏸️ PAUSE.flag → skip"); return
    if not risk.new_entries_allowed(): log.warning(f"🟠 {dd_mode} → suspended"); return
    if is_consec_loss_paused(): return

    data = feed.fetch_all(symbol=symbol)
    if data["m5"] is None: log.warning(f"[{symbol}] M5 N/A"); return
    cleanup_cooldowns()

    profile = ACTIVE_SYMBOLS[symbol]
    setup   = analyze_setup(
        data["m5"], data["h4"], data["d1"], data["m15"], data.get("h1"),
        session, feed._clock.now_utc() if hasattr(feed, "_clock") else datetime.now(pytz.utc),
        in_kz, risk.get_spread_pts(symbol), profile["sl_atr_mult"],  # [C3]
    )
    # NOTE: analyze_setup needs bar_time — pass via a thin wrapper below

    last_ctx.update({"bias": setup.htf_bias, "h1_bias": setup.h1_bias,
                     "session": session, "adr_pct": str(setup.adr_pct)})

    if setup.signal == "WAIT" or setup.score < setup.threshold:
        log.info(f"⚠️ [{symbol}] {setup.signal} score:{setup.score}/{setup.threshold}"); return

    if is_on_cooldown(setup.setup_hash):
        log.info(f"🔁 [{symbol}] Cooldown → skip"); return
    if risk.has_duplicate_setup(setup.setup_hash, symbol):
        log.info(f"🚫 [{symbol}] Duplicate → skip"); return

    log.info(f"🔥 [{symbol}] {setup.summary()}")

    adr_val = calculate_adr(data.get("d1"))
    if execution.place_order(setup, session, dd_mode, adr=adr_val,
                              df_d1=data.get("d1"), symbol=symbol):
        set_cooldown(setup.setup_hash)


# ─────────────────────────────────────────────────────────────────────────────
#  HEARTBEAT
# ─────────────────────────────────────────────────────────────────────────────
def emit_heartbeat(risk: RiskManager, session: str, htf_bias: str,
                   h1_bias: str, adr_pct: float) -> None:
    acct = mt5.account_info()
    if acct is None: return
    daily_dd, total_dd, dd_mode = risk.get_dd_state()
    init_bal  = get_state("initial_balance") or acct.balance
    eq_pct    = (acct.equity - init_bal) / init_bal * 100 if init_bal > 0 else 0
    global_pos = risk.count_all_open_positions()
    floating   = risk.calculate_floating_risk_pct()
    sym_list   = ", ".join(ACTIVE_SYMBOLS.keys())
    log.info(
        f"\n{'═'*70}\n"
        f"  📊  STATUS V22  [{datetime.now(STRATEGY_TZ).strftime('%H:%M:%S')} BKK]\n"
        f"  Equity    : ${acct.equity:>10,.2f}  ({eq_pct:+.2f}%)\n"
        f"  DD Daily  : {daily_dd:.2f}%   DD Total: {total_dd:.2f}%   Mode: {dd_mode}\n"
        f"  Session   : {session:<16} H4:{htf_bias:<10} H1:{h1_bias:<10}\n"
        f"  Global Pos: {global_pos}/{GLOBAL_MAX_CONCURRENT_TRADES} | "
        f"Floating Risk: {floating:.1f}%/{MAX_GLOBAL_EXPOSURE_PCT}%\n"
        f"  Symbols   : {sym_list}\n"
        f"  Thresholds: NY={SCORE_THRESHOLD_IN_SESSION} "
        f"LDN=82 NY_EARLY=85 OOS={SCORE_THRESHOLD_OUT_SESSION}\n"
        f"{'═'*70}"
    )


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────────
BANNER = """
╔══════════════════════════════════════════════════════════════════════════════════╗
║  🌐  SMC/ICT Pro Sniper  —  V.22  "Perfected Kamikaze Scanner"                  ║
║                                                                                  ║
║  SHARED CORE: smc_core_v22.py  (same analyze_setup as backtest — 1:1 mirror)   ║
║  [C1]  Market-Order Entry fixed      [C3]  sl_atr_mult per-symbol               ║
║  [C4]  ATR n=20 for trail            [C5]  Exact tick-value PnL math            ║
║  [C6]  H4 Neutral = -8 penalty       [C7]  Redundant bonuses removed            ║
║  [C8]  LONDON=82, NY_EARLY=85        [C9]  60% partial@1R, BE, trail@1.5R      ║
║  [C10] Min 2.0R liquidity gate       MAX_LOSS_PER_TRADE_USD = $3.00 armour      ║
╚══════════════════════════════════════════════════════════════════════════════════╝
"""


def main() -> None:
    print(BANNER)
    log.info("Bot V.22 starting")
    init_db()

    conn_mgr = ConnectionManager()
    for delay in [0, 5, 10, 20, 30]:
        if delay: time.sleep(delay)
        if conn_mgr.ensure_connected(): break
    else:
        log.error("❌ Cannot connect to MT5"); return

    clock        = BrokerClockSync(CLOCK_ANCHOR_SYMBOL)
    clock.refresh()
    feed         = MarketDataFeed()
    news_guard   = NewsGuard()
    sess_helper  = SessionHelper(clock, news_guard)
    risk         = RiskManager()
    execution    = ExecutionHandler(risk, conn_mgr)
    friday_guard = FridayGuard(clock)

    # Monkey-patch clock onto feed for signal_cycle use
    feed._clock = clock  # type: ignore

    pm = PositionManager(feed, execution, conn_mgr)
    pm.start()

    # Startup orphan scan
    log.info("Startup orphan SL scan…")
    for sym in ACTIVE_SYMBOLS:
        for pos in (mt5.positions_get(symbol=sym) or []):
            if pos.magic == MAGIC_NUMBER and pos.sl == 0.0:
                log.warning(f"Orphan [{sym}] #{pos.ticket} SL=0")

    last_ctx: Dict = {"bias": "NEUTRAL", "h1_bias": "NEUTRAL",
                       "session": "UNKNOWN", "adr_pct": "0.0"}
    last_closed_bar: Dict[str, Optional[int]] = {sym: None for sym in ACTIVE_SYMBOLS}
    last_heartbeat  = time.time()
    _shutdown       = threading.Event()

    def _sig_handler(signum, frame):
        log.warning(f"Signal {signum} → shutdown"); _shutdown.set()

    signal.signal(signal.SIGTERM, _sig_handler)
    signal.signal(signal.SIGINT,  _sig_handler)

    log.info(f"🌐 Round-Robin scanner ACTIVE | {', '.join(ACTIVE_SYMBOLS.keys())}")

    try:
        while not _shutdown.is_set():
            if os.path.isfile(KILL_FLAG_PATH):
                log.warning("🚨 KILL.flag"); _shutdown.set(); break
            if not conn_mgr.ensure_connected():
                time.sleep(TICK_POLL_SEC); continue
            clock.refresh()

            if friday_guard.is_blocked():
                friday_guard.execute_eod_close(execution)
                time.sleep(60); continue

            # ── ROUND-ROBIN bar poll ──────────────────────────────────────────
            for sym in list(ACTIVE_SYMBOLS.keys()):
                if _shutdown.is_set(): break
                try:
                    latest_rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, 2)
                except Exception as exc:
                    log.warning(f"[{sym}] copy_rates exc: {exc}"); time.sleep(0.1); continue

                if latest_rates is None or len(latest_rates) < 2:
                    time.sleep(0.1); continue

                prev_closed_ts = int(latest_rates[-2]["time"])
                if prev_closed_ts != last_closed_bar[sym]:
                    log.info(f"🕯️ [{sym}] New M5 bar closed: {prev_closed_ts}")
                    last_closed_bar[sym] = prev_closed_ts

                    # Build bar_time for analyze_setup
                    bar_time = datetime.fromtimestamp(prev_closed_ts, pytz.utc)

                    # Fetch all TF data for this symbol
                    data = feed.fetch_all(symbol=sym)
                    if data["m5"] is None:
                        log.warning(f"[{sym}] M5 N/A"); time.sleep(0.1); continue

                    session = sess_helper.get_session()
                    if session in ("OUT_OF_SESSION", "RED_NEWS_BLOCK"):
                        time.sleep(0.1); continue

                    in_kz, kz_name = sess_helper.is_in_killzone()

                    # ── All pre-trade gates ───────────────────────────────────
                    daily_dd, _, dd_mode = risk.get_dd_state()
                    if dd_mode == "RED": time.sleep(0.1); continue
                    if risk.is_circuit_breaker_tripped(): time.sleep(0.1); continue
                    if risk.count_all_open_positions() >= GLOBAL_MAX_CONCURRENT_TRADES:
                        time.sleep(0.1); continue
                    if risk.calculate_floating_risk_pct() >= MAX_GLOBAL_EXPOSURE_PCT:
                        time.sleep(0.1); continue
                    if risk.count_open_positions(sym) >= MAX_TRADES_PER_SYMBOL:
                        time.sleep(0.1); continue
                    sp_ok, sp_reason = risk.is_spread_ok(sym)
                    if not sp_ok:
                        log.warning(f"⛔ [{sym}] {sp_reason}"); time.sleep(0.1); continue
                    if os.path.isfile(PAUSE_FLAG_PATH): time.sleep(0.1); continue
                    if not risk.new_entries_allowed(): time.sleep(0.1); continue
                    if is_consec_loss_paused(): time.sleep(0.1); continue

                    cleanup_cooldowns()
                    profile = ACTIVE_SYMBOLS[sym]

                    setup = analyze_setup(
                        data["m5"], data["h4"], data["d1"], data["m15"], data.get("h1"),
                        session, bar_time, in_kz,
                        risk.get_spread_pts(sym), profile["sl_atr_mult"],  # [C3]
                    )

                    last_ctx.update({"bias": setup.htf_bias, "h1_bias": setup.h1_bias,
                                     "session": session, "adr_pct": str(setup.adr_pct)})

                    if setup.signal == "WAIT" or setup.score < setup.threshold:
                        log.info(f"  [{sym}] {setup.signal} {setup.score}/{setup.threshold}")
                    elif is_on_cooldown(setup.setup_hash):
                        log.info(f"  [{sym}] Cooldown → skip")
                    elif risk.has_duplicate_setup(setup.setup_hash, sym):
                        log.info(f"  [{sym}] Duplicate → skip")
                    else:
                        log.info(f"  🔥 [{sym}] {setup.summary()}")
                        adr_val = calculate_adr(data.get("d1"))
                        if execution.place_order(setup, session, dd_mode,
                                                  adr=adr_val, df_d1=data.get("d1"),
                                                  symbol=sym):
                            set_cooldown(setup.setup_hash)

                time.sleep(0.1)   # 100ms between symbols — MT5 rate-limit guard
            # ── END ROUND-ROBIN ───────────────────────────────────────────────

            now = time.time()
            if now - last_heartbeat >= HEARTBEAT_SEC:
                emit_heartbeat(risk, last_ctx.get("session", "?"),
                               last_ctx.get("bias", "?"), last_ctx.get("h1_bias", "?"),
                               float(last_ctx.get("adr_pct", "0")))
                last_heartbeat = now

            remaining = TICK_POLL_SEC - (len(ACTIVE_SYMBOLS) * 0.1)
            if remaining > 0: time.sleep(remaining)

    except KeyboardInterrupt:
        log.info("🛑 KeyboardInterrupt")
    except Exception as exc:
        log.exception(f"💥 Unhandled: {exc}")
    finally:
        pm.stop()
        graceful_shutdown(execution)
        close_db()
        try: mt5.shutdown()
        except Exception: pass
        log.info("MT5 offline. Bot V.22 terminated.")


if __name__ == "__main__":
    main()
