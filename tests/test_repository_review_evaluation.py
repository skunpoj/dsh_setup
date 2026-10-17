import copy
import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('review_evaluator', Path(__file__).parents[1]/'scripts/evaluate_repository_review.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


class CitationAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.blocks = [{'id': f'S{i:04}', 'repo': 'fixture', 'path': f'file-{i}.py',
            'content': 'ANSWER = 42\nSecond line'} for i in range(1, 9)]
        self.key = [{'id': 'Q01', 'expectedValue': '42', 'sourceId': 'S0001', 'supportLine': 1}]
        self.answer = {'answers': [{'id': 'Q01', 'value': '42', 'citation': {
            'source_id': 'S0001', 'start_line': 1, 'end_line': 1, 'quote': 'ANSWER = 42'}}],
            'report_markdown': 'word '*1100+' '.join(f'[S{i:04}:L1-L1]' for i in range(1, 9))}
        self.result = {'status': 'completed', 'persistedPromptMatches': True,
            'lastUsage': {'inputTokens': 990000, 'outputTokens': 2500}}

    def check(self, answer=None, result=None):
        result = copy.deepcopy(result or self.result)
        result['assistantText'] = json.dumps(answer or self.answer)
        return module.evaluate(result, self.key, self.blocks)[0]

    def test_complete_mechanical_fixture_passes(self):
        self.assertTrue(self.check()['mechanicalAcceptancePassed'])

    def test_correct_value_with_wrong_revision_source_fails(self):
        a = copy.deepcopy(self.answer); a['answers'][0]['citation']['source_id'] = 'S0002'
        self.assertFalse(self.check(a)['mechanicalAcceptancePassed'])

    def test_fabricated_quote_fails_even_with_correct_value(self):
        a = copy.deepcopy(self.answer); a['answers'][0]['citation']['quote'] = 'ANSWER = 43'
        self.assertFalse(self.check(a)['mechanicalAcceptancePassed'])

    def test_nonexistent_report_line_fails(self):
        a = copy.deepcopy(self.answer); a['report_markdown'] += ' [S0001:L99-L100]'
        self.assertFalse(self.check(a)['mechanicalAcceptancePassed'])

    def test_malformed_combined_span_cannot_hide_from_range_checks(self):
        a = copy.deepcopy(self.answer); a['report_markdown'] += ' [S0001:L1-L1;L2-L2]'
        value = self.check(a)
        self.assertFalse(value['mechanicalAcceptancePassed'])
        self.assertEqual(value['malformedReportCitations'], ['[S0001:L1-L1;L2-L2]'])

    def test_valid_single_line_report_citations_are_supported(self):
        a = copy.deepcopy(self.answer); a['report_markdown'] = a['report_markdown'].replace(':L1-L1]', ':L1]')
        self.assertTrue(self.check(a)['mechanicalAcceptancePassed'])

    def test_duplicate_answer_cannot_inflate_score(self):
        a = copy.deepcopy(self.answer); a['answers'].append(copy.deepcopy(a['answers'][0]))
        self.assertFalse(self.check(a)['mechanicalAcceptancePassed'])

    def test_short_output_does_not_qualify_long_generation(self):
        r = copy.deepcopy(self.result); r['lastUsage']['outputTokens'] = 8
        self.assertFalse(self.check(result=r)['mechanicalAcceptancePassed'])

    def test_small_input_does_not_qualify_near_million(self):
        r = copy.deepcopy(self.result); r['lastUsage']['inputTokens'] = 120000
        self.assertFalse(self.check(result=r)['mechanicalAcceptancePassed'])


if __name__ == '__main__': unittest.main()
