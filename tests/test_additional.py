from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import threading
import unittest

from middle_office.demo import run
from middle_office.client import Client
from middle_office.market import MarketFeed
from middle_office.server import Server
from middle_office.service import MiddleOffice
from middle_office.validation import BusinessError, iso


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.now = datetime.now(timezone.utc)
        self.office = MiddleOffice(Path(self.temp.name) / 'ledger.sqlite3', clock=lambda: self.now)
        self.office.create_account('user', {})
        self.office.ingest_quotes({'quotes': [{'symbol': 'BTC/USDT', 'price': '100', 'source': 'test', 'as_of': iso(self.now)}]})

    def tearDown(self):
        self.temp.cleanup()

    def test_future_timestamp_rejected(self):
        with self.assertRaises(BusinessError):
            self.office.ingest_quotes({'quotes': [{'symbol': 'BTC/USDT', 'price': '100', 'source': 'future',
                                                  'as_of': iso(self.now + timedelta(seconds=16))}]})

    def test_risk_limits_reject_large_trade(self):
        result = self.office.place_order('user', {'request_id': 'limit', 'symbol': 'BTC/USDT', 'side': 'buy', 'quantity': '1001'})
        self.assertEqual(result['reason'], 'order_limit')

    def test_initial_position_and_realized_profit(self):
        self.office.create_account('seed', {'initial_balances': {'USDT': '0'}, 'initial_positions': [
            {'symbol': 'BTC/USDT', 'quantity': '2', 'average_cost': '80'}]})
        self.office.place_order('seed', {'request_id': 'sell', 'symbol': 'BTC/USDT', 'side': 'sell', 'quantity': '2'})
        portfolio = self.office.portfolio('seed')
        self.assertEqual(portfolio['realized_pnl'], '40')
        self.assertEqual(portfolio['total_assets'], '200')

    def test_snapshot_truncation_is_explicit(self):
        for i in range(51):
            self.office.place_order('user', {'request_id': f'o{i}', 'symbol': 'BTC/USDT', 'side': 'buy',
                                             'quantity': '0.01', 'order_type': 'limit', 'limit_price': '90'})
        result = self.office.snapshot('user')
        self.assertEqual(len(result['open_orders']), 50)
        self.assertTrue(result['truncated'])

    def test_pending_buys_recheck_updated_prohibition(self):
        order = self.office.place_order('user', {'request_id': 'pending', 'symbol': 'BTC/USDT', 'side': 'buy',
                                                'quantity': '1', 'order_type': 'limit', 'limit_price': '90'})
        self.office.assessment('user', {'assessment': {'dimensions': {k: 60 for k in ['FC', 'RA', 'KE', 'BD', 'OC']},
                                                      'rai': 60, 'risk_level': 'C3', 'product_cap': 'R3',
                                                      'prohibitions': ['new_buys_blocked']}})
        self.now += timedelta(seconds=1)
        self.office.ingest_quotes({'quotes': [{'symbol': 'BTC/USDT', 'price': '89', 'source': 'test', 'as_of': iso(self.now)}]})
        result = self.office.orders('user')[0]
        self.assertEqual(result['status'], 'rejected')
        self.assertEqual(result['reason'], 'assessment_prohibition')
        self.assertEqual(result['reserved_cash'], '0')
        self.assertEqual(self.office.records('user', 'trades'), [])

    def test_lan_requires_token_and_separate_reader(self):
        with self.assertRaises(BusinessError):
            Server(('0.0.0.0', 0), self.office)
        with self.assertRaises(BusinessError):
            Server(('127.0.0.1', 0), self.office, token='same', read_token='same')

    def test_http_demo_and_market_polling(self):
        source = Server(('127.0.0.1', 0), self.office)
        thread = threading.Thread(target=source.serve_forever, daemon=True)
        thread.start()
        try:
            url = f'http://127.0.0.1:{source.server_port}'
            # The six-module demo runs through HTTP and creates its own fictional user.
            result = run(Client(url))
            self.assertEqual(result['aml_review'], 'closed')
            target = MiddleOffice(Path(self.temp.name) / 'target.sqlite3')
            feed = MarketFeed(target, url + '/api/quotes')
            self.assertGreater(feed.poll_once()['accepted'], 0)
            self.assertTrue(target.quotes('BTC/USDT')['quotes'])
        finally:
            source.shutdown()
            source.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
