# experiments/schema_enricher

Schema KB Enricher 실험 기록 폴더입니다.

## 폴더 구조

```
schema_enricher/
├── logs/          # 실험별 실행 로그 (run_YYYYMMDD.jsonl)
└── README.md
```

## 실험 체크리스트

- [ ] Cold start: BIRD-SQL Hard 샘플로 KB 초기화
- [ ] top_n 하이퍼파라미터 튜닝 (5 / 10 / 20)
- [ ] weak_description_threshold 튜닝
- [ ] max_turns 튜닝 (5 / 10 / 15)
- [ ] 보강 전/후 Hard 쿼리 정확도 비교 (EX / VES)
