from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import app as application
from auth_test_helpers import registration_fields


class AuthApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.original_database_path = application.DATABASE_PATH
        self.original_data_dir = application.DATA_DIR
        application.DATA_DIR = Path(self.temporary.name)
        application.DATABASE_PATH = application.DATA_DIR / "api-test.sqlite3"
        application.initialize_database()
        application.initialize_auth_schema(application.DATABASE_PATH)
        self.client = TestClient(application.app)

    def tearDown(self) -> None:
        self.client.close()
        application.DATABASE_PATH = self.original_database_path
        application.DATA_DIR = self.original_data_dir
        self.temporary.cleanup()

    def test_protected_workspace_flow(self) -> None:
        anonymous = self.client.get("/api/tasks")
        self.assertEqual(anonymous.status_code, 401)

        registered = self.client.post(
            "/api/auth/register",
            json={
                **registration_fields("secure-pass-2026"),
                "email": "api@example.com",
                "display_name": "接口测试",
                "password": "secure-pass-2026",
                "accepted_terms": True,
                "accepted_privacy": True,
            },
        )
        self.assertEqual(registered.status_code, 201)
        self.assertIn("lungsight_session", self.client.cookies)

        me = self.client.get("/api/auth/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["user"]["email"], "api@example.com")

        tasks = self.client.get("/api/tasks")
        self.assertEqual(tasks.status_code, 200)
        self.assertEqual(tasks.json()["items"], [])

        saved = self.client.put(
            "/api/settings/openai",
            json={
                "api_key": "sk-test-abcdefghijklmnopqrstuvwxyz123456",
                "model": "gpt-5.4",
            },
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["masked_key"], "sk-••••••••3456")

        kimi_saved = self.client.put(
            "/api/settings/llm",
            json={"provider":"kimi", "api_key":"sk-kimi-abcdefghijklmnopqrstuvwxyz", "model":"kimi-k3"},
        )
        self.assertEqual(kimi_saved.status_code, 200)
        self.assertEqual(kimi_saved.json()["selected_provider"], "kimi")
        deepseek_saved = self.client.put(
            "/api/settings/llm",
            json={"provider":"deepseek", "api_key":"sk-deepseek-abcdefghijklmnopqrstuvwxyz", "model":"deepseek-v4-flash"},
        )
        self.assertEqual(deepseek_saved.status_code, 200)
        selected = self.client.post(
            "/api/settings/llm/select", json={"provider":"kimi", "model":"kimi-k3"},
        )
        self.assertEqual(selected.status_code, 200)
        self.assertEqual(selected.json()["selected_provider"], "kimi")

        logged_out = self.client.post("/api/auth/logout")
        self.assertEqual(logged_out.status_code, 204)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)


if __name__ == "__main__":
    unittest.main()
