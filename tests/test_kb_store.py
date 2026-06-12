import json
import tempfile
import unittest
from pathlib import Path

from nl2sql_agent.schema.kb_store import (
    ColumnKBEntry,
    DescriptionVersion,
    SchemaKBConfig,
    SchemaKBStore,
    format_enriched_note,
    merge_column_descriptions,
    resolve_kb_path,
    save_kb_file,
)
from nl2sql_agent.schema_enricher.kb_updater import SchemaKBUpdater
from nl2sql_agent.schema_enricher.db_explorer import ExplorationResult


class SchemaKBStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        self.kb_path = self.base_dir / "ecommerce_kb.json"
        self.kb_path.write_text(
            json.dumps(
                {
                    "orders.status": {
                        "table": "orders",
                        "column": "status",
                        "current_description": "주문 상태 컬럼",
                        "history": [
                            {
                                "description": "주문 상태 컬럼",
                                "version": 1,
                                "updated_at": "2026-06-03T10:00:00",
                                "source": "schema_enricher",
                            }
                        ],
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_resolve_kb_path_uses_template(self):
        config = SchemaKBConfig(path_template="ecommerce_kb.json")
        resolved = resolve_kb_path(config, "ecommerce", self.base_dir)
        self.assertEqual(resolved, self.kb_path)

    def test_format_enriched_note_includes_version_and_date(self):
        entry = SchemaKBStore(str(self.kb_path)).get_entry("orders", "status")
        self.assertIsNotNone(entry)
        note = format_enriched_note(entry)
        self.assertIn("enriched_note (v1, 2026-06-03)", note)
        self.assertIn("주문 상태 컬럼", note)

    def test_merge_column_descriptions_supplement(self):
        entry = ColumnKBEntry(
            table="orders",
            column="status",
            current_description="환불, 취소, 처리 중",
            history=[
                DescriptionVersion(
                    description="환불, 취소, 처리 중",
                    version=2,
                    updated_at="2026-06-03T11:00:00",
                )
            ],
        )
        primary, enriched, hit = merge_column_descriptions(
            "Order lifecycle state",
            "",
            entry,
            merge_mode="supplement",
        )
        self.assertEqual(primary, "Order lifecycle state")
        self.assertIn("enriched_note (v1, 2026-06-03)", enriched)
        self.assertEqual(hit, "orders.status")

    def test_updater_shares_store_and_versions(self):
        updater = SchemaKBUpdater(str(self.kb_path))
        updater.update(
            ExplorationResult(
                table="orders",
                column="status",
                nl_questions=["환불 주문 수"],
                enriched_description="환불 포함 주문 상태",
                done=True,
            )
        )
        self.assertEqual(len(updater), 1)
        entry = updater.get_entry("orders", "status")
        self.assertEqual(entry.current_description, "환불 포함 주문 상태")
        self.assertEqual(len(entry.history), 2)

        out_path = self.base_dir / "saved_kb.json"
        updater.kb_path = str(out_path)
        updater.save()
        reloaded = SchemaKBStore(str(out_path))
        self.assertEqual(reloaded.get_entry("orders", "status").version, 2)


if __name__ == "__main__":
    unittest.main()
