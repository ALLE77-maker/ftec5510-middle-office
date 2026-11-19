"""Run Yang's actual HTTP adapters and AI server against our service.

Usage: python scripts/check_ai_integration.py --ai-source /path/to/crypto-ai-mvp
The external checkout stays outside this repository. No model/API key required.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from middle_office.client import Client
from middle_office.service import MiddleOffice
from middle_office.server import Server
from middle_office.validation import iso


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ai-source', type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.ai_source.resolve()))
    from ai_mvp.assistant import Assistant
    from ai_mvp.profiles import ProfileStore
    from ai_mvp.providers import HttpMarketProvider, HttpTradingProvider, QuoteBook
    from ai_mvp.server import ApiServer

    with tempfile.TemporaryDirectory() as temp:
        office = MiddleOffice(Path(temp) / 'middle.sqlite3')
        middle = Server(('127.0.0.1', 0), office, token='integration-operator', read_token='integration-reader')
        base = f'http://127.0.0.1:{middle.server_port}'
        assistant = Assistant(ProfileStore(Path(temp) / 'ai.sqlite3'), QuoteBook(),
                              trading=HttpTradingProvider(base + '/api', token='integration-reader'),
                              market_provider=HttpMarketProvider(base + '/api', token='integration-reader'))
        ai = ApiServer(0, assistant, 'integration-ai')
        servers = [middle, ai]
        threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in servers]
        for thread in threads:
            thread.start()
        try:
            client = Client(base, 'integration-operator')
            user = 'integration_user'
            root = '/api/accounts/' + user
            client.request('POST', root, {'initial_balances': {'USDT': '10000'}})
            now = iso(datetime.now(timezone.utc))
            client.request('POST', '/api/quotes', {'quotes': [
                {'symbol': 'BTC/USDT', 'price': '68000', 'source': source, 'as_of': now,
                 'name': 'Bitcoin', 'aliases': ['比特币']} for source in ('demo_a', 'demo_b')]})
            profile = {'assessment': {'dimensions': {'FC': 62, 'RA': 65, 'KE': 75, 'BD': 60, 'OC': 55},
                                      'rai': 63, 'risk_level': 'C3', 'product_cap': 'R3'}}
            profile = client.request('PUT', root + '/assessment', profile)
            aiclient = Client(f'http://127.0.0.1:{ai.server_port}', 'integration-ai')
            aiclient.request('PUT', '/v1/profiles/' + user, profile)
            client.request('POST', root + '/orders', {'request_id': 'filled', 'symbol': 'BTC/USDT', 'side': 'buy', 'quantity': '0.01'})
            client.request('POST', root + '/orders', {'request_id': 'pending', 'symbol': 'BTC/USDT', 'side': 'sell',
                                                    'quantity': '0.005', 'order_type': 'limit', 'limit_price': '70000'})
            quote = assistant.lookup_market('BTC/USDT')
            assert quote['status'] == 'exact' and len(quote['matches']) == 1, quote
            account = assistant.account_snapshot(user)
            assert account['state'] == 'ok' and len(account['open_orders']) == 1, account
            assert any(row == {'symbol': 'BTC', 'quantity': '0.01'} for row in account['positions']), account
            risk = aiclient.request('GET', '/v1/risk/' + user + '?quote_currency=USDT')
            assert risk['state'] == 'ok' and risk['summary']['complete'], risk
            chat = aiclient.request('POST', '/v1/chat', {'user_id': user, 'message': '看看我的持仓和挂单',
                                                        'include_account': True, 'market_queries': ['BTC/USDT']})
            assert chat['account']['state'] == 'ok' and chat['reply'], chat
            print(json.dumps({'result': 'PASS', 'market': quote['status'], 'account': account['state'],
                              'open_orders': len(account['open_orders']), 'risk': risk['state'],
                              'ai_generation': chat['generation']}, ensure_ascii=False, indent=2))
        finally:
            for server in servers:
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join()


if __name__ == '__main__':
    main()
