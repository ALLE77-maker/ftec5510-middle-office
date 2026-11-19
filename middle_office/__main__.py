import argparse
import json
import os

from .market import MarketFeed
from .service import MiddleOffice
from .server import Server


def main():
    parser = argparse.ArgumentParser(description="Group 20 middle office (simulation)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8200)
    parser.add_argument("--db", default=".middle_office/ledger.sqlite3")
    parser.add_argument("--quote-max-age", type=int, default=120)
    parser.add_argument("--market-url", default=os.getenv("MO_MARKET_URL"), help="upstream quote URL returning {quotes:[...]}")
    parser.add_argument("--market-interval", type=int, default=5)
    parser.add_argument("--product-risks", help='JSON file mapping pairs to agreed demo risk levels, e.g. {"BTC/USDT": 5}')
    args = parser.parse_args()
    risks = {}
    if args.product_risks:
        with open(args.product_risks, encoding="utf-8") as file:
            risks = json.load(file)
    office = MiddleOffice(args.db, max_quote_age=args.quote_max_age, product_risks=risks)
    server = Server((args.host, args.port), office, token=os.getenv("MO_API_TOKEN"), read_token=os.getenv("MO_AI_READ_TOKEN"))
    feed = MarketFeed(office, args.market_url, token=os.getenv("MO_MARKET_TOKEN"), interval=args.market_interval) if args.market_url else None
    if feed:
        feed.start()
    print(f"Middle office listening at http://{args.host}:{server.server_port} (simulation)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if feed:
            feed.stop()
        server.server_close()


if __name__ == "__main__":
    main()
