from engine.llm import LLMExtractor
from engine.pack import load_pack
from engine.redact import redact
from pathlib import Path

PACK = load_pack(Path(__file__).resolve().parent.parent / "packs/clinical_referral.yaml")


def test_identifiers_are_masked():
    out = redact("Contact jo.smith@example.com or 0412 345 678, DOB 04/05/1961, Medicare 2123 45670 1.")
    assert "@" not in out and "0412" not in out and "1961" not in out and "[EMAIL]" in out and "[PHONE]" in out


def test_clinical_numbers_survive():
    t = "Routine referral, waiting 120 days. Estimate $12,400. Rebate of 7.5%."
    assert redact(t) == t


def test_llm_sees_redacted_text_but_grounding_uses_original():
    seen = {}

    class Fake:
        def complete_structured(self, system, user, schema):
            seen["user"] = user
            return {"urgency": "routine", "specialty": "cardiology", "days_waiting": 120, "red_flag": None}

    text = "Referral to cardiology. Routine, waiting 120 days. Call 0412 345 678."
    d, flags = LLMExtractor(Fake()).extract_with_flags(text, PACK)
    assert "0412" not in seen["user"] and "[PHONE]" in seen["user"]
    assert d["days_waiting"] == 120 and not flags
