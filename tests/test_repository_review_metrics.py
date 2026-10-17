from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]/'scripts'))
from repository_review_metrics import turn_stats


class TurnMetricsTests(unittest.TestCase):
    def test_cold_turn_keeps_its_own_counters(self):
        self.assertEqual(turn_stats({'projection': {'sessionStats': {'decodeTokens': 4000}}}), {'decodeTokens': 4000})

    def test_continuation_does_not_double_count_previous_generation(self):
        r = {'continuedSession': True, 'projection': {'sessionStats': {'decodeTokens': 7000, 'decodeMs': 220000}}}
        self.assertEqual(turn_stats(r, {'decodeTokens': 4000, 'decodeMs': 130000}),
                         {'decodeTokens': 3000, 'decodeMs': 90000})

    def test_missing_or_wrong_baseline_fails_closed(self):
        r = {'continuedSession': True, 'projection': {'sessionStats': {'decodeTokens': 3000}}}
        with self.assertRaises(ValueError): turn_stats(r)
        with self.assertRaises(ValueError): turn_stats(r, {'decodeTokens': 4000})


if __name__ == '__main__': unittest.main()
