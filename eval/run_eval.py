"""Field-level evaluation of an extractor on a labelled set, tracked with MLflow.

    python -m eval.run_eval --extractor rule
    python -m eval.run_eval --extractor anthropic     # needs ANTHROPIC_API_KEY (and network)
    python -m eval.run_eval --extractor openrouter --model anthropic/claude-sonnet-5.5   # needs OPENROUTER_API_KEY
    python -m eval.run_eval --extractor azure_openai  # needs AZURE_OPENAI_* variables
    mlflow ui                                         # compare runs

The labelled set (eval/labelled.jsonl) is 24 short synthetic documents written for this repo,
including prompt-injection and phrasing the regex baseline does not cover. It is a regression
check for the pipeline, not evidence about real claims or contracts.
Scoring per field: correct = extracted equals expected; wrong = extracted but different or not
expected (a false positive); missed = expected but not extracted.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path

from app.main import build_extractor
from engine.audit import AuditLog
from engine.pack import load_pack
from engine.pipeline import run

ROOT = Path(__file__).resolve().parent.parent


def same(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(a - b) < 1e-9
    return str(a).strip().lower() == str(b).strip().lower() if isinstance(a, str) else a == b


def score(extractor, rows: list[dict]) -> dict:
    packs = {p.stem: load_pack(p) for p in (ROOT / "packs").glob("*.yaml")}
    tally = defaultdict(lambda: {"correct": 0, "wrong": 0, "missed": 0})
    routes = {"auto_action": 0, "human_review": 0, "reject": 0}
    for r in rows:
        out = run(r["text"], packs[r["pack"]], AuditLog(), extractor)
        routes[out["route"]] = routes.get(out["route"], 0) + 1
        got, want = out["extracted"], r["expected"]
        for f in set(got) | set(want):
            t = tally[f"{r['pack']}.{f}"]
            if f in got and f in want:
                t["correct" if same(got[f], want[f]) else "wrong"] += 1
            elif f in got:
                t["wrong"] += 1
            else:
                t["missed"] += 1
    total = {k: sum(t[k] for t in tally.values()) for k in ("correct", "wrong", "missed")}
    precision = total["correct"] / max(1, total["correct"] + total["wrong"])
    recall = total["correct"] / max(1, total["correct"] + total["missed"])
    return {"precision": precision, "recall": recall, "n_documents": len(rows), "totals": total,
            "per_field": dict(tally), "routes": routes}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--extractor", default="rule", choices=["rule", "azure_openai", "anthropic", "openrouter"])
    ap.add_argument("--model", help="model slug for --extractor openrouter, e.g. anthropic/claude-sonnet-5.5")
    ap.add_argument("--tracking-uri", default=f"sqlite:///{ROOT / 'mlflow.db'}")
    a = ap.parse_args()
    rows = [json.loads(line) for line in (ROOT / "eval/labelled.jsonl").read_text().splitlines() if line.strip()]
    env = {**os.environ, "LLM_PROVIDER": a.extractor}
    if a.model:
        env["OPENROUTER_MODEL"] = a.model
    res = score(build_extractor(env), rows)

    import mlflow
    mlflow.set_tracking_uri(a.tracking_uri)
    mlflow.set_experiment("claims-extraction-eval")
    with mlflow.start_run(run_name=f"{a.extractor}:{env.get('OPENROUTER_MODEL', '')}".rstrip(":")):
        mlflow.log_params({"extractor": a.extractor, "n_documents": res["n_documents"],
                           "model": env.get("OPENROUTER_MODEL") or env.get("ANTHROPIC_MODEL") or env.get("AZURE_OPENAI_DEPLOYMENT") or "n/a"})
        mlflow.log_metrics({"precision": res["precision"], "recall": res["recall"],
                            **{f"routes_{k}": v for k, v in res["routes"].items()}})
        mlflow.log_dict(res, "field_results.json")
    print(f"{a.extractor}: precision {res['precision']:.2f}  recall {res['recall']:.2f}  "
          f"on {res['n_documents']} documents  routes {res['routes']}")
    for k, t in sorted(res["per_field"].items()):
        print(f"  {k:42s} {t}")


if __name__ == "__main__":
    main()
