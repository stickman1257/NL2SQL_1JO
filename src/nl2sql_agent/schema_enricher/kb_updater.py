"""Step 5: Schema KB 컬럼 설명 버저닝 및 저장."""

from __future__ import annotations

from datetime import datetime

from nl2sql_agent.schema.kb_store import (
    ColumnKBEntry,
    DescriptionVersion,
    SchemaKBStore,
    column_key,
    save_kb_file,
)

from .db_explorer import ExplorationResult


class SchemaKBUpdater(SchemaKBStore):
    """
    컬럼 설명을 버저닝하며 JSON 파일 기반 KB에 저장한다.

    덮어쓰기 대신 history를 누적해 회귀를 방지한다.
    읽기 로직은 SchemaKBStore와 공유한다.
    """

    def save(self) -> None:
        save_kb_file(self.kb_path, self._entries)

    def get_description(self, table: str, column: str) -> str:
        entry = self.get_entry(table, column)
        return entry.current_description if entry else ""

    def update(self, result: ExplorationResult) -> None:
        """탐색 결과로 KB를 업데이트한다. 기존 설명은 history에 보존한다."""
        if not result.done or not result.enriched_description:
            return

        key = column_key(result.table, result.column)
        entry = self._entries.get(key)
        now = datetime.now().isoformat()

        if entry is None:
            self._entries[key] = ColumnKBEntry(
                table=result.table,
                column=result.column,
                current_description=result.enriched_description,
                history=[
                    DescriptionVersion(
                        description=result.enriched_description,
                        version=1,
                        updated_at=now,
                    )
                ],
            )
        else:
            next_version = len(entry.history) + 1
            entry.history.append(
                DescriptionVersion(
                    description=result.enriched_description,
                    version=next_version,
                    updated_at=now,
                )
            )
            entry.current_description = result.enriched_description
