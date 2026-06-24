"""Focused historical check for the frequent, small-target ZF Pulse layer."""

from datetime import datetime, timedelta
import json
from pathlib import Path

import MetaTrader5 as mt5
import numpy as np
import pandas as pd

from zf_strategy_core import (
    ZFStrategyParams,
    calculate_trend_series,
    prepare_zf_dataframe,
)


SYMBOLS = ["EURCADm", "GBPCADm", "AUDJPYm", "USDCADm", "GBPNZDm", "CADCHFm"]
PROFILE_PATH = Path(__file__).resolve().parent / "zf_profiles" / "pulse_profile.json"


def evaluate_symbol(symbol, days=60):
    info = mt5.symbol_info(symbol)
    end = datetime.now()
    start = end - timedelta(days=days)
    m15_rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M15, start, end)
    h1_rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_H1, start - timedelta(days=45), end)
    h4_rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_H4, start - timedelta(days=45), end)
    if m15_rates is None or len(m15_rates) < 500:
        return None
    frame = prepare_zf_dataframe(pd.DataFrame(m15_rates), ZFStrategyParams()).sort_values("time")
    for name, rates in (("H1", h1_rates), ("H4", h4_rates)):
        trend = calculate_trend_series(rates)[["time", "Trend_Score"]].dropna().sort_values("time")
        frame = pd.merge_asof(
            frame,
            trend.rename(columns={"Trend_Score": f"{name}_Score"}),
            on="time",
            direction="backward",
        )
    frame["MTF_Score"] = frame["H4_Score"].fillna(0) * 0.58 + frame["H1_Score"].fillna(0) * 0.42
    point = float(info.point)
    pip_size = point * (10 if info.digits in (3, 5) else 1)
    spread_pips = float(pd.Series(m15_rates["spread"]).replace(0, np.nan).median()) / (10 if info.digits in (3, 5) else 1)
    returns = []
    next_index = 220
    for idx in range(220, len(frame) - 20):
        if idx < next_index:
            continue
        row = frame.iloc[idx]
        score = float(row["MTF_Score"])
        direction = "BUY" if score >= 35 else "SELL" if score <= -35 else ""
        if not direction or float(row["ZF_Score"]) < 0.20:
            continue
        price_ok = row["close"] >= row["P_pure"] if direction == "BUY" else row["close"] <= row["P_pure"]
        di_ok = row["plus_di"] >= row["minus_di"] if direction == "BUY" else row["minus_di"] >= row["plus_di"]
        velocity_ok = row["Velocity"] >= -row["atr"] * 0.10 if direction == "BUY" else row["Velocity"] <= row["atr"] * 0.10
        if not (price_ok and di_ok and velocity_ok):
            continue
        entry = float(row["close"])
        sl_distance = max(float(row["atr"]), spread_pips * 2 * pip_size)
        tp_distance = max(float(row["atr"]) * 0.8, spread_pips * 1.5 * pip_size)
        sl = entry - sl_distance if direction == "BUY" else entry + sl_distance
        tp = entry + tp_distance if direction == "BUY" else entry - tp_distance
        result = 0.0
        exit_idx = idx + 16
        for future_idx in range(idx + 1, min(idx + 17, len(frame))):
            high = float(frame.iloc[future_idx]["high"])
            low = float(frame.iloc[future_idx]["low"])
            hit_sl = low <= sl if direction == "BUY" else high >= sl
            hit_tp = high >= tp if direction == "BUY" else low <= tp
            if hit_sl and hit_tp:
                hit_tp = False
            if hit_sl:
                result, exit_idx = -1.0, future_idx
                break
            if hit_tp:
                result, exit_idx = tp_distance / sl_distance, future_idx
                break
        returns.append(result)
        next_index = exit_idx + 1
    if not returns:
        return {"Symbol": symbol, "Trades": 0}
    series = pd.Series(returns)
    wins = int((series > 0).sum())
    losses = int((series < 0).sum())
    gross_profit = float(series[series > 0].sum())
    gross_loss = abs(float(series[series < 0].sum()))
    return {
        "Symbol": symbol,
        "Trades": len(series),
        "Trades_Per_Day": round(len(series) / days, 2),
        "Win_Rate": round(wins / max(wins + losses, 1) * 100, 2),
        "Expectancy_R": round(float(series.mean()), 4),
        "Profit_Factor": round(gross_profit / gross_loss, 3) if gross_loss else 0.0,
    }


def main():
    if not mt5.initialize():
        raise SystemExit("MT5 tidak tersedia.")
    rows = [result for symbol in SYMBOLS if (result := evaluate_symbol(symbol))]
    mt5.shutdown()
    frame = pd.DataFrame(rows)
    print(frame.to_string(index=False))
    enabled = frame[
        (frame["Trades"] >= 30)
        & (frame["Expectancy_R"] >= 0.01)
        & (frame["Profit_Factor"] >= 1.02)
    ]
    payload = {
        "updated_at": datetime.now().astimezone().isoformat(),
        "lookback_days": 60,
        "rules": {"min_trades": 30, "min_expectancy_r": 0.01, "min_profit_factor": 1.02},
        "enabled_symbols": enabled["Symbol"].tolist(),
        "symbols": {row["Symbol"]: row for row in rows},
    }
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nPulse profile: {PROFILE_PATH}")
    print(f"Enabled: {', '.join(payload['enabled_symbols']) or '-'}")


if __name__ == "__main__":
    main()
