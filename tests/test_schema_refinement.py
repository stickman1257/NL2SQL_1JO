"""Tests for the Step 3 schema knowledge base and execution-feedback diagnosis.

These run without any LLM or GPU: the diagnosis step is exercised with a fake
model that returns canned structured output.

Run from the repo root:
    python -m pytest tests/test_schema_refinement.py
    # or, without pytest:
    python tests/test_schema_refinement.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from nl2sql_agent.schema import (  # noqa: E402
    SchemaKnowledgeBase,
    diagnose_failure,
    extract_tables_from_sql,
    normalize_table,
    parse_diagnosis,
)


class _FakeResult:
    def __init__(self, columns):
        self.columns = columns


class _FakeModel:
    """Returns a fixed response; records the messages it was called with."""

    def __init__(self, response: str):
        self.response = response
        self.last_messages = None

    def generate(self, messages, settings=None):
        self.last_messages = messages
        return self.response


def test_normalize_table_is_case_and_quote_insensitive():
    assert normalize_table('"Customers"') == "customers"
    assert normalize_table("main.Orders") == "orders"
    assert normalize_table("`Order_Items`") == "order_items"
    assert normalize_table("   ") == ""


def test_extract_tables_from_sql():
    sql = 'SELECT * FROM "Customers" c JOIN orders o ON c.id = o.cid'
    assert extract_tables_from_sql(sql) == ["customers", "orders"]


def test_knowledge_base_dedup_and_render():
    kb = SchemaKnowledgeBase()
    assert kb.add_note("customers", "data", "Status uses 1/0, not text") is True
    # Same guideline (even with different casing key) is not duplicated.
    assert kb.add_note('"Customers"', "data", "Status uses 1/0, not text") is False
    assert kb.add_note("orders", "type", "Dates are stored as YYYY-MM-DD text") is True

    rendered = kb.render_notes(["orders", "CUSTOMERS"])
    assert 'Table "customers":' in rendered
    assert 'Table "orders":' in rendered
    assert "[data] Status uses 1/0, not text" in rendered
    # Irrelevant tables yield no notes.
    assert kb.render_notes(["products"]) == ""


def test_knowledge_base_respects_per_table_cap():
    kb = SchemaKnowledgeBase(max_notes_per_table=2)
    for i in range(5):
        kb.add_note("t", "data", f"note {i}")
    notes = kb.notes_for(["t"])["t"]
    assert len(notes) == 2
    assert notes[0].guideline == "note 3"
    assert notes[1].guideline == "note 4"


def test_parse_diagnosis_extracts_json_from_noise():
    raw = 'blah {"target_table":"Orders","error_type":"data","guideline":"use code"} tail'
    diag = parse_diagnosis(raw)
    assert diag.target_table == "orders"
    assert diag.error_type == "data"
    assert diag.guideline == "use code"


def test_parse_diagnosis_falls_back_when_unparseable():
    diag = parse_diagnosis("not json at all", fallback_sql="SELECT * FROM customers")
    assert diag.target_table == "customers"
    assert diag.error_type == "data"
    assert diag.guideline


def test_diagnose_then_inject_loop():
    """End-to-end Step 3 loop with a fake model: diagnose -> store -> re-inject."""

    kb = SchemaKnowledgeBase()
    model = _FakeModel(
        '{"target_table": "customers", "error_type": "data", '
        '"guideline": "Active flag is 1/0, not \'Y\'/\'N\'."}'
    )

    diag = diagnose_failure(
        question="How many active customers are there?",
        sql="SELECT COUNT(*) FROM customers WHERE active = 'Y'",
        schema='Table: "customers"\n  - "active" INTEGER',
        model=model,
        result=_FakeResult(columns=["COUNT(*)"]),
    )
    assert diag.target_table == "customers"
    assert diag.error_type == "data"

    stored = kb.add_note(diag.target_table, diag.error_type, diag.guideline)
    assert stored is True

    injected = kb.render_notes(["customers"])
    assert "Active flag is 1/0" in injected
    # The diagnosis prompt actually carried the failure context to the model.
    assert "Generated SQL" in model.last_messages[-1]["content"]


def _run_all():
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    if failures:
        raise SystemExit(f"{failures} test(s) failed")
    print("All tests passed.")


if __name__ == "__main__":
    _run_all()
