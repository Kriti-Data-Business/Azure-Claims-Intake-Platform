import re
from typing import Protocol
from engine.pack import Pack


class Extractor(Protocol):
    def extract(self, text: str, pack: Pack) -> dict: ...


class RuleExtractor:
    def extract(self, text: str, pack: Pack) -> dict:
        out: dict = {}
        for f in pack.fields:
            if not f.pattern:
                continue
            m = re.search(f.pattern, text, re.IGNORECASE)
            if not m:
                continue
            raw = m.group(1).replace(",", "").strip()
            if f.type == "number":
                out[f.name] = float(raw)
            elif f.type == "boolean":
                out[f.name] = True
            else:
                out[f.name] = raw
        return out
