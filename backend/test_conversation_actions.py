from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient

import app as application
from auth_test_helpers import registration_fields
from agent_service import connect, initialize_agent_schema
from auth import initialize_auth_schema


class ConversationActionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.original_database = application.DATABASE_PATH
        application.DATABASE_PATH = Path(self.temporary.name) / "history.sqlite3"
        application.initialize_database()
        initialize_auth_schema(application.DATABASE_PATH)
        initialize_agent_schema(application.DATABASE_PATH)
        self.client = TestClient(application.app)
        self.other = TestClient(application.app)
        self.anonymous = TestClient(application.app)
        for client, email in [(self.client, "history@example.com"), (self.other, "other@example.com")]:
            response = client.post("/api/auth/register", json={
                **registration_fields(),
                "email": email, "display_name": "历史测试", "password": "test-pass-2026",
                "accepted_terms": True, "accepted_privacy": True,
            })
            self.assertEqual(response.status_code, 201)
        self.user = self.client.get("/api/auth/me").json()["user"]
        self.first = self.client.post("/api/agent/conversations", json={"title": "早期对话"}).json()
        self.second = self.client.post("/api/agent/conversations", json={"title": "最新对话"}).json()
        self.path = f'/api/agent/conversations/{self.first["conversation_id"]}'

    def tearDown(self):
        self.client.close()
        self.other.close()
        self.anonymous.close()
        application.DATABASE_PATH = self.original_database
        self.temporary.cleanup()

    def listing(self):
        return self.client.get("/api/agent/conversations").json()["items"]

    def test_pin_persists_is_idempotent_and_unpin_restores_recency(self):
        self.assertEqual(self.listing()[0]["conversation_id"], self.second["conversation_id"])
        result = self.client.put(self.path + "/pin", json={"pinned": True})
        self.assertEqual(result.status_code, 200)
        pinned_at = result.json()["pinned_at"]
        self.assertTrue(pinned_at)
        self.assertEqual(self.client.put(self.path + "/pin", json={"pinned": True}).json()["pinned_at"], pinned_at)
        self.assertEqual(self.listing()[0]["conversation_id"], self.first["conversation_id"])
        self.assertEqual(self.client.get(self.path).json()["last_message_at"], self.first["last_message_at"])
        self.client.post("/api/auth/logout")
        self.client.post("/api/auth/login", json={"email": "history@example.com", "password": "test-pass-2026"})
        self.assertEqual(self.listing()[0]["pinned_at"], pinned_at)
        self.assertIsNone(self.client.put(self.path + "/pin", json={"pinned": False}).json()["pinned_at"])
        self.assertEqual(self.listing()[0]["conversation_id"], self.second["conversation_id"])
        with connect(application.DATABASE_PATH) as connection:
            events = [row[0] for row in connection.execute("SELECT event_type FROM agent_audit_events")]
        self.assertEqual(events.count("CONVERSATION_PINNED"), 1)
        self.assertEqual(events.count("CONVERSATION_UNPINNED"), 1)

    def test_anonymous_other_accounts_and_unknown_conversations_are_rejected(self):
        for client, status in [(self.anonymous, 401), (self.other, 404)]:
            self.assertEqual(client.put(self.path + "/pin", json={"pinned": True}).status_code, status)
            self.assertEqual(client.post(self.path + "/export", json={"purpose": "share"}).status_code, status)
        self.assertEqual(self.client.put("/api/agent/conversations/CONV-MISSING/pin", json={"pinned": True}).status_code, 404)
        self.assertEqual(self.client.post("/api/agent/conversations/CONV-MISSING/export", json={"purpose": "copy"}).status_code, 404)
        self.assertTrue(all(item["pinned_at"] is None for item in self.listing()))

    def test_untrusted_origins_and_invalid_payloads_rejected(self):
        headers = {"Origin": "https://untrusted.example"}
        self.assertEqual(self.client.put(self.path + "/pin", json={"pinned": True}, headers=headers).status_code, 403)
        self.assertEqual(self.client.post(self.path + "/export", json={"purpose": "copy"}, headers=headers).status_code, 403)
        for value in [{}, {"pinned": "false"}, {"pinned": 1}, {"pinned": True, "user_id": "other"}]:
            self.assertEqual(self.client.put(self.path + "/pin", json=value).status_code, 422)
        self.assertEqual(self.client.post(self.path + "/export", json={"purpose": "publish"}).status_code, 422)
        self.assertEqual(self.client.put(self.path + "/pin", json={"pinned": True}, headers={"Origin": "http://127.0.0.1:3000"}).status_code, 200)

    def test_export_uses_selected_conversation_keeps_safety_and_filters_private_fields(self):
        with connect(application.DATABASE_PATH) as connection:
            connection.execute("UPDATE agent_conversations SET title = ? WHERE conversation_id = ?",
                               ("联系history@example.com 13800138000", self.first["conversation_id"]))
            connection.execute(
                """INSERT INTO agent_messages (message_id,conversation_id,user_id,role,content,
                   support_level,risk_level,response_json,safety_json,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                ("MSG-HISTORY", self.first["conversation_id"], self.user["user_id"], "assistant",
                 "样例内容 联系history@example.com 姓名：张三 CT-SECRET sk-abcdef1234567890",
                 "PARTIALLY_SUPPORTED", "MEDIUM", json.dumps({"uncertainty": ["证据有限，请复核"]}),
                 '{"internal":"private audit detail"}', "2026-08-30"),
            )
            connection.execute(
                """INSERT INTO agent_message_citations
                   (message_id,citation_id,source_id,ordinal,title,excerpt,locator,page_number,verified)
                   VALUES ('MSG-HISTORY','E1','PRIVATE-SOURCE',0,'论文','证据摘录','C:/private/paper.pdf',12,1)"""
            )
        for purpose in ["share", "copy"]:
            response = self.client.post(self.path + "/export", json={"purpose": purpose})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["cache-control"], "no-store")
            result = response.json()
            self.assertEqual(set(result), {"title", "text", "filename"})
            text = result["text"]
            for expected in ["样例内容", "证据有限", "部分支持", "风险等级：中", "证据摘录", "第12页", "已核验", "不构成诊断"]:
                self.assertIn(expected, text)
            for private in ["history@example.com", "13800138000", "张三", "CT-SECRET", "sk-abcdef", "PRIVATE-SOURCE", "C:/private", "private audit detail", self.user["user_id"], "最新对话"]:
                self.assertNotIn(private, text)
        with connect(application.DATABASE_PATH) as connection:
            audits = connection.execute("SELECT details_json FROM agent_audit_events WHERE event_type = 'CONVERSATION_EXPORT_PREPARED'").fetchall()
        self.assertEqual([json.loads(row[0])["purpose"] for row in audits], ["share", "copy"])

    def test_empty_conversation_can_be_exported_without_public_link(self):
        result = self.client.post(self.path + "/export", json={"purpose": "share"}).json()
        self.assertIn("暂无问答内容", result["text"])
        self.assertNotIn("http", result["text"])

    def test_inactive_conversation_cannot_be_pinned_or_exported(self):
        with connect(application.DATABASE_PATH) as connection:
            connection.execute("UPDATE agent_conversations SET status = 'ARCHIVED' WHERE conversation_id = ?", (self.first["conversation_id"],))
        self.assertEqual(self.client.put(self.path + "/pin", json={"pinned": True}).status_code, 404)
        self.assertEqual(self.client.post(self.path + "/export", json={"purpose": "share"}).status_code, 404)

    def test_additive_migration_preserves_old_rows_and_can_run_twice(self):
        legacy = Path(self.temporary.name) / "legacy.sqlite3"
        with closing(sqlite3.connect(legacy)) as connection:
            connection.executescript("""
                CREATE TABLE agent_conversations (
                  conversation_id TEXT PRIMARY KEY, user_id TEXT, title TEXT, linked_task_id TEXT,
                  status TEXT DEFAULT 'ACTIVE', created_at TEXT, updated_at TEXT, last_message_at TEXT
                );
                INSERT INTO agent_conversations VALUES ('OLD','USER','原有记录',NULL,'ACTIVE','2026','2026','2026');
            """)
        initialize_agent_schema(legacy)
        initialize_agent_schema(legacy)
        with connect(legacy) as connection:
            row = connection.execute("SELECT * FROM agent_conversations").fetchone()
            self.assertEqual(row["title"], "原有记录")
            self.assertIsNone(row["pinned_at"])

    def test_delete_hides_only_selected_record_and_preserves_usage_and_audit(self):
        self.client.put(self.path + "/pin", json={"pinned": True})
        with connect(application.DATABASE_PATH) as connection:
            connection.execute(
                """INSERT INTO agent_messages(message_id,conversation_id,user_id,role,content,created_at)
                   VALUES ('MSG-DELETE',?,?,'assistant','保存的回答','2026-08-30')""",
                (self.first["conversation_id"], self.user["user_id"]),
            )
            connection.execute(
                """INSERT INTO agent_usage_records(usage_id,user_id,conversation_id,message_id,provider,model,
                   input_tokens,output_tokens,total_tokens,created_at)
                   VALUES ('USE-DELETE',?,?,'MSG-DELETE','mock','mock',20,30,50,'2026-08-30')""",
                (self.user["user_id"], self.first["conversation_id"]),
            )
        usage_before = self.client.get("/api/agent/usage").json()
        result = self.client.delete(self.path, headers={"Origin": "http://127.0.0.1:3000"})
        self.assertEqual(result.status_code, 204)
        self.assertEqual(result.content, b"")
        self.assertEqual([row["conversation_id"] for row in self.listing()], [self.second["conversation_id"]])
        self.assertEqual(self.client.get(self.path).status_code, 404)
        self.assertEqual(self.client.put(self.path + "/pin", json={"pinned": True}).status_code, 404)
        self.assertEqual(self.client.post(self.path + "/export", json={"purpose": "copy"}).status_code, 404)
        self.assertEqual(self.client.post("/api/agent/chat", json={"conversation_id": self.first["conversation_id"], "question": "请确诊这个患者"}).status_code, 404)
        self.assertEqual(self.client.get("/api/agent/usage").json(), usage_before)
        self.assertEqual(self.client.delete(self.path).status_code, 204)
        with connect(application.DATABASE_PATH) as connection:
            record = connection.execute("SELECT status,pinned_at FROM agent_conversations WHERE conversation_id = ?", (self.first["conversation_id"],)).fetchone()
            self.assertEqual(record["status"], "DELETED")
            self.assertIsNone(record["pinned_at"])
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM agent_messages WHERE message_id = 'MSG-DELETE'").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM agent_audit_events WHERE event_type = 'CONVERSATION_DELETED'").fetchone()[0], 1)
        self.client.post("/api/auth/logout")
        self.client.post("/api/auth/login", json={"email": "history@example.com", "password": "test-pass-2026"})
        self.assertNotIn(self.first["conversation_id"], [row["conversation_id"] for row in self.listing()])

    def test_delete_rejects_anonymous_cross_account_unknown_and_untrusted_origin(self):
        self.assertEqual(self.anonymous.delete(self.path).status_code, 401)
        self.assertEqual(self.other.delete(self.path).status_code, 404)
        self.assertEqual(self.client.delete("/api/agent/conversations/CONV-MISSING").status_code, 404)
        self.assertEqual(self.client.delete(self.path, headers={"Origin": "https://untrusted.example"}).status_code, 403)
        self.assertEqual(self.client.get(self.path).status_code, 200)
        self.client.delete(self.path)
        self.assertEqual(self.other.delete(self.path).status_code, 404)


if __name__ == "__main__":
    unittest.main()
