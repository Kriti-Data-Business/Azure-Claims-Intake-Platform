from pathlib import Path
from engine.audit import AuditLog
from engine.pack import load_pack
from engine.pipeline import run

P = Path(__file__).resolve().parent.parent


def test_retail_contract_escalates():
    pack = load_pack(P / "packs/retail_supplier_contract.yaml")
    out = run((P / "samples/supplier_contract.txt").read_text(), pack, AuditLog())
    assert out["extracted"]["payment_days"] == 90
    assert out["extracted"]["rebate_pct"] == 7.5
    assert out["route"] == "human_review"
    assert out["context"]


def test_standard_terms_auto():
    pack = load_pack(P / "packs/retail_supplier_contract.yaml")
    out = run("Supplier: Acme Ltd. Net 30 days.", pack, AuditLog())
    assert out["route"] == "auto_action"


def test_missing_required_goes_to_review():
    pack = load_pack(P / "packs/retail_supplier_contract.yaml")
    assert run("Nothing useful here", pack, AuditLog())["route"] == "human_review"


def test_same_engine_other_domain():
    pack = load_pack(P / "packs/claims_intake.yaml")
    assert run("Roof repair cost $500", pack, AuditLog())["route"] == "auto_action"
    assert run("URGENT roof repair $500", pack, AuditLog())["route"] == "human_review"


def test_audit_chain_detects_tamper():
    pack = load_pack(P / "packs/claims_intake.yaml")
    a = AuditLog()
    run("cost $500", pack, a); run("cost $600", pack, a)
    assert a.verify()
    a.records[0]["route"] = "tampered"
    assert not a.verify()
