from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.queue import InMemoryQueue, ServiceBusQueue
from app.store import CaseStore
from app.worker import Worker
from engine.audit import AuditLog
from engine.extract import RuleExtractor
from engine.llm import ExtractionError
from engine.pack import load_pack

P = Path(__file__).resolve().parent.parent
HI, HR = {"X-API-Key": "ingest"}, {"X-API-Key": "review"}
CONTRACT = (P / "samples/supplier_contract.txt").read_text()


def make(extractor=None, max_attempts=3):
    packs = {p.stem: load_pack(p) for p in (P / "packs").glob("*.yaml")}
    q, s, a = InMemoryQueue(), CaseStore(), AuditLog()
    w = Worker(q, s, packs, extractor or RuleExtractor(), a, max_attempts)
    return TestClient(create_app(q, s, w, a, "ingest", "review")), q, s, w, a


def submit(c, domain="claims_intake", text="Roof repair $500"):
    return c.post("/cases", json={"domain": domain, "text": text}, headers=HI).json()["case_id"]


def test_auth_required_and_roles_separated():
    c, *_ = make()
    assert c.post("/cases", json={"domain": "claims_intake", "text": "x"}).status_code == 401
    assert c.post("/cases", json={"domain": "claims_intake", "text": "x"}, headers=HR).status_code == 401
    assert c.get("/reviews", headers=HI).status_code == 401
    assert c.post("/admin/process", headers=HI).status_code == 401


def test_validation_rejects_unknown_domain_and_oversize():
    c, *_ = make()
    assert c.post("/cases", json={"domain": "nope", "text": "x"}, headers=HI).status_code == 422
    assert c.post("/cases", json={"domain": "claims_intake", "text": "x" * 20_001}, headers=HI).status_code == 422
    assert c.post("/cases", json={"domain": "claims_intake", "text": ""}, headers=HI).status_code == 422


def test_auto_action_path():
    c, *_ = make()
    cid = submit(c)
    assert c.get(f"/cases/{cid}", headers=HI).json()["status"] == "queued"
    assert c.post("/admin/process", headers=HR).json() == {"processed": 1}
    body = c.get(f"/cases/{cid}", headers=HI).json()
    assert body["status"] == "processed" and body["result"]["route"] == "auto_action" and "text" not in body


def test_human_review_approve_flow_is_audited():
    c, q, s, w, audit = make()
    cid = submit(c, "retail_supplier_contract", CONTRACT)
    c.post("/admin/process", headers=HR)
    pending = c.get("/reviews", headers=HR).json()
    assert [p["case_id"] for p in pending] == [cid] and pending[0]["extracted"]["payment_days"] == 90
    r = c.post(f"/reviews/{cid}/decision", json={"decision": "approve", "reviewer": "kriti", "note": "ok"}, headers=HR)
    assert r.status_code == 200 and c.get(f"/cases/{cid}", headers=HI).json()["status"] == "approved"
    assert audit.records[-1]["event"] == "human_review" and audit.verify()
    again = c.post(f"/reviews/{cid}/decision", json={"decision": "reject", "reviewer": "x"}, headers=HR)
    assert again.status_code == 409  # a decision cannot be overwritten


def test_cannot_review_a_case_that_needs_no_review():
    c, *_ = make()
    cid = submit(c); c.post("/admin/process", headers=HR)
    assert c.post(f"/reviews/{cid}/decision", json={"decision": "approve", "reviewer": "x"}, headers=HR).status_code == 409


def test_poison_message_retried_then_dead_lettered():
    class Boom:
        def extract(self, *a): raise RuntimeError("bug")
    c, q, s, w, _ = make(Boom(), max_attempts=3)
    cid = submit(c)
    for _ in range(3):
        c.post("/admin/process", headers=HR)
    assert s.get(cid)["status"] == "failed" and len(q.dead_lettered) == 1 and not q._pending


def test_extraction_error_is_a_review_not_a_failure():
    class Fail:
        def extract(self, *a): raise ExtractionError("provider error 500")
    c, *_ = make(Fail())
    cid = submit(c); c.post("/admin/process", headers=HR)
    assert c.get(f"/cases/{cid}", headers=HI).json()["status"] == "pending_review"


def test_health_reports_audit_chain():
    c, *_ = make()
    assert c.get("/healthz").json() == {"status": "ok", "audit_chain_valid": True}


class FakeMsg:
    def __init__(self, body, n): self.body, self.message_id, self.delivery_count = body, "id1", n


class FakeSB:
    def __init__(self): self.sent, self.log = [], []; self.queue = [FakeMsg(b'{"case_id": "c1"}', 0)]
    def get_queue_sender(self, name): return self
    def get_queue_receiver(self, name): return self
    def send_messages(self, m): self.sent.append(m)
    def receive_messages(self, max_message_count, max_wait_time): return self.queue
    def complete_message(self, m): self.log.append("complete")
    def abandon_message(self, m): self.log.append("abandon")
    def dead_letter_message(self, m, reason): self.log.append(("dlq", reason))


def test_service_bus_adapter_surface():
    fake = FakeSB(); q = ServiceBusQueue(fake, "cases")
    [m] = q.receive()
    assert m.body == {"case_id": "c1"} and m.attempts == 1
    q.complete(m); q.abandon(m); q.dead_letter(m, "x" * 300)
    assert fake.log[:2] == ["complete", "abandon"] and len(fake.log[2][1]) == 128


def test_main_wires_actions_endpoints():
    from app.main import build
    app, _ = build({"INGEST_API_KEY": "i", "REVIEWER_API_KEY": "r"})
    c = TestClient(app)
    assert c.get("/actions", headers={"X-API-Key": "r"}).json() == []
    with pytest.raises(RuntimeError):
        build({})
