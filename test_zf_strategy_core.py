import unittest

import numpy as np
import pandas as pd

from zf_strategy_core import (
    ZFStrategyParams,
    calculate_trend_series,
    calculate_trend_state,
    calculate_wilder_adx,
    prepare_zf_dataframe,
)


class StrategyCoreTests(unittest.TestCase):
    def setUp(self):
        size = 240
        close = np.linspace(1.0, 1.2, size) + np.sin(np.arange(size) / 8) * 0.002
        self.rates = pd.DataFrame(
            {
                "time": np.arange(size) + 1_700_000_000,
                "open": close - 0.0002,
                "high": close + 0.0010,
                "low": close - 0.0010,
                "close": close,
                "tick_volume": np.linspace(100, 200, size),
                "spread": np.full(size, 10),
            }
        )

    def test_wilder_adx_has_expected_columns(self):
        result = calculate_wilder_adx(self.rates, 14)
        self.assertEqual({"tr", "atr", "plus_di", "minus_di", "adx"}, set(result.columns))
        self.assertGreater(result["adx"].notna().sum(), 0)

    def test_shared_frame_produces_bounded_score(self):
        frame = prepare_zf_dataframe(self.rates, ZFStrategyParams())
        score = frame["ZF_Score"].dropna()
        core_score = frame["ZF_Core_Score"].dropna()
        self.assertGreater(len(score), 0)
        self.assertTrue(score.between(0, 1).all())
        self.assertGreater(len(core_score), 0)
        self.assertTrue(core_score.between(0, 1).all())
        self.assertIn("minus_di", frame.columns)
        self.assertIn("Inflection_Detected", frame.columns)

    def test_trend_engine_recognizes_persistent_uptrend(self):
        state = calculate_trend_state(self.rates)
        self.assertEqual("BUY", state["bias"])
        self.assertGreater(state["score"], 35)
        series = calculate_trend_series(self.rates)
        self.assertEqual(len(self.rates), len(series))


if __name__ == "__main__":
    unittest.main()
