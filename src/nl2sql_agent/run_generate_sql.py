import argparse
import json
from pathlib import Path

from NL2SQL_1JO.src.nl2sql_agent.generate_sql.agent import NL2SQLAgent
from NL2SQL_1JO.src.nl2sql_agent.generate_sql.config import AgentConfig, DBSearchConfig, ModelConfig, SQLWriterConfig
from NL2SQL_1JO.src.nl2sql_agent.generate_sql.db_search_tool import DBSearchTool
from NL2SQL_1JO.src.nl2sql_agent.generate_sql.llm_client import LLMClientFactory
from NL2SQL_1JO.src.nl2sql_agent.generate_sql.sql_writing_tool import SQLWritingTool


def build_output(result, include_trace):
    first_result = result.subquery_results[0] if result.subquery_results else None
    final_candidate = first_result.candidates[-1] if first_result and first_result.candidates else None
    execution = first_result.execution if first_result else None
    output = {
        "sql": result.final_sql or (final_candidate.sql if final_candidate else None),
        "data": {
            "columns": execution.columns if execution else [],
            "rows": execution.rows if execution else [],
        },
    }
    error = result.error or (execution.error if execution else None)
    if error:
        output["error"] = error
    return output


def load_subqueries(path):
    if not path:
        return None
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and "subqueries" in value:
        return value["subqueries"]
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-root", required=True, default = '/home/jonghak/bird_sql/dev_databases/dev_databases')
    parser.add_argument("--db-id", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--evidence", default="")
    parser.add_argument("--subqueries", default=None)
    parser.add_argument("--model", default="Qwen/Qwen3-4B")
    parser.add_argument("--backend", default="transformers", choices=["transformers", "openai", "openai-compatible", "vllm"])
    parser.add_argument("--openai-base-url", default=None)
    parser.add_argument("--openai-api-key", default="EMPTY")
    parser.add_argument("--load-in-4bit", dest="load_in_4bit", action="store_true", default=True)
    parser.add_argument("--no-load-in-4bit", dest="load_in_4bit", action="store_false")
    parser.add_argument("--device-map", default="auto")
    parser.add_argument("--dtype", default="auto")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-new-tokens", type=int, default=512)
    parser.add_argument("--enable-thinking", action="store_true", default=False)
    parser.add_argument("--schema-top-k", type=int, default=6)
    parser.add_argument("--max-repair-rounds", type=int, default=2)
    parser.add_argument("--no-execute", action="store_true")
    parser.add_argument("--include-trace", action="store_true")
    args = parser.parse_args()
    model_config = ModelConfig(
        model_name=args.model,
        backend=args.backend,
        load_in_4bit=args.load_in_4bit,
        device_map=args.device_map,
        dtype=args.dtype,
        temperature=args.temperature,
        max_new_tokens=args.max_new_tokens,
        enable_thinking=args.enable_thinking,
        openai_base_url=args.openai_base_url,
        openai_api_key=args.openai_api_key,
    )
    db_config = DBSearchConfig(database_root=args.database_root)
    writer_config = SQLWriterConfig(schema_top_k=args.schema_top_k, max_repair_rounds=args.max_repair_rounds)
    agent_config = AgentConfig(execute_sql=not args.no_execute)
    llm = LLMClientFactory.create(model_config)
    db_tool = DBSearchTool(db_config)
    sql_tool = SQLWritingTool(llm, writer_config)
    agent = NL2SQLAgent(db_tool, sql_tool, agent_config, writer_config)
    result = agent.run(args.question, args.db_id, args.evidence, load_subqueries(args.subqueries))
    print(json.dumps(build_output(result, args.include_trace), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
