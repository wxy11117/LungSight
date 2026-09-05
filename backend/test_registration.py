from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient

import app as application
from auth import initialize_auth_schema, register_user, create_session, get_user_for_session
from auth_test_helpers import registration_fields
from registration import CATALOG, normalize_phone


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = application.DATABASE_PATH
        application.DATABASE_PATH = Path(self.tmp.name) / "registration.sqlite3"
        initialize_auth_schema(application.DATABASE_PATH)
        self.client = TestClient(application.app)  # No model/network lifespan.

    def tearDown(self):
        self.client.close()
        application.DATABASE_PATH = self.old_path
        self.tmp.cleanup()

    def payload(self, **changes):
        return {"email": "doctor@example.com", "display_name": "测试昵称", "password": "test-pass-2026",
                "accepted_terms": True, "accepted_privacy": True, **registration_fields(), **changes}

    def test_email_only_register_logout_login_and_profile_persistence(self):
        response = self.client.post("/api/auth/register", json=self.payload())
        self.assertEqual(response.status_code, 201, response.text)
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertEqual(response.json()["user"]["identity_verification"], "UNVERIFIED")
        self.assertIsNone(response.json()["user"]["phone_masked"])
        self.client.post("/api/auth/logout")
        response = self.client.post("/api/auth/login", json={"email": " DOCTOR@EXAMPLE.COM ", "password": "test-pass-2026"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/auth/doctor-profile").json()["profile"]["hospital_name"], "测试医院（虚构）")
        self.assertEqual(self.client.get("/api/auth/doctor-profile").json()["profile"]["verification_status"], "SELF_DECLARED")

    def test_phone_only_registration_and_normalized_login(self):
        payload = self.payload(phone="13800138000")
        payload.pop("email")
        response = self.client.post("/api/auth/register", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        user = response.json()["user"]
        self.assertIsNone(user["email"])
        self.assertNotIn("13800138000", response.text)
        self.assertNotIn("phone-account:", response.text)
        self.assertIn("*", user["phone_masked"])
        self.client.post("/api/auth/logout")
        self.assertEqual(self.client.post("/api/auth/login", json={"phone": "+86 138-0013-8000", "password": "test-pass-2026"}).status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me").json()["user"]["user_id"], user["user_id"])
        self.assertEqual(self.client.post("/api/auth/login", json={"phone": "13800138000", "password": "wrong-password"}).status_code, 401)

    def test_both_identities_or_neither_are_rejected(self):
        for payload in [self.payload(phone="13800138000"), self.payload(email=None)]:
            self.assertEqual(self.client.post("/api/auth/register", json=payload).status_code, 422)
        for payload in [{"email": "doctor@example.com", "phone": "13800138000"}, {}]:
            self.assertEqual(self.client.post("/api/auth/login", json={**payload, "password": "test-pass-2026"}).status_code, 422)

    def test_duplicates_rejected_including_canonical_phone(self):
        self.assertEqual(self.client.post("/api/auth/register", json=self.payload()).status_code, 201)
        self.assertEqual(self.client.post("/api/auth/register", json=self.payload(email=" DOCTOR@example.com ")).status_code, 409)
        payload = self.payload(phone="13800138000"); payload.pop("email")
        self.assertEqual(self.client.post("/api/auth/register", json=payload).status_code, 201)
        payload["phone"] = "+86 138 0013 8000"
        self.assertEqual(self.client.post("/api/auth/register", json=payload).status_code, 409)

    def test_no_partial_account_created_on_bad_registration(self):
        cases = [self.payload(confirm_password="different-2026"), self.payload(accepted_terms=False),
                 self.payload(accepted_privacy="true"), self.payload(password="abcdefghijk", confirm_password="abcdefghijk"),
                 self.payload(doctor_profile=None), self.payload(role="admin"), self.payload(display_name="  ")]
        for bad_profile in [{}, {**registration_fields()["doctor_profile"], "province": "不存在"},
                            {**registration_fields()["doctor_profile"], "real_name": "张\n医生"},
                            {**registration_fields()["doctor_profile"], "verification_status": "VERIFIED"}]:
            cases.append(self.payload(doctor_profile=bad_profile))
        for payload in cases:
            with self.subTest(payload_keys=list(payload)):
                response = self.client.post("/api/auth/register", json=payload)
                self.assertEqual(response.status_code, 422, response.text)
        with closing(sqlite3.connect(application.DATABASE_PATH)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM doctor_profiles").fetchone()[0], 0)

    def test_password_and_doctor_details_not_echoed_in_validation_or_audit(self):
        invalid = self.payload(password="short-secret", doctor_profile=None)
        response = self.client.post("/api/auth/register", json=invalid)
        self.assertNotIn("short-secret", response.text)
        self.assertNotIn("test-pass-2026", response.text)
        self.assertEqual(self.client.post("/api/auth/register", json=self.payload()).status_code, 201)
        with closing(sqlite3.connect(application.DATABASE_PATH)) as db:
            hashed = db.execute("SELECT password_hash FROM users").fetchone()[0]
            audit = json.dumps(db.execute("SELECT * FROM account_audit_events").fetchall(), ensure_ascii=False)
            columns = [row[1] for row in db.execute("PRAGMA table_info(users)")]
        self.assertTrue(hashed.startswith("$argon2"))
        self.assertNotIn("confirm_password", columns)
        for secret in ["test-pass-2026", "测试医生", "doctor@example.com", "测试医院"]:
            self.assertNotIn(secret, audit)

    def test_hospital_selection_matches_region_and_manual_fallback(self):
        hospital = CATALOG["hospitals"][0]
        profile = {**registration_fields()["doctor_profile"], "hospital_id": hospital["id"], "hospital_name": hospital["name"]}
        self.assertEqual(self.client.post("/api/auth/register", json=self.payload(doctor_profile={**profile, "province": "四川省"})).status_code, 422)
        self.assertEqual(self.client.post("/api/auth/register", json=self.payload(doctor_profile={**profile, "hospital_id": "unknown"})).status_code, 422)
        self.assertEqual(self.client.post("/api/auth/register", json=self.payload(doctor_profile=profile)).status_code, 201)
        manual = {**profile, "province": "西藏自治区", "city": "拉萨市", "hospital_id": None, "hospital_name": "未收录测试医院"}
        self.assertEqual(self.client.post("/api/auth/register", json=self.payload(email="second@example.com", doctor_profile=manual)).status_code, 201)

    def test_doctor_profile_is_self_only_and_missing_for_legacy_accounts(self):
        first = self.client.post("/api/auth/register", json=self.payload()).json()["user"]
        self.client.post("/api/auth/logout")
        self.assertEqual(self.client.get("/api/auth/doctor-profile").status_code, 401)
        second_profile = {**registration_fields()["doctor_profile"], "real_name": "另一个医生"}
        self.client.post("/api/auth/register", json=self.payload(email="second@example.com", doctor_profile=second_profile))
        response = self.client.get("/api/auth/doctor-profile", params={"user_id": first["user_id"]})
        self.assertEqual(response.json()["profile"]["real_name"], "另一个医生")
        self.assertIn("no-store", response.headers["cache-control"])

    def test_migration_preserves_legacy_sessions_and_email_login(self):
        user = register_user(application.DATABASE_PATH, email="legacy@example.com", display_name="原有医生", password="test-pass-2026", accepted_terms=True, accepted_privacy=True)
        token, _ = create_session(application.DATABASE_PATH, user_id=user["user_id"], user_agent=None)
        initialize_auth_schema(application.DATABASE_PATH)
        initialize_auth_schema(application.DATABASE_PATH)
        self.assertEqual(get_user_for_session(application.DATABASE_PATH, token)["user_id"], user["user_id"])
        self.assertEqual(self.client.post("/api/auth/login", json={"email": "legacy@example.com", "password": "test-pass-2026"}).status_code, 200)
        self.assertIsNone(self.client.get("/api/auth/doctor-profile").json()["profile"])

    def test_phone_validation_and_lockout(self):
        for phone in ["123", "+8612800138000", "+86138001380000", "abc", "１３８００１３８０００"]:
            with self.assertRaises(ValueError): normalize_phone(phone)
        for phone in ["13800138000", "+85251234567", "+85361234567", "+886912345678"]:
            self.assertTrue(normalize_phone(phone).startswith("+"))
        payload = self.payload(phone="13800138000"); payload.pop("email")
        self.client.post("/api/auth/register", json=payload)
        for _ in range(5):
            self.assertEqual(self.client.post("/api/auth/login", json={"phone": "13800138000", "password": "wrong-password"}).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json={"phone": "13800138000", "password": "test-pass-2026"}).status_code, 429)

    def test_cross_origin_auth_rejected(self):
        headers = {"Origin": "https://untrusted.example"}
        self.assertEqual(self.client.post("/api/auth/register", json=self.payload(), headers=headers).status_code, 403)
        self.assertEqual(self.client.post("/api/auth/login", json={"email": "doctor@example.com", "password": "test-pass-2026"}, headers=headers).status_code, 403)

    def test_local_account_picker_requires_session_and_switch_reauthenticates_target(self):
        first = self.client.post("/api/auth/register", json=self.payload()).json()["user"]
        self.client.post("/api/auth/logout")
        second = self.client.post("/api/auth/register", json=self.payload(email="second@example.com", password="second-pass-2026", confirm_password="second-pass-2026")).json()["user"]

        accounts = self.client.get("/api/auth/accounts")
        self.assertEqual(accounts.status_code, 200)
        self.assertIn("no-store", accounts.headers["cache-control"])
        items = accounts.json()["items"]
        self.assertEqual({item["user_id"] for item in items}, {first["user_id"], second["user_id"]})
        self.assertTrue(items[0]["is_current"])
        self.assertNotIn("doctor@example.com", accounts.text)

        rejected = self.client.post("/api/auth/switch", json={"user_id": first["user_id"], "password": "wrong-password"})
        self.assertEqual(rejected.status_code, 401)
        self.assertEqual(self.client.get("/api/auth/me").json()["user"]["user_id"], second["user_id"])

        switched = self.client.post("/api/auth/switch", json={"user_id": first["user_id"], "password": "test-pass-2026"})
        self.assertEqual(switched.status_code, 200, switched.text)
        self.assertEqual(switched.json()["previous_user_id"], second["user_id"])
        self.assertEqual(self.client.get("/api/auth/me").json()["user"]["user_id"], first["user_id"])

        self.client.post("/api/auth/logout")
        self.assertEqual(self.client.get("/api/auth/accounts").status_code, 401)


if __name__ == "__main__":
    unittest.main()
