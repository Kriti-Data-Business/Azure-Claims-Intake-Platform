import json
from pathlib import Path

from engine.audit import AuditLog
from engine.llm import JsonHttp, RateLimiter
from engine.pack import load_pack
from engine.pipeline import run
from engine.vector import AzureOpenAIEmbedder, HashingEmbedder, VectorIndex, vector_retriever
from eval.run_eval import same, score

P = Path(__file__).resolve().parent.parent
RETAIL = load_pack(P / "packs/retail_supplier_contract.yaml")


def test_vector_index_finds_the_relevant_policy():
    idx = VectorIndex(HashingEmbedder()); idx.add(RETAIL.knowledge)
    hits = idx.search("the supplier wants exclusive supply across all stores")
    assert hits and "exclusive supply" in hits[0][1]


def test_irrelevant_query_returns_nothing():
    idx = VectorIndex(HashingEmbedder()); idx.add(RETAIL.knowledge)
    assert idx.search("zebra quantum marmalade") == []


def test_pipeline_accepts_a_vector_retriever():
    r = vector_retriever(HashingEmbedder())
    out = run("Supplier: Acme Ltd. Net 90 days. Exclusive supply.", RETAIL, AuditLog(), retriever=r)
    assert out["context"] and any("60 days" in c or "exclusive" in c for c in out["context"])


def test_azure_embedder_request_and_ordering():
    seen = []
    def transport(url, headers, body, timeout):
        seen.append((url, headers, json.loads(body)))
        return 200, {}, json.dumps({"data": [{"index": 1, "embedding": [0, 2]}, {"index": 0, "embedding": [3, 0]}]}).encode()
    e = AzureOpenAIEmbedder("https://x/", "emb", "k", http=JsonHttp(transport, limiter=RateLimiter(1000, sleep=lambda s: None)))
    assert e.embed(["a", "b"]) == [[1.0, 0.0], [0.0, 1.0]]
    assert seen[0][0].startswith("https://x/openai/deployments/emb/embeddings?api-version=") and seen[0][1]["api-key"] == "k"


def test_eval_scoring_perfect_and_wrong_extractor():
    rows = [{"pack": "claims_intake", "text": "x", "expected": {"amount": 500}}]
    class Perfect:
        def extract(self, t, p): return {"amount": 500.0}
    class Wrong:
        def extract(self, t, p): return {"amount": 5.0}
    assert score(Perfect(), rows)["precision"] == 1.0
    w = score(Wrong(), rows)
    assert w["precision"] == 0.0 and w["totals"]["wrong"] == 1


def test_labelled_set_is_well_formed():
    rows = [json.loads(l) for l in (P / "eval/labelled.jsonl").read_text().splitlines() if l.strip()]
    assert len(rows) == 24 and {r["pack"] for r in rows} == {"retail_supplier_contract", "claims_intake", "clinical_referral"}
    assert same(6.25, 6.25) and same("Acme Ltd", "acme ltd")
