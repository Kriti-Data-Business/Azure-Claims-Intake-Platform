import asyncio
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.actions import ActionError, ActionStore
from app.api import create_app
from app.queue import InMemoryQueue
from app.store import CaseStore
from app.worker import Worker
from engine.audit import AuditLog
from engine.extract import RuleExtractor
from engine.pack import load_pack
from mcp_server.server import build_server

P = Path(__file__).resolve().parent.parent
HR = {"X-API-Key": "review"}


@pytest.fixture
def env():
    packs = {p.stem: load_pack(p) for p in (P / "packs").glob("*.yaml")}
    q, s, a, lock = InMemoryQueue(), CaseStore(), AuditLog(), threading.Lock()
    w = Worker(q, s, packs, RuleExtractor(), a); w.audit_lock = lock
    acts = ActionStore(s, a, lock)
    client = TestClient(create_app(q, s, w, a, "ingest", "review", acts))
    cid = s.create("claims_intake", "URGENT roof $500")
    return client, s, acts, a, cid


def call(server, name, **args):
    import json
    r = asyncio.run(server.call_tool(name, args))
    return json.loads(r.content[0].text)


def test_there_is_no_approve_tool(env):
    client, s, acts, a, cid = env
    names = {t.name for t in asyncio.run(build_server(s, acts).list_tools())}
    assert names == {"list_pending_reviews", "get_case", "propose_action", "check_action", "execute_action"}


def test_agent_cannot_execute_before_human_approval(env):
    client, s, acts, a, cid = env
    aid = acts.propose(cid, "create_ticket", {"title": "Urgent roof claim", "priority": "high"})["id"]
    with pytest.raises(ActionError, match="human must approve"):
        acts.execute(aid)
    assert acts.outbox == []


def test_full_gate_flow_over_http_and_executes_once(env):
    client, s, acts, a, cid = env
    aid = acts.propose(cid, "notify_customer", {"template": "claim_received"})["id"]
    assert [x["id"] for x in client.get("/actions", headers=HR).json()] == [aid]
    assert client.post(f"/actions/{aid}/approval", json={"approve": True, "reviewer": "kriti"}).status_code == 401
    assert client.post(f"/actions/{aid}/approval", json={"approve": True, "reviewer": "kriti"}, headers=HR).status_code == 200
    acts.execute(aid)
    assert len(acts.outbox) == 1
    with pytest.raises(ActionError):
        acts.execute(aid)  # second run refused
    assert len(acts.outbox) == 1
    events = [r.get("event") for r in a.records]
    assert events == ["action_proposed", "action_decision", "action_executed"] and a.verify()


def test_denied_action_never_runs_and_decision_is_final(env):
    client, s, acts, a, cid = env
    aid = acts.propose(cid, "create_ticket", {"title": "x"})["id"]
    client.post(f"/actions/{aid}/approval", json={"approve": False, "reviewer": "kriti"}, headers=HR)
    with pytest.raises(ActionError):
        acts.execute(aid)
    again = client.post(f"/actions/{aid}/approval", json={"approve": True, "reviewer": "kriti"}, headers=HR)
    assert again.status_code == 409


@pytest.mark.parametrize("kind,params", [
    ("delete_case", {}), ("create_ticket", {"title": "x", "cmd": "rm -rf"}), ("create_ticket", {"title": ""}),
    ("create_ticket", {"title": "x", "priority": "urgent!!"}), ("notify_customer", {"template": "free text"}),
])
def test_proposals_are_validated_against_an_allow_list(env, kind, params):
    client, s, acts, a, cid = env
    with pytest.raises(ActionError):
        acts.propose(cid, kind, params)


def test_unknown_case_rejected(env):
    client, s, acts, a, cid = env
    with pytest.raises(ActionError, match="no such case"):
        acts.propose("nope", "create_ticket", {"title": "x"})


def test_mcp_tools_propose_then_refuse_execution(env):
    client, s, acts, a, cid = env
    srv = build_server(s, acts)
    p = call(srv, "propose_action", case_id=cid, kind="create_ticket", title="Check claim")
    assert p["status"] == "awaiting_approval"
    assert "human must approve" in call(srv, "execute_action", action_id=p["action_id"])["error"]
    assert "error" in call(srv, "propose_action", case_id=cid, kind="delete_case")
