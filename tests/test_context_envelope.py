import copy
import importlib.util
from pathlib import Path
import unittest


class ContextEnvelopeTests(unittest.TestCase):
    def test_defaults_are_explicit_without_changing_tools_or_transport(self):
        file = Path(__file__).parents[1]/'scripts/context_envelope.py'
        spec = importlib.util.spec_from_file_location('envelope_test', file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        original = {'model': 'deepseek-v4.1-flash', 'stream': True,
            'messages': [{'role': 'user', 'content': 'synthetic'}],
            'tools': [{'type': 'function', 'function': {'name': 'a',
                'parameters': {'type': 'object', 'additionalProperties': False}}},
                {'type': 'function', 'function': {'name': 'b', 'strict': True}}]}
        expected = copy.deepcopy(original)
        expected['continue_final_message'] = False
        expected['tools'][0]['function']['strict'] = False
        actual = module.normalize_conditioning(copy.deepcopy(original))
        self.assertEqual(actual, expected)
        self.assertEqual(module.normalize_conditioning(actual), expected)


if __name__ == '__main__':
    unittest.main()
