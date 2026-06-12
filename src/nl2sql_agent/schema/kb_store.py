"""Schema KB 공유 모델, 로드/저장, 읽기 저장소."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Sequence


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

    @property
    def version(self) -> int:
        return len(self.history) if self.history else 1

    @property
    def updated_at(self) -> str:
        if self.history:
            return self.history[-1].updated_at
        return ""


@dataclass
class SchemaKBConfig:
    enabled: bool = True
    path: str | None = None
    path_template: str = "data/schema/{db_id}_kb.json"
    merge_mode: str = "supplement"
    include_in_search: bool = True


def column_key(table: str, column: str) -> str:
    return f"{table}.{column}"


def load_kb_file(path: str) -> dict[str, ColumnKBEntry]:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    entries: dict[str, ColumnKBEntry] = {}
    for key, value in raw.items():
        history = [DescriptionVersion(**item) for item in value.get("history", [])]
        entries[key] = ColumnKBEntry(
            table=value["table"],
            column=value["column"],
            current_description=value["current_description"],
            history=history,
        )
    return entries


def save_kb_file(path: str, entries: dict[str, ColumnKBEntry]) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {key: asdict(entry) for key, entry in entries.items()},
            f,
            ensure_ascii=False,
            indent=2,
        )


def resolve_kb_path(config: SchemaKBConfig, db_id: str, base_dir: Path) -> Path | None:
    if not config.enabled:
        return None
    candidates: list[Path] = []
    if config.path:
        path = Path(config.path)
        candidates.append(path if path.is_absolute() else base_dir / path)
    if config.path_template:
        path = Path(config.path_template.format(db_id=db_id))
        candidates.append(path if path.is_absolute() else base_dir / path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def format_enriched_note(entry: ColumnKBEntry) -> str:
    date_part = entry.updated_at[:10] if entry.updated_at else "unknown"
    return f"enriched_note (v{entry.version}, {date_part}): {entry.current_description}"


def merge_column_descriptions(
    db_description: str,
    value_description: str,
    kb_entry: ColumnKBEntry | None,
    merge_mode: str = "supplement",
) -> tuple[str, str | None, str | None]:
    """
    DB/CSV 설명과 KB 설명을 병합한다.

    Returns:
        primary_desc: 컬럼 라인에 붙일 기본 설명
        enriched_line: supplement 모드 KB 보조 라인 (들여쓰기 제외)
        kb_hit: 사용된 KB 키 (table.column) 또는 None
    """
    primary_parts = [part for part in (db_description, value_description) if part]
    primary_desc = " ".join(primary_parts).strip()

    if not kb_entry or not kb_entry.current_description or merge_mode != "supplement":
        return primary_desc, None, None

    kb_hit = column_key(kb_entry.table, kb_entry.column)
    return primary_desc, format_enriched_note(kb_entry), kb_hit


class SchemaKBStore:
    """Schema KB JSON 파일 읽기 저장소."""

    def __init__(self, kb_path: str):
        self.kb_path = kb_path
        self._entries: dict[str, ColumnKBEntry] = {}
        if kb_path and os.path.exists(kb_path):
            self._entries = load_kb_file(kb_path)

    @classmethod
    def from_config(cls, config: SchemaKBConfig, db_id: str, base_dir: Path) -> SchemaKBStore | None:
        path = resolve_kb_path(config, db_id, base_dir)
        if path is None:
            return None
        return cls(str(path))

    def get_entry(self, table: str, column: str) -> ColumnKBEntry | None:
        return self._entries.get(column_key(table, column))

    def get_for_tables(self, table_names: Sequence[str]) -> dict[tuple[str, str], ColumnKBEntry]:
        allowed = set(table_names)
        return {
            (entry.table, entry.column): entry
            for entry in self._entries.values()
            if entry.table in allowed
        }

    def as_dict(self) -> dict[tuple[str, str], str]:
        return {(entry.table, entry.column): entry.current_description for entry in self._entries.values()}

    def all_entries(self) -> dict[str, ColumnKBEntry]:
        return dict(self._entries)

    def __len__(self) -> int:
        return len(self._entries)
