"""Walk-forward calibration for ZF Core using broker MT5 bars and realistic pending fills."""

import argparse
import itertools
import json
from dataclasses import asdict, replace
from datetime import datetime, timedelta
from pathlib import Path

import MetaTrader5 as mt5
import numpy as np
import pandas as pd

from zf_strategy_core import (
    ZFStrategyParams,
    calculate_trend_series,
    dynamic_distances,
    pending_entry_price,
    prepare_zf_dataframe,
    signal_direction,
    simulate_pending_trade,
)


BASE_DIR = Path(__file__).resolve().parent
PROFILE_PATH = BASE_DIR / "zf_profiles" / "calibration_profile.json"
REPORT_DIR = BASE_DIR / "zf_validation_reports"
TIMEFRAMES = {"M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1}


def load_primary_symbols(limit):
    path = BASE_DIR / "zf_profiles" / "primary_symbols.json"
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        symbols = payload.get("primary_symbols", [])
        if symbols:
            return symbols[:limit]
    return [item.name for item in mt5.symbols_get() if item.visible][:limit]


def symbol_spread_pips(symbol_info, rates):
    digits = int(symbol_info.digits)
    point = float(symbol_info.point)
    pip_points = 10 if digits in (3, 5) else 1
    if "spread" not in rates.dtype.names:
        return 0.0
    values = pd.Series(rates["spread"]).replace(0, np.nan).dropna()
    return float(values.median() / pip_points) if not values.empty else 0.0


def evaluate(df, symbol_info, params, expiry_bars, start_index, end_index, spread_pips, use_trend=True):
    trades = []
    next_allowed = start_index
    commission_r = 0.015
    buy_raw = df["Decay_Integral"] < df["Lower_Threshold"]
    sell_raw = df["Decay_Integral"] > df["Upper_Threshold"]
    if params.confirmation_bars > 1:
        buy_raw = buy_raw.rolling(params.confirmation_bars).sum() == params.confirmation_bars
        sell_raw = sell_raw.rolling(params.confirmation_bars).sum() == params.confirmation_bars
    zf_ok = df["ZF_Score"] >= params.zf_floor
    buy_mask = buy_raw & zf_ok & (df["Fibo_Position"] <= params.fibo_buy_max)
    sell_mask = sell_raw & zf_ok & (df["Fibo_Position"] >= params.fibo_sell_min)
    candidate_indices = np.flatnonzero((buy_mask | sell_mask).to_numpy())
    lower = max(start_index, 150)
    upper = min(end_index, len(df) - 2)
    for idx in candidate_indices:
        if idx < lower or idx >= upper:
            continue
        if idx < next_allowed:
            continue
        direction = "BUY" if bool(buy_mask.iloc[idx]) else "SELL"
        if use_trend and "MTF_Trend_Score" in df:
            trend_score = float(df.iloc[idx].get("MTF_Trend_Score", 0.0) or 0.0)
            trend_bias = "BUY" if trend_score >= 35 else "SELL" if trend_score <= -35 else "RANGE"
            if trend_bias in ("BUY", "SELL") and direction != trend_bias and abs(trend_score) >= 45:
                continue
        sl_pips, tp_pips = dynamic_distances(df.iloc[idx], symbol_info, params=params)
        entry = pending_entry_price(df.iloc[idx], direction)
        outcome = simulate_pending_trade(
            df,
            idx,
            direction,
            entry,
            sl_pips,
            tp_pips,
            symbol_info,
            expiry_bars=expiry_bars,
            horizon_bars=96,
            trailing=True,
            spread_pips=spread_pips,
            slippage_pips=max(spread_pips * 0.10, 0.05),
            commission_r=commission_r,
        )
        outcome.update({"Signal_Index": idx, "Direction": direction, "Reason": "STRICT"})
        trades.append(outcome)
        if "Fill_Index" in outcome:
            next_allowed = idx + max(int(outcome.get("Bars_To_Result", 1)), 1)
    if not trades:
        return {"signals": 0, "filled": 0, "expectancy_r": -9.0, "win_rate": 0.0, "profit_factor": 0.0, "score": -99.0}
    frame = pd.DataFrame(trades)
    filled = frame[frame["Result"] != "NOT_FILLED"].copy()
    if filled.empty:
        return {"signals": len(frame), "filled": 0, "expectancy_r": -9.0, "win_rate": 0.0, "profit_factor": 0.0, "score": -99.0}
    returns = pd.to_numeric(filled["R_Result"], errors="coerce").fillna(0.0)
    wins = returns[returns > 0]
    losses = returns[returns < 0]
    expectancy = float(returns.mean())
    win_rate = float((returns > 0).mean() * 100)
    profit_factor = float(wins.sum() / abs(losses.sum())) if abs(losses.sum()) > 0 else (9.0 if wins.sum() > 0 else 0.0)
    sample_penalty = min(len(filled) / 30.0, 1.0)
    score = (expectancy * 50.0 + min(profit_factor, 3.0) * 5.0 + win_rate * 0.08) * sample_penalty
    return {
        "signals": int(len(frame)),
        "filled": int(len(filled)),
        "expectancy_r": round(expectancy, 4),
        "win_rate": round(win_rate, 2),
        "profit_factor": round(profit_factor, 3),
        "score": round(score, 4),
    }


def calibrate_symbol(symbol, timeframe, days):
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        return None, []
    end = datetime.now()
    start = end - timedelta(days=days)
    rates = mt5.copy_rates_range(symbol, TIMEFRAMES[timeframe], start, end)
    if rates is None or len(rates) < 600:
        return None, []
    spread_pips = symbol_spread_pips(symbol_info, rates)
    base_df = pd.DataFrame(rates)
    base_df["time"] = pd.to_datetime(base_df["time"], unit="s")
    trend_frames = {}
    for trend_name, trend_tf in (("H1", mt5.TIMEFRAME_H1), ("H4", mt5.TIMEFRAME_H4)):
        trend_rates = mt5.copy_rates_range(symbol, trend_tf, start - timedelta(days=45), end)
        trend_frames[trend_name] = calculate_trend_series(trend_rates) if trend_rates is not None else pd.DataFrame()
    split = int(len(base_df) * 0.70)
    candidates = []
    grid = itertools.product(
        (1.25, 1.50, 1.75),
        (1, 2),
        (0.40, 0.50),
        ((0.75, 0.25),),
        (1.20, 1.40),
        (6,),
    )
    frame_cache = {}
    for sigma, confirmations, zf_floor, fibo_bounds, rr, expiry in grid:
        fib_buy, fib_sell = fibo_bounds
        params = replace(
            ZFStrategyParams(),
            threshold_sigma=sigma,
            confirmation_bars=confirmations,
            zf_floor=zf_floor,
            fibo_buy_max=fib_buy,
            fibo_sell_min=fib_sell,
            min_reward_risk=rr,
        )
        if sigma not in frame_cache:
            frame = prepare_zf_dataframe(base_df, params=params).sort_values("time")
            for trend_name, trend_frame in trend_frames.items():
                if trend_frame.empty:
                    frame[f"{trend_name}_Trend_Score"] = 0.0
                    continue
                right = trend_frame[["time", "Trend_Score"]].dropna().sort_values("time").rename(
                    columns={"Trend_Score": f"{trend_name}_Trend_Score"}
                )
                frame = pd.merge_asof(frame, right, on="time", direction="backward")
            h4_scores = pd.to_numeric(frame["H4_Trend_Score"], errors="coerce").fillna(0)
            h1_scores = pd.to_numeric(frame["H1_Trend_Score"], errors="coerce").fillna(0)
            frame["MTF_Trend_Score"] = h4_scores * 0.58 + h1_scores * 0.42
            frame_cache[sigma] = frame
        df = frame_cache[sigma]
        train = evaluate(df, symbol_info, params, expiry, 0, split, spread_pips)
        if train["filled"] < 8 or train["expectancy_r"] <= 0:
            continue
        test = evaluate(df, symbol_info, params, expiry, split, len(df), spread_pips)
        if test["filled"] < 8 or test["expectancy_r"] <= 0 or test["profit_factor"] <= 1.0:
            continue
        stability = min(train["expectancy_r"], test["expectancy_r"])
        score = test["score"] + stability * 30.0 - abs(train["expectancy_r"] - test["expectancy_r"]) * 8.0
        candidates.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "expiry_bars": expiry,
                "spread_pips": round(spread_pips, 3),
                "params": asdict(params),
                "train": train,
                "test": test,
                "walk_forward_score": round(score, 4),
            }
        )
    candidates.sort(key=lambda item: (item["walk_forward_score"], item["test"]["filled"]), reverse=True)
    return (candidates[0] if candidates else None), candidates[:10]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--timeframe", choices=sorted(TIMEFRAMES), default="M15")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--symbols", default="")
    args = parser.parse_args()
    if not mt5.initialize():
        raise SystemExit("MT5 tidak dapat diinisialisasi.")
    symbols = [item.strip() for item in args.symbols.split(",") if item.strip()] or load_primary_symbols(args.limit)
    selected = {}
    report_rows = []
    for symbol in symbols:
        print(f"Calibrating {symbol}...")
        best, candidates = calibrate_symbol(symbol, args.timeframe, args.days)
        if best:
            selected[symbol] = best
            report_rows.extend(candidates)
            print(f"  test E={best['test']['expectancy_r']}R PF={best['test']['profit_factor']} n={best['test']['filled']}")
        else:
            print("  tidak ada konfigurasi stabil yang lolos.")
    mt5.shutdown()
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now().astimezone().isoformat(),
        "method": "70/30 chronological walk-forward, causal H1/H4 trend context, pending Fibonacci fills, costs, conservative intrabar ordering",
        "days": args.days,
        "timeframe": args.timeframe,
        "symbols": selected,
    }
    PROFILE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if report_rows:
        flat_rows = []
        for row in report_rows:
            flat_rows.append(
                {
                    "Symbol": row["symbol"],
                    "Timeframe": row["timeframe"],
                    "Walk_Forward_Score": row["walk_forward_score"],
                    "Train_Filled": row["train"]["filled"],
                    "Train_Expectancy_R": row["train"]["expectancy_r"],
                    "Test_Filled": row["test"]["filled"],
                    "Test_Win_Rate": row["test"]["win_rate"],
                    "Test_Expectancy_R": row["test"]["expectancy_r"],
                    "Test_Profit_Factor": row["test"]["profit_factor"],
                    "Sigma": row["params"]["threshold_sigma"],
                    "Confirmations": row["params"]["confirmation_bars"],
                    "ZF_Floor": row["params"]["zf_floor"],
                    "Fibo_Buy_Max": row["params"]["fibo_buy_max"],
                    "Fibo_Sell_Min": row["params"]["fibo_sell_min"],
                    "Min_RR": row["params"]["min_reward_risk"],
                    "Expiry_Bars": row["expiry_bars"],
                }
            )
        pd.DataFrame(flat_rows).to_csv(REPORT_DIR / f"zf_calibration_{stamp}.csv", index=False)
    print(f"Calibration profile: {PROFILE_PATH}")


if __name__ == "__main__":
    main()
