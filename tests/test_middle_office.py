from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from middle_office.service import MiddleOffice
from middle_office.server import Server
from middle_office.validation import BusinessError, iso


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'ledger.sqlite3'
        self.now = datetime(2026, 11, 19, 5, tzinfo=timezone.utc)
        self.office = MiddleOffice(self.path, clock=lambda: self.now)
        self.office.create_account('alice', {'initial_balances': {'USDT': '10000'}})
        self.quote('100')

    def tearDown(self):
        self.temp.cleanup()

    def quote(self, price, **extra):
        return self.office.ingest_quotes({'quotes': [{'symbol': 'BTC/USDT', 'source': 'demo_a', 'price': price,
                                                       'as_of': iso(self.now), **extra}]})

    def buy(self, request='one', quantity='1', **extra):
        return self.office.place_order('alice', {'request_id': request, 'symbol': 'BTC/USDT', 'side': 'buy',
                                                 'quantity': quantity, **extra})

    def test_cost_and_realized_profit_include_fees(self):
        self.now += timedelta(seconds=1)
        self.quote('100', fee_rate='0.01')
        self.buy(quantity='2')
        self.now += timedelta(seconds=1)
        self.quote('200', fee_rate='0.01')
        self.buy('two', '2')
        self.assertEqual(self.office.portfolio('alice')['positions'][0]['average_cost'], '151.5')
        self.office.place_order('alice', {'request_id': 'sell', 'symbol': 'BTC/USDT', 'side': 'sell', 'quantity': '1'})
        result = self.office.portfolio('alice')
        self.assertEqual(result['positions'][0]['quantity'], '3')
        self.assertEqual(result['realized_pnl'], '46.5')
        self.assertEqual(result['balances'][0]['total'], '9592')

    def test_fractional_btc_retry_and_restart(self):
        first = self.buy(quantity='0.00000001')
        self.office = MiddleOffice(self.path, clock=lambda: self.now)
        self.assertEqual(first, self.buy(quantity='0.00000001'))
        self.assertEqual(len(self.office.records('alice', 'trades')), 1)
        self.assertEqual(self.office.portfolio('alice')['positions'][0]['quantity'], '0.00000001')

    def test_request_conflict(self):
        self.buy()
        with self.assertRaises(BusinessError) as error:
            self.buy(quantity='2')
        self.assertEqual(error.exception.code, 'request_conflict')

    def test_reserved_cash_and_cancellation(self):
        order = self.buy(quantity='100', order_type='limit', limit_price='90')
        self.assertEqual(order['status'], 'open')
        self.assertEqual(self.buy('second', '20')['reason'], 'insufficient_balance')
        self.assertEqual(self.office.portfolio('alice')['balances'][0]['available'], '1000')
        self.office.cancel_order('alice', order['order_id'])
        self.office.cancel_order('alice', order['order_id'])
        self.assertEqual(self.office.portfolio('alice')['balances'][0]['available'], '10000')

    def test_quote_event_fills_limit_once(self):
        order = self.buy(order_type='limit', limit_price='90')
        self.now += timedelta(seconds=1)
        self.quote('89')
        self.quote('89')
        self.assertEqual(self.office.orders('alice')[0]['status'], 'filled')
        self.assertEqual(self.office.portfolio('alice')['balances'][0]['total'], '9911')
        self.assertEqual(len(self.office.records('alice', 'trades')), 1)
        with self.assertRaises(BusinessError):
            self.office.cancel_order('alice', order['order_id'])

    def test_pending_sell_reserves_position(self):
        self.buy()
        pending = self.office.place_order('alice', {'request_id': 's1', 'symbol': 'BTC/USDT', 'side': 'sell',
                                                   'quantity': '1', 'order_type': 'limit', 'limit_price': '110'})
        self.assertEqual(pending['status'], 'open')
        rejected = self.office.place_order('alice', {'request_id': 's2', 'symbol': 'BTC/USDT', 'side': 'sell', 'quantity': '1'})
        self.assertEqual(rejected['reason'], 'insufficient_position')

    def test_concurrent_buy_cannot_double_spend(self):
        def place(index):
            service = MiddleOffice(self.path, clock=lambda: self.now)
            return service.place_order('alice', {'request_id': f'r{index}', 'symbol': 'BTC/USDT', 'side': 'buy', 'quantity': '60'})
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(place, (1, 2)))
        self.assertEqual(sorted(row['status'] for row in results), ['filled', 'rejected'])
        self.assertEqual(self.office.portfolio('alice')['balances'][0]['total'], '4000')

    def test_stale_quotes_and_partial_valuation(self):
        self.buy()
        self.now += timedelta(seconds=121)
        self.assertEqual(self.buy('stale')['reason'], 'quote_unavailable')
        result = self.office.portfolio('alice')
        self.assertEqual(result['state'], 'partial')
        self.assertIsNone(result['total_assets'])
        self.assertIsNone(result['unrealized_pnl'])

    def test_quote_batch_atomicity_and_old_updates(self):
        with self.assertRaises(BusinessError):
            self.office.ingest_quotes({'quotes': [
                {'symbol': 'BTC/USDT', 'source': 'new', 'price': '105', 'as_of': iso(self.now)},
                {'symbol': 'BTC/USDT', 'source': 'bad', 'price': 'NaN', 'as_of': iso(self.now)}]})
        self.assertEqual(len(self.office.quotes(all_sources=True)['quotes']), 1)
        self.now -= timedelta(seconds=1)
        self.assertEqual(self.quote('80')['accepted'], 0)

    def test_comparison_and_ai_pair_deduplication(self):
        self.now += timedelta(seconds=1)
        self.quote('102', source='demo_b')
        result = self.office.comparison('BTC/USDT', '1')
        self.assertEqual(result['recommended_source'], 'demo_a')
        self.assertEqual(len(result['venues']), 2)
        self.assertEqual(len(self.office.quotes('BTC/USDT')['quotes']), 1)
        self.assertEqual(self.office.quotes('missing')['quotes'], [])

    def test_account_isolation(self):
        self.office.create_account('bob', {'initial_balances': {'USDT': '0'}})
        order = self.buy()
        self.assertEqual(self.office.snapshot('bob')['positions'], [])
        with self.assertRaises(BusinessError):
            self.office.cancel_order('bob', order['order_id'])
        with self.assertRaises(BusinessError):
            self.office.snapshot('unknown')

    def test_aml_review_and_retry(self):
        self.office.create_account('large', {'initial_balances': {'USDT': '100000'}})
        order = self.office.place_order('large', {'request_id': 'large', 'symbol': 'BTC/USDT', 'side': 'buy', 'quantity': '100'})
        alerts = [a for a in self.office.alerts('large') if a['category'] == 'aml']
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]['evidence']['trade_ids'], [order['trade_id']])
        payload = {'reviewer': 'operator_1', 'decision': 'closed', 'note': 'Expected classroom scenario'}
        result = self.office.review_alert('large', alerts[0]['alert_id'], payload)
        self.assertEqual(result, self.office.review_alert('large', alerts[0]['alert_id'], payload))
        self.assertEqual(result['status'], 'closed')

    def test_frequency_monitor(self):
        for i in range(5):
            self.buy(f'freq_{i}', '0.01')
        self.assertTrue(any(a['evidence']['rule'] == 'frequent_trades' for a in self.office.alerts('alice')))

    def test_price_and_position_alerts_deduplicate(self):
        self.office.preferences('alice', {'price_alerts': [{'symbol': 'BTC/USDT', 'direction': 'above', 'price': '99'}]})
        self.buy(quantity='70')
        alerts = self.office.alerts('alice')
        self.assertEqual(len(alerts), len(self.office.alerts('alice')))
        self.assertEqual({a['category'] for a in alerts}, {'price', 'position_risk'})

    def test_position_alert_rearms(self):
        self.buy(quantity='70')
        self.office.place_order('alice', {'request_id': 'reduce', 'symbol': 'BTC/USDT', 'side': 'sell', 'quantity': '65'})
        self.assertFalse(self.office.alerts('alice')[0]['active'])
        self.buy('again', '65')
        self.assertEqual(len(self.office.alerts('alice')), 2)

    def test_invalid_numbers(self):
        for value in (True, 'NaN', 'Infinity', '-1', '0', '0.000000001'):
            with self.subTest(value=value), self.assertRaises(BusinessError):
                self.buy(quantity=value)
        self.assertEqual(self.office.records('alice', 'trades'), [])

    def test_derived_assessment_and_product_cap(self):
        self.office.product_risks = {'BTC/USDT': 5}
        self.assertEqual(self.buy()['reason'], 'assessment_required')
        assessment = {'assessment': {'dimensions': {'FC': 62, 'RA': 65, 'KE': 75, 'BD': 60, 'OC': 55},
                                     'rai': 63, 'risk_level': 'C3', 'product_cap': 'R3'}}
        self.assertEqual(self.office.assessment('alice', assessment)['assessment']['rai'], 63)
        self.assertEqual(self.buy('cap')['reason'], 'product_cap')

    def test_transaction_rollback(self):
        with self.assertRaises(RuntimeError), self.office.store.transaction(write=True) as state:
            state['accounts']['alice']['balances']['USDT'] = '0'
            raise RuntimeError('simulated failure before commit')
        self.assertEqual(self.office.portfolio('alice')['balances'][0]['total'], '10000')

    def test_stablecoin_pair_needs_its_own_price(self):
        self.assertEqual(self.office.quotes('BTC/USD')['quotes'], [])
        self.now += timedelta(seconds=1)
        self.quote('0.99', symbol='USDC/USDT')
        result = self.office.place_order('alice', {'request_id': 'usdc', 'symbol': 'USDC/USDT', 'side': 'buy', 'quantity': '10'})
        self.assertEqual(result['execution_price'], '0.99')


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        office = MiddleOffice(Path(self.temp.name) / 'ledger.sqlite3')
        self.server = Server(('127.0.0.1', 0), office, token='test-operator', read_token='test-reader')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, method='GET', body=None, token='test-operator'):
        headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
        req = Request(self.url + path, data=json.dumps(body).encode() if body is not None else None,
                      method=method, headers=headers)
        try:
            with urlopen(req, timeout=3) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            with error:
                return error.code, json.load(error)

    def test_entrypoints(self):
        self.assertEqual(self.request('/api/accounts/alice', 'POST', {})[0], 201)
        now = iso(datetime.now(timezone.utc))
        self.assertEqual(self.request('/api/quotes', 'POST', {'quotes': [
            {'symbol': 'BTC/USDT', 'price': '100', 'source': 'demo', 'as_of': now}]})[0], 200)
        status, order = self.request('/api/accounts/alice/orders', 'POST', {
            'request_id': 'one', 'symbol': 'BTC/USDT', 'side': 'buy', 'quantity': '0.1'})
        self.assertEqual((status, order['status']), (200, 'filled'))
        _, snapshot = self.request('/api/accounts/alice/snapshot', token='test-reader')
        self.assertEqual(snapshot['positions'][0], {'symbol': 'BTC', 'quantity': '0.1'})

    def test_read_token_cannot_write_or_read_internal_alerts(self):
        self.assertEqual(self.request('/api/accounts/alice', 'POST', {}, token='test-reader')[0], 403)
        self.assertEqual(self.request('/api/accounts/alice/alerts', token='test-reader')[0], 403)
        self.assertEqual(self.request('/api/quotes', token='wrong')[0], 401)
        self.assertEqual(self.request('/health', token='')[0], 200)

    def test_invalid_request(self):
        self.assertEqual(self.request('/api/accounts/alice', 'POST', [1, 2])[0], 400)
        self.assertEqual(self.request('/api/quotes?limit=bad')[0], 400)


if __name__ == '__main__':
    unittest.main()
