from engine.audit import AuditLog
from engine.decide import decide
from engine.extract import Extractor, RuleExtractor
from engine.llm import ExtractionError
from engine.pack import Pack
from engine.retrieve import retrieve
from engine.validate import validate


def run(text: str, pack: Pack, audit: AuditLog, extractor: Extractor | None = None) -> dict:
    extractor = extractor or RuleExtractor()
    try:
        if hasattr(extractor, "extract_with_flags"):
            data, flags = extractor.extract_with_flags(text, pack)
        else:
            data, flags = extractor.extract(text, pack), []
        failure = None
    except ExtractionError as e:
        data, flags, failure = {}, [], f"extraction failed: {e}"
    issues = validate(data, pack) + flags + ([failure] if failure else [])
    context = retrieve(text, pack)
    route, reason = decide(data, issues, pack)  # any issue forces human_review
    rec = audit.append({"domain": pack.domain, "extracted": data, "issues": issues,
                        "context": context, "route": route, "reason": reason})
    return {"route": route, "reason": reason, "extracted": data, "issues": issues,
            "context": context, "audit_hash": rec["hash"]}
