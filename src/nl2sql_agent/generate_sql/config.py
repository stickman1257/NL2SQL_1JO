from dataclasses import dataclass
from typing import Optional

from nl2sql_agent.schema.kb_store import SchemaKBConfig


@dataclass
class ModelConfig:
    model_name: str = "Qwen/Qwen2.5-7B-Instruct"
    backend: str = "transformers"
    device_map: str = "auto"
    dtype: str = "auto"
    load_in_4bit: bool = True
    trust_remote_code: bool = True
    max_new_tokens: int = 1024
    temperature: float = 0.0
    top_p: float = 1.0
    repetition_penalty: float = 1.05
    enable_thinking: Optional[bool] = False
    openai_base_url: Optional[str] = None
    openai_api_key: str = "EMPTY"


@dataclass
class DBSearchConfig:
    database_root: str
    max_tables: int = 12
    max_columns_per_table: int = 80
    sample_rows: int = 3
    include_samples: bool = True
    include_descriptions: bool = True
    count_rows: bool = False
    execution_timeout_s: float = 15.0
    max_result_rows: int = 50
    schema_kb: Optional[SchemaKBConfig] = None


@dataclass
class SQLWriterConfig:
    dialect: str = "SQLite"
    max_repair_rounds: int = 2
    schema_top_k: int = 12
    include_rationale: bool = True


@dataclass
class AgentConfig:
    max_subqueries: int = 8
    stop_after_first_success: bool = False
    execute_sql: bool = True
