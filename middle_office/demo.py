"""Exercise the six modules against a running service with fictional data."""
import argparse
from datetime import datetime, timezone
import json
import os
import uuid

from .client import Client
from .validation import iso


def run(client):
    user = 'demo_' + uuid.uuid4().hex[:10]
    root = f'/api/accounts/{user}'
    client.request('POST', root, {'initial_balances': {'USDT': '10000'},
                                'limits': {'aml_large_trade': '500', 'concentration_pct': '5'}})
    client.request('PUT', root + '/preferences', {'watchlist': ['BTC/USDT', 'USDC/USDT']})
    assessment = {'assessment': {'dimensions': {'FC': 62, 'RA': 65, 'KE': 75, 'BD': 60, 'OC': 55},
                                'rai': 63, 'risk_level': 'C3', 'product_cap': 'R3'}}
    client.request('PUT', root + '/assessment', assessment)
    now = iso(datetime.now(timezone.utc))
    client.request('POST', '/api/quotes', {'quotes': [
        {'symbol': 'BTC/USDT', 'price': '68000', 'bid': '67999', 'ask': '68001', 'fee_rate': '0.001',
         'source': 'demo_a', 'as_of': now, 'name': 'Bitcoin', 'aliases': ['比特币']},
        {'symbol': 'BTC/USDT', 'price': '68005', 'bid': '68004', 'ask': '68006', 'fee_rate': '0.002',
         'source': 'demo_b', 'as_of': now, 'name': 'Bitcoin', 'aliases': ['比特币']}]})
    comparison = client.request('GET', '/api/comparison?symbol=BTC%2FUSDT&quantity=0.01')
    filled = client.request('POST', root + '/orders', {'request_id': 'buy', 'symbol': 'BTC/USDT', 'side': 'buy', 'quantity': '0.01', 'source': 'demo_a'})
    pending = client.request('POST', root + '/orders', {'request_id': 'pending', 'symbol': 'BTC/USDT', 'side': 'buy',
                                                      'quantity': '0.01', 'order_type': 'limit', 'limit_price': '60000', 'source': 'demo_a'})
    snapshot = client.request('GET', root + '/snapshot')
    client.request('POST', root + '/orders/' + pending['order_id'] + '/cancel', {})
    rejected = client.request('POST', root + '/orders', {'request_id': 'too_large', 'symbol': 'BTC/USDT', 'side': 'buy', 'quantity': '1', 'source': 'demo_a'})
    alerts = client.request('GET', root + '/alerts')
    aml = next(item for item in alerts if item['category'] == 'aml')
    reviewed = client.request('POST', root + '/alerts/' + aml['alert_id'] + '/review',
                              {'reviewer': 'demo_operator', 'decision': 'closed', 'note': 'Fictional classroom demonstration'})
    result = {'user_id': user, 'comparison': comparison['status'], 'filled_order': filled['status'],
              'snapshot_before_cancel': snapshot, 'rejected_order_reason': rejected['reason'],
              'aml_review': reviewed['status'], 'portfolio': client.request('GET', root + '/portfolio')}
    assert filled['status'] == 'filled' and pending['status'] == 'open' and rejected['status'] == 'rejected'
    assert snapshot['open_orders'] and reviewed['status'] == 'closed'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8200')
    args = parser.parse_args()
    print(json.dumps(run(Client(args.url, os.getenv('MO_API_TOKEN'))), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
