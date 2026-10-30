"""Action requests: what an AI agent may ask for, and the human gate that releases it.

The agent can only *propose*. A person approves or denies through the HTTP API (reviewer key).
Execution is refused unless the request is approved, and runs at most once. The executors here
only write to an outbox: no ticketing or email system is connected.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone

from engine.audit import AuditLog
from app.store import CaseStore

ALLOWED = {
    "create_ticket": {"title", "priority"},
    "notify_customer": {"template"},
}
PRIORITIES = {"low", "normal", "high"}
TEMPLATES = {"claim_received", "more_information_needed"}


class ActionError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ActionStore:
    def __init__(self, cases: CaseStore, audit: AuditLog, audit_lock: threading.Lock):
        self.cases, self.audit, self.audit_lock = cases, audit, audit_lock
        self.db, self.lock = cases.db, threading.Lock()
        self.db.execute("""CREATE TABLE IF NOT EXISTS actions (
            id TEXT PRIMARY KEY, case_id TEXT, kind TEXT, params TEXT, status TEXT,
            decided_by TEXT, created TEXT, updated TEXT)""")
        self.outbox: list[dict] = []

    def _log(self, event: str, **kw) -> None:
        with self.audit_lock:
            self.audit.append({"event": event, **kw})

    def propose(self, case_id: str, kind: str, params: dict, proposer: str = "agent") -> dict:
        if kind not in ALLOWED:
            raise ActionError(f"action not allowed: {kind}; allowed: {sorted(ALLOWED)}")
        if set(params) - ALLOWED[kind]:
            raise ActionError(f"unexpected parameters: {sorted(set(params) - ALLOWED[kind])}")
        if kind == "create_ticket":
            if not str(params.get("title", "")).strip() or len(params["title"]) > 120:
                raise ActionError("title is required and must be at most 120 characters")
            if params.get("priority", "normal") not in PRIORITIES:
                raise ActionError(f"priority must be one of {sorted(PRIORITIES)}")
        if kind == "notify_customer" and params.get("template") not in TEMPLATES:
            raise ActionError(f"template must be one of {sorted(TEMPLATES)}")
        if self.cases.get(case_id) is None:
            raise ActionError("no such case")
        aid = uuid.uuid4().hex[:12]
        with self.lock:
            self.db.execute("INSERT INTO actions VALUES (?,?,?,?,?,?,?,?)",
                            (aid, case_id, kind, json.dumps(params), "awaiting_approval", None, _now(), _now()))
            self.db.commit()
        self._log("action_proposed", action_id=aid, case_id=case_id, kind=kind, proposer=proposer)
        return self.get(aid)

    def get(self, aid: str) -> dict | None:
        with self.lock:
            r = self.db.execute("SELECT * FROM actions WHERE id=?", (aid,)).fetchone()
        if not r:
            return None
        d = dict(r); d["params"] = json.loads(d["params"]); return d

    def list(self, status: str) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT id FROM actions WHERE status=? ORDER BY created", (status,)).fetchall()
        return [self.get(r["id"]) for r in rows]

    def _set(self, aid: str, status: str, by: str | None = None, expect: str | None = None) -> None:
        with self.lock:
            cur = self.db.execute("UPDATE actions SET status=?, decided_by=COALESCE(?, decided_by), updated=? "
                                  "WHERE id=? AND status=?", (status, by, _now(), aid, expect))
            self.db.commit()
        if cur.rowcount != 1:
            raise ActionError(f"action is not {expect}")

    def decide(self, aid: str, approve: bool, reviewer: str) -> dict:
        if self.get(aid) is None:
            raise ActionError("no such action")
        self._set(aid, "approved" if approve else "denied", reviewer, expect="awaiting_approval")
        self._log("action_decision", action_id=aid, approved=approve, reviewer=reviewer)
        return self.get(aid)

    def execute(self, aid: str, executor: str = "agent") -> dict:
        a = self.get(aid)
        if a is None:
            raise ActionError("no such action")
        if a["status"] == "executed":
            raise ActionError("refused: this action has already been executed")
        if a["status"] != "approved":
            raise ActionError(f"refused: action is {a['status']}, a human must approve it first")
        self._set(aid, "executed", expect="approved")  # atomic: a second call finds it already executed
        self.outbox.append({"action_id": aid, "kind": a["kind"], "case_id": a["case_id"], "params": a["params"]})
        self._log("action_executed", action_id=aid, kind=a["kind"], executor=executor)
        return self.get(aid)
