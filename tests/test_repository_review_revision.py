import hashlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1]/'scripts'))
from assess_repository_revision import assess
from prepare_repository_review_revision import REVISION_RULES


class RevisionAcceptanceTests(unittest.TestCase):
    def fixture(self):
        result = {'assistantText': 'original response'}
        mechanical = {'mechanicalAcceptancePassed': True, 'requestedWordRangeMet': True,
                      'answers': [{'quoteCharacters': 40}]}
        review = {'assistantTextSHA256': hashlib.sha256(b'original response').hexdigest(),
                  'completed': True, 'allMaterialClaimsReviewed': True, 'findings': [],
                  'priorFindingChecks': {f'N{i}': {'resolved': True} for i in range(1, 8)}}
        return result, mechanical, review

    def test_missing_source_review_cannot_be_accepted(self):
        r, m, _ = self.fixture()
        self.assertFalse(assess(r, m, {})['accepted'])

    def test_changed_output_invalidates_previous_review(self):
        r, m, v = self.fixture(); r['assistantText'] += ' added claim'
        self.assertFalse(assess(r, m, v)['accepted'])

    def test_open_finding_prevents_acceptance(self):
        r, m, v = self.fixture(); v['findings'] = [{'issue': 'unsupported claim'}]
        self.assertFalse(assess(r, m, v)['accepted'])

    def test_revision_short_quote_limit_is_enforced(self):
        r, m, v = self.fixture(); m['answers'][0]['quoteCharacters'] = 170
        self.assertFalse(assess(r, m, v)['accepted'])

    def test_all_recorded_conditions_are_required(self):
        r, m, v = self.fixture()
        self.assertTrue(assess(r, m, v)['accepted'])
        m['requestedWordRangeMet'] = False
        self.assertFalse(assess(r, m, v)['accepted'])

    def test_contract_addresses_provenance_not_answers(self):
        self.assertIn('policies can combine additively', REVISION_RULES)
        self.assertIn('Source absence cannot prove a negative', REVISION_RULES)
        self.assertNotIn('expectedValue', REVISION_RULES)


if __name__ == '__main__': unittest.main()
