import importlib.util
import json
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("gpu_trial_log", Path(__file__).resolve().parents[1] / "scripts/check_gpu_trial_log.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class GPUTrialLogGateTests(unittest.TestCase):
    def test_cuda_error_colon_variant_is_not_a_clean_completed_stage(self):
        for message in ['CUDA error: out of memory', 'CUDA error:  out of memory', 'cuda error: out of memory']:
            with self.subTest(message=message):
                result = gate.inspect_log('Prefill batch\nRuntimeError: ' + message + '\nDecode batch')
                self.assertFalse(result['passed'])
                self.assertEqual(result['diagnosticCounts']['cudaOutOfMemory'], 1)

    def test_completed_stage_does_not_hide_earlier_allocator_warning(self):
        result = gate.inspect_log("Prefill batch\nmemory mapping failed with OOM on device 0\nDecode batch\nHTTP 200")
        self.assertFalse(result["passed"])
        self.assertEqual(result["diagnosticCounts"]["allocatorMappingWarnings"], 1)

    def test_normal_inference_and_unrelated_startup_warning(self):
        self.assertTrue(gate.inspect_log("UserWarning: deprecated launch command\nPrefill batch\nDecode batch")["passed"])

    def test_no_inference_evidence_is_not_a_clean_gpu_result(self):
        for text in ["", "HTTP 200", "server Ready"]:
            self.assertFalse(gate.inspect_log(text)["passed"])

    def test_fatal_diagnostics_and_no_raw_log_disclosure(self):
        text = "Prefill batch\nprivate prompt body\nCUDA out of memory\nAssertionError\nTraceback (most recent call last)"
        result = gate.inspect_log(text)
        self.assertFalse(result["passed"])
        self.assertNotIn("private prompt", json.dumps(result))
        self.assertEqual(result["diagnosticCounts"]["tracebacks"], 1)


if __name__ == "__main__":
    unittest.main()
