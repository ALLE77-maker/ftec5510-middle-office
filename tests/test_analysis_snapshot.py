from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_UP, localcontext
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError

from examples.ai.consistent_analysis import build_explanation_context, fetch_analysis
from middle_office.client import Client
from middle_office.server import Server
from middle_office.service import MiddleOffice
from middle_office.validation import amount, iso


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'ledger.sqlite3'
        self.now = datetime(2026, 11, 19, 6, tzinfo=timezone.utc)
        self.office = MiddleOffice(self.path, clock=lambda: self.now)
        self.office.create_account('alice', {'initial_balances': {'USDT': '10000'}, 'initial_positions': [
            {'symbol': 'BTC/USDT', 'quantity': '0.01', 'average_cost': '60000'}]})
        self.quote()

    def tearDown(self):
        self.temp.cleanup()

    def quote(self, price='68000', source='demo_a'):
        self.office.ingest_quotes({'quotes': [{'symbol': 'BTC/USDT', 'source': source,
                                              'price': price, 'as_of': iso(self.now)}]})

    def test_shared_sources_and_canonical_amounts(self):
        self.now += timedelta(seconds=1)
        self.quote('70000', 'demo_b')
        self.office.place_order('alice', {'request_id': 'pending', 'symbol': 'BTC/USDT',
                                        'side': 'sell', 'quantity': '0.005',
                                        'order_type': 'limit', 'limit_price': '80000'})
        report = self.office.analysis_snapshot('alice')
        portfolio = report['portfolio']
        self.assertEqual(report['as_of'], report['account']['as_of'])
        self.assertEqual(report['as_of'], portfolio['as_of'])
        self.assertEqual(portfolio['valuation_quotes'][0]['source'], 'demo_b')
        self.assertEqual(portfolio['positions'][0]['market_price'], '70000')
        self.assertEqual(portfolio['total_assets'], '10700')
        context = build_explanation_context(report)
        self.assertEqual(context['official_numbers']['total_assets'], '10700')
        self.assertEqual(context['official_numbers']['unrealized_pnl'], '100')
        self.assertEqual(context['snapshot_id'], report['snapshot_id'])
        self.assertEqual(context['auxiliary_statistics']['sell_orders_returned'], 1)
        context['official_positions'][0]['market_value'] = '0'
        self.assertEqual(portfolio['positions'][0]['market_value'], '700')

    def test_one_evaluation_clock_even_at_freshness_boundary(self):
        calls = []

        def advancing_clock():
            calls.append(True)
            return self.now if len(calls) == 1 else self.now + timedelta(seconds=121)

        self.office.clock = advancing_clock
        report = self.office.analysis_snapshot('alice')
        self.assertEqual(len(calls), 1)
        self.assertEqual(report['state'], 'ok')
        self.assertEqual(report['portfolio']['total_assets'], '10680')

    def test_partial_quotes_preserve_unknown_totals(self):
        self.now += timedelta(seconds=121)
        report = self.office.analysis_snapshot('alice')
        context = build_explanation_context(report)
        self.assertEqual(report['state'], 'partial')
        self.assertIsNone(context['official_numbers']['total_assets'])
        self.assertIsNone(context['official_numbers']['unrealized_pnl'])
        self.assertEqual(context['valuation_quotes'], [])
        self.assertEqual(context['position_risk']['position_metrics'], [])

    def test_old_response_stays_frozen_after_new_quotes_and_fills(self):
        before = self.office.analysis_snapshot('alice')
        frozen = deepcopy(before)
        self.now += timedelta(seconds=1)
        self.quote('70000', 'demo_b')
        self.office.place_order('alice', {'request_id': 'buy', 'symbol': 'BTC/USDT',
                                        'side': 'buy', 'quantity': '0.01'})
        after = self.office.analysis_snapshot('alice')
        self.assertNotEqual(before['snapshot_id'], after['snapshot_id'])
        self.assertEqual(before, frozen)
        self.assertEqual(before['portfolio']['positions'][0]['quantity'], '0.01')
        self.assertEqual(after['portfolio']['positions'][0]['quantity'], '0.02')
        self.assertEqual(build_explanation_context(before)['official_numbers']['total_assets'], '10680')

    def test_single_database_snapshot_during_concurrent_write(self):
        staged = threading.Event()
        errors = []
        original = self.office._portfolio

        def write():
            try:
                with self.office.store.transaction(write=True) as state:
                    state['accounts']['alice']['balances']['USDT'] = '9000'
                    state['quotes']['BTC/USDT@demo_a']['price'] = '70000'
                    staged.set()
            except BaseException as error:
                errors.append(error)

        writer = threading.Thread(target=write)

        def intercept(state, user, *, as_of=None):
            result = original(state, user, as_of=as_of)
            writer.start()
            self.assertTrue(staged.wait(2))
            return result

        self.office._portfolio = intercept
        try:
            report = self.office.analysis_snapshot('alice')
        finally:
            self.office._portfolio = original
            if writer.ident is not None:
                writer.join(5)
        self.assertFalse(writer.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(report['portfolio']['total_assets'], '10680')
        self.assertEqual(report['account']['positions'][1]['quantity'], '10000')
        self.assertEqual(report['portfolio']['valuation_quotes'][0]['price'], '68000')
        self.assertEqual(self.office.analysis_snapshot('alice')['portfolio']['total_assets'], '9700')

    def test_official_risk_values_match_monitoring_evidence(self):
        self.office.create_account('risk_user', {'initial_balances': {'USDT': '100'},
                                               'initial_positions': [{'symbol': 'BTC/USDT', 'quantity': '0.01',
                                                                      'average_cost': '100000'}]})
        alerts = self.office.alerts('risk_user')
        report = self.office.analysis_snapshot('risk_user')
        metrics = {row['rule']: row for row in report['risk']['position_metrics']}
        for alert in alerts:
            if alert['category'] == 'position_risk':
                metric = metrics[alert['evidence']['rule']]
                self.assertTrue(metric['breached'])
                self.assertEqual(metric['value'], alert['evidence']['value'])
                self.assertEqual(metric['threshold'], alert['evidence']['threshold'])
        self.assertTrue(metrics['loss_pct']['breached'])
        self.assertTrue(metrics['concentration_pct']['breached'])

    def test_snapshot_id_detects_mixed_or_changed_response(self):
        report = self.office.analysis_snapshot('alice')
        report['portfolio']['total_assets'] = '1'
        with self.assertRaisesRegex(ValueError, 'content ID mismatch'):
            build_explanation_context(report)

    def test_explicit_rounding_does_not_depend_on_caller(self):
        with localcontext() as context:
            context.rounding = ROUND_UP
            self.assertEqual(amount(Decimal('0.000000005')), '0')

    def test_read_only_http_adapter_and_legacy_snapshot(self):
        server = Server(('127.0.0.1', 0), self.office, token='test-operator', read_token='test-reader')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            report = fetch_analysis(base + '/api', 'alice', 'test-reader')
            self.assertEqual(report['portfolio']['total_assets'], '10680')
            reader = Client(base, 'test-reader')
            old = reader.request('GET', '/api/accounts/alice/snapshot')
            self.assertEqual(set(old), {'as_of', 'positions', 'open_orders', 'truncated'})
            self.assertEqual(reader.request('GET', '/api/accounts/alice/analysis_snapshot')['state'], 'ok')
            with self.assertRaisesRegex(RuntimeError, 'HTTP 403'):
                reader.request('POST', '/api/accounts/alice/analysis_snapshot', {})
            with self.assertRaisesRegex(RuntimeError, 'HTTP 403'):
                reader.request('GET', '/api/accounts/alice/alerts')
            with self.assertRaises(HTTPError) as error:
                fetch_analysis(base + '/api', 'alice', 'wrong')
            error.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
