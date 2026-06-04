from __future__ import annotations

import argparse
from pathlib import Path
from time import perf_counter

from NL2SQL_1JO.src.nl2sql_agent.generate_answer.data_sql import execute_sql, load_bird_example
from NL2SQL_1JO.src.nl2sql_agent.generate_answer.logging_utils import append_jsonl, utc_now_iso
from NL2SQL_1JO.src.nl2sql_agent.generate_answer.llm_io import build_llm_messages, format_messages_for_log
from NL2SQL_1JO.src.nl2sql_agent.generate_answer.qwen_model import QwenGenerator


SCRIPT_DIR = Path(__file__).resolve().parent
BIRD_SQL_ROOT = SCRIPT_DIR.parent
DEFAULT_DATA_PATH = BIRD_SQL_ROOT / "bird_sql" / "dev.json"
DEFAULT_DB_ROOT = BIRD_SQL_ROOT / "dev_databases" / "dev_databases"
DEFAULT_LOG_PATH = SCRIPT_DIR / "logs" / "answer_agent.jsonl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Execute a BIRD SQL query, pass the original question/SQL/result to Qwen, "
            "and print the LLM input and output explicitly."
        )
    )
    parser.add_argument("--data-path", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument("--db-root", type=Path, default=DEFAULT_DB_ROOT)
    parser.add_argument("--index", type=int, default=5, help="0-based row index in dev.json")
    parser.add_argument("--model-name", default="Qwen/Qwen3-4B")
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--greedy", action="store_true", help="Use deterministic greedy decoding")
    parser.add_argument("--log-path", type=Path, default=DEFAULT_LOG_PATH)
    parser.add_argument(
        "--max-result-rows",
        type=int,
        default=None,
        help="Limit how many SQL result rows are included in the LLM input",
    )
    parser.add_argument(
        "--print-llm-input-only",
        action="store_true",
        help="Execute SQL and print the LLM messages without loading the model",
    )
    return parser.parse_args()


def print_section(title: str, body: object) -> None:
    print(f"\n===== {title} =====")
    print(body)


def main() -> None:
    args = parse_args()

    example = load_bird_example(
        data_path=args.data_path,
        db_root=args.db_root,
        index=args.index,
    )
    sql_result = execute_sql(db_path=example.db_path, sql=example.sql)
    messages = build_llm_messages(
        question=example.question,
        sql=example.sql,
        result=sql_result,
        max_rows=args.max_result_rows,
    )

    print_section("SELECTED EXAMPLE", f"index: {example.index}\nquestion_id: {example.question_id}\ndb_id: {example.db_id}\ndb_path: {example.db_path}\ndifficulty: {example.difficulty}\nevidence: {example.evidence}")
    print_section("ORIGINAL QUESTION", example.question)
    print_section("SQL TO EXECUTE", example.sql)
    print_section("SQL EXECUTION OUTPUT", f"columns: {sql_result.columns}\nrows: {sql_result.rows}")
    print_section("LLM INPUT MESSAGES", format_messages_for_log(messages))

    if args.print_llm_input_only:
        return

    generator = QwenGenerator(model_name=args.model_name)
    llm_started_at = utc_now_iso()
    llm_timer_start = perf_counter()
    rendered_prompt, answer = generator.generate(
        messages=messages,
        max_new_tokens=args.max_new_tokens,
        temperature=args.temperature,
        top_p=args.top_p,
        do_sample=not args.greedy,
    )
    llm_elapsed_seconds = perf_counter() - llm_timer_start
    llm_finished_at = utc_now_iso()

    print_section("LLM INPUT RENDERED PROMPT", rendered_prompt)
    print_section("LLM OUTPUT FINAL ANSWER", answer)

    log_record = {
        "timestamp_utc": llm_finished_at,
        "llm_started_at_utc": llm_started_at,
        "llm_finished_at_utc": llm_finished_at,
        "llm_elapsed_seconds": round(llm_elapsed_seconds, 6),
        "question": example.question,
        "answer": answer,
        "index": example.index,
        "question_id": example.question_id,
        "db_id": example.db_id,
        "sql": example.sql,
        "model_name": args.model_name,
    }
    append_jsonl(args.log_path, log_record)
    print_section("LOG WRITTEN", args.log_path)


if __name__ == "__main__":
    main()
