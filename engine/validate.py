from engine.pack import Pack


def validate(data: dict, pack: Pack) -> list[str]:
    issues: list[str] = []
    for f in pack.fields:
        v = data.get(f.name)
        if v is None:
            if f.required:
                issues.append(f"missing required field: {f.name}")
            continue
        if f.type == "number":
            if f.min is not None and v < f.min:
                issues.append(f"{f.name} below minimum {f.min}")
            if f.max is not None and v > f.max:
                issues.append(f"{f.name} above maximum {f.max}")
    return issues
