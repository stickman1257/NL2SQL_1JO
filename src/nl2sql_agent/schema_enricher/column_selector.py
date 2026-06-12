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
    min_score: float = 1.5              # 최소 스코어 (ref_count 1짜리 제거용)
    weak_description_threshold: int = 30  # 설명 글자 수 기준
    weak_description_bonus: float = 0.5   # 설명 빈약 시 스코어 보정치
    dedup_logs: bool = True             # 동일 (질문, SQL) 중복 집계 방지


class ColumnSelector:
    """Hard 쿼리 SQL을 파싱해 컬럼 참조 빈도를 집계하고 보강 대상을 선별한다."""

    def __init__(self, config: SelectorConfig | None = None):
        self.config = config or SelectorConfig()

    # ------------------------------------------------------------------
    # SQL 파싱 — alias + 따옴표 지원
    # ------------------------------------------------------------------

    def _build_alias_map(self, sql: str) -> dict[str, str]:
        """FROM / JOIN 절에서 table alias 매핑을 추출한다.
        
        예:
          FROM orders o          → {'o': 'orders'}
          JOIN customers AS c    → {'c': 'customers'}
          FROM orders            → {}  (alias 없으면 생략)
        """
        alias_map = {}
        # FROM/JOIN 뒤의 table alias 또는 table AS alias 패턴
        pattern = re.compile(
            r'\b(?:FROM|JOIN)\s+([a-zA-Z_]\w*)(?:\s+(?:AS\s+)?([a-zA-Z_]\w*))?',
            re.IGNORECASE,
        )
        for match in pattern.finditer(sql):
            table = match.group(1)
            alias = match.group(2)
            if alias:
                alias_map[alias.lower()] = table
        return alias_map

    def _extract_column_refs(self, sql: str) -> list[tuple[str, str]]:
        """SQL에서 table.column 패턴을 추출한다.
        
        지원 패턴:
          - 일반 식별자:   table.column
          - 따옴표:       "table"."column"  `table`.`column`
          - 별칭 해소:     o.status → orders.status (alias map 기반)
        """
        alias_map = self._build_alias_map(sql)
        refs: list[tuple[str, str]] = []

        # 1) 따옴표 패턴: "table"."column" 또는 `table`.`column`
        for match in re.finditer(r'["`]([a-zA-Z_]\w*)["`]\.["`]([a-zA-Z_]\w*)["`]', sql):
            refs.append((match.group(1), match.group(2)))

        # 2) 일반 식별자 패턴: table.column 또는 alias.column
        for match in re.finditer(r'([a-zA-Z_]\w*)\.([a-zA-Z_]\w*)', sql):
            table_or_alias, col = match.group(1), match.group(2)
            # 따옴표 패턴과 중복 방지: 이미 refs에 있으면 skip
            if any(t == table_or_alias and c == col for t, c in refs):
                continue
            table = alias_map.get(table_or_alias.lower(), table_or_alias)
            refs.append((table, col))

        return refs

    # ------------------------------------------------------------------
    # 빈도 집계 (중복 제거 포함)
    # ------------------------------------------------------------------

    def count_references(self, logs: list[QueryLog]) -> Counter:
        counter: Counter = Counter()
        seen: set[tuple[str, str]] = set()

        for log in logs:
            # 중복 방지: 동일 (NL 질문, SQL) 쌍은 1번만 카운트
            if self.config.dedup_logs:
                key = (log.nl_question.strip().lower(), log.generated_sql.strip())
                if key in seen:
                    continue
                seen.add(key)

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
            스코어 상위 N개 ColumnScore 리스트 (min_score 미만 제외)
        """
        counter = self.count_references(logs)
        kb = existing_kb or {}
        cfg = self.config

        scores = []
        for (table, col), count in counter.items():
            if count <= 0:
                continue
            desc = kb.get((table, col), "")
            weak = len(desc) < cfg.weak_description_threshold
            score = count * (1.0 + (cfg.weak_description_bonus if weak else 0.0))
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

        # min_score 미만 제외
        filtered = [s for s in scores if s.score >= cfg.min_score]

        return filtered[: cfg.top_n]

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
        seen_q: set[str] = set()
        result = []
        for log in logs:
            if pattern.search(log.generated_sql):
                q = log.nl_question.strip()
                if q not in seen_q:
                    seen_q.add(q)
                    result.append(q)
        return result
