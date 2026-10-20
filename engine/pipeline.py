from engine.audit import AuditLog
from engine.decide import decide
from engine.extract import Extractor, RuleExtractor
from engine.pack import Pack
from engine.retrieve import retrieve
from engine.validate import validate


def run(text: str, pack: Pack, audit: AuditLog, extractor: Extractor | None = None) -> dict:
    extractor = extractor or RuleExtractor()
    data = extractor.extract(text, pack)
    issues = validate(data, pack)
    context = retrieve(text, pack)
    route, reason = decide(data, issues, pack)
    rec = audit.append({"domain": pack.domain, "extracted": data, "issues": issues,
                        "context": context, "route": route, "reason": reason})
    return {"route": route, "reason": reason, "extracted": data, "issues": issues,
            "context": context, "audit_hash": rec["hash"]}
