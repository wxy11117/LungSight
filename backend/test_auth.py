from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from auth import (
    authenticate_user,
    create_session,
    delete_openai_credential,
    get_openai_credential_status,
    get_user_for_session,
    get_llm_settings,
    initialize_auth_schema,
    load_openai_credential,
    load_llm_credential,
    register_user,
    revoke_session,
    save_openai_credential,
    save_llm_credential,
    select_llm_provider,
)


class AuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temporary.name)
        self.database_path = self.data_dir / "test.sqlite3"
        initialize_auth_schema(self.database_path)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def create_user(self) -> dict:
        return register_user(
            self.database_path,
            email="Doctor@example.com",
            display_name="测试医生",
            password="secure-pass-2026",
            accepted_terms=True,
            accepted_privacy=True,
        )

    def test_register_hashes_password_and_rejects_duplicate(self) -> None:
        user = self.create_user()
        self.assertEqual(user["email"], "doctor@example.com")
        with closing(sqlite3.connect(self.database_path)) as connection:
            stored = connection.execute("SELECT password_hash FROM users").fetchone()[0]
        self.assertNotIn("secure-pass-2026", stored)
        with self.assertRaisesRegex(ValueError, "已经注册"):
            self.create_user()

    def test_login_session_and_logout(self) -> None:
        user = self.create_user()
        self.assertIsNone(
            authenticate_user(
                self.database_path, email="doctor@example.com", password="wrong-password"
            )
        )
        authenticated = authenticate_user(
            self.database_path, email="doctor@example.com", password="secure-pass-2026"
        )
        self.assertEqual(authenticated["user_id"], user["user_id"])
        token, _ = create_session(
            self.database_path, user_id=user["user_id"], user_agent="unit-test"
        )
        self.assertEqual(get_user_for_session(self.database_path, token)["user_id"], user["user_id"])
        revoke_session(self.database_path, token)
        self.assertIsNone(get_user_for_session(self.database_path, token))

    def test_openai_key_is_encrypted_and_only_mask_is_returned(self) -> None:
        user = self.create_user()
        api_key = "sk-test-abcdefghijklmnopqrstuvwxyz123456"
        status = save_openai_credential(
            self.database_path,
            self.data_dir,
            user_id=user["user_id"],
            api_key=api_key,
            model="gpt-5.4",
        )
        self.assertTrue(status["configured"])
        self.assertTrue(status["masked_key"].endswith("3456"))
        with closing(sqlite3.connect(self.database_path)) as connection:
            encrypted = connection.execute(
                "SELECT encrypted_api_key FROM openai_credentials"
            ).fetchone()[0]
        self.assertNotIn(api_key, encrypted)
        loaded_key, model = load_openai_credential(
            self.database_path, self.data_dir, user_id=user["user_id"]
        )
        self.assertEqual(loaded_key, api_key)
        self.assertEqual(model, "gpt-5.4")
        delete_openai_credential(self.database_path, user_id=user["user_id"])
        self.assertFalse(
            get_openai_credential_status(self.database_path, user_id=user["user_id"])["configured"]
        )

    def test_multiple_llm_providers_are_encrypted_and_switchable(self) -> None:
        user = self.create_user()
        save_llm_credential(
            self.database_path, self.data_dir, user_id=user["user_id"], provider="openai",
            api_key="sk-openai-abcdefghijklmnopqrstuvwxyz", model="gpt-5.4",
        )
        save_llm_credential(
            self.database_path, self.data_dir, user_id=user["user_id"], provider="kimi",
            api_key="sk-kimi-abcdefghijklmnopqrstuvwxyz", model="kimi-k3",
        )
        save_llm_credential(
            self.database_path, self.data_dir, user_id=user["user_id"], provider="deepseek",
            api_key="sk-deepseek-abcdefghijklmnopqrstuvwxyz", model="deepseek-v4-flash",
        )
        settings = get_llm_settings(self.database_path, user_id=user["user_id"])
        self.assertEqual(settings["selected_provider"], "deepseek")
        self.assertTrue(all(item["configured"] for item in settings["providers"]))
        select_llm_provider(self.database_path, user_id=user["user_id"], provider="kimi")
        provider, key, model = load_llm_credential(
            self.database_path, self.data_dir, user_id=user["user_id"]
        )
        self.assertEqual((provider, model), ("kimi", "kimi-k3"))
        self.assertEqual(key, "sk-kimi-abcdefghijklmnopqrstuvwxyz")


if __name__ == "__main__":
    unittest.main()
