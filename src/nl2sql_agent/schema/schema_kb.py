"""In-memory schema knowledge base for execution-feedback driven refinement.

This realises the "Dynamic Schema Update" component (Step 3): execution feedback
(failures / empty results) is distilled into short per-table notes that are
re-injected into a later SQL-generation prompt for the relevant tables only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from threading import Lock
from typing import Dict, Iterable, List


@dataclass(frozen=True)
class SchemaNote:
    """A single execution-feedback note attached to one table."""

    error_type: str
    guideline: str

    def render(self) -> str:
        return f"[{self.error_type}] {self.guideline}"


class SchemaKnowledgeBase:
    """In-memory key-value store mapping a table name to execution-feedback notes."""

    def __init__(self, max_notes_per_table: int = 8) -> None:
        self._notes: Dict[str, List[SchemaNote]] = {}
        self._lock = Lock()
        self._max_notes_per_table = max(1, int(max_notes_per_table))

    def add_note(self, table: str, error_type: str, guideline: str) -> bool:
        key = normalize_table(table)
        guideline = (guideline or "").strip()
        if not key or not guideline:
            return False

        note = SchemaNote(
            error_type=(error_type or "unknown").strip() or "unknown",
            guideline=guideline,
        )
        with self._lock:
            notes = self._notes.setdefault(key, [])
            if any(existing.guideline == note.guideline for existing in notes):
                return False
            notes.append(note)
            if len(notes) > self._max_notes_per_table:
                del notes[0]
        return True

    def notes_for(self, tables: Iterable[str]) -> Dict[str, List[SchemaNote]]:
        wanted = {normalize_table(table) for table in tables}
        wanted.discard("")
        result: Dict[str, List[SchemaNote]] = {}
        with self._lock:
            for key in wanted:
                notes = self._notes.get(key)
                if notes:
                    result[key] = list(notes)
        return result

    def render_notes(self, tables: Iterable[str]) -> str:
        relevant = self.notes_for(tables)
        if not relevant:
            return ""

        lines: List[str] = []
        for table in sorted(relevant):
            lines.append(f'Table "{table}":')
            for note in relevant[table]:
                lines.append(f"  - {note.render()}")
        return "\n".join(lines)

    def tables(self) -> List[str]:
        with self._lock:
            return sorted(key for key, notes in self._notes.items() if notes)

    def clear(self) -> None:
        with self._lock:
            self._notes.clear()


def normalize_table(table: str) -> str:
    """Normalise a table identifier for case-insensitive key matching."""

    text = (table or "").strip()
    if not text:
        return ""
    # Strip a leading schema qualifier such as "main.customers".
    text = text.split(".")[-1]
    text = text.strip().strip('"').strip("`").strip("'")
    text = text.strip("[").strip("]")
    return text.lower()


_TABLE_REF = re.compile(
    r"\b(?:FROM|JOIN)\s+"
    r"(\"[^\"]+\"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)",
    re.IGNORECASE,
)


def extract_tables_from_sql(sql: str) -> List[str]:
    """Best-effort extraction of referenced tables from a SQL statement."""

    if not sql:
        return []

    found: List[str] = []
    seen = set()
    for match in _TABLE_REF.finditer(sql):
        normalized = normalize_table(match.group(1))
        if normalized and normalized not in seen:
            seen.add(normalized)
            found.append(normalized)
    return found
