# NL2SQL

## Project Structure

```
NL2SQL/
├── configs/
│   ├── dataset/
│   ├── model/
│   └── prompt/
│
├── data/
│   ├── processed/
│   ├── raw/
│   │   ├── bird_sql/
│   │   └── spider/
│   ├── samples/
│   └── schema/
│
├── docs/
│   └── meeting_notes/
│
├── experiments/
│   ├── ablation/
│   │   ├── without_decomposition/
│   │   ├── without_execution_feedback/
│   │   └── without_schema_refinement/
│   ├── baseline/
│   │   ├── cot_prompting/
│   │   └── few_shot/
│   └── results/
│       ├── bird_sql/
│       └── spider/
│
├── notebooks/
│
├── prompts/
│   ├── answer_generation/
│   ├── schema_refinement/
│   ├── subquery_decomposition/
│   └── system/
│
├── scripts/
│
├── src/
│   └── nl2sql_agent/
│       ├── agent/
│       ├── decomposition/
│       ├── evaluation/
│       ├── models/
│       ├── pipeline/
│       ├── schema/
│       ├── sql/
│       └── utils/
│
├── tests/
│
└── assets/
    ├── diagrams/
    ├── figures/
    └── presentation/
```
