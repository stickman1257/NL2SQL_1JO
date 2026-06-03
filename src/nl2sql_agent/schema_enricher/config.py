"""Schema Enricher 설정 로더.

enricher_config.yaml 파일을 읽어 Python dataclass로 반환한다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore


@dataclass
class ModelConfig:
    path: str = "mlx-community/Qwen2.5-3B-Instruct-4bit"


@dataclass
class ExplorerConfig_:
    """db_explorer.py의 ExplorerConfig와 이름 충돌 방지용."""
    max_turns: int = 5
    max_tokens: int = 256
    temperature: float = 0.3
    top_p: float = 0.9


@dataclass
class SelectorConfig_:
    """column_selector.py의 SelectorConfig와 이름 충돌 방지용."""
    top_n: int = 10
    min_score: float = 1.5
    dedup_logs: bool = True
    weak_description_threshold: int = 30
    weak_description_bonus: float = 0.5


@dataclass
class PathConfig:
    kb: str = "data/schema/ecommerce_kb.json"
    db: str = "data/samples/ecommerce.sqlite"
    logs: str = "data/samples/nl2sql_logs.jsonl"


@dataclass
class EnricherConfig:
    model: ModelConfig = field(default_factory=ModelConfig)
    explorer: ExplorerConfig_ = field(default_factory=ExplorerConfig_)
    selector: SelectorConfig_ = field(default_factory=SelectorConfig_)
    paths: PathConfig = field(default_factory=PathConfig)


# ------------------------------------------------------------------
# 로더
# ------------------------------------------------------------------

_DEFAULT_CONFIG_PATHS = [
    "configs/dataset/enricher_config.yaml",
    "../configs/dataset/enricher_config.yaml",
]


def load_config(custom_path: Optional[str] = None) -> EnricherConfig:
    """YAML 설정 파일을 로드한다.

    Args:
        custom_path: 설정 파일 경로 (없으면 기본 경로 탐색)

    Returns:
        EnricherConfig dataclass
    """
    # 탐색할 경로 목록
    search_paths = []
    if custom_path:
        search_paths.append(custom_path)
    search_paths.extend(_DEFAULT_CONFIG_PATHS)

    # 프로젝트 루트 추정 (src/nl2sql_agent/schema_enricher/config.py 기준)
    script_dir = Path(__file__).resolve().parent  # schema_enricher/
    project_root = script_dir.parent.parent.parent.parent  # NL2SQL_1JO/
    search_paths.append(str(project_root / "configs/dataset/enricher_config.yaml"))

    # 작업 디렉토리 기준
    cwd = Path.cwd()
    search_paths.append(str(cwd / "configs/dataset/enricher_config.yaml"))

    # 찾을 때까지 탐색
    for sp in search_paths:
        p = Path(sp)
        if p.exists():
            return _parse_yaml(p)

    # 파일 없으면 기본값
    print("[Config] 설정 파일을 찾을 수 없습니다. 기본값을 사용합니다.")
    return EnricherConfig()


def _parse_yaml(path: Path) -> EnricherConfig:
    """YAML 파일을 읽어 EnricherConfig로 변환한다."""
    if yaml is None:
        raise ImportError("PyYAML이 필요합니다: pip install pyyaml")

    with open(path) as f:
        raw = yaml.safe_load(f)

    cfg = EnricherConfig()

    if raw is None:
        return cfg

    # model
    if "model" in raw:
        cfg.model.path = raw["model"].get("path", cfg.model.path)

    # explorer
    if "explorer" in raw:
        ex = raw["explorer"]
        cfg.explorer.max_turns = ex.get("max_turns", cfg.explorer.max_turns)
        cfg.explorer.max_tokens = ex.get("max_tokens", cfg.explorer.max_tokens)
        cfg.explorer.temperature = ex.get("temperature", cfg.explorer.temperature)
        cfg.explorer.top_p = ex.get("top_p", cfg.explorer.top_p)

    # selector
    if "selector" in raw:
        sel = raw["selector"]
        cfg.selector.top_n = sel.get("top_n", cfg.selector.top_n)
        cfg.selector.min_score = sel.get("min_score", cfg.selector.min_score)
        cfg.selector.dedup_logs = sel.get("dedup_logs", cfg.selector.dedup_logs)
        cfg.selector.weak_description_threshold = sel.get(
            "weak_description_threshold", cfg.selector.weak_description_threshold
        )
        cfg.selector.weak_description_bonus = sel.get(
            "weak_description_bonus", cfg.selector.weak_description_bonus
        )

    # paths
    if "paths" in raw:
        p = raw["paths"]
        cfg.paths.kb = p.get("kb", cfg.paths.kb)
        cfg.paths.db = p.get("db", cfg.paths.db)
        cfg.paths.logs = p.get("logs", cfg.paths.logs)

    return cfg
