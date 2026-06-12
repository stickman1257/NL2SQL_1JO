"""샘플 SQLite DB와 NL2SQL 로그를 생성한다."""

import json
import os
import sqlite3

BASE_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(BASE_DIR, "ecommerce.sqlite")
LOG_PATH = os.path.join(BASE_DIR, "nl2sql_logs.jsonl")


# ------------------------------------------------------------------
# 1. SQLite DB 생성
# ------------------------------------------------------------------

def create_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.executescript("""
    DROP TABLE IF EXISTS orders;
    DROP TABLE IF EXISTS products;
    DROP TABLE IF EXISTS customers;
    DROP TABLE IF EXISTS order_items;

    CREATE TABLE customers (
        customer_id   INTEGER PRIMARY KEY,
        name          TEXT NOT NULL,
        email         TEXT UNIQUE,
        tier          TEXT DEFAULT 'standard',   -- standard / gold / vip
        joined_at     TEXT
    );

    CREATE TABLE products (
        product_id    INTEGER PRIMARY KEY,
        name          TEXT NOT NULL,
        category      TEXT,
        price         REAL,
        stock_qty     INTEGER DEFAULT 0
    );

    CREATE TABLE orders (
        order_id      INTEGER PRIMARY KEY,
        customer_id   INTEGER REFERENCES customers(customer_id),
        status        TEXT,   -- pending / processing / completed / cancelled / refunded
        total_amount  REAL,
        created_at    TEXT,
        updated_at    TEXT
    );

    CREATE TABLE order_items (
        item_id       INTEGER PRIMARY KEY,
        order_id      INTEGER REFERENCES orders(order_id),
        product_id    INTEGER REFERENCES products(product_id),
        quantity      INTEGER,
        unit_price    REAL
    );
    """)

    c.executemany("INSERT INTO customers VALUES (?,?,?,?,?)", [
        (1, "Alice",  "alice@example.com",  "vip",      "2023-01-10"),
        (2, "Bob",    "bob@example.com",    "gold",     "2023-03-15"),
        (3, "Charlie","charlie@example.com","standard", "2023-06-01"),
        (4, "Diana",  "diana@example.com",  "vip",      "2022-11-20"),
        (5, "Eve",    "eve@example.com",    "standard", "2024-01-05"),
    ])

    c.executemany("INSERT INTO products VALUES (?,?,?,?,?)", [
        (1, "Laptop Pro",    "electronics", 1500.0, 50),
        (2, "Wireless Mouse","electronics",   30.0, 200),
        (3, "Desk Chair",    "furniture",    350.0, 30),
        (4, "Notebook Set",  "stationery",    15.0, 500),
        (5, "USB-C Hub",     "electronics",   45.0, 150),
    ])

    statuses = ["completed","completed","pending","refunded","cancelled",
                "processing","completed","refunded","completed","pending"]
    for i, st in enumerate(statuses, 1):
        c.execute("INSERT INTO orders VALUES (?,?,?,?,?,?)",
                  (i, (i % 5) + 1, st, 100.0 * i, f"2026-05-{i:02d}", f"2026-05-{i:02d}"))

    c.executemany("INSERT INTO order_items VALUES (?,?,?,?,?)", [
        (1, 1, 1, 1, 1500.0),  # Alice의 Laptop Pro 주문
        (2, 2, 2, 2, 30.0),    # Bob의 Wireless Mouse 2개
        (3, 3, 3, 1, 350.0),   # Charlie의 Desk Chair
        (4, 4, 4, 3, 15.0),    # Diana의 Notebook Set 3개
        (5, 5, 5, 1, 45.0),    # Eve의 USB-C Hub
        (6, 6, 1, 2, 1500.0),  # Bob의 Laptop Pro 2개
        (7, 7, 3, 1, 350.0),   # Charlie의 Desk Chair 1개
        (8, 8, 4, 5, 15.0),    # Diana의 Notebook Set 5개
        (9, 9, 2, 1, 30.0),    # Eve의 Wireless Mouse 1개
        (10, 10, 5, 2, 45.0),  # Alice의 USB-C Hub 2개
    ])

    conn.commit()
    conn.close()
    print(f"[DB] 생성 완료: {DB_PATH}")


# ------------------------------------------------------------------
# 2. 샘플 NL2SQL 로그 생성 (hard 10 + easy 10)
# ------------------------------------------------------------------

SAMPLE_LOGS = [
    # ========== HARD 쿼리 10개 ==========
    # orders.status 관련 (JOIN, GROUP BY, 집계)
    {"nl_question": "환불된 주문이 몇 건인지 알려줘",
     "generated_sql": "SELECT COUNT(*) FROM orders WHERE orders.status = 'refunded'",
     "difficulty": "hard", "execution_error": None,
     "db_id": "ecommerce", "timestamp": "2026-06-03T09:00:00"},

    {"nl_question": "취소된 주문의 총 금액은?",
     "generated_sql": "SELECT SUM(orders.total_amount) FROM orders WHERE orders.status = 'cancelled'",
     "difficulty": "hard", "execution_error": None,
     "db_id": "ecommerce", "timestamp": "2026-06-03T09:05:00"},

    {"nl_question": "VIP 고객 중 환불 이력이 있는 사람 목록",
     "generated_sql": "SELECT DISTINCT customers.name FROM customers JOIN orders ON customers.customer_id = orders.customer_id WHERE customers.tier = 'vip' AND orders.status = 'refunded'",
     "difficulty": "hard", "execution_error": None,
     "db_id": "ecommerce", "timestamp": "2026-06-03T09:10:00"},

    {"nl_question": "처리 중인 주문의 고객 이메일을 알려줘",
     "generated_sql": "SELECT customers.email FROM customers JOIN orders ON customers.customer_id = orders.customer_id WHERE orders.status = 'processing'",
     "difficulty": "hard", "execution_error": None,
     "db_id": "ecommerce", "timestamp": "2026-06-03T09:15:00"},

    {"nl_question": "상태별 주문 수를 보여줘",
     "generated_sql": "SELECT orders.status, COUNT(*) FROM orders GROUP BY orders.status",
     "difficulty": "hard", "execution_error": None,
     "db_id": "ecommerce", "timestamp": "2026-06-03T09:20:00"},

    # customers.tier 관련 (JOIN + 집계)
    {"nl_question": "골드 등급 고객의 평균 주문 금액은?",
     "generated_sql": "SELECT AVG(orders.total_amount) FROM orders JOIN customers ON orders.customer_id = customers.customer_id WHERE customers.tier = 'gold'",
     "difficulty": "hard", "execution_error": None,
     "db_id": "ecommerce", "timestamp": "2026-06-03T09:25:00"},

    {"nl_question": "등급별 고객 수는?",
     "generated_sql": "SELECT customers.tier, COUNT(*) FROM customers GROUP BY customers.tier",
     "difficulty": "hard", "execution_error": None,
     "db_id": "ecommerce", "timestamp": "2026-06-03T09:30:00"},

    # order_items + products JOIN (다중 JOIN)
    {"nl_question": "가장 많이 팔린 상품 이름과 수량은?",
     "generated_sql": "SELECT products.name, SUM(order_items.quantity) FROM order_items JOIN products ON order_items.product_id = products.product_id GROUP BY products.name ORDER BY SUM(order_items.quantity) DESC LIMIT 1",
     "difficulty": "hard", "execution_error": None,
     "db_id": "ecommerce", "timestamp": "2026-06-03T09:35:00"},

    {"nl_question": "전자제품 카테고리에서 총 판매 금액은?",
     "generated_sql": "SELECT SUM(order_items.quantity * order_items.unit_price) FROM order_items JOIN products ON order_items.product_id = products.product_id WHERE products.category = 'electronics'",
     "difficulty": "hard", "execution_error": None,
     "db_id": "ecommerce", "timestamp": "2026-06-03T09:40:00"},

    # 고객별 통계 (3중 JOIN)
    {"nl_question": "VIP 고객의 총 구매 금액을 고객별로 보여줘",
     "generated_sql": "SELECT customers.name, SUM(orders.total_amount) FROM customers JOIN orders ON customers.customer_id = orders.customer_id WHERE customers.tier = 'vip' GROUP BY customers.name",
     "difficulty": "hard", "execution_error": None,
     "db_id": "ecommerce", "timestamp": "2026-06-03T09:45:00"},

    # ========== EASY 쿼리 10개 ==========
    {"nl_question": "전체 고객 수는?",
     "generated_sql": "SELECT COUNT(*) FROM customers",
     "difficulty": "easy", "execution_error": None,
     "db_id": "ecommerce", "timestamp": "2026-06-03T10:00:00"},

    {"nl_question": "가장 비싼 상품 이름은?",
     "generated_sql": "SELECT products.name FROM products ORDER BY products.price DESC LIMIT 1",
     "difficulty": "easy", "execution_error": None,
     "db_id": "ecommerce", "timestamp": "2026-06-03T10:05:00"},

    {"nl_question": "모든 상품 목록을 보여줘",
     "generated_sql": "SELECT * FROM products",
     "difficulty": "easy", "execution_error": None,
     "db_id": "ecommerce", "timestamp": "2026-06-03T10:10:00"},

    {"nl_question": "앨리스의 이메일은?",
     "generated_sql": "SELECT customers.email FROM customers WHERE customers.name = 'Alice'",
     "difficulty": "easy", "execution_error": None,
     "db_id": "ecommerce", "timestamp": "2026-06-03T10:15:00"},

    {"nl_question": "재고가 100개 이상인 상품은?",
     "generated_sql": "SELECT products.name FROM products WHERE products.stock_qty >= 100",
     "difficulty": "easy", "execution_error": None,
     "db_id": "ecommerce", "timestamp": "2026-06-03T10:20:00"},

    {"nl_question": "가구 카테고리 상품의 가격은?",
     "generated_sql": "SELECT products.name, products.price FROM products WHERE products.category = 'furniture'",
     "difficulty": "easy", "execution_error": None,
     "db_id": "ecommerce", "timestamp": "2026-06-03T10:25:00"},

    {"nl_question": "완료된 주문의 수는?",
     "generated_sql": "SELECT COUNT(*) FROM orders WHERE orders.status = 'completed'",
     "difficulty": "easy", "execution_error": None,
     "db_id": "ecommerce", "timestamp": "2026-06-03T10:30:00"},

    {"nl_question": "가장 최근에 가입한 고객은?",
     "generated_sql": "SELECT customers.name FROM customers ORDER BY customers.joined_at DESC LIMIT 1",
     "difficulty": "easy", "execution_error": None,
     "db_id": "ecommerce", "timestamp": "2026-06-03T10:35:00"},

    {"nl_question": "전체 주문의 평균 금액은?",
     "generated_sql": "SELECT AVG(orders.total_amount) FROM orders",
     "difficulty": "easy", "execution_error": None,
     "db_id": "ecommerce", "timestamp": "2026-06-03T10:40:00"},

    # 실행 에러 (easy지만 에러 — include_execution_errors 옵션으로 Hard 필터에 포함됨)
    {"nl_question": "상품의 재고 컬럼을 보여줘",
     "generated_sql": "SELECT products.name, products.stock FROM products",
     "difficulty": "easy",
     "execution_error": "no such column: products.stock",
     "db_id": "ecommerce", "timestamp": "2026-06-03T10:45:00"},
]


def create_logs():
    with open(LOG_PATH, "w") as f:
        for log in SAMPLE_LOGS:
            f.write(json.dumps(log, ensure_ascii=False) + "\n")
    print(f"[LOG] 생성 완료: {LOG_PATH} ({len(SAMPLE_LOGS)}건)")
    hard_count = sum(1 for l in SAMPLE_LOGS if l["difficulty"] == "hard")
    easy_count = sum(1 for l in SAMPLE_LOGS if l["difficulty"] == "easy")
    print(f"       Hard: {hard_count}, Easy: {easy_count}")


if __name__ == "__main__":
    create_db()
    create_logs()
