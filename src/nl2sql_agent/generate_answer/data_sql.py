from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from NL2SQL_1JO.src.nl2sql_agent.generate_answer.llm_io import SqlExecutionResult


@dataclass(frozen=True)
class BirdExample:
    index: int
    question_id: int | None
    db_id: str
    question: str
    sql: str
    evidence: str | None
    difficulty: str | None
    db_path: Path


def load_bird_example(data_path: Path, db_root: Path, index: int) -> BirdExample:
    if not data_path.exists():
        raise FileNotFoundError(f"dev.json not found: {data_path}")

    if not db_root.exists():
        raise FileNotFoundError(f"database root not found: {db_root}")

    with data_path.open("r", encoding="utf-8") as f:
        dev_data: list[dict[str, Any]] = json.load(f)

    if index < 0 or index >= len(dev_data):
        raise IndexError(f"index {index} is out of range for {data_path} ({len(dev_data)} rows)")

    sample = dev_data[index]
    db_id = sample["db_id"]
    db_path = db_root / db_id / f"{db_id}.sqlite"

    if not db_path.exists():
        raise FileNotFoundError(f"sqlite file not found: {db_path}")

    return BirdExample(
        index=index,
        question_id=sample.get("question_id"),
        db_id=db_id,
        question=sample["question"],
        sql=sample["SQL"],
        evidence=sample.get("evidence"),
        difficulty=sample.get("difficulty"),
        db_path=db_path,
    )


def execute_sql(db_path: Path, sql: str) -> SqlExecutionResult:
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(sql)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description] if cursor.description else []

    return SqlExecutionResult(columns=columns, rows=rows)
