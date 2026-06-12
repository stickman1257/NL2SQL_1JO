# src/nl2sql_agent

## 폴더 목적
NL2SQL 파이프라인의 핵심 모듈을 담는 메인 패키지입니다.

## 하위 폴더
| 폴더 | 설명 |
|------|------|
| `agent/` | 에이전트 오케스트레이션 로직 |
| `decomposition/` | 서브쿼리 분해 모듈 |
| `evaluation/` | 결과 평가 모듈 |
| `models/` | LLM 모델 래퍼 |
| `pipeline/` | 전체 파이프라인 구성 |
| `schema/` | 스키마 정제 모듈 |
| `sql/` | SQL 파싱/실행 유틸리티 |
| `utils/` | 공통 유틸리티 |
