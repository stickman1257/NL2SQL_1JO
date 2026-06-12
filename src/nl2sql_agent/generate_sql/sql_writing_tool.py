from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from .config import SQLWriterConfig
from .llm_client import BaseLLMClient
from .utils import extract_json_object, extract_sql, normalize_sql, validate_readonly_sql


@dataclass
class SQLCandidate:
    sql: str
    confidence: Optional[float]
    rationale: str
    used_tables: List[str]
    raw_response: str
    validation_error: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sql": self.sql,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "used_tables": self.used_tables,
            "raw_response": self.raw_response,
            "validation_error": self.validation_error,
        }


class SQLWritingTool:
    name = "sql_writer"

    def __init__(self, llm: BaseLLMClient, config: SQLWriterConfig):
        self.llm = llm
        self.config = config

    def write_sql(
        self,
        question: str,
        schema_context: str,
        evidence: Optional[str] = None,
        subquery: Optional[str] = None,
        subquery_type: Optional[str] = None,
        op_tags: Optional[Sequence[str]] = None,
    ) -> SQLCandidate:
        messages = self._build_generation_messages(question, schema_context, evidence, subquery, subquery_type, op_tags)
        raw = self.llm.chat(messages)
        return self._parse_candidate(raw)

    def repair_sql(
        self,
        question: str,
        schema_context: str,
        previous_sql: str,
        error: str,
        evidence: Optional[str] = None,
        subquery: Optional[str] = None,
        subquery_type: Optional[str] = None,
        op_tags: Optional[Sequence[str]] = None,
    ) -> SQLCandidate:
        messages = self._build_repair_messages(question, schema_context, previous_sql, error, evidence, subquery, subquery_type, op_tags)
        raw = self.llm.chat(messages)
        return self._parse_candidate(raw)

    def call(self, action: str, **kwargs: Any) -> SQLCandidate:
        if action == "write_sql":
            return self.write_sql(**kwargs)
        if action == "repair_sql":
            return self.repair_sql(**kwargs)
        raise ValueError(f"Unsupported sql_writer action: {action}")

    def _parse_candidate(self, raw: str) -> SQLCandidate:
        obj = extract_json_object(raw)
        sql = normalize_sql(str(obj.get("sql") or extract_sql(raw)))
        confidence = self._parse_confidence(obj.get("confidence"))
        rationale = str(obj.get("rationale") or obj.get("explanation") or "").strip()
        used_tables = obj.get("used_tables") or []
        if isinstance(used_tables, str):
            used_tables = [item.strip() for item in used_tables.split(",") if item.strip()]
        if not isinstance(used_tables, list):
            used_tables = []
        validation_error = validate_readonly_sql(sql)
        return SQLCandidate(sql, confidence, rationale, [str(x) for x in used_tables], raw, validation_error)

    def _parse_confidence(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            numeric = float(value)
            if numeric < 0:
                return 0.0
            if numeric > 1:
                return 1.0
            return numeric
        except Exception:
            return None

    def _build_generation_messages(
        self,
        question: str,
        schema_context: str,
        evidence: Optional[str],
        subquery: Optional[str],
        subquery_type: Optional[str],
        op_tags: Optional[Sequence[str]],
    ) -> List[Dict[str, str]]:
        system = self._system_prompt()
        user = self._task_prompt(question, schema_context, evidence, subquery, subquery_type, op_tags)
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def _build_repair_messages(
        self,
        question: str,
        schema_context: str,
        previous_sql: str,
        error: str,
        evidence: Optional[str],
        subquery: Optional[str],
        subquery_type: Optional[str],
        op_tags: Optional[Sequence[str]],
    ) -> List[Dict[str, str]]:
        system = self._system_prompt()
        user = self._task_prompt(question, schema_context, evidence, subquery, subquery_type, op_tags)
        repair = f"""
The previous SQL failed validation or execution.
Previous SQL:
{previous_sql}

Error feedback:
{error}

Generate a corrected SQL query. Keep the same output JSON format.
""".strip()
        return [{"role": "system", "content": system}, {"role": "user", "content": user + "\n\n" + repair}]

    def _system_prompt(self) -> str:
        return f"""
You are a careful Text-to-SQL agent for the {self.config.dialect} dialect.
You must produce one executable read-only SQL query.
Use only tables and columns that appear in the provided schema context.
Do not invent schema elements.
Use the provided evidence as a business rule when it is relevant.
When joins are necessary, infer join keys from the foreign key information in the schema context.
For identifiers containing spaces or special characters, quote them with double quotes.
Return JSON only. Do not return markdown.
The JSON schema is: {{"sql": "...", "used_tables": ["..."], "confidence": 0.0, "rationale": "..."}}.
""".strip()

    def _task_prompt(
        self,
        question: str,
        schema_context: str,
        evidence: Optional[str],
        subquery: Optional[str],
        subquery_type: Optional[str],
        op_tags: Optional[Sequence[str]],
    ) -> str:
        op_tag_text = ", ".join(op_tags or [])
        parts = [
            f"Original user question:\n{question}",
            f"Database schema context:\n{schema_context}",
        ]
        if evidence:
            parts.append(f"Evidence:\n{evidence}")
        if subquery:
            parts.append(f"Current subquery to solve:\n{subquery}")
        if subquery_type:
            parts.append(f"Subquery type:\n{subquery_type}")
        if op_tag_text:
            parts.append(f"Expected SQL operation tags:\n{op_tag_text}")
        parts.append(
            """
Write the SQL query now.
Constraints:
1. Return exactly one JSON object.
2. The sql value must be a single SELECT or WITH query.
3. Do not include explanations outside JSON.
4. Prefer correctness over brevity.
5. If the schema context is insufficient, use the most plausible query from the given schema without inventing columns.
""".strip()
        )
        return "\n\n".join(parts)
