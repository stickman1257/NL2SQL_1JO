# 로컬 검증 환경 (MLX · MacBook M3)

`schema` 패키지(Step 3)의 엔드투엔드 동작 확인은 동일 프로젝트 폴더의 **`NL2_SQL/` 프로토타입**에서 수행했습니다.

## 검증 환경 (특수·로컬 전용)

| 항목 | 내용 |
|------|------|
| 기기 | **MacBook M3 Air, 24GB RAM** |
| OS | macOS (Apple Silicon) |
| 추론 백엔드 | **MLX 4-bit** (`mlx-community/Qwen3-4B-Instruct-2507-4bit`, ~2.3GB) |
| 데이터 | BIRD dev (`dev_20240627/dev_databases`, 11개 DB) |

## 왜 MLX인가

- `bitsandbytes` 4-bit는 **CUDA 전용**이라 M3 Mac에서는 사용할 수 없습니다.
- M3에서는 **MLX**가 Apple Silicon 네이티브 4-bit 추론에 적합합니다.
- SQL·진단·답변에 **모델 1개를 공유**해 24GB 메모리 안에서 동작했습니다.

## 팀 배포 시 참고

MLX 연동은 **위 M3 로컬 개발·검증용**이며, `NL2SQL_1JO`의 `schema` 모듈은 백엔드에 독립적입니다
(`.generate(messages, settings)` 인터페이스만 맞으면 됨). CUDA 서버 등 프로덕션 환경에서는
Hugging Face 백엔드(Qwen)를 사용하는 것을 전제로 합니다.

프로토타입 실행 예시는 `NL2_SQL/llm_agents/README.md`를 참고하세요.
