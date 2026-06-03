"""
Schema KB Enricher
------------------
Hard 쿼리 로그를 분석해 자주 참조되는 컬럼을 선별하고,
LLM ReAct Agent로 DB를 탐색하여 Schema KB의 컬럼 설명을 보강한다.

Pipeline:
    log_filter → column_selector → db_explorer → kb_updater
"""

from .pipeline import SchemaEnricherPipeline

__all__ = ["SchemaEnricherPipeline"]
