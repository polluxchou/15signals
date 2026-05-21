import unittest

from backend.aggregation import aggregate_dimensions, overall_intensity, top_signals
from backend.signals_meta import SIGNAL_NAMES


class AggregationTests(unittest.TestCase):
    def test_aggregate_dimensions_averages_each_dimension_and_defaults_missing_scores(self):
        signal_scores = {
            "cognitive_decay": 1.0,
            "attention_scatter": 0.5,
            "emotional_numbness": 0.6,
            "burnout": 0.3,
        }

        result = aggregate_dimensions(signal_scores)

        self.assertEqual(result["cognitive"], 0.5)
        self.assertEqual(result["emotional"], 0.3)
        self.assertEqual(result["existential"], 0.0)

    def test_overall_intensity_returns_rounded_average_as_percent(self):
        signal_scores = {name: 0.0 for name in SIGNAL_NAMES}
        signal_scores["cognitive_decay"] = 1.0
        signal_scores["attention_scatter"] = 0.5

        result = overall_intensity(signal_scores)

        self.assertEqual(result, 10)

    def test_top_signals_returns_highest_signal_with_metadata_when_none_reach_threshold(self):
        signal_scores = {name: 0.0 for name in SIGNAL_NAMES}
        signal_scores["burnout"] = 0.3
        signal_scores["cognitive_decay"] = 0.2

        result = top_signals(signal_scores)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["signal_name"], "burnout")
        self.assertEqual(result[0]["intensity"], 0.3)
        self.assertEqual(result[0]["dimension"], "emotional")
        self.assertEqual(result[0]["display_name_zh"], "倦怠耗竭")


if __name__ == "__main__":
    unittest.main()
