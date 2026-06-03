"""Step 1: Hard 쿼리 로그 필터링."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class QueryLog:
    nl_question: str
    generated_sql: str
    difficulty: Literal["easy", "hard"]
    execution_error: str | None = None  # SQL 실행 에러 메시지 (있으면 추가 가중치)
    db_id: str = ""
    timestamp: str = ""


@dataclass
class FilterConfig:
    include_difficulty: list[str] = field(default_factory=lambda: ["hard"])
    include_execution_errors: bool = True  # 실행 에러 난 쿼리도 포함 (easy라도)


class HardQueryFilter:
    """로그에서 Hard 쿼리(+ 실행 오류 쿼리)만 추려낸다."""

    def __init__(self, config: FilterConfig | None = None):
        self.config = config or FilterConfig()

    def filter(self, logs: list[QueryLog]) -> list[QueryLog]:
        result = []
        for log in logs:
            is_target_difficulty = log.difficulty in self.config.include_difficulty
            is_execution_error = (
                self.config.include_execution_errors and log.execution_error is not None
            )
            if is_target_difficulty or is_execution_error:
                result.append(log)
        return result

    def load_from_jsonl(self, path: str) -> list[QueryLog]:
        """JSONL 형식 로그 파일을 읽어 QueryLog 리스트로 반환."""
        import json

        logs = []
        with open(path) as f:
            for line in f:
                data = json.loads(line)
                logs.append(QueryLog(**data))
        return logs
