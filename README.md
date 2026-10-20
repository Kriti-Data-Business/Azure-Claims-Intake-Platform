# Document-to-Action Platform (domain-pluggable)

One engine, many domains. A **domain pack** (YAML) defines the fields to extract, validation rules, routing rules and a small knowledge base. The engine extracts, validates, retrieves context, decides a route (auto-action, human review, reject) and emits an audit record.

Included packs:
- `retail_supplier_contract` - supplier agreements (payment terms, rebates, exclusivity, renewal, liability cap)
- `claims_intake` - insurance/complaint intake

Adding a new domain (e.g. legal NDAs, healthcare referrals) = a new YAML file, no engine change.

```bash
pip install -r requirements.txt
pytest -q
python -m engine.cli packs/retail_supplier_contract.yaml samples/supplier_contract.txt
```

## Design
- `engine/extract.py`: extractor interface. `RuleExtractor` (offline, regex) now; `AzureOpenAIExtractor` plugs in later with structured output.
- `engine/validate.py`: required fields, type checks, per-field rules from the pack.
- `engine/retrieve.py`: keyword retrieval over pack knowledge (swap for Azure AI Search later).
- `engine/decide.py`: routing rules in the pack (`when` expressions on extracted fields).
- `engine/audit.py`: immutable, hash-chained audit records.

## Roadmap
- [ ] FastAPI wrapper + Service Bus intake (reuse claims-intake-platform)
- [ ] Azure OpenAI extractor with structured outputs
- [ ] AI Search retrieval, agent tool calls (create ticket, notify)
- [ ] Evaluation harness: field-level precision/recall per pack
