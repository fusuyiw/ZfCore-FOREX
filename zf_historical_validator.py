import argparse
from datetime import datetime, timedelta
from pathlib import Path

import MetaTrader5 as mt5
import numpy as np
import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
REPORT_DIR = BASE_DIR / "zf_validation_reports"

TF_CORE = mt5.TIMEFRAME_M30
SCAN_BARS_WARMUP = 120
DEFAULT_DAYS = 365
DEFAULT_HORIZON_BARS = 16
DEFAULT_RISK_REWARD = 1.25

ATR_SL_MULTIPLIER = 1.35
DRIFT_SL_MULTIPLIER = 1.15
ATR_TP_MULTIPLIER = 1.80
DRIFT_TP_MULTIPLIER = 1.60
TREND_SL_MULTIPLIER = 1.20
RANGE_SL_MULTIPLIER = 0.95
TREND_TP_MULTIPLIER = 1.25
RANGE_TP_MULTIPLIER = 0.90
ZF_DRIFT_ZSCORE_SCALE = 3.0


def calculate_hma(series, period=20):
    half_period = int(period / 2)
    sqrt_period = int(np.sqrt(period))

    def wma(s, p):
        weights = np.arange(1, p + 1)
        return s.rolling(p).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)

    raw_hma = 2 * wma(series, half_period) - wma(series, period)
    return wma(raw_hma, sqrt_period)


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
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")

    df["P_pure"] = calculate_hma(df["close"], period=20)
    df["D_res"] = (abs(df["close"] - df["P_pure"]) / df["P_pure"]) * 100
    df["Polarity"] = np.where(df["close"] > df["P_pure"], 1, -1)
    df["Decay_Integral"] = (df["D_res"] * df["Polarity"]).rolling(window=30).sum()
    df["Integral_Mean"] = df["Decay_Integral"].rolling(window=50).mean()
    df["Integral_Std"] = df["Decay_Integral"].rolling(window=50).std()
    df["Upper_Threshold"] = df["Integral_Mean"] + (2 * df["Integral_Std"])
    df["Lower_Threshold"] = df["Integral_Mean"] - (2 * df["Integral_Std"])

    df["V_avg"] = df["tick_volume"].rolling(window=20).mean()
    df["V_abs"] = abs(df["tick_volume"] - df["V_avg"])
    df["drift_mean"] = df["D_res"].rolling(window=50).mean()
    df["drift_std"] = df["D_res"].rolling(window=50).std()

    safe_tick_volume = df["tick_volume"].replace(0, np.nan)
    safe_drift_std = df["drift_std"].replace(0, np.nan)
    volume_component = np.clip(df["V_abs"] / safe_tick_volume, 0, 1)
    drift_zscore = ((df["D_res"] - df["drift_mean"]) / safe_drift_std).abs()
    drift_component = np.clip(drift_zscore / ZF_DRIFT_ZSCORE_SCALE, 0, 1)
    df["ZF_Score"] = np.clip((0.45 * volume_component) + (0.35 * drift_component), 0, 1)

    df["tr"] = np.maximum(
        df["high"] - df["low"],
        np.maximum(abs(df["high"] - df["close"].shift(1)), abs(df["low"] - df["close"].shift(1))),
    )
    df["atr"] = df["tr"].rolling(window=14).mean()
    df["plus_dm"] = np.where(
        (df["high"] - df["high"].shift(1)) > (df["low"].shift(1) - df["low"]),
        np.maximum(df["high"] - df["high"].shift(1), 0),
        0,
    )
    df["plus_di"] = 100 * (df["plus_dm"].rolling(window=14).mean() / df["atr"])
    df["adx"] = abs(df["plus_di"] - 20)
    df["Regime"] = np.where(df["adx"] > 15, "TREND", "RANGE")

    df["BUY_LOCK"] = (
        (df["Decay_Integral"] < df["Lower_Threshold"])
        & (df["Decay_Integral"].shift(1) < df["Lower_Threshold"].shift(1))
    )
    df["SELL_LOCK"] = (
        (df["Decay_Integral"] > df["Upper_Threshold"])
        & (df["Decay_Integral"].shift(1) > df["Upper_Threshold"].shift(1))
    )
    df["Direction"] = np.select([df["BUY_LOCK"], df["SELL_LOCK"]], ["BUY", "SELL"], default="NEUTRAL")

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


def simulate_trade(df, entry_idx, direction, sl_pips, tp_pips, symbol_info, horizon_bars):
    entry = float(df.loc[entry_idx, "close"])
    sl_distance = pips_to_price(sl_pips, symbol_info)
    tp_distance = pips_to_price(tp_pips, symbol_info)
    if pd.isna(sl_distance) or pd.isna(tp_distance):
        return "INVALID", 0, entry, np.nan, np.nan

    if direction == "BUY":
        sl_price = entry - sl_distance
        tp_price = entry + tp_distance
    else:
        sl_price = entry + sl_distance
        tp_price = entry - tp_distance

    max_idx = min(entry_idx + horizon_bars, len(df) - 1)
    for idx in range(entry_idx + 1, max_idx + 1):
        high = float(df.loc[idx, "high"])
        low = float(df.loc[idx, "low"])

        if direction == "BUY":
            hit_sl = low <= sl_price
            hit_tp = high >= tp_price
        else:
            hit_sl = high >= sl_price
            hit_tp = low <= tp_price

        if hit_sl and hit_tp:
            return "LOSS_BOTH_HIT", idx - entry_idx, entry, sl_price, tp_price
        if hit_sl:
            return "LOSS", idx - entry_idx, entry, sl_price, tp_price
        if hit_tp:
            return "WIN", idx - entry_idx, entry, sl_price, tp_price

    return "EXPIRED", max_idx - entry_idx, entry, sl_price, tp_price


def validate_symbol(symbol_name, start_dt, end_dt, horizon_bars):
    symbol_info = mt5.symbol_info(symbol_name)
    rates = mt5.copy_rates_range(symbol_name, TF_CORE, start_dt, end_dt)
    if rates is None or len(rates) < SCAN_BARS_WARMUP:
        return [], {"Symbol": symbol_name, "Error": "INSUFFICIENT_DATA"}

    df = prepare_zf_dataframe(rates)
    trades = []

    for idx in range(2, len(df) - 1):
        row = df.loc[idx]
        direction = row["Direction"]
        if direction not in ("BUY", "SELL"):
            continue

        sl_pips, tp_pips, model = calculate_historical_sl_tp(row, symbol_info)
        if pd.isna(sl_pips) or pd.isna(tp_pips):
            continue

        result, bars_to_result, entry_price, sl_price, tp_price = simulate_trade(
            df, idx, direction, sl_pips, tp_pips, symbol_info, horizon_bars
        )
        rr_ratio = tp_pips / sl_pips if sl_pips else 0
        r_result = rr_ratio if result == "WIN" else -1 if result in ("LOSS", "LOSS_BOTH_HIT") else 0

        trades.append(
            {
                "Symbol": symbol_name,
                "Signal_Time": row["time"],
                "Direction": direction,
                "Entry": entry_price,
                "SL_Price": sl_price,
                "TP_Price": tp_price,
                "SL_Pips": sl_pips,
                "TP_Pips": tp_pips,
                "RR_Ratio": round(rr_ratio, 2),
                "Result": result,
                "R_Result": round(r_result, 3),
                "Bars_To_Result": bars_to_result,
                "ZF_Score": round(float(row["ZF_Score"]), 4),
                "Drift": round(float(row["D_res"]), 4),
                "Decay_Integral": round(float(row["Decay_Integral"]), 4),
                "Regime": row["Regime"],
                "Inflection_Detected": bool(row["Inflection_Detected"]),
                "SL_TP_Model": model,
            }
        )

    if not trades:
        return [], {"Symbol": symbol_name, "Signals": 0}

    trades_df = pd.DataFrame(trades)
    wins = int((trades_df["Result"] == "WIN").sum())
    losses = int(trades_df["Result"].isin(["LOSS", "LOSS_BOTH_HIT"]).sum())
    expired = int((trades_df["Result"] == "EXPIRED").sum())
    total = int(len(trades_df))
    resolved = wins + losses
    summary = {
        "Symbol": symbol_name,
        "Signals": total,
        "Wins": wins,
        "Losses": losses,
        "Expired": expired,
        "Win_Rate_Resolved": round(wins / resolved * 100, 2) if resolved else 0.0,
        "Win_Rate_All": round(wins / total * 100, 2) if total else 0.0,
        "Expectancy_R": round(float(trades_df["R_Result"].mean()), 4),
        "Avg_RR": round(float(trades_df["RR_Ratio"].mean()), 2),
        "Avg_Bars_To_Result": round(float(trades_df["Bars_To_Result"].mean()), 2),
    }
    return trades, summary


def get_symbols(limit_symbols=None):
    all_symbols = mt5.symbols_get()
    if all_symbols is None:
        return []

    symbols = [
        s.name for s in all_symbols
        if s.name.lower().endswith(".m")
        and any(x in s.name.upper() for x in ["USD", "JPY", "EUR", "GBP", "AUD", "CAD", "CHF", "NZD", "XAU", "XAG"])
    ]
    symbols = sorted(set(symbols))
    if limit_symbols:
        requested = {sym.strip() for sym in limit_symbols.split(",") if sym.strip()}
        symbols = [sym for sym in symbols if sym in requested]
    return symbols


def main():
    parser = argparse.ArgumentParser(description="ZF historical validator for M30 scanner signals.")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="Historical lookback in days.")
    parser.add_argument("--horizon-bars", type=int, default=DEFAULT_HORIZON_BARS, help="Bars allowed for TP/SL resolution.")
    parser.add_argument("--symbols", default="", help="Optional comma-separated symbols, e.g. EURUSD.m,XAUUSD.m")
    args = parser.parse_args()

    if not mt5.initialize():
        print("CRITICAL ERROR: MetaTrader 5 tidak terbuka atau tidak bisa diinisialisasi.")
        return

    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=args.days)
    symbols = get_symbols(args.symbols)
    if not symbols:
        print("Tidak ada symbol yang cocok untuk divalidasi.")
        mt5.shutdown()
        return

    print(f"[ZF HISTORICAL VALIDATOR] Membaca {len(symbols)} symbol, {args.days} hari, horizon {args.horizon_bars} candle M30.")

    all_trades = []
    summaries = []
    for symbol in symbols:
        trades, summary = validate_symbol(symbol, start_dt, end_dt, args.horizon_bars)
        all_trades.extend(trades)
        summaries.append(summary)
        print(f"  {symbol:<10} signals={summary.get('Signals', 0)} win_resolved={summary.get('Win_Rate_Resolved', 0)} expectancy={summary.get('Expectancy_R', 0)}")

    mt5.shutdown()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_path = REPORT_DIR / f"zf_validation_summary_{stamp}.csv"
    trades_path = REPORT_DIR / f"zf_validation_trades_{stamp}.csv"

    summary_df = pd.DataFrame(summaries).sort_values(by="Expectancy_R", ascending=False, na_position="last")
    trades_df = pd.DataFrame(all_trades)
    summary_df.to_csv(summary_path, index=False)
    trades_df.to_csv(trades_path, index=False)

    print("\n========================================================")
    print("ZF HISTORICAL VALIDATION COMPLETE")
    print("========================================================")
    print(f"Summary CSV: {summary_path}")
    print(f"Trades CSV : {trades_path}")
    if not trades_df.empty:
        wins = int((trades_df["Result"] == "WIN").sum())
        losses = int(trades_df["Result"].isin(["LOSS", "LOSS_BOTH_HIT"]).sum())
        expired = int((trades_df["Result"] == "EXPIRED").sum())
        resolved = wins + losses
        print(f"Total Signals: {len(trades_df)}")
        print(f"Wins/Losses/Expired: {wins}/{losses}/{expired}")
        print(f"Resolved Win Rate: {wins / resolved * 100:.2f}%" if resolved else "Resolved Win Rate: 0.00%")
        print(f"Expectancy R: {trades_df['R_Result'].mean():.4f}")
    print("Catatan: Jika TP dan SL tersentuh dalam candle yang sama, validator menghitung LOSS secara konservatif.")


if __name__ == "__main__":
    main()
