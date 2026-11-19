"""Optional polling of an agreed upstream {quotes:[...]} HTTP data source."""
import json
import logging
import threading
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from .validation import require


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class MarketFeed:
    def __init__(self, office, url, *, token=None, interval=5):
        parsed = urlsplit(url)
        require(parsed.scheme in {'http', 'https'} and parsed.hostname and not parsed.username
                and not parsed.fragment, 'invalid_market_url', 'use an explicit trusted HTTP(S) quote URL')
        require(interval >= 1, 'invalid_interval', 'poll interval must be at least one second')
        self.office, self.url, self.token, self.interval = office, url, token, interval
        self.stop_event = threading.Event()
        self.last_status = 'not_started'
        self.thread = threading.Thread(target=self._run, daemon=True)

    def poll_once(self):
        headers = {'Accept': 'application/json'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        with build_opener(NoRedirect).open(Request(self.url, headers=headers), timeout=2) as response:
            body = response.read(256 * 1024 + 1)
        require(len(body) <= 256 * 1024, 'upstream_too_large', 'upstream quotes exceed 256 KiB')
        payload = json.loads(body)
        require(isinstance(payload, dict), 'invalid_upstream', 'upstream must return a quote object')
        result = self.office.ingest_quotes(payload)
        self.last_status = 'ok'
        return result

    def _run(self):
        while not self.stop_event.is_set():
            try:
                self.poll_once()
            except Exception:
                # Keep the original timestamps so failed polling never freshens stale prices.
                self.last_status = 'unavailable'
                logging.getLogger(__name__).warning('Market feed unavailable; existing quotes retain their timestamps')
            self.stop_event.wait(self.interval)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=3)
