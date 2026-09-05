from __future__ import annotations

import io
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, PngImagePlugin

import app as application
from auth_test_helpers import registration_fields
from auth import create_session, get_user_for_session, initialize_auth_schema
from profile_images import MAX_AVATAR_BYTES, normalize_avatar


def image_bytes(color="red", size=(320, 240), fmt="PNG"):
    buffer = io.BytesIO()
    image = Image.new("RGB", size, color)
    if fmt == "PNG":
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("Comment", "private image metadata")
        image.save(buffer, format=fmt, pnginfo=metadata)
    else:
        image.save(buffer, format=fmt)
    return buffer.getvalue()


class ProfileApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.original_database = application.DATABASE_PATH
        application.DATABASE_PATH = Path(self.temporary.name) / "profile-test.sqlite3"
        initialize_auth_schema(application.DATABASE_PATH)
        self.client = TestClient(application.app)
        result = self.client.post("/api/auth/register", json={
            **registration_fields(),
            "email": "profile@example.com", "display_name": "测试用户", "password": "test-pass-2026",
            "accepted_terms": True, "accepted_privacy": True,
        })
        self.user = result.json()["user"]

    def tearDown(self):
        self.client.close()
        application.DATABASE_PATH = self.original_database
        self.temporary.cleanup()

    def upload(self, payload=None, **kwargs):
        if payload is None:
            payload = image_bytes()
        return self.client.post("/api/auth/avatar", files={"file": ("avatar.png", payload, "image/png")}, **kwargs)

    def test_nickname_persists_across_login_without_changing_identity(self):
        response = self.client.put("/api/auth/profile", json={"display_name": "  新的昵称  "})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["display_name"], "新的昵称")
        self.assertEqual(response.json()["user"]["user_id"], self.user["user_id"])
        self.assertEqual(response.json()["user"]["email"], self.user["email"])
        self.client.post("/api/auth/logout")
        login = self.client.post("/api/auth/login", json={"email": self.user["email"], "password": "test-pass-2026"})
        self.assertEqual(login.json()["user"]["display_name"], "新的昵称")

    def test_invalid_nickname_preserves_previous_value(self):
        for value in ["", "x", "  ", "x" * 61, "ab\ncd", "ab\x00cd", "ab\u202ecd"]:
            with self.subTest(value=value):
                self.assertEqual(self.client.put("/api/auth/profile", json={"display_name": value}).status_code, 422)
        self.assertEqual(self.client.get("/api/auth/me").json()["user"]["display_name"], "测试用户")

    def test_extra_identity_fields_are_rejected(self):
        response = self.client.put("/api/auth/profile", json={"display_name": "新的昵称", "user_id": "another-account", "email": "changed@example.com"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get("/api/auth/me").json()["user"]["email"], self.user["email"])

    def test_avatar_is_private_normalized_and_metadata_free(self):
        response = self.upload()
        self.assertEqual(response.status_code, 200)
        url = response.json()["user"]["avatar_url"]
        avatar = self.client.get(url)
        self.assertEqual(avatar.status_code, 200)
        self.assertEqual(avatar.headers["content-type"], "image/png")
        self.assertIn("no-store", avatar.headers["cache-control"])
        self.assertEqual(avatar.headers["x-content-type-options"], "nosniff")
        with Image.open(io.BytesIO(avatar.content)) as image:
            self.assertEqual(image.size, (256, 256))
            self.assertEqual(image.info, {})
        self.assertEqual(self.client.get("/api/auth/me").json()["user"]["avatar_url"], url)
        self.client.post("/api/auth/logout")
        self.assertEqual(self.client.get(url).status_code, 401)
        self.client.post("/api/auth/login", json={"email": self.user["email"], "password": "test-pass-2026"})
        self.assertEqual(self.client.get(url).content, avatar.content)

    def test_avatar_failure_preserves_existing_picture(self):
        url = self.upload().json()["user"]["avatar_url"]
        before = self.client.get(url).content
        for payload in [b"", b"not an image", b'<svg xmlns="http://www.w3.org/2000/svg"/>', image_bytes()[:40]]:
            with self.subTest(payload=payload[:10]):
                self.assertEqual(self.upload(payload).status_code, 422)
        self.assertEqual(self.upload(b"x" * (MAX_AVATAR_BYTES + 1)).status_code, 413)
        self.assertEqual(self.client.get(url).content, before)

    def test_large_dimensions_and_unsupported_format_rejected(self):
        self.assertEqual(self.upload(image_bytes(size=(4097, 10))).status_code, 422)
        self.assertEqual(self.upload(image_bytes(fmt="GIF")).status_code, 422)

    def test_avatar_replacement_and_audit(self):
        first = self.upload().json()["user"]["avatar_url"]
        second = self.upload(image_bytes("blue")).json()["user"]["avatar_url"]
        self.assertNotEqual(first, second)
        self.client.put("/api/auth/profile", json={"display_name": "新的昵称"})
        with closing(sqlite3.connect(application.DATABASE_PATH)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM user_avatars").fetchone()[0], 1)
            events = [row[0] for row in connection.execute("SELECT event_type FROM account_audit_events")]
        self.assertEqual(events.count("PROFILE_AVATAR_UPDATED"), 2)
        self.assertIn("PROFILE_NAME_UPDATED", events)

    def test_anonymous_requests_rejected(self):
        anonymous = TestClient(application.app)
        try:
            self.assertEqual(anonymous.get("/api/auth/avatar").status_code, 401)
            self.assertEqual(anonymous.put("/api/auth/profile", json={"display_name": "新的昵称"}).status_code, 401)
            self.assertEqual(anonymous.post("/api/auth/avatar", files={"file": ("avatar.png", image_bytes())}).status_code, 401)
        finally:
            anonymous.close()

    def test_accounts_cannot_read_or_change_each_others_avatar(self):
        first_url = self.upload().json()["user"]["avatar_url"]
        first_bytes = self.client.get(first_url).content
        # Do not enter TestClient's lifespan: profile tests must not load CT models.
        other = TestClient(application.app)
        try:
            other_user = other.post("/api/auth/register", json={
                **registration_fields(),
                "email": "other@example.com", "display_name": "另一个用户", "password": "test-pass-2026",
                "accepted_terms": True, "accepted_privacy": True,
            }).json()["user"]
            self.assertEqual(other.get(first_url).status_code, 404)
            self.assertEqual(other.get(f'/api/auth/avatar?user_id={self.user["user_id"]}').status_code, 404)
            other.put("/api/auth/profile", json={"display_name": "其他昵称"})
            other.post("/api/auth/avatar", files={"file": ("avatar.png", image_bytes("green"))}, data={"user_id": self.user["user_id"]})
            self.assertNotEqual(other.get(first_url).content, first_bytes)
            self.assertEqual(self.client.get(first_url).content, first_bytes)
            self.assertEqual(self.client.get("/api/auth/me").json()["user"]["display_name"], self.user["display_name"])
            self.assertNotEqual(other_user["user_id"], self.user["user_id"])
        finally:
            other.close()

    def test_cross_origin_profile_mutations_rejected(self):
        headers = {"Origin": "http://127.0.0.1:9999"}
        self.assertEqual(self.client.put("/api/auth/profile", json={"display_name": "新的昵称"}, headers=headers).status_code, 403)
        self.assertEqual(self.upload(headers=headers).status_code, 403)
        allowed = {"Origin": "http://127.0.0.1:3000"}
        self.assertEqual(self.upload(headers=allowed).status_code, 200)

    def test_schema_initialization_is_repeatable(self):
        avatar = self.upload().json()["user"]["avatar_url"]
        initialize_auth_schema(application.DATABASE_PATH)
        initialize_auth_schema(application.DATABASE_PATH)
        self.assertEqual(self.client.get("/api/auth/me").json()["user"]["avatar_url"], avatar)


class ProfileImageTests(unittest.TestCase):
    def test_supported_formats(self):
        for fmt in ["PNG", "JPEG", "WEBP"]:
            with self.subTest(fmt=fmt):
                with Image.open(io.BytesIO(normalize_avatar(image_bytes(fmt=fmt)))) as image:
                    self.assertEqual(image.format, "PNG")
                    self.assertEqual(image.size, (256, 256))

    def test_animated_png_rejected(self):
        output = io.BytesIO()
        first = Image.new("RGB", (64, 64), "red")
        first.save(output, format="PNG", save_all=True, append_images=[Image.new("RGB", (64, 64), "blue")], duration=100, loop=0)
        with self.assertRaisesRegex(ValueError, "静态"):
            normalize_avatar(output.getvalue())

    def test_exif_is_removed(self):
        image = Image.new("RGB", (60, 40), "green")
        exif = image.getexif()
        exif[270] = "private description"
        exif[274] = 6
        output = io.BytesIO()
        image.save(output, format="JPEG", exif=exif)
        with Image.open(io.BytesIO(normalize_avatar(output.getvalue()))) as result:
            self.assertFalse(result.getexif())
            self.assertEqual(result.info, {})

    def test_existing_database_migrates_without_losing_account(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.sqlite3"
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("""CREATE TABLE users (
                    user_id TEXT PRIMARY KEY, email TEXT UNIQUE, display_name TEXT, password_hash TEXT,
                    status TEXT DEFAULT 'ACTIVE', failed_login_count INTEGER DEFAULT 0, locked_until TEXT,
                    accepted_terms_at TEXT, accepted_privacy_at TEXT, created_at TEXT, updated_at TEXT, last_login_at TEXT
                )""")
                connection.execute("INSERT INTO users (user_id, email, display_name, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                                   ("legacy", "legacy@example.com", "原有昵称", "unchanged-hash", "2026-08-29"))
                connection.commit()
            initialize_auth_schema(path)
            token, _ = create_session(path, user_id="legacy", user_agent=None)
            user = get_user_for_session(path, token)
            self.assertEqual(user["display_name"], "原有昵称")
            self.assertIsNone(user["avatar_url"])
            with closing(sqlite3.connect(path)) as connection:
                self.assertEqual(connection.execute("SELECT password_hash FROM users").fetchone()[0], "unchanged-hash")


if __name__ == "__main__":
    unittest.main()
