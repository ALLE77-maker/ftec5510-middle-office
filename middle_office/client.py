"""Small HTTP client used by the demo and the integration check."""
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class Client:
    def __init__(self, url='http://127.0.0.1:8200', token=None):
        self.url, self.token = url.rstrip('/'), token

    def request(self, method, path, payload=None):
        headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        request = Request(self.url + path, method=method, headers=headers,
                          data=json.dumps(payload).encode() if payload is not None else None)
        try:
            with urlopen(request, timeout=5) as response:
                return json.load(response)
        except HTTPError as error:
            with error:
                message = json.load(error)
            raise RuntimeError(f'HTTP {error.code}: {message}') from None
