"""Tests for multi-signal risk scoring and the human-review gate"""
from django.test import SimpleTestCase
from documents.risk_scoring import compute_risk

VALID = "123412341234"    # passes Verhoeff
INVALID = "123412341235"  # fails Verhoeff


class RiskScoringTests(SimpleTestCase):

    def test_all_signals_clean_is_low_risk_and_not_reviewed(self):
        r = compute_risk(VALID, True, 0.95, 0.0, [])
        self.assertEqual(r['risk_level'], 'low')
        self.assertFalse(r['needs_review'])

    def test_llm_authentic_but_checksum_fails_is_high_and_flagged(self):
        r = compute_risk(INVALID, True, 0.95, 0.0, [])
        self.assertEqual(r['risk_level'], 'high')
        self.assertTrue(r['needs_review'])
        self.assertTrue(any('checksum' in x for x in r['review_reasons']))

    def test_llm_authentic_but_yolo_finds_tampering_is_flagged(self):
        r = compute_risk(VALID, True, 0.9, 0.9, [])
        self.assertTrue(r['needs_review'])

    def test_low_llm_confidence_is_flagged(self):
        r = compute_risk(VALID, True, 0.3, 0.0, [])
        self.assertTrue(r['needs_review'])

    def test_missing_number_is_flagged_and_checksum_dropped(self):
        r = compute_risk(None, True, 0.95, 0.0, [])
        self.assertIsNone(r['signals']['checksum'])
        self.assertTrue(r['needs_review'])

    def test_no_llm_verdict_is_flagged(self):
        r = compute_risk(VALID, None, None, 0.0, [])
        self.assertTrue(r['needs_review'])

    def test_cv_indicators_alone_cannot_make_high_risk(self):
        r = compute_risk(VALID, True, 0.95, 0.0, ['a compression', 'noise', 'edge', 'copy-paste'])
        self.assertNotEqual(r['risk_level'], 'high')
