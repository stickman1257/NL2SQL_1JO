import csv
import glob
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .config import DBSearchConfig
from .utils import compact_text, normalize_sql, quote_identifier, rows_to_jsonable, tokenize, unique_keep_order, validate_readonly_sql


@dataclass
class ColumnInfo:
    name: str
    type: str
    not_null: bool
    default: Optional[str]
    primary_key: bool
    description: str = ""
    value_description: str = ""


@dataclass
class ForeignKeyInfo:
    table: str
    column: str
    ref_table: str
    ref_column: str


@dataclass
class TableInfo:
    name: str
    columns: List[ColumnInfo] = field(default_factory=list)
    foreign_keys: List[ForeignKeyInfo] = field(default_factory=list)
    row_count: Optional[int] = None
    description: str = ""


@dataclass
class SchemaInfo:
    db_id: str
    sqlite_path: str
    tables: Dict[str, TableInfo]


@dataclass
class ExecutionResult:
    success: bool
    sql: str
    columns: List[str]
    rows: List[List[Any]]
    error: Optional[str]
    elapsed_s: float
    truncated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "sql": self.sql,
            "columns": self.columns,
            "rows": self.rows,
            "error": self.error,
            "elapsed_s": self.elapsed_s,
            "truncated": self.truncated,
        }


class DBSearchTool:
    name = "db_search"

    def __init__(self, config: DBSearchConfig):
        self.config = config
        self.root = Path(config.database_root).expanduser().resolve()
        self._schema_cache: Dict[str, SchemaInfo] = {}

    def resolve_sqlite_path(self, db_id: str) -> Path:
        candidates = [
            self.root / db_id / f"{db_id}.sqlite",
            self.root / db_id / f"{db_id}.db",
            self.root / f"{db_id}.sqlite",
            self.root / f"{db_id}.db",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        patterns = [
            str(self.root / db_id / "*.sqlite"),
            str(self.root / db_id / "*.db"),
            str(self.root / "**" / db_id / "*.sqlite"),
            str(self.root / "**" / db_id / "*.db"),
            str(self.root / "**" / f"{db_id}.sqlite"),
            str(self.root / "**" / f"{db_id}.db"),
        ]
        for pattern in patterns:
            matches = glob.glob(pattern, recursive=True)
            if matches:
                return Path(matches[0]).resolve()
        raise FileNotFoundError(f"SQLite database for db_id='{db_id}' was not found under {self.root}")

    def connect(self, db_id: str) -> sqlite3.Connection:
        path = self.resolve_sqlite_path(db_id)
        uri = f"file:{path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=self.config.execution_timeout_s)
        conn.execute("PRAGMA query_only=ON")
        return conn

    def load_schema(self, db_id: str) -> SchemaInfo:
        if db_id in self._schema_cache:
            return self._schema_cache[db_id]
        sqlite_path = self.resolve_sqlite_path(db_id)
        descriptions = self._load_descriptions(sqlite_path.parent)
        with self.connect(db_id) as conn:
            table_rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
            tables: Dict[str, TableInfo] = {}
            for (table_name,) in table_rows:
                table_info = TableInfo(name=table_name)
                table_description = descriptions.get(table_name, {}).get("__table__", {})
                table_info.description = compact_text(table_description.get("description") or table_description.get("table_description") or "")
                for row in conn.execute(f"PRAGMA table_info({quote_identifier(table_name)})").fetchall():
                    _, name, col_type, not_null, default_value, pk = row
                    desc_row = descriptions.get(table_name, {}).get(name, {})
                    table_info.columns.append(
                        ColumnInfo(
                            name=name,
                            type=col_type or "",
                            not_null=bool(not_null),
                            default=str(default_value) if default_value is not None else None,
                            primary_key=bool(pk),
                            description=compact_text(desc_row.get("column_description") or desc_row.get("description") or desc_row.get("column_name") or ""),
                            value_description=compact_text(desc_row.get("value_description") or desc_row.get("data_format") or ""),
                        )
                    )
                for fk in conn.execute(f"PRAGMA foreign_key_list({quote_identifier(table_name)})").fetchall():
                    _, _, ref_table, from_col, to_col, *_ = fk
                    table_info.foreign_keys.append(ForeignKeyInfo(table=table_name, column=from_col, ref_table=ref_table, ref_column=to_col))
                if self.config.count_rows:
                    try:
                        table_info.row_count = int(conn.execute(f"SELECT COUNT(*) FROM {quote_identifier(table_name)}").fetchone()[0])
                    except Exception:
                        table_info.row_count = None
                tables[table_name] = table_info
        schema = SchemaInfo(db_id=db_id, sqlite_path=str(sqlite_path), tables=tables)
        self._schema_cache[db_id] = schema
        return schema

    def list_tables(self, db_id: str) -> List[str]:
        return list(self.load_schema(db_id).tables.keys())
    
    def describe_tables(self, db_id: str, table_names: Optional[Sequence[str]] = None, include_samples: Optional[bool] = None) -> str:
        schema = self.load_schema(db_id)
        names = list(table_names) if table_names else list(schema.tables.keys())[: self.config.max_tables]
        valid_names = [name for name in names if name in schema.tables]
        return self._format_schema_context(schema, valid_names, self.config.include_samples if include_samples is None else include_samples)

    def foreign_keys(self, db_id: str, table_names: Optional[Sequence[str]] = None) -> List[Dict[str, str]]:
        schema = self.load_schema(db_id)
        allowed = set(table_names) if table_names else set(schema.tables.keys())
        items = []
        for table in schema.tables.values():
            for fk in table.foreign_keys:
                if fk.table in allowed or fk.ref_table in allowed:
                    items.append({"table": fk.table, "column": fk.column, "ref_table": fk.ref_table, "ref_column": fk.ref_column})
        return items
    
    def sample_values(self, db_id: str, table_name: str, columns: Optional[Sequence[str]] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        schema = self.load_schema(db_id)
        if table_name not in schema.tables:
            return []
        table = schema.tables[table_name]
        selected_columns = list(columns) if columns else [col.name for col in table.columns[: min(8, len(table.columns))]]
        selected_columns = [col for col in selected_columns if any(c.name == col for c in table.columns)]
        if not selected_columns:
            return []
        limit_value = limit or self.config.sample_rows
        column_sql = ", ".join(quote_identifier(col) for col in selected_columns)
        sql = f"SELECT {column_sql} FROM {quote_identifier(table_name)} LIMIT {int(limit_value)}"
        with self.connect(db_id) as conn:
            rows = conn.execute(sql).fetchall()
        result = []
        for row in rows:
            result.append({selected_columns[idx]: row[idx] for idx in range(len(selected_columns))})
        return result

    def search_schema(self, db_id: str, query: str, top_k: Optional[int] = None) -> List[str]:
        schema = self.load_schema(db_id)
        top_k_value = top_k or self.config.max_tables
        query_tokens = set(tokenize(query))
        scored: List[Tuple[float, str]] = []
        for table_name, table in schema.tables.items():
            text_parts = [table_name, table.description]
            for column in table.columns:
                text_parts.extend([column.name, column.type, column.description, column.value_description])
            table_tokens = set(tokenize(" ".join(text_parts)))
            overlap = len(query_tokens & table_tokens)
            exact = 0.0
            lowered_query = compact_text(query).lower()
            if table_name.lower() in lowered_query:
                exact += 6.0
            for column in table.columns:
                if column.name.lower() in lowered_query:
                    exact += 2.0
            score = overlap + exact
            scored.append((score, table_name))
        scored.sort(key=lambda item: (-item[0], item[1]))
        selected = [name for score, name in scored if score > 0][:top_k_value]
        if not selected:
            selected = [name for _, name in scored[:top_k_value]]
        selected = self._expand_with_foreign_key_neighbors(schema, selected, top_k_value)
        return selected

    def build_schema_context(
        self,
        db_id: str,
        question: str,
        evidence: Optional[str] = None,
        subquery: Optional[str] = None,
        op_tags: Optional[Sequence[str]] = None,
        top_k: Optional[int] = None,
        include_samples: Optional[bool] = None,
    ) -> str:
        search_text = "\n".join([question or "", evidence or "", subquery or "", " ".join(op_tags or [])])
        selected_tables = self.search_schema(db_id, search_text, top_k or self.config.max_tables)
        schema = self.load_schema(db_id)
        parts = [f"Database ID: {db_id}", f"SQLite path: {schema.sqlite_path}"]
        if evidence:
            parts.append(f"Evidence: {compact_text(evidence)}")
        if subquery:
            parts.append(f"Subquery: {compact_text(subquery)}")
        if op_tags:
            parts.append(f"Operation tags: {', '.join(op_tags)}")
        parts.append(self._format_schema_context(schema, selected_tables, self.config.include_samples if include_samples is None else include_samples))
        return "\n\n".join(part for part in parts if part)

    def execute_sql(self, db_id: str, sql: str, max_rows: Optional[int] = None, timeout_s: Optional[float] = None) -> ExecutionResult:
        start = time.perf_counter()
        normalized = normalize_sql(sql)
        safety_error = validate_readonly_sql(normalized)
        if safety_error:
            return ExecutionResult(False, normalized, [], [], safety_error, time.perf_counter() - start, False)
        row_limit = max_rows or self.config.max_result_rows
        deadline = start + (timeout_s or self.config.execution_timeout_s)
        try:
            with self.connect(db_id) as conn:
                def progress_handler() -> int:
                    return 1 if time.perf_counter() > deadline else 0

                conn.set_progress_handler(progress_handler, 1000)
                cursor = conn.execute(normalized)
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                rows = cursor.fetchmany(row_limit + 1)
                truncated = len(rows) > row_limit
                rows = rows[:row_limit]
                return ExecutionResult(True, normalized, columns, rows_to_jsonable(rows), None, time.perf_counter() - start, truncated)
        except Exception as exc:
            return ExecutionResult(False, normalized, [], [], str(exc), time.perf_counter() - start, False)

    def call(self, db_id: str, action: str, **kwargs: Any) -> Any:
        if action == "list_tables":
            return self.list_tables(db_id)
        if action == "describe_tables":
            return self.describe_tables(db_id, kwargs.get("table_names"), kwargs.get("include_samples"))
        if action == "foreign_keys":
            return self.foreign_keys(db_id, kwargs.get("table_names"))
        if action == "sample_values":
            return self.sample_values(db_id, kwargs["table_name"], kwargs.get("columns"), kwargs.get("limit"))
        if action == "search_schema":
            return self.search_schema(db_id, kwargs.get("query", ""), kwargs.get("top_k"))
        if action == "build_schema_context":
            return self.build_schema_context(
                db_id,
                kwargs.get("question", ""),
                kwargs.get("evidence"),
                kwargs.get("subquery"),
                kwargs.get("op_tags"),
                kwargs.get("top_k"),
                kwargs.get("include_samples"),
            )
        if action == "execute_sql":
            return self.execute_sql(db_id, kwargs["sql"], kwargs.get("max_rows"), kwargs.get("timeout_s"))
        raise ValueError(f"Unsupported db_search action: {action}")

    def _expand_with_foreign_key_neighbors(self, schema: SchemaInfo, selected: List[str], limit: int) -> List[str]:
        result = list(selected)
        for table_name in list(selected):
            table = schema.tables.get(table_name)
            if not table:
                continue
            for fk in table.foreign_keys:
                result.append(fk.ref_table)
            for other in schema.tables.values():
                for fk in other.foreign_keys:
                    if fk.ref_table == table_name:
                        result.append(other.name)
        return [name for name in unique_keep_order(result) if name in schema.tables][:limit]

    def _format_schema_context(self, schema: SchemaInfo, table_names: Sequence[str], include_samples: bool) -> str:
        parts = ["Selected schema:"]
        for table_name in table_names[: self.config.max_tables]:
            table = schema.tables[table_name]
            header = f"Table: {table.name}"
            if table.description:
                header += f" | {table.description}"
            if table.row_count is not None:
                header += f" | rows={table.row_count}"
            parts.append(header)
            for column in table.columns[: self.config.max_columns_per_table]:
                flags = []
                if column.primary_key:
                    flags.append("PK")
                if column.not_null:
                    flags.append("NOT_NULL")
                flag_text = f" [{', '.join(flags)}]" if flags else ""
                desc = ""
                if self.config.include_descriptions and (column.description or column.value_description):
                    desc = f" | {compact_text(' '.join([column.description, column.value_description]))}"
                parts.append(f"  - {column.name} {column.type}{flag_text}{desc}")
            for fk in table.foreign_keys:
                parts.append(f"  FK: {fk.table}.{fk.column} -> {fk.ref_table}.{fk.ref_column}")
            if include_samples and self.config.sample_rows > 0:
                try:
                    samples = self.sample_values(schema.db_id, table.name, limit=self.config.sample_rows)
                    if samples:
                        parts.append(f"  Sample rows: {samples}")
                except Exception:
                    pass
        return "\n".join(parts)

    def _load_descriptions(self, db_folder: Path) -> Dict[str, Dict[str, Dict[str, str]]]:
        if not self.config.include_descriptions:
            return {}
        description_dirs = [db_folder / "database_description", db_folder / "db_description"]
        description_dirs.extend(db_folder.glob("**/database_description"))
        result: Dict[str, Dict[str, Dict[str, str]]] = {}
        for directory in description_dirs:
            if not directory.exists() or not directory.is_dir():
                continue
            for csv_path in directory.glob("*.csv"):
                table_name = csv_path.stem
                rows = self._read_csv(csv_path)
                if table_name not in result:
                    result[table_name] = {}
                for row in rows:
                    original = row.get("original_column_name") or row.get("column_name") or row.get("name") or row.get("column")
                    if not original:
                        continue
                    result[table_name][original] = {str(k): str(v) for k, v in row.items() if v is not None}
        return result

    def _read_csv(self, path: Path) -> List[Dict[str, str]]:
        encodings = ["utf-8-sig", "utf-8", "latin-1"]
        for encoding in encodings:
            try:
                with path.open("r", encoding=encoding, newline="") as f:
                    return list(csv.DictReader(f))
            except Exception:
                continue
        return []
