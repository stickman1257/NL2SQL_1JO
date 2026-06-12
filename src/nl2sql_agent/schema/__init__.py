"""Schema knowledge base, execution-feedback diagnosis, and Enricher KB store."""

from .diagnosis import (
    DIAGNOSIS_SYSTEM_PROMPT,
    ERROR_TYPES,
    SchemaDiagnosis,
    build_diagnosis_messages,
    diagnose_failure,
    parse_diagnosis,
)
from .kb_store import (
    ColumnKBEntry,
    DescriptionVersion,
    SchemaKBConfig,
    SchemaKBStore,
    column_key,
    format_enriched_note,
    merge_column_descriptions,
    resolve_kb_path,
    save_kb_file,
)
from .schema_kb import (
    SchemaKnowledgeBase,
    SchemaNote,
    extract_tables_from_sql,
    normalize_table,
)

__all__ = [
    "ColumnKBEntry",
    "DescriptionVersion",
    "SchemaKBConfig",
    "SchemaKBStore",
    "column_key",
    "format_enriched_note",
    "merge_column_descriptions",
    "resolve_kb_path",
    "save_kb_file",
    "SchemaKnowledgeBase",
    "SchemaNote",
    "extract_tables_from_sql",
    "normalize_table",
    "SchemaDiagnosis",
    "diagnose_failure",
    "parse_diagnosis",
    "build_diagnosis_messages",
    "DIAGNOSIS_SYSTEM_PROMPT",
    "ERROR_TYPES",
]
