import re
from engine.pack import Pack


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z]{4,}", s.lower()))


def retrieve(text: str, pack: Pack, k: int = 2) -> list[str]:
    q = _tokens(text)
    scored = sorted(((len(q & _tokens(d)), d) for d in pack.knowledge), reverse=True)
    return [d for s, d in scored[:k] if s > 0]
