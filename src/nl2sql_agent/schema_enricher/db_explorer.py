"""Step 4: ReAct 루프 기반 LLM Agent DB 탐색."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .column_selector import ColumnScore


@dataclass
class ExplorationResult:
    table: str
    column: str
    nl_questions: list[str]
    react_trace: list[dict[str, str]] = field(default_factory=list)
    enriched_description: str = ""
    done: bool = False
    fallback: bool = False  # max_turns 초과로 fallback 사용 시 True


@dataclass
class ExplorerConfig:
    max_turns: int = 10
    sql_executor: Callable[[str], Any] | None = None  # 읽기 전용 SQL 실행 함수
    llm_caller: Callable[[list[dict]], str] | None = None


SYSTEM_PROMPT = """\
당신은 DB 스키마 전문가입니다. 주어진 컬럼에 대해 ReAct 루프로 DB를 탐색하고,
사용자의 자연어 질문 맥락을 바탕으로 컬럼의 정확한 설명을 생성합니다.

규칙:
- SELECT 쿼리만 실행할 수 있습니다 (읽기 전용).
- 각 턴은 REASON / ACT / OBSERVE 형식으로 작성합니다.
- 충분히 파악했다면 즉시 OUTPUT: <최종 설명> 으로 종료합니다.
- OUTPUT 없이 5턴 이상 지속되면 마지막 응답이 설명으로 사용됩니다.

출력 형식:
  ACT: SELECT ... ;
  OUTPUT: 이 컬럼은 ... 입니다.

OUTPUT이 없는 응답은 다음 턴에서 다시 시도합니다.
"""


class DBExplorerAgent:
    """ReAct 루프로 DB를 탐색하여 컬럼 설명을 생성하는 Agent."""

    def __init__(self, config: ExplorerConfig | None = None):
        self.config = config or ExplorerConfig()

    def _build_initial_messages(
        self, target: ColumnScore, nl_questions: list[str]
    ) -> list[dict[str, str]]:
        context = "\n".join(f"- {q}" for q in nl_questions)
        user_content = (
            f"대상 컬럼: {target.table}.{target.column}\n\n"
            f"이 컬럼이 자주 등장한 사용자 질문들:\n{context}\n\n"
            "위 질문들을 참고해 DB를 탐색하고 컬럼 설명을 작성하세요."
        )
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

    def _extract_sql(self, response: str) -> str | None:
        """ACT: ... 줄에서 SQL을 추출한다."""
        for line in response.splitlines():
            if line.strip().upper().startswith("ACT:"):
                sql = line.split("ACT:", 1)[1].strip()
                if sql.upper().startswith("SELECT"):
                    return sql
        return None

    def _is_done(self, response: str) -> tuple[bool, str]:
        """OUTPUT: 으로 종료 신호를 감지한다."""
        for line in response.splitlines():
            if line.strip().upper().startswith("OUTPUT:"):
                desc = line.split("OUTPUT:", 1)[1].strip()
                return True, desc
        return False, ""

    def explore(
        self, target: ColumnScore, nl_questions: list[str]
    ) -> ExplorationResult:
        if not self.config.llm_caller or not self.config.sql_executor:
            raise ValueError("llm_caller와 sql_executor를 설정해야 합니다.")

        result = ExplorationResult(
            table=target.table,
            column=target.column,
            nl_questions=nl_questions,
        )
        messages = self._build_initial_messages(target, nl_questions)

        for turn in range(self.config.max_turns):
            response = self.config.llm_caller(messages)
            result.react_trace.append({"turn": str(turn), "response": response})

            done, description = self._is_done(response)
            if done:
                result.enriched_description = description
                result.done = True
                break

            sql = self._extract_sql(response)
            if sql:
                try:
                    observe = str(self.config.sql_executor(sql))
                except Exception as e:
                    observe = f"[ERROR] {e}"
                messages.append({"role": "assistant", "content": response})
                messages.append({"role": "user", "content": f"OBSERVE: {observe}"})
            else:
                messages.append({"role": "assistant", "content": response})
                messages.append({
                    "role": "user",
                    "content": "충분히 파악됐으면 OUTPUT: <설명> 으로 종료해주세요.",
                })
        else:
            # ── Fallback: max_turns 초과 시 마지막 응답을 설명으로 사용 ──
            last_response = result.react_trace[-1]["response"] if result.react_trace else ""
            # OUTPUT 형식이 아니어도 내용을 그대로 설명으로 채택
            result.enriched_description = last_response.strip() or (
                f"'{target.table}.{target.column}' 컬럼 (LLM 탐색 중 타임아웃)"
            )
            result.done = True
            result.fallback = True

        return result
