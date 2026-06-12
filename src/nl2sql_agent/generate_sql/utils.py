import json
import re
from typing import Any, Dict, Iterable, List, Optional


WRITE_KEYWORDS = {
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "create",
    "attach",
    "detach",
    "pragma",
    "vacuum",
    "reindex",
    "replace",
    "truncate",
}


def compact_text(text: Optional[str]) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def tokenize(text: Optional[str]) -> List[str]:
    normalized = compact_text(text).lower()
    return re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*|\d+(?:\.\d+)?", normalized)


def unique_keep_order(items: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def strip_code_fence(text: str) -> str:
    value = text.strip()
    fenced = re.search(r"```(?:sql|json)?\s*(.*?)```", value, re.IGNORECASE | re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    return value


def extract_json_object(text: str) -> Dict[str, Any]:
    cleaned = strip_code_fence(text)
    try:
        value = json.loads(cleaned)
        if isinstance(value, dict):
            return value
    except Exception:
        pass
    starts = [i for i, ch in enumerate(cleaned) if ch == "{"]
    for start in starts:
        depth = 0
        in_string = False
        escape = False
        for idx in range(start, len(cleaned)):
            ch = cleaned[idx]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
            else:
                if ch == '"':
                    in_string = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = cleaned[start : idx + 1]
                        try:
                            value = json.loads(candidate)
                            if isinstance(value, dict):
                                return value
                        except Exception:
                            break
    return {}


def extract_sql(text: str) -> str:
    cleaned = strip_code_fence(text).strip()
    obj = extract_json_object(cleaned)
    if obj.get("sql"):
        return str(obj["sql"]).strip()
    sql_match = re.search(r"(?is)\b(with\b.*|select\b.*)", cleaned)
    if sql_match:
        candidate = sql_match.group(1).strip()
        return candidate.rstrip("`").strip()
    return cleaned


def split_sql_statements(sql: str) -> List[str]:
    try:
        import sqlparse

        return [s.strip() for s in sqlparse.split(sql) if s.strip()]
    except Exception:
        parts = [p.strip() for p in sql.split(";") if p.strip()]
        return parts


def normalize_sql(sql: str) -> str:
    value = strip_code_fence(sql).strip()
    value = re.sub(r"^SQL\s*:\s*", "", value, flags=re.IGNORECASE)
    value = value.strip()
    if value.endswith(";"):
        value = value[:-1].strip()
    return value


def validate_readonly_sql(sql: str) -> Optional[str]:
    value = normalize_sql(sql)
    if not value:
        return "SQL is empty"
    statements = split_sql_statements(value)
    if len(statements) != 1:
        return "SQL must contain exactly one statement"
    lowered = statements[0].lower()
    first = re.match(r"\s*([a-zA-Z]+)", lowered)
    if not first or first.group(1) not in {"select", "with"}:
        return "SQL must start with SELECT or WITH"
    for keyword in WRITE_KEYWORDS:
        if re.search(rf"\b{re.escape(keyword)}\b", lowered):
            return f"SQL contains disallowed keyword: {keyword}"
    return None


def quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def rows_to_jsonable(rows: List[tuple]) -> List[List[Any]]:
    result = []
    for row in rows:
        result.append([item for item in row])
    return result


def truncate_middle(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    return text[:half].rstrip() + "\n...\n" + text[-half:].lstrip()
