import argparse
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import MetaTrader5 as mt5
import numpy as np
import pandas as pd

from zf_strategy_core import (
    ZFStrategyParams,
    pending_entry_price,
    prepare_zf_dataframe as prepare_shared_zf_dataframe,
    signal_direction,
    simulate_pending_trade,
)


BASE_DIR = Path(__file__).resolve().parent
REPORT_DIR = BASE_DIR / "zf_validation_reports"
PROFILE_DIR = BASE_DIR / "zf_profiles"
PRIMARY_SYMBOLS_PATH = PROFILE_DIR / "primary_symbols.json"

TIMEFRAME_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
    "W1": mt5.TIMEFRAME_W1,
}
SYNTHETIC_TIMEFRAMES = set()
TF_CORE = TIMEFRAME_MAP["M30"]
DEFAULT_DAYS = 365
DEFAULT_HORIZON_BARS = 16
DEFAULT_RISK_REWARD = 1.25
DEFAULT_ASSET_CLASSES = "forex,energy,crypto"
DEFAULT_TOP_N = 10
DEFAULT_TIMEFRAME = "M30"
DEFAULT_WINDOW_PROFILE = "auto"
DEFAULT_TP_ONLY_PIPS = "50,70"

TIMEFRAME_HOURS = {
    "M1": 1 / 60,
    "M5": 5 / 60,
    "M15": 15 / 60,
    "M30": 0.5,
    "H1": 1,
    "H4": 4,
    "D1": 24,
    "W1": 168,
}

ZF_WINDOWS = {
    "hma": 20,
    "decay": 30,
    "threshold": 50,
    "volume": 20,
    "drift": 50,
    "atr": 14,
}

ATR_SL_MULTIPLIER = 1.35
DRIFT_SL_MULTIPLIER = 1.15
ATR_TP_MULTIPLIER = 1.80
DRIFT_TP_MULTIPLIER = 1.60
TREND_SL_MULTIPLIER = 1.20
RANGE_SL_MULTIPLIER = 0.95
TREND_TP_MULTIPLIER = 1.25
RANGE_TP_MULTIPLIER = 0.90
ZF_DRIFT_ZSCORE_SCALE = 3.0
FIBO_LOOKBACK_BARS = 96
FIBO_BUY_MAX = 0.618
FIBO_SELL_MIN = 0.382
TRAILING_ACTIVATE_R = 0.75
TRAILING_DISTANCE_R = 0.55

MAJOR_CURRENCIES = ("USD", "JPY", "EUR", "GBP", "AUD", "CAD", "CHF", "NZD")
ENERGY_MARKERS = ("USOIL", "UKOIL", "XTIUSD", "XBRUSD", "WTI", "BRENT", "BRN", "OIL")
METAL_MARKERS = ("XAU", "XAG")
CRYPTO_MARKERS = ("BTC", "ETH", "XRP", "LTC", "DOGE", "ADA", "SOL", "BNB", "DOT", "TRX", "AVAX", "LINK")


def load_env_file(env_path=BASE_DIR / ".env"):
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file()


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


def parse_csv_set(value):
    return {item.strip().lower() for item in str(value).split(",") if item.strip()}


def parse_float_list(value):
    return [float(item.strip()) for item in str(value).split(",") if item.strip()]


def timeframe_to_mt5(timeframe_name):
    normalized = str(timeframe_name).strip().upper()
    if normalized in SYNTHETIC_TIMEFRAMES:
        return normalized, TIMEFRAME_MAP["D1"]
    if normalized not in TIMEFRAME_MAP:
        choices = list(TIMEFRAME_MAP) + sorted(SYNTHETIC_TIMEFRAMES)
        raise ValueError(f"Timeframe tidak dikenal: {timeframe_name}. Pilihan: {', '.join(choices)}")
    return normalized, TIMEFRAME_MAP[normalized]


def configure_window_profile(profile_name, timeframe_name, days):
    """Use compact ZF windows for short H4/D1 samples so validation still has enough bars."""
    global ZF_WINDOWS
    profile = str(profile_name or DEFAULT_WINDOW_PROFILE).strip().lower()
    estimated_bars = {
        "M1": days * 24 * 60,
        "M5": days * 24 * 12,
        "M15": days * 24 * 4,
        "M30": days * 24 * 2,
        "H1": days * 24,
        "H4": days * 6,
        "D1": days,
        "W1": max(days // 7, 1),
    }.get(timeframe_name.upper(), days * 48)

    if profile == "auto":
        if estimated_bars < 80:
            profile = "ultra"
        elif estimated_bars < 180:
            profile = "compact"
        else:
            profile = "standard"

    if profile == "ultra":
        ZF_WINDOWS = {
            "hma": 5,
            "decay": 3,
            "threshold": 4,
            "volume": 3,
            "drift": 4,
            "atr": 3,
        }
    elif profile == "compact":
        ZF_WINDOWS = {
            "hma": 10,
            "decay": 8,
            "threshold": 12,
            "volume": 8,
            "drift": 12,
            "atr": 7,
        }
    elif profile == "standard":
        ZF_WINDOWS = {
            "hma": 20,
            "decay": 30,
            "threshold": 50,
            "volume": 20,
            "drift": 50,
            "atr": 14,
        }
    else:
        raise ValueError("window-profile harus auto, standard, compact, atau ultra.")

    warmup_bars = max(
        ZF_WINDOWS["hma"] + ZF_WINDOWS["decay"] + ZF_WINDOWS["threshold"],
        ZF_WINDOWS["drift"],
        ZF_WINDOWS["atr"] * 3,
    )
    return profile, estimated_bars, warmup_bars


def calculate_hma(series, period=20):
    half_period = int(period / 2)
    sqrt_period = int(np.sqrt(period))

    def wma(s, p):
        weights = np.arange(1, p + 1)
        return s.rolling(p).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)

    raw_hma = 2 * wma(series, half_period) - wma(series, period)
    return wma(raw_hma, sqrt_period)


def aggregate_rates_to_d10(rates):
    if rates is None or len(rates) == 0:
        return rates

    df = pd.DataFrame(rates)
    df["dt"] = pd.to_datetime(df["time"], unit="s")
    start = df["dt"].min().normalize()
    df["bucket"] = ((df["dt"] - start).dt.days // 10).astype(int)

    grouped = df.groupby("bucket", sort=True).agg(
        time=("time", "first"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        tick_volume=("tick_volume", "sum"),
        spread=("spread", "mean"),
        real_volume=("real_volume", "sum"),
    )
    grouped["spread"] = grouped["spread"].fillna(0).round().astype(int)
    return grouped.reset_index(drop=True).to_records(index=False)


def symbol_pip_factor(symbol_info):
    if symbol_info is None:
        return 10.0
    return 10.0 if symbol_info.digits in (3, 5) else 1.0


def price_distance_to_pips(price_distance, symbol_info):
    if symbol_info is None or not getattr(symbol_info, "point", 0):
        return np.nan
    return float(price_distance / float(symbol_info.point) / symbol_pip_factor(symbol_info))


def pips_to_price(pips, symbol_info):
    if symbol_info is None or not getattr(symbol_info, "point", 0):
        return np.nan
    return float(pips * float(symbol_info.point) * symbol_pip_factor(symbol_info))


def prepare_zf_dataframe(rates):
    params = ZFStrategyParams(
        hma_period=ZF_WINDOWS["hma"],
        decay_window=ZF_WINDOWS["decay"],
        threshold_window=ZF_WINDOWS["threshold"],
        threshold_sigma=float(os.getenv("ZF_VALIDATION_SIGMA", "1.5") or 1.5),
        confirmation_bars=int(os.getenv("ZF_VALIDATION_CONFIRMATION_BARS", "1") or 1),
        volume_window=ZF_WINDOWS["volume"],
        drift_window=ZF_WINDOWS["drift"],
        atr_period=ZF_WINDOWS["atr"],
        fibo_lookback=FIBO_LOOKBACK_BARS,
        zf_floor=float(os.getenv("ZF_VALIDATION_ZF_FLOOR", "0.45") or 0.45),
    )
    df = prepare_shared_zf_dataframe(rates, params=params)
    directions = [signal_direction(df, idx, params=params, use_fibo=False)[0] for idx in range(len(df))]
    df["Direction"] = directions
    df["Fibo_Aligned"] = np.select(
        [
            (df["Direction"] == "BUY") & (df["Fibo_Position"] <= FIBO_BUY_MAX),
            (df["Direction"] == "SELL") & (df["Fibo_Position"] >= FIBO_SELL_MIN),
        ],
        [True, True],
        default=False,
    )

    df["Velocity"] = df["close"].diff()
    df["Acceleration"] = df["Velocity"].diff()
    df["Inflection_Detected"] = np.sign(df["Acceleration"]) != np.sign(df["Acceleration"].shift(1))

    return df.dropna().reset_index(drop=True)


def calculate_historical_sl_tp(row, symbol_info):
    atr_pips = price_distance_to_pips(row["atr"], symbol_info)
    drift_pips = price_distance_to_pips(abs(row["close"] - row["P_pure"]), symbol_info)

    atr_sl = atr_pips * ATR_SL_MULTIPLIER if pd.notna(atr_pips) else np.nan
    drift_sl = drift_pips * DRIFT_SL_MULTIPLIER if pd.notna(drift_pips) else np.nan
    sl_candidates = [value for value in [atr_sl, drift_sl] if pd.notna(value) and value > 0]
    if not sl_candidates:
        return np.nan, np.nan, "NO_VOLATILITY"

    regime_sl = TREND_SL_MULTIPLIER if row["Regime"] == "TREND" else RANGE_SL_MULTIPLIER
    sl_pips = max(sl_candidates) * regime_sl

    atr_tp = atr_pips * ATR_TP_MULTIPLIER if pd.notna(atr_pips) else np.nan
    drift_tp = drift_pips * DRIFT_TP_MULTIPLIER if pd.notna(drift_pips) else np.nan
    tp_candidates = [value for value in [atr_tp, drift_tp] if pd.notna(value) and value > 0]
    regime_tp = TREND_TP_MULTIPLIER if row["Regime"] == "TREND" else RANGE_TP_MULTIPLIER
    structure_tp = max(tp_candidates) * regime_tp if tp_candidates else 0
    tp_pips = max(structure_tp, sl_pips * DEFAULT_RISK_REWARD)

    return float(round(sl_pips, 1)), float(round(tp_pips, 1)), "HISTORICAL_DATA"


def simulate_trade(df, entry_idx, direction, sl_pips, tp_pips, symbol_info, horizon_bars, use_trailing=False):
    entry = float(df.loc[entry_idx, "close"])
    sl_distance = pips_to_price(sl_pips, symbol_info)
    tp_distance = pips_to_price(tp_pips, symbol_info)
    if pd.isna(sl_distance) or pd.isna(tp_distance):
        return "INVALID", 0, entry, np.nan, np.nan, 0.0, np.nan

    if direction == "BUY":
        sl_price = entry - sl_distance
        tp_price = entry + tp_distance
    else:
        sl_price = entry + sl_distance
        tp_price = entry - tp_distance

    active_sl = sl_price
    trail_active = False
    activation_distance = sl_distance * TRAILING_ACTIVATE_R
    trail_distance = sl_distance * TRAILING_DISTANCE_R
    max_idx = min(entry_idx + horizon_bars, len(df) - 1)
    for idx in range(entry_idx + 1, max_idx + 1):
        high = float(df.loc[idx, "high"])
        low = float(df.loc[idx, "low"])

        if use_trailing:
            if direction == "BUY" and high >= entry + activation_distance:
                trail_active = True
                active_sl = max(active_sl, high - trail_distance)
            elif direction == "SELL" and low <= entry - activation_distance:
                trail_active = True
                active_sl = min(active_sl, low + trail_distance)

        if direction == "BUY":
            hit_sl = low <= active_sl
            hit_tp = high >= tp_price
        else:
            hit_sl = high >= active_sl
            hit_tp = low <= tp_price

        if hit_sl and hit_tp:
            exit_price = active_sl if use_trailing and trail_active else sl_price
            profit_pips = price_distance_to_pips(exit_price - entry, symbol_info) if direction == "BUY" else price_distance_to_pips(entry - exit_price, symbol_info)
            result = "WIN" if profit_pips > 0 else "LOSS_BOTH_HIT"
            return result, idx - entry_idx, entry, sl_price, tp_price, float(round(profit_pips, 1)), exit_price
        if hit_sl:
            exit_price = active_sl
            profit_pips = price_distance_to_pips(exit_price - entry, symbol_info) if direction == "BUY" else price_distance_to_pips(entry - exit_price, symbol_info)
            result = "WIN" if profit_pips > 0 else "LOSS"
            return result, idx - entry_idx, entry, sl_price, tp_price, float(round(profit_pips, 1)), exit_price
        if hit_tp:
            return "WIN", idx - entry_idx, entry, sl_price, tp_price, float(round(tp_pips, 1)), tp_price

    exit_price = float(df.loc[max_idx, "close"])
    profit_pips = price_distance_to_pips(exit_price - entry, symbol_info) if direction == "BUY" else price_distance_to_pips(entry - exit_price, symbol_info)
    return "EXPIRED", max_idx - entry_idx, entry, sl_price, tp_price, float(round(profit_pips, 1)), exit_price


def simulate_tp_only(df, entry_idx, direction, tp_pips, symbol_info, horizon_bars):
    entry = float(df.loc[entry_idx, "close"])
    tp_distance = pips_to_price(tp_pips, symbol_info)
    if pd.isna(tp_distance):
        return "INVALID", 0, entry, np.nan

    tp_price = entry + tp_distance if direction == "BUY" else entry - tp_distance
    max_idx = min(entry_idx + horizon_bars, len(df) - 1)
    for idx in range(entry_idx + 1, max_idx + 1):
        high = float(df.loc[idx, "high"])
        low = float(df.loc[idx, "low"])
        hit_tp = high >= tp_price if direction == "BUY" else low <= tp_price
        if hit_tp:
            return "TP_HIT", idx - entry_idx, entry, tp_price

    return "NOT_HIT", max_idx - entry_idx, entry, tp_price


def validate_symbol(
    symbol_name,
    start_dt,
    end_dt,
    horizon_bars,
    timeframe_name="M30",
    mt5_timeframe=None,
    warmup_bars=120,
    exit_mode="dynamic_sl_tp",
    tp_only_pips=None,
    zf_floor=0.0,
    min_drift=0.0,
    require_regime="",
    fibo_filter=False,
    use_trailing=False,
):
    symbol_info = mt5.symbol_info(symbol_name)
    timeframe_name = str(timeframe_name).upper()
    mt5_timeframe = mt5_timeframe if mt5_timeframe is not None else TIMEFRAME_MAP["M30"]
    rates = mt5.copy_rates_range(symbol_name, mt5_timeframe, start_dt, end_dt)
    if rates is None or len(rates) < warmup_bars:
        return [], {"Symbol": symbol_name, "Timeframe": timeframe_name, "Asset_Class": classify_symbol(symbol_name), "Error": "INSUFFICIENT_DATA"}

    df = prepare_zf_dataframe(rates)
    if df.empty:
        return [], {"Symbol": symbol_name, "Timeframe": timeframe_name, "Asset_Class": classify_symbol(symbol_name), "Error": "NO_ZF_ROWS"}
    trades = []

    for idx in range(2, len(df) - 1):
        row = df.loc[idx]
        direction = row["Direction"]
        if direction not in ("BUY", "SELL"):
            continue
        if zf_floor and float(row.get("ZF_Score", 0) or 0) < zf_floor:
            continue
        if min_drift and float(row.get("D_res", 0) or 0) < min_drift:
            continue
        if require_regime and str(row.get("Regime", "")).upper() != str(require_regime).upper():
            continue
        if fibo_filter and not bool(row.get("Fibo_Aligned", False)):
            continue

        if exit_mode == "tp_only":
            for target_pips in tp_only_pips or []:
                result, bars_to_result, entry_price, tp_price = simulate_tp_only(
                    df, idx, direction, target_pips, symbol_info, horizon_bars
                )
                hit = result == "TP_HIT"
                trades.append(
                    {
                        "Symbol": symbol_name,
                        "Timeframe": timeframe_name,
                        "Asset_Class": classify_symbol(symbol_name),
                        "Signal_Time": row["time"],
                        "Direction": direction,
                        "Entry": entry_price,
                        "SL_Price": np.nan,
                        "TP_Price": tp_price,
                        "SL_Pips": np.nan,
                        "TP_Pips": target_pips,
                        "RR_Ratio": np.nan,
                        "Result": result,
                        "R_Result": 1 if hit else 0,
                        "Bars_To_Result": bars_to_result,
                        "Hours_To_Result": round(bars_to_result * TIMEFRAME_HOURS.get(timeframe_name, 0), 2),
                        "ZF_Score": round(float(row["ZF_Score"]), 4),
                        "Drift": round(float(row["D_res"]), 4),
                        "Fibo_Position": round(float(row.get("Fibo_Position", np.nan)), 4),
                        "Fibo_Aligned": bool(row.get("Fibo_Aligned", False)),
                        "Decay_Integral": round(float(row["Decay_Integral"]), 4),
                        "Regime": row["Regime"],
                        "Inflection_Detected": bool(row["Inflection_Detected"]),
                        "SL_TP_Model": f"TP_ONLY_{target_pips:g}_PIPS",
                    }
                )
        else:
            sl_pips, tp_pips, model = calculate_historical_sl_tp(row, symbol_info)
            if pd.isna(sl_pips) or pd.isna(tp_pips):
                continue

            entry_price = pending_entry_price(row, direction)
            digits = int(getattr(symbol_info, "digits", 5) or 5)
            pip_points = 10 if digits in (3, 5) else 1
            spread_series = pd.to_numeric(df.get("spread", pd.Series(dtype=float)), errors="coerce")
            spread_pips = float(spread_series.replace(0, np.nan).median() / pip_points) if not spread_series.empty else 0.0
            outcome = simulate_pending_trade(
                df,
                idx,
                direction,
                entry_price,
                sl_pips,
                tp_pips,
                symbol_info,
                expiry_bars=int(os.getenv("ZF_VALIDATION_PENDING_EXPIRY_BARS", "6") or 6),
                horizon_bars=horizon_bars,
                trailing=use_trailing,
                spread_pips=spread_pips,
                slippage_pips=max(spread_pips * 0.10, 0.05),
                commission_r=0.015,
            )
            result = outcome.get("Result", "INVALID")
            bars_to_result = int(outcome.get("Bars_To_Result", 0) or 0)
            r_result = float(outcome.get("R_Result", 0.0) or 0.0)
            profit_pips = r_result * sl_pips
            sl_distance = pips_to_price(sl_pips, symbol_info)
            tp_distance = pips_to_price(tp_pips, symbol_info)
            sl_price = entry_price - sl_distance if direction == "BUY" else entry_price + sl_distance
            tp_price = entry_price + tp_distance if direction == "BUY" else entry_price - tp_distance
            exit_price = np.nan
            rr_ratio = tp_pips / sl_pips if sl_pips else 0

            trades.append(
                {
                    "Symbol": symbol_name,
                    "Timeframe": timeframe_name,
                    "Asset_Class": classify_symbol(symbol_name),
                    "Signal_Time": row["time"],
                    "Direction": direction,
                    "Entry": entry_price,
                    "SL_Price": sl_price,
                    "TP_Price": tp_price,
                    "Exit_Price": exit_price,
                    "SL_Pips": sl_pips,
                    "TP_Pips": tp_pips,
                    "Profit_Pips": profit_pips,
                    "RR_Ratio": round(rr_ratio, 2),
                    "Result": result,
                    "R_Result": round(r_result, 3),
                    "Bars_To_Result": bars_to_result,
                    "Hours_To_Result": round(bars_to_result * TIMEFRAME_HOURS.get(timeframe_name, 0), 2),
                    "ZF_Score": round(float(row["ZF_Score"]), 4),
                    "Drift": round(float(row["D_res"]), 4),
                    "Fibo_Position": round(float(row.get("Fibo_Position", np.nan)), 4),
                    "Fibo_Aligned": bool(row.get("Fibo_Aligned", False)),
                    "Decay_Integral": round(float(row["Decay_Integral"]), 4),
                    "Regime": row["Regime"],
                    "Inflection_Detected": bool(row["Inflection_Detected"]),
                    "SL_TP_Model": model + ("_TRAILING" if use_trailing else ""),
                }
            )

    if not trades:
        return [], {"Symbol": symbol_name, "Timeframe": timeframe_name, "Asset_Class": classify_symbol(symbol_name), "Signals": 0}

    trades_df = pd.DataFrame(trades)
    wins = int((trades_df["Result"].isin(["WIN", "TP_HIT"])).sum())
    losses = int(trades_df["Result"].isin(["LOSS", "LOSS_BOTH_HIT"]).sum())
    expired = int(trades_df["Result"].isin(["EXPIRED", "NOT_HIT", "NOT_FILLED"]).sum())
    total = int(len(trades_df))
    resolved = wins + losses
    summary = {
        "Symbol": symbol_name,
        "Timeframe": timeframe_name,
        "Asset_Class": classify_symbol(symbol_name),
        "Exit_Mode": exit_mode,
        "Signals": total,
        "Wins": wins,
        "Losses": losses,
        "Expired": expired,
        "Win_Rate_Resolved": round(wins / resolved * 100, 2) if resolved else 0.0,
        "Win_Rate_All": round(wins / total * 100, 2) if total else 0.0,
        "Expectancy_R": round(float(trades_df["R_Result"].mean()), 4),
        "Avg_RR": round(float(trades_df["RR_Ratio"].mean()), 2),
        "Avg_Bars_To_Result": round(float(trades_df["Bars_To_Result"].mean()), 2),
        "Avg_Hours_To_Result": round(float(trades_df["Hours_To_Result"].mean()), 2) if "Hours_To_Result" in trades_df else np.nan,
    }
    return trades, summary


def get_symbols(limit_symbols=None, asset_classes=None):
    all_symbols = mt5.symbols_get()
    if all_symbols is None:
        return []

    allowed_classes = asset_classes or parse_csv_set(os.getenv("ZF_ASSET_CLASSES", DEFAULT_ASSET_CLASSES))
    suffixes = parse_csv_set(os.getenv("MT5_SYMBOL_SUFFIXES", ""))
    symbols = []
    for item in all_symbols:
        name = getattr(item, "name", "")
        if not name:
            continue
        if suffixes and not any(name.lower().endswith(suffix) for suffix in suffixes):
            continue
        if classify_symbol(name) not in allowed_classes:
            continue
        symbols.append(name)
    symbols = sorted(set(symbols))
    if limit_symbols:
        requested = {sym.strip() for sym in limit_symbols.split(",") if sym.strip()}
        symbols = [sym for sym in symbols if sym in requested]
    return symbols


def attach_selection_score(summary_df):
    if summary_df.empty:
        return summary_df
    df = summary_df.copy()

    def numeric_column(name, default=0.0):
        if name not in df.columns:
            return pd.Series(default, index=df.index, dtype=float)
        return pd.to_numeric(df[name], errors="coerce").fillna(default)

    signals = numeric_column("Signals")
    win_rate = numeric_column("Win_Rate_Resolved")
    expectancy = numeric_column("Expectancy_R")
    avg_rr = numeric_column("Avg_RR")
    signal_factor = np.clip(signals / 100, 0, 1)
    df["Selection_Score"] = (
        win_rate * 0.50
        + np.clip(50 + expectancy * 150, 0, 100) * 0.32
        + np.clip(avg_rr / 2.0 * 100, 0, 100) * 0.10
        + signal_factor * 100 * 0.08
    ).round(2)
    invalid_rows = signals <= 0
    if "Error" in df.columns:
        invalid_rows = invalid_rows | df["Error"].fillna("").astype(str).ne("")
    df.loc[invalid_rows, "Selection_Score"] = 0.0
    return df


def write_primary_symbols(summary_df, top_n, summary_path):
    full_ranked = summary_df.sort_values(
        by=["Selection_Score", "Win_Rate_Resolved", "Expectancy_R", "Signals"],
        ascending=[False, False, False, False],
        na_position="last",
    ).copy()
    signals = (
        pd.to_numeric(full_ranked["Signals"], errors="coerce").fillna(0)
        if "Signals" in full_ranked.columns
        else pd.Series(0, index=full_ranked.index, dtype=float)
    )
    expectancy = (
        pd.to_numeric(full_ranked["Expectancy_R"], errors="coerce").fillna(0)
        if "Expectancy_R" in full_ranked.columns
        else pd.Series(0, index=full_ranked.index, dtype=float)
    )
    ranked = full_ranked[(signals >= 100) & (expectancy > 0)].copy()
    if ranked.empty:
        ranked = full_ranked.copy()
    elif len(ranked) < top_n:
        ranked = pd.concat([ranked, full_ranked[~full_ranked["Symbol"].isin(ranked["Symbol"])]], ignore_index=True)
    primary_symbols = ranked.drop_duplicates(subset=["Symbol"])["Symbol"].dropna().astype(str).head(top_n).tolist()
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now().astimezone().isoformat(),
        "source": str(summary_path),
        "top_n": top_n,
        "asset_classes": sorted(set(ranked.get("Asset_Class", pd.Series(dtype=str)).dropna().astype(str))),
        "primary_symbols": primary_symbols,
    }
    with PRIMARY_SYMBOLS_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=True, indent=2)
    return primary_symbols


def summarize_timeframe(trades_df):
    rows = []
    if trades_df.empty:
        return pd.DataFrame(rows)
    for timeframe, group in trades_df.groupby("Timeframe"):
        tp_only = bool(group["Result"].isin(["TP_HIT", "NOT_HIT"]).any())
        wins = int((group["Result"].isin(["WIN", "TP_HIT"])).sum())
        losses = int(group["Result"].isin(["LOSS", "LOSS_BOTH_HIT"]).sum())
        expired = int(group["Result"].isin(["EXPIRED", "NOT_HIT"]).sum())
        resolved = int(len(group)) if tp_only else wins + losses
        rows.append(
            {
                "Timeframe": timeframe,
                "Metric": "TP_Hit_Rate" if tp_only else "Win_Rate_Resolved",
                "Signals": int(len(group)),
                "Wins": wins,
                "Losses": losses,
                "Expired": expired,
                "Win_Rate_Resolved": round(wins / resolved * 100, 2) if resolved else 0.0,
                "Expectancy_R": round(float(group["R_Result"].mean()), 4) if "R_Result" in group else 0.0,
            }
        )
    return pd.DataFrame(rows).sort_values(by=["Expectancy_R", "Win_Rate_Resolved"], ascending=[False, False])


def summarize_tp_targets(trades_df):
    rows = []
    if trades_df.empty or "TP_Pips" not in trades_df.columns:
        return pd.DataFrame(rows)
    for (timeframe, tp_pips), group in trades_df.groupby(["Timeframe", "TP_Pips"]):
        total = int(len(group))
        hits = int((group["Result"] == "TP_HIT").sum())
        hit_df = group[group["Result"] == "TP_HIT"]
        rows.append(
            {
                "Timeframe": timeframe,
                "TP_Pips": tp_pips,
                "Signals": total,
                "TP_Hits": hits,
                "Not_Hit": total - hits,
                "TP_Hit_Rate": round(hits / total * 100, 2) if total else 0.0,
                "Avg_Bars_To_TP": round(float(hit_df["Bars_To_Result"].mean()), 2) if not hit_df.empty else np.nan,
                "Avg_Hours_To_TP": round(float(hit_df["Hours_To_Result"].mean()), 2) if not hit_df.empty else np.nan,
                "Median_Hours_To_TP": round(float(hit_df["Hours_To_Result"].median()), 2) if not hit_df.empty else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values(by=["TP_Hit_Rate", "Avg_Hours_To_TP"], ascending=[False, True], na_position="last")


def main():
    parser = argparse.ArgumentParser(description="ZF historical validator for multi-timeframe scanner signals.")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="Historical lookback in days.")
    parser.add_argument("--horizon-bars", type=int, default=DEFAULT_HORIZON_BARS, help="Bars allowed for TP/SL resolution.")
    parser.add_argument("--timeframes", default=DEFAULT_TIMEFRAME, help="Comma-separated timeframes, e.g. M30,H4,W1.")
    parser.add_argument("--window-profile", default=DEFAULT_WINDOW_PROFILE, help="ZF window profile: auto, standard, compact.")
    parser.add_argument("--exit-mode", choices=["dynamic_sl_tp", "tp_only"], default="dynamic_sl_tp", help="Backtest exit model.")
    parser.add_argument("--tp-pips", default=DEFAULT_TP_ONLY_PIPS, help="Comma-separated TP targets for tp_only mode, e.g. 50,70.")
    parser.add_argument("--symbols", default="", help="Optional comma-separated symbols, e.g. EURUSD.m,XAUUSD.m")
    parser.add_argument("--asset-classes", default=os.getenv("ZF_ASSET_CLASSES", DEFAULT_ASSET_CLASSES), help="Comma-separated classes: forex,metal,energy.")
    parser.add_argument("--zf-floor", type=float, default=float(os.getenv("ZF_VALIDATION_ZF_FLOOR", "0") or 0), help="Minimum ZF_Score required for a signal.")
    parser.add_argument("--min-drift", type=float, default=float(os.getenv("ZF_VALIDATION_MIN_DRIFT", "0") or 0), help="Minimum D_res required for a signal.")
    parser.add_argument("--require-regime", default=os.getenv("ZF_VALIDATION_REQUIRE_REGIME", ""), help="Require market regime, e.g. TREND or RANGE.")
    parser.add_argument("--fibo-filter", action="store_true", help="Require ZF-Fibo re-entry alignment.")
    parser.add_argument("--trailing", action="store_true", help="Use historical trailing stop simulation.")
    parser.add_argument("--top-n", type=int, default=int(os.getenv("ZF_ACTIVE_SYMBOL_LIMIT", DEFAULT_TOP_N)), help="Number of best symbols to save for live scanner.")
    parser.add_argument("--write-primary-profile", action="store_true", help="Save ranked Top N symbols to zf_profiles/primary_symbols.json.")
    args = parser.parse_args()

    if not mt5.initialize():
        print("CRITICAL ERROR: MetaTrader 5 tidak terbuka atau tidak bisa diinisialisasi.")
        return

    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=args.days)
    asset_classes = parse_csv_set(args.asset_classes)
    symbols = get_symbols(args.symbols, asset_classes=asset_classes)
    if not symbols:
        print("Tidak ada symbol yang cocok untuk divalidasi.")
        mt5.shutdown()
        return

    timeframes = [item.strip().upper() for item in args.timeframes.split(",") if item.strip()]
    tp_only_pips = parse_float_list(args.tp_pips)
    print(f"[ZF HISTORICAL VALIDATOR] Membaca {len(symbols)} symbol ({','.join(sorted(asset_classes))}), {args.days} hari.")
    print(f"[ZF HISTORICAL VALIDATOR] Timeframe test: {', '.join(timeframes)} | horizon {args.horizon_bars} candle per timeframe.")
    print(f"[ZF HISTORICAL VALIDATOR] Exit mode: {args.exit_mode}" + (f" | TP targets: {tp_only_pips} pips tanpa SL" if args.exit_mode == "tp_only" else ""))
    print(
        f"[ZF HISTORICAL VALIDATOR] Filters: zf_floor={args.zf_floor:g}, min_drift={args.min_drift:g}, "
        f"require_regime={args.require_regime or '-'}, fibo_filter={args.fibo_filter}, trailing={args.trailing}"
    )

    all_trades = []
    summaries = []
    for timeframe_name in timeframes:
        try:
            normalized_tf, mt5_timeframe = timeframe_to_mt5(timeframe_name)
            active_profile, estimated_bars, warmup_bars = configure_window_profile(args.window_profile, normalized_tf, args.days)
        except ValueError as exc:
            print(f"  SKIP {timeframe_name}: {exc}")
            continue

        print(f"\n[TF {normalized_tf}] window={active_profile} estimated_bars={estimated_bars} warmup={warmup_bars}")
        for symbol in symbols:
            trades, summary = validate_symbol(
                symbol,
                start_dt,
                end_dt,
                args.horizon_bars,
                timeframe_name=normalized_tf,
                mt5_timeframe=mt5_timeframe,
                warmup_bars=warmup_bars,
                exit_mode=args.exit_mode,
                tp_only_pips=tp_only_pips,
                zf_floor=args.zf_floor,
                min_drift=args.min_drift,
                require_regime=args.require_regime,
                fibo_filter=args.fibo_filter,
                use_trailing=args.trailing,
            )
            all_trades.extend(trades)
            summaries.append(summary)
            print(
                f"  {symbol:<10} tf={normalized_tf:<3} signals={summary.get('Signals', 0)} "
                f"win_resolved={summary.get('Win_Rate_Resolved', 0)} expectancy={summary.get('Expectancy_R', 0)}"
            )

    mt5.shutdown()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_path = REPORT_DIR / f"zf_validation_summary_{stamp}.csv"
    trades_path = REPORT_DIR / f"zf_validation_trades_{stamp}.csv"

    summary_df = attach_selection_score(pd.DataFrame(summaries))
    summary_df = summary_df.sort_values(
        by=["Selection_Score", "Win_Rate_Resolved", "Expectancy_R", "Signals"],
        ascending=[False, False, False, False],
        na_position="last",
    )
    trades_df = pd.DataFrame(all_trades)
    summary_df.to_csv(summary_path, index=False)
    trades_df.to_csv(trades_path, index=False)
    timeframe_summary = summarize_timeframe(trades_df)
    timeframe_summary_path = REPORT_DIR / f"zf_validation_timeframes_{stamp}.csv"
    timeframe_summary.to_csv(timeframe_summary_path, index=False)
    tp_summary = summarize_tp_targets(trades_df) if args.exit_mode == "tp_only" else pd.DataFrame()
    tp_summary_path = REPORT_DIR / f"zf_validation_tp_targets_{stamp}.csv"
    if args.exit_mode == "tp_only":
        tp_summary.to_csv(tp_summary_path, index=False)
    primary_symbols = write_primary_symbols(summary_df, args.top_n, summary_path) if args.write_primary_profile else []

    print("\n========================================================")
    print("ZF HISTORICAL VALIDATION COMPLETE")
    print("========================================================")
    print(f"Summary CSV: {summary_path}")
    print(f"Trades CSV : {trades_path}")
    print(f"Timeframe CSV: {timeframe_summary_path}")
    if args.exit_mode == "tp_only":
        print(f"TP Target CSV: {tp_summary_path}")
    if not timeframe_summary.empty:
        print("\nTIMEFRAME PERFORMANCE")
        for row in timeframe_summary.itertuples(index=False):
            print(
                f"  {row.Timeframe:<4} signals={row.Signals:<5} "
                f"win_resolved={row.Win_Rate_Resolved:.2f}% expectancy={row.Expectancy_R:.4f}R"
            )
    if primary_symbols:
        print(f"Primary Top {len(primary_symbols)}: {', '.join(primary_symbols)}")
        print(f"Primary Profile: {PRIMARY_SYMBOLS_PATH}")
    if args.exit_mode == "tp_only" and not tp_summary.empty:
        print("\nTP-ONLY PERFORMANCE")
        for row in tp_summary.itertuples(index=False):
            avg_hours = "NA" if pd.isna(row.Avg_Hours_To_TP) else f"{row.Avg_Hours_To_TP:.2f}h"
            median_hours = "NA" if pd.isna(row.Median_Hours_To_TP) else f"{row.Median_Hours_To_TP:.2f}h"
            print(
                f"  {row.Timeframe:<4} TP={row.TP_Pips:g} pips | hit={row.TP_Hit_Rate:.2f}% "
                f"({row.TP_Hits}/{row.Signals}) | avg={avg_hours} median={median_hours}"
            )
    if not trades_df.empty:
        wins = int((trades_df["Result"].isin(["WIN", "TP_HIT"])).sum())
        losses = int(trades_df["Result"].isin(["LOSS", "LOSS_BOTH_HIT"]).sum())
        expired = int(trades_df["Result"].isin(["EXPIRED", "NOT_HIT"]).sum())
        resolved = wins + losses
        print(f"Total Signals: {len(trades_df)}")
        if args.exit_mode == "tp_only":
            print(f"TP Hit / Not Hit: {wins}/{expired}")
            print(f"TP Hit Rate: {wins / len(trades_df) * 100:.2f}%")
        else:
            print(f"Wins/Losses/Expired: {wins}/{losses}/{expired}")
            print(f"Resolved Win Rate: {wins / resolved * 100:.2f}%" if resolved else "Resolved Win Rate: 0.00%")
            print(f"Expectancy R: {trades_df['R_Result'].mean():.4f}")
    if args.exit_mode == "tp_only":
        print("Catatan: Mode TP-only tidak memakai stop loss; hasil ini mengukur peluang dan waktu menuju TP, bukan risiko floating/drawdown.")
    else:
        print("Catatan: Jika TP dan SL tersentuh dalam candle yang sama, validator menghitung LOSS secara konservatif.")


if __name__ == "__main__":
    main()
