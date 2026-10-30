# Claims Intake Platform

A document-to-action service for back-office intake. A document comes in, an extractor (rules or an LLM) pulls out structured fields, validation and routing rules decide what happens next, and anything uncertain goes to a person. An AI agent can work the review queue through MCP, but it can only propose actions: a human has to approve each one.

One engine, many domains. A **domain pack** (YAML) defines the fields, validation rules, routing rules and a small knowledge base. Adding a domain is a new YAML file, not an engine change. Packs included: `claims_intake` and `retail_supplier_contract`.

**Status in plain terms.** The engine, API, queue logic, LLM adapters, MCP server and evaluation harness are built and covered by 53 automated tests that run with no network and no keys. Two things are not done: nothing has been deployed to Azure, and the LLM adapters have not been run against a live model. The Bicep file is unvalidated.

## How a case flows

```
POST /cases -> queue -> worker -> extractor -> validate -> retrieve -> decide
                                                                      |-- auto_action  -> processed
                                                                      |-- human_review -> /reviews -> approve | reject
                                                                      `-- failures x3  -> dead-letter queue
agent (MCP): list_pending_reviews, get_case, propose_action ... execute_action only after a human approves via /actions
```

Every step appends to a hash-chained audit log (`/healthz` reports whether the chain still verifies).

## Run it

```bash
pip install -r requirements-dev.txt
pytest -q                                           # 53 tests, offline
export INGEST_API_KEY=dev-ingest REVIEWER_API_KEY=dev-review
uvicorn app.main:app                                # API, rule extractor, in-memory queue
python -m app.main worker                           # separate worker process (use with Service Bus)
python -m mcp_server.server                         # MCP server over stdio
python -m eval.run_eval --extractor rule && mlflow ui --backend-store-uri sqlite:///mlflow.db
docker build -t claims-intake . && docker run -p 8000:8000 -e INGEST_API_KEY=a -e REVIEWER_API_KEY=b claims-intake
```

Choose the extractor with `LLM_PROVIDER=rule | azure_openai | anthropic` (see `app/main.py` for the variables each one reads). Use `SERVICEBUS_CONNECTION_STRING` to switch from the in-memory queue to Service Bus.

## What is in each part

| Part | Where | Notes |
|---|---|---|
| Extraction with LLMs | `engine/llm.py` | Azure OpenAI (strict `json_schema`) and Anthropic (forced tool use) clients. Timeout, retry with backoff and `Retry-After`, client-side rate limit, Entra token or API-key auth. Not implemented: streaming. |
| Grounding check | `LLMExtractor` | A value the model returns is dropped, and the case forced to review, unless it appears in the document. The document is delimited and treated as untrusted. Known limit: number matching is textual, so a wrong number that also appears elsewhere in the document passes. |
| Safe routing rules | `engine/safe_expr.py` | The original `eval()` was replaced by an AST evaluator that allows only comparisons, boolean logic and arithmetic. Tests cover code-execution attempts. |
| Queue | `app/queue.py` | In-memory and an Azure Service Bus adapter, at-least-once delivery, dead-letter after 3 attempts. The adapter is tested against a fake with the same surface, not a real namespace. |
| API and human review | `app/api.py`, `app/store.py` | FastAPI, SQLite case store, two API-key roles (ingest, reviewer), decisions are final and audited. Production would use Entra ID or OIDC. |
| Agent tools (MCP) | `mcp_server/server.py`, `app/actions.py` | Five tools and no approve tool. Proposals are checked against an allow-list. Execution is refused unless a person approved, runs once, and writes to an outbox only (no ticketing or email system is connected). Handshake tested over stdio. |
| Retrieval (RAG) | `engine/vector.py` | Cosine index behind an `Embedder` interface. The offline embedder matches wording, not meaning. The Azure OpenAI embedder is tested against a fake transport. Not built: Azure AI Search or a persistent index. |
| Evaluation and tracking | `eval/` | 18 synthetic labelled documents (including prompt-injection and phrasing the regex misses), field-level precision and recall, tracked as MLflow runs. The rule baseline scores 0.97 precision and 0.94 recall on this set, which I wrote, so treat it as a regression check and not as evidence about real documents. The regex counts "not urgent" as urgent, which is a known miss. |
| Containers and CI | `Dockerfile`, `.github/workflows/ci.yml` | Non-root image. The workflow runs the tests, builds the image and checks that the container serves `/healthz`. |
| Infrastructure as code | `infra/main.bicep` | Log Analytics, Service Bus queue with dead-lettering, Key Vault, Container Apps. Written, not validated, not deployed. Secrets still need to be wired to Key Vault references. |

## Known gaps

- No live LLM run yet. Run `python -m eval.run_eval --extractor anthropic` (or `azure_openai`) with a key to get real numbers.
- Audit log and action outbox are in process memory. The case store is SQLite. A shared database is needed for the API, worker and MCP server to run as separate processes.
- No Databricks or Unity Catalog. MLflow tracks the evaluation runs locally only.
- Authentication is static API keys.

## Related project

[Two Hats](https://github.com/Kriti-Data-Business/fraud-deployment-validation-project) tests an LLM triage layer in the same spirit: a fraud model, an independent validation, and a bench that tries to break the AI assistant before anyone trusts it.
