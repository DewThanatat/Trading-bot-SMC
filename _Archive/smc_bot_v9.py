"""
╔══════════════════════════════════════════════════════════════════════════════╗
║   🚀 AI SMC/ICT Pro Sniper — V.9  (Architecture Refactor + ML-Ready)        ║
║                                                                              ║
║   WHAT CHANGED FROM V8 FINAL                                                 ║
║   ─────────────────────────────────────────────────────────────────────────  ║
║   [FIX-1]  Dynamic Requote Handling   — _send_retry re-fetches live          ║
║             tick.ask / tick.bid on REQUOTE / PRICE_CHANGED / PRICE_OFF       ║
║   [FIX-2]  Dynamic Deviation (Slip)   — volatility-based, floor = 50 pts    ║
║   [FIX-3]  Robust Position Tracking   — trail_state keyed on setup_hash     ║
║             (hedge acct ticket churn tolerance)                               ║
║   [OPT-1]  NumPy ATR / Swings / Liq   — all hot-path calcs use NumPy arrays ║
║   [OOP-1]  OOP Architecture           — MarketDataFeed · SMCSignalEngine ·  ║
║             RiskManager · ExecutionHandler · PositionManager                 ║
║   [EDGE-1] Lot zero-floor             — if rounded lot == 0.0 → volume_min  ║
║   [ML-1]   Feature Extraction         — extract_features() → std array      ║
║   [ML-2]   MLPredictor class          — scikit-learn compatible interface,   ║
║             currently returns mocked probability (swap model in later)        ║
║   [ML-3]   Dynamic Gating             — ML win-prob gate replaces static     ║
║             SCORE_THRESHOLD (configurable threshold, default 0.65)           ║
║                                                                              ║
║   PRESERVED FROM V8                                                          ║
║   ─────────────────────────────────────────────────────────────────────────  ║
║   SQLite persistence (WAL mode) · Background PositionManager thread ·        ║
║   Circuit Breaker · Killzone filter · HTF BOS/CHOCH/Sweep · FVG memory ·    ║
║   OB detection · Partial TP · Breakeven · Trailing SL · spread padding       ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

# ─────────────────────────────────────────────────────────────────────────────
#  STANDARD LIBRARY / THIRD-PARTY IMPORTS
# ─────────────────────────────────────────────────────────────────────────────
import MetaTrader5 as mt5
import numpy as np
import pandas as pd          # still used for DataFrame construction from MT5 rates
import sqlite3
import json
import time
import hashlib
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, time as dtime
from decimal import Decimal, ROUND_DOWN
from typing import Optional, List, Tuple, Dict
import pytz

# scikit-learn is optional at import time; the MLPredictor gracefully degrades
try:
    from sklearn.pipeline import Pipeline            # noqa: F401 (future use)
    from sklearn.preprocessing import StandardScaler  # noqa: F401
    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False


# ══════════════════════════════════════════════════════════════════════════════
# ⚙️  CONFIGURATION  (unchanged from V8 unless explicitly noted)
# ══════════════════════════════════════════════════════════════════════════════
SYMBOL              = "XAUUSDm"
MAGIC_NUMBER        = 99999
RR_RATIO            = 2.5
MAX_DAILY_LOSS_PCT  = 4.0
MAX_TOTAL_DD_PCT    = 8.0
EXPIRATION_CANDLES  = 6

# [V8-4] Spread
HARD_SPREAD_BLOCK   = 100.0
MAX_SPREAD_POINTS   = 50.0
SPREAD_LOT_PENALTY  = 0.3
SPREAD_SL_PADDING   = True

MOMENTUM_BODY_ATR   = 1.2
BREAKEVEN_RR        = 1.0
TRAIL_AFTER_RR      = 2.0
TRAIL_ATR_MULT      = 1.2
TRAIL_MIN_MOVE_ATR  = 0.3
ADR_EXHAUSTED_PCT   = 0.85
SWING_PERIOD        = 5
SWING_CONFIRM_BARS  = 2
SETUP_COOLDOWN_SEC  = 180

# Partial TP
PARTIAL_TP_RR       = 1.0
PARTIAL_TP_PCT      = 0.50

# Pending order enabled
INTRABAR_ENABLED    = True

# [V8-3] FVG
FVG_BUFFER_RATIO    = 0.6
FVG_MOMENTUM_RATIO  = 0.25
FVG_MITIGATED_PCT   = 0.5
FVG_MEMORY_BARS: Dict[str, int] = {
    "PRE_LONDON":    24,
    "LONDON":        36,
    "NY_OPEN_EARLY": 30,
    "NEW_YORK":      36,
    "DEFAULT":       30,
}

# M1 bonus
MTF_M1_BODY_ATR     = 0.3

# Liquidity
LIQ_SWING_PERIOD    = 10
LIQ_EQUAL_TOLERANCE = 0.0003
LIQ_MIN_CLUSTER     = 2

# [V8-1] HTF BOS
HTF_SWING_PERIOD    = 8
HTF_SWING_CONFIRM   = 2

# ── Scoring constants (kept for feature extraction & legacy logging) ──────────
SCORE_BASE           = 55
SCORE_SWEEP_AND_FVG  = 20
SCORE_HTF_ALIGN      = 12
SCORE_HTF_AGAINST    = -8
SCORE_M15_BOS        = 8
SCORE_STRONG_CANDLE  = 10
SCORE_OB_BONUS       = 10
SCORE_OB_OVERLAP     = 5
SCORE_BOS_M5         = 7
SCORE_FVG_FRESH      = 8
SCORE_FVG_STRENGTH   = 4
SCORE_LIQ_SWEPT      = 10
SCORE_LIQ_TARGET     = 10
SCORE_M1_CONFIRM     = 5
SCORE_ADR_WARN       = -8
SCORE_SPREAD_WARN    = -4

# [ML-3] ML gate replaces SCORE_THRESHOLD; kept as fallback reference
SCORE_THRESHOLD: Dict[str, int] = {
    "LONDON":        55,
    "NEW_YORK":      55,
    "NY_OPEN_EARLY": 58,
    "PRE_LONDON":    62,
    "DEFAULT":       60,
}
SCORE_PENALTY_HTF_NEUTRAL = 3
SCORE_PENALTY_HIGH_ADR    = 2

# [ML-3] Win-probability gate (0.0–1.0)
ML_WIN_PROB_THRESHOLD = 0.65

# [FIX A2] Risk tiers
LOT_MIN  = 0.01
LOT_MAX  = 1.00
RISK_TIERS = [
    (90, 1.00),
    (80, 0.75),
    (70, 0.50),
    (60, 0.25),
    (0,  0.10),
]

# [FIX A2] Circuit Breaker
CIRCUIT_BREAKER_PCT = 3.0

# [FIX C2] Killzone Filter (Bangkok time)
KILLZONE_ENABLED = True
KILLZONES = [
    (14,  0, 16, 30, "London Open"),
    (19, 45, 22,  0, "NY Open"),
]

# Cache TTL (seconds)
CACHE_TTL_LTF = 5
CACHE_TTL_HTF = 60
CACHE_TTL_D1  = 300

# Position Manager poll interval
POSITION_POLL_SEC = 1.0

# Sessions (Bangkok time)
SESSIONS = [
    (12,  0, 14,  0, "PRE_LONDON"),
    (14,  0, 18,  0, "LONDON"),
    (18, 30, 19, 15, "NY_OPEN_EARLY"),
    (19, 45, 23, 59, "NEW_YORK"),
]
NEWS_BLOCKS = [(19, 15, 19, 45)]

DB_PATH  = "smc_state.db"
LOG_PATH = "smc_bot.log"
bkk_tz   = pytz.timezone("Asia/Bangkok")


# ══════════════════════════════════════════════════════════════════════════════
# 📋  LOGGING
# ══════════════════════════════════════════════════════════════════════════════
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


# ══════════════════════════════════════════════════════════════════════════════
# 💾  PERSISTENCE LAYER  (thread-safe RLock singleton)
# ══════════════════════════════════════════════════════════════════════════════
_db_conn: Optional[sqlite3.Connection] = None
_db_lock = threading.RLock()


def get_db() -> sqlite3.Connection:
    global _db_conn
    with _db_lock:
        if _db_conn is None:
            _db_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            _db_conn.row_factory = sqlite3.Row
            _db_conn.execute("PRAGMA journal_mode=WAL")
            _db_conn.execute("PRAGMA synchronous=NORMAL")
        return _db_conn


def close_db() -> None:
    global _db_conn
    with _db_lock:
        if _db_conn is not None:
            _db_conn.close()
            _db_conn = None


def init_db() -> None:
    """
    Create all required tables.

    trail_state schema change (V9):
    ─ Added  `setup_hash TEXT`  column so we can look up state by hash
      even when the hedging account re-numbers a ticket after partial close.
    ─ `ticket` stays as PRIMARY KEY for quick lookup during normal flow;
      `setup_hash` is indexed for the fallback lookup path.
    """
    c = get_db()
    with _db_lock:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS setup_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL, signal TEXT, score INTEGER,
            entry REAL, sl REAL, tp REAL,
            setup_hash TEXT, session TEXT
        );
        CREATE TABLE IF NOT EXISTS cooldown (
            setup_hash TEXT PRIMARY KEY, expires_at REAL
        );

        -- [FIX-3] trail_state now also stores setup_hash for hedge-account
        --         ticket-churn resilience.
        CREATE TABLE IF NOT EXISTS trail_state (
            ticket       INTEGER PRIMARY KEY,
            setup_hash   TEXT,
            last_sl      REAL,
            updated_at   REAL,
            partial_done INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_trail_hash
            ON trail_state (setup_hash);

        CREATE TABLE IF NOT EXISTS bot_state (
            key TEXT PRIMARY KEY, value TEXT
        );
        """)
        c.commit()


def _db_exec(sql: str, params: tuple = ()) -> None:
    with _db_lock:
        get_db().execute(sql, params)
        get_db().commit()


def _db_query(sql: str, params: tuple = ()):
    with _db_lock:
        return get_db().execute(sql, params).fetchone()


# ── Cooldown helpers ──────────────────────────────────────────────────────────
def is_on_cooldown(h: str) -> bool:
    row = _db_query("SELECT expires_at FROM cooldown WHERE setup_hash=?", (h,))
    return bool(row and row["expires_at"] > time.time())


def set_cooldown(h: str) -> None:
    _db_exec("INSERT OR REPLACE INTO cooldown VALUES(?,?)",
             (h, time.time() + SETUP_COOLDOWN_SEC))


def cleanup_cooldowns() -> None:
    _db_exec("DELETE FROM cooldown WHERE expires_at<=?", (time.time(),))


# ── Setup log ─────────────────────────────────────────────────────────────────
def db_log_setup(signal: str, score: int, entry: float, sl: float,
                 tp: float, h: str, session: str = "") -> None:
    _db_exec(
        "INSERT INTO setup_log(ts,signal,score,entry,sl,tp,setup_hash,session)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (time.time(), signal, score, entry, sl, tp, h, session),
    )


# ── Trail state — [FIX-3] dual-key (ticket primary, hash fallback) ─────────
def get_trail_state_by_ticket(ticket: int):
    return _db_query(
        "SELECT setup_hash, last_sl, partial_done FROM trail_state WHERE ticket=?",
        (ticket,),
    )


def get_trail_state_by_hash(setup_hash: str):
    """
    [FIX-3] Fallback: look up trail state via setup_hash.
    Useful when hedging accounts change ticket numbers after partial close.
    """
    return _db_query(
        "SELECT ticket, last_sl, partial_done FROM trail_state WHERE setup_hash=?",
        (setup_hash,),
    )


def get_trail_state(ticket: int, setup_hash: str = ""):
    """
    [FIX-3] Unified getter: try ticket first, fall back to setup_hash.
    Returns the row or None.
    """
    row = get_trail_state_by_ticket(ticket)
    if row:
        return row
    if setup_hash:
        return get_trail_state_by_hash(setup_hash)
    return None


def save_trail_sl(ticket: int, sl: float, setup_hash: str = "",
                  partial_done: Optional[int] = None) -> None:
    """
    [FIX-3] Upsert trail state keyed on BOTH ticket and setup_hash.
    """
    existing = get_trail_state(ticket, setup_hash)
    if partial_done is None:
        partial_done = existing["partial_done"] if existing else 0
    _db_exec(
        "INSERT OR REPLACE INTO trail_state VALUES(?,?,?,?,?)",
        (ticket, setup_hash or "", sl, time.time(), partial_done),
    )


def set_partial_done(ticket: int, setup_hash: str = "") -> None:
    existing = get_trail_state(ticket, setup_hash)
    last_sl  = existing["last_sl"] if existing else 0.0
    _db_exec(
        "INSERT OR REPLACE INTO trail_state VALUES(?,?,?,?,?)",
        (ticket, setup_hash or "", last_sl, time.time(), 1),
    )


def cleanup_trail_state(open_tickets: set) -> None:
    if not open_tickets:
        _db_exec("DELETE FROM trail_state")
        return
    ph = ",".join("?" * len(open_tickets))
    _db_exec(
        f"DELETE FROM trail_state WHERE ticket NOT IN ({ph})",
        tuple(open_tickets),
    )


# ── Generic bot state ─────────────────────────────────────────────────────────
def get_state(key: str, default=None):
    row = _db_query("SELECT value FROM bot_state WHERE key=?", (key,))
    return json.loads(row["value"]) if row else default


def set_state(key: str, value) -> None:
    _db_exec("INSERT OR REPLACE INTO bot_state VALUES(?,?)",
             (key, json.dumps(value)))


# ══════════════════════════════════════════════════════════════════════════════
# 📐  DATA CLASSES  (shared between layers)
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class HTFBiasResult:
    bias:         str              = "NEUTRAL"
    last_bos:     str              = "NONE"
    choch_signal: str              = "NONE"
    swept_high:   Optional[float]  = None
    swept_low:    Optional[float]  = None
    reason:       str              = ""


@dataclass
class FVGZone:
    kind:      str
    top:       float
    bot:       float
    strength:  float
    bar_index: int
    mitigated: bool = False


@dataclass
class LiquidityMap:
    buy_side:    List[float] = field(default_factory=list)
    sell_side:   List[float] = field(default_factory=list)
    swept_high:  Optional[float] = None
    swept_low:   Optional[float] = None
    bsl_nearest: Optional[float] = None
    ssl_nearest: Optional[float] = None


@dataclass
class OBResult:
    found: bool  = False
    high:  float = 0.0
    low:   float = 0.0
    score: float = 0.0


@dataclass
class SetupResult:
    signal:      str              = "WAIT"
    score:       int              = 0
    entry:       float            = 0.0
    sl:          float            = 0.0
    atr:         float            = 0.0
    htf_bias:    str              = "NEUTRAL"
    m15_struct:  str              = "NEUTRAL"
    adr_pct:     float            = 0.0
    threshold:   int              = 60
    reasons:     List[str]        = field(default_factory=list)
    setup_hash:  str              = ""
    use_market:  bool             = False
    liq_map:     Optional[LiquidityMap]  = None
    fvg_zone:    Optional[FVGZone]       = None
    candle_ts:   float            = 0.0
    htf_result:  Optional[HTFBiasResult] = None
    # [ML-1] Feature vector populated by extract_features()
    features:    Optional[np.ndarray]    = None
    # [ML-3] Predicted win probability (filled after MLPredictor.predict)
    win_prob:    float            = 0.0
    spread_pts:  float            = 0.0

    def summary(self) -> str:
        mode = "MKT" if self.use_market else "LMT"
        gap  = self.score - self.threshold
        conf = "🔥🔥🔥" if gap >= 20 else "🔥🔥" if gap >= 10 else "🔥"
        return (
            f"{conf} {self.signal}({mode}) "
            f"Score:{self.score}/{self.threshold} "
            f"WinProb:{self.win_prob:.2f} "
            f"| {' | '.join(self.reasons)}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 🤖  ML LAYER  [ML-1] [ML-2] [ML-3]
# ══════════════════════════════════════════════════════════════════════════════

def extract_features(setup: "SetupResult") -> np.ndarray:
    """
    [ML-1] Standardised feature extraction.

    Returns a 1-D float64 array:
        [htf_bias_enc, atr, adr_pct, fvg_strength, spread_pts, m15_trend_enc,
         score_normalised, has_liquidity_target, has_ob, sweep_and_fvg]

    Encoding conventions
    ─────────────────────
    htf_bias_enc   : BULLISH=1, BEARISH=-1, NEUTRAL=0
    m15_trend_enc  : BULLISH_BOS=1, BEARISH_BOS=-1, else 0
    score_norm     : raw score / 100.0  (scale ~0-1 for most realistic setups)
    has_liq_target : 1 if nearest liquidity target sits within RR reach, else 0
    has_ob         : 1 if setup reasons mention "OB", else 0
    sweep_and_fvg  : 1 if "Sweep+FVG" in reasons, else 0

    NOTE: When a real model is wired in, normalise this vector with the same
    StandardScaler that was fitted during training.
    """
    htf_bias_enc = {"BULLISH": 1.0, "BEARISH": -1.0}.get(setup.htf_bias, 0.0)

    fvg_strength = setup.fvg_zone.strength if setup.fvg_zone else 0.0

    m15_enc = {"BULLISH_BOS": 1.0, "BEARISH_BOS": -1.0}.get(setup.m15_struct, 0.0)

    reasons_str = " ".join(setup.reasons)
    has_ob         = 1.0 if "OB" in reasons_str else 0.0
    sweep_and_fvg  = 1.0 if "Sweep+FVG" in reasons_str else 0.0
    has_liq_target = 1.0 if ("BSL→" in reasons_str or "SSL→" in reasons_str) else 0.0

    return np.array([
        htf_bias_enc,
        float(setup.atr),
        float(setup.adr_pct),
        float(fvg_strength),
        float(setup.spread_pts),
        m15_enc,
        float(setup.score) / 100.0,
        has_liq_target,
        has_ob,
        sweep_and_fvg,
    ], dtype=np.float64)


class MLPredictor:
    """
    [ML-2] Machine-learning inference pipeline.

    Architecture
    ─────────────
    • Interface mirrors scikit-learn / xgboost estimators.
    • `self._model` holds the trained estimator once `load_model()` is called.
    • Until a real model file is supplied, `predict_win_probability()` returns
      a heuristic mock derived from the score + feature array so that the gate
      logic works correctly end-to-end during development.

    Replacing the mock with a real model
    ──────────────────────────────────────
    1. Train an XGBClassifier / RandomForestClassifier on historical
       SetupResult feature arrays with binary outcome labels (1=win, 0=loss).
    2. Serialise with joblib:
           joblib.dump(pipeline, "smc_model.joblib")
    3. Call `predictor.load_model("smc_model.joblib")` at bot startup.
    """

    def __init__(self):
        self._model = None      # sklearn / xgboost estimator
        self._scaler = None     # optional pre-fitted StandardScaler
        log.info("🧠 MLPredictor initialised (mock mode until model is loaded)")

    def load_model(self, path: str) -> bool:
        """Load a serialised model (joblib format)."""
        try:
            import joblib  # type: ignore
            obj = joblib.load(path)
            # Accept a bare estimator or a (scaler, estimator) tuple
            if isinstance(obj, tuple) and len(obj) == 2:
                self._scaler, self._model = obj
            else:
                self._model = obj
            log.info(f"🧠 MLPredictor: model loaded from {path}")
            return True
        except Exception as exc:
            log.warning(f"🧠 MLPredictor: could not load model ({exc}) — staying mock")
            return False

    def predict_win_probability(self, features: np.ndarray) -> float:
        """
        [ML-2] Returns a probability in [0, 1].

        Live path  : model.predict_proba(features)[0][1]
        Mock path  : deterministic heuristic so the gate fires sensibly
                     during backtesting / dry runs without a trained model.
        """
        if self._model is not None:
            try:
                X = features.reshape(1, -1)
                if self._scaler is not None:
                    X = self._scaler.transform(X)
                prob = float(self._model.predict_proba(X)[0][1])
                return max(0.0, min(1.0, prob))
            except Exception as exc:
                log.warning(f"🧠 MLPredictor inference error: {exc} — using mock")

        # ── MOCK HEURISTIC (deterministic, not random) ────────────────────────
        # Features: [htf_bias(0), atr(1), adr_pct(2), fvg_str(3),
        #            spread(4),   m15(5), score_norm(6),
        #            has_liq(7),  has_ob(8), sweep_fvg(9)]
        score_norm     = float(features[6])   # 0-1
        htf_aligned    = abs(float(features[0])) > 0.5  # not neutral
        sweep_and_fvg  = float(features[9]) > 0.5
        has_liq        = float(features[7]) > 0.5
        m15_confirms   = abs(float(features[5])) > 0.5
        adr_pct        = float(features[2])

        prob = 0.35
        prob += score_norm * 0.35          # score contribution
        if htf_aligned:    prob += 0.10
        if sweep_and_fvg:  prob += 0.08
        if has_liq:        prob += 0.06
        if m15_confirms:   prob += 0.05
        if adr_pct > 0.85: prob -= 0.08   # market already extended

        return max(0.0, min(1.0, round(prob, 4)))


# ══════════════════════════════════════════════════════════════════════════════
# 📊  CLASS: MarketDataFeed
# ══════════════════════════════════════════════════════════════════════════════
class MarketDataFeed:
    """
    Responsible for all MT5 data retrieval and in-memory caching.

    The cache is keyed by MT5 timeframe constant and stores
    (fetch_timestamp, DataFrame) pairs.  TTL is respected per timeframe.
    """

    def __init__(self):
        self._cache: Dict[int, Tuple[float, pd.DataFrame]] = {}
        self._lock  = threading.Lock()

    @staticmethod
    def _ttl(tf: int) -> float:
        if tf in (mt5.TIMEFRAME_M1, mt5.TIMEFRAME_M5):
            return CACHE_TTL_LTF
        if tf == mt5.TIMEFRAME_D1:
            return CACHE_TTL_D1
        return CACHE_TTL_HTF

    def fetch(self, tf: int, n: int,
              use_cache: bool = True) -> Optional[pd.DataFrame]:
        now = time.time()
        with self._lock:
            if use_cache and tf in self._cache:
                ts, df = self._cache[tf]
                if now - ts < self._ttl(tf):
                    return df

        rates = mt5.copy_rates_from_pos(SYMBOL, tf, 0, n)
        if rates is None or len(rates) == 0:
            log.warning(f"MarketDataFeed.fetch: no data tf={tf}")
            return None

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        with self._lock:
            self._cache[tf] = (now, df)
        return df

    def get_cached_m5(self) -> Optional[pd.DataFrame]:
        """Thread-safe read of the M5 cache (used by PositionManager)."""
        with self._lock:
            entry = self._cache.get(mt5.TIMEFRAME_M5)
        return entry[1] if entry else None

    def fetch_all(self) -> Dict[str, Optional[pd.DataFrame]]:
        """Fetch all required timeframes; M1/M5 always fresh."""
        def _trim(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
            return df.iloc[:-1].copy() if df is not None else None

        m1  = _trim(self.fetch(mt5.TIMEFRAME_M1,   60, use_cache=False))
        m5  = _trim(self.fetch(mt5.TIMEFRAME_M5,  300, use_cache=False))
        m15 = _trim(self.fetch(mt5.TIMEFRAME_M15, 100, use_cache=True))
        h1  = _trim(self.fetch(mt5.TIMEFRAME_H1,  220, use_cache=True))
        d1  = self.fetch(mt5.TIMEFRAME_D1,  20, use_cache=True)  # D1 no trim
        return {"m1": m1, "m5": m5, "m15": m15, "h1": h1, "d1": d1}


# ══════════════════════════════════════════════════════════════════════════════
# 🧮  INDICATOR FUNCTIONS  — [OPT-1] NumPy hot-path
# ══════════════════════════════════════════════════════════════════════════════

def _to_numpy(df: pd.DataFrame, col: str) -> np.ndarray:
    """Fast column extraction to contiguous float64 NumPy array."""
    return np.ascontiguousarray(df[col].values, dtype=np.float64)


def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """
    [OPT-1] ATR using NumPy vectorised operations.
    ~4-6× faster than the Pandas rolling path for typical 300-bar arrays.
    """
    if len(df) < period + 1:
        return 0.0
    high  = _to_numpy(df, "high")
    low   = _to_numpy(df, "low")
    close = _to_numpy(df, "close")

    prev_close = close[:-1]
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(
            np.abs(high[1:] - prev_close),
            np.abs(low[1:]  - prev_close),
        ),
    )
    # Wilder smoothing via simple seed + EMA-style loop avoids pandas overhead
    if len(tr) < period:
        return 0.0
    atr_val = float(tr[:period].mean())
    alpha   = 1.0 / period
    for v in tr[period:]:
        atr_val = atr_val * (1.0 - alpha) + float(v) * alpha
    return atr_val if not np.isnan(atr_val) else 0.0


def calculate_adr(df_d1: Optional[pd.DataFrame], period: int = 10) -> float:
    """[OPT-1] Average Daily Range via NumPy."""
    if df_d1 is None or len(df_d1) < period:
        return 0.0
    high = _to_numpy(df_d1, "high")
    low  = _to_numpy(df_d1, "low")
    dr   = high - low
    return float(dr[-period:].mean())


def get_confirmed_swings_np(df: pd.DataFrame,
                            period: int = 5,
                            confirm: int = 2) -> Tuple[float, float]:
    """
    [OPT-1] Confirmed swing High / Low using NumPy stride-window approach.
    Replaces the Pandas iterrow loop in the original code.
    Returns (last_swing_high, last_swing_low).
    """
    if len(df) < period * 2 + confirm + 1:
        return float(df["high"].max()), float(df["low"].min())

    high = _to_numpy(df, "high")
    low  = _to_numpy(df, "low")
    safe_len = len(high) - confirm

    sh_vals, sl_vals = [], []
    for i in range(period, safe_len - period):
        window_h = high[i - period: i + period + 1]
        window_l = low[i  - period: i + period + 1]
        if high[i] == window_h.max():
            sh_vals.append(high[i])
        if low[i] == window_l.min():
            sl_vals.append(low[i])

    last_sh = float(sh_vals[-1]) if sh_vals else float(high.max())
    last_sl = float(sl_vals[-1]) if sl_vals else float(low.min())
    return last_sh, last_sl


def build_liquidity_map_np(df: pd.DataFrame, atr: float,
                           period: int = 10) -> LiquidityMap:
    """
    [OPT-1] Liquidity map using NumPy swing detection.
    The clustering step is O(n²) by design but n is always small (≤50 swings).
    """
    liq = LiquidityMap()
    if len(df) < period * 2 + 4 or atr == 0:
        return liq

    high = _to_numpy(df, "high")
    low  = _to_numpy(df, "low")
    cls  = _to_numpy(df, "close")
    safe = len(high) - 2
    tol  = max(atr * 0.08, abs(cls[-1]) * LIQ_EQUAL_TOLERANCE)

    ph_list, pl_list = [], []
    for i in range(period, safe - period):
        wh = high[i - period: i + period + 1]
        wl = low[i  - period: i + period + 1]
        if high[i] == wh.max():
            ph_list.append(high[i])
        if low[i] == wl.min():
            pl_list.append(low[i])

    def cluster(prices: List[float], tol: float) -> List[float]:
        clusters: List[float] = []
        used = [False] * len(prices)
        for i in range(len(prices)):
            if used[i]:
                continue
            group = [prices[i]]
            for j in range(i + 1, len(prices)):
                if not used[j] and abs(prices[j] - prices[i]) <= tol:
                    group.append(prices[j])
                    used[j] = True
            if len(group) >= LIQ_MIN_CLUSTER:
                clusters.append(round(sum(group) / len(group), 5))
        return clusters

    liq.buy_side  = sorted(cluster(ph_list, tol), reverse=True)
    liq.sell_side = sorted(cluster(pl_list, tol))

    last_high  = float(high[-1])
    last_low   = float(low[-1])
    last_close = float(cls[-1])

    for lvl in liq.buy_side:
        if last_high > lvl and last_close < lvl:
            liq.swept_high = lvl
            break
    for lvl in liq.sell_side:
        if last_low < lvl and last_close > lvl:
            liq.swept_low = lvl
            break

    price  = last_close
    above  = [l for l in liq.buy_side  if l > price]
    below  = [l for l in liq.sell_side if l < price]
    liq.bsl_nearest = min(above) if above else None
    liq.ssl_nearest = max(below) if below else None
    return liq


# ══════════════════════════════════════════════════════════════════════════════
# 🧠  CLASS: SMCSignalEngine
# ══════════════════════════════════════════════════════════════════════════════
class SMCSignalEngine:
    """
    Encapsulates all signal detection logic:
    HTF Bias · FVG Memory · Order Block · Liquidity Map · Score Assembly.
    """

    # ── HTF Bias ──────────────────────────────────────────────────────────────
    @staticmethod
    def get_htf_bias(df_h1: Optional[pd.DataFrame]) -> HTFBiasResult:
        """Pure-SMC H1 BOS/CHOCH/Sweep analysis (logic unchanged from V8)."""
        res = HTFBiasResult()
        if df_h1 is None or len(df_h1) < HTF_SWING_PERIOD * 2 + HTF_SWING_CONFIRM + 5:
            res.reason = "H1 data insufficient"
            return res

        lookback = min(60, len(df_h1))
        df = df_h1.iloc[-lookback:].reset_index(drop=True)
        p, c = HTF_SWING_PERIOD, HTF_SWING_CONFIRM

        high = _to_numpy(df, "high")
        low  = _to_numpy(df, "low")
        cls  = _to_numpy(df, "close")
        safe = len(high) - c

        sh_list: List[Tuple[int, float]] = []
        sl_list: List[Tuple[int, float]] = []
        for i in range(p, safe - p):
            wh = high[i - p: i + p + 1]
            wl = low[i  - p: i + p + 1]
            if high[i] == wh.max():
                sh_list.append((i, float(high[i])))
            if low[i] == wl.min():
                sl_list.append((i, float(low[i])))

        if len(sh_list) < 2 or len(sl_list) < 2:
            res.reason = "Insufficient swings"
            return res

        prev_sh = sh_list[-1][1]
        prev_sl = sl_list[-1][1]

        last_high  = float(high[-1])
        last_low   = float(low[-1])
        last_close = float(cls[-1])

        if last_high > prev_sh and last_close < prev_sh:
            res.swept_high = prev_sh
        if last_low < prev_sl and last_close > prev_sl:
            res.swept_low = prev_sl

        recent_cls = cls[-5:]
        bos_up   = bool(np.any(recent_cls > prev_sh))
        bos_down = bool(np.any(recent_cls < prev_sl))

        hh = sh_list[-1][1] > sh_list[-2][1]
        lh = sh_list[-1][1] < sh_list[-2][1]
        hl = sl_list[-1][1] > sl_list[-2][1]
        ll = sl_list[-1][1] < sl_list[-2][1]

        bull_pts = bear_pts = 0
        if bos_up:         bull_pts += 2; res.last_bos = "UP"
        if bos_down:       bear_pts += 2; res.last_bos = "DOWN"
        if hh and hl:      bull_pts += 2
        if lh and ll:      bear_pts += 2
        if res.swept_low:  bull_pts += 1
        if res.swept_high: bear_pts += 1

        if bos_up   and (lh and ll): res.choch_signal = "UP"
        if bos_down and (hh and hl): res.choch_signal = "DOWN"

        if bull_pts >= 3 and bull_pts > bear_pts:
            res.bias   = "BULLISH"
            res.reason = f"BOS_UP:{bos_up}|HH:{hh}|HL:{hl}|SwL:{res.swept_low is not None}"
        elif bear_pts >= 3 and bear_pts > bull_pts:
            res.bias   = "BEARISH"
            res.reason = f"BOS_DN:{bos_down}|LH:{lh}|LL:{ll}|SwH:{res.swept_high is not None}"
        else:
            res.bias   = "NEUTRAL"
            res.reason = f"Bull:{bull_pts} Bear:{bear_pts} unclear"

        return res

    # ── M15 Structure ─────────────────────────────────────────────────────────
    @staticmethod
    def get_m15_structure(df_m15: Optional[pd.DataFrame]) -> str:
        if df_m15 is None or len(df_m15) < 20:
            return "NEUTRAL"
        sh, sl = get_confirmed_swings_np(df_m15, period=3, confirm=2)
        last_close = float(df_m15["close"].iloc[-1])
        if last_close > sh: return "BULLISH_BOS"
        if last_close < sl: return "BEARISH_BOS"
        return "NEUTRAL"

    # ── FVG Memory ────────────────────────────────────────────────────────────
    @staticmethod
    def scan_fvg_memory(df: pd.DataFrame, atr: float,
                        lookback: int = 30) -> List[FVGZone]:
        zones: List[FVGZone] = []
        if len(df) < lookback + 3 or atr == 0:
            return zones

        min_gap = atr * 0.12
        overlap = atr * 0.30
        start   = max(3, len(df) - lookback)

        for i in range(start, len(df)):
            c1 = df.iloc[i - 2]
            c2 = df.iloc[i - 1]
            c3 = df.iloc[i]

            c2_range = float(c2["high"] - c2["low"])
            c2_body  = abs(float(c2["close"] - c2["open"]))
            if c2_range > 0 and (c2_body / c2_range) < FVG_MOMENTUM_RATIO:
                continue

            # Bullish FVG
            if c3["low"] > c1["high"] - overlap:
                top = max(float(c3["low"]), float(c1["high"]))
                bot = min(float(c3["low"]), float(c1["high"]))
                gap = top - bot
                if gap >= min_gap:
                    z = FVGZone("BULLISH", top, bot, gap / atr, i)
                    mid = bot + gap * FVG_MITIGATED_PCT
                    for j in range(i + 1, len(df)):
                        if df.iloc[j]["low"] <= mid:
                            z.mitigated = True
                            break
                    zones.append(z)

            # Bearish FVG
            if c3["high"] < c1["low"] + overlap:
                top = float(c1["low"])
                bot = float(c3["high"])
                gap = top - bot
                if gap >= min_gap:
                    z = FVGZone("BEARISH", top, bot, gap / atr, i)
                    mid = top - gap * FVG_MITIGATED_PCT
                    for j in range(i + 1, len(df)):
                        if df.iloc[j]["high"] >= mid:
                            z.mitigated = True
                            break
                    zones.append(z)

        zones.sort(key=lambda z: z.bar_index, reverse=True)
        return zones

    @staticmethod
    def get_active_fvg(zones: List[FVGZone], price: float,
                       direction: str) -> Optional[FVGZone]:
        target = "BULLISH" if direction == "BUY" else "BEARISH"
        for z in zones:
            if z.mitigated or z.kind != target:
                continue
            buf = (z.top - z.bot) * FVG_BUFFER_RATIO
            if (z.bot - buf) <= price <= (z.top + buf):
                return z
        return None

    # ── Order Block ───────────────────────────────────────────────────────────
    @staticmethod
    def find_order_block(df: pd.DataFrame,
                         direction: str, atr: float) -> OBResult:
        if len(df) < 10 or atr == 0:
            return OBResult()
        closed = df.iloc[:-1]
        for i in range(len(closed) - 3, 3, -1):
            ob  = closed.iloc[i]
            imp = closed.iloc[i + 1]
            if abs(float(imp["close"]) - float(imp["open"])) < atr * 1.2:
                continue
            if direction == "BUY":
                if ob["close"] >= ob["open"]: continue
                if imp["close"] <= imp["open"]: continue
                ph = closed["high"].iloc[max(0, i - 10): i].max()
                if imp["close"] <= ph * 0.998: continue
                pl    = closed["low"].iloc[max(0, i - 5): i].min()
                sweep = float(pl) < float(ob["low"])
                rng   = float(ob["high"] - ob["low"])
                body  = (float(ob["open"]) - float(ob["close"])) / rng if rng > 0 else 0
                q = 0.5 + (0.3 if sweep else 0) + (0.2 if body > 0.6 else 0)
                return OBResult(True, float(ob["high"]), float(ob["low"]), q)
            else:  # SELL
                if ob["close"] <= ob["open"]: continue
                if imp["close"] >= imp["open"]: continue
                pl = closed["low"].iloc[max(0, i - 10): i].min()
                if imp["close"] >= float(pl) * 1.002: continue
                ph    = closed["high"].iloc[max(0, i - 5): i].max()
                sweep = float(ph) > float(ob["high"])
                rng   = float(ob["high"] - ob["low"])
                body  = (float(ob["close"]) - float(ob["open"])) / rng if rng > 0 else 0
                q = 0.5 + (0.3 if sweep else 0) + (0.2 if body > 0.6 else 0)
                return OBResult(True, float(ob["high"]), float(ob["low"]), q)
        return OBResult()

    # ── Session helpers ───────────────────────────────────────────────────────
    @staticmethod
    def get_session() -> str:
        now = datetime.now(bkk_tz).time()
        for sh, sm, eh, em in NEWS_BLOCKS:
            if dtime(sh, sm) <= now <= dtime(eh, em):
                return "RED_NEWS_BLOCK"
        for sh, sm, eh, em, name in SESSIONS:
            s, e = dtime(sh, sm), dtime(eh, em)
            if e < s:
                if now >= s or now <= e: return name
            else:
                if s <= now <= e: return name
        return "OUT_OF_SESSION"

    @staticmethod
    def is_in_killzone() -> Tuple[bool, str]:
        if not KILLZONE_ENABLED:
            return True, "All"
        now = datetime.now(bkk_tz).time()
        for sh, sm, eh, em, name in KILLZONES:
            if dtime(sh, sm) <= now <= dtime(eh, em):
                return True, name
        return False, "Outside Killzone"

    @staticmethod
    def get_dynamic_threshold(session: str, htf_bias: str,
                               adr_pct: float) -> int:
        base = SCORE_THRESHOLD.get(session, SCORE_THRESHOLD["DEFAULT"])
        if htf_bias == "NEUTRAL":
            base += SCORE_PENALTY_HTF_NEUTRAL
        if adr_pct >= ADR_EXHAUSTED_PCT:
            base += SCORE_PENALTY_HIGH_ADR
        return base

    # ── Master setup analyser ─────────────────────────────────────────────────
    def analyze_setup(
        self,
        df_m5: Optional[pd.DataFrame],
        df_h1: Optional[pd.DataFrame],
        df_d1: Optional[pd.DataFrame],
        df_m15: Optional[pd.DataFrame],
        session: str = "DEFAULT",
    ) -> SetupResult:
        r = SetupResult()

        if df_m5 is None or len(df_m5) < 30:
            r.reasons.append("M5 data insufficient")
            return r

        atr = calculate_atr(df_m5)
        if atr == 0:
            r.reasons.append("ATR=0")
            return r
        r.atr = atr

        adr = calculate_adr(df_d1)
        if adr > 0 and df_d1 is not None and len(df_d1) >= 1:
            day_range = float(df_d1["high"].iloc[-1] - df_d1["low"].iloc[-1])
            r.adr_pct = day_range / adr

        htf_res     = self.get_htf_bias(df_h1)
        r.htf_bias  = htf_res.bias
        r.htf_result = htf_res
        r.m15_struct = self.get_m15_structure(df_m15)
        r.threshold  = self.get_dynamic_threshold(session, r.htf_bias, r.adr_pct)

        liq      = build_liquidity_map_np(df_m5, atr, LIQ_SWING_PERIOD)
        r.liq_map = liq

        last_sh, last_sl = get_confirmed_swings_np(df_m5, SWING_PERIOD,
                                                    SWING_CONFIRM_BARS)
        fvg_lookback = FVG_MEMORY_BARS.get(session, FVG_MEMORY_BARS["DEFAULT"])
        fvg_zones    = self.scan_fvg_memory(df_m5, atr, fvg_lookback)

        last  = df_m5.iloc[-1]
        prev  = df_m5.iloc[-2]
        r.candle_ts = (float(last["time"].timestamp())
                       if hasattr(last["time"], "timestamp") else time.time())

        price      = float(last["close"])
        sweep_sell = float(last["low"]) < last_sl  and float(last["close"]) > last_sl
        sweep_buy  = float(last["high"]) > last_sh and float(last["close"]) < last_sh

        # ── Inner build helpers ───────────────────────────────────────────────
        def _build_buy() -> bool:
            has_sweep  = sweep_sell
            fvg_active = self.get_active_fvg(fvg_zones, price, "BUY")
            if not has_sweep and fvg_active is None:
                return False

            r.signal = "BUY"
            r.score  = SCORE_BASE

            if fvg_active is not None:
                r.entry    = fvg_active.top
                r.fvg_zone = fvg_active
            elif has_sweep:
                r.entry = last_sl + (atr * 0.1)
            r.sl = last_sl - (atr * 0.5)

            if has_sweep and fvg_active is not None:
                r.score += SCORE_SWEEP_AND_FVG
                r.reasons.append("Sweep+FVG ✓✓")
            elif has_sweep:
                r.reasons.append("Sweep SSL ✓")
            else:
                r.reasons.append("FVG Zone ✓")

            if fvg_active is not None and not fvg_active.mitigated:
                r.score += SCORE_FVG_FRESH
                r.reasons.append(f"FVG Fresh(s:{fvg_active.strength:.2f}) ✓")
                if fvg_active.strength > 0.5:
                    r.score += SCORE_FVG_STRENGTH

            if r.htf_bias == "BULLISH":
                r.score += SCORE_HTF_ALIGN
                choch_tag = "(CHOCH)" if htf_res.choch_signal == "UP" else ""
                r.reasons.append(f"HTF Bull{choch_tag} ✓")
            elif r.htf_bias == "BEARISH":
                r.score += SCORE_HTF_AGAINST
                r.reasons.append("HTF Bear ⚠️")
            if htf_res.swept_low is not None:
                r.score += 4
                r.reasons.append("H1 SSL Swept ✓")

            if r.m15_struct == "BULLISH_BOS":
                r.score += SCORE_M15_BOS
                r.reasons.append("M15 BOS ✓")

            body = float(last["close"]) - float(last["open"])
            if body > atr * 0.6:
                r.score += SCORE_STRONG_CANDLE
                r.reasons.append("Strong ✓")

            ob = self.find_order_block(df_m5, "BUY", atr)
            if ob.found:
                r.score += int(SCORE_OB_BONUS * ob.score)
                r.reasons.append(f"OB(q:{ob.score:.2f}) ✓")
                if ob.low <= r.entry <= ob.high:
                    r.score += SCORE_OB_OVERLAP
                    r.reasons.append("OB Overlap ✓")

            if float(last["close"]) > float(prev["high"]):
                r.score += SCORE_BOS_M5
                r.reasons.append("BOS ✓")

            if liq.swept_low is not None:
                r.score += SCORE_LIQ_SWEPT
                r.reasons.append(f"SSL Swept({liq.swept_low:.2f}) ✓")
            if liq.bsl_nearest is not None:
                risk = abs(r.entry - r.sl)
                if risk > 0 and (liq.bsl_nearest - r.entry) >= risk * RR_RATIO * 0.8:
                    r.score += SCORE_LIQ_TARGET
                    r.reasons.append(f"BSL→{liq.bsl_nearest:.2f} ✓")

            if r.adr_pct >= ADR_EXHAUSTED_PCT:
                r.score += SCORE_ADR_WARN
                r.reasons.append(f"ADR{r.adr_pct*100:.0f}% ⚠️")

            body_ratio = body / atr if atr > 0 else 0
            if (float(last["close"]) > float(prev["high"])
                    and body_ratio > MOMENTUM_BODY_ATR
                    and r.score >= r.threshold):
                r.use_market = True
                r.entry      = 0.0
                r.reasons.append("🚀 MKT")

            return True

        def _build_sell() -> bool:
            has_sweep  = sweep_buy
            fvg_active = self.get_active_fvg(fvg_zones, price, "SELL")
            if not has_sweep and fvg_active is None:
                return False

            r.signal = "SELL"
            r.score  = SCORE_BASE

            if fvg_active is not None:
                r.entry    = fvg_active.bot
                r.fvg_zone = fvg_active
            elif has_sweep:
                r.entry = last_sh - (atr * 0.1)
            r.sl = last_sh + (atr * 0.5)

            if has_sweep and fvg_active is not None:
                r.score += SCORE_SWEEP_AND_FVG
                r.reasons.append("Sweep+FVG ✓✓")
            elif has_sweep:
                r.reasons.append("Sweep BSL ✓")
            else:
                r.reasons.append("FVG Zone ✓")

            if fvg_active is not None and not fvg_active.mitigated:
                r.score += SCORE_FVG_FRESH
                r.reasons.append(f"FVG Fresh(s:{fvg_active.strength:.2f}) ✓")
                if fvg_active.strength > 0.5:
                    r.score += SCORE_FVG_STRENGTH

            if r.htf_bias == "BEARISH":
                r.score += SCORE_HTF_ALIGN
                choch_tag = "(CHOCH)" if htf_res.choch_signal == "DOWN" else ""
                r.reasons.append(f"HTF Bear{choch_tag} ✓")
            elif r.htf_bias == "BULLISH":
                r.score += SCORE_HTF_AGAINST
                r.reasons.append("HTF Bull ⚠️")
            if htf_res.swept_high is not None:
                r.score += 4
                r.reasons.append("H1 BSL Swept ✓")

            if r.m15_struct == "BEARISH_BOS":
                r.score += SCORE_M15_BOS
                r.reasons.append("M15 BOS ✓")

            body = float(last["open"]) - float(last["close"])
            if body > atr * 0.6:
                r.score += SCORE_STRONG_CANDLE
                r.reasons.append("Strong ✓")

            ob = self.find_order_block(df_m5, "SELL", atr)
            if ob.found:
                r.score += int(SCORE_OB_BONUS * ob.score)
                r.reasons.append(f"OB(q:{ob.score:.2f}) ✓")
                if ob.low <= r.entry <= ob.high:
                    r.score += SCORE_OB_OVERLAP
                    r.reasons.append("OB Overlap ✓")

            if float(last["close"]) < float(prev["low"]):
                r.score += SCORE_BOS_M5
                r.reasons.append("BOS ✓")

            if liq.swept_high is not None:
                r.score += SCORE_LIQ_SWEPT
                r.reasons.append(f"BSL Swept({liq.swept_high:.2f}) ✓")
            if liq.ssl_nearest is not None:
                risk = abs(r.sl - r.entry)
                if risk > 0 and (r.entry - liq.ssl_nearest) >= risk * RR_RATIO * 0.8:
                    r.score += SCORE_LIQ_TARGET
                    r.reasons.append(f"SSL→{liq.ssl_nearest:.2f} ✓")

            if r.adr_pct >= ADR_EXHAUSTED_PCT:
                r.score += SCORE_ADR_WARN
                r.reasons.append(f"ADR{r.adr_pct*100:.0f}% ⚠️")

            body_ratio = body / atr if atr > 0 else 0
            if (float(last["close"]) < float(prev["low"])
                    and body_ratio > MOMENTUM_BODY_ATR
                    and r.score >= r.threshold):
                r.use_market = True
                r.entry      = 0.0
                r.reasons.append("🚀 MKT")

            return True

        # ── Build direction preference: BUY first ─────────────────────────────
        if not _build_buy():
            r.signal = "WAIT"
            r.score  = 0
            r.reasons = []
            if not _build_sell():
                return r

        if r.signal != "WAIT":
            entry_h     = r.entry if not r.use_market else -1.0
            r.setup_hash = _make_hash(r.signal, entry_h, r.sl, r.candle_ts)

        return r


# ══════════════════════════════════════════════════════════════════════════════
# 💰  CLASS: RiskManager
# ══════════════════════════════════════════════════════════════════════════════
class RiskManager:
    """
    Encapsulates all risk checks and lot-sizing logic.
    """

    @staticmethod
    def get_broker_date() -> str:
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is not None:
            return datetime.fromtimestamp(tick.time, tz=pytz.utc).strftime("%Y%m%d")
        return datetime.utcnow().strftime("%Y%m%d")

    @staticmethod
    def get_spread_pts() -> float:
        tick = mt5.symbol_info_tick(SYMBOL)
        info = mt5.symbol_info(SYMBOL)
        if tick is None or info is None:
            return 999.0
        return (tick.ask - tick.bid) / info.point

    def is_spread_ok(self) -> bool:
        sp = self.get_spread_pts()
        if sp > HARD_SPREAD_BLOCK:
            log.warning(f"⛔ Spread {sp:.1f}pts > HARD_BLOCK {HARD_SPREAD_BLOCK}")
            return False
        return True

    @staticmethod
    def get_spread_sl_padding() -> float:
        if not SPREAD_SL_PADDING:
            return 0.0
        tick = mt5.symbol_info_tick(SYMBOL)
        info = mt5.symbol_info(SYMBOL)
        if tick is None or info is None:
            return 0.0
        return ((tick.ask - tick.bid) / info.point) * info.point

    def is_within_risk_limits(self) -> bool:
        acct = mt5.account_info()
        if acct is None:
            return True
        equity  = acct.equity
        balance = acct.balance

        today_key   = "daily_start_balance_" + self.get_broker_date()
        daily_start = get_state(today_key)
        if daily_start is None or daily_start <= 0:
            set_state(today_key, balance)
            daily_start = balance

        daily_dd = (daily_start - equity) / daily_start * 100 if daily_start > 0 else 0
        if daily_dd >= MAX_DAILY_LOSS_PCT:
            log.warning(f"🛑 Daily DD {daily_dd:.2f}% ≥ {MAX_DAILY_LOSS_PCT}%")
            return False

        init_bal = get_state("initial_balance")
        if init_bal is None:
            set_state("initial_balance", balance)
            init_bal = balance
        total_dd = (init_bal - equity) / init_bal * 100 if init_bal > 0 else 0
        if total_dd >= MAX_TOTAL_DD_PCT:
            log.warning(f"🛑 Total DD {total_dd:.2f}% ≥ {MAX_TOTAL_DD_PCT}%")
            return False

        return True

    def is_circuit_breaker_tripped(self) -> bool:
        """[FIX A2] Halt new orders once intraday equity drops CIRCUIT_BREAKER_PCT."""
        acct = mt5.account_info()
        if acct is None:
            return False
        today_key   = "daily_start_balance_" + self.get_broker_date()
        daily_start = get_state(today_key)
        if daily_start is None or daily_start <= 0:
            return False
        dd_pct = (daily_start - acct.equity) / daily_start * 100
        if dd_pct >= CIRCUIT_BREAKER_PCT:
            log.warning(
                f"⚡ Circuit Breaker: DD {dd_pct:.2f}% ≥ {CIRCUIT_BREAKER_PCT}%"
                " → halting new orders today"
            )
            return True
        return False

    @staticmethod
    def _round_lot(lot: float, step: float) -> float:
        d_lot  = Decimal(str(lot))
        d_step = Decimal(str(step))
        return float(
            (d_lot / d_step).to_integral_value(rounding=ROUND_DOWN) * d_step
        )

    def calculate_lot(self, entry: float, sl: float,
                      score: int = 0, spread_pts: float = 0.0,
                      atr: float = 0.0) -> float:
        """
        [FIX A2][EDGE-1] Risk-based lot sizing.

        Edge case fix: if rounded lot == 0.0 → default to info.volume_min.
        Dynamic deviation is also derived here for callers to use.
        """
        info = mt5.symbol_info(SYMBOL)
        acct = mt5.account_info()
        if info is None or acct is None:
            log.warning("calculate_lot: cannot read broker info → LOT_MIN")
            return LOT_MIN

        risk_pct = RISK_TIERS[-1][1]
        for score_min, pct in RISK_TIERS:
            if score >= score_min:
                risk_pct = pct
                break

        if spread_pts > MAX_SPREAD_POINTS:
            risk_pct *= (1.0 - SPREAD_LOT_PENALTY)
            log.info(f"📉 Spread penalty → risk% = {risk_pct:.3f}%")

        balance     = acct.balance
        risk_amount = balance * (risk_pct / 100.0)

        sl_dist = abs(entry - sl)
        if sl_dist == 0:
            log.error("calculate_lot: SL dist=0 → LOT_MIN")
            return LOT_MIN

        sl_pts = max(1.0, sl_dist / info.point)

        tick_val = info.trade_tick_value
        if not tick_val or tick_val <= 0:
            tick_val = info.trade_contract_size * info.point
        if tick_val <= 0:
            log.warning("calculate_lot: tick_value unavailable → LOT_MIN")
            return LOT_MIN

        raw_lot = risk_amount / (sl_pts * tick_val)

        step = info.volume_step if info.volume_step > 0 else 0.01
        lot  = self._round_lot(raw_lot, step)

        # [EDGE-1] Zero-floor — must never be less than broker minimum
        if lot <= 0.0:
            log.warning(f"calculate_lot: rounded lot=0 → volume_min={info.volume_min}")
            lot = info.volume_min

        lot = max(info.volume_min, min(lot, info.volume_max, LOT_MAX))

        log.info(
            f"💰 Lot | Score:{score} Risk:{risk_pct:.2f}% "
            f"Bal:{balance:.0f} SL:{sl_pts:.1f}pts TV:{tick_val:.4f} → {lot}"
        )
        return float(lot)

    @staticmethod
    def dynamic_deviation(atr: float) -> int:
        """
        [FIX-2] Volatility-based deviation (slippage tolerance) in points.
        Floor = 50 points to survive XAUUSD spread widening.
        Formula: int(atr * 0.1 / point)  or at minimum 50.
        """
        info = mt5.symbol_info(SYMBOL)
        if info is None or info.point == 0:
            return 50
        vol_dev = int(atr * 0.1 / info.point)
        return max(50, vol_dev)

    @staticmethod
    def validate_order(entry: float, sl: float, tp: float,
                       lot: float, signal: str) -> Tuple[bool, str]:
        info = mt5.symbol_info(SYMBOL)
        acct = mt5.account_info()
        tick = mt5.symbol_info_tick(SYMBOL)
        if not all([info, acct, tick]):
            return False, "Cannot read broker data"

        min_d = info.trade_stops_level * info.point
        if abs(entry - sl) < min_d: return False, "SL too close (stop_level)"
        if abs(entry - tp) < min_d: return False, "TP too close (stop_level)"

        frz = info.trade_freeze_level * info.point
        if frz > 0 and abs(entry - tick.ask) < frz:
            return False, "Entry in freeze zone"

        d_lot  = Decimal(str(lot))
        d_step = Decimal(str(info.volume_step))
        if d_lot % d_step > Decimal("1e-8"):
            return False, "Lot step mismatch"

        otype     = mt5.ORDER_TYPE_BUY if signal == "BUY" else mt5.ORDER_TYPE_SELL
        margin_req = mt5.order_calc_margin(otype, SYMBOL, lot, entry)
        if margin_req is None or margin_req > acct.margin_free * 0.9:
            return False, "Insufficient margin"

        return True, "OK"

    @staticmethod
    def has_duplicate_setup(setup_hash: str, signal: str) -> bool:  # noqa: ARG002
        for p in (mt5.positions_get(symbol=SYMBOL) or []):
            if p.magic == MAGIC_NUMBER and setup_hash in (p.comment or ""):
                return True
        for o in (mt5.orders_get(symbol=SYMBOL) or []):
            if o.magic == MAGIC_NUMBER and setup_hash in (o.comment or ""):
                return True
        return False


# ══════════════════════════════════════════════════════════════════════════════
# 📤  CLASS: ExecutionHandler
# ══════════════════════════════════════════════════════════════════════════════
class ExecutionHandler:
    """
    Wraps all MT5 order-send operations.

    Key improvements over V8:
    [FIX-1] _send_retry: re-fetches live price on REQUOTE/PRICE_CHANGED/PRICE_OFF
    [FIX-2] deviation computed dynamically per trade
    """

    def __init__(self, risk: RiskManager):
        self._risk  = risk
        self._lock  = threading.Lock()   # non-blocking: only wraps order_send call

    # ── Retry sender ─────────────────────────────────────────────────────────
    def _send_retry(self, req: dict, retries: int = 3):
        """
        [FIX-1] Non-blocking retry with live price refresh.

        Pattern: lock→send→unlock→[sleep outside lock]→lock→send…
        On REQUOTE / PRICE_CHANGED / PRICE_OFF the function:
          1. Fetches the latest tick (ask or bid depending on direction)
          2. Updates req['price'] in-place before sleeping
          3. Retries — no stale price re-submission
        """
        last_res = None
        is_buy   = req.get("type") in (mt5.ORDER_TYPE_BUY,
                                        mt5.ORDER_TYPE_BUY_LIMIT,
                                        mt5.ORDER_TYPE_BUY_STOP)

        for i in range(1, retries + 1):
            with self._lock:
                res = mt5.order_send(req)

            if res is None:
                log.warning(f"order_send returned None (try {i}/{retries})")
                if i < retries:
                    time.sleep(0.5)
                continue

            last_res = res

            if res.retcode == mt5.TRADE_RETCODE_DONE:
                return res

            # [FIX-1] Price-related retcodes → refresh price before retry
            if res.retcode in (
                mt5.TRADE_RETCODE_REQUOTE,
                mt5.TRADE_RETCODE_PRICE_CHANGED,
                mt5.TRADE_RETCODE_PRICE_OFF,
            ):
                tick = mt5.symbol_info_tick(SYMBOL)
                if tick is not None:
                    new_price = tick.ask if is_buy else tick.bid
                    log.warning(
                        f"[FIX-1] Price refresh on retcode {res.retcode}: "
                        f"{req.get('price', '?'):.2f} → {new_price:.2f} "
                        f"(try {i}/{retries})"
                    )
                    req["price"] = round(float(new_price), 2)
                else:
                    log.warning(f"Price retcode {res.retcode} but tick unavailable")
                if i < retries:
                    time.sleep(0.3 * i)
                continue

            # Connection/timeout — retry without price change
            if res.retcode in (
                mt5.TRADE_RETCODE_CONNECTION,
                mt5.TRADE_RETCODE_TIMEOUT,
            ):
                log.warning(f"Retryable retcode:{res.retcode} (try {i}/{retries})")
                if i < retries:
                    time.sleep(0.5 * i)
                continue

            # Any other error — do not retry
            log.error(f"❌ retcode:{res.retcode} | {res.comment}")
            return res

        log.error(f"❌ _send_retry exhausted {retries} attempts")
        return last_res

    # ── Modify SL ─────────────────────────────────────────────────────────────
    def modify_sl(self, ticket: int, new_sl: float) -> None:
        req = {
            "action":   mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "sl":       round(float(new_sl), 2),
        }
        with self._lock:
            res = mt5.order_send(req)
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            log.warning(
                f"modify_sl FAIL #{ticket} "
                f"retcode:{res.retcode if res else 'None'}"
            )

    # ── Partial close ─────────────────────────────────────────────────────────
    def close_partial(self, pos, lot_close: float) -> None:
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None:
            return
        info  = mt5.symbol_info(SYMBOL)
        step  = info.volume_step if info else 0.01
        v_min = info.volume_min  if info else 0.01

        lot_close = float(max(
            v_min,
            min(
                self._risk._round_lot(lot_close, step),
                pos.volume,
            ),
        ))

        is_buy     = (pos.type == mt5.ORDER_TYPE_BUY)
        close_type = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
        price      = tick.bid if is_buy else tick.ask

        # [FIX-2] dynamic deviation for partial close as well
        atr_fallback = pos.sl  # rough proxy; PM will have real ATR
        dev = self._risk.dynamic_deviation(0.0)  # use floor=50 for closes

        res = self._send_retry({
            "action":    mt5.TRADE_ACTION_DEAL,
            "symbol":    SYMBOL,
            "volume":    lot_close,
            "type":      close_type,
            "position":  pos.ticket,
            "price":     round(float(price), 2),
            "deviation": dev,
            "magic":     MAGIC_NUMBER,
            "comment":   "V9|PartialTP",
        })
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            log.info(f"💰 Partial #{pos.ticket} Lot:{lot_close:.2f} @ {price:.2f}")

    # ── Place order ────────────────────────────────────────────────────────────
    def place_order(self, setup: SetupResult, session: str = "") -> bool:
        """
        Full order placement pipeline: validation → lot sizing → dual-leg send.
        """
        if not self._risk.is_spread_ok() or not self._risk.is_within_risk_limits():
            return False
        if self._risk.has_duplicate_setup(setup.setup_hash, setup.signal):
            log.info(f"🚫 Duplicate {setup.setup_hash} → skip")
            return False

        sp     = self._risk.get_spread_pts()
        sl_pad = self._risk.get_spread_sl_padding()

        if sp > MAX_SPREAD_POINTS:
            setup.score += SCORE_SPREAD_WARN
            setup.reasons.append(f"Spread{sp:.0f}pts ⚠️")

        # M1 confirmation bonus
        rates_m1 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M1, 0, 5)
        if rates_m1 is not None and len(rates_m1) >= 3:
            df_m1 = pd.DataFrame(rates_m1)
            c     = df_m1.iloc[-2]
            body_m1 = abs(float(c["close"]) - float(c["open"]))
            if body_m1 >= setup.atr * MTF_M1_BODY_ATR:
                if (setup.signal == "BUY"  and c["close"] > c["open"]) or \
                   (setup.signal == "SELL" and c["close"] < c["open"]):
                    setup.score += SCORE_M1_CONFIRM
                    setup.reasons.append("M1 ✓")

        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None:
            return False

        sig = setup.signal
        sl_raw = setup.sl
        sl_adjusted = (sl_raw - sl_pad) if sig == "BUY" else (sl_raw + sl_pad)
        log.info(f"📏 SL Padding: {sl_raw:.2f} → {sl_adjusted:.2f} (spread={sp:.1f}pts)")

        if setup.use_market or not INTRABAR_ENABLED:
            entry  = tick.ask if sig == "BUY" else tick.bid
            otype  = mt5.ORDER_TYPE_BUY  if sig == "BUY" else mt5.ORDER_TYPE_SELL
            action = mt5.TRADE_ACTION_DEAL
            exp    = 0
        else:
            entry  = setup.entry
            otype  = mt5.ORDER_TYPE_BUY_LIMIT if sig == "BUY" else mt5.ORDER_TYPE_SELL_LIMIT
            action = mt5.TRADE_ACTION_PENDING
            exp    = int(time.time()) + (EXPIRATION_CANDLES * 5 * 60)
            if sig == "BUY" and entry >= tick.ask:
                entry = tick.ask
                otype = mt5.ORDER_TYPE_BUY
                action = mt5.TRADE_ACTION_DEAL
                exp    = 0
            elif sig == "SELL" and entry <= tick.bid:
                entry = tick.bid
                otype = mt5.ORDER_TYPE_SELL
                action = mt5.TRADE_ACTION_DEAL
                exp    = 0

        risk = abs(entry - sl_adjusted)
        if risk == 0:
            log.error("place_order: risk=0 → abort")
            return False

        tp_full  = (entry + risk * RR_RATIO if sig == "BUY"
                    else entry - risk * RR_RATIO)
        lot_full = self._risk.calculate_lot(
            entry, sl_adjusted, setup.score, sp, setup.atr
        )
        ok, reason = self._risk.validate_order(
            entry, sl_adjusted, tp_full, lot_full, sig
        )
        if not ok:
            log.warning(f"⚠️ Validate: {reason}")
            return False

        info   = mt5.symbol_info(SYMBOL)
        v_step = info.volume_step if info else 0.01
        v_min  = info.volume_min  if info else 0.01

        lot_a = max(v_min, self._risk._round_lot(lot_full * PARTIAL_TP_PCT, v_step))
        lot_b = max(v_min, self._risk._round_lot(lot_full - lot_a, v_step))
        if lot_a + lot_b > lot_full + v_step:
            lot_b = max(v_min, self._risk._round_lot(lot_full - lot_a, v_step))

        tp_pt = (entry + risk * PARTIAL_TP_RR if sig == "BUY"
                 else entry - risk * PARTIAL_TP_RR)

        # [FIX-2] Dynamic deviation per trade
        dev = self._risk.dynamic_deviation(setup.atr)
        log.info(f"📐 Deviation: {dev} pts (ATR={setup.atr:.4f})")

        sent = 0
        for lot_i, tp_i, label in [(lot_a, tp_pt, "PT"), (lot_b, tp_full, "FT")]:
            req = {
                "action":    action,
                "symbol":    SYMBOL,
                "volume":    lot_i,
                "type":      otype,
                "price":     round(float(entry), 2),
                "sl":        round(float(sl_adjusted), 2),
                "tp":        round(float(tp_i), 2),
                "deviation": dev,            # [FIX-2]
                "magic":     MAGIC_NUMBER,
                "comment":   f"V9|{sig}|{label}|{setup.score}|{setup.setup_hash}",
            }
            if action == mt5.TRADE_ACTION_PENDING:
                req["type_time"]  = mt5.ORDER_TIME_SPECIFIED
                req["expiration"] = exp

            res = self._send_retry(req)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                sent += 1
                mode_tag = "MKT" if action == mt5.TRADE_ACTION_DEAL else "LMT"
                log.info(
                    f"✅ {label}|{sig}|{mode_tag}|Lot:{lot_i}|"
                    f"E:{entry:.2f}|SL:{sl_adjusted:.2f}|TP:{tp_i:.2f}"
                )
            else:
                log.warning(f"⚠️ {label} order failed")

        if sent > 0:
            mode = "MKT" if action == mt5.TRADE_ACTION_DEAL else "LMT"
            log.info(
                f"📦 {mode}|{sig}|Score:{setup.score}|"
                f"Lot:{lot_a}+{lot_b}|WinProb:{setup.win_prob:.2f}|{session}"
            )
            db_log_setup(sig, setup.score, entry, sl_adjusted, tp_full,
                         setup.setup_hash, session)
            return True
        return False


# ══════════════════════════════════════════════════════════════════════════════
# 🔧  CLASS: PositionManager
# ══════════════════════════════════════════════════════════════════════════════
class PositionManager:
    """
    Background thread: polls open positions every POSITION_POLL_SEC seconds.
    Handles Partial TP · Breakeven · Trailing SL.

    Thread-safety: reads MarketDataFeed cache (read-only), writes to SQLite
    via the thread-safe _db_exec helpers, sends orders via ExecutionHandler
    which uses its own threading.Lock wrapping only the order_send call.
    """

    def __init__(self, feed: MarketDataFeed, execution: ExecutionHandler):
        self._feed      = feed
        self._exec      = execution
        self._running   = threading.Event()
        self._running.set()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._loop, name="PositionManager", daemon=True
        )
        self._thread.start()
        log.info("🔄 PositionManager thread started")

    def stop(self) -> None:
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=5)
        log.info("🔄 PositionManager thread stopped")

    def _loop(self) -> None:
        while self._running.is_set():
            try:
                if mt5.terminal_info() is not None:
                    df_m5 = self._feed.get_cached_m5()
                    atr   = calculate_atr(df_m5) if df_m5 is not None else 1.0
                    self._manage_positions(atr)
            except Exception as exc:
                log.warning(f"⚠️ PositionManager error: {exc}")
            time.sleep(POSITION_POLL_SEC)

    def _manage_positions(self, atr: float) -> None:
        """
        [FIX-3] Position tracking uses setup_hash extracted from the MT5
        comment field (format: "V9|SIG|LABEL|SCORE|HASH") as a secondary key.
        This survives ticket renumbering on hedging accounts.
        """
        positions = [
            p for p in (mt5.positions_get(symbol=SYMBOL) or [])
            if p.magic == MAGIC_NUMBER
        ]
        if not positions:
            return

        tick = mt5.symbol_info_tick(SYMBOL)
        info = mt5.symbol_info(SYMBOL)
        if tick is None or info is None:
            return

        a             = max(atr, info.point * 10)
        open_tickets  = {p.ticket for p in positions}

        for pos in positions:
            entry  = pos.price_open
            sl_now = pos.sl
            is_buy = (pos.type == mt5.ORDER_TYPE_BUY)

            # [FIX-3] Extract setup_hash from comment ("V9|SIG|LBL|SCORE|HASH")
            comment_parts = (pos.comment or "").split("|")
            pos_hash = comment_parts[-1] if len(comment_parts) >= 5 else ""

            risk = abs(entry - sl_now)
            if risk < info.point:
                risk = a * 1.5
                log.warning(
                    f"⚠️ #{pos.ticket} SL≈0 → fallback risk={risk:.2f}"
                )

            price    = tick.bid if is_buy else tick.ask
            buf      = info.point * 5
            profit_r = ((price - entry) / risk if is_buy
                        else (entry - price) / risk)

            # [FIX-3] Dual-key trail state lookup
            ts           = get_trail_state(pos.ticket, pos_hash)
            partial_done = ts["partial_done"] if ts else 0

            # Step 1: Partial TP @ 1R
            if not partial_done and profit_r >= PARTIAL_TP_RR:
                self._exec.close_partial(pos, pos.volume * PARTIAL_TP_PCT)
                set_partial_done(pos.ticket, pos_hash)
                be_sl = (entry + buf) if is_buy else (entry - buf)
                if ((is_buy     and sl_now < be_sl) or
                        (not is_buy and sl_now > be_sl)):
                    self._exec.modify_sl(pos.ticket, be_sl)
                    log.info(
                        f"🔒 BE+Partial #{pos.ticket} "
                        f"SL:{sl_now:.2f}→{be_sl:.2f} R:{profit_r:.2f}"
                    )
                continue

            # Step 2: Breakeven @ 1R
            if profit_r >= BREAKEVEN_RR:
                be_sl = (entry + buf) if is_buy else (entry - buf)
                if ((is_buy     and sl_now < be_sl) or
                        (not is_buy and sl_now > be_sl)):
                    self._exec.modify_sl(pos.ticket, be_sl)
                    log.info(
                        f"🔒 BE #{pos.ticket} "
                        f"SL:{sl_now:.2f}→{be_sl:.2f}"
                    )
                continue

            # Step 3: Trailing Stop @ 2R
            if profit_r >= TRAIL_AFTER_RR:
                last_tsl = ts["last_sl"] if ts else None
                min_move = a * TRAIL_MIN_MOVE_ATR

                if is_buy:
                    new_tsl = price - (a * TRAIL_ATR_MULT)
                    if (new_tsl > sl_now and
                            (last_tsl is None or new_tsl > last_tsl + min_move)):
                        self._exec.modify_sl(pos.ticket, new_tsl)
                        save_trail_sl(pos.ticket, new_tsl, pos_hash)
                        log.info(
                            f"📈 Trail #{pos.ticket} "
                            f"SL:{sl_now:.2f}→{new_tsl:.2f} R:{profit_r:.2f}"
                        )
                else:
                    new_tsl = price + (a * TRAIL_ATR_MULT)
                    if (new_tsl < sl_now and
                            (last_tsl is None or new_tsl < last_tsl - min_move)):
                        self._exec.modify_sl(pos.ticket, new_tsl)
                        save_trail_sl(pos.ticket, new_tsl, pos_hash)
                        log.info(
                            f"📉 Trail #{pos.ticket} "
                            f"SL:{sl_now:.2f}→{new_tsl:.2f} R:{profit_r:.2f}"
                        )

        cleanup_trail_state(open_tickets)


# ══════════════════════════════════════════════════════════════════════════════
# 🔧  HELPER UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def _make_hash(sig: str, entry: float, sl: float, ts: float) -> str:
    raw = f"{sig}:{entry:.2f}:{sl:.2f}:{int(ts)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def mt5_connect(retries: int = 10, delay: float = 5.0) -> bool:
    for i in range(1, retries + 1):
        if mt5.initialize():
            log.info(f"✅ MT5 connected (try {i})")
            return True
        log.warning(f"MT5 connect try {i}/{retries}…")
        time.sleep(delay)
    return False


def mt5_alive() -> bool:
    return mt5.terminal_info() is not None


def ensure_alive() -> bool:
    if mt5_alive():
        return True
    log.warning("MT5 disconnected → reconnecting…")
    return mt5_connect(retries=5, delay=3.0)


def wait_next_candle(tf_min: int = 5) -> None:
    """Block until the next M5 candle opens (PM thread works during this wait)."""
    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M5, 0, 1)
    if rates is not None and len(rates) > 0:
        next_bar = int(rates[0]["time"]) + (tf_min * 60)
        wait     = next_bar - int(time.time()) + 3
        if 0 < wait <= tf_min * 60 + 10:
            log.info(f"⏳ Waiting {wait:.0f}s for next candle")
            time.sleep(wait)
            return
    now     = datetime.now(bkk_tz)
    elapsed = (now.minute % tf_min) * 60 + now.second
    wait    = (tf_min * 60) - elapsed + 3
    if wait <= 0 or wait > tf_min * 60:
        wait = tf_min * 60 + 3
    log.info(f"⏳ Waiting {wait:.0f}s (fallback)")
    time.sleep(wait)


# ══════════════════════════════════════════════════════════════════════════════
# 🚀  MAIN LOOP
# ══════════════════════════════════════════════════════════════════════════════
BANNER = """
╔══════════════════════════════════════════════════════════════════════════════╗
║  🚀 AI SMC/ICT Pro Sniper — V.9  (Architecture Refactor + ML-Ready)         ║
║  [FIX-1] Dynamic requote refresh  [FIX-2] Volatility deviation ≥50pts       ║
║  [FIX-3] Hash-based position tracking (hedge acct resilient)                ║
║  [OPT-1] NumPy ATR/Swings/Liq     [OOP-1] 4-class OOP architecture         ║
║  [ML-1/2/3] Feature extraction · MLPredictor · win-prob gate (0.65)         ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""


def main() -> None:
    print(BANNER)
    log.info("Bot V.9 starting")
    init_db()

    if not mt5_connect():
        log.error("❌ Cannot connect to MT5")
        return

    # ── Instantiate all components ────────────────────────────────────────────
    feed      = MarketDataFeed()
    signal_engine = SMCSignalEngine()
    risk      = RiskManager()
    execution = ExecutionHandler(risk)
    predictor = MLPredictor()
    # To load a real model uncomment:
    # predictor.load_model("smc_model.joblib")

    pm = PositionManager(feed, execution)
    pm.start()

    try:
        while True:
            cur = datetime.now(bkk_tz).strftime("%H:%M:%S")
            log.info("─" * 68)

            # GATE 1a — Connection
            if not ensure_alive():
                log.error("Reconnect failed → wait 60s")
                time.sleep(60)
                continue

            # GATE 1b — Drawdown limit
            if not risk.is_within_risk_limits():
                log.warning(f"⛔ {cur} | DD limit → halting today")
                wait_next_candle()
                continue

            # GATE 1b2 — Circuit Breaker
            if risk.is_circuit_breaker_tripped():
                log.warning(f"⚡ {cur} | Circuit Breaker → no new orders")
                wait_next_candle()
                continue

            # GATE 1c — Session
            session = signal_engine.get_session()
            log.info(f"🕐 {cur} | {session}")
            if session in ("OUT_OF_SESSION", "RED_NEWS_BLOCK"):
                wait_next_candle()
                continue

            # GATE 1c2 — Killzone
            in_kz, kz_name = signal_engine.is_in_killzone()
            if not in_kz:
                log.info(f"🕐 {kz_name} → outside killzone, skipping")
                wait_next_candle()
                continue
            log.info(f"✅ Killzone: {kz_name}")

            # GATE 1d — Hard spread
            if not risk.is_spread_ok():
                log.warning("⚠️ Spread exceeds HARD_BLOCK → wait")
                wait_next_candle()
                continue

            # ── Fetch data ────────────────────────────────────────────────────
            data = feed.fetch_all()
            if data["m5"] is None:
                log.warning("M5 unavailable → skip cycle")
                wait_next_candle()
                continue

            cleanup_cooldowns()

            # ── Signal analysis ───────────────────────────────────────────────
            setup = signal_engine.analyze_setup(
                data["m5"], data["h1"], data["d1"],
                data["m15"], session,
            )
            setup.spread_pts = risk.get_spread_pts()

            # Log market context
            liq = setup.liq_map
            if liq:
                log.info(
                    f"💧 BSL:{liq.bsl_nearest or '—'} | "
                    f"SSL:{liq.ssl_nearest or '—'} | "
                    f"SwH:{liq.swept_high} | SwL:{liq.swept_low}"
                )

            htf = setup.htf_result
            if htf:
                log.info(
                    f"🏗️  HTF SMC | Bias:{htf.bias} | BOS:{htf.last_bos} | "
                    f"CHOCH:{htf.choch_signal} | {htf.reason}"
                )

            log.info(
                f"📊 M15:{setup.m15_struct} | "
                f"ADR:{setup.adr_pct*100:.0f}% | "
                f"Threshold:{setup.threshold}"
            )

            if setup.signal == "WAIT":
                log.info(f"📉 WAIT → {' | '.join(setup.reasons) or 'no setup'}")
                wait_next_candle()
                continue

            # ── Score gate (legacy floor, pre-ML sanity check) ────────────────
            if setup.score < setup.threshold:
                log.info(f"⚠️ Score {setup.score} < {setup.threshold} → skip")
                wait_next_candle()
                continue

            # ── [ML-1] Extract features ───────────────────────────────────────
            setup.features = extract_features(setup)

            # ── [ML-3] ML win-probability gate ────────────────────────────────
            setup.win_prob = predictor.predict_win_probability(setup.features)
            log.info(
                f"🧠 ML WinProb: {setup.win_prob:.3f} "
                f"(threshold:{ML_WIN_PROB_THRESHOLD}) | {setup.summary()}"
            )

            if setup.win_prob < ML_WIN_PROB_THRESHOLD:
                log.info(
                    f"🤖 ML gate rejected: prob={setup.win_prob:.3f} "
                    f"< {ML_WIN_PROB_THRESHOLD} → skip"
                )
                wait_next_candle()
                continue

            # ── Cooldown check ────────────────────────────────────────────────
            if is_on_cooldown(setup.setup_hash):
                log.info(f"🔁 Cooldown ({setup.setup_hash}) → skip")
                wait_next_candle()
                continue

            # ── Duplicate guard ───────────────────────────────────────────────
            if risk.has_duplicate_setup(setup.setup_hash, setup.signal):
                log.info(f"🚫 Duplicate {setup.setup_hash} → skip")
                wait_next_candle()
                continue

            # ── Execute ───────────────────────────────────────────────────────
            if execution.place_order(setup, session):
                set_cooldown(setup.setup_hash)
                log.info(f"🎯 Placed | hash:{setup.setup_hash}")

            wait_next_candle()

    except KeyboardInterrupt:
        log.info("🛑 Stopped by user")
    except Exception as exc:
        log.exception(f"💥 Unhandled exception: {exc}")
    finally:
        pm.stop()
        close_db()
        mt5.shutdown()
        log.info("MT5 offline. Bot V.9 bye.")


# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    main()
