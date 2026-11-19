"""Read official numbers once and prepare AI context without revaluing assets.

Run from the repository root:
  python examples/ai/consistent_analysis.py --user demo_user
The token is read from MO_AI_READ_TOKEN. This example has no write operations
and does not call a model. Reuse the SAME report for frontend display and AI.
"""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
import os
import re
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def fetch_analysis(base_url, user_id, token):
    """base_url ends at /api; all account and quote data come from one GET."""
    url = urlsplit(base_url)
    if (url.scheme not in {"http", "https"} or not url.hostname
            or url.username is not None or url.query or url.fragment):
        raise ValueError("use an HTTP(S) API base URL without credentials, query or fragment")
    if not isinstance(user_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", user_id):
        raise ValueError("invalid user_id")
    if not isinstance(token, str) or not token or any(not 33 <= ord(c) <= 126 for c in token):
        raise ValueError("a printable ASCII read-only token is required")
    request = Request(base_url.rstrip('/') + '/accounts/' + user_id + '/analysis_snapshot',
                      headers={"Accept": "application/json", "Authorization": "Bearer " + token}, method="GET")
    with build_opener(NoRedirect).open(request, timeout=5) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("analysis response exceeds 1 MiB")
    report = json.loads(raw)
    validate_report(report)
    if report["user_id"] != user_id:
        raise ValueError("analysis user_id does not match request")
    return report


def validate_report(report):
    """Check the content ID, not a signature or a substitute for HTTPS."""
    if not isinstance(report, dict) or report.get("schema_version") != 1:
        raise ValueError("unsupported analysis snapshot")
    body = {key: value for key, value in report.items() if key != "snapshot_id"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if report.get("snapshot_id") != 'ana_' + hashlib.sha256(encoded).hexdigest():
        raise ValueError("analysis snapshot content ID mismatch")
    if report.get("state") not in {"ok", "partial"}:
        raise ValueError("invalid analysis state")


def build_explanation_context(report):
    """Canonical amounts remain strings; the AI only adds order counts."""
    validate_report(report)
    portfolio = report["portfolio"]
    account = report["account"]
    counts = Counter(order["side"] for order in account["open_orders"])
    context = {
        "instruction": "Explain these supplied facts. Preserve official decimal strings, units and snapshot_id. "
                       "Do not fetch newer quotes, recalculate official P&L or claim partial data is complete. "
                       "Order counts are auxiliary statistics, not order execution or approval.",
        "snapshot_id": report["snapshot_id"], "as_of": report["as_of"],
        "state": report["state"], "reasons": report["reasons"],
        "valuation_currency": portfolio["valuation_currency"],
        "official_numbers": {key: portfolio[key] for key in
                             ("total_assets", "observed_assets", "realized_pnl", "unrealized_pnl", "fees_by_currency")},
        "official_positions": portfolio["positions"], "balances": portfolio["balances"],
        "valuation_quotes": portfolio["valuation_quotes"], "position_risk": report["risk"],
        "basis": report["basis"],
        "auxiliary_statistics": {"open_orders_returned": len(account["open_orders"]),
                                 "buy_orders_returned": counts["buy"], "sell_orders_returned": counts["sell"],
                                 "complete": not account["truncated"]},
    }
    # Model or UI code cannot accidentally mutate the shared source report.
    return deepcopy(context)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8200/api')
    parser.add_argument('--user', required=True)
    args = parser.parse_args()
    data = fetch_analysis(args.base_url, args.user, os.getenv('MO_AI_READ_TOKEN'))
    print(json.dumps(build_explanation_context(data), ensure_ascii=False, indent=2))
