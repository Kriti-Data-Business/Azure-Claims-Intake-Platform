"""Worker: pull messages, run the engine, route the case. Poison messages are dead-lettered."""

from __future__ import annotations

import logging
import threading

from engine.audit import AuditLog
from engine.pipeline import run
from app.queue import Queue
from app.store import CaseStore

log = logging.getLogger("worker")
ROUTE_STATUS = {"auto_action": "processed", "human_review": "pending_review", "reject": "rejected"}


class Worker:
    def __init__(self, queue: Queue, store: CaseStore, packs: dict, extractor, audit: AuditLog,
                 max_attempts: int = 3):
        self.queue, self.store, self.packs, self.extractor = queue, store, packs, extractor
        self.audit, self.max_attempts, self.audit_lock = audit, max_attempts, threading.Lock()

    def process_batch(self, max_messages: int = 10) -> int:
        msgs = self.queue.receive(max_messages)
        for m in msgs:
            self._handle(m)
        return len(msgs)

    def _handle(self, m) -> None:
        cid = m.body.get("case_id")
        try:
            case = self.store.get(cid)
            if case is None:
                raise LookupError(f"unknown case {cid}")
            with self.audit_lock:
                result = run(case["text"], self.packs[case["domain"]], self.audit, self.extractor)
            self.store.update(cid, ROUTE_STATUS.get(result["route"], "pending_review"), result=result)
            self.queue.complete(m)
        except Exception as e:  # noqa: BLE001 - any failure is retried, then dead-lettered
            log.warning("case %s failed on attempt %s: %s", cid, m.attempts, type(e).__name__)
            if m.attempts >= self.max_attempts:
                self.queue.dead_letter(m, f"{type(e).__name__}: {e}")
                if cid and self.store.get(cid):
                    self.store.update(cid, "failed", result={"error": type(e).__name__})
            else:
                self.queue.abandon(m)
