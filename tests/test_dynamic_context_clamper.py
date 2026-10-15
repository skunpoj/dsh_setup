import asyncio
import sys
import types
import unittest
from pathlib import Path


class CustomLogger:
    pass


litellm = types.ModuleType("litellm")
litellm.token_counter = lambda **_: 1000
integrations = types.ModuleType("litellm.integrations")
custom_logger = types.ModuleType("litellm.integrations.custom_logger")
custom_logger.CustomLogger = CustomLogger
sys.modules["litellm"] = litellm
sys.modules["litellm.integrations"] = integrations
sys.modules["litellm.integrations.custom_logger"] = custom_logger

callback_path = Path(__file__).parents[1] / "scripts" / "litellm_custom_callbacks.py"
namespace = {}
exec(callback_path.read_text(encoding="utf-8"), namespace)
clamper = namespace["DynamicContextClamper"]()


def run(data):
    return asyncio.run(clamper.async_pre_call_hook(None, None, data, None))


class DynamicContextClamperTests(unittest.TestCase):
    def setUp(self):
        litellm.token_counter = lambda **_: 1000

    def test_legacy_output_limit_is_clamped_to_deployed_ceiling(self):
        result = run({"messages": [{"role": "user", "content": "hello"}], "max_tokens": 65536})
        self.assertEqual(result["max_tokens"], 8192)

    def test_output_limit_uses_remaining_context_headroom(self):
        litellm.token_counter = lambda **_: 130000
        result = run({"messages": [{"role": "user", "content": "large"}], "max_tokens": 65536})
        self.assertEqual(result["max_tokens"], 816)

    def test_input_that_exhausts_context_is_rejected_before_dispatch(self):
        litellm.token_counter = lambda **_: 130816
        with self.assertRaisesRegex(ValueError, "compact the session"):
            run({"messages": [{"role": "user", "content": "too large"}], "max_tokens": 65536})


if __name__ == "__main__":
    unittest.main()
