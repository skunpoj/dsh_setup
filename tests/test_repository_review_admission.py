import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]/'scripts'))
from run_repository_accuracy_test import require_idle


class ReviewAdmissionTests(unittest.TestCase):
    def test_yielding_prefill_is_not_idle_when_long_lease_is_held(self):
        with self.assertRaises(RuntimeError):
            require_idle({'metrics': {'sglang:num_running_reqs': 0, 'sglang:num_queue_reqs': 0}}, False)

    def test_free_lease_does_not_override_active_gpu_work(self):
        with self.assertRaises(RuntimeError):
            require_idle({'metrics': {'sglang:num_running_reqs': 1, 'sglang:num_queue_reqs': 0}}, True)

    def test_both_conditions_are_required(self):
        require_idle({'metrics': {'sglang:num_running_reqs': 0, 'sglang:num_queue_reqs': 0}}, True)


if __name__ == '__main__': unittest.main()
