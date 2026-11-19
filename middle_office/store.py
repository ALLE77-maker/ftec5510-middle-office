"""One atomic SQLite snapshot for a small classroom service.

BEGIN IMMEDIATE serializes writers, including separate service processes. An
exception rolls back the complete order/balance/position/trade/alert update.
"""
from contextlib import closing, contextmanager
import json
from decimal import localcontext
from pathlib import Path
import sqlite3


class Store:
    def __init__(self, path):
        if str(path) == ":memory:":
            raise ValueError("use a file-backed database")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)")
            initial = {"version": 1, "accounts": {}, "quotes": {}, "orders": {},
                       "trades": {}, "alerts": {}, "audit": []}
            connection.execute("INSERT OR IGNORE INTO state VALUES(1, ?)", (json.dumps(initial),))

    @contextmanager
    def transaction(self, *, write=False):
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            state = json.loads(connection.execute("SELECT data FROM state WHERE id=1").fetchone()[0])
            if state.get("version") != 1:
                raise RuntimeError("unsupported middle-office database version")
            with localcontext() as context:
                context.prec = 60
                yield state
            if write:
                connection.execute("UPDATE state SET data=? WHERE id=1", (json.dumps(state, allow_nan=False),))
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
