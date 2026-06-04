import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .agent import NL2SQLAgent
from .bird import load_bird_examples
from .config import AgentConfig, DBSearchConfig, ModelConfig, SQLWriterConfig
from .db_search_tool import DBSearchTool
from .llm_client import LLMClientFactory
from .sql_writing_tool import SQLWritingTool


def build_agent(args: argparse.Namespace) -> NL2SQLAgent:
    model_config = ModelConfig(
        model_name=args.model,
        backend=args.backend,
        device_map=args.device_map,
        dtype=args.dtype,
        load_in_4bit=args.load_in_4bit,
        trust_remote_code=args.trust_remote_code,
        max_new_tokens=args.max_new_tokens,
        temperature=args.temperature,
        top_p=args.top_p,
        repetition_penalty=args.repetition_penalty,
        enable_thinking=args.enable_thinking,
        openai_base_url=args.openai_base_url,
        openai_api_key=args.openai_api_key,
    )
    db_config = DBSearchConfig(
        database_root=args.database_root,
        max_tables=args.max_tables,
        max_columns_per_table=args.max_columns_per_table,
        sample_rows=args.sample_rows,
        include_samples=not args.no_samples,
        include_descriptions=not args.no_descriptions,
        count_rows=args.count_rows,
        execution_timeout_s=args.execution_timeout_s,
        max_result_rows=args.max_result_rows,
    )
    writer_config = SQLWriterConfig(
        dialect=args.dialect,
        max_repair_rounds=args.max_repair_rounds,
        schema_top_k=args.schema_top_k,
        include_rationale=True,
    )
    agent_config = AgentConfig(
        max_subqueries=args.max_subqueries,
        stop_after_first_success=False,
        execute_sql=not args.no_execute,
    )
    llm = LLMClientFactory.create(model_config)
    db_tool = DBSearchTool(db_config)
    sql_tool = SQLWritingTool(llm, writer_config)
    return NL2SQLAgent(db_tool, sql_tool, agent_config, writer_config)


def evaluate(args: argparse.Namespace) -> None:
    examples = load_bird_examples(args.dataset, args.limit)
    agent = build_agent(args)
    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from tqdm import tqdm

        iterator = tqdm(examples, desc="BIRD")
    except Exception:
        iterator = examples
    rows: List[Dict[str, Any]] = []
    with output_path.open("w", encoding="utf-8") as f:
        for example in iterator:
            result = agent.run(example.question, example.db_id, example.evidence)
            record = {
                "question_id": example.question_id,
                "db_id": example.db_id,
                "question": example.question,
                "evidence": example.evidence,
                "difficulty": example.difficulty,
                "gold_sql": example.gold_sql,
                "predicted_sql": result.final_sql,
                "success": result.success,
                "error": result.error,
                "agent_result": result.to_dict(include_trace=args.include_trace),
            }
            if args.compare_gold and example.gold_sql and result.final_sql:
                record.update(compare_with_gold(agent, example.db_id, result.final_sql, example.gold_sql))
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            rows.append(record)
    metrics = summarize(rows)
    metrics_path = output_path.with_suffix(output_path.suffix + ".metrics.json")
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


def compare_with_gold(agent: NL2SQLAgent, db_id: str, predicted_sql: str, gold_sql: str) -> Dict[str, Any]:
    pred = agent.db_search_tool.execute_sql(db_id, predicted_sql)
    gold = agent.db_search_tool.execute_sql(db_id, gold_sql)
    match = False
    if pred.success and gold.success:
        match = normalize_rows(pred.rows) == normalize_rows(gold.rows)
    return {
        "pred_execution_success": pred.success,
        "gold_execution_success": gold.success,
        "execution_match": match,
        "pred_execution_error": pred.error,
        "gold_execution_error": gold.error,
    }


def normalize_rows(rows: List[List[Any]]) -> List[List[str]]:
    return sorted([[str(value) for value in row] for row in rows])


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(rows)
    success = sum(1 for row in rows if row.get("success"))
    execution_matches = [row.get("execution_match") for row in rows if "execution_match" in row]
    return {
        "total": total,
        "agent_success": success,
        "agent_success_rate": success / total if total else 0.0,
        "execution_match_total": len(execution_matches),
        "execution_match_count": sum(1 for item in execution_matches if item),
        "execution_match_rate": sum(1 for item in execution_matches if item) / len(execution_matches) if execution_matches else None,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--database-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default="Qwen/Qwen2.5-7B-Instruct")
    parser.add_argument("--backend", default="transformers", choices=["transformers", "openai", "openai-compatible", "vllm"])
    parser.add_argument("--openai-base-url", default=None)
    parser.add_argument("--openai-api-key", default="EMPTY")
    parser.add_argument("--device-map", default="auto")
    parser.add_argument("--dtype", default="auto")
    parser.add_argument("--load-in-4bit", dest="load_in_4bit", action="store_true", default=True)
    parser.add_argument("--no-load-in-4bit", dest="load_in_4bit", action="store_false")
    parser.add_argument("--trust-remote-code", action="store_true", default=True)
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-p", type=float, default=1.0)
    parser.add_argument("--repetition-penalty", type=float, default=1.05)
    parser.add_argument("--enable-thinking", dest="enable_thinking", action="store_true", default=False)
    parser.add_argument("--disable-thinking", dest="enable_thinking", action="store_false")
    parser.add_argument("--max-tables", type=int, default=12)
    parser.add_argument("--schema-top-k", type=int, default=12)
    parser.add_argument("--max-columns-per-table", type=int, default=80)
    parser.add_argument("--sample-rows", type=int, default=3)
    parser.add_argument("--no-samples", action="store_true")
    parser.add_argument("--no-descriptions", action="store_true")
    parser.add_argument("--count-rows", action="store_true")
    parser.add_argument("--execution-timeout-s", type=float, default=15.0)
    parser.add_argument("--max-result-rows", type=int, default=50)
    parser.add_argument("--dialect", default="SQLite")
    parser.add_argument("--max-repair-rounds", type=int, default=2)
    parser.add_argument("--max-subqueries", type=int, default=8)
    parser.add_argument("--no-execute", action="store_true")
    parser.add_argument("--compare-gold", action="store_true")
    parser.add_argument("--include-trace", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    evaluate(args)


if __name__ == "__main__":
    main()
