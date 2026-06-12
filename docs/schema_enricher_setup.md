# Schema Enricher — 팀원 셋업 가이드

> Qwen 2.5 3B 로컬 LLM으로 컬럼 설명을 자동 생성하는 파이프라인
> **Linux/Windows NVIDIA GPU** (`cuda`) 또는 **Apple Silicon Mac** (`mlx`) 지원

---

## 1. 사전 조건

| 환경 | backend | 요구 사항 |
|------|---------|-----------|
| Linux/Windows GPU 서버 | `cuda` (기본) | NVIDIA GPU + CUDA 드라이버 |
| Apple Silicon Mac | `mlx` | M1~M5 |

공통: Python 3.9+, `uv` (없으면 `curl -LsSf https://astral.sh/uv/install.sh | sh`)

## 2. 가상환경 + 패키지

### NVIDIA GPU 서버 (권장)

```bash
cd NL2SQL_1JO
uv venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
uv pip install torch transformers accelerate bitsandbytes pyyaml
```

기본 설정(`enricher_config.yaml`)은 `backend: auto` — Mac이면 MLX, GPU 서버면 CUDA.
GPU 서버 고정: `--config configs/dataset/enricher_config.cuda.yaml`
Mac 고정: `--config configs/dataset/enricher_config.mlx.yaml`

### Apple Silicon Mac (MLX)

```bash
uv pip install mlx mlx-lm transformers pyyaml
```

설정에서 `model.backend: mlx`, `model.path: mlx-community/Qwen2.5-3B-Instruct-4bit` 로 변경.

## 3. 모델 다운로드 (1회)

**CUDA:**
```bash
python3 -c "from transformers import AutoTokenizer; AutoTokenizer.from_pretrained('Qwen/Qwen2.5-3B-Instruct')"
```

**MLX:**
```bash
python3 -c "from mlx_lm import load; load('mlx-community/Qwen2.5-3B-Instruct-4bit')"
```

HuggingFace 캐시(`~/.cache/huggingface/hub/`)에 저장되므로 한 번만 받으면 됨.

## 4. 실행

```bash
source .venv/bin/activate
cd NL2SQL_1JO
python3 scripts/run_enricher.py
```

## 5. 설정 변경

```yaml
# configs/dataset/enricher_config.yaml

# CUDA 서버
model:
  backend: "cuda"
  path: "Qwen/Qwen2.5-3B-Instruct"
  load_in_4bit: true

# MLX Mac
model:
  backend: "mlx"
  path: "mlx-community/Qwen2.5-3B-Instruct-4bit"

# 탐색 턴 수
explorer:
  max_turns: 5

# 보강 컬럼 수
selector:
  top_n: 10
  min_score: 1.5          # ref_count=1 제외
```

## 6. 출력

- `data/schema/ecommerce_kb.json` — 버저닝된 컬럼 설명 KB
- 매일 배치 실행 시 KB 점진적 보강
- NL2SQL Agent가 `DBSearchTool`을 통해 KB를 읽어 SQL 생성 컨텍스트에 주입 (구현 완료)

### Agent에서 KB 사용 확인

Enricher 실행 후, Agent가 KB를 읽는지 확인:

```bash
# 샘플 DB 생성 (최초 1회)
python3 data/samples/setup_sample_db.py

# Enricher로 KB 보강
python3 scripts/run_enricher.py

# Agent 실행 시 schema_context에 enriched_note 포함 여부 확인
PYTHONPATH=src python3 -c "
from pathlib import Path
from nl2sql_agent.generate_sql.config import DBSearchConfig
from nl2sql_agent.generate_sql.db_search_tool import DBSearchTool
from nl2sql_agent.schema.kb_store import SchemaKBConfig

root = Path('.').resolve()
tool = DBSearchTool(
    DBSearchConfig(
        database_root='data/samples',
        schema_kb=SchemaKBConfig(path='data/schema/ecommerce_kb.json'),
    ),
    kb_base_dir=root,
)
ctx = tool.build_schema_context('ecommerce', '환불된 주문이 몇 건인지 알려줘', top_k=4)
print('kb_hits:', tool.last_kb_hits)
print('enriched_note 포함:', 'enriched_note' in ctx)
"
```

상세 연동 설명: [schema_kb_integration.md](./schema_kb_integration.md)

## 7. 문제 해결

| 증상 | 확인 |
|------|------|
| `ModuleNotFoundError: bitsandbytes` | `uv pip install bitsandbytes accelerate` |
| CUDA OOM | `load_in_4bit: true` 확인, 더 작은 모델 사용 |
| `ModuleNotFoundError: mlx` | Mac이 아니면 `backend: cuda` 사용 |
| MLX `load() OSError` | `mlx-community/` 모델명인지 확인 |
| 생성 속도 느림 | `temperature` 낮추기 (0.3 → 0.1) |
