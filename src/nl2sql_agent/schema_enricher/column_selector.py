"""Step 2-3: 참조 컬럼 빈도 집계 및 보강 대상 선별."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .log_filter import QueryLog


@dataclass
class ColumnScore:
    table: str
    column: str
    ref_count: int
    has_weak_description: bool = False  # 기존 KB 설명이 빈약하면 True
    score: float = 0.0                  # ref_count × (1 + weak_penalty)


@dataclass
class SelectorConfig:
    top_n: int = 10
    weak_description_threshold: int = 30  # 설명 글자 수 기준
    weak_description_bonus: float = 0.5   # 설명 빈약 시 스코어 보정치


class ColumnSelector:
    """Hard 쿼리 SQL을 파싱해 컬럼 참조 빈도를 집계하고 보강 대상을 선별한다."""

    def __init__(self, config: SelectorConfig | None = None):
        self.config = config or SelectorConfig()

    # ------------------------------------------------------------------
    # SQL 파싱
    # ------------------------------------------------------------------

    def _extract_column_refs(self, sql: str) -> list[tuple[str, str]]:
        """SQL에서 table.column 패턴을 추출한다."""
        pattern = r'\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\b'
        return re.findall(pattern, sql)

    # ------------------------------------------------------------------
    # 빈도 집계
    # ------------------------------------------------------------------

    def count_references(self, logs: list[QueryLog]) -> Counter:
        counter: Counter = Counter()
        for log in logs:
            for table, col in self._extract_column_refs(log.generated_sql):
                counter[(table, col)] += 1
        return counter

    # ------------------------------------------------------------------
    # 보강 대상 선별
    # ------------------------------------------------------------------

    def select_targets(
        self,
        logs: list[QueryLog],
        existing_kb: dict[tuple[str, str], str] | None = None,
    ) -> list[ColumnScore]:
        """
        Args:
            logs: Hard 쿼리 로그
            existing_kb: {(table, col): description} 형태의 현재 KB
        Returns:
            스코어 상위 N개 ColumnScore 리스트
        """
        counter = self.count_references(logs)
        kb = existing_kb or {}
        cfg = self.config

        scores = []
        for (table, col), count in counter.items():
            desc = kb.get((table, col), "")
            weak = len(desc) < cfg.weak_description_threshold
            score = count * (1.0 + cfg.weak_description_bonus if weak else 1.0)
            scores.append(
                ColumnScore(
                    table=table,
                    column=col,
                    ref_count=count,
                    has_weak_description=weak,
                    score=score,
                )
            )

        scores.sort(key=lambda x: x.score, reverse=True)
        return scores[: cfg.top_n]

    # ------------------------------------------------------------------
    # 컨텍스트 수집 (Step 3 - 패시브)
    # ------------------------------------------------------------------

    def collect_context(
        self, target: ColumnScore, logs: list[QueryLog]
    ) -> list[str]:
        """타겟 컬럼을 참조하는 Hard NL 질문들을 묶음으로 반환한다."""
        pattern = re.compile(
            rf'\b{re.escape(target.table)}\.{re.escape(target.column)}\b',
            re.IGNORECASE,
        )
        return [
            log.nl_question
            for log in logs
            if pattern.search(log.generated_sql)
        ]
