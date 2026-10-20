from pathlib import Path
from pydantic import BaseModel
import yaml


class FieldSpec(BaseModel):
    name: str
    type: str = "string"          # string | number | boolean
    required: bool = False
    pattern: str | None = None    # regex used by RuleExtractor; capture group 1 = value
    min: float | None = None
    max: float | None = None


class RouteRule(BaseModel):
    name: str
    when: str                     # python expression over extracted fields, e.g. "rebate_pct > 5"
    route: str                    # auto_action | human_review | reject


class Pack(BaseModel):
    domain: str
    fields: list[FieldSpec]
    routes: list[RouteRule]
    default_route: str = "human_review"
    knowledge: list[str] = []


def load_pack(path: str | Path) -> Pack:
    return Pack.model_validate(yaml.safe_load(Path(path).read_text()))
