from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Union

from .config import AgentConfig, SQLWriterConfig
from .db_search_tool import DBSearchTool, ExecutionResult
from .sql_writing_tool import SQLCandidate, SQLWritingTool


@dataclass
class SubquerySpec:
    text: str
    type_name: str = "full"
    op_tags: List[str] = field(default_factory=list)
    index: int = 0

    @staticmethod
    def from_value(value: Union[str, Dict[str, Any]], index: int) -> "SubquerySpec":
        if isinstance(value, str):
            return SubquerySpec(text=value, index=index)
        return SubquerySpec(
            text=str(value.get("text") or value.get("subquery") or value.get("question") or ""),
            type_name=str(value.get("type_name") or value.get("type") or value.get("subquery_type") or "full"),
            op_tags=[str(tag) for tag in value.get("op_tags") or value.get("tags") or []],
            index=int(value.get("index") or index),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {"text": self.text, "type_name": self.type_name, "op_tags": self.op_tags, "index": self.index}


@dataclass
class TraceEvent:
    tool: str
    action: str
    input: Dict[str, Any]
    output: Any

    def to_dict(self) -> Dict[str, Any]:
        if hasattr(self.output, "to_dict"):
            output = self.output.to_dict()
        else:
            output = self.output
        return {"tool": self.tool, "action": self.action, "input": self.input, "output": output}


@dataclass
class SubqueryRunResult:
    subquery: SubquerySpec
    schema_context: str
    candidates: List[SQLCandidate]
    execution: Optional[ExecutionResult]
    success: bool
    error: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "subquery": self.subquery.to_dict(),
            "schema_context": self.schema_context,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "execution": self.execution.to_dict() if self.execution else None,
            "success": self.success,
            "error": self.error,
        }


@dataclass
class AgentResult:
    question: str
    db_id: str
    evidence: str
    final_sql: Optional[str]
    subquery_results: List[SubqueryRunResult]
    trace: List[TraceEvent]
    success: bool
    error: Optional[str]

    def to_dict(self, include_trace: bool = True) -> Dict[str, Any]:
        return {
            "question": self.question,
            "db_id": self.db_id,
            "evidence": self.evidence,
            "final_sql": self.final_sql,
            "subquery_results": [result.to_dict() for result in self.subquery_results],
            "trace": [event.to_dict() for event in self.trace] if include_trace else [],
            "success": self.success,
            "error": self.error,
        }


class NL2SQLAgent:
    def __init__(self, db_search_tool: DBSearchTool, sql_writing_tool: SQLWritingTool, agent_config: AgentConfig, sql_writer_config: SQLWriterConfig):
        self.db_search_tool = db_search_tool
        self.sql_writing_tool = sql_writing_tool
        self.agent_config = agent_config
        self.sql_writer_config = sql_writer_config

    def run(
        self,
        question: str,
        db_id: str,
        evidence: Optional[str] = None,
        subqueries: Optional[Sequence[Union[str, Dict[str, Any], SubquerySpec]]] = None,
    ) -> AgentResult:
        evidence_value = evidence or ""
        trace: List[TraceEvent] = []
        specs = self._normalize_subqueries(question, subqueries)
        subquery_results: List[SubqueryRunResult] = []
        for spec in specs[: self.agent_config.max_subqueries]:
            result = self._run_subquery(question, db_id, evidence_value, spec, trace)
            subquery_results.append(result)
            if self.agent_config.stop_after_first_success and result.success:
                break
        final_sql = subquery_results[0].candidates[-1].sql if len(subquery_results) == 1 and subquery_results[0].candidates else None
        success = all(result.success for result in subquery_results) if subquery_results else False
        error = None if success else "; ".join(result.error or "unknown error" for result in subquery_results if not result.success)
        return AgentResult(question, db_id, evidence_value, final_sql, subquery_results, trace, success, error)

    def _run_subquery(self, question: str, db_id: str, evidence: str, spec: SubquerySpec, trace: List[TraceEvent]) -> SubqueryRunResult:
        schema_context = self.db_search_tool.build_schema_context(
            db_id=db_id,
            question=question,
            evidence=evidence,
            subquery=spec.text,
            op_tags=spec.op_tags,
            top_k=self.sql_writer_config.schema_top_k,
        )
        trace.append(
            TraceEvent(
                self.db_search_tool.name,
                "build_schema_context",
                {
                    "db_id": db_id,
                    "question": question,
                    "evidence": evidence,
                    "subquery": spec.to_dict(),
                    "kb_hits": self.db_search_tool.last_kb_hits,
                },
                schema_context,
            )
        )
        candidates: List[SQLCandidate] = []
        candidate = self.sql_writing_tool.write_sql(question, schema_context, evidence, spec.text, spec.type_name, spec.op_tags)
        candidates.append(candidate)
        trace.append(
            TraceEvent(
                self.sql_writing_tool.name,
                "write_sql",
                {"question": question, "db_id": db_id, "subquery": spec.to_dict()},
                candidate,
            )
        )
        execution: Optional[ExecutionResult] = None
        error = candidate.validation_error
        for attempt in range(self.sql_writer_config.max_repair_rounds + 1):
            current = candidates[-1]
            if current.validation_error:
                error = current.validation_error
            elif self.agent_config.execute_sql:
                execution = self.db_search_tool.execute_sql(db_id, current.sql)
                trace.append(
                    TraceEvent(
                        self.db_search_tool.name,
                        "execute_sql",
                        {"db_id": db_id, "sql": current.sql},
                        execution,
                    )
                )
                if execution.success:
                    return SubqueryRunResult(spec, schema_context, candidates, execution, True, None)
                error = execution.error or "execution failed"
            else:
                return SubqueryRunResult(spec, schema_context, candidates, None, True, None)
            if attempt >= self.sql_writer_config.max_repair_rounds:
                break
            repaired = self.sql_writing_tool.repair_sql(question, schema_context, current.sql, error, evidence, spec.text, spec.type_name, spec.op_tags)
            candidates.append(repaired)
            trace.append(
                TraceEvent(
                    self.sql_writing_tool.name,
                    "repair_sql",
                    {"question": question, "db_id": db_id, "subquery": spec.to_dict(), "previous_sql": current.sql, "error": error},
                    repaired,
                )
            )
        return SubqueryRunResult(spec, schema_context, candidates, execution, False, error)

    def _normalize_subqueries(self, question: str, subqueries: Optional[Sequence[Union[str, Dict[str, Any], SubquerySpec]]]) -> List[SubquerySpec]:
        if not subqueries:
            return [SubquerySpec(text=question, index=0)]
        specs = []
        for idx, item in enumerate(subqueries):
            if isinstance(item, SubquerySpec):
                specs.append(item)
            else:
                specs.append(SubquerySpec.from_value(item, idx))
        return [spec for spec in specs if spec.text.strip()]
