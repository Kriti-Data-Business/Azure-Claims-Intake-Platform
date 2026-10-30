"""Wire the app from environment variables. `uvicorn app.main:app` or `python -m app.main worker`."""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

from app.api import create_app
from app.queue import InMemoryQueue, ServiceBusQueue
from app.store import CaseStore
from app.worker import Worker
from engine.audit import AuditLog
from engine.extract import RuleExtractor
from engine.llm import AnthropicClient, AzureOpenAIClient, LLMExtractor
from engine.pack import load_pack

ROOT = Path(__file__).resolve().parent.parent


def build_extractor(env=os.environ):
    provider = env.get("LLM_PROVIDER", "rule")
    if provider == "azure_openai":
        return LLMExtractor(AzureOpenAIClient(env["AZURE_OPENAI_ENDPOINT"], env["AZURE_OPENAI_DEPLOYMENT"],
                                              api_key=env.get("AZURE_OPENAI_API_KEY")))
    if provider == "anthropic":
        return LLMExtractor(AnthropicClient(env["ANTHROPIC_API_KEY"], env.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")))
    return RuleExtractor()


def build(env=os.environ):
    packs = {p.stem: load_pack(p) for p in (ROOT / "packs").glob("*.yaml")}
    queue = (ServiceBusQueue.from_connection_string(env["SERVICEBUS_CONNECTION_STRING"], env.get("SERVICEBUS_QUEUE", "cases"))
             if env.get("SERVICEBUS_CONNECTION_STRING") else InMemoryQueue())
    store, audit = CaseStore(env.get("CASE_DB", ":memory:")), AuditLog()
    worker = Worker(queue, store, packs, build_extractor(env), audit)
    ingest, reviewer = env.get("INGEST_API_KEY"), env.get("REVIEWER_API_KEY")
    if not ingest or not reviewer:
        raise RuntimeError("set INGEST_API_KEY and REVIEWER_API_KEY")
    return create_app(queue, store, worker, audit, ingest, reviewer), worker


def worker_loop() -> None:  # pragma: no cover
    _, worker = build()
    logging.basicConfig(level=logging.INFO)
    while True:
        if not worker.process_batch():
            time.sleep(2)


if __name__ == "__main__":  # pragma: no cover
    if sys.argv[1:] == ["worker"]:
        worker_loop()


def _app():  # pragma: no cover
    return build()[0]


app = _app() if os.environ.get("INGEST_API_KEY") else None  # lazy: import stays side-effect free in tests
