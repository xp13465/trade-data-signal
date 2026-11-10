import copy
import datetime as dt
import unittest
import tempfile
import json
from pathlib import Path
from capture_d1_metrics import capture, parse_metrics, window, write_receipt, UTC


class D1CaptureContract(unittest.TestCase):
    day = dt.date(2026, 11, 10)

    def payload(self):
        return {'data': {'viewer': {'accounts': [{'d1AnalyticsAdaptiveGroups': [{
            'dimensions': {'date': '2026-11-10', 'databaseId': 'test-db'},
            'sum': {'rowsRead': 174182, 'rowsWritten': 36152, 'readQueries': 16, 'writeQueries': 2}
        }]}]}}}

    def test_open_day_makes_no_request(self):
        def forbidden():
            self.fail('open UTC day must not query metrics or load credentials')
        result, code = capture(self.day, dt.datetime(2026, 11, 10, 23, 59, 59, tzinfo=UTC), forbidden)
        self.assertEqual(code, 2)
        self.assertEqual(result['state'], 'awaiting_window_close')
        self.assertNotIn('counters', result)

    def test_beijing_eight_is_utc_boundary(self):
        now = dt.datetime(2026, 11, 11, 8, tzinfo=dt.timezone(dt.timedelta(hours=8)))
        self.assertTrue(window(self.day, now)['window_closed'])
        self.assertFalse(window(self.day, now)['platform_finality_verified'])

    def test_closed_does_not_claim_finality_or_savings(self):
        result, code = capture(self.day, dt.datetime(2026, 11, 11, 1, tzinfo=UTC),
                               lambda: parse_metrics(self.payload(), self.day, 'test-db'))
        self.assertEqual(code, 0)
        self.assertEqual(result['counters']['rowsWritten'], 36152)
        self.assertFalse(result['platform_finality_verified'])
        self.assertFalse(result['cost_savings_claimed'])

    def test_bad_identity_missing_or_duplicate_never_zero(self):
        variants = []
        p = self.payload(); p['data']['viewer']['accounts'][0]['d1AnalyticsAdaptiveGroups'][0]['dimensions']['databaseId'] = 'other'; variants.append(p)
        p = self.payload(); p['data']['viewer']['accounts'][0]['d1AnalyticsAdaptiveGroups'][0]['dimensions']['date'] = '2026-11-09'; variants.append(p)
        p = self.payload(); p['data']['viewer']['accounts'][0]['d1AnalyticsAdaptiveGroups'] = []; variants.append(p)
        p = self.payload(); rows = p['data']['viewer']['accounts'][0]['d1AnalyticsAdaptiveGroups']; rows.append(copy.deepcopy(rows[0])); variants.append(p)
        for payload in variants:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    parse_metrics(payload, self.day, 'test-db')

    def test_graphql_errors_override_partial_data(self):
        payload = self.payload(); payload['errors'] = [{'message': 'partial result'}]
        with self.assertRaises(ValueError):
            parse_metrics(payload, self.day, 'test-db')

    def test_non_object_payload_returns_unavailable_receipt(self):
        for payload in (None, [], 'not-an-object', True, 1):
            with self.subTest(payload=payload):
                result, code = capture(
                    self.day, dt.datetime(2026, 11, 11, tzinfo=UTC),
                    lambda: parse_metrics(payload, self.day, 'test-db'))
                self.assertEqual(code, 1)
                self.assertEqual(result['state'], 'unavailable')
                self.assertNotIn('counters', result)

    def test_counter_types_and_missing_rejected(self):
        for value in (True, -1, '36152', None, 2.5):
            with self.subTest(value=value):
                payload = self.payload(); payload['data']['viewer']['accounts'][0]['d1AnalyticsAdaptiveGroups'][0]['sum']['rowsWritten'] = value
                with self.assertRaises(ValueError):
                    parse_metrics(payload, self.day, 'test-db')
        payload = self.payload(); del payload['data']['viewer']['accounts'][0]['d1AnalyticsAdaptiveGroups'][0]['sum']['rowsWritten']
        with self.assertRaises(KeyError):
            parse_metrics(payload, self.day, 'test-db')

    def test_transport_failure_receipt_no_counters(self):
        def fail():
            raise OSError('transport failure')
        result, code = capture(self.day, dt.datetime(2026, 11, 11, tzinfo=UTC), fail)
        self.assertEqual(code, 1)
        self.assertEqual(result['state'], 'unavailable')
        self.assertNotIn('counters', result)

    def test_naive_time_rejected(self):
        with self.assertRaises(ValueError):
            window(self.day, dt.datetime(2026, 11, 11))

    def test_receipt_complete_private_and_create_only(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'receipt.json'
            write_receipt(target, {'state': 'observed'})
            self.assertEqual(json.loads(target.read_text()), {'state': 'observed'})
            self.assertEqual(target.stat().st_mode & 0o077, 0)
            with self.assertRaises(FileExistsError):
                write_receipt(target, {'state': 'replacement'})
            self.assertEqual(json.loads(target.read_text()), {'state': 'observed'})
            self.assertEqual([x.name for x in Path(directory).iterdir()], ['receipt.json'])


if __name__ == '__main__':
    unittest.main()
