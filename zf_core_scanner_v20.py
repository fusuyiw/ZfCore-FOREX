try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None
import pandas as pd
import numpy as np
import yfinance as yf
import requests
import os
import json
import hashlib
import shutil
import time
import argparse
import contextlib
import io
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ==============================================================================
# CONFIGURATION BLOCK (API Keys & Risk Management)
# ==============================================================================
BASE_DIR = Path(os.getenv("ZF_STORAGE_DIR", Path(__file__).resolve().parent)).resolve()
ARCHIVE_DIR = BASE_DIR / "zf_archival_vault"
COLD_STORAGE_DIR = ARCHIVE_DIR / "cold_storage"
VALIDATION_REPORT_DIR = BASE_DIR / "zf_validation_reports"
PROFILE_DIR = BASE_DIR / "zf_profiles"
LIVE_LEARNING_DIR = BASE_DIR / "zf_live_learning"
OPEN_SIGNALS_PATH = LIVE_LEARNING_DIR / "open_signals.json"
CLOSED_SIGNALS_PATH = LIVE_LEARNING_DIR / "closed_signals.csv"
LIVE_SUMMARY_PATH = LIVE_LEARNING_DIR / "live_performance_summary.csv"
DAILY_LEARNING_SUMMARY_PATH = LIVE_LEARNING_DIR / "daily_learning_summary.csv"
OPTIMIZER_STATE_PATH = PROFILE_DIR / "optimizer_state.json"
PRIMARY_SYMBOLS_PATH = PROFILE_DIR / "primary_symbols.json"
MT5_FORWARD_DEALS_PATH = LIVE_LEARNING_DIR / "mt5_forward_deals.csv"
OKX_MARKET_STATE_PATH = LIVE_LEARNING_DIR / "okx_market_state.json"


def load_env_file(env_path=BASE_DIR / ".env"):
    """Load simple KEY=VALUE pairs from .env without adding a new dependency."""
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file()

ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
DATA_PROVIDER = os.getenv("ZF_DATA_PROVIDER", "MT5").strip().upper()
OANDA_API_TOKEN = os.getenv("OANDA_API_TOKEN", "")
OANDA_ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID", "")
OANDA_ENV = os.getenv("OANDA_ENV", "practice").strip().lower()
OANDA_SYMBOLS = os.getenv("OANDA_SYMBOLS", "")
OANDA_ACCOUNT_EQUITY_FALLBACK = float(os.getenv("OANDA_ACCOUNT_EQUITY_FALLBACK", "1000") or 1000)
YFINANCE_SYMBOLS = os.getenv("YFINANCE_SYMBOLS", "")
YFINANCE_ACCOUNT_EQUITY_FALLBACK = float(os.getenv("YFINANCE_ACCOUNT_EQUITY_FALLBACK", "1000") or 1000)
MT5_SYMBOL_SUFFIXES = [
    suffix.strip().lower()
    for suffix in os.getenv("MT5_SYMBOL_SUFFIXES", "").split(",")
    if suffix.strip()
]
SUPPORTED_ASSET_CLASSES = {
    item.strip().lower()
    for item in os.getenv("ZF_ASSET_CLASSES", "forex,energy,crypto").split(",")
    if item.strip()
}
ACTIVE_SYMBOL_LIMIT = int(os.getenv("ZF_ACTIVE_SYMBOL_LIMIT", "10") or 10)
USE_PRIMARY_SYMBOL_PROFILE = os.getenv("ZF_USE_PRIMARY_SYMBOL_PROFILE", "1").strip().lower() not in ("0", "false", "no")
USE_PROFILE_TIMEFRAMES = os.getenv("ZF_USE_PROFILE_TIMEFRAMES", "0").strip().lower() not in ("0", "false", "no")
USE_FIBO_FILTER = os.getenv("ZF_USE_FIBO_FILTER", "1").strip().lower() not in ("0", "false", "no")
MIN_EXECUTION_ZF_SCORE = float(os.getenv("ZF_MIN_EXECUTION_ZF_SCORE", "0.50") or 0.50)
FOCUS_SYMBOLS = [item.strip() for item in os.getenv("ZF_FOCUS_SYMBOLS", "").split(",") if item.strip()]

# Pengaturan Struktur Fraktal Waktu
TIMEFRAME_MAP = {
    "M15": mt5.TIMEFRAME_M15 if mt5 else "M15",
    "M30": mt5.TIMEFRAME_M30 if mt5 else "M30",
    "H4": mt5.TIMEFRAME_H4 if mt5 else "H4",
    "W1": mt5.TIMEFRAME_W1 if mt5 else "W1",
}
TIMEFRAME_HOURS = {"M15": 0.25, "M30": 0.5, "H4": 4.0, "W1": 168.0}
TF_CORE = TIMEFRAME_MAP["M30"]
DEFAULT_SCAN_TIMEFRAME = os.getenv("ZF_DEFAULT_SCAN_TIMEFRAME", "M30").strip().upper()
TP_ONLY_TARGET_PIPS = float(os.getenv("ZF_TP_ONLY_TARGET_PIPS", "50") or 50)
AUTO_EXECUTION_REQUIRES_SL = os.getenv("ZF_AUTO_EXECUTION_REQUIRES_SL", "1").strip().lower() not in ("0", "false", "no")
OANDA_GRANULARITY = "M30"
YFINANCE_INTERVAL = "30m"
YFINANCE_PERIOD = "30d"
BOOK_TYPE_BUY = mt5.BOOK_TYPE_BUY if mt5 else 1
BOOK_TYPE_SELL = mt5.BOOK_TYPE_SELL if mt5 else 2

SCAN_BARS = 500
TOP_BUY = 5
TOP_SELL = 5
TOP_MISMATCH = 8
SCAN_INTERVAL_MINUTES = 30
RUN_CONTINUOUS_BY_DEFAULT = True
AUTO_HISTORICAL_VALIDATION = os.getenv("ZF_AUTO_HISTORICAL_VALIDATION", "0").strip().lower() not in ("0", "false", "no")
HISTORICAL_REFRESH_HOURS = int(os.getenv("ZF_HISTORICAL_REFRESH_HOURS", "168") or 168)
HISTORICAL_LOOKBACK_DAYS = int(os.getenv("ZF_HISTORICAL_LOOKBACK_DAYS", "60") or 60)
HISTORICAL_HORIZON_BARS = 16
LIVE_SIGNAL_HORIZON_BARS = 16
TP_ONLY_LIVE_HORIZON_BARS = int(os.getenv("ZF_TP_ONLY_LIVE_HORIZON_BARS", "96") or 96)
EXPORT_EA_SIGNALS = os.getenv("ZF_EXPORT_EA_SIGNALS", "1").strip().lower() not in ("0", "false", "no")
EA_SIGNAL_FILE_NAME = os.getenv("ZF_EA_SIGNAL_FILE_NAME", "zf_ea_signals.csv")
EA_SIGNAL_EXPIRE_MINUTES = int(os.getenv("ZF_EA_SIGNAL_EXPIRE_MINUTES", "240") or 240)
EA_MAX_LOT = float(os.getenv("ZF_EA_MAX_LOT", "1.0") or 1.0)
EA_BUY_ORDER_TYPE = os.getenv("ZF_EA_BUY_ORDER_TYPE", "BUY_LIMIT").strip().upper()
EA_SELL_ORDER_TYPE = os.getenv("ZF_EA_SELL_ORDER_TYPE", "SELL_LIMIT").strip().upper()
EA_MAGIC_NUMBER = int(os.getenv("ZF_EA_MAGIC_NUMBER", "26061620") or 26061620)
SYNC_MT5_FORWARD_RESULTS = os.getenv("ZF_SYNC_MT5_FORWARD_RESULTS", "1").strip().lower() not in ("0", "false", "no")
MT5_FORWARD_LOOKBACK_DAYS = int(os.getenv("ZF_MT5_FORWARD_LOOKBACK_DAYS", "30") or 30)
SELF_HEALING_OPTIMIZER = True
OPTIMIZER_MIN_LIVE_SIGNALS = 20
OPTIMIZER_REFRESH_MINUTES = 60
OKX_PUBLIC_DATA_ENABLED = os.getenv("ZF_OKX_PUBLIC_DATA_ENABLED", "1").strip().lower() not in ("0", "false", "no")
OKX_BASE_URL = os.getenv("ZF_OKX_BASE_URL", "https://www.okx.com").rstrip("/")
OKX_TIMEOUT_SECONDS = float(os.getenv("ZF_OKX_TIMEOUT_SECONDS", "8") or 8)
OKX_CACHE_SECONDS = int(os.getenv("ZF_OKX_CACHE_SECONDS", "60") or 60)
OKX_REQUIRE_CRYPTO_DATA = os.getenv("ZF_OKX_REQUIRE_CRYPTO_DATA", "0").strip().lower() not in ("0", "false", "no")
FRACTIONAL_KELLY_ENABLED = os.getenv("ZF_FRACTIONAL_KELLY_ENABLED", "1").strip().lower() not in ("0", "false", "no")
FRACTIONAL_KELLY_FRACTION = float(os.getenv("ZF_FRACTIONAL_KELLY_FRACTION", "0.25") or 0.25)
FRACTIONAL_KELLY_MIN_MULTIPLIER = float(os.getenv("ZF_FRACTIONAL_KELLY_MIN_MULTIPLIER", "0.25") or 0.25)
WEEKLY_GRID_OPTIMIZER_ENABLED = os.getenv("ZF_WEEKLY_GRID_OPTIMIZER_ENABLED", "1").strip().lower() not in ("0", "false", "no")
WEEKLY_ZF_FLOORS = [
    float(item.strip())
    for item in os.getenv("ZF_WEEKLY_ZF_FLOORS", "0.45,0.50,0.55").split(",")
    if item.strip()
]
WEEKLY_TRAILING_OPTIONS = [
    item.strip().lower() not in ("0", "false", "no")
    for item in os.getenv("ZF_WEEKLY_TRAILING_OPTIONS", "1").split(",")
    if item.strip()
]

# KEPATUHAN DYNAMIC LOT SIZING (Manajemen Risiko Keras)
RISK_PER_TRADE_PCT = 1.5        # Risiko maksimal 1.5% dari Equity per posisi
DEFAULT_STOP_LOSS_PIPS = 30.0   # Bantalan SL minimum jika volatilitas terlalu tipis
ZF_DELTA_ALERT = 0.35
DRIFT_DELTA_ALERT = 0.25
ZF_WATCH_FLOOR = 0.50
DRIFT_WATCH_FLOOR = 0.50
ZF_CRITICAL_FLOOR = 0.80
ZF_COLD_MODE_FLOOR = 0.85
ZF_CIRCUIT_BREAKER = 0.99
ZF_DRIFT_ZSCORE_SCALE = 3.0
ARCHIVE_RETENTION_DAYS = 30
MAX_SPREAD_PIPS = 3.0
MAX_SLIPPAGE_PIPS = 2.0
SPREAD_STRESS_PIPS = 2.0
DEPTH_IMBALANCE_ALERT = 0.65
MIN_DEPTH_VOLUME = 1.0
P_PURE_HMA_WEIGHT = 0.70
P_PURE_MICRO_WEIGHT = 0.30
FIBO_LOOKBACK_BARS = 96
FIBO_BUY_MAX = 0.618
FIBO_SELL_MIN = 0.382
METAL_MIN_DRIFT = float(os.getenv("ZF_METAL_MIN_DRIFT", "1.0") or 1.0)
METAL_REQUIRE_TREND = os.getenv("ZF_METAL_REQUIRE_TREND", "1").strip().lower() not in ("0", "false", "no")
ATR_SL_MULTIPLIER = 1.35
DRIFT_SL_MULTIPLIER = 1.15
TREND_SL_MULTIPLIER = 1.20
RANGE_SL_MULTIPLIER = 0.95
MIN_REWARD_RISK = 1.25
ATR_TP_MULTIPLIER = 1.80
DRIFT_TP_MULTIPLIER = 1.60
TREND_TP_MULTIPLIER = 1.25
RANGE_TP_MULTIPLIER = 0.90
PROFILE_MIN_EXPECTANCY_R = 0.03
PROFILE_MIN_WIN_RATE = 43.0
PROFILE_MIN_SIGNALS = int(os.getenv("ZF_PROFILE_MIN_SIGNALS", "15") or 15)
PROJECTION_LOOKBACK_BARS = 6
PROJECTION_MATURITY_FLOOR = 0.55
PROJECTION_ZF_FLOOR = 0.45
PROJECTION_CONFIDENCE_FLOOR = 58
WATCH_ONLY_CONFIDENCE_FLOOR = 75
STRICT_ACCURACY_MODE = os.getenv("ZF_STRICT_ACCURACY_MODE", "1").strip().lower() not in ("0", "false", "no")
STRICT_MIN_QUALITY_SCORE = float(os.getenv("ZF_STRICT_MIN_QUALITY_SCORE", "55") or 55)
STRICT_MIN_HISTORICAL_WIN_RATE = float(os.getenv("ZF_STRICT_MIN_HISTORICAL_WIN_RATE", "58.0") or 58.0)
STRICT_MIN_HISTORICAL_EXPECTANCY_R = float(os.getenv("ZF_STRICT_MIN_HISTORICAL_EXPECTANCY_R", "0.03") or 0.03)
STRICT_MIN_LIVE_EXPECTANCY_R = float(os.getenv("ZF_STRICT_MIN_LIVE_EXPECTANCY_R", "-0.05") or -0.05)
STRICT_MIN_PROJECTED_MATURITY = float(os.getenv("ZF_STRICT_MIN_PROJECTED_MATURITY", "0.55") or 0.55)
STRICT_MIN_PROJECTED_RR = float(os.getenv("ZF_STRICT_MIN_PROJECTED_RR", "1.15") or 1.15)
STRICT_MIN_STRICT_RR = float(os.getenv("ZF_STRICT_MIN_STRICT_RR", "1.05") or 1.05)
STRICT_MARKET_HOURS_UTC = set(range(6, 21))

OPTIMIZER_DEFAULTS = {
    "atr_sl_multiplier": ATR_SL_MULTIPLIER,
    "drift_sl_multiplier": DRIFT_SL_MULTIPLIER,
    "atr_tp_multiplier": ATR_TP_MULTIPLIER,
    "drift_tp_multiplier": DRIFT_TP_MULTIPLIER,
    "min_reward_risk": MIN_REWARD_RISK,
    "max_spread_pips": MAX_SPREAD_PIPS,
    "max_slippage_pips": MAX_SLIPPAGE_PIPS,
    "confidence_floor": 60,
    "projection_maturity_floor": PROJECTION_MATURITY_FLOOR,
    "projection_zf_floor": PROJECTION_ZF_FLOOR,
    "projection_confidence_floor": PROJECTION_CONFIDENCE_FLOOR,
}
OPTIMIZER_BOUNDS = {
    "atr_sl_multiplier": (1.0, 2.2),
    "drift_sl_multiplier": (0.8, 2.0),
    "atr_tp_multiplier": (1.2, 3.0),
    "drift_tp_multiplier": (1.0, 2.8),
    "min_reward_risk": (1.1, 2.0),
    "max_spread_pips": (1.5, 5.0),
    "max_slippage_pips": (1.0, 4.0),
    "confidence_floor": (50, 95),
    "projection_maturity_floor": (0.45, 0.85),
    "projection_zf_floor": (0.35, 0.75),
    "projection_confidence_floor": (50, 90),
}

DEFAULT_OANDA_SYMBOLS = [
    "AUDCAD.o", "AUDCHF.o", "AUDJPY.o", "AUDNZD.o", "AUDUSD.o",
    "CHFJPY.o", "EURAUD.o", "EURCAD.o", "EURCHF.o", "EURGBP.o",
    "EURJPY.o", "EURNZD.o", "EURUSD.o", "GBPAUD.o", "GBPCAD.o",
    "GBPCHF.o", "GBPJPY.o", "GBPNZD.o", "GBPUSD.o", "NZDCAD.o",
    "NZDCHF.o", "NZDJPY.o", "NZDUSD.o", "USDCAD.o", "USDCHF.o",
    "USDJPY.o", "XAGUSD.o", "XAUUSD.o",
]
DEFAULT_YFINANCE_SYMBOLS = [
    "AUDCAD.yf", "AUDCHF.yf", "AUDJPY.yf", "AUDNZD.yf", "AUDUSD.yf",
    "CHFJPY.yf", "EURAUD.yf", "EURCAD.yf", "EURCHF.yf", "EURGBP.yf",
    "EURJPY.yf", "EURNZD.yf", "EURUSD.yf", "GBPAUD.yf", "GBPCAD.yf",
    "GBPCHF.yf", "GBPJPY.yf", "GBPNZD.yf", "GBPUSD.yf", "NZDCAD.yf",
    "NZDCHF.yf", "NZDJPY.yf", "NZDUSD.yf", "USDCAD.yf", "USDCHF.yf",
    "USDJPY.yf", "XAGUSD.yf", "XAUUSD.yf",
]


class SimpleObject:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class OandaProvider:
    def __init__(self):
        self.api_token = OANDA_API_TOKEN
        self.account_id = OANDA_ACCOUNT_ID
        self.base_url = "https://api-fxpractice.oanda.com" if OANDA_ENV != "live" else "https://api-fxtrade.oanda.com"
        self.session = requests.Session()
        if self.api_token:
            self.session.headers.update({"Authorization": f"Bearer {self.api_token}"})

    @property
    def configured(self):
        return bool(self.api_token and self.account_id)

    def request(self, path, params=None):
        if not self.configured:
            raise RuntimeError("OANDA_API_TOKEN dan OANDA_ACCOUNT_ID belum diisi.")
        url = f"{self.base_url}{path}"
        response = self.session.get(url, params=params or {}, timeout=12)
        response.raise_for_status()
        return response.json()

    def symbol_to_instrument(self, symbol_name):
        clean = str(symbol_name).split(".")[0].upper().replace("_", "")
        if len(clean) < 6:
            return clean
        return f"{clean[:3]}_{clean[3:6]}"

    def instrument_to_symbol(self, instrument):
        return f"{instrument.replace('_', '')}.o"

    def symbols_get(self):
        if OANDA_SYMBOLS:
            symbols = [item.strip() for item in OANDA_SYMBOLS.split(",") if item.strip()]
            return [SimpleObject(name=symbol) for symbol in symbols]

        try:
            payload = self.request(f"/v3/accounts/{self.account_id}/instruments")
            instruments = payload.get("instruments", [])
            symbols = []
            for item in instruments:
                name = item.get("name", "")
                instrument_type = item.get("type", "")
                if instrument_type in ("CURRENCY", "CFD") and "_" in name:
                    symbol = self.instrument_to_symbol(name)
                    if any(asset in symbol for asset in ["USD", "JPY", "EUR", "GBP", "AUD", "CAD", "CHF", "NZD", "XAU", "XAG"]):
                        symbols.append(symbol)
            return [SimpleObject(name=symbol) for symbol in sorted(set(symbols))] or [SimpleObject(name=s) for s in DEFAULT_OANDA_SYMBOLS]
        except Exception:
            return [SimpleObject(name=s) for s in DEFAULT_OANDA_SYMBOLS]

    def account_equity(self):
        try:
            payload = self.request(f"/v3/accounts/{self.account_id}/summary")
            account = payload.get("account", {})
            return float(account.get("NAV") or account.get("balance") or OANDA_ACCOUNT_EQUITY_FALLBACK)
        except Exception:
            return OANDA_ACCOUNT_EQUITY_FALLBACK

    def symbol_info(self, symbol_name):
        clean = str(symbol_name).split(".")[0].upper()
        if clean.endswith("JPY"):
            return SimpleObject(point=0.001, digits=3, name=symbol_name)
        if clean.startswith("XAU") or clean.startswith("XAG"):
            return SimpleObject(point=0.01, digits=2, name=symbol_name)
        return SimpleObject(point=0.00001, digits=5, name=symbol_name)

    def symbol_info_tick(self, symbol_name):
        instrument = self.symbol_to_instrument(symbol_name)
        payload = self.request(f"/v3/accounts/{self.account_id}/pricing", {"instruments": instrument})
        prices = payload.get("prices", [])
        if not prices:
            return None
        price = prices[0]
        bids = price.get("bids", [])
        asks = price.get("asks", [])
        bid = float(bids[0]["price"]) if bids else np.nan
        ask = float(asks[0]["price"]) if asks else np.nan
        return SimpleObject(bid=bid, ask=ask, time=price.get("time"))

    def market_book_get(self, symbol_name):
        instrument = self.symbol_to_instrument(symbol_name)
        payload = self.request(f"/v3/accounts/{self.account_id}/pricing", {"instruments": instrument})
        prices = payload.get("prices", [])
        if not prices:
            return []
        price = prices[0]
        entries = []
        for bid in price.get("bids", []):
            entries.append(
                SimpleObject(
                    type=BOOK_TYPE_BUY,
                    price=float(bid.get("price", 0) or 0),
                    volume=float(bid.get("liquidity", 0) or 0),
                )
            )
        for ask in price.get("asks", []):
            entries.append(
                SimpleObject(
                    type=BOOK_TYPE_SELL,
                    price=float(ask.get("price", 0) or 0),
                    volume=float(ask.get("liquidity", 0) or 0),
                )
            )
        return entries

    def _parse_candles(self, candles):
        rows = []
        for item in candles:
            if not item.get("complete", True):
                continue
            mid = item.get("mid", {})
            if not mid:
                continue
            dt = pd.to_datetime(item.get("time"), utc=True)
            rows.append(
                {
                    "time": int(dt.timestamp()),
                    "open": float(mid.get("o", np.nan)),
                    "high": float(mid.get("h", np.nan)),
                    "low": float(mid.get("l", np.nan)),
                    "close": float(mid.get("c", np.nan)),
                    "tick_volume": int(item.get("volume", 0) or 0),
                }
            )
        return rows

    def copy_rates_from_pos(self, symbol_name, timeframe, start_pos, count):
        instrument = self.symbol_to_instrument(symbol_name)
        payload = self.request(
            f"/v3/instruments/{instrument}/candles",
            {"granularity": OANDA_GRANULARITY, "count": int(count), "price": "M"},
        )
        rows = self._parse_candles(payload.get("candles", []))
        if start_pos:
            rows = rows[int(start_pos):]
        return rows

    def copy_rates_range(self, symbol_name, timeframe, start_time, end_time):
        instrument = self.symbol_to_instrument(symbol_name)
        start_dt = pd.to_datetime(start_time, utc=True)
        end_dt = pd.to_datetime(end_time, utc=True)
        payload = self.request(
            f"/v3/instruments/{instrument}/candles",
            {
                "granularity": OANDA_GRANULARITY,
                "from": start_dt.isoformat().replace("+00:00", "Z"),
                "to": end_dt.isoformat().replace("+00:00", "Z"),
                "price": "M",
            },
        )
        return self._parse_candles(payload.get("candles", []))


OANDA_PROVIDER = OandaProvider()


class YFinanceProvider:
    def __init__(self):
        self._rates_cache = {}

    @property
    def configured(self):
        return True

    def symbols_get(self):
        if YFINANCE_SYMBOLS:
            symbols = [item.strip() for item in YFINANCE_SYMBOLS.split(",") if item.strip()]
            return [SimpleObject(name=symbol) for symbol in symbols]
        return [SimpleObject(name=symbol) for symbol in DEFAULT_YFINANCE_SYMBOLS]

    def account_equity(self):
        return YFINANCE_ACCOUNT_EQUITY_FALLBACK

    def symbol_to_ticker(self, symbol_name):
        clean = str(symbol_name).split(".")[0].upper()
        if clean == "XAUUSD":
            return "GC=F"
        if clean == "XAGUSD":
            return "SI=F"
        if len(clean) >= 6:
            return f"{clean[:3]}{clean[3:6]}=X"
        return clean

    def symbol_info(self, symbol_name):
        clean = str(symbol_name).split(".")[0].upper()
        if clean.endswith("JPY"):
            return SimpleObject(point=0.001, digits=3, name=symbol_name)
        if clean.startswith("XAU") or clean.startswith("XAG"):
            return SimpleObject(point=0.01, digits=2, name=symbol_name)
        return SimpleObject(point=0.00001, digits=5, name=symbol_name)

    def _download_rates(self, symbol_name):
        now_bucket = int(time.time() // 60)
        cache_key = (symbol_name, now_bucket)
        if cache_key in self._rates_cache:
            return self._rates_cache[cache_key]

        ticker = self.symbol_to_ticker(symbol_name)
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                df = yf.download(ticker, period=YFINANCE_PERIOD, interval=YFINANCE_INTERVAL, progress=False, auto_adjust=False)
        except Exception:
            self._rates_cache[cache_key] = []
            return []
        if df is None or df.empty:
            self._rates_cache[cache_key] = []
            return []

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        rows = []
        for idx, row in df.dropna().iterrows():
            dt = pd.to_datetime(idx, utc=True)
            rows.append(
                {
                    "time": int(dt.timestamp()),
                    "open": float(row.get("Open", np.nan)),
                    "high": float(row.get("High", np.nan)),
                    "low": float(row.get("Low", np.nan)),
                    "close": float(row.get("Close", np.nan)),
                    "tick_volume": int(row.get("Volume", 0) or 0),
                }
            )

        self._rates_cache[cache_key] = rows
        return rows

    def symbol_info_tick(self, symbol_name):
        rows = self._download_rates(symbol_name)
        if not rows:
            return None
        last = rows[-1]
        info = self.symbol_info(symbol_name)
        close = float(last["close"])
        point = float(info.point)
        pip_factor = symbol_pip_factor(info)
        synthetic_spread_pips = 0.2 if str(symbol_name).split(".")[0].upper().endswith("USD") else 0.6
        if str(symbol_name).split(".")[0].upper().startswith(("XAU", "XAG")):
            synthetic_spread_pips = 2.0
        spread_price = synthetic_spread_pips * point * pip_factor
        return SimpleObject(bid=close - spread_price / 2, ask=close + spread_price / 2, time=last["time"])

    def market_book_get(self, symbol_name):
        return []

    def copy_rates_from_pos(self, symbol_name, timeframe, start_pos, count):
        rows = self._download_rates(symbol_name)
        if start_pos:
            rows = rows[int(start_pos):]
        return rows[-int(count):]

    def copy_rates_range(self, symbol_name, timeframe, start_time, end_time):
        rows = self._download_rates(symbol_name)
        start_ts = int(pd.to_datetime(start_time, utc=True).timestamp())
        end_ts = int(pd.to_datetime(end_time, utc=True).timestamp())
        return [row for row in rows if start_ts <= row["time"] <= end_ts]


YFINANCE_PROVIDER = YFinanceProvider()


class OkxPublicProvider:
    """Public, read-only OKX derivatives context for crypto ZF validation."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "ZF-Core-Scanner/20"})
        self.cache = {}
        self.state = self._load_state()

    def _load_state(self):
        if not OKX_MARKET_STATE_PATH.exists():
            return {}
        try:
            return json.loads(OKX_MARKET_STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_state(self):
        LIVE_LEARNING_DIR.mkdir(parents=True, exist_ok=True)
        OKX_MARKET_STATE_PATH.write_text(
            json.dumps(self.state, ensure_ascii=True, indent=2, default=str),
            encoding="utf-8",
        )

    def request(self, path, params=None):
        cache_key = (path, tuple(sorted((params or {}).items())))
        cached = self.cache.get(cache_key)
        if cached and time.time() - cached["time"] < OKX_CACHE_SECONDS:
            return cached["data"]

        response = self.session.get(
            f"{OKX_BASE_URL}{path}",
            params=params or {},
            timeout=OKX_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        if str(payload.get("code", "")) != "0":
            raise RuntimeError(payload.get("msg") or f"OKX code {payload.get('code')}")
        data = payload.get("data", [])
        self.cache[cache_key] = {"time": time.time(), "data": data}
        return data

    def instrument_for_symbol(self, symbol_name):
        clean = normalized_symbol_text(symbol_name)
        for marker in CRYPTO_MARKERS:
            if marker in clean:
                return f"{marker}-USDT-SWAP"
        return ""

    def market_context(self, symbol_name):
        empty = {
            "Status": "DISABLED" if not OKX_PUBLIC_DATA_ENABLED else "UNAVAILABLE",
            "Instrument": "",
            "Last": np.nan,
            "Funding_Rate": np.nan,
            "Open_Interest": np.nan,
            "Open_Interest_USD": np.nan,
            "OI_Change_Pct": np.nan,
            "External_Stress": 0.0,
            "Funding_Bias": "NEUTRAL",
        }
        if not OKX_PUBLIC_DATA_ENABLED:
            return empty

        instrument = self.instrument_for_symbol(symbol_name)
        if not instrument:
            return empty

        try:
            ticker_rows = self.request("/api/v5/market/ticker", {"instId": instrument})
            funding_rows = self.request("/api/v5/public/funding-rate", {"instId": instrument})
            oi_rows = self.request(
                "/api/v5/public/open-interest",
                {"instType": "SWAP", "instId": instrument},
            )
            ticker = ticker_rows[0] if ticker_rows else {}
            funding = funding_rows[0] if funding_rows else {}
            oi = oi_rows[0] if oi_rows else {}

            funding_rate = float(funding.get("fundingRate") or 0.0)
            open_interest = float(oi.get("oi") or 0.0)
            open_interest_usd = float(oi.get("oiUsd") or 0.0)
            previous = self.state.get(instrument, {})
            previous_oi = float(previous.get("open_interest") or 0.0)
            oi_change_pct = (
                ((open_interest - previous_oi) / previous_oi) * 100
                if previous_oi > 0 and open_interest > 0
                else np.nan
            )

            funding_stress = min(abs(funding_rate) / 0.001, 1.0)
            oi_stress = min(abs(oi_change_pct) / 5.0, 1.0) if pd.notna(oi_change_pct) else 0.0
            external_stress = float(np.clip((funding_stress * 0.60) + (oi_stress * 0.40), 0, 1))
            funding_bias = "SELL" if funding_rate > 0.0005 else "BUY" if funding_rate < -0.0005 else "NEUTRAL"

            self.state[instrument] = {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "open_interest": open_interest,
                "open_interest_usd": open_interest_usd,
                "funding_rate": funding_rate,
            }
            self._save_state()
            return {
                "Status": "OK",
                "Instrument": instrument,
                "Last": float(ticker.get("last") or np.nan),
                "Funding_Rate": funding_rate,
                "Open_Interest": open_interest,
                "Open_Interest_USD": open_interest_usd,
                "OI_Change_Pct": oi_change_pct,
                "External_Stress": external_stress,
                "Funding_Bias": funding_bias,
            }
        except Exception as exc:
            empty["Instrument"] = instrument
            empty["Status"] = f"ERROR: {exc}"
            return empty


OKX_PROVIDER = OkxPublicProvider()


def using_oanda_provider():
    return DATA_PROVIDER == "OANDA"


def using_yfinance_provider():
    return DATA_PROVIDER == "YFINANCE"


def data_initialize():
    if using_oanda_provider():
        return OANDA_PROVIDER.configured
    if using_yfinance_provider():
        return YFINANCE_PROVIDER.configured
    return bool(mt5 and mt5.initialize())


def data_shutdown():
    if not using_oanda_provider() and not using_yfinance_provider() and mt5:
        mt5.shutdown()


def data_account_equity():
    if using_oanda_provider():
        return OANDA_PROVIDER.account_equity()
    if using_yfinance_provider():
        return YFINANCE_PROVIDER.account_equity()
    account_info = mt5.account_info() if mt5 else None
    return float(account_info.equity) if account_info is not None else 1000.0


def data_symbols_get():
    if using_oanda_provider():
        return OANDA_PROVIDER.symbols_get()
    if using_yfinance_provider():
        return YFINANCE_PROVIDER.symbols_get()
    return mt5.symbols_get() if mt5 else []


MAJOR_CURRENCIES = ("USD", "JPY", "EUR", "GBP", "AUD", "CAD", "CHF", "NZD")
ENERGY_MARKERS = ("USOIL", "UKOIL", "XTIUSD", "XBRUSD", "WTI", "BRENT", "BRN", "OIL")
METAL_MARKERS = ("XAU", "XAG")
CRYPTO_MARKERS = ("BTC", "ETH", "XRP", "LTC", "DOGE", "ADA", "SOL", "BNB", "DOT", "TRX", "AVAX", "LINK")


def normalized_symbol_text(symbol_name):
    return "".join(ch for ch in str(symbol_name).upper() if ch.isalnum())


def classify_symbol(symbol_name):
    clean = normalized_symbol_text(symbol_name)
    for marker in CRYPTO_MARKERS:
        if marker in clean:
            return "crypto"
    for marker in ENERGY_MARKERS:
        if marker in clean:
            return "energy"
    for marker in METAL_MARKERS:
        if marker in clean:
            return "metal"
    for base in MAJOR_CURRENCIES:
        for quote in MAJOR_CURRENCIES:
            if base != quote and f"{base}{quote}" in clean:
                return "forex"
    return "other"


def is_supported_scan_symbol(symbol_name):
    return classify_symbol(symbol_name) in SUPPORTED_ASSET_CLASSES


def normalize_timeframe_name(timeframe_name):
    normalized = str(timeframe_name or DEFAULT_SCAN_TIMEFRAME).strip().upper()
    return normalized if normalized in TIMEFRAME_MAP else "M30"


def timeframe_value(timeframe_name):
    return TIMEFRAME_MAP[normalize_timeframe_name(timeframe_name)]


def filter_trade_symbols(symbols):
    names = [s.name for s in symbols if getattr(s, "name", "")]
    if MT5_SYMBOL_SUFFIXES and not (using_oanda_provider() or using_yfinance_provider()):
        names = [name for name in names if any(name.lower().endswith(suffix) for suffix in MT5_SYMBOL_SUFFIXES)]
    return sorted({name for name in names if is_supported_scan_symbol(name)})


def data_symbol_info(symbol_name):
    if using_oanda_provider():
        return OANDA_PROVIDER.symbol_info(symbol_name)
    if using_yfinance_provider():
        return YFINANCE_PROVIDER.symbol_info(symbol_name)
    return mt5.symbol_info(symbol_name) if mt5 else None


def data_symbol_info_tick(symbol_name):
    if using_oanda_provider():
        return OANDA_PROVIDER.symbol_info_tick(symbol_name)
    if using_yfinance_provider():
        return YFINANCE_PROVIDER.symbol_info_tick(symbol_name)
    return mt5.symbol_info_tick(symbol_name) if mt5 else None


def data_market_book(symbol_name):
    if using_oanda_provider():
        return OANDA_PROVIDER.market_book_get(symbol_name)
    if using_yfinance_provider():
        return YFINANCE_PROVIDER.market_book_get(symbol_name)
    if not mt5:
        return []
    if mt5.market_book_add(symbol_name):
        try:
            return mt5.market_book_get(symbol_name) or []
        finally:
            mt5.market_book_release(symbol_name)
    return []


def data_copy_rates_from_pos(symbol_name, timeframe, start_pos, count):
    if using_oanda_provider():
        return OANDA_PROVIDER.copy_rates_from_pos(symbol_name, timeframe, start_pos, count)
    if using_yfinance_provider():
        return YFINANCE_PROVIDER.copy_rates_from_pos(symbol_name, timeframe, start_pos, count)
    return mt5.copy_rates_from_pos(symbol_name, timeframe, start_pos, count) if mt5 else None


def data_copy_rates_range(symbol_name, timeframe, start_time, end_time):
    if using_oanda_provider():
        return OANDA_PROVIDER.copy_rates_range(symbol_name, timeframe, start_time, end_time)
    if using_yfinance_provider():
        return YFINANCE_PROVIDER.copy_rates_range(symbol_name, timeframe, start_time, end_time)
    return mt5.copy_rates_range(symbol_name, timeframe, start_time, end_time) if mt5 else None

# ==============================================================================
# QUANTITATIVE ENGINE (Hull Moving Average & Mathematical Models)
# ==============================================================================
def calculate_hma(series, period=20):
    """Hull Moving Average (HMA) sebagai proksi dinamis P_pure (Bab 4.2)"""
    half_period = int(period / 2)
    sqrt_period = int(np.sqrt(period))
    
    def wma(s, p):
        weights = np.arange(1, p + 1)
        return s.rolling(p).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)
    
    raw_hma = 2 * wma(series, half_period) - wma(series, period)
    return wma(raw_hma, sqrt_period)

def fetch_macro_sentiment():
    """Menarik Parameter Manifold Eksternal via Yahoo Finance"""
    macro_data = {"DXY": 0.0, "US10Y": 0.0, "GOLD": 0.0}
    try:
        dxy_df = yf.download("DX-Y.NYB", period="5d", progress=False)
        us10y_df = yf.download("^TNX", period="5d", progress=False)
        gold_df = yf.download("GC=F", period="5d", progress=False)
        
        macro_data["DXY"] = float(dxy_df['Close'].iloc[-1].iloc[0] if isinstance(dxy_df['Close'].iloc[-1], pd.Series) else dxy_df['Close'].iloc[-1])
        macro_data["US10Y"] = float(us10y_df['Close'].iloc[-1].iloc[0] if isinstance(us10y_df['Close'].iloc[-1], pd.Series) else us10y_df['Close'].iloc[-1])
        macro_data["GOLD"] = float(gold_df['Close'].iloc[-1].iloc[0] if isinstance(gold_df['Close'].iloc[-1], pd.Series) else gold_df['Close'].iloc[-1])
    except Exception:
        pass
    return macro_data

def fetch_news_risk():
    """News Risk Engine via Finnhub API"""
    if not FINNHUB_API_KEY:
        return "MEDIUM RISK (FINNHUB_API_KEY not configured)"

    try:
        now = datetime.now(timezone.utc)
        end_window = now + timedelta(hours=2)
        url = f"https://finnhub.io/api/v1/calendar/economic?from={now.strftime('%Y-%m-%d')}&to={end_window.strftime('%Y-%m-%d')}&token={FINNHUB_API_KEY}"
        response = requests.get(url, timeout=5).json()
        
        if "economicCalendar" in response:
            events = response["economicCalendar"]
            for event in events:
                if event.get('impact') == 'high' or any(keyword in event.get('event', '').upper() for keyword in ['FOMC', 'NFP', 'FED', 'RATE', 'INTEREST']):
                    return "HIGH RISK (Event-Lock Active)"
        return "LOW RISK"
    except Exception:
        return "MEDIUM RISK (API Fallback Mode)"


def file_sha256(path):
    """Calculate SHA-256 checksum for archive integrity validation."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_archive_manifest(json_path):
    """Return False only when a manifest exists and checksum validation fails."""
    manifest_path = json_path.with_suffix(".manifest.json")
    if not manifest_path.exists():
        return True

    try:
        with manifest_path.open("r", encoding="utf-8") as f:
            manifest = json.load(f)
        expected_hash = manifest.get("files", {}).get(json_path.name, {}).get("sha256")
        return bool(expected_hash) and file_sha256(json_path) == expected_hash
    except (OSError, json.JSONDecodeError):
        return False


def prune_archival_vault(retention_days=ARCHIVE_RETENTION_DAYS):
    """Move old hot-memory archives into cold storage without deleting them."""
    if not ARCHIVE_DIR.exists():
        return []

    COLD_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = datetime.now().timestamp() - (retention_days * 24 * 60 * 60)
    moved = []

    for path in ARCHIVE_DIR.glob("zf_scan_*"):
        if path.is_dir() or path.parent == COLD_STORAGE_DIR:
            continue
        if path.stat().st_mtime >= cutoff:
            continue

        target = COLD_STORAGE_DIR / path.name
        if target.exists():
            target = COLD_STORAGE_DIR / f"{path.stem}_{int(datetime.now().timestamp())}{path.suffix}"
        shutil.move(str(path), str(target))
        moved.append(str(target))

    return moved


def load_latest_archive():
    """Load the latest completed scan snapshot, if available."""
    if not ARCHIVE_DIR.exists():
        return None, None

    archive_paths = [
        path for path in ARCHIVE_DIR.glob("zf_scan_*.json")
        if not path.name.endswith(".manifest.json")
    ]
    for path in sorted(archive_paths, reverse=True):
        try:
            if not verify_archive_manifest(path):
                continue
            with path.open("r", encoding="utf-8") as f:
                return path, json.load(f)
        except (OSError, json.JSONDecodeError):
            continue

    return None, None


def load_or_build_historical_profile():
    """Build live scanner profile from the latest historical validation summary."""
    if not VALIDATION_REPORT_DIR.exists():
        return {}, None

    summaries = sorted(VALIDATION_REPORT_DIR.glob("zf_validation_summary_*.csv"), reverse=True)
    if not summaries:
        return {}, None

    latest_summary = summaries[0]
    try:
        summary_df = pd.read_csv(latest_summary)
    except (OSError, pd.errors.EmptyDataError):
        return {}, None

    if "Selection_Score" not in summary_df.columns:
        signals = pd.to_numeric(summary_df.get("Signals", 0), errors="coerce").fillna(0)
        win_rate = pd.to_numeric(summary_df.get("Win_Rate_Resolved", 0), errors="coerce").fillna(0)
        expectancy = pd.to_numeric(summary_df.get("Expectancy_R", 0), errors="coerce").fillna(0)
        avg_rr = pd.to_numeric(summary_df.get("Avg_RR", 0), errors="coerce").fillna(0)
        signal_factor = np.clip(signals / max(PROFILE_MIN_SIGNALS, 1), 0, 1)
        summary_df["Selection_Score"] = (
            win_rate * 0.48
            + np.clip(50 + expectancy * 150, 0, 100) * 0.34
            + np.clip(avg_rr / 2.0 * 100, 0, 100) * 0.10
            + signal_factor * 100 * 0.08
        ).round(2)

    profile = {}
    for _, row in summary_df.iterrows():
        symbol = str(row.get("Symbol", "")).strip()
        if not symbol:
            continue

        expectancy = float(row.get("Expectancy_R", 0.0) or 0.0)
        win_rate = float(row.get("Win_Rate_Resolved", 0.0) or 0.0)
        signals_value = pd.to_numeric(pd.Series([row.get("Signals", 0)]), errors="coerce").fillna(0).iloc[0]
        signals = int(signals_value)
        selection_score = float(row.get("Selection_Score", 0.0) or 0.0)
        if symbol in profile and selection_score <= profile[symbol].get("selection_score", 0.0):
            continue

        if (
            expectancy >= PROFILE_MIN_EXPECTANCY_R
            and win_rate >= PROFILE_MIN_WIN_RATE
            and signals >= PROFILE_MIN_SIGNALS
        ):
            status = "TRADEABLE"
        elif expectancy >= 0:
            status = "WATCH_ONLY"
        else:
            status = "AVOID"

        profile[symbol] = {
            "status": status,
            "expectancy_r": expectancy,
            "win_rate_resolved": win_rate,
            "signals": signals,
            "asset_class": row.get("Asset_Class", classify_symbol(symbol)),
            "timeframe": normalize_timeframe_name(row.get("Timeframe", DEFAULT_SCAN_TIMEFRAME)),
            "exit_mode": str(row.get("Exit_Mode", "dynamic_sl_tp") or "dynamic_sl_tp"),
            "optimizer_zf_floor": float(row.get("Optimizer_ZF_Floor", MIN_EXECUTION_ZF_SCORE) or MIN_EXECUTION_ZF_SCORE),
            "optimizer_fibo_filter": str(row.get("Optimizer_Fibo_Filter", USE_FIBO_FILTER)).strip().lower() not in ("0", "false", "no"),
            "optimizer_trailing": str(row.get("Optimizer_Trailing", True)).strip().lower() not in ("0", "false", "no"),
            "avg_hours_to_result": float(row.get("Avg_Hours_To_Result", np.nan) or np.nan),
            "selection_score": selection_score,
            "live_expectancy_r": np.nan,
            "live_win_rate_resolved": np.nan,
            "live_signals": 0,
            "blended_expectancy_r": expectancy,
        }

    if LIVE_SUMMARY_PATH.exists():
        try:
            live_df = pd.read_csv(LIVE_SUMMARY_PATH)
            for _, row in live_df.iterrows():
                symbol = str(row.get("Symbol", "")).strip()
                if symbol not in profile:
                    continue

                live_signals = int(row.get("Signals", 0) or 0)
                live_expectancy = float(row.get("Expectancy_R", 0.0) or 0.0)
                live_win_rate = float(row.get("Win_Rate_Resolved", 0.0) or 0.0)
                blended = profile[symbol]["expectancy_r"]
                if live_signals >= 20:
                    blended = (profile[symbol]["expectancy_r"] * 0.80) + (live_expectancy * 0.20)

                profile[symbol]["live_expectancy_r"] = live_expectancy
                profile[symbol]["live_win_rate_resolved"] = live_win_rate
                profile[symbol]["live_signals"] = live_signals
                profile[symbol]["blended_expectancy_r"] = round(blended, 4)

                if profile[symbol]["status"] == "TRADEABLE" and live_signals >= 20 and live_expectancy <= -0.15:
                    profile[symbol]["status"] = "WATCH_ONLY"
                elif (
                    profile[symbol]["status"] == "WATCH_ONLY"
                    and live_signals >= 50
                    and blended >= PROFILE_MIN_EXPECTANCY_R
                    and live_win_rate >= PROFILE_MIN_WIN_RATE
                ):
                    profile[symbol]["status"] = "TRADEABLE"
        except (OSError, pd.errors.EmptyDataError):
            pass

    ranked_symbols = sorted(
        profile,
        key=lambda symbol: (
            profile[symbol].get("status") == "TRADEABLE",
            profile[symbol].get("blended_expectancy_r", profile[symbol].get("expectancy_r", 0)),
            profile[symbol].get("win_rate_resolved", 0),
            profile[symbol].get("selection_score", 0),
        ),
        reverse=True,
    )
    primary_symbols = [
        symbol
        for symbol in ranked_symbols
        if profile[symbol].get("status") == "TRADEABLE"
    ][:ACTIVE_SYMBOL_LIMIT]
    if len(primary_symbols) < ACTIVE_SYMBOL_LIMIT:
        primary_symbols.extend(
            [
                symbol
                for symbol in ranked_symbols
                if symbol not in primary_symbols and profile[symbol].get("status") == "WATCH_ONLY"
            ][: ACTIVE_SYMBOL_LIMIT - len(primary_symbols)]
        )
    if len(primary_symbols) < ACTIVE_SYMBOL_LIMIT:
        primary_symbols.extend(
            [
                symbol
                for symbol in ranked_symbols
                if symbol not in primary_symbols
            ][: ACTIVE_SYMBOL_LIMIT - len(primary_symbols)]
        )

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    profile_path = PROFILE_DIR / "tradeable_symbols.json"
    payload = {
        "updated_at": datetime.now().astimezone().isoformat(),
        "source": str(latest_summary),
        "rules": {
            "min_expectancy_r": PROFILE_MIN_EXPECTANCY_R,
            "min_win_rate_resolved": PROFILE_MIN_WIN_RATE,
            "min_signals": PROFILE_MIN_SIGNALS,
        },
        "active_symbol_limit": ACTIVE_SYMBOL_LIMIT,
        "primary_symbols": primary_symbols,
        "primary_routes": [
            {
                "symbol": symbol,
                "timeframe": profile[symbol].get("timeframe", "M30"),
                "exit_mode": profile[symbol].get("exit_mode", "dynamic_sl_tp"),
                "win_rate_resolved": profile[symbol].get("win_rate_resolved", 0),
                "expectancy_r": profile[symbol].get("expectancy_r", 0),
                "selection_score": profile[symbol].get("selection_score", 0),
            }
            for symbol in primary_symbols
        ],
        "tradeable_symbols": sorted([symbol for symbol, item in profile.items() if item["status"] == "TRADEABLE"]),
        "watch_only_symbols": sorted([symbol for symbol, item in profile.items() if item["status"] == "WATCH_ONLY"]),
        "avoid_symbols": sorted([symbol for symbol, item in profile.items() if item["status"] == "AVOID"]),
        "symbols": profile,
    }
    with profile_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=True, indent=2)
    with PRIMARY_SYMBOLS_PATH.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "updated_at": payload["updated_at"],
                "source": str(latest_summary),
                "asset_classes": sorted(SUPPORTED_ASSET_CLASSES),
                "active_symbol_limit": ACTIVE_SYMBOL_LIMIT,
                "primary_symbols": primary_symbols,
                "primary_routes": payload["primary_routes"],
            },
            f,
            ensure_ascii=True,
            indent=2,
        )

    return profile, latest_summary


def apply_primary_symbol_limit(symbols, profile):
    if not USE_PRIMARY_SYMBOL_PROFILE or ACTIVE_SYMBOL_LIMIT <= 0 or not profile:
        return symbols

    primary = [
        symbol
        for symbol, item in sorted(
            profile.items(),
            key=lambda kv: (
                kv[1].get("status") == "TRADEABLE",
                kv[1].get("blended_expectancy_r", kv[1].get("expectancy_r", 0)),
                kv[1].get("win_rate_resolved", 0),
                kv[1].get("selection_score", 0),
            ),
            reverse=True,
        )
        if symbol
    ][:ACTIVE_SYMBOL_LIMIT]

    if not primary:
        return symbols
    available = set(symbols)
    selected = [symbol for symbol in primary if symbol in available]
    selected.extend([symbol for symbol in FOCUS_SYMBOLS if symbol in available and symbol not in selected])
    return selected or symbols


def apply_historical_profile_gate(risk_df, profile):
    """Attach historical validation status without limiting scan to only tradeable pairs."""
    if risk_df.empty or not profile:
        return risk_df.copy()

    gated_df = risk_df.copy()
    gated_df["Historical_Status"] = gated_df["Symbol"].map(lambda symbol: profile.get(symbol, {}).get("status", "UNVALIDATED"))
    gated_df["Historical_Expectancy_R"] = gated_df["Symbol"].map(lambda symbol: profile.get(symbol, {}).get("blended_expectancy_r", profile.get(symbol, {}).get("expectancy_r", np.nan)))
    gated_df["Historical_Win_Rate"] = gated_df["Symbol"].map(lambda symbol: profile.get(symbol, {}).get("win_rate_resolved", np.nan))
    gated_df["Historical_Signals"] = gated_df["Symbol"].map(lambda symbol: profile.get(symbol, {}).get("signals", 0))
    gated_df["Live_Expectancy_R"] = gated_df["Symbol"].map(lambda symbol: profile.get(symbol, {}).get("live_expectancy_r", np.nan))
    gated_df["Live_Signals"] = gated_df["Symbol"].map(lambda symbol: profile.get(symbol, {}).get("live_signals", 0))
    focus_mask = gated_df["Symbol"].isin(FOCUS_SYMBOLS)
    gated_df.loc[focus_mask & gated_df["Historical_Status"].isin(["AVOID", "UNVALIDATED"]), "Historical_Status"] = "FOCUS"

    avoid_lock = gated_df["Historical_Status"].isin(["AVOID", "UNVALIDATED"]) & gated_df["Direction"].isin(["BUY", "SELL"])
    watch_projected_lock = (
        (gated_df["Historical_Status"] == "WATCH_ONLY")
        & (gated_df.get("Signal_Type", "") == "PROJECTED")
        & (gated_df["Confidence"] < WATCH_ONLY_CONFIDENCE_FLOOR)
    )

    gated_df.loc[avoid_lock, "Trade_Allowed"] = False
    gated_df.loc[avoid_lock, "Dynamic_Lot"] = 0.0
    gated_df.loc[avoid_lock, "Risk_Mode"] = "PROFILE_LOCK"
    gated_df.loc[avoid_lock, "Action_Signal"] = "WATCH HISTORIS"
    gated_df.loc[avoid_lock, "Risk_Note"] = "Pair historis negatif/belum tervalidasi; tidak masuk TOP eksekusi."

    gated_df.loc[watch_projected_lock, "Trade_Allowed"] = False
    gated_df.loc[watch_projected_lock, "Dynamic_Lot"] = 0.0
    gated_df.loc[watch_projected_lock, "Risk_Mode"] = "PROFILE_LOCK"
    gated_df.loc[watch_projected_lock, "Action_Signal"] = "WATCH HISTORIS"
    gated_df.loc[watch_projected_lock, "Risk_Note"] = "Pair watch-only butuh confidence lebih tinggi untuk proyeksi."

    return gated_df


def current_market_session_label(now=None):
    """Simple liquidity session hint based on UTC hour."""
    now = now or datetime.now(timezone.utc)
    hour = now.hour
    if 6 <= hour < 12:
        return "LONDON"
    if 12 <= hour < 17:
        return "LONDON_NY_OVERLAP"
    if 17 <= hour < 21:
        return "NEW_YORK"
    return "THIN_SESSION"


def calculate_accuracy_quality_score(row):
    """Blend ZF geometry with historical/live evidence into a single quality score."""
    confidence = float(row.get("Confidence", 0) or 0)
    maturity = float(row.get("Setup_Maturity", 0) or 0)
    zf_score = float(row.get("ZF_Score", 0) or 0)
    rr_ratio = float(row.get("RR_Ratio", 0) or 0)
    if pd.isna(rr_ratio):
        rr_ratio = 1.0
    spread = float(row.get("Spread_Pips", 0) or 0)
    slippage = float(row.get("Slippage_Est_Pips", 0) or 0)
    historical_win = row.get("Historical_Win_Rate", np.nan)
    historical_expectancy = row.get("Historical_Expectancy_R", np.nan)
    live_expectancy = row.get("Live_Expectancy_R", np.nan)
    signal_type = row.get("Signal_Type", "NEUTRAL")

    history_component = 42.0 if pd.isna(historical_win) else float(historical_win)
    expectancy_component = 50.0 if pd.isna(historical_expectancy) else np.clip(50 + float(historical_expectancy) * 120, 0, 100)
    live_component = 50.0 if pd.isna(live_expectancy) else np.clip(50 + float(live_expectancy) * 120, 0, 100)
    rr_component = np.clip((rr_ratio / 1.8) * 100, 0, 100)
    maturity_component = np.clip(maturity * 100, 0, 100)
    zf_component = np.clip(zf_score * 100, 0, 100)
    cost_penalty = np.clip((spread * 4.0) + (slippage * 5.0), 0, 30)
    projected_penalty = 4.0 if signal_type == "PROJECTED" else 0.0

    score = (
        confidence * 0.23
        + maturity_component * 0.18
        + history_component * 0.20
        + expectancy_component * 0.13
        + live_component * 0.10
        + rr_component * 0.10
        + zf_component * 0.06
        - cost_penalty
        - projected_penalty
    )
    return float(round(np.clip(score, 0, 100), 2))


def apply_accuracy_quality_gate(risk_df):
    """Hold weak directional signals so TOP BUY/SELL favors proven patterns."""
    if risk_df.empty:
        gated_df = risk_df.copy()
        gated_df["Accuracy_Quality_Score"] = []
        gated_df["Accuracy_Gate"] = "NO_DATA"
        gated_df["Accuracy_Gate_Reason"] = ""
        gated_df["Market_Session"] = current_market_session_label()
        return gated_df

    gated_df = risk_df.copy()
    market_session = current_market_session_label()
    gated_df["Market_Session"] = market_session
    gated_df["Accuracy_Quality_Score"] = gated_df.apply(calculate_accuracy_quality_score, axis=1)
    gated_df["Accuracy_Gate"] = "PASS"
    gated_df["Accuracy_Gate_Reason"] = ""

    if not STRICT_ACCURACY_MODE:
        gated_df["User_Recommendation"] = gated_df.apply(build_user_recommendation, axis=1)
        return gated_df

    for idx, row in gated_df.iterrows():
        direction = row.get("Direction", "NEUTRAL")
        if direction not in ("BUY", "SELL"):
            gated_df.at[idx, "Accuracy_Gate"] = "NEUTRAL"
            gated_df.at[idx, "Accuracy_Gate_Reason"] = "Belum ada arah BUY/SELL matang."
            continue

        reasons = []
        signal_type = row.get("Signal_Type", "NEUTRAL")
        quality = float(row.get("Accuracy_Quality_Score", 0) or 0)
        historical_status = row.get("Historical_Status", "LEARNING")
        historical_win = row.get("Historical_Win_Rate", np.nan)
        historical_expectancy = row.get("Historical_Expectancy_R", np.nan)
        live_expectancy = row.get("Live_Expectancy_R", np.nan)
        maturity = float(row.get("Setup_Maturity", 0) or 0)
        rr_ratio = float(row.get("RR_Ratio", 0) or 0)

        if quality < STRICT_MIN_QUALITY_SCORE:
            reasons.append(f"quality {quality:.1f} < {STRICT_MIN_QUALITY_SCORE}")
        if historical_status in ("AVOID", "UNVALIDATED") and "Historical_Status" in gated_df.columns:
            reasons.append(f"status historis {historical_status}")
        if pd.notna(historical_win) and historical_win < STRICT_MIN_HISTORICAL_WIN_RATE:
            reasons.append(f"winrate historis {float(historical_win):.2f}% < {STRICT_MIN_HISTORICAL_WIN_RATE:.2f}%")
        if pd.notna(historical_expectancy) and historical_expectancy < STRICT_MIN_HISTORICAL_EXPECTANCY_R:
            reasons.append(f"expectancy historis {float(historical_expectancy):.4f}R < {STRICT_MIN_HISTORICAL_EXPECTANCY_R:.4f}R")
        if pd.notna(live_expectancy) and live_expectancy < STRICT_MIN_LIVE_EXPECTANCY_R:
            reasons.append(f"expectancy live {float(live_expectancy):.4f}R masih negatif")
        if signal_type == "PROJECTED" and maturity < STRICT_MIN_PROJECTED_MATURITY:
            reasons.append(f"maturity proyeksi {maturity:.2f} < {STRICT_MIN_PROJECTED_MATURITY:.2f}")
        if signal_type == "PROJECTED" and rr_ratio < STRICT_MIN_PROJECTED_RR:
            reasons.append(f"RR proyeksi {rr_ratio:.2f} < {STRICT_MIN_PROJECTED_RR:.2f}")
        if signal_type == "STRICT" and rr_ratio < STRICT_MIN_STRICT_RR:
            reasons.append(f"RR strict {rr_ratio:.2f} < {STRICT_MIN_STRICT_RR:.2f}")
        if market_session == "THIN_SESSION" and signal_type == "PROJECTED":
            reasons.append("sesi market tipis untuk sinyal proyeksi")

        if reasons and bool(row.get("Trade_Allowed", False)):
            gated_df.at[idx, "Trade_Allowed"] = False
            gated_df.at[idx, "Dynamic_Lot"] = 0.0
            gated_df.at[idx, "Risk_Mode"] = "ACCURACY_LOCK"
            gated_df.at[idx, "Action_Signal"] = "TUNGGU AKURASI"
            gated_df.at[idx, "Risk_Note"] = " | ".join(reasons)
            gated_df.at[idx, "Accuracy_Gate"] = "LOCKED"
            gated_df.at[idx, "Accuracy_Gate_Reason"] = " | ".join(reasons)
        elif reasons:
            gated_df.at[idx, "Accuracy_Gate"] = "WATCH"
            gated_df.at[idx, "Accuracy_Gate_Reason"] = " | ".join(reasons)

    gated_df["User_Recommendation"] = gated_df.apply(build_user_recommendation, axis=1)
    return gated_df


def summarize_empty_signal_reasons(risk_df, direction):
    if risk_df.empty:
        return ["Tidak ada data symbol yang berhasil dihitung."]

    directional_df = risk_df[risk_df["Direction"] == direction].copy()
    if directional_df.empty:
        mature_watch = risk_df.sort_values(by="Setup_Maturity", ascending=False).head(3)
        if mature_watch.empty:
            return [f"Belum ada kandidat {direction}; semua pair masih NEUTRAL."]
        preview = ", ".join(f"{row.Symbol} mat {row.Setup_Maturity:.2f}" for row in mature_watch.itertuples())
        return [f"Belum ada kandidat {direction}; setup terdekat: {preview}."]

    blocked = directional_df[~directional_df["Trade_Allowed"]]
    if blocked.empty:
        return [f"Ada kandidat {direction}, tetapi ranking belum masuk TOP."]

    counts = blocked["Risk_Mode"].value_counts().head(3).to_dict()
    reasons = [f"{mode}: {count} pair tertahan" for mode, count in counts.items()]
    locked_reasons = blocked.get("Accuracy_Gate_Reason", pd.Series(dtype=str)).dropna()
    locked_reasons = [reason for reason in locked_reasons.astype(str).tolist() if reason]
    if locked_reasons:
        reasons.append(f"Alasan utama: {locked_reasons[0]}")
    return reasons


def latest_validation_summary():
    if not VALIDATION_REPORT_DIR.exists():
        return None
    summaries = sorted(VALIDATION_REPORT_DIR.glob("zf_validation_summary_*.csv"), reverse=True)
    return summaries[0] if summaries else None


def auto_refresh_historical_validation(symbols):
    """Run historical validation from inside v20 when profile data is missing or stale."""
    if not AUTO_HISTORICAL_VALIDATION:
        return None, "DISABLED"
    if DATA_PROVIDER in ("OANDA", "YFINANCE"):
        return latest_validation_summary(), f"DISABLED_{DATA_PROVIDER}_PROVIDER"

    latest_summary = latest_validation_summary()
    if latest_summary:
        age_hours = (datetime.now().timestamp() - latest_summary.stat().st_mtime) / 3600
        coverage_status = "UNKNOWN"
        try:
            summary_df = pd.read_csv(latest_summary)
            covered_symbols = set(summary_df.get("Symbol", pd.Series(dtype=str)).dropna().astype(str))
            active_symbols = set(symbols)
            missing_symbols = active_symbols - covered_symbols
            coverage_status = f"coverage {len(covered_symbols & active_symbols)}/{len(active_symbols)}"
        except (OSError, pd.errors.EmptyDataError):
            missing_symbols = set(symbols)

        if age_hours < HISTORICAL_REFRESH_HOURS and not missing_symbols:
            return latest_summary, f"FRESH ({age_hours:.1f}h old)"
        if missing_symbols:
            print(f"[ZF LEARNING] Summary terbaru belum mencakup semua pair aktif ({coverage_status}). Validasi ulang semua pair.")

    try:
        from zf_historical_validator import attach_selection_score, configure_window_profile, timeframe_to_mt5, validate_symbol
    except Exception as exc:
        return latest_summary, f"IMPORT_FAILED: {exc}"

    print("[ZF LEARNING] Historical profile kosong/stale. Menjalankan validasi historis otomatis.")
    learning_timeframes = [item.strip().upper() for item in os.getenv("ZF_VALIDATION_TIMEFRAMES", "M30,H4,W1").split(",") if item.strip()]
    learning_exit_mode = os.getenv("ZF_VALIDATION_EXIT_MODE", "tp_only").strip().lower()
    learning_tp_pips = [TP_ONLY_TARGET_PIPS] if learning_exit_mode == "tp_only" else None
    learning_horizon = int(os.getenv("ZF_VALIDATION_HORIZON_BARS", "96" if learning_exit_mode == "tp_only" else str(HISTORICAL_HORIZON_BARS)))
    learning_zf_floor = float(os.getenv("ZF_VALIDATION_ZF_FLOOR", str(MIN_EXECUTION_ZF_SCORE)) or MIN_EXECUTION_ZF_SCORE)
    learning_fibo_filter = os.getenv("ZF_VALIDATION_FIBO_FILTER", "1" if USE_FIBO_FILTER else "0").strip().lower() not in ("0", "false", "no")
    learning_trailing = os.getenv("ZF_VALIDATION_TRAILING", "1").strip().lower() not in ("0", "false", "no")
    print(
        f"[ZF LEARNING] Lookback={HISTORICAL_LOOKBACK_DAYS} hari, "
        f"timeframes={','.join(learning_timeframes)}, exit={learning_exit_mode}, horizon={learning_horizon} candle, "
        f"zf_floor={learning_zf_floor:g}, fibo={learning_fibo_filter}, trailing={learning_trailing}."
    )

    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=HISTORICAL_LOOKBACK_DAYS)
    all_trades = []
    summaries = []
    grid_floors = WEEKLY_ZF_FLOORS if WEEKLY_GRID_OPTIMIZER_ENABLED else [learning_zf_floor]
    grid_trailing = WEEKLY_TRAILING_OPTIONS if WEEKLY_GRID_OPTIMIZER_ENABLED else [learning_trailing]

    for timeframe_name in learning_timeframes:
        try:
            normalized_tf, mt5_timeframe = timeframe_to_mt5(timeframe_name)
            _, _, warmup_bars = configure_window_profile("auto", normalized_tf, HISTORICAL_LOOKBACK_DAYS)
        except Exception as exc:
            print(f"  SKIP {timeframe_name}: {exc}")
            continue

        for symbol in symbols:
            candidates = []
            for candidate_floor in grid_floors:
                for candidate_trailing in grid_trailing:
                    trades, summary = validate_symbol(
                        symbol,
                        start_dt,
                        end_dt,
                        learning_horizon,
                        timeframe_name=normalized_tf,
                        mt5_timeframe=mt5_timeframe,
                        warmup_bars=warmup_bars,
                        exit_mode=learning_exit_mode,
                        tp_only_pips=learning_tp_pips,
                        zf_floor=candidate_floor,
                        fibo_filter=learning_fibo_filter,
                        use_trailing=candidate_trailing,
                    )
                    summary["Optimizer_ZF_Floor"] = candidate_floor
                    summary["Optimizer_Fibo_Filter"] = learning_fibo_filter
                    summary["Optimizer_Trailing"] = candidate_trailing
                    scored = attach_selection_score(pd.DataFrame([summary])).iloc[0].to_dict()
                    candidates.append((float(scored.get("Selection_Score", 0.0) or 0.0), trades, scored))

            _, best_trades, best_summary = max(
                candidates,
                key=lambda item: (
                    item[0],
                    float(item[2].get("Expectancy_R", 0.0) or 0.0),
                    float(item[2].get("Win_Rate_Resolved", 0.0) or 0.0),
                    int(item[2].get("Signals", 0) or 0),
                ),
            )
            all_trades.extend(best_trades)
            summaries.append(best_summary)
            print(
                f"  {symbol:<10} tf={normalized_tf:<3} signals={best_summary.get('Signals', 0)} "
                f"win_resolved={best_summary.get('Win_Rate_Resolved', 0)} "
                f"expectancy={best_summary.get('Expectancy_R', 0)} "
                f"best_zf={best_summary.get('Optimizer_ZF_Floor')} "
                f"trailing={best_summary.get('Optimizer_Trailing')}"
            )

    VALIDATION_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_path = VALIDATION_REPORT_DIR / f"zf_validation_summary_{stamp}.csv"
    trades_path = VALIDATION_REPORT_DIR / f"zf_validation_trades_{stamp}.csv"
    summary_df = attach_selection_score(pd.DataFrame(summaries))
    summary_df = summary_df.sort_values(
        by=["Selection_Score", "Win_Rate_Resolved", "Expectancy_R", "Signals"],
        ascending=[False, False, False, False],
        na_position="last",
    )
    summary_df.to_csv(summary_path, index=False)
    pd.DataFrame(all_trades).to_csv(trades_path, index=False)

    return summary_path, "REFRESHED"


def load_open_signals():
    if not OPEN_SIGNALS_PATH.exists():
        return []
    try:
        return json.loads(OPEN_SIGNALS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def save_open_signals(signals):
    LIVE_LEARNING_DIR.mkdir(parents=True, exist_ok=True)
    OPEN_SIGNALS_PATH.write_text(json.dumps(signals, ensure_ascii=True, indent=2, default=str), encoding="utf-8")


def append_closed_signals(closed_signals):
    if not closed_signals:
        return
    LIVE_LEARNING_DIR.mkdir(parents=True, exist_ok=True)
    closed_df = pd.DataFrame(closed_signals)
    if CLOSED_SIGNALS_PATH.exists():
        existing_df = pd.read_csv(CLOSED_SIGNALS_PATH)
        closed_df = pd.concat([existing_df, closed_df], ignore_index=True)
    closed_df.to_csv(CLOSED_SIGNALS_PATH, index=False)


def ea_signal_output_path():
    if mt5:
        try:
            info = mt5.terminal_info()
            common_path = getattr(info, "commondata_path", "") if info else ""
            if common_path:
                files_dir = Path(common_path) / "Files"
                files_dir.mkdir(parents=True, exist_ok=True)
                return files_dir / EA_SIGNAL_FILE_NAME
        except Exception:
            pass
    return BASE_DIR / EA_SIGNAL_FILE_NAME


def export_ea_signals(buy_pool, sell_pool):
    if not EXPORT_EA_SIGNALS:
        return None

    output_path = ea_signal_output_path()
    rows = []
    scan_time = datetime.now().astimezone()
    candidates = pd.concat([buy_pool, sell_pool], ignore_index=True) if len(buy_pool) or len(sell_pool) else pd.DataFrame()

    for _, row in candidates.iterrows():
        if row.get("Action_Signal") != "EKSEKUSI" or row.get("Direction") not in ("BUY", "SELL"):
            continue
        if pd.isna(row.get("SL_Price", np.nan)) or pd.isna(row.get("TP_Price", np.nan)):
            continue

        lot = float(row.get("Dynamic_Lot", 0.0) or 0.0)
        if lot <= 0:
            continue
        lot = min(lot, EA_MAX_LOT)

        signal_id = f"{row['Symbol']}_{row['Direction']}_{row.get('Timeframe', 'M30')}_{scan_time.strftime('%Y%m%d_%H%M')}"
        order_type = EA_BUY_ORDER_TYPE if row["Direction"] == "BUY" else EA_SELL_ORDER_TYPE
        rows.append(
            {
                "SignalId": signal_id,
                "ScanTime": scan_time.isoformat(),
                "ScanEpoch": int(scan_time.timestamp()),
                "ExpireMinutes": EA_SIGNAL_EXPIRE_MINUTES,
                "Symbol": row["Symbol"],
                "Direction": row["Direction"],
                "Action": row.get("Action_Signal", ""),
                "OrderType": order_type,
                "Lot": lot,
                "Entry": row.get("Entry_Price", np.nan),
                "SL": "" if pd.isna(row.get("SL_Price", np.nan)) else row.get("SL_Price"),
                "TP": "" if pd.isna(row.get("TP_Price", np.nan)) else row.get("TP_Price"),
                "TP_Pips": row.get("TP_Pips", ""),
                "Timeframe": row.get("Timeframe", "M30"),
                "ExitMode": row.get("Exit_Mode", "DYNAMIC_SL_TP"),
                "Confidence": row.get("Confidence", 0),
                "Quality": row.get("Accuracy_Quality_Score", 0),
                "Note": row.get("User_Recommendation", ""),
            }
        )

    fieldnames = [
        "SignalId",
        "ScanTime",
        "ScanEpoch",
        "ExpireMinutes",
        "Symbol",
        "Direction",
        "Action",
        "OrderType",
        "Lot",
        "Entry",
        "SL",
        "TP",
        "TP_Pips",
        "Timeframe",
        "ExitMode",
        "Confidence",
        "Quality",
        "Note",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)

    return output_path


def update_live_performance_summary():
    if not CLOSED_SIGNALS_PATH.exists():
        return pd.DataFrame()

    closed_df = pd.read_csv(CLOSED_SIGNALS_PATH)
    if closed_df.empty:
        return pd.DataFrame()

    grouped = []
    for symbol, group in closed_df.groupby("Symbol"):
        wins = int((group["Result"] == "WIN").sum())
        losses = int(group["Result"].isin(["LOSS", "LOSS_BOTH_HIT"]).sum())
        expired = int((group["Result"] == "EXPIRED").sum())
        resolved = wins + losses
        grouped.append(
            {
                "Symbol": symbol,
                "Signals": int(len(group)),
                "Wins": wins,
                "Losses": losses,
                "Expired": expired,
                "Win_Rate_Resolved": round(wins / resolved * 100, 2) if resolved else 0.0,
                "Expectancy_R": round(float(group["R_Result"].mean()), 4),
                "Avg_RR": round(float(group["RR_Ratio"].mean()), 2),
            }
        )

    summary_df = pd.DataFrame(grouped).sort_values(by="Expectancy_R", ascending=False)
    summary_df.to_csv(LIVE_SUMMARY_PATH, index=False)
    update_daily_learning_summary(closed_df)
    return summary_df


def sync_mt5_forward_results():
    """Import closed EA deals from MT5 demo history into live learning."""
    if not SYNC_MT5_FORWARD_RESULTS or using_oanda_provider() or using_yfinance_provider() or not mt5:
        return {"imported": 0, "status": "DISABLED"}

    end_time = datetime.now()
    start_time = end_time - timedelta(days=MT5_FORWARD_LOOKBACK_DAYS)
    try:
        deals = mt5.history_deals_get(start_time, end_time)
    except Exception as exc:
        return {"imported": 0, "status": f"ERROR: {exc}"}
    if deals is None:
        return {"imported": 0, "status": "NO_HISTORY"}

    existing_ids = set()
    if MT5_FORWARD_DEALS_PATH.exists():
        try:
            existing_df = pd.read_csv(MT5_FORWARD_DEALS_PATH)
            existing_ids = set(existing_df.get("Deal_Ticket", pd.Series(dtype=str)).astype(str))
        except (OSError, pd.errors.EmptyDataError):
            existing_ids = set()

    rows = []
    closed_signals = []
    deal_entry_out = getattr(mt5, "DEAL_ENTRY_OUT", 1)
    deal_entry_inout = getattr(mt5, "DEAL_ENTRY_INOUT", 2)
    for deal in deals:
        ticket = str(getattr(deal, "ticket", ""))
        if not ticket or ticket in existing_ids:
            continue
        if int(getattr(deal, "magic", 0) or 0) != EA_MAGIC_NUMBER:
            continue
        if int(getattr(deal, "entry", -1) or -1) not in (deal_entry_out, deal_entry_inout):
            continue

        symbol = str(getattr(deal, "symbol", ""))
        profit = float(getattr(deal, "profit", 0.0) or 0.0)
        swap = float(getattr(deal, "swap", 0.0) or 0.0)
        commission = float(getattr(deal, "commission", 0.0) or 0.0)
        net_profit = profit + swap + commission
        result = "WIN" if net_profit > 0 else "LOSS" if net_profit < 0 else "BREAKEVEN"
        deal_time = datetime.fromtimestamp(int(getattr(deal, "time", 0) or 0)).astimezone()
        row = {
            "Deal_Ticket": ticket,
            "Deal_Time": deal_time.isoformat(),
            "Symbol": symbol,
            "Volume": float(getattr(deal, "volume", 0.0) or 0.0),
            "Price": float(getattr(deal, "price", 0.0) or 0.0),
            "Profit": profit,
            "Swap": swap,
            "Commission": commission,
            "Net_Profit": net_profit,
            "Result": result,
            "Magic": int(getattr(deal, "magic", 0) or 0),
            "Comment": str(getattr(deal, "comment", "")),
        }
        rows.append(row)
        closed_signals.append(
            {
                "Signal_Id": f"MT5_DEAL_{ticket}",
                "Signal_Time": deal_time.isoformat(),
                "Symbol": symbol,
                "Timeframe": DEFAULT_SCAN_TIMEFRAME,
                "Exit_Mode": "FORWARD_DEMO",
                "Direction": "UNKNOWN",
                "Entry": np.nan,
                "SL_Pips": np.nan,
                "TP_Pips": np.nan,
                "SL_Price": np.nan,
                "TP_Price": np.nan,
                "RR_Ratio": 1.0,
                "Dynamic_Lot": float(getattr(deal, "volume", 0.0) or 0.0),
                "Confidence": np.nan,
                "Action_Signal": "FORWARD_DEMO",
                "Result": result,
                "R_Result": 1.0 if result == "WIN" else -1.0 if result == "LOSS" else 0.0,
                "Net_Profit": net_profit,
                "Signal_Type": "FORWARD_DEMO",
            }
        )

    if not rows:
        return {"imported": 0, "status": "NO_NEW_DEALS"}

    LIVE_LEARNING_DIR.mkdir(parents=True, exist_ok=True)
    forward_df = pd.DataFrame(rows)
    if MT5_FORWARD_DEALS_PATH.exists():
        try:
            existing_df = pd.read_csv(MT5_FORWARD_DEALS_PATH)
            forward_df = pd.concat([existing_df, forward_df], ignore_index=True)
        except (OSError, pd.errors.EmptyDataError):
            pass
    forward_df = forward_df.drop_duplicates(subset=["Deal_Ticket"], keep="last")
    forward_df.to_csv(MT5_FORWARD_DEALS_PATH, index=False)
    append_closed_signals(closed_signals)
    update_live_performance_summary()
    return {"imported": len(rows), "status": "IMPORTED"}


def update_daily_learning_summary(closed_df):
    if closed_df.empty or "Signal_Time" not in closed_df.columns:
        return pd.DataFrame()

    working_df = closed_df.copy()
    working_df["Signal_Date"] = pd.to_datetime(working_df["Signal_Time"], errors="coerce").dt.date
    if "Signal_Type" not in working_df.columns:
        working_df["Signal_Type"] = "UNKNOWN"
    else:
        working_df["Signal_Type"] = working_df["Signal_Type"].fillna("UNKNOWN")

    rows = []
    for (signal_date, signal_type), group in working_df.groupby(["Signal_Date", "Signal_Type"]):
        wins = int((group["Result"] == "WIN").sum())
        losses = int(group["Result"].isin(["LOSS", "LOSS_BOTH_HIT"]).sum())
        expired = int((group["Result"] == "EXPIRED").sum())
        resolved = wins + losses
        rows.append(
            {
                "Signal_Date": signal_date,
                "Signal_Type": signal_type,
                "Signals": int(len(group)),
                "Wins": wins,
                "Losses": losses,
                "Expired": expired,
                "Win_Rate_Resolved": round(wins / resolved * 100, 2) if resolved else 0.0,
                "Expectancy_R": round(float(group["R_Result"].mean()), 4),
                "Avg_RR": round(float(group["RR_Ratio"].mean()), 2),
            }
        )

    daily_df = pd.DataFrame(rows).sort_values(by=["Signal_Date", "Signal_Type"], ascending=[False, True])
    daily_df.to_csv(DAILY_LEARNING_SUMMARY_PATH, index=False)
    return daily_df


def get_projection_accuracy_summary():
    if not CLOSED_SIGNALS_PATH.exists():
        return None
    try:
        closed_df = pd.read_csv(CLOSED_SIGNALS_PATH)
    except (OSError, pd.errors.EmptyDataError):
        return None
    if closed_df.empty or "Signal_Type" not in closed_df.columns:
        return None

    projected_df = closed_df[closed_df["Signal_Type"] == "PROJECTED"]
    if projected_df.empty:
        return {
            "signals": 0,
            "wins": 0,
            "losses": 0,
            "expired": 0,
            "accuracy_resolved": 0.0,
            "accuracy_all": 0.0,
            "expectancy_r": 0.0,
        }

    wins = int((projected_df["Result"] == "WIN").sum())
    losses = int(projected_df["Result"].isin(["LOSS", "LOSS_BOTH_HIT"]).sum())
    expired = int((projected_df["Result"] == "EXPIRED").sum())
    resolved = wins + losses
    total = int(len(projected_df))
    return {
        "signals": total,
        "wins": wins,
        "losses": losses,
        "expired": expired,
        "accuracy_resolved": round(wins / resolved * 100, 2) if resolved else 0.0,
        "accuracy_all": round(wins / total * 100, 2) if total else 0.0,
        "expectancy_r": round(float(projected_df["R_Result"].mean()), 4) if "R_Result" in projected_df.columns else 0.0,
    }


def clamp_optimizer_value(key, value):
    low, high = OPTIMIZER_BOUNDS[key]
    return max(low, min(high, value))


def load_optimizer_state():
    if not OPTIMIZER_STATE_PATH.exists():
        return {"updated_at": None, "symbols": {}}
    try:
        return json.loads(OPTIMIZER_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"updated_at": None, "symbols": {}}


def save_optimizer_state(state):
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    OPTIMIZER_STATE_PATH.write_text(json.dumps(state, ensure_ascii=True, indent=2, default=str), encoding="utf-8")


def recent_loss_streak(group):
    streak = 0
    for result in reversed(group["Result"].tolist()):
        if result in ("LOSS", "LOSS_BOTH_HIT"):
            streak += 1
        elif result == "WIN":
            break
    return streak


def build_optimizer_params(mode):
    params = dict(OPTIMIZER_DEFAULTS)

    if mode == "COOLDOWN":
        params.update(
            {
                "atr_sl_multiplier": 1.65,
                "drift_sl_multiplier": 1.35,
                "atr_tp_multiplier": 2.10,
                "drift_tp_multiplier": 1.90,
                "min_reward_risk": 1.60,
                "max_spread_pips": 2.0,
                "max_slippage_pips": 1.25,
                "confidence_floor": 95,
                "projection_maturity_floor": 0.82,
                "projection_zf_floor": 0.70,
                "projection_confidence_floor": 88,
            }
        )
    elif mode == "DEFENSIVE":
        params.update(
            {
                "atr_sl_multiplier": 1.55,
                "drift_sl_multiplier": 1.30,
                "atr_tp_multiplier": 2.00,
                "drift_tp_multiplier": 1.80,
                "min_reward_risk": 1.50,
                "max_spread_pips": 2.2,
                "max_slippage_pips": 1.5,
                "confidence_floor": 72,
                "projection_maturity_floor": 0.74,
                "projection_zf_floor": 0.62,
                "projection_confidence_floor": 78,
            }
        )
    elif mode == "CAUTIOUS":
        params.update(
            {
                "atr_sl_multiplier": 1.45,
                "drift_sl_multiplier": 1.22,
                "atr_tp_multiplier": 1.90,
                "drift_tp_multiplier": 1.70,
                "min_reward_risk": 1.35,
                "max_spread_pips": 2.6,
                "max_slippage_pips": 1.8,
                "confidence_floor": 66,
                "projection_maturity_floor": 0.64,
                "projection_zf_floor": 0.52,
                "projection_confidence_floor": 68,
            }
        )
    elif mode == "EXPANSIVE":
        params.update(
            {
                "atr_sl_multiplier": 1.25,
                "drift_sl_multiplier": 1.05,
                "atr_tp_multiplier": 1.90,
                "drift_tp_multiplier": 1.75,
                "min_reward_risk": 1.20,
                "max_spread_pips": 3.5,
                "max_slippage_pips": 2.5,
                "confidence_floor": 55,
                "projection_maturity_floor": 0.50,
                "projection_zf_floor": 0.40,
                "projection_confidence_floor": 54,
            }
        )

    for key, value in list(params.items()):
        params[key] = clamp_optimizer_value(key, value)
    params["confidence_floor"] = int(params["confidence_floor"])
    return params


def run_self_healing_optimizer(force=False):
    """Bounded optimizer that adapts per-pair parameters from live closed signals."""
    state = load_optimizer_state()
    if not SELF_HEALING_OPTIMIZER:
        return state, "DISABLED"

    now = datetime.now().astimezone()
    updated_at = state.get("updated_at")
    if updated_at and not force:
        try:
            age_minutes = (now - datetime.fromisoformat(updated_at)).total_seconds() / 60
            if age_minutes < OPTIMIZER_REFRESH_MINUTES:
                return state, f"FRESH ({age_minutes:.1f}m old)"
        except ValueError:
            pass

    if not CLOSED_SIGNALS_PATH.exists():
        state["updated_at"] = now.isoformat()
        state.setdefault("symbols", {})
        save_optimizer_state(state)
        return state, "NO_LIVE_DATA"

    try:
        closed_df = pd.read_csv(CLOSED_SIGNALS_PATH)
    except (OSError, pd.errors.EmptyDataError):
        return state, "NO_LIVE_DATA"

    if closed_df.empty:
        return state, "NO_LIVE_DATA"

    symbols_state = state.setdefault("symbols", {})
    for symbol, group in closed_df.groupby("Symbol"):
        signal_count = int(len(group))
        wins = int((group["Result"] == "WIN").sum())
        losses = int(group["Result"].isin(["LOSS", "LOSS_BOTH_HIT"]).sum())
        resolved = wins + losses
        expectancy = float(group["R_Result"].mean()) if "R_Result" in group.columns else 0.0
        win_rate = (wins / resolved * 100) if resolved else 0.0
        rr_series = group["RR_Ratio"] if "RR_Ratio" in group.columns else pd.Series([1.0] * len(group))
        avg_rr = float(pd.to_numeric(rr_series, errors="coerce").dropna().mean()) if len(group) else 1.0
        if not np.isfinite(avg_rr) or avg_rr <= 0:
            avg_rr = 1.0
        loss_streak = recent_loss_streak(group)
        projected_group = group[group.get("Signal_Type", "") == "PROJECTED"] if "Signal_Type" in group.columns else pd.DataFrame()
        projected_signals = int(len(projected_group))
        projected_expectancy = float(projected_group["R_Result"].mean()) if projected_signals and "R_Result" in projected_group.columns else 0.0

        if signal_count < OPTIMIZER_MIN_LIVE_SIGNALS:
            mode = "LEARNING"
            params = dict(OPTIMIZER_DEFAULTS)
        elif projected_signals >= 10 and projected_expectancy <= -0.10:
            mode = "PROJECTION_DEFENSIVE"
            params = build_optimizer_params("DEFENSIVE")
            params["confidence_floor"] = max(params["confidence_floor"], 78)
            params["projection_maturity_floor"] = max(params["projection_maturity_floor"], 0.78)
            params["projection_zf_floor"] = max(params["projection_zf_floor"], 0.65)
            params["projection_confidence_floor"] = max(params["projection_confidence_floor"], 82)
        elif loss_streak >= 3:
            mode = "COOLDOWN"
            params = build_optimizer_params(mode)
        elif expectancy <= -0.15 or win_rate < 38:
            mode = "DEFENSIVE"
            params = build_optimizer_params(mode)
        elif expectancy < 0:
            mode = "CAUTIOUS"
            params = build_optimizer_params(mode)
        elif expectancy >= 0.10 and win_rate >= 45:
            mode = "EXPANSIVE"
            params = build_optimizer_params(mode)
        else:
            mode = "STABLE"
            params = build_optimizer_params(mode)

        symbols_state[symbol] = {
            "mode": mode,
            "updated_at": now.isoformat(),
            "signals": signal_count,
            "wins": wins,
            "losses": losses,
            "win_rate_resolved": round(win_rate, 2),
            "expectancy_r": round(expectancy, 4),
            "avg_rr": round(avg_rr, 4),
            "projected_signals": projected_signals,
            "projected_expectancy_r": round(projected_expectancy, 4),
            "loss_streak": loss_streak,
            "params": params,
        }

    state["updated_at"] = now.isoformat()
    state["bounds"] = OPTIMIZER_BOUNDS
    save_optimizer_state(state)
    return state, "REFRESHED"


def get_optimizer_params(symbol_name, optimizer_state):
    symbol_state = optimizer_state.get("symbols", {}).get(symbol_name, {}) if optimizer_state else {}
    params = dict(OPTIMIZER_DEFAULTS)
    params.update(symbol_state.get("params", {}))
    for key, value in list(params.items()):
        params[key] = clamp_optimizer_value(key, value)
    params["confidence_floor"] = int(params["confidence_floor"])
    return params, symbol_state.get("mode", "DEFAULT")


def fractional_kelly_multiplier(symbol_name, optimizer_state):
    """Return a bounded Kelly multiplier that can only reduce baseline risk."""
    if not FRACTIONAL_KELLY_ENABLED:
        return 1.0, 0.0

    symbol_state = optimizer_state.get("symbols", {}).get(symbol_name, {}) if optimizer_state else {}
    resolved = int(symbol_state.get("wins", 0) or 0) + int(symbol_state.get("losses", 0) or 0)
    if resolved < OPTIMIZER_MIN_LIVE_SIGNALS:
        return 0.50, 0.0

    probability = float(symbol_state.get("win_rate_resolved", 0.0) or 0.0) / 100.0
    reward_risk = max(float(symbol_state.get("avg_rr", 1.0) or 1.0), 0.01)
    full_kelly = ((reward_risk * probability) - (1.0 - probability)) / reward_risk
    fractional_kelly = max(full_kelly * FRACTIONAL_KELLY_FRACTION, 0.0)
    multiplier = float(np.clip(fractional_kelly, FRACTIONAL_KELLY_MIN_MULTIPLIER, 1.0))
    return multiplier, full_kelly


def evaluate_open_signal(signal):
    symbol = signal["Symbol"]
    direction = signal["Direction"]
    signal_time = datetime.fromisoformat(signal["Signal_Time"]).replace(tzinfo=None)
    now = datetime.now()
    signal_timeframe = normalize_timeframe_name(signal.get("Timeframe", "M30"))
    rates = data_copy_rates_range(symbol, timeframe_value(signal_timeframe), signal_time, now)
    if rates is None or len(rates) < 2:
        return None

    df = pd.DataFrame(rates)
    exit_mode = str(signal.get("Exit_Mode", "DYNAMIC_SL_TP")).lower()
    sl_price = float(signal.get("SL_Price", np.nan) or np.nan)
    tp_price = float(signal["TP_Price"])

    for idx in range(1, len(df)):
        high = float(df.loc[idx, "high"])
        low = float(df.loc[idx, "low"])
        if direction == "BUY":
            hit_sl = False if exit_mode == "tp_only" or pd.isna(sl_price) else low <= sl_price
            hit_tp = high >= tp_price
        else:
            hit_sl = False if exit_mode == "tp_only" or pd.isna(sl_price) else high >= sl_price
            hit_tp = low <= tp_price

        if hit_sl and hit_tp:
            return "LOSS_BOTH_HIT", idx
        if hit_sl:
            return "LOSS", idx
        if hit_tp:
            return "WIN", idx

    elapsed_bars = len(df) - 1
    horizon = TP_ONLY_LIVE_HORIZON_BARS if exit_mode == "tp_only" else LIVE_SIGNAL_HORIZON_BARS
    if elapsed_bars >= horizon:
        return "EXPIRED", elapsed_bars
    return None


def update_live_signal_tracker(buy_pool, sell_pool, scan_context=None):
    """Track live scanner signals and evaluate TP/SL over later M30 candles."""
    scan_context = scan_context or {}
    open_signals = load_open_signals()
    still_open = []
    closed = []

    for signal in open_signals:
        result = evaluate_open_signal(signal)
        if result is None:
            still_open.append(signal)
            continue

        outcome, bars_to_result = result
        rr_ratio = float(signal.get("RR_Ratio", 0.0) or 0.0)
        exit_mode = str(signal.get("Exit_Mode", "DYNAMIC_SL_TP") or "DYNAMIC_SL_TP").lower()
        if exit_mode == "tp_only":
            r_result = 1 if outcome == "WIN" else 0
        else:
            r_result = rr_ratio if outcome == "WIN" else -1 if outcome in ("LOSS", "LOSS_BOTH_HIT") else 0
        closed_signal = dict(signal)
        closed_signal.update(
            {
                "Close_Time": datetime.now().astimezone().isoformat(),
                "Result": outcome,
                "Bars_To_Result": bars_to_result,
                "R_Result": round(r_result, 3),
            }
        )
        closed.append(closed_signal)

    existing_keys = {(sig["Symbol"], sig["Direction"]) for sig in still_open}
    new_count = 0
    candidates = pd.concat([buy_pool, sell_pool], ignore_index=True) if len(buy_pool) or len(sell_pool) else pd.DataFrame()
    for _, row in candidates.iterrows():
        key = (row["Symbol"], row["Direction"])
        if key in existing_keys:
            continue

        entry = float(row["Close"])
        symbol_info = data_symbol_info(row["Symbol"])
        exit_mode = str(row.get("Exit_Mode", "DYNAMIC_SL_TP") or "DYNAMIC_SL_TP").lower()
        sl_pips = float(row["SL_Pips"]) if pd.notna(row.get("SL_Pips", np.nan)) else np.nan
        sl_distance = pips_to_price(sl_pips, symbol_info)
        tp_distance = pips_to_price(float(row["TP_Pips"]), symbol_info)
        if (exit_mode != "tp_only" and pd.isna(sl_distance)) or pd.isna(tp_distance):
            continue

        if row["Direction"] == "BUY":
            sl_price = np.nan if exit_mode == "tp_only" else entry - sl_distance
            tp_price = entry + tp_distance
        else:
            sl_price = np.nan if exit_mode == "tp_only" else entry + sl_distance
            tp_price = entry - tp_distance

        rr_ratio = 0.0 if exit_mode == "tp_only" or pd.isna(row.get("RR_Ratio", np.nan)) else float(row["RR_Ratio"])

        still_open.append(
            {
                "Signal_Id": f"{row['Symbol']}_{row['Direction']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                "Signal_Time": datetime.now().astimezone().isoformat(),
                "Symbol": row["Symbol"],
                "Timeframe": row.get("Timeframe", "M30"),
                "Exit_Mode": row.get("Exit_Mode", "DYNAMIC_SL_TP"),
                "Direction": row["Direction"],
                "Entry": entry,
                "SL_Pips": sl_pips,
                "TP_Pips": float(row["TP_Pips"]),
                "SL_Price": sl_price,
                "TP_Price": tp_price,
                "RR_Ratio": rr_ratio,
                "Dynamic_Lot": float(row["Dynamic_Lot"]),
                "Confidence": int(row["Confidence"]),
                "Action_Signal": row.get("Action_Signal", ""),
                "Signal_Type": row.get("Signal_Type", "UNKNOWN"),
                "Setup_Maturity": float(row.get("Setup_Maturity", 0.0) or 0.0),
                "Projection_Score": float(row.get("Projection_Score", 0.0) or 0.0),
                "Accuracy_Quality_Score": float(row.get("Accuracy_Quality_Score", 0.0) or 0.0),
                "Accuracy_Gate": row.get("Accuracy_Gate", ""),
                "Liquidity_Status": row.get("Liquidity_Status", ""),
                "Spread_Pips": float(row.get("Spread_Pips", 0.0) or 0.0),
                "Slippage_Est_Pips": float(row.get("Slippage_Est_Pips", 0.0) or 0.0),
                "Optimizer_Mode": row.get("Optimizer_Mode", ""),
                "Historical_Status": row.get("Historical_Status", ""),
                "ZF_Score": float(row["ZF_Score"]),
                "Drift": float(row["Drift"]),
                "News_Risk": scan_context.get("news_status", ""),
                "DXY": scan_context.get("macro", {}).get("DXY", 0.0),
                "US10Y": scan_context.get("macro", {}).get("US10Y", 0.0),
                "GOLD": scan_context.get("macro", {}).get("GOLD", 0.0),
            }
        )
        existing_keys.add(key)
        new_count += 1

    save_open_signals(still_open)
    append_closed_signals(closed)
    live_summary_df = update_live_performance_summary()

    return {
        "opened": new_count,
        "closed": len(closed),
        "open": len(still_open),
        "live_summary": live_summary_df,
    }


def build_memory_cross_check(master_df, previous_payload):
    """Compare current scan against the previous Archival Vault snapshot."""
    if master_df.empty:
        enriched_df = master_df.copy()
        for col, default in {
            "Previous_Direction": "",
            "Previous_Drift": np.nan,
            "Previous_ZF_Score": np.nan,
            "Delta_Drift": np.nan,
            "Delta_ZF_Score": np.nan,
            "Delta_Lambda": np.nan,
            "Direction_Changed": False,
            "Memory_Status": "NO_DATA",
        }.items():
            enriched_df[col] = default
        return enriched_df, pd.DataFrame()

    enriched_df = master_df.copy()
    if not previous_payload or not previous_payload.get("results"):
        enriched_df["Previous_Direction"] = ""
        enriched_df["Previous_Drift"] = np.nan
        enriched_df["Previous_ZF_Score"] = np.nan
        enriched_df["Delta_Drift"] = np.nan
        enriched_df["Delta_ZF_Score"] = np.nan
        enriched_df["Direction_Changed"] = False
        enriched_df["Memory_Status"] = "NO_MEMORY"
        return enriched_df, pd.DataFrame()

    previous_df = pd.DataFrame(previous_payload["results"])
    required_cols = {"Symbol", "Direction", "Drift", "ZF_Score"}
    if not required_cols.issubset(previous_df.columns):
        enriched_df["Memory_Status"] = "MEMORY_INCOMPLETE"
        return enriched_df, pd.DataFrame()

    optional_cols = [col for col in ["Lambda_Liquidity", "Liquidity_Status"] if col in previous_df.columns]
    previous_df = previous_df[["Symbol", "Direction", "Drift", "ZF_Score"] + optional_cols].rename(
        columns={
            "Direction": "Previous_Direction",
            "Drift": "Previous_Drift",
            "ZF_Score": "Previous_ZF_Score",
            "Lambda_Liquidity": "Previous_Lambda_Liquidity",
            "Liquidity_Status": "Previous_Liquidity_Status",
        }
    )

    enriched_df = enriched_df.merge(previous_df, on="Symbol", how="left")
    enriched_df["Previous_Drift"] = pd.to_numeric(enriched_df["Previous_Drift"], errors="coerce")
    enriched_df["Previous_ZF_Score"] = pd.to_numeric(enriched_df["Previous_ZF_Score"], errors="coerce")
    if "Previous_Lambda_Liquidity" not in enriched_df.columns:
        enriched_df["Previous_Lambda_Liquidity"] = np.nan
    if "Previous_Liquidity_Status" not in enriched_df.columns:
        enriched_df["Previous_Liquidity_Status"] = ""
    enriched_df["Previous_Lambda_Liquidity"] = pd.to_numeric(enriched_df["Previous_Lambda_Liquidity"], errors="coerce")
    enriched_df["Delta_Drift"] = enriched_df["Drift"] - enriched_df["Previous_Drift"]
    enriched_df["Delta_ZF_Score"] = enriched_df["ZF_Score"] - enriched_df["Previous_ZF_Score"]
    enriched_df["Delta_Lambda"] = enriched_df["Lambda_Liquidity"] - enriched_df["Previous_Lambda_Liquidity"]
    enriched_df.loc[enriched_df["Previous_Lambda_Liquidity"].isna(), "Delta_Lambda"] = 0.0
    enriched_df["Direction_Changed"] = (
        enriched_df["Previous_Direction"].notna()
        & (enriched_df["Previous_Direction"] != "")
        & (enriched_df["Direction"] != enriched_df["Previous_Direction"])
    )
    enriched_df["Liquidity_Status_Changed"] = (
        enriched_df["Previous_Liquidity_Status"].notna()
        & (enriched_df["Previous_Liquidity_Status"] != "")
        & (enriched_df["Liquidity_Status"] != enriched_df["Previous_Liquidity_Status"])
    )

    zf_alert = enriched_df["Delta_ZF_Score"].abs() >= ZF_DELTA_ALERT
    drift_alert = enriched_df["Delta_Drift"].abs() >= DRIFT_DELTA_ALERT
    lambda_alert = enriched_df["Delta_Lambda"].abs() >= 0.50
    liquidity_alert = enriched_df["Liquidity_Status_Changed"] & enriched_df["Liquidity_Status"].isin(["STRESSED", "VOID"])
    directional_signal = enriched_df["Direction"].isin(["BUY", "SELL"]) | enriched_df["Previous_Direction"].isin(["BUY", "SELL"])
    structural_resonance = (
        (enriched_df["Drift"] >= DRIFT_WATCH_FLOOR)
        | enriched_df["Liquidity_Status"].isin(["STRESSED", "VOID"])
        | directional_signal
    )
    direction_alert = enriched_df["Direction_Changed"] & directional_signal

    critical_alert = (
        (enriched_df["ZF_Score"] >= ZF_CRITICAL_FLOOR)
        & (zf_alert | drift_alert | direction_alert | lambda_alert | liquidity_alert)
        & structural_resonance
    )
    mismatch_alert = (
        (zf_alert | drift_alert | direction_alert | lambda_alert | liquidity_alert)
        & structural_resonance
        & ~critical_alert
    )

    enriched_df["Memory_Status"] = np.select(
        [critical_alert, mismatch_alert, enriched_df["Previous_ZF_Score"].isna(), zf_alert | drift_alert | lambda_alert],
        ["CRITICAL_MISMATCH", "RESONANCE_MISMATCH", "NEW_SYMBOL", "WATCH"],
        default="LAMINAR",
    )

    mismatch_df = enriched_df[enriched_df["Memory_Status"].isin(["CRITICAL_MISMATCH", "RESONANCE_MISMATCH"])].copy()
    if not mismatch_df.empty:
        mismatch_df["Mismatch_Rank"] = mismatch_df[["Delta_ZF_Score", "Delta_Drift", "Delta_Lambda"]].abs().max(axis=1)
        mismatch_df = mismatch_df.sort_values(by="Mismatch_Rank", ascending=False).head(TOP_MISMATCH)

    return enriched_df, mismatch_df


def apply_risk_controls(memory_df, news_status):
    """Apply Bab 6 risk gates without sending live trade orders."""
    if memory_df.empty:
        risk_df = memory_df.copy()
        for col, default in {
            "Risk_Mode": "NORMAL",
            "Trade_Allowed": False,
            "Action_Signal": "STANDBY",
            "Risk_Note": "",
        }.items():
            risk_df[col] = default
        return risk_df

    risk_df = memory_df.copy()
    high_news_risk = "HIGH RISK" in str(news_status).upper()
    critical_memory = risk_df.get("Memory_Status", "") == "CRITICAL_MISMATCH"

    actionable = risk_df["Direction"].isin(["BUY", "SELL"])
    circuit_confirmation = (
        (risk_df["Drift"] >= DRIFT_WATCH_FLOOR)
        | risk_df["Liquidity_Status"].isin(["STRESSED", "VOID"])
        | actionable
    )
    circuit_breaker = (risk_df["ZF_Score"] >= ZF_CIRCUIT_BREAKER) & circuit_confirmation
    cold_mode = high_news_risk & (risk_df["ZF_Score"] >= ZF_COLD_MODE_FLOOR)
    memory_lock = critical_memory & risk_df["Direction"].isin(["BUY", "SELL"])
    max_spread_limit = risk_df.get("Optimizer_Max_Spread_Pips", MAX_SPREAD_PIPS)
    max_slippage_limit = risk_df.get("Optimizer_Max_Slippage_Pips", MAX_SLIPPAGE_PIPS)
    confidence_floor = risk_df.get("Optimizer_Confidence_Floor", 0)
    liquidity_lock = risk_df["Liquidity_Void"] | (risk_df["Spread_Pips"] > max_spread_limit)
    slippage_lock = risk_df["Slippage_Est_Pips"] > max_slippage_limit
    optimizer_confidence_lock = risk_df["Direction"].isin(["BUY", "SELL"]) & (risk_df["Confidence"] < confidence_floor)
    adverse_depth_lock = (
        risk_df["Depth_Available"]
        & (
            ((risk_df["Direction"] == "BUY") & (risk_df["Depth_Imbalance"] <= -DEPTH_IMBALANCE_ALERT))
            | ((risk_df["Direction"] == "SELL") & (risk_df["Depth_Imbalance"] >= DEPTH_IMBALANCE_ALERT))
        )
    )
    risk_df["Risk_Mode"] = np.select(
        [circuit_breaker, cold_mode, memory_lock, liquidity_lock, slippage_lock, adverse_depth_lock, optimizer_confidence_lock],
        ["CIRCUIT_BREAKER", "COLD_MODE", "MEMORY_LOCK", "LIQUIDITY_LOCK", "SLIPPAGE_LOCK", "DEPTH_LOCK", "OPTIMIZER_LOCK"],
        default="NORMAL",
    )
    risk_df["Trade_Allowed"] = actionable & (risk_df["Risk_Mode"] == "NORMAL")
    projected_trade = risk_df["Trade_Allowed"] & (risk_df.get("Signal_Type", "") == "PROJECTED")
    risk_df["Action_Signal"] = np.select(
        [
            circuit_breaker,
            cold_mode,
            memory_lock,
            liquidity_lock,
            slippage_lock,
            adverse_depth_lock,
            optimizer_confidence_lock,
            projected_trade,
            risk_df["Trade_Allowed"],
            risk_df["Memory_Status"].isin(["RESONANCE_MISMATCH", "WATCH"]),
        ],
        [
            "PERTAHANAN SISTEMIK",
            "MODE DINGIN",
            "VALIDASI ULANG",
            "PERTAHANAN LIKUIDITAS",
            "TUNGGU SLIPPAGE",
            "DEPTH TIDAK SELARAS",
            "OPTIMIZER MENAHAN",
            "PROYEKSI 30M",
            "EKSEKUSI",
            "WASPADA",
        ],
        default="STANDBY",
    )
    risk_df["Risk_Note"] = np.select(
        [circuit_breaker, cold_mode, memory_lock, liquidity_lock, slippage_lock, adverse_depth_lock, optimizer_confidence_lock],
        [
            "ZF-Score melewati circuit breaker; jangan eksekusi.",
            "High-impact news dan ZF tinggi; tunda eksekusi.",
            "Critical mismatch pada sinyal aktif; validasi ulang.",
            "Liquidity void atau spread terlalu lebar.",
            "Estimasi slippage melebihi batas.",
            "Depth imbalance berlawanan dengan arah sinyal.",
            "Confidence di bawah batas self-healing optimizer.",
        ],
        default="",
    )
    risk_df["Session_Phase"] = np.select(
        [
            risk_df["Risk_Mode"] == "CIRCUIT_BREAKER",
            risk_df["Liquidity_Status"] == "VOID",
            risk_df["Memory_Status"].isin(["CRITICAL_MISMATCH", "RESONANCE_MISMATCH"]),
            risk_df["Liquidity_Status"] == "STRESSED",
        ],
        ["FRACTURE", "ANOMALOUS", "ANOMALOUS", "STRESSED"],
        default="LAMINAR",
    )
    risk_df.loc[~risk_df["Trade_Allowed"], "Dynamic_Lot"] = 0.0
    risk_df["User_Recommendation"] = risk_df.apply(build_user_recommendation, axis=1)

    return risk_df


def build_user_recommendation(row):
    """Plain Indonesian guidance for non-technical users."""
    direction = row.get("Direction", "NEUTRAL")
    signal_type = row.get("Signal_Type", "NEUTRAL")
    risk_mode = row.get("Risk_Mode", "NORMAL")
    action = row.get("Action_Signal", "STANDBY")
    liquidity = row.get("Liquidity_Status", "-")
    confidence = int(row.get("Confidence", 0) or 0)
    historical_status = row.get("Historical_Status", "LEARNING")
    historical_win = row.get("Historical_Win_Rate", np.nan)
    live_expectancy = row.get("Live_Expectancy_R", np.nan)
    history_note = ""
    if pd.notna(historical_win):
        history_note = f" Akurasi historis resolved sekitar {float(historical_win):.2f}%."
    if pd.notna(live_expectancy):
        history_note += f" Expectancy live {float(live_expectancy):.4f}R."

    if risk_mode == "PROFILE_LOCK":
        return "Jangan entry. Pair ini belum lolos validasi historis."
    if risk_mode == "LIQUIDITY_LOCK":
        return "Jangan entry. Likuiditas/spread sedang tidak sehat."
    if risk_mode == "SLIPPAGE_LOCK":
        return "Jangan entry. Risiko slippage terlalu besar."
    if risk_mode == "DEPTH_LOCK":
        return "Jangan entry. Depth/order book tidak mendukung arah sinyal."
    if risk_mode == "COLD_MODE":
        return "Tunggu. Ada risiko berita besar, jangan terburu-buru."
    if risk_mode == "CIRCUIT_BREAKER":
        return "Stop trading sementara. Kondisi pasar ekstrem."
    if risk_mode == "OPTIMIZER_LOCK":
        return "Tunggu. Confidence belum cukup menurut optimizer."
    if risk_mode == "MEMORY_LOCK":
        return "Validasi ulang. Ada mismatch kuat dengan memori sebelumnya."
    if risk_mode == "ACCURACY_LOCK":
        reason = row.get("Accuracy_Gate_Reason", "")
        detail = f" Alasan: {reason}." if reason else ""
        return f"Jangan entry dulu. Sinyal ditahan oleh mode akurasi ketat.{detail}"

    if action == "PROYEKSI 30M" and direction in ("BUY", "SELL"):
        if historical_status in ("AVOID", "UNVALIDATED"):
            return f"Pantau saja {direction}. Ada proyeksi 30 menit, tetapi riwayat pair belum cukup kuat untuk entry agresif.{history_note}"
        if historical_status == "WATCH_ONLY":
            return f"Pantau {direction} dengan hati-hati. Pair historisnya watch-only, tunggu konfirmasi tambahan.{history_note}"
        if historical_status == "LEARNING":
            return f"Pantau {direction}. Mode provider API masih mengumpulkan bukti live, gunakan simulasi/lot kecil dulu.{history_note}"
        return f"Pantau {direction}. Ini proyeksi 30 menit, tunggu konfirmasi harga sebelum entry.{history_note}"
    if action == "EKSEKUSI" and direction in ("BUY", "SELL"):
        if historical_status == "AVOID":
            return f"Sinyal {direction} muncul, tetapi riwayat pair negatif. Entry tidak disarankan.{history_note}"
        if historical_status == "UNVALIDATED":
            return f"Sinyal {direction} muncul, tetapi pair belum tervalidasi historis. Gunakan simulasi/pantau dulu.{history_note}"
        if historical_status == "WATCH_ONLY":
            return f"Sinyal {direction} muncul, tetapi status watch-only. Gunakan lot kecil dan tunggu konfirmasi.{history_note}"
        if historical_status == "LEARNING":
            return f"Sinyal {direction} muncul. Mode provider API masih belajar dari hasil real, gunakan simulasi/lot kecil dulu.{history_note}"
        if signal_type == "STRICT":
            if str(row.get("Exit_Mode", "")).lower() == "tp_only":
                tp_pips = row.get("TP_Pips", TP_ONLY_TARGET_PIPS)
                tf = row.get("Timeframe", "H4")
                return f"Setup {direction} valid pada TF {tf}. Mode ini mengincar TP sekitar {tp_pips} pips tanpa SL; gunakan lot kecil dan pantau floating risk.{history_note}"
            return f"Setup {direction} valid. Entry manual boleh dipertimbangkan dengan SL/TP yang tampil.{history_note}"
        return f"Setup {direction} layak dipantau. Gunakan lot kecil jika belum ada konfirmasi tambahan.{history_note}"
    if action == "WASPADA":
        return f"Waspada. Ada tanda anomali, tetapi belum ada arah entry yang matang. Likuiditas: {liquidity}."
    if direction == "NEUTRAL":
        return "Tidak ada entry. Tunggu sinyal BUY/SELL berikutnya."

    return f"Tunggu. Sinyal {direction} belum cukup aman. Confidence {confidence}%."


def archive_scan_results(master_df, buy_pool, sell_pool, mismatch_df, macro, news_status, account_equity, previous_archive_path):
    """Persist each scan as the first Archival Vault layer for future cross-checks."""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    scan_time = datetime.now().astimezone()
    stamp = scan_time.strftime("%Y%m%d_%H%M%S")

    csv_path = ARCHIVE_DIR / f"zf_scan_{stamp}.csv"
    json_path = ARCHIVE_DIR / f"zf_scan_{stamp}.json"
    manifest_path = ARCHIVE_DIR / f"zf_scan_{stamp}.manifest.json"

    master_df.to_csv(csv_path, index=False)

    payload = {
        "scan_time": scan_time.isoformat(),
        "account_equity": account_equity,
        "news_status": news_status,
        "macro": macro,
        "summary": {
            "symbols_scanned": int(len(master_df)),
            "buy_candidates": int(len(buy_pool)),
            "sell_candidates": int(len(sell_pool)),
            "resonance_mismatches": int(len(mismatch_df)),
        },
        "previous_archive": str(previous_archive_path) if previous_archive_path else None,
        "top_buy": buy_pool.to_dict(orient="records"),
        "top_sell": sell_pool.to_dict(orient="records"),
        "resonance_mismatches": mismatch_df.to_dict(orient="records"),
        "results": master_df.to_dict(orient="records"),
    }

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=True, indent=2, default=str)

    manifest = {
        "created_at": scan_time.isoformat(),
        "retention_days": ARCHIVE_RETENTION_DAYS,
        "files": {
            csv_path.name: {
                "sha256": file_sha256(csv_path),
                "bytes": csv_path.stat().st_size,
            },
            json_path.name: {
                "sha256": file_sha256(json_path),
                "bytes": json_path.stat().st_size,
            },
        },
    }
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=True, indent=2)

    moved_to_cold = prune_archival_vault()

    return csv_path, json_path, manifest_path, moved_to_cold

def compute_currency_strength(mifx_symbols, symbol_timeframes=None):
    """Menghitung Matriks Kekuatan Mata Uang Absolut Secara Silang"""
    strength_map = {"USD": 0.0, "EUR": 0.0, "GBP": 0.0, "JPY": 0.0, "AUD": 0.0, "CAD": 0.0, "CHF": 0.0, "NZD": 0.0}
    counts = {"USD": 0, "EUR": 0, "GBP": 0, "JPY": 0, "AUD": 0, "CAD": 0, "CHF": 0, "NZD": 0}
    
    for sym in mifx_symbols:
        base = sym[:3].upper()
        quote = sym[3:6].upper()
        if base in strength_map and quote in strength_map:
            rates = data_copy_rates_from_pos(sym, timeframe_value((symbol_timeframes or {}).get(sym, DEFAULT_SCAN_TIMEFRAME)), 0, 20)
            if rates is not None and len(rates) > 0:
                close_prices = [r['close'] for r in rates]
                pct_change = (close_prices[-1] - close_prices[0]) / close_prices[0] * 100
                
                strength_map[base] += pct_change
                strength_map[quote] -= pct_change
                counts[base] += 1
                counts[quote] += 1
                
    for k in strength_map:
        if counts[k] > 0:
            strength_map[k] = strength_map[k] / counts[k]
            
    return strength_map


def symbol_pip_factor(symbol_info):
    """Convert MT5 points to common pip units for most FX symbols."""
    if symbol_info is None:
        return 10.0
    return 10.0 if symbol_info.digits in (3, 5) else 1.0


def safe_book_volume(entry):
    volume_real = float(getattr(entry, "volume_real", 0.0) or 0.0)
    volume = float(getattr(entry, "volume", 0.0) or 0.0)
    return volume_real if volume_real > 0 else volume


def fetch_market_microstructure(symbol_name):
    """Read provider tick, spread, and optional Depth of Market as Bab 3 inputs."""
    symbol_info = data_symbol_info(symbol_name)
    tick = data_symbol_info_tick(symbol_name)

    point = float(symbol_info.point) if symbol_info and symbol_info.point else 0.0
    pip_factor = symbol_pip_factor(symbol_info)
    bid = float(getattr(tick, "bid", 0.0) or 0.0) if tick else 0.0
    ask = float(getattr(tick, "ask", 0.0) or 0.0) if tick else 0.0
    mid_price = (bid + ask) / 2 if bid > 0 and ask > 0 else np.nan
    spread_points = ((ask - bid) / point) if point > 0 and ask > bid else np.nan
    spread_pips = spread_points / pip_factor if pd.notna(spread_points) else np.nan

    bid_depth = 0.0
    ask_depth = 0.0
    cluster_price = np.nan
    cluster_volume = 0.0
    depth_available = False

    try:
        book = data_market_book(symbol_name)
        if book:
            depth_available = True
            for entry in book:
                volume = safe_book_volume(entry)
                if volume > cluster_volume:
                    cluster_volume = volume
                    cluster_price = float(entry.price)

                if entry.type == BOOK_TYPE_BUY:
                    bid_depth += volume
                elif entry.type == BOOK_TYPE_SELL:
                    ask_depth += volume
    except Exception:
        depth_available = False

    total_depth = bid_depth + ask_depth
    depth_imbalance = ((bid_depth - ask_depth) / total_depth) if total_depth > 0 else 0.0
    depth_score = min(total_depth / 100.0, 1.0) if depth_available else 0.0
    spread_stress = min((spread_pips / SPREAD_STRESS_PIPS), 1.0) if pd.notna(spread_pips) else 1.0
    liquidity_stress = float(np.clip((spread_stress * 0.70) + ((1.0 - depth_score) * 0.30), 0, 1))
    lambda_liquidity = float(np.clip(0.10 + liquidity_stress + abs(depth_imbalance) * 0.50, 0.10, 2.50))

    liquidity_void = False
    if pd.notna(spread_pips) and spread_pips > MAX_SPREAD_PIPS:
        liquidity_void = True
    if depth_available and total_depth < MIN_DEPTH_VOLUME:
        liquidity_void = True

    return {
        "Bid": bid,
        "Ask": ask,
        "Mid_Price": mid_price,
        "Spread_Points": spread_points,
        "Spread_Pips": spread_pips,
        "Bid_Depth": bid_depth,
        "Ask_Depth": ask_depth,
        "Total_Depth": total_depth,
        "Depth_Imbalance": depth_imbalance,
        "Depth_Available": depth_available,
        "Liquidity_Cluster_Price": cluster_price,
        "Liquidity_Cluster_Volume": cluster_volume,
        "Liquidity_Stress": liquidity_stress,
        "Lambda_Liquidity": lambda_liquidity,
        "Liquidity_Void": liquidity_void,
    }


def estimate_slippage_pips(dynamic_lot, micro):
    """Estimate slippage from spread and available depth as a conservative guard."""
    spread_pips = micro.get("Spread_Pips", np.nan)
    base_slippage = spread_pips / 2 if pd.notna(spread_pips) else MAX_SLIPPAGE_PIPS
    total_depth = micro.get("Total_Depth", 0.0)

    if total_depth > 0:
        depth_penalty = min(dynamic_lot / max(total_depth, 0.01), 2.0)
    else:
        depth_penalty = 0.75

    return float(round(base_slippage * (1.0 + depth_penalty), 2))


def price_distance_to_pips(price_distance, symbol_info):
    """Convert a raw price distance to pips using the symbol point/digits."""
    if symbol_info is None or not getattr(symbol_info, "point", 0):
        return np.nan
    point = float(symbol_info.point)
    pip_factor = symbol_pip_factor(symbol_info)
    return float(price_distance / point / pip_factor)


def pips_to_price(pips, symbol_info):
    """Convert pips back to raw price distance using MT5 symbol point/digits."""
    if symbol_info is None or not getattr(symbol_info, "point", 0):
        return np.nan
    point = float(symbol_info.point)
    pip_factor = symbol_pip_factor(symbol_info)
    return float(pips * point * pip_factor)


def pips_to_points(pips, symbol_info):
    """Convert common pips to broker points for manual execution forms."""
    if symbol_info is None:
        return np.nan
    return float(pips * symbol_pip_factor(symbol_info))


def round_symbol_price(price, symbol_info):
    if pd.isna(price):
        return np.nan
    digits = int(getattr(symbol_info, "digits", 5) or 5) if symbol_info else 5
    return round(float(price), digits)


def fmt_value(value, decimals=2, suffix=""):
    if pd.isna(value):
        return "-"
    return f"{float(value):.{decimals}f}{suffix}"


def fmt_price(value):
    return "-" if pd.isna(value) else str(value)


def fmt_rr(value):
    return "-" if pd.isna(value) else f"{float(value):.2f}"


def calculate_dynamic_stop_loss_pips(symbol_name, last_row, micro, regime, optimizer_params=None):
    """Build SL from current volatility, drift, spread, slippage, and regime."""
    optimizer_params = optimizer_params or OPTIMIZER_DEFAULTS
    symbol_info = data_symbol_info(symbol_name)

    atr_pips = price_distance_to_pips(last_row.get("atr", np.nan), symbol_info)
    atr_sl = atr_pips * optimizer_params["atr_sl_multiplier"] if pd.notna(atr_pips) else np.nan

    drift_pips = price_distance_to_pips(abs(last_row.get("close", 0) - last_row.get("P_pure", 0)), symbol_info)
    drift_sl = drift_pips * optimizer_params["drift_sl_multiplier"] if pd.notna(drift_pips) else np.nan

    spread_pips = micro.get("Spread_Pips", np.nan)
    spread_buffer = spread_pips * 2.0 if pd.notna(spread_pips) else 0.0
    liquidity_buffer = micro.get("Liquidity_Stress", 0.0) * 10.0

    candidates = [
        value for value in [atr_sl, drift_sl, spread_buffer + liquidity_buffer]
        if pd.notna(value) and value > 0
    ]
    if not candidates:
        return DEFAULT_STOP_LOSS_PIPS, "FALLBACK"

    regime_multiplier = TREND_SL_MULTIPLIER if regime == "TREND" else RANGE_SL_MULTIPLIER
    dynamic_sl = max(candidates) * regime_multiplier
    dynamic_sl = max(dynamic_sl, spread_buffer + MAX_SLIPPAGE_PIPS)

    return float(round(dynamic_sl, 1)), "DATA_DRIVEN"


def calculate_dynamic_take_profit_pips(symbol_name, last_row, micro, regime, direction, stop_loss_pips, optimizer_params=None):
    """Build TP from expected resonance travel, ATR, liquidity clusters, and minimum RR."""
    optimizer_params = optimizer_params or OPTIMIZER_DEFAULTS
    if direction == "NEUTRAL":
        return 0.0, "NO_SIGNAL", 0.0

    symbol_info = data_symbol_info(symbol_name)
    close_price = last_row.get("close", 0.0)
    p_pure = last_row.get("P_pure", close_price)

    atr_pips = price_distance_to_pips(last_row.get("atr", np.nan), symbol_info)
    atr_tp = atr_pips * optimizer_params["atr_tp_multiplier"] if pd.notna(atr_pips) else np.nan

    resonance_distance_pips = price_distance_to_pips(abs(close_price - p_pure), symbol_info)
    resonance_tp = resonance_distance_pips * optimizer_params["drift_tp_multiplier"] if pd.notna(resonance_distance_pips) else np.nan

    cluster_tp = np.nan
    cluster_price = micro.get("Liquidity_Cluster_Price", np.nan)
    if pd.notna(cluster_price) and cluster_price > 0:
        if direction == "BUY" and cluster_price > close_price:
            cluster_tp = price_distance_to_pips(cluster_price - close_price, symbol_info)
        elif direction == "SELL" and cluster_price < close_price:
            cluster_tp = price_distance_to_pips(close_price - cluster_price, symbol_info)

    candidates = [
        value for value in [atr_tp, resonance_tp, cluster_tp]
        if pd.notna(value) and value > 0
    ]
    if not candidates:
        base_tp = stop_loss_pips * optimizer_params["min_reward_risk"]
        return float(round(base_tp, 1)), "RR_FALLBACK", float(round(base_tp / stop_loss_pips, 2)) if stop_loss_pips else 0.0

    regime_multiplier = TREND_TP_MULTIPLIER if regime == "TREND" else RANGE_TP_MULTIPLIER
    structure_tp = max(candidates) * regime_multiplier
    min_rr_tp = stop_loss_pips * optimizer_params["min_reward_risk"]
    dynamic_tp = max(structure_tp, min_rr_tp)

    if pd.notna(cluster_tp) and cluster_tp > 0 and cluster_tp < dynamic_tp:
        dynamic_tp = max(cluster_tp * 0.90, min_rr_tp)
        tp_model = "CLUSTER_CAPPED"
    else:
        tp_model = "DATA_DRIVEN"

    rr_ratio = dynamic_tp / stop_loss_pips if stop_loss_pips else 0.0
    return float(round(dynamic_tp, 1)), tp_model, float(round(rr_ratio, 2))


def project_next_m30_direction(df, optimizer_params=None):
    """Project the next M30 direction from recent ZF geometry, before strict trigger fires."""
    optimizer_params = optimizer_params or OPTIMIZER_DEFAULTS
    if len(df) < PROJECTION_LOOKBACK_BARS + 2:
        return "NEUTRAL", 0.0, 0.0, 0.0

    recent = df.tail(PROJECTION_LOOKBACK_BARS)
    last = df.iloc[-1]

    upper_span = max(float(last["Upper_Threshold"] - last["Integral_Mean"]), 1e-9)
    lower_span = max(float(last["Integral_Mean"] - last["Lower_Threshold"]), 1e-9)
    sell_maturity = float(np.clip((last["Decay_Integral"] - last["Integral_Mean"]) / upper_span, 0, 1.25))
    buy_maturity = float(np.clip((last["Integral_Mean"] - last["Decay_Integral"]) / lower_span, 0, 1.25))

    x = np.arange(len(recent))
    decay_slope = float(np.polyfit(x, recent["Decay_Integral"].astype(float), 1)[0])
    price_slope = float(np.polyfit(x, recent["close"].astype(float), 1)[0])
    zf_score = float(last["ZF_Score"])

    projected_direction = "NEUTRAL"
    setup_maturity = max(buy_maturity, sell_maturity)

    buy_pressure = (
        buy_maturity >= optimizer_params["projection_maturity_floor"]
        and decay_slope < 0
        and last["close"] < last["P_pure"]
        and zf_score >= optimizer_params["projection_zf_floor"]
    )
    sell_pressure = (
        sell_maturity >= optimizer_params["projection_maturity_floor"]
        and decay_slope > 0
        and last["close"] > last["P_pure"]
        and zf_score >= optimizer_params["projection_zf_floor"]
    )

    if buy_pressure and buy_maturity >= sell_maturity:
        projected_direction = "BUY"
        setup_maturity = buy_maturity
    elif sell_pressure:
        projected_direction = "SELL"
        setup_maturity = sell_maturity

    projection_score = float(np.clip((setup_maturity * 0.60) + (zf_score * 0.30) + (min(abs(decay_slope), 1.0) * 0.10), 0, 1))
    return projected_direction, setup_maturity, projection_score, price_slope


def analyze_zf_manifold_v20(symbol_name, currency_strength, account_equity, optimizer_state=None, scan_timeframe="M30", profile_item=None):
    """
    MESIN ANALISIS MANIFOLD V20 - TIMEFRAME ADAPTIF BERDASARKAN HASIL BACKTEST
    """
    try:
        optimizer_params, optimizer_mode = get_optimizer_params(symbol_name, optimizer_state or {})
        kelly_multiplier, full_kelly = fractional_kelly_multiplier(symbol_name, optimizer_state or {})
        scan_timeframe = normalize_timeframe_name(scan_timeframe)
        scan_tf_value = timeframe_value(scan_timeframe)
        profile_item = profile_item or {}
        # --------------------------------------------------------------------------
        # AMBIL DATA UTAMA TIMEFRAME AKTIF
        # --------------------------------------------------------------------------
        micro = fetch_market_microstructure(symbol_name)
        asset_class = classify_symbol(symbol_name)
        crypto_context = OKX_PROVIDER.market_context(symbol_name) if asset_class == "crypto" else {
            "Status": "NOT_CRYPTO",
            "Instrument": "",
            "Last": np.nan,
            "Funding_Rate": np.nan,
            "Open_Interest": np.nan,
            "Open_Interest_USD": np.nan,
            "OI_Change_Pct": np.nan,
            "External_Stress": 0.0,
            "Funding_Bias": "NEUTRAL",
        }
        rates = data_copy_rates_from_pos(symbol_name, scan_tf_value, 0, SCAN_BARS)
        if rates is None or len(rates) < 100:
            return None
        
        df = pd.DataFrame(rates)
        df['P_pure_hma'] = calculate_hma(df['close'], period=20)
        df['P_pure'] = df['P_pure_hma']
        if pd.notna(micro["Mid_Price"]) and micro["Mid_Price"] > 0:
            imbalance_shift = micro["Depth_Imbalance"] * (micro["Spread_Pips"] if pd.notna(micro["Spread_Pips"]) else 0.0)
            imbalance_shift_price = imbalance_shift * (micro["Ask"] - micro["Bid"]) if micro["Ask"] > micro["Bid"] else 0.0
            micro_pure = micro["Mid_Price"] + imbalance_shift_price
            df.loc[df.index[-1], 'P_pure'] = (
                df.loc[df.index[-1], 'P_pure_hma'] * P_PURE_HMA_WEIGHT
                + micro_pure * P_PURE_MICRO_WEIGHT
            )
        df['D_res'] = (abs(df['close'] - df['P_pure']) / df['P_pure']) * 100
        
        df['Polarity'] = np.where(df['close'] > df['P_pure'], 1, -1)
        df['Lambda_Liquidity'] = micro["Lambda_Liquidity"]
        df['Decay_Integral'] = (df['Lambda_Liquidity'] * df['D_res'] * df['Polarity']).rolling(window=30).sum()
        
        # Lorong Pagar Kelayakan Statistik (2-Sigma)
        df['Integral_Mean'] = df['Decay_Integral'].rolling(window=50).mean()
        df['Integral_Std'] = df['Decay_Integral'].rolling(window=50).std()
        df['Upper_Threshold'] = df['Integral_Mean'] + (2 * df['Integral_Std'])
        df['Lower_Threshold'] = df['Integral_Mean'] - (2 * df['Integral_Std'])
        
        # Filter Volume Abnormal & ZF-Score
        df['V_avg'] = df['tick_volume'].rolling(window=20).mean()
        df['V_abs'] = abs(df['tick_volume'] - df['V_avg'])
        df['drift_mean'] = df['D_res'].rolling(window=50).mean()
        df['drift_std'] = df['D_res'].rolling(window=50).std()
        
        # Hitung nilai anomali gabungan berbobot agar ZF-Score tidak jenuh oleh noise kecil.
        safe_tick_volume = df['tick_volume'].replace(0, np.nan)
        safe_drift_std = df['drift_std'].replace(0, np.nan)
        volume_component = np.clip(df['V_abs'] / safe_tick_volume, 0, 1)
        drift_zscore = ((df['D_res'] - df['drift_mean']) / safe_drift_std).abs()
        drift_component = np.clip(drift_zscore / ZF_DRIFT_ZSCORE_SCALE, 0, 1)
        liquidity_component = micro["Liquidity_Stress"]
        if asset_class == "crypto":
            df['ZF_Score'] = np.clip(
                (0.35 * volume_component)
                + (0.25 * drift_component)
                + (0.15 * liquidity_component)
                + (0.25 * crypto_context["External_Stress"]),
                0,
                1,
            )
        else:
            df['ZF_Score'] = np.clip(
                (0.45 * volume_component) + (0.35 * drift_component) + (0.20 * liquidity_component),
                0,
                1,
            )
        
        # Market Regime Engine (ATR & ADX tetap dipertahankan)
        df['tr'] = np.maximum(df['high'] - df['low'], np.maximum(abs(df['high'] - df['close'].shift(1)), abs(df['low'] - df['close'].shift(1))))
        df['atr'] = df['tr'].rolling(window=14).mean()
        df['plus_dm'] = np.where((df['high'] - df['high'].shift(1)) > (df['low'].shift(1) - df['low']), np.maximum(df['high'] - df['high'].shift(1), 0), 0)
        df['plus_di'] = 100 * (df['plus_dm'].rolling(window=14).mean() / df['atr'])
        df['adx'] = abs(df['plus_di'] - 20)
        df['Velocity'] = df['close'].diff()
        df['Acceleration'] = df['Velocity'].diff()
        df['Inflection_Detected'] = np.sign(df['Acceleration']) != np.sign(df['Acceleration'].shift(1))
        df['Swing_High'] = df['high'].rolling(window=FIBO_LOOKBACK_BARS, min_periods=20).max()
        df['Swing_Low'] = df['low'].rolling(window=FIBO_LOOKBACK_BARS, min_periods=20).min()
        fib_range = (df['Swing_High'] - df['Swing_Low']).replace(0, np.nan)
        df['Fibo_Position'] = np.clip((df['close'] - df['Swing_Low']) / fib_range, 0, 1)
        df['Fibo_382'] = df['Swing_Low'] + fib_range * 0.382
        df['Fibo_500'] = df['Swing_Low'] + fib_range * 0.500
        df['Fibo_618'] = df['Swing_Low'] + fib_range * 0.618
        
        df = df.dropna()
        if df.empty:
            return None
            
        # Double Confirm Time-Lock timeframe aktif
        last_idx = df.index[-1]
        prev_idx = df.index[-2]
        last_row = df.iloc[-1]
        
        is_buy_locked = (df.loc[last_idx, 'Decay_Integral'] < df.loc[last_idx, 'Lower_Threshold']) and \
                            (df.loc[prev_idx, 'Decay_Integral'] < df.loc[prev_idx, 'Lower_Threshold'])
                        
        is_sell_locked = (df.loc[last_idx, 'Decay_Integral'] > df.loc[last_idx, 'Upper_Threshold']) and \
                             (df.loc[prev_idx, 'Decay_Integral'] > df.loc[prev_idx, 'Upper_Threshold'])
        
        # --------------------------------------------------------------------------
        # SENSOR EKSEKUSI (M30 TUNGGAL)
        # --------------------------------------------------------------------------
        direction = "NEUTRAL"
        signal_type = "NEUTRAL"
        projected_direction, setup_maturity, projection_score, projection_price_slope = project_next_m30_direction(df, optimizer_params)
        if is_buy_locked:
            direction = "BUY"
            signal_type = "STRICT"
        elif is_sell_locked:
            direction = "SELL"
            signal_type = "STRICT"
        elif projected_direction in ("BUY", "SELL"):
            direction = projected_direction
            signal_type = "PROJECTED"
            
        regime = "TREND" if last_row['adx'] > 15 else "RANGE"
        metal_gate_ok = True
        if asset_class == "metal" and direction in ("BUY", "SELL"):
            metal_gate_ok = float(last_row['D_res']) >= METAL_MIN_DRIFT
            if METAL_REQUIRE_TREND:
                metal_gate_ok = metal_gate_ok and regime == "TREND"
            if not metal_gate_ok:
                direction = "NEUTRAL"
                signal_type = "METAL_RESONANCE_BLOCK"
        fibo_position = float(last_row.get('Fibo_Position', np.nan))
        fibo_aligned = (
            (direction == "BUY" and pd.notna(fibo_position) and fibo_position <= FIBO_BUY_MAX)
            or (direction == "SELL" and pd.notna(fibo_position) and fibo_position >= FIBO_SELL_MIN)
        )
        active_zf_floor = float(profile_item.get("optimizer_zf_floor", MIN_EXECUTION_ZF_SCORE) or MIN_EXECUTION_ZF_SCORE)
        zf_execution_floor_ok = float(last_row['ZF_Score']) >= active_zf_floor
        if direction in ("BUY", "SELL") and USE_FIBO_FILTER and not fibo_aligned:
            direction = "NEUTRAL"
            signal_type = "FIBO_BLOCK"
        if direction in ("BUY", "SELL") and not zf_execution_floor_ok:
            direction = "NEUTRAL"
            signal_type = "ZF_FLOOR_BLOCK"
        if (
            asset_class == "crypto"
            and direction in ("BUY", "SELL")
            and OKX_REQUIRE_CRYPTO_DATA
            and crypto_context["Status"] != "OK"
        ):
            direction = "NEUTRAL"
            signal_type = "CRYPTO_DATA_BLOCK"
        
        # Hitung Kematangan Rasa Percaya Diri (Confidence)
        zf_weight = abs(last_row['ZF_Score']) * 100
        if signal_type == "PROJECTED":
            confidence = min(max(int((projection_score * 45) + (setup_maturity * 25) + 25), 10), 88)
        else:
            confidence = min(max(int(zf_weight * 5 + 50), 10), 98)
        
        base_curr = symbol_name[:3].upper()
        quote_curr = symbol_name[3:6].upper()
        if direction == "BUY" and currency_strength.get(base_curr, 0) < currency_strength.get(quote_curr, 0):
            confidence -= 15
        elif direction == "SELL" and currency_strength.get(base_curr, 0) > currency_strength.get(quote_curr, 0):
            confidence -= 15
            
        if direction == "NEUTRAL":
            confidence = 0
        if signal_type == "PROJECTED" and confidence < optimizer_params["projection_confidence_floor"]:
            direction = "NEUTRAL"
            signal_type = "NEUTRAL"
            confidence = 0
        if micro["Liquidity_Void"]:
            confidence = max(confidence - 25, 0)
        elif micro["Liquidity_Stress"] >= 0.75:
            confidence = max(confidence - 10, 0)
        if asset_class == "crypto" and direction in ("BUY", "SELL") and crypto_context["Status"] == "OK":
            if crypto_context["Funding_Bias"] == direction:
                confidence = min(confidence + 5, 98)
            elif crypto_context["Funding_Bias"] not in ("NEUTRAL", direction):
                confidence = max(confidence - 8, 0)

        # --------------------------------------------------------------------------
        # IMPLEMENTASI DYNAMIC FRACTIONAL POSITION SIZING (MIFX Proksi)
        # --------------------------------------------------------------------------
        recommended_lot = 0.00
        stop_loss_distance_pips, sl_model = calculate_dynamic_stop_loss_pips(symbol_name, last_row, micro, regime, optimizer_params)
        take_profit_distance_pips, tp_model, rr_ratio = calculate_dynamic_take_profit_pips(
            symbol_name,
            last_row,
            micro,
            regime,
            direction,
            stop_loss_distance_pips,
            optimizer_params,
        )
        exit_mode = str(profile_item.get("exit_mode", "dynamic_sl_tp") or "dynamic_sl_tp").lower()
        if exit_mode == "tp_only" and AUTO_EXECUTION_REQUIRES_SL:
            exit_mode = "zf_dynamic_sl_tp"
        if exit_mode == "tp_only":
            stop_loss_distance_pips = np.nan
            sl_model = "TANPA_SL_TP_ONLY"
            take_profit_distance_pips = TP_ONLY_TARGET_PIPS
            tp_model = f"TP_ONLY_{TP_ONLY_TARGET_PIPS:g}_PIPS"
            rr_ratio = np.nan
        symbol_info = data_symbol_info(symbol_name)
        close_price = float(last_row["close"])
        entry_model = "MARKET_REFERENCE"
        fibo_limit_price = np.nan
        if direction == "BUY" and USE_FIBO_FILTER:
            fibo_candidates = [
                float(last_row.get("Fibo_618", np.nan)),
                float(last_row.get("Fibo_500", np.nan)),
                close_price,
            ]
            fibo_limit_price = min([v for v in fibo_candidates if pd.notna(v) and v > 0] or [close_price])
            entry_model = "ZF_FIBO_BUY_LIMIT"
        elif direction == "SELL" and USE_FIBO_FILTER:
            fibo_candidates = [
                float(last_row.get("Fibo_382", np.nan)),
                float(last_row.get("Fibo_500", np.nan)),
                close_price,
            ]
            fibo_limit_price = max([v for v in fibo_candidates if pd.notna(v) and v > 0] or [close_price])
            entry_model = "ZF_FIBO_SELL_LIMIT"
        execution_entry_price = fibo_limit_price if pd.notna(fibo_limit_price) else close_price
        sl_price_distance = pips_to_price(stop_loss_distance_pips, symbol_info)
        tp_price_distance = pips_to_price(take_profit_distance_pips, symbol_info)
        sl_points = pips_to_points(stop_loss_distance_pips, symbol_info)
        tp_points = pips_to_points(take_profit_distance_pips, symbol_info)
        sl_price = np.nan
        tp_price = np.nan
        if direction == "BUY":
            sl_price = execution_entry_price - sl_price_distance
            tp_price = execution_entry_price + tp_price_distance
        elif direction == "SELL":
            sl_price = execution_entry_price + sl_price_distance
            tp_price = execution_entry_price - tp_price_distance
        
        if direction != "NEUTRAL" and exit_mode == "tp_only":
            recommended_lot = 0.01
        elif direction != "NEUTRAL":
            money_at_risk = account_equity * (RISK_PER_TRADE_PCT / 100) * kelly_multiplier
            pip_value_standard_lot = 10.0 
            
            raw_lot = money_at_risk / (stop_loss_distance_pips * pip_value_standard_lot)
            recommended_lot = max(round(raw_lot, 2), 0.01)
            
            recommended_lot = min(recommended_lot, EA_MAX_LOT)

        estimated_slippage_pips = estimate_slippage_pips(recommended_lot, micro)
        liquidity_status = "VOID" if micro["Liquidity_Void"] else "STRESSED" if micro["Liquidity_Stress"] >= 0.75 else "LAMINAR"
                
        return {
            "Symbol": symbol_name,
            "Asset_Class": asset_class,
            "Timeframe": scan_timeframe,
            "Exit_Mode": exit_mode.upper(),
            "Expected_Hold_Hours": profile_item.get("avg_hours_to_result", np.nan),
            "Close": last_row['close'],
            "Bid": micro["Bid"],
            "Ask": micro["Ask"],
            "Mid_Price": micro["Mid_Price"],
            "Direction": direction,
            "Projected_Direction": projected_direction,
            "Signal_Type": signal_type,
            "Setup_Maturity": round(setup_maturity, 4),
            "Projection_Score": round(projection_score, 4),
            "Projection_Price_Slope": projection_price_slope,
            "Regime": regime,
            "Confidence": confidence,
            "Optimizer_Mode": optimizer_mode,
            "Optimizer_Confidence_Floor": optimizer_params["confidence_floor"],
            "Optimizer_Max_Spread_Pips": optimizer_params["max_spread_pips"],
            "Optimizer_Max_Slippage_Pips": optimizer_params["max_slippage_pips"],
            "Optimizer_Projection_Maturity_Floor": optimizer_params["projection_maturity_floor"],
            "Optimizer_Projection_ZF_Floor": optimizer_params["projection_zf_floor"],
            "Optimizer_Projection_Confidence_Floor": optimizer_params["projection_confidence_floor"],
            "Historical_Optimizer_ZF_Floor": active_zf_floor,
            "Kelly_Full": round(full_kelly, 4),
            "Kelly_Risk_Multiplier": round(kelly_multiplier, 4),
            "Dynamic_Lot": recommended_lot,
            "Entry_Price": round_symbol_price(execution_entry_price, symbol_info),
            "Entry_Model": entry_model,
            "SL_Pips": round(stop_loss_distance_pips, 1),
            "SL_Points": round(sl_points, 0) if pd.notna(sl_points) else np.nan,
            "SL_Price": round_symbol_price(sl_price, symbol_info),
            "SL_Model": sl_model,
            "TP_Pips": round(take_profit_distance_pips, 1),
            "TP_Points": round(tp_points, 0) if pd.notna(tp_points) else np.nan,
            "TP_Price": round_symbol_price(tp_price, symbol_info),
            "TP_Model": tp_model,
            "RR_Ratio": rr_ratio,
            "Spread_Pips": micro["Spread_Pips"],
            "Slippage_Est_Pips": estimated_slippage_pips,
            "Bid_Depth": micro["Bid_Depth"],
            "Ask_Depth": micro["Ask_Depth"],
            "Total_Depth": micro["Total_Depth"],
            "Depth_Imbalance": micro["Depth_Imbalance"],
            "Depth_Available": micro["Depth_Available"],
            "Liquidity_Cluster_Price": micro["Liquidity_Cluster_Price"],
            "Liquidity_Cluster_Volume": micro["Liquidity_Cluster_Volume"],
            "Liquidity_Stress": micro["Liquidity_Stress"],
            "Liquidity_Status": liquidity_status,
            "Liquidity_Void": micro["Liquidity_Void"],
            "Lambda_Liquidity": micro["Lambda_Liquidity"],
            "Fibo_Position": round(fibo_position, 4) if pd.notna(fibo_position) else np.nan,
            "Fibo_Aligned": bool(fibo_aligned),
            "Fibo_382": round_symbol_price(last_row.get("Fibo_382", np.nan), symbol_info),
            "Fibo_500": round_symbol_price(last_row.get("Fibo_500", np.nan), symbol_info),
            "Fibo_618": round_symbol_price(last_row.get("Fibo_618", np.nan), symbol_info),
            "Metal_Gate_Ok": bool(metal_gate_ok),
            "OKX_Status": crypto_context["Status"],
            "OKX_Instrument": crypto_context["Instrument"],
            "OKX_Last": crypto_context["Last"],
            "OKX_Funding_Rate": crypto_context["Funding_Rate"],
            "OKX_Open_Interest": crypto_context["Open_Interest"],
            "OKX_Open_Interest_USD": crypto_context["Open_Interest_USD"],
            "OKX_OI_Change_Pct": crypto_context["OI_Change_Pct"],
            "OKX_External_Stress": crypto_context["External_Stress"],
            "OKX_Funding_Bias": crypto_context["Funding_Bias"],
            "Drift": last_row['D_res'],       
            "Decay_Integral": last_row['Decay_Integral'],
            "Inflection_Detected": bool(last_row['Inflection_Detected']),
            "ZF_Score": last_row['ZF_Score']  
        }
        
    except Exception as e:
        print(f"WARNING: Gangguan pada analisis simbol {symbol_name}: {e}")
        return None

# ==============================================================================
# "REVISI" CORE EXECUTION TERMINAL DASHBOARD (OPSI B)
# ==============================================================================
def main_core_final():
    if not data_initialize():
        provider_name = DATA_PROVIDER if (using_oanda_provider() or using_yfinance_provider()) else "MetaTrader 5"
        print(f"CRITICAL ERROR: Provider data {provider_name} belum siap.")
        if using_oanda_provider():
            print("Pastikan OANDA_API_TOKEN dan OANDA_ACCOUNT_ID sudah diisi di .env.")
        elif using_yfinance_provider():
            print("Pastikan NAS/container memiliki akses internet untuk yfinance.")
        return
    
    account_equity = data_account_equity()
        
    print("[ZF CORE V20 PRO] Memulai Sinkronisasi Komputasi Fraktal...")
    macro = fetch_macro_sentiment()
    news_status = fetch_news_risk()
    forward_sync = sync_mt5_forward_results()
    
    all_symbols = data_symbols_get()
    mifx_symbols = filter_trade_symbols(all_symbols)
    auto_profile_path, auto_profile_status = auto_refresh_historical_validation(mifx_symbols)
    historical_profile, profile_source = load_or_build_historical_profile()
    scanned_symbols = apply_primary_symbol_limit(mifx_symbols, historical_profile)
    symbol_timeframes = {
        symbol: (
            historical_profile.get(symbol, {}).get("timeframe", DEFAULT_SCAN_TIMEFRAME)
            if USE_PROFILE_TIMEFRAMES
            else DEFAULT_SCAN_TIMEFRAME
        )
        for symbol in scanned_symbols
    }
    optimizer_state, optimizer_status = run_self_healing_optimizer(force=forward_sync.get("imported", 0) > 0)
    
    print("Menghitung Matriks Kekuatan Mata Uang Absolut...")
    currency_strength = compute_currency_strength(scanned_symbols, symbol_timeframes)
    
    print("Memindai Geometri Struktur Manifold Adaptif...")
    results = []
    for sym in scanned_symbols:
        res = analyze_zf_manifold_v20(
            sym,
            currency_strength,
            account_equity,
            optimizer_state,
            scan_timeframe=symbol_timeframes.get(sym, DEFAULT_SCAN_TIMEFRAME),
            profile_item=historical_profile.get(sym, {}),
        )
        if res is not None:
            results.append(res)
    
    if len(results) == 0:
        master_df = pd.DataFrame(columns=["Symbol", "Direction", "Confidence", "Dynamic_Lot", "SL_Pips", "Drift", "ZF_Score"])
    else:
        master_df = pd.DataFrame(results)
        
    previous_archive_path, previous_payload = load_latest_archive()
    memory_df, mismatch_df = build_memory_cross_check(master_df, previous_payload)
    risk_df = apply_risk_controls(memory_df, news_status)
    risk_df = apply_historical_profile_gate(risk_df, historical_profile)
    risk_df = apply_accuracy_quality_gate(risk_df)
    mismatch_df = risk_df[risk_df["Memory_Status"].isin(["CRITICAL_MISMATCH", "RESONANCE_MISMATCH"])].copy()
    if not mismatch_df.empty:
        mismatch_rank_cols = [col for col in ["Delta_ZF_Score", "Delta_Drift", "Delta_Lambda"] if col in mismatch_df.columns]
        mismatch_df["Mismatch_Rank"] = mismatch_df[mismatch_rank_cols].abs().max(axis=1)
        mismatch_df = mismatch_df.sort_values(by="Mismatch_Rank", ascending=False).head(TOP_MISMATCH)

    if not risk_df.empty:
        risk_df["Ranking_Score"] = (
            risk_df["Accuracy_Quality_Score"].fillna(0) * 0.55
            + risk_df["Confidence"].fillna(0) * 0.18
            + risk_df["Setup_Maturity"].fillna(0) * 16
            + risk_df["Historical_Win_Rate"].fillna(40) * 0.08
            + risk_df["Historical_Expectancy_R"].fillna(0) * 100 * 0.08
            + risk_df["ZF_Score"].fillna(0) * 5
        )
    elif "Ranking_Score" not in risk_df.columns:
        risk_df["Ranking_Score"] = pd.Series(dtype=float)
    buy_pool = risk_df[(risk_df['Direction'] == "BUY") & (risk_df["Trade_Allowed"])].sort_values(by='Ranking_Score', ascending=False).head(TOP_BUY)
    sell_pool = risk_df[(risk_df['Direction'] == "SELL") & (risk_df["Trade_Allowed"])].sort_values(by='Ranking_Score', ascending=False).head(TOP_SELL)
    live_tracker_stats = update_live_signal_tracker(
        buy_pool,
        sell_pool,
        scan_context={"macro": macro, "news_status": news_status},
    )
    ea_signal_path = export_ea_signals(buy_pool, sell_pool)
    if live_tracker_stats["closed"] > 0:
        optimizer_state, optimizer_status = run_self_healing_optimizer(force=True)
    if forward_sync.get("imported", 0) > 0:
        optimizer_state, optimizer_status = run_self_healing_optimizer(force=True)
    data_shutdown()

    csv_path, json_path, manifest_path, moved_to_cold = archive_scan_results(
        risk_df,
        buy_pool,
        sell_pool,
        mismatch_df,
        macro,
        news_status,
        account_equity,
        previous_archive_path,
    )
    
    print("\n========================================================")
    print("             ZF CORE SCANNER V20 PRO ASSISTANT")
    timeframe_mode = "ADAPTIF BERDASARKAN BACKTEST" if USE_PROFILE_TIMEFRAMES else f"FIXED {normalize_timeframe_name(DEFAULT_SCAN_TIMEFRAME)}"
    print(f"             [MODE {timeframe_mode}]")
    print("========================================================")
    print(f"Scan Time : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} WITA")
    print(f"Account Equity: ${account_equity:,.2f} USD")
    print(f"News Risk : {news_status}")
    print(f"Macro Info: [DXY: {macro['DXY']:.2f}]  [US10Y: {macro['US10Y']:.2f}%]  [GOLD: ${macro['GOLD']:.2f}]")
    print(f"Forward Sync: {forward_sync.get('status')} ({forward_sync.get('imported', 0)} new MT5 deal)")
    print(f"Universe   : {len(mifx_symbols)} eligible -> {len(scanned_symbols)} active utama ({','.join(sorted(SUPPORTED_ASSET_CLASSES))})")
    system_issues = []
    if not previous_archive_path:
        system_issues.append("memori awal belum ada")
    if str(auto_profile_status).startswith("IMPORT_FAILED"):
        system_issues.append("validasi historis error")
    if str(optimizer_status).startswith("NO_LIVE_DATA"):
        system_issues.append("optimizer menunggu data live")
    elif "FAILED" in str(optimizer_status).upper():
        system_issues.append("optimizer error")
    if historical_profile:
        tradeable_count = sum(1 for item in historical_profile.values() if item["status"] == "TRADEABLE")
        watch_count = sum(1 for item in historical_profile.values() if item["status"] == "WATCH_ONLY")
        avoid_count = sum(1 for item in historical_profile.values() if item["status"] == "AVOID")
    else:
        tradeable_count = 0
        watch_count = 0
        avoid_count = 0
        if not (using_oanda_provider() or using_yfinance_provider()):
            system_issues.append("profile historis belum ada")
    print(
        "Sistem     : "
        + ("AMAN - data, archive, dan optimizer berjalan." if not system_issues else "PERLU CEK - " + "; ".join(system_issues))
    )
    print(f"Profile    : TRADEABLE={tradeable_count} WATCH_ONLY={watch_count} AVOID={avoid_count}")
    if moved_to_cold:
        print(f"Cold Storage Move: {len(moved_to_cold)} old archive file(s)")
    if ea_signal_path:
        print(f"EA Signal : {ea_signal_path}")
    print("--------------------------------------------------------")

    print("RISK ENGINE SUMMARY")
    if len(risk_df) == 0:
        print("   (X) Tidak ada data risiko yang dapat dihitung.")
    else:
        blocked_count = int((~risk_df["Trade_Allowed"] & risk_df["Direction"].isin(["BUY", "SELL"])).sum())
        active_count = int(risk_df["Direction"].isin(["BUY", "SELL"]).sum())
        critical_count = int(risk_df["Risk_Mode"].isin(["CIRCUIT_BREAKER", "COLD_MODE", "LIQUIDITY_LOCK", "SLIPPAGE_LOCK"]).sum())
        if critical_count:
            print(f"   Status Risiko : PERLU WASPADA - {critical_count} pair sedang dibatasi sistem.")
        elif active_count and blocked_count:
            print(f"   Status Risiko : SELEKTIF - {blocked_count} sinyal ditahan demi akurasi.")
        else:
            print("   Status Risiko : AMAN - tidak ada pembatasan besar.")
        print(
            "   Belajar Live : "
            f"opened={live_tracker_stats['opened']} "
            f"closed={live_tracker_stats['closed']} "
            f"open={live_tracker_stats['open']}"
        )
        projection_accuracy = get_projection_accuracy_summary()
        if projection_accuracy:
            print(
                "   Akurasi Proyeksi ZF: "
                f"{projection_accuracy['accuracy_resolved']}% resolved "
                f"({projection_accuracy['wins']} win / {projection_accuracy['losses']} loss / "
                f"{projection_accuracy['expired']} expired, total {projection_accuracy['signals']}) "
                f"| Expectancy R {projection_accuracy['expectancy_r']}"
            )
    print("--------------------------------------------------------")
    
    print("TOP BUY RANKING (Manifold Adaptif)")
    if len(buy_pool) == 0:
        print("   (X) TIDAK ADA PASANGAN ASSET YANG LOLOS ALIGNMENT FRAKTAL (STANDBY)")
        for reason in summarize_empty_signal_reasons(risk_df, "BUY"):
            print(f"       - {reason}")
    else:
        rank = 1
        for _, row in buy_pool.iterrows():
            print(f" {rank}. {row['Symbol']:<10} | TF: {row.get('Timeframe', 'M30')} | Mode: {row.get('Exit_Mode', 'DYNAMIC_SL_TP')} | {row['Action_Signal']} | Sig: {row['Signal_Type']} | Lot: {row['Dynamic_Lot']} | Entry: {row['Entry_Price']} | SL: {fmt_price(row['SL_Price'])} ({fmt_value(row['SL_Points'], 0, ' points')}) | TP: {fmt_price(row['TP_Price'])} ({fmt_value(row['TP_Points'], 0, ' points')}) | RR: {fmt_rr(row['RR_Ratio'])} | Quality: {row['Accuracy_Quality_Score']:.1f} | Conf: {row['Confidence']}%")
            hold_note = "" if pd.isna(row.get("Expected_Hold_Hours", np.nan)) else f" | Est. hold historis {float(row['Expected_Hold_Hours']):.1f} jam"
            print(f"    Detail: SL {fmt_value(row['SL_Pips'], 1, ' pips')} ({row['SL_Model']}) | TP {fmt_value(row['TP_Pips'], 1, ' pips')} ({row['TP_Model']}){hold_note} | Spread {row['Spread_Pips']:.2f} | Slip {row['Slippage_Est_Pips']:.2f} | Liq {row['Liquidity_Status']} | Drift {row['Drift']:.3f}% | ZF {row['ZF_Score']:.4f}")
            print(f"    Saran: {row.get('User_Recommendation', '-')}")
            rank += 1
            
    print("\nTOP SELL RANKING (Manifold Adaptif)")
    if len(sell_pool) == 0:
        print("   (X) TIDAK ADA PASANGAN ASSET YANG LOLOS ALIGNMENT FRAKTAL (STANDBY)")
        for reason in summarize_empty_signal_reasons(risk_df, "SELL"):
            print(f"       - {reason}")
    else:
        rank = 1
        for _, row in sell_pool.iterrows():
            print(f" {rank}. {row['Symbol']:<10} | TF: {row.get('Timeframe', 'M30')} | Mode: {row.get('Exit_Mode', 'DYNAMIC_SL_TP')} | {row['Action_Signal']} | Sig: {row['Signal_Type']} | Lot: {row['Dynamic_Lot']} | Entry: {row['Entry_Price']} | SL: {fmt_price(row['SL_Price'])} ({fmt_value(row['SL_Points'], 0, ' points')}) | TP: {fmt_price(row['TP_Price'])} ({fmt_value(row['TP_Points'], 0, ' points')}) | RR: {fmt_rr(row['RR_Ratio'])} | Quality: {row['Accuracy_Quality_Score']:.1f} | Conf: {row['Confidence']}%")
            hold_note = "" if pd.isna(row.get("Expected_Hold_Hours", np.nan)) else f" | Est. hold historis {float(row['Expected_Hold_Hours']):.1f} jam"
            print(f"    Detail: SL {fmt_value(row['SL_Pips'], 1, ' pips')} ({row['SL_Model']}) | TP {fmt_value(row['TP_Pips'], 1, ' pips')} ({row['TP_Model']}){hold_note} | Spread {row['Spread_Pips']:.2f} | Slip {row['Slippage_Est_Pips']:.2f} | Liq {row['Liquidity_Status']} | Drift {row['Drift']:.3f}% | ZF {row['ZF_Score']:.4f}")
            print(f"    Saran: {row.get('User_Recommendation', '-')}")
            rank += 1

    print("\nRESONANCE MISMATCH WATCHLIST (Session Memory Cross-Check)")
    if len(mismatch_df) == 0:
        print("   (OK) Tidak ada divergensi ekstrem terhadap sesi sebelumnya.")
    else:
        rank = 1
        for _, row in mismatch_df.iterrows():
            prev_dir = row.get("Previous_Direction", "")
            delta_zf = row.get("Delta_ZF_Score", np.nan)
            delta_drift = row.get("Delta_Drift", np.nan)
            delta_lambda = row.get("Delta_Lambda", np.nan)
            memory_status = row.get("Memory_Status", "RESONANCE_MISMATCH")
            print(
                f" {rank}. {row['Symbol']:<10} | {memory_status} | {prev_dir}->{row['Direction']} "
                f"| dZF: {delta_zf:+.4f} | dDrift: {delta_drift:+.3f}% | dLambda: {delta_lambda:+.3f} "
                f"| Liq: {row['Liquidity_Status']} | ZF: {row['ZF_Score']:.4f} | Drift: {row['Drift']:.3f}%"
            )
            rank += 1
    print("--------------------------------------------------------")


def scan_interval_minutes():
    timeframe = normalize_timeframe_name(DEFAULT_SCAN_TIMEFRAME)
    if timeframe.startswith("M"):
        return max(1, int(timeframe[1:]))
    return SCAN_INTERVAL_MINUTES


def seconds_until_next_scan_boundary(now=None):
    """Return seconds until the next active scan timeframe boundary."""
    now = now or datetime.now()
    interval = scan_interval_minutes()
    minute = ((now.minute // interval) + 1) * interval
    next_hour = now.replace(second=0, microsecond=0)
    if minute >= 60:
        target = next_hour.replace(minute=0) + timedelta(hours=1)
    else:
        target = next_hour.replace(minute=minute)
    return max(1, int((target - now).total_seconds()))


def run_continuous_scheduler(run_once=False):
    """Run scanner immediately, then repeat on the active scan timeframe boundary."""
    if run_once:
        main_core_final()
        return

    print("[ZF CORE V20 PRO] Service mode aktif. Scan pertama dijalankan sekarang.")
    print("Tekan Ctrl+C untuk menghentikan service.")
    try:
        while True:
            cycle_start = datetime.now()
            print(f"\n[ZF SERVICE] Cycle start: {cycle_start.strftime('%Y-%m-%d %H:%M:%S')}")
            main_core_final()

            wait_seconds = seconds_until_next_scan_boundary()
            next_run = datetime.now() + timedelta(seconds=wait_seconds)
            print(f"[ZF SERVICE] Menunggu sampai boundary {normalize_timeframe_name(DEFAULT_SCAN_TIMEFRAME)} berikutnya: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
            time.sleep(wait_seconds)
    except KeyboardInterrupt:
        print("\n[ZF SERVICE] Dihentikan oleh user. Archival Vault tetap aman.")


def parse_args():
    parser = argparse.ArgumentParser(description="ZF Core Scanner V20 service.")
    parser.add_argument("--once", action="store_true", help="Run one scan only, then exit.")
    parser.add_argument("--service", action="store_true", help="Run continuously on each active timeframe boundary.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_once = args.once or (not RUN_CONTINUOUS_BY_DEFAULT and not args.service)
    run_continuous_scheduler(run_once=run_once)
