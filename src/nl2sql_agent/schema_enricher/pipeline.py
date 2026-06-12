"""전체 Schema Enricher 파이프라인 오케스트레이션."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .column_selector import ColumnSelector, SelectorConfig
from .db_explorer import DBExplorerAgent, ExplorerConfig
from .kb_updater import SchemaKBUpdater
from .log_filter import FilterConfig, HardQueryFilter, QueryLog


@dataclass
class PipelineConfig:
    kb_path: str                                    # Schema KB JSON 파일 경로
    sql_executor: Callable[[str], Any]              # 읽기 전용 SQL 실행 함수
    llm_caller: Callable[[list[dict]], str]         # LLM 호출 함수
    filter_config: FilterConfig | None = None
    selector_config: SelectorConfig | None = None
    explorer_max_turns: int = 10


class SchemaEnricherPipeline:
    """
    Hard 쿼리 로그 → 컬럼 선별 → DB 탐색 → KB 업데이트를 한 번에 실행한다.

    사용 예:
        pipeline = SchemaEnricherPipeline(config)
        pipeline.run(logs)            # QueryLog 리스트 직접 전달
        pipeline.run_from_file(path)  # JSONL 로그 파일 경로 전달
    """

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.filter = HardQueryFilter(config.filter_config)
        self.selector = ColumnSelector(config.selector_config)
        self.explorer = DBExplorerAgent(
            ExplorerConfig(
                max_turns=config.explorer_max_turns,
                sql_executor=config.sql_executor,
                llm_caller=config.llm_caller,
            )
        )
        self.kb = SchemaKBUpdater(config.kb_path)

    def run(self, logs: list[QueryLog]) -> None:
        # Step 1: Hard 쿼리 필터링
        hard_logs = self.filter.filter(logs)
        if not hard_logs:
            print("[SchemaEnricher] Hard 쿼리가 없습니다. 종료.")
            return

        # Step 2-3: 컬럼 선별 + 컨텍스트 수집
        targets = self.selector.select_targets(hard_logs, existing_kb=self.kb.as_dict())
        print(f"[SchemaEnricher] 보강 대상 {len(targets)}개 컬럼 선별됨.")

        # Step 4-5: DB 탐색 → KB 업데이트
        for target in targets:
            nl_questions = self.selector.collect_context(target, hard_logs)
            print(f"  탐색 중: {target.table}.{target.column} (ref={target.ref_count}, nl={len(nl_questions)}개)")
            result = self.explorer.explore(target, nl_questions)
            self.kb.update(result)
            status = "완료" if result.done else "미완료(max_turns 초과)"
            print(f"  → {status}: {result.enriched_description[:80]}")

        self.kb.save()
        print(f"[SchemaEnricher] KB 저장 완료: {self.config.kb_path}")

    def run_from_file(self, log_path: str) -> None:
        logs = self.filter.load_from_jsonl(log_path)
        self.run(logs)
