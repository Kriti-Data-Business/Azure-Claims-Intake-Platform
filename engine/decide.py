from engine.pack import Pack


def decide(data: dict, issues: list[str], pack: Pack) -> tuple[str, str]:
    if issues:
        return "human_review", "validation issues: " + "; ".join(issues)
    for rule in pack.routes:
        try:
            # restricted eval: only extracted fields, no builtins
            if eval(rule.when, {"__builtins__": {}}, dict(data)):  # noqa: S307
                return rule.route, rule.name
        except NameError:
            continue
    return pack.default_route, "default"
