import pytest
from engine.safe_expr import UnsafeExpression, evaluate


def test_comparisons_and_logic():
    assert evaluate("amount < 1000 and not urgent", {"amount": 500, "urgent": False})
    assert evaluate("1 < x <= 5", {"x": 5})
    assert not evaluate("x > 5 or y", {"x": 1, "y": False})


def test_missing_field_raises_keyerror():
    with pytest.raises(KeyError):
        evaluate("amount < 10", {})


@pytest.mark.parametrize("bad", [
    "__import__('os').system('echo hi')",
    "().__class__.__bases__",
    "open('/etc/passwd')",
    "[x for x in range(3)]",
    "(lambda: 1)()",
    "a[0]",
])
def test_code_execution_is_refused(bad):
    with pytest.raises(UnsafeExpression):
        evaluate(bad, {"a": [1]})
