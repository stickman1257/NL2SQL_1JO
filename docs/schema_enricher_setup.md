# Schema Enricher — 팀원 셋업 가이드

> Qwen 2.5 3B (MLX) 로컬 LLM으로 컬럼 설명을 자동 생성하는 파이프라인
> 팀원은 **모델 1회 다운로드 + 설정 파일 확인**만 하면 바로 사용 가능

---

## 1. 사전 조건

- Apple Silicon Mac (M1~M5) — MLX GPU 가속 사용
- Python 3.9+
- `uv` (없으면 `curl -LsSf https://astral.sh/uv/install.sh | sh`)

## 2. 가상환경 + 패키지

```bash
cd NL2SQL_1JO
uv venv .venv
source .venv/bin/activate
uv pip install mlx mlx-lm transformers pyyaml
```

## 3. 모델 다운로드 (1회, ~1.8GB)

```bash
source .venv/bin/activate
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

# 모델 변경
model:
  path: "mlx-community/Qwen2.5-7B-Instruct-4bit"   # 7B (4GB, 더 정확)
  path: "mlx-community/Qwen2.5-1.5B-Instruct-4bit"  # 1.5B (1GB, 더 빠름)
  path: "/Users/name/Downloads/local-model"          # 로컬 경로

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
| `ModuleNotFoundError: mlx` | `.venv` 활성화 + `uv pip install mlx mlx-lm` |
| `load() OSError` | 모델명 오타. HuggingFace에 있는 MLX 모델인지 확인 |
| `generate() 에러` | `pip install --upgrade mlx mlx-lm` |
| 생성 속도 느림 | `temperature` 낮추기 (0.3 → 0.1) |
| 메모리 부족 | 1.5B 모델로 변경 |
