"""Execution-feedback error diagnosis (Step 3).

When a generated query fails to execute or returns an empty result set, this
module classifies the root cause into a fixed three-class taxonomy
(``syntax`` / ``type`` / ``data``) using a structured-output LLM call and emits
a short corrective guideline that can be stored as a schema note.

The module is intentionally self-contained: it does not import the SQL model or
result types directly. ``diagnose_failure`` accepts any chat model exposing a
``generate(messages, settings)`` method (e.g. the project's Qwen wrapper), and
the result is duck-typed (only ``.columns`` is read).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, List, Optional

from .schema_kb import extract_tables_from_sql, normalize_table


ERROR_TYPES = ("syntax", "type", "data")


DIAGNOSIS_SYSTEM_PROMPT = """You diagnose why a SQLite SELECT query failed or returned no rows.
Classify the root cause into exactly one of these error types:
- "syntax": the SQL is malformed or references a table/column that does not exist.
- "type": a value, comparison, or function is applied to an incompatible column type or format.
- "data": the SQL is valid but its filters/joins exclude all rows (e.g. wrong literal, case mismatch, over-strict condition).
Pick the single table most responsible for the problem.
Write a short, imperative guideline (<= 30 words) that, if added to the schema, would help a future query avoid this mistake.
Return ONLY a JSON object, no markdown or prose, in this exact shape:
{"target_table": "<table name>", "error_type": "syntax|type|data", "guideline": "<hint>"}"""


@dataclass(frozen=True)
class SchemaDiagnosis:
    """Structured output of the execution-feedback error diagnosis."""

    target_table: str
    error_type: str
    guideline: str
    raw_output: str


def build_diagnosis_messages(
    question: str,
    sql: str,
    schema: str,
    error_message: str = "",
    result: Optional[Any] = None,
) -> List[dict]:
    if error_message:
        outcome = f"Execution failed with error:\n{error_message}"
    elif result is not None:
        columns = ", ".join(getattr(result, "columns", []) or []) or "none"
        outcome = (
            "Execution succeeded but returned an empty result set "
            f"(0 rows, columns: {columns})."
        )
    else:
        outcome = "Execution produced no usable result."

    return [
        {"role": "system", "content": DIAGNOSIS_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Schema:\n"
                f"{schema}\n\n"
                "User question:\n"
                f"{question}\n\n"
                "Generated SQL:\n"
                f"{sql}\n\n"
                "Execution outcome:\n"
                f"{outcome}\n\n"
                "JSON diagnosis:"
            ),
        },
    ]


def diagnose_failure(
    question: str,
    sql: str,
    schema: str,
    model: Any,
    settings: Any = None,
    *,
    error_message: str = "",
    result: Optional[Any] = None,
) -> SchemaDiagnosis:
    """Diagnose a failed or empty execution into the fixed JSON taxonomy.

    ``model`` is any object with ``generate(messages, settings) -> str``.
    """

    messages = build_diagnosis_messages(
        question=question,
        sql=sql,
        schema=schema,
        error_message=error_message,
        result=result,
    )
    raw_output = model.generate(messages, settings)
    return parse_diagnosis(raw_output, fallback_sql=sql)


def parse_diagnosis(raw_output: str, fallback_sql: str = "") -> SchemaDiagnosis:
    payload = _extract_json_object(raw_output)

    target_table = ""
    error_type = ""
    guideline = ""
    if payload is not None:
        target_table = normalize_table(str(payload.get("target_table", "")))
        error_type = _normalize_error_type(str(payload.get("error_type", "")))
        guideline = str(payload.get("guideline", "")).strip()

    if not target_table:
        candidates = extract_tables_from_sql(fallback_sql)
        target_table = candidates[0] if candidates else "unknown"
    if not error_type:
        error_type = "data"
    if not guideline:
        guideline = (
            "Re-check this table's columns, value formats, and filter literals "
            "before querying it again."
        )

    return SchemaDiagnosis(
        target_table=target_table,
        error_type=error_type,
        guideline=guideline,
        raw_output=raw_output,
    )


def _normalize_error_type(value: str) -> str:
    lowered = (value or "").strip().lower()
    for error_type in ERROR_TYPES:
        if error_type in lowered:
            return error_type
    return ""


def _extract_json_object(text: str) -> Optional[dict]:
    if not text:
        return None

    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.IGNORECASE | re.DOTALL)

    candidates: List[str] = []
    fenced = re.search(
        r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.IGNORECASE | re.DOTALL
    )
    if fenced:
        candidates.append(fenced.group(1))

    brace = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if brace:
        candidates.append(brace.group(0))

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None
