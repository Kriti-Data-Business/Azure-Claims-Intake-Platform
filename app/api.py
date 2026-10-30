"""HTTP API: intake, case status, human review. Auth is two static API keys (ingest, reviewer);
production would use Entra ID / OIDC. Request size and domain are validated before queueing."""

from __future__ import annotations

import hmac
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from app.queue import Queue
from app.store import CaseStore
from app.worker import Worker
from engine.audit import AuditLog

MAX_TEXT = 20_000


class NewCase(BaseModel):
    domain: str
    text: str = Field(min_length=1, max_length=MAX_TEXT)


class Decision(BaseModel):
    decision: Literal["approve", "reject"]
    reviewer: str = Field(min_length=1, max_length=80)
    note: str = Field(default="", max_length=500)


def create_app(queue: Queue, store: CaseStore, worker: Worker, audit: AuditLog,
               ingest_key: str, reviewer_key: str) -> FastAPI:
    app = FastAPI(title="Claims Intake Platform", version="0.1.0")

    def need(expected: str):
        def dep(x_api_key: str = Header(default="")):
            if not hmac.compare_digest(x_api_key.encode(), expected.encode()):
                raise HTTPException(401, "invalid API key")
        return dep

    ingest, reviewer = Depends(need(ingest_key)), Depends(need(reviewer_key))

    @app.get("/healthz")
    def health():
        return {"status": "ok", "audit_chain_valid": audit.verify()}

    @app.post("/cases", status_code=202, dependencies=[ingest])
    def submit(body: NewCase):
        if body.domain not in worker.packs:
            raise HTTPException(422, f"unknown domain; available: {sorted(worker.packs)}")
        cid = store.create(body.domain, body.text)
        queue.send({"case_id": cid})
        return {"case_id": cid, "status": "queued"}

    @app.get("/cases/{cid}", dependencies=[ingest])
    def get_case(cid: str):
        c = store.get(cid)
        if not c:
            raise HTTPException(404, "no such case")
        c.pop("text")  # the source document is not returned
        return c

    @app.post("/admin/process", dependencies=[reviewer])
    def process(max_messages: int = 10):
        return {"processed": worker.process_batch(min(max_messages, 50))}

    @app.get("/reviews", dependencies=[reviewer])
    def pending():
        return [{"case_id": c["id"], "domain": c["domain"], "reason": c["result"]["reason"],
                 "issues": c["result"]["issues"], "extracted": c["result"]["extracted"]}
                for c in store.list("pending_review")]

    @app.post("/reviews/{cid}/decision", dependencies=[reviewer])
    def decide(cid: str, d: Decision):
        c = store.get(cid)
        if not c:
            raise HTTPException(404, "no such case")
        if c["status"] != "pending_review":
            raise HTTPException(409, f"case is {c['status']}, not pending_review")
        review = {"decision": d.decision, "reviewer": d.reviewer, "note": d.note}
        with worker.audit_lock:
            rec = audit.append({"event": "human_review", "case_id": cid, **review})
        store.update(cid, "approved" if d.decision == "approve" else "rejected", review={**review, "audit_hash": rec["hash"]})
        return {"case_id": cid, "status": store.get(cid)["status"], "audit_hash": rec["hash"]}

    return app
