"""Step 5: Schema KB 컬럼 설명 버저닝 및 저장."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime

from .db_explorer import ExplorationResult


@dataclass
class DescriptionVersion:
    description: str
    version: int
    updated_at: str
    source: str = "schema_enricher"


@dataclass
class ColumnKBEntry:
    table: str
    column: str
    current_description: str
    history: list[DescriptionVersion] = field(default_factory=list)


class SchemaKBUpdater:
    """
    컬럼 설명을 버저닝하며 JSON 파일 기반 KB에 저장한다.

    덮어쓰기 대신 history를 누적해 회귀를 방지한다.
    """

    def __init__(self, kb_path: str):
        self.kb_path = kb_path
        self._kb: dict[str, ColumnKBEntry] = {}
        if os.path.exists(kb_path):
            self._load()

    def _key(self, table: str, column: str) -> str:
        return f"{table}.{column}"

    def _load(self) -> None:
        with open(self.kb_path) as f:
            raw = json.load(f)
        for k, v in raw.items():
            history = [DescriptionVersion(**h) for h in v.get("history", [])]
            self._kb[k] = ColumnKBEntry(
                table=v["table"],
                column=v["column"],
                current_description=v["current_description"],
                history=history,
            )

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.kb_path), exist_ok=True)
        with open(self.kb_path, "w") as f:
            json.dump(
                {k: asdict(v) for k, v in self._kb.items()},
                f,
                ensure_ascii=False,
                indent=2,
            )

    def get_description(self, table: str, column: str) -> str:
        return self._kb.get(self._key(table, column), ColumnKBEntry(table, column, "")).current_description

    def update(self, result: ExplorationResult) -> None:
        """탐색 결과로 KB를 업데이트한다. 기존 설명은 history에 보존한다."""
        if not result.done or not result.enriched_description:
            return

        key = self._key(result.table, result.column)
        entry = self._kb.get(key)

        if entry is None:
            self._kb[key] = ColumnKBEntry(
                table=result.table,
                column=result.column,
                current_description=result.enriched_description,
                history=[
                    DescriptionVersion(
                        description=result.enriched_description,
                        version=1,
                        updated_at=datetime.now().isoformat(),
                    )
                ],
            )
        else:
            next_version = len(entry.history) + 1
            entry.history.append(
                DescriptionVersion(
                    description=result.enriched_description,
                    version=next_version,
                    updated_at=datetime.now().isoformat(),
                )
            )
            entry.current_description = result.enriched_description

    def as_dict(self) -> dict[tuple[str, str], str]:
        """column_selector가 사용하는 existing_kb 형식으로 반환한다."""
        return {
            (e.table, e.column): e.current_description
            for e in self._kb.values()
        }
