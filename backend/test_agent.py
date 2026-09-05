from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import app as application
from auth_test_helpers import registration_fields
from agent_service import (
    MockLLMProvider,
    deidentify,
    get_conversation,
    initialize_agent_schema,
    run_agent_chat,
    usage_summary,
)
from auth import initialize_auth_schema, register_user
from knowledge import initialize_knowledge_schema, retrieve_evidence


class AgentPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database_path = self.root / "agent.sqlite3"
        self.original_database_path = application.DATABASE_PATH
        self.original_data_dir = application.DATA_DIR
        application.DATA_DIR = self.root
        application.DATABASE_PATH = self.database_path
        application.initialize_database()
        initialize_auth_schema(self.database_path)
        initialize_knowledge_schema(self.database_path)
        initialize_agent_schema(self.database_path)
        self.user = register_user(
            self.database_path, email="agent@example.com", display_name="Agent测试",
            password="secure-pass-2026", accepted_terms=True, accepted_privacy=True,
        )
        with application.database_connection() as connection:
            connection.execute(
                """INSERT INTO evidence_sources
                   (source_id,title,source_type,version,publication_date,authority,scope,locator,sha256,imported_at)
                   VALUES ('SRC-1','模型方法论文','pdf','1',NULL,'模型方法研究论文','二维CT研究排序','paper.pdf','abc','2026-01-01')"""
            )
            connection.execute(
                """INSERT INTO evidence_chunks
                   (source_id,chunk_index,section,page_number,content)
                   VALUES ('SRC-1',0,'模型选择',12,
                   '最终选择 ResNet18，是因为五折结果稳定并满足保守工程筛选规则。模型仅用于研究数据范围内的二维 CT 闭集排序，不能替代临床诊断。')"""
            )

    def tearDown(self) -> None:
        application.DATABASE_PATH = self.original_database_path
        application.DATA_DIR = self.original_data_dir
        self.temporary.cleanup()

    def test_general_retrieval_does_not_require_ct_task(self) -> None:
        result = retrieve_evidence(self.database_path, question="为什么最终选择ResNet18？")
        self.assertTrue(result["evidence"])
        self.assertEqual(result["evidence"][0]["source_id"], "SRC-1")

    def test_grounded_answer_persists_verified_citations_and_usage(self) -> None:
        provider = MockLLMProvider()
        result = run_agent_chat(
            self.database_path, user_id=self.user["user_id"],
            question="为什么最终选择ResNet18？", provider=provider,
        )
        self.assertEqual(result["support_level"], "PARTIALLY_SUPPORTED")
        self.assertEqual(len(result["citations"]), 1)
        self.assertTrue(provider.calls)
        conversation = get_conversation(
            self.database_path, user_id=self.user["user_id"],
            conversation_id=result["conversation_id"],
        )
        self.assertEqual(len(conversation["messages"]), 2)
        self.assertTrue(conversation["messages"][1]["citations"][0]["verified"])
        self.assertEqual(usage_summary(self.database_path, user_id=self.user["user_id"])["total_tokens"], 96)

    def test_high_risk_request_is_refused_without_provider_call(self) -> None:
        provider = MockLLMProvider()
        result = run_agent_chat(
            self.database_path, user_id=self.user["user_id"],
            question="请确诊这个患者并给出治疗方案", provider=provider,
        )
        self.assertEqual(result["support_level"], "REFUSED")
        self.assertEqual(result["risk_level"], "HIGH")
        self.assertEqual(provider.calls, [])

    def test_unsupported_question_does_not_call_provider(self) -> None:
        provider = MockLLMProvider()
        result = run_agent_chat(
            self.database_path, user_id=self.user["user_id"],
            question="知识库中2028年WHO指南新增了什么？", provider=provider,
        )
        self.assertEqual(result["support_level"], "INSUFFICIENT")
        self.assertEqual(provider.calls, [])

    def test_privacy_is_redacted_before_provider(self) -> None:
        provider = MockLLMProvider()
        result = run_agent_chat(
            self.database_path, user_id=self.user["user_id"],
            question="手机号13800138000，为什么最终选择ResNet18？", provider=provider,
        )
        self.assertNotIn("13800138000", provider.calls[0]["question"])
        self.assertIn("PHONE", result["privacy"]["redaction_types"])
        sanitized, privacy = deidentify("联系doctor@example.com或13800138000")
        self.assertNotIn("doctor@example.com", sanitized)
        self.assertEqual(set(privacy["redaction_types"]), {"EMAIL", "PHONE"})


class AgentApiTests(AgentPipelineTests):
    def setUp(self) -> None:
        super().setUp()
        self.original_loader = application.load_agent_provider
        self.provider = MockLLMProvider()
        application.load_agent_provider = lambda _user_id: self.provider
        self.client = TestClient(application.app)
        registered = self.client.post(
            "/api/auth/register",
            json={**registration_fields("secure-pass-2026"), "email":"api-agent@example.com","display_name":"API Agent",
                  "password":"secure-pass-2026","accepted_terms":True,"accepted_privacy":True},
        )
        self.assertEqual(registered.status_code, 201)

    def tearDown(self) -> None:
        self.client.close()
        application.load_agent_provider = self.original_loader
        super().tearDown()

    def test_stream_endpoint_emits_meta_deltas_and_done(self) -> None:
        response = self.client.post(
            "/api/agent/chat/stream", json={"question":"为什么最终选择ResNet18？"}
        )
        self.assertEqual(response.status_code, 200)
        events = [json.loads(line) for line in response.text.splitlines()]
        self.assertEqual(events[0]["type"], "meta")
        self.assertTrue(any(item["type"] == "delta" for item in events))
        self.assertEqual(events[-1]["type"], "done")
        conversations = self.client.get("/api/agent/conversations").json()["items"]
        self.assertEqual(len(conversations), 1)


if __name__ == "__main__":
    unittest.main()
