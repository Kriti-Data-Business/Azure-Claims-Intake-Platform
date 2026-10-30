from engine.pack import Pack
from engine.safe_expr import evaluate


def decide(data: dict, issues: list[str], pack: Pack) -> tuple[str, str]:
    if issues:
        return "human_review", "validation issues: " + "; ".join(issues)
    for rule in pack.routes:
        try:
            if evaluate(rule.when, data):
                return rule.route, rule.name
        except KeyError:
            continue  # rule refers to a field that was not extracted
    return pack.default_route, "default"
