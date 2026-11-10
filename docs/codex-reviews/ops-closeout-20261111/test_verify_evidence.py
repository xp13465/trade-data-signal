import copy
import json
from pathlib import Path
import unittest
from verify_evidence import check


class EvidenceNegativeControls(unittest.TestCase):
    def setUp(self):
        self.facts = json.loads(Path(__file__).with_name('facts.json').read_text())

    def test_real_receipts_consistent(self):
        self.assertTrue(check(self.facts)['evidence_consistent'])

    def test_same_counts_wrong_backup_run_rejected(self):
        self.facts['backup_restore']['results'][0]['run_id'] = 'different-run'
        self.assertFalse(check(self.facts)['evidence_consistent'])

    def test_same_length_different_hash_rejected(self):
        self.facts['backup_restore']['results'][0]['raw']['sha256'] = '0' * 64
        self.assertFalse(check(self.facts)['evidence_consistent'])

    def test_duplicate_database_cannot_claim_four(self):
        rows = self.facts['backup_restore']['results']
        rows[3] = copy.deepcopy(rows[0])
        self.assertFalse(check(self.facts)['evidence_consistent'])

    def test_nonempty_overwrite_rejected(self):
        self.facts['fund_recovery']['changes'][0]['before'] = 1.0
        self.assertFalse(check(self.facts)['evidence_consistent'])

    def test_changed_bucket_other_fund_rejected(self):
        self.facts['fund_recovery']['other_codes_unchanged'] = False
        self.assertFalse(check(self.facts)['evidence_consistent'])

    def test_novel_missing_key_rejected(self):
        self.facts['history']['audit_compare']['added'] = ['unexpected-key']
        self.assertFalse(check(self.facts)['evidence_consistent'])

    def test_old_evidence_cannot_claim_deployed(self):
        self.facts['source_deployed'] = True
        self.assertFalse(check(self.facts)['evidence_consistent'])


if __name__ == '__main__':
    unittest.main()
