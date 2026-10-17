import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]/'scripts'))
from evaluate_narrative_regressions import CASES, evaluate


class NarrativeRegressionTests(unittest.TestCase):
    def setUp(self):
        paths = list(dict.fromkeys(path for path, _ in CASES.values()))
        self.blocks = []
        for i, path in enumerate(paths):
            lines = ['fixture heading']
            if path.endswith('promote_1m_runtimes.py'):
                lines += ['assert hashlib.sha256(original).hexdigest() backup branch', 'if restore:']
            for _, (file, needles) in CASES.items():
                if file == path: lines += [n+' fixture' for n in needles]
            self.blocks.append({'id': f'S{i:04}', 'repo': 'DSH', 'current': True,
                                'path': path, 'content': '\n'.join(lines)})
        self.response = {'claim_checks': [], 'report_markdown': ''}
        for case, (path, needles) in CASES.items():
            b = next(b for b in self.blocks if b['path'] == path)
            lines = b['content'].splitlines()
            floor = lines.index('if restore:')+1 if case == 'ROLLBACK_HASH' else 1
            indices = [next(i for i, line in enumerate(lines, 1) if i >= floor and n in line) for n in needles]
            start, end = min(indices), max(indices)
            self.response['claim_checks'].append({'id': case, 'claim': 'fixture claim',
                'citation': {'source_id': b['id'], 'start_line': start, 'end_line': end,
                             'quote': lines[start-1][:100]}})
            self.response['report_markdown'] += f"[{b['id']}:L{start}-L{end}] "

    def test_correct_branches_are_required(self):
        self.assertTrue(evaluate(self.response, self.blocks)['passed'])

    def test_correct_ledger_cannot_mask_wrong_narrative_span(self):
        c = self.response['claim_checks'][0]['citation']
        self.response['report_markdown'] = self.response['report_markdown'].replace(
            f"[{c['source_id']}:L{c['start_line']}-L{c['end_line']}]", '')
        self.assertFalse(evaluate(self.response, self.blocks)['passed'])

    def test_backup_hash_is_not_restore_hash(self):
        c = self.response['claim_checks'][0]['citation'];c.update(start_line=2, end_line=2)
        self.assertFalse(evaluate(self.response, self.blocks)['passed'])

    def test_invented_quote_is_rejected(self):
        self.response['claim_checks'][0]['citation']['quote'] = 'invented supporting text'
        self.assertFalse(evaluate(self.response, self.blocks)['passed'])

    def test_missing_or_duplicate_ledger_cannot_pass(self):
        self.response['claim_checks'].append(copy.deepcopy(self.response['claim_checks'][0]))
        self.assertFalse(evaluate(self.response, self.blocks)['passed'])
        self.response['claim_checks'] = []
        self.assertFalse(evaluate(self.response, self.blocks)['passed'])


if __name__ == '__main__': unittest.main()
