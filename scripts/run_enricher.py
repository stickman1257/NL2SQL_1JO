"""
Schema Enricher Pipeline 실행 스크립트.

설정 파일(configs/dataset/enricher_config.yaml)에서 모델 경로와 옵션을 읽어
LLM 기반 DBExplorerAgent로 컬럼 설명을 생성하고 KB에 저장한다.

사용법:
    python3 scripts/run_enricher.py
    python3 scripts/run_enricher.py --config configs/dataset/enricher_config.yaml
"""

import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from nl2sql_agent.schema_enricher.config import load_config
from nl2sql_agent.schema_enricher.log_filter import HardQueryFilter, FilterConfig, QueryLog
from nl2sql_agent.schema_enricher.column_selector import ColumnSelector, SelectorConfig
from nl2sql_agent.schema_enricher.kb_updater import SchemaKBUpdater
from nl2sql_agent.schema_enricher.db_explorer import DBExplorerAgent, ExplorerConfig


# ------------------------------------------------------------------
# SQL Executor
# ------------------------------------------------------------------

def make_sql_executor(db_path: str):
    """SQLite 읽기 전용 SQL 실행 함수."""
    def sql_executor(sql: str) -> str:
        conn = sqlite3.connect(db_path)
        conn.text_factory = str
        try:
            cur = conn.cursor()
            cur.execute(sql)
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            result = []
            for row in rows[:30]:
                result.append(dict(zip(cols, row)))
            return json.dumps(result, ensure_ascii=False)
        except Exception as e:
            return f"[ERROR] {e}"
        finally:
            conn.close()
    return sql_executor


# ------------------------------------------------------------------
# 메인
# ------------------------------------------------------------------

def main():
    # 설정 로드
    config_path = None
    for i, arg in enumerate(sys.argv):
        if arg == "--config" and i + 1 < len(sys.argv):
            config_path = sys.argv[i + 1]

    cfg = load_config(config_path)

    # 절대 경로로 변환
    root = PROJECT_ROOT

    db_path = root / cfg.paths.db
    log_path = root / cfg.paths.logs
    kb_path = str(root / cfg.paths.kb)

    print("=" * 60)
    print("Schema Enricher Pipeline — LLM 모드")
    print(f"모델 : {cfg.model.path}")
    print(f"DB   : {db_path}")
    print(f"LOG  : {log_path}")
    print(f"KB   : {kb_path}")
    print("=" * 60)

    # 1. 로그 로드
    print("\n[1/5] 로그 로드...")
    with open(log_path) as f:
        raw_logs = [json.loads(line) for line in f]
    logs = [QueryLog(**r) for r in raw_logs]
    print(f"       총 {len(logs)}개 로그")

    # 2. Hard 필터링
    print("\n[2/5] Hard 쿼리 필터링...")
    filter_ = HardQueryFilter(FilterConfig(
        include_difficulty=["hard"],
        include_execution_errors=True,
    ))
    hard_logs = filter_.filter(logs)
    print(f"       Hard + 실행에러: {len(hard_logs)}개")
    for hl in hard_logs:
        err = f" [ERROR: {hl.execution_error}]" if hl.execution_error else ""
        print(f"         [{hl.difficulty}] {hl.nl_question}{err}")

    # 3. 컬럼 선별
    print("\n[3/5] 보강 대상 컬럼 선별...")
    sc = cfg.selector
    selector = ColumnSelector(SelectorConfig(
        top_n=sc.top_n,
        min_score=sc.min_score,
        dedup_logs=sc.dedup_logs,
        weak_description_threshold=sc.weak_description_threshold,
        weak_description_bonus=sc.weak_description_bonus,
    ))
    targets = selector.select_targets(hard_logs, existing_kb={})
    print(f"       선별된 컬럼: {len(targets)}개 (min_score={sc.min_score}, dedup={sc.dedup_logs})")
    for t in targets:
        print(f"         {t.table}.{t.column} (ref={t.ref_count}, score={t.score:.1f})")

    # 4. KB 준비
    print(f"\n[4/5] KB 로드...")
    kb = SchemaKBUpdater(kb_path)
    print(f"       기존 KB 엔트리: {len(kb._kb)}개")

    # 5. LLM 탐색 → KB 업데이트
    print(f"\n[5/5] LLM DB 탐색 + KB 업데이트...")

    from nl2sql_agent.schema_enricher.llm_caller import create_mlx_caller

    sql_executor = make_sql_executor(str(db_path))
    ec = cfg.explorer
    llm_caller = create_mlx_caller(
        model_name=cfg.model.path,
        max_tokens=ec.max_tokens,
        temperature=ec.temperature,
        top_p=ec.top_p,
    )

    explorer = DBExplorerAgent(ExplorerConfig(
        max_turns=ec.max_turns,
        sql_executor=sql_executor,
        llm_caller=llm_caller,
    ))

    for target in targets:
        nl_questions = selector.collect_context(target, hard_logs)
        print(f"\n  ── {target.table}.{target.column} (ref={target.ref_count}) ──")
        print(f"     NL 질문: {len(nl_questions)}개")
        print(f"     [LLM 탐색 중...]")

        result = explorer.explore(target, nl_questions)
        kb.update(result)

        status = "✅" if result.done else "⚠️"
        fallback_tag = " [fallback]" if result.fallback else ""
        print(f"     {status}{fallback_tag} 설명: {result.enriched_description[:150]}")

    kb.save()

    # 최종 요약
    print(f"\n{'=' * 60}")
    print(f"✅ KB 저장 완료: {kb_path}")
    print(f"   총 {len(targets)}개 컬럼 설명 보강")
    print("=" * 60)

    with open(kb_path) as f:
        kb_data = json.load(f)
    for key, entry in kb_data.items():
        print(f"\n  [{key}] v{len(entry['history'])}")
        print(f"     {entry['current_description'][:120]}")


if __name__ == "__main__":
    main()
