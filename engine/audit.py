import hashlib, json
from datetime import datetime, timezone


class AuditLog:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def append(self, payload: dict) -> dict:
        prev = self.records[-1]["hash"] if self.records else "GENESIS"
        body = {"ts": datetime.now(timezone.utc).isoformat(), "prev": prev, **payload}
        body["hash"] = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
        self.records.append(body)
        return body

    def verify(self) -> bool:
        prev = "GENESIS"
        for r in self.records:
            h = r["hash"]
            body = {k: v for k, v in r.items() if k != "hash"}
            if body["prev"] != prev or hashlib.sha256(
                json.dumps(body, sort_keys=True, default=str).encode()).hexdigest() != h:
                return False
            prev = h
        return True
