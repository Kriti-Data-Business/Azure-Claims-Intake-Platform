"""Case store (SQLite). Cases move queued -> processed | pending_review -> approved | rejected | failed."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CaseStore:
    def __init__(self, path: str = ":memory:"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self.db.execute("""CREATE TABLE IF NOT EXISTS cases (
            id TEXT PRIMARY KEY, domain TEXT, text TEXT, status TEXT, result TEXT, review TEXT,
            created TEXT, updated TEXT)""")

    def create(self, domain: str, text: str) -> str:
        cid = uuid.uuid4().hex[:12]
        with self.lock:
            self.db.execute("INSERT INTO cases VALUES (?,?,?,?,?,?,?,?)",
                            (cid, domain, text, "queued", None, None, _now(), _now()))
            self.db.commit()
        return cid

    def get(self, cid: str) -> dict | None:
        with self.lock:
            r = self.db.execute("SELECT * FROM cases WHERE id=?", (cid,)).fetchone()
        return self._row(r) if r else None

    def update(self, cid: str, status: str, result: dict | None = None, review: dict | None = None) -> None:
        with self.lock:
            cur = self.get_unlocked(cid)
            self.db.execute("UPDATE cases SET status=?, result=?, review=?, updated=? WHERE id=?",
                            (status, json.dumps(result if result is not None else cur["result"]),
                             json.dumps(review if review is not None else cur["review"]), _now(), cid))
            self.db.commit()

    def get_unlocked(self, cid: str) -> dict:
        return self._row(self.db.execute("SELECT * FROM cases WHERE id=?", (cid,)).fetchone())

    def list(self, status: str) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM cases WHERE status=? ORDER BY created", (status,)).fetchall()
        return [self._row(r) for r in rows]

    @staticmethod
    def _row(r) -> dict:
        d = dict(r)
        d["result"] = json.loads(d["result"]) if d["result"] else None
        d["review"] = json.loads(d["review"]) if d["review"] else None
        return d
