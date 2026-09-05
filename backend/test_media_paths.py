from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import app as application
from auth import initialize_auth_schema
from auth_test_helpers import registration_fields


class ManagedMediaPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.original = {
            "DATA_DIR": application.DATA_DIR,
            "DATABASE_PATH": application.DATABASE_PATH,
            "UPLOADS_DIR": application.UPLOADS_DIR,
            "ATTENTION_DIR": application.ATTENTION_DIR,
        }
        application.DATA_DIR = self.root
        application.DATABASE_PATH = self.root / "media.sqlite3"
        application.UPLOADS_DIR = self.root / "uploads"
        application.ATTENTION_DIR = self.root / "attention"
        application.initialize_database()
        initialize_auth_schema(application.DATABASE_PATH)
        self.client = TestClient(application.app)
        registered = self.client.post(
            "/api/auth/register",
            json={
                **registration_fields("secure-pass-2026"),
                "email": "media@example.com",
                "display_name": "影像测试",
                "password": "secure-pass-2026",
                "accepted_terms": True,
                "accepted_privacy": True,
            },
        )
        self.assertEqual(registered.status_code, 201)
        self.user_id = registered.json()["user"]["user_id"]

    def tearDown(self) -> None:
        self.client.close()
        for key, value in self.original.items():
            setattr(application, key, value)
        self.temporary.cleanup()

    def test_legacy_absolute_paths_rebind_to_current_managed_directories(self) -> None:
        task_id = "CT-MOVED000001"
        image = application.UPLOADS_DIR / f"{task_id}.png"
        attention = application.ATTENTION_DIR / f"{task_id}.png"
        image.write_bytes(b"current-image-bytes")
        attention.write_bytes(b"current-attention-bytes")
        legacy_root = Path(r"C:\old-workspace\lung-vision-site\backend\data")
        now = "2026-09-04T00:00:00+00:00"
        with application.database_connection() as connection:
            connection.execute(
                """
                INSERT INTO analysis_tasks (
                    task_id, created_at, updated_at, status, file_name, image_path,
                    image_sha256, top_class, top_class_cn, reliability_level,
                    fold_agreement, analysis_json, attention_path, owner_user_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id, now, now, "WAITING_FOR_REVIEW", "moved.png",
                    str(legacy_root / "uploads" / image.name), "hash", "normal", "正常肺部",
                    "STABLE", 5, json.dumps({"task_id": task_id}),
                    str(legacy_root / "attention" / attention.name), self.user_id,
                ),
            )

        image_response = self.client.get(f"/api/tasks/{task_id}/image")
        attention_response = self.client.get(f"/api/tasks/{task_id}/attention")
        self.assertEqual(image_response.status_code, 200)
        self.assertEqual(image_response.content, b"current-image-bytes")
        self.assertEqual(image_response.headers["cache-control"], "private, no-store")
        self.assertEqual(attention_response.status_code, 200)
        self.assertEqual(attention_response.content, b"current-attention-bytes")
        self.assertEqual(attention_response.headers["cache-control"], "private, no-store")

        application.initialize_database()
        with application.database_connection() as connection:
            row = connection.execute(
                "SELECT image_path, attention_path FROM analysis_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        self.assertEqual(row["image_path"], image.name)
        self.assertEqual(row["attention_path"], attention.name)

    def test_database_path_cannot_escape_the_managed_directory(self) -> None:
        outside = self.root / "outside.png"
        outside.write_bytes(b"private")
        self.assertIsNone(application.resolve_managed_media(str(outside), application.UPLOADS_DIR))


if __name__ == "__main__":
    unittest.main()
