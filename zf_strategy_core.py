"""Shared, deterministic ZF strategy calculations for live scanning and backtests."""

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ZFStrategyParams:
    hma_period: int = 20
    decay_window: int = 30
    threshold_window: int = 50
    threshold_sigma: float = 1.50
    confirmation_bars: int = 1
    volume_window: int = 20
    drift_window: int = 50
    atr_period: int = 14
    adx_period: int = 14
    fibo_lookback: int = 96
    fibo_buy_max: float = 0.70
    fibo_sell_min: float = 0.30
    zf_floor: float = 0.45
    min_reward_risk: float = 1.25
    atr_sl_multiplier: float = 1.35
    drift_sl_multiplier: float = 1.15
    atr_tp_multiplier: float = 1.80
    drift_tp_multiplier: float = 1.60
    trend_sl_multiplier: float = 1.20
    range_sl_multiplier: float = 0.95
    trend_tp_multiplier: float = 1.25
    range_tp_multiplier: float = 0.90


def calculate_hma(series, period=20):
    period = max(int(period), 2)
    half_period = max(int(period / 2), 1)
    sqrt_period = max(int(np.sqrt(period)), 1)
    weights_half = np.arange(1, half_period + 1)
    weights_full = np.arange(1, period + 1)
    weights_sqrt = np.arange(1, sqrt_period + 1)
    wma_half = series.rolling(half_period).apply(
        lambda values: np.dot(values, weights_half) / weights_half.sum(), raw=True
    )
    wma_full = series.rolling(period).apply(
        lambda values: np.dot(values, weights_full) / weights_full.sum(), raw=True
    )
    raw_hma = (2 * wma_half) - wma_full
    return raw_hma.rolling(sqrt_period).apply(
        lambda values: np.dot(values, weights_sqrt) / weights_sqrt.sum(), raw=True
    )


def calculate_wilder_adx(df, period=14):
    period = max(int(period), 2)
    high = pd.to_numeric(df["high"], errors="coerce")
    low = pd.to_numeric(df["low"], errors="coerce")
    close = pd.to_numeric(df["close"], errors="coerce")
    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index)
    alpha = 1.0 / period
    atr = true_range.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    plus_smoothed = plus_dm.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    minus_smoothed = minus_dm.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    plus_di = 100.0 * plus_smoothed / atr.replace(0, np.nan)
    minus_di = 100.0 * minus_smoothed / atr.replace(0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    return pd.DataFrame(
        {"tr": true_range, "atr": atr, "plus_di": plus_di, "minus_di": minus_di, "adx": adx},
        index=df.index,
    )


def calculate_trend_series(rates, fast_period=50, slow_period=200, structure_lookback=20):
    """Build a causal per-bar trend score suitable for walk-forward joins."""
    df = pd.DataFrame(rates).copy()
    if df.empty:
        return pd.DataFrame()
    if "time" in df and not pd.api.types.is_datetime64_any_dtype(df["time"]):
        df["time"] = pd.to_datetime(df["time"], unit="s", errors="coerce")
    for column in ("high", "low", "close"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    close = df["close"]
    ema_fast = close.ewm(span=fast_period, adjust=False).mean()
    ema_slow = close.ewm(span=slow_period, adjust=False).mean()
    hma = calculate_hma(close, 20)
    adx_frame = calculate_wilder_adx(df, 14)
    atr = adx_frame["atr"].replace(0, np.nan)

    location = (((close - ema_slow) / atr) * 12.0).clip(-25, 25)
    ma_alignment = pd.Series(np.where(ema_fast > ema_slow, 15.0, -15.0), index=df.index)
    slope_distance = 8
    slope = (hma - hma.shift(slope_distance)) / slope_distance
    slope_score = ((slope / atr) * 180.0).clip(-25, 25)
    di_score = ((adx_frame["plus_di"] - adx_frame["minus_di"]) * 0.8).clip(-20, 20)
    recent_high = df["high"].rolling(structure_lookback).max()
    recent_low = df["low"].rolling(structure_lookback).min()
    previous_high = recent_high.shift(structure_lookback)
    previous_low = recent_low.shift(structure_lookback)
    bullish_structure = (recent_high > previous_high) & (recent_low > previous_low)
    bearish_structure = (recent_high < previous_high) & (recent_low < previous_low)
    structure_score = pd.Series(
        np.select([bullish_structure, bearish_structure], [15.0, -15.0], default=0.0),
        index=df.index,
    )
    structure = pd.Series(
        np.select([bullish_structure, bearish_structure], ["HH_HL", "LH_LL"], default="MIXED"),
        index=df.index,
    )
    score = (location + ma_alignment + slope_score + di_score + structure_score).clip(-100, 100)
    result = pd.DataFrame(
        {
            "time": df.get("time", pd.Series(df.index, index=df.index)),
            "Trend_Score": score,
            "Trend_Bias": np.select([score >= 35, score <= -35], ["BUY", "SELL"], default="RANGE"),
            "Trend_Structure": structure,
            "Trend_ADX": adx_frame["adx"],
            "Trend_Plus_DI": adx_frame["plus_di"],
            "Trend_Minus_DI": adx_frame["minus_di"],
        }
    )
    return result


def calculate_trend_state(rates, fast_period=50, slow_period=200, structure_lookback=20):
    """Return the latest state from the same causal trend formula used in tests."""
    df = pd.DataFrame(rates)
    if df.empty or len(df) < slow_period + 10:
        return {
            "score": 0.0,
            "bias": "RANGE",
            "strength": 0.0,
            "structure": "UNKNOWN",
            "adx": 0.0,
        }
    series = calculate_trend_series(df, fast_period, slow_period, structure_lookback)
    latest = series.iloc[-1]
    score = float(latest["Trend_Score"]) if pd.notna(latest["Trend_Score"]) else 0.0
    adx_value = float(latest["Trend_ADX"]) if pd.notna(latest["Trend_ADX"]) else 0.0
    source = pd.DataFrame(rates)
    close = pd.to_numeric(source["close"], errors="coerce")
    ema_fast = close.ewm(span=fast_period, adjust=False).mean()
    ema_slow = close.ewm(span=slow_period, adjust=False).mean()
    hma = calculate_hma(close, 20)
    atr = calculate_wilder_adx(source, 14)["atr"].replace(0, np.nan)
    slope = (hma.iloc[-1] - hma.iloc[-9]) / 8
    if score >= 35:
        bias = "BUY"
    elif score <= -35:
        bias = "SELL"
    else:
        bias = "RANGE"
    return {
        "score": round(score, 2),
        "bias": bias,
        "strength": round(abs(score), 2),
        "structure": latest["Trend_Structure"],
        "adx": round(adx_value, 2),
        "plus_di": round(float(latest["Trend_Plus_DI"]), 2),
        "minus_di": round(float(latest["Trend_Minus_DI"]), 2),
        "ema_fast": float(ema_fast.iloc[-1]),
        "ema_slow": float(ema_slow.iloc[-1]),
        "hma_slope_atr": round(float(slope / atr.iloc[-1]), 4) if pd.notna(atr.iloc[-1]) else 0.0,
    }


def prepare_zf_dataframe(
    rates,
    params=None,
    lambda_liquidity=1.0,
    liquidity_stress=0.0,
    external_stress=0.0,
    crypto=False,
):
    params = params or ZFStrategyParams()
    df = pd.DataFrame(rates).copy()
    if "time" in df:
        if not pd.api.types.is_datetime64_any_dtype(df["time"]):
            df["time"] = pd.to_datetime(df["time"], unit="s", errors="coerce")
    for column in ("open", "high", "low", "close", "tick_volume"):
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df["P_pure"] = calculate_hma(df["close"], params.hma_period)
    df["D_res"] = ((df["close"] - df["P_pure"]).abs() / df["P_pure"].replace(0, np.nan)) * 100
    df["Polarity"] = np.where(df["close"] >= df["P_pure"], 1.0, -1.0)
    df["Lambda_Liquidity"] = float(lambda_liquidity)
    df["Decay_Integral"] = (
        df["Lambda_Liquidity"] * df["D_res"] * df["Polarity"]
    ).rolling(params.decay_window).sum()
    df["Integral_Mean"] = df["Decay_Integral"].rolling(params.threshold_window).mean()
    df["Integral_Std"] = df["Decay_Integral"].rolling(params.threshold_window).std()
    df["Upper_Threshold"] = df["Integral_Mean"] + params.threshold_sigma * df["Integral_Std"]
    df["Lower_Threshold"] = df["Integral_Mean"] - params.threshold_sigma * df["Integral_Std"]

    df["V_avg"] = df["tick_volume"].rolling(params.volume_window).mean()
    df["V_abs"] = (df["tick_volume"] - df["V_avg"]).abs()
    volume_component = (df["V_abs"] / df["tick_volume"].replace(0, np.nan)).clip(0, 1)
    # Buku Besar Bab 4.3: (Vabs / Vtotal) * tanh(Dres). MT5 candle
    # volume is only a proxy for true order-book Vtotal, so keep this score
    # separate from the calibrated operational score used by the strategy.
    df["ZF_Core_Score"] = (
        volume_component * np.tanh(df["D_res"].clip(lower=0))
    ).clip(0, 1)
    drift_mean = df["D_res"].rolling(params.drift_window).mean()
    drift_std = df["D_res"].rolling(params.drift_window).std().replace(0, np.nan)
    drift_component = (((df["D_res"] - drift_mean) / drift_std).abs() / 3.0).clip(0, 1)
    if crypto:
        df["ZF_Score"] = (
            0.35 * volume_component
            + 0.25 * drift_component
            + 0.15 * float(liquidity_stress)
            + 0.25 * float(external_stress)
        ).clip(0, 1)
    else:
        df["ZF_Score"] = (
            0.45 * volume_component
            + 0.35 * drift_component
            + 0.20 * float(liquidity_stress)
        ).clip(0, 1)

    adx = calculate_wilder_adx(df, params.adx_period)
    for column in adx:
        df[column] = adx[column]
    df["Regime"] = np.where(df["adx"] >= 20.0, "TREND", "RANGE")
    df["Swing_High"] = df["high"].rolling(params.fibo_lookback, min_periods=max(params.hma_period, 20)).max()
    df["Swing_Low"] = df["low"].rolling(params.fibo_lookback, min_periods=max(params.hma_period, 20)).min()
    fib_range = (df["Swing_High"] - df["Swing_Low"]).replace(0, np.nan)
    df["Fibo_Position"] = ((df["close"] - df["Swing_Low"]) / fib_range).clip(0, 1)
    df["Fibo_382"] = df["Swing_Low"] + fib_range * 0.382
    df["Fibo_500"] = df["Swing_Low"] + fib_range * 0.500
    df["Fibo_618"] = df["Swing_Low"] + fib_range * 0.618
    df["Velocity"] = df["close"].diff()
    df["Acceleration"] = df["Velocity"].diff()
    acceleration_scale = df["Acceleration"].abs().rolling(20).median().replace(0, np.nan)
    near_zero = df["Acceleration"].abs() <= acceleration_scale * 0.20
    zero_cross = np.sign(df["Acceleration"]) != np.sign(df["Acceleration"].shift(1))
    df["Inflection_Detected"] = (near_zero | zero_cross).fillna(False)
    return df


def signal_direction(df, index, params=None, use_fibo=True):
    params = params or ZFStrategyParams()
    if index < params.confirmation_bars - 1:
        return "NEUTRAL", "WARMUP"
    window = df.iloc[index - params.confirmation_bars + 1 : index + 1]
    if window.empty or window[["Decay_Integral", "Upper_Threshold", "Lower_Threshold", "ZF_Score"]].isna().any().any():
        return "NEUTRAL", "WARMUP"
    buy = bool((window["Decay_Integral"] < window["Lower_Threshold"]).all())
    sell = bool((window["Decay_Integral"] > window["Upper_Threshold"]).all())
    direction = "BUY" if buy else "SELL" if sell else "NEUTRAL"
    if direction == "NEUTRAL":
        return direction, "NO_RESONANCE"
    row = df.iloc[index]
    if float(row["ZF_Score"]) < params.zf_floor:
        return "NEUTRAL", "ZF_FLOOR"
    fibo_position = float(row["Fibo_Position"])
    fibo_ok = (
        direction == "BUY" and fibo_position <= params.fibo_buy_max
    ) or (
        direction == "SELL" and fibo_position >= params.fibo_sell_min
    )
    if use_fibo and not fibo_ok:
        return "NEUTRAL", "FIBO_BLOCK"
    return direction, "STRICT"


def dynamic_distances(row, symbol_info, params=None):
    params = params or ZFStrategyParams()
    point = float(getattr(symbol_info, "point", 0.0) or 0.0)
    digits = int(getattr(symbol_info, "digits", 5) or 5)
    pip_size = point * (10 if digits in (3, 5) else 1)
    if pip_size <= 0:
        return np.nan, np.nan
    atr_pips = float(row["atr"]) / pip_size
    drift_pips = abs(float(row["close"]) - float(row["P_pure"])) / pip_size
    regime = str(row.get("Regime", "RANGE"))
    sl = max(atr_pips * params.atr_sl_multiplier, drift_pips * params.drift_sl_multiplier)
    sl *= params.trend_sl_multiplier if regime == "TREND" else params.range_sl_multiplier
    structure_tp = max(atr_pips * params.atr_tp_multiplier, drift_pips * params.drift_tp_multiplier)
    structure_tp *= params.trend_tp_multiplier if regime == "TREND" else params.range_tp_multiplier
    tp = max(structure_tp, sl * params.min_reward_risk)
    return round(sl, 1), round(tp, 1)


def pending_entry_price(row, direction):
    if direction == "BUY":
        return float(min(row["Fibo_500"], row["Fibo_618"], row["close"]))
    return float(max(row["Fibo_382"], row["Fibo_500"], row["close"]))


def simulate_pending_trade(
    df,
    signal_index,
    direction,
    entry,
    sl_pips,
    tp_pips,
    symbol_info,
    expiry_bars=4,
    horizon_bars=96,
    trailing=True,
    spread_pips=0.0,
    slippage_pips=0.0,
    commission_r=0.0,
):
    point = float(getattr(symbol_info, "point", 0.0) or 0.0)
    digits = int(getattr(symbol_info, "digits", 5) or 5)
    pip_size = point * (10 if digits in (3, 5) else 1)
    if pip_size <= 0 or sl_pips <= 0 or tp_pips <= 0:
        return {"Result": "INVALID", "R_Result": 0.0}
    fill_index = None
    expiry_index = min(signal_index + max(int(expiry_bars), 1), len(df) - 1)
    for idx in range(signal_index + 1, expiry_index + 1):
        if float(df.iloc[idx]["low"]) <= entry <= float(df.iloc[idx]["high"]):
            fill_index = idx
            break
    if fill_index is None:
        return {"Result": "NOT_FILLED", "R_Result": 0.0, "Bars_To_Result": expiry_index - signal_index}

    effective_entry = entry + ((spread_pips / 2 + slippage_pips) * pip_size if direction == "BUY" else -(spread_pips / 2 + slippage_pips) * pip_size)
    sl_distance = sl_pips * pip_size
    tp_distance = tp_pips * pip_size
    sl_price = effective_entry - sl_distance if direction == "BUY" else effective_entry + sl_distance
    tp_price = effective_entry + tp_distance if direction == "BUY" else effective_entry - tp_distance
    active_sl = sl_price
    trail_active = False
    max_index = min(fill_index + max(int(horizon_bars), 1), len(df) - 1)

    for idx in range(fill_index, max_index + 1):
        high = float(df.iloc[idx]["high"])
        low = float(df.iloc[idx]["low"])
        if direction == "BUY":
            hit_sl = low <= active_sl
            hit_tp = high >= tp_price
        else:
            hit_sl = high >= active_sl
            hit_tp = low <= tp_price
        if hit_sl and hit_tp:
            hit_tp = False  # Conservative ordering when tick sequence is unknown.
        if hit_sl:
            gross_r = (
                (active_sl - effective_entry) / sl_distance
                if direction == "BUY"
                else (effective_entry - active_sl) / sl_distance
            )
            return {
                "Result": "WIN" if gross_r > 0 else "LOSS",
                "R_Result": round(gross_r - commission_r, 4),
                "Bars_To_Result": idx - signal_index,
                "Fill_Index": fill_index,
            }
        if hit_tp:
            return {
                "Result": "WIN",
                "R_Result": round(tp_pips / sl_pips - commission_r, 4),
                "Bars_To_Result": idx - signal_index,
                "Fill_Index": fill_index,
            }
        if trailing:
            if direction == "BUY" and high - effective_entry >= sl_distance * 0.75:
                trail_active = True
                active_sl = max(active_sl, high - sl_distance * 0.55)
            elif direction == "SELL" and effective_entry - low >= sl_distance * 0.75:
                trail_active = True
                active_sl = min(active_sl, low + sl_distance * 0.55)

    final_close = float(df.iloc[max_index]["close"])
    gross_r = (
        (final_close - effective_entry) / sl_distance
        if direction == "BUY"
        else (effective_entry - final_close) / sl_distance
    )
    return {
        "Result": "EXPIRED",
        "R_Result": round(gross_r - commission_r, 4),
        "Bars_To_Result": max_index - signal_index,
        "Fill_Index": fill_index,
        "Trail_Active": trail_active,
    }
