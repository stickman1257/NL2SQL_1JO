"""Schema knowledge base and execution-feedback diagnosis (Step 3)."""

from .diagnosis import (
    DIAGNOSIS_SYSTEM_PROMPT,
    ERROR_TYPES,
    SchemaDiagnosis,
    build_diagnosis_messages,
    diagnose_failure,
    parse_diagnosis,
)
from .schema_kb import (
    SchemaKnowledgeBase,
    SchemaNote,
    extract_tables_from_sql,
    normalize_table,
)

__all__ = [
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
