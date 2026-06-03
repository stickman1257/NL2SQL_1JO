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
- KB를 NL2SQL Agent가 읽어 SQL 생성 컨텍스트로 활용

## 7. 문제 해결

| 증상 | 확인 |
|------|------|
| `ModuleNotFoundError: mlx` | `.venv` 활성화 + `uv pip install mlx mlx-lm` |
| `load() OSError` | 모델명 오타. HuggingFace에 있는 MLX 모델인지 확인 |
| `generate() 에러` | `pip install --upgrade mlx mlx-lm` |
| 생성 속도 느림 | `temperature` 낮추기 (0.3 → 0.1) |
| 메모리 부족 | 1.5B 모델로 변경 |
