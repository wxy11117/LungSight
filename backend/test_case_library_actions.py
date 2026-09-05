from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import app as application
from auth_test_helpers import registration_fields


class CaseLibraryActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.original_database_path = application.DATABASE_PATH
        self.original_data_dir = application.DATA_DIR
        self.original_uploads_dir = application.UPLOADS_DIR
        self.original_attention_dir = application.ATTENTION_DIR
        application.DATA_DIR = Path(self.temporary.name)
        application.UPLOADS_DIR = application.DATA_DIR / "uploads"
        application.ATTENTION_DIR = application.DATA_DIR / "attention"
        application.DATABASE_PATH = application.DATA_DIR / "case-library.sqlite3"
        application.initialize_database()
        application.initialize_auth_schema(application.DATABASE_PATH)
        application.initialize_agent_schema(application.DATABASE_PATH)
        application.initialize_knowledge_schema(application.DATABASE_PATH)
        self.client = TestClient(application.app)
        response = self.client.post(
            "/api/auth/register",
            json={
                **registration_fields("case-action-pass-2026"),
                "email": "case-actions@example.com",
                "display_name": "病例操作测试",
                "password": "case-action-pass-2026",
                "accepted_terms": True,
                "accepted_privacy": True,
            },
        )
        self.assertEqual(response.status_code, 201)
        with application.database_connection() as connection:
            self.user_id = connection.execute(
                "SELECT user_id FROM users WHERE email = ?", ("case-actions@example.com",)
            ).fetchone()[0]

    def tearDown(self) -> None:
        self.client.close()
        application.DATABASE_PATH = self.original_database_path
        application.DATA_DIR = self.original_data_dir
        application.UPLOADS_DIR = self.original_uploads_dir
        application.ATTENTION_DIR = self.original_attention_dir
        self.temporary.cleanup()

    def seed_task(self, task_id: str, created_at: str) -> None:
        image = application.UPLOADS_DIR / f"{task_id}.png"
        attention = application.ATTENTION_DIR / f"{task_id}.png"
        image.write_bytes(b"image")
        attention.write_bytes(b"attention")
        analysis = {
            "prediction": {
                "top_class": "normal",
                "top_class_cn": "正常肺部",
                "probabilities": {
                    "adenocarcinoma": 0.02,
                    "large_cell_carcinoma": 0.01,
                    "normal": 0.95,
                    "squamous_cell_carcinoma": 0.02,
                },
            }
        }
        with application.database_connection() as connection:
            connection.execute(
                """INSERT INTO analysis_tasks
                   (task_id, created_at, updated_at, status, file_name, image_path,
                    image_sha256, top_class, top_class_cn, reliability_level,
                    fold_agreement, analysis_json, quality_status, priority,
                    attention_path, owner_user_id)
                   VALUES (?, ?, ?, 'WAITING_FOR_REVIEW', ?, ?, ?, 'normal',
                           '正常肺部', 'STABLE', 5, ?, 'PASS', 'ROUTINE', ?, ?)""",
                (
                    task_id, created_at, created_at, f"{task_id}.png", image.name,
                    f"sha-{task_id}", json.dumps(analysis, ensure_ascii=False),
                    attention.name, self.user_id,
                ),
            )

    def test_star_archive_restore_and_permanent_delete(self) -> None:
        self.seed_task("CT-CASE-OLDER", "2026-09-01T00:00:00+00:00")
        self.seed_task("CT-CASE-NEWER", "2026-09-02T00:00:00+00:00")

        starred = self.client.patch(
            "/api/tasks/CT-CASE-OLDER/library", json={"action": "STAR"}
        )
        self.assertEqual(starred.status_code, 200)
        self.assertIsNotNone(starred.json()["starred_at"])
        active = self.client.get("/api/tasks")
        self.assertEqual(active.status_code, 200)
        self.assertEqual(active.json()["items"][0]["task_id"], "CT-CASE-OLDER")

        archived = self.client.patch(
            "/api/tasks/CT-CASE-OLDER/library", json={"action": "ARCHIVE"}
        )
        self.assertEqual(archived.status_code, 200)
        self.assertEqual([item["task_id"] for item in self.client.get("/api/tasks").json()["items"]], ["CT-CASE-NEWER"])
        archive_payload = self.client.get("/api/tasks?archived=true").json()
        self.assertEqual(archive_payload["items"][0]["task_id"], "CT-CASE-OLDER")
        self.assertEqual(archive_payload["counts"]["archived"], 1)

        restored = self.client.patch(
            "/api/tasks/CT-CASE-OLDER/library", json={"action": "RESTORE"}
        )
        self.assertEqual(restored.status_code, 200)
        self.assertIsNone(restored.json()["archived_at"])
        self.client.patch("/api/tasks/CT-CASE-OLDER/library", json={"action": "ARCHIVE"})

        deleted = self.client.delete("/api/tasks/CT-CASE-OLDER")
        self.assertEqual(deleted.status_code, 200)
        self.assertTrue(deleted.json()["deleted"])
        self.assertEqual(self.client.get("/api/tasks?archived=true").json()["items"], [])
        self.assertFalse((application.UPLOADS_DIR / "CT-CASE-OLDER.png").exists())
        self.assertFalse((application.ATTENTION_DIR / "CT-CASE-OLDER.png").exists())
        with application.database_connection() as connection:
            self.assertIsNone(connection.execute(
                "SELECT 1 FROM analysis_tasks WHERE task_id = ?", ("CT-CASE-OLDER",)
            ).fetchone())

    def test_archive_actions_require_ownership_and_valid_transitions(self) -> None:
        self.seed_task("CT-PRIVATE", "2026-09-03T00:00:00+00:00")
        self.assertEqual(
            self.client.patch("/api/tasks/CT-PRIVATE/library", json={"action": "RESTORE"}).status_code,
            409,
        )
        second = TestClient(application.app)
        try:
            response = second.post(
                "/api/auth/register",
                json={
                    **registration_fields("second-case-pass-2026"),
                    "email": "second-case@example.com",
                    "display_name": "第二账号",
                    "password": "second-case-pass-2026",
                    "accepted_terms": True,
                    "accepted_privacy": True,
                },
            )
            self.assertEqual(response.status_code, 201)
            self.assertEqual(
                second.patch("/api/tasks/CT-PRIVATE/library", json={"action": "ARCHIVE"}).status_code,
                404,
            )
            self.assertEqual(second.delete("/api/tasks/CT-PRIVATE").status_code, 404)
        finally:
            second.close()


if __name__ == "__main__":
    unittest.main()

