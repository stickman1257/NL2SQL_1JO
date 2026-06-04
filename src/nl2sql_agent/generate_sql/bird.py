import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class BirdExample:
    question_id: str
    db_id: str
    question: str
    evidence: str
    gold_sql: str
    difficulty: str
    raw: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question_id": self.question_id,
            "db_id": self.db_id,
            "question": self.question,
            "evidence": self.evidence,
            "gold_sql": self.gold_sql,
            "difficulty": self.difficulty,
            "raw": self.raw,
        }


def load_bird_examples(path: str, limit: Optional[int] = None) -> List[BirdExample]:
    source = Path(path).expanduser().resolve()
    rows = _load_json_or_jsonl(source)
    examples = []
    for idx, row in enumerate(rows):
        db_id = str(row.get("db_id") or row.get("database_id") or "")
        question = str(row.get("question") or row.get("utterance") or row.get("nl") or "")
        evidence = str(row.get("evidence") or row.get("external_knowledge") or "")
        gold_sql = str(row.get("SQL") or row.get("sql") or row.get("query") or "")
        qid = str(row.get("question_id") or row.get("id") or idx)
        difficulty = str(row.get("difficulty") or row.get("question_difficulty") or "")
        if db_id and question:
            examples.append(BirdExample(qid, db_id, question, evidence, gold_sql, difficulty, row))
        if limit is not None and len(examples) >= limit:
            break
    return examples


def iter_jsonl(path: str, rows: Iterable[Dict[str, Any]]) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def resolve_database_root(bird_root: str, split: Optional[str] = None) -> str:
    root = Path(bird_root).expanduser().resolve()
    if split:
        candidates = [
            root / f"{split}_databases",
            root / f"{split}" / f"{split}_databases",
            root / "database",
            root / "databases",
        ]
    else:
        candidates = [root / "dev_databases", root / "train_databases", root / "database", root / "databases", root]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return str(root)


def _load_json_or_jsonl(path: Path) -> List[Dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    stripped = text.strip()
    if not stripped:
        return []
    if stripped[0] == "[":
        data = json.loads(stripped)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []
    rows = []
    for line in stripped.splitlines():
        line = line.strip()
        if line:
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    return rows
