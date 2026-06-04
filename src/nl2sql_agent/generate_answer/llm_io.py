from __future__ import annotations

from dataclasses import dataclass
from typing import Any


SYSTEM_MESSAGE = (
    "You are a helpful assistant. Based on the SQL execution result, answer "
    "the user's question clearly and concisely in natural language. Do not "
    "mention chain-of-thought."
)


@dataclass(frozen=True)
class SqlExecutionResult:
    columns: list[str]
    rows: list[tuple[Any, ...]]


def format_sql_result(result: SqlExecutionResult, max_rows: int | None = None) -> str:
    rows = result.rows if max_rows is None else result.rows[:max_rows]
    result_lines = [f"Columns: {result.columns}"]

    if rows:
        result_lines.append("Rows:")
        result_lines.extend(str(row) for row in rows)
    else:
        result_lines.append("Rows: []")

    if max_rows is not None and len(result.rows) > max_rows:
        result_lines.append(f"... truncated {len(result.rows) - max_rows} more rows")

    return "\n".join(result_lines)


def build_llm_messages(
    question: str,
    sql: str,
    result: SqlExecutionResult,
    max_rows: int | None = None,
) -> list[dict[str, str]]:
    result_text = format_sql_result(result=result, max_rows=max_rows)

    return [
        {
            "role": "system",
            "content": SYSTEM_MESSAGE,
        },
        {
            "role": "user",
            "content": (
                f"Question: {question}\n"
                f"SQL: {sql}\n"
                f"Execution Result:\n{result_text}\n\n"
                "Please provide only the final natural-language answer."
            ),
        },
    ]


def format_messages_for_log(messages: list[dict[str, str]]) -> str:
    """Readable representation of the exact chat messages before tokenization."""
    blocks = []
    for message in messages:
        role = message["role"].upper()
        blocks.append(f"[{role}]\n{message['content']}")
    return "\n\n".join(blocks)
