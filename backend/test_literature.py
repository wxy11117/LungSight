"""Isolated literature + RAG tests. No network, model key or real account used."""
import json
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

import app as application
import literature
import test_agent
from agent_service import MockLLMProvider, run_agent_chat, get_conversation
from knowledge import connect, knowledge_sources, retrieve_evidence


def paper(**overrides):
    return {"id": "12345678", "pmid": "12345678", "source": "MED", "title": "Lung adenocarcinoma CT morphology",
            "firstPublicationDate": "2024-01-01", "abstractText": "<p>" + "Evidence " * 80 + "</p>",
            "journalInfo": {"journal": {"title": "Synthetic research journal"}},
            "pubTypeList": {"pubType": ["Journal Article"]}, **overrides}


def response_for(record=None):
    return {"resultList": {"result": [record or paper()]}, "hitCount": 1}


class LibraryTests(unittest.TestCase):
    setUp = test_agent.AgentPipelineTests.setUp
    tearDown = test_agent.AgentPipelineTests.tearDown

    def seed(self):
        return literature.seed_medical_library(self.database_path)

    def import_one(self, record=None, user_id=None):
        literature.initialize_literature_schema(self.database_path)
        with patch.object(literature, "_fetch", return_value=response_for(record)):
            return literature.import_literature(self.database_path, pmid="12345678", topic="adenocarcinoma", user_id=user_id or self.user["user_id"])

    def enable(self, source_id, **overrides):
        values = {"source_id": source_id, "user_id": self.user["user_id"], "enabled": True, "acknowledged": True,
                  "note": "肺腺癌CT形态研究的合成测试笔记 reviewedlungnote，病理与CT并不等价，不能代替病理确诊。"}
        return literature.review_literature(self.database_path, **{**values, **overrides})

    def test_additive_idempotent_seed_and_disabled_indexes(self):
        self.assertEqual(self.seed()["active"], 11)
        before = knowledge_sources(self.database_path)
        with connect(self.database_path) as connection:
            chunks = [tuple(row) for row in connection.execute("SELECT * FROM evidence_chunks ORDER BY chunk_id")]
        self.seed()
        self.assertEqual(knowledge_sources(self.database_path), before)
        with connect(self.database_path) as connection:
            self.assertEqual([tuple(row) for row in connection.execute("SELECT * FROM evidence_chunks ORDER BY chunk_id")], chunks)
        self.assertEqual(before["counts"]["sources"], 16)  # 15 new + retained project fixture
        self.assertEqual(before["counts"]["active_sources"], 12)
        data = retrieve_evidence(self.database_path, question="TCIA NSCLC CPTAC CT数据集", limit=50)["evidence"]
        self.assertNotIn("DATASET_INDEX", {item["source_type"] for item in data})

    def test_morphology_and_clinical_queries_have_relevant_sources(self):
        self.seed()
        cases = [
            ("腺癌细胞形态有哪些特征", "38736711"),
            ("鳞癌细胞角化和细胞间桥的病理特征", "38736711"),
            ("大细胞癌的病理重分类", "29246019"),
            ("腺癌鳞癌的CT空洞壁厚度有什么区别", "27394062"),
            ("肺癌CT放射组学分型与批次效应", "36980475"),
            ("正常肺部预测和肺癌筛查", "41565348"),
        ]
        for query, pmid in cases:
            with self.subTest(query=query):
                evidence = retrieve_evidence(self.database_path, question=query)["evidence"]
                self.assertIn(pmid, [item["source_metadata"].get("pmid") for item in evidence])
                self.assertEqual(evidence[0]["source_type"], "MEDICAL_NOTE")
                self.assertIn("非原文", evidence[0]["excerpt"])
                self.assertIn("适用限制", evidence[0]["excerpt"])

    def test_treatment_prefers_professional_summary_and_project_still_works(self):
        self.seed()
        evidence = retrieve_evidence(self.database_path, question="肺癌靶向治疗和免疫治疗的一般原则")["evidence"]
        self.assertIn("cancer.gov", evidence[0]["locator"])
        self.assertEqual(retrieve_evidence(self.database_path, question="为什么最终选择ResNet18？")["evidence"][0]["source_id"], "SRC-1")

    def test_curated_content_not_fulltext_or_cell_diagnosis(self):
        self.seed()
        rows = knowledge_sources(self.database_path)["items"]
        who = next(item for item in rows if item["metadata"].get("pmid") == "38736711")
        content = literature.literature_content(self.database_path, who["source_id"])
        self.assertIn("不是原文", content)
        self.assertIn("显微镜", content)
        self.assertIn("不会训练", content)
        self.assertEqual(literature.literature_content(self.database_path, "SRC-1"), None)

    def test_import_disabled_until_review_then_available_to_mock_rag(self):
        item = self.import_one()
        result = retrieve_evidence(self.database_path, question="肺腺癌形态")["evidence"]
        self.assertNotIn(item["source_id"], [entry["source_id"] for entry in result])
        self.enable(item["source_id"])
        result = run_agent_chat(self.database_path, user_id=self.user["user_id"], question="请解释 reviewedlungnote",
                                provider=MockLLMProvider(), mode="medical_general")
        self.assertIn(item["source_id"], [entry["source_id"] for entry in result["citations"]])
        self.assertNotIn("owner_user_id", json.dumps(result["citations"]))
        self.assertIn("非原文或临床审定", json.dumps(result, ensure_ascii=False))
        self.enable(item["source_id"], enabled=False)
        self.assertNotIn(item["source_id"], [entry["source_id"] for entry in retrieve_evidence(self.database_path, question="肺腺癌形态")["evidence"]])

    def test_review_requires_owner_ack_original_note_and_no_retraction(self):
        item = self.import_one()
        with self.assertRaises(PermissionError): self.enable(item["source_id"], user_id="someone-else")
        with self.assertRaises(ValueError): self.enable(item["source_id"], acknowledged=False)
        with self.assertRaises(ValueError): self.enable(item["source_id"], note="太短")
        with self.assertRaises(ValueError): self.enable(item["source_id"], note="字" * 2001)
        with self.assertRaises(PermissionError): self.enable("SRC-1")
        self.import_one(paper(pubTypeList={"pubType": ["Retracted Publication"]}))
        with self.assertRaises(ValueError): self.enable(item["source_id"])

    def test_upstream_unchanged_preserves_review_change_invalidates_and_audits(self):
        item = self.import_one()
        self.enable(item["source_id"])
        self.assertEqual(self.import_one()["status"], "unchanged")
        self.assertTrue(next(row for row in knowledge_sources(self.database_path)["items"] if row["source_id"] == item["source_id"])["retrieval_enabled"])
        self.import_one(paper(title="Corrected lung adenocarcinoma CT morphology"))
        row = next(row for row in knowledge_sources(self.database_path)["items"] if row["source_id"] == item["source_id"])
        self.assertFalse(row["retrieval_enabled"])
        self.assertEqual(row["metadata"]["review_status"], "PENDING")
        self.assertTrue(row["metadata"]["previous_note"])
        with connect(self.database_path) as connection:
            events = [row[0] for row in connection.execute("SELECT event_type FROM literature_events")]
        self.assertEqual(events, ["IMPORTED_PENDING", "RETRIEVAL_ENABLED", "UPSTREAM_CHECKED", "IMPORT_UPDATED"])

    def test_second_user_cannot_overwrite_shared_source(self):
        item = self.import_one()
        self.enable(item["source_id"])
        result = self.import_one(paper(title="Attempt overwrite"), user_id="other-account")
        self.assertEqual(result["status"], "existing")
        self.assertNotIn("Attempt overwrite", literature.literature_content(self.database_path, item["source_id"]))

    def test_offline_seed_never_makes_http_or_model_calls(self):
        with patch.object(literature.httpx, "get", side_effect=AssertionError("No network allowed")):
            self.seed()
            provider = MockLLMProvider()
            result = run_agent_chat(self.database_path, user_id=self.user["user_id"], question="腺癌细胞形态特征", provider=provider, mode="medical_general")
            self.assertTrue(any(card["source_type"] == "MEDICAL_NOTE" for card in result["citations"]))
            history = get_conversation(self.database_path, user_id=self.user["user_id"], conversation_id=result["conversation_id"])
            self.assertTrue(all(card["verified"] for card in history["messages"][-1]["citations"]))


class ConnectorTests(unittest.TestCase):
    def test_fixed_https_service_preset_no_patient_text_and_short_excerpt(self):
        response = httpx.Response(200, json=response_for(), request=httpx.Request("GET", literature.API_URL))
        with patch.object(literature.httpx, "get", return_value=response) as network:
            result = literature.search_literature(topic="adenocarcinoma", since=2020)
        args, kwargs = network.call_args
        self.assertEqual(args[0], literature.API_URL)
        self.assertFalse(kwargs["follow_redirects"])
        self.assertEqual(set(kwargs["params"]), {"query", "format", "resultType", "pageSize"})
        self.assertNotIn("Cookie", kwargs["headers"])
        self.assertLessEqual(len(result["items"][0]["abstract_preview"].split()), 25)
        self.assertNotIn("<p>", result["items"][0]["abstract_preview"])
        self.assertEqual(result["items"][0]["url"], "https://pubmed.ncbi.nlm.nih.gov/12345678/")

    def test_invalid_input_is_rejected_before_any_network(self):
        with patch.object(literature.httpx, "get") as network:
            for topic, since in [("姓名张三13800138000", 2020), ("treatment", 1999), ("treatment", 2999)]:
                with self.assertRaises(ValueError): literature.search_literature(topic=topic, since=since)
            with self.assertRaises(ValueError): literature.import_literature(None, pmid="http://127.0.0.1", topic="treatment", user_id="test")
            network.assert_not_called()

    def test_timeout_http_errors_malformed_and_redirect_fail_closed(self):
        payloads = [httpx.Response(503), httpx.Response(302, headers={"Location": "http://private/"}),
                    httpx.Response(200, text="not json"), httpx.Response(200, json={"resultList": None}),
                    httpx.Response(200, json={"resultList": {"result": ["bad"]}}),
                    httpx.Response(200, content=b"x" * 2_000_001)]
        for response in payloads:
            response.request = httpx.Request("GET", literature.API_URL)
            with self.subTest(status=response.status_code), patch.object(literature.httpx, "get", return_value=response):
                with self.assertRaises(literature.LiteratureUnavailable): literature.search_literature(topic="treatment")
        with patch.object(literature.httpx, "get", side_effect=httpx.ReadTimeout("timeout")):
            with self.assertRaises(literature.LiteratureUnavailable): literature.search_literature(topic="prediction")

    def test_record_filters_metadata_and_detects_warning_flags(self):
        self.assertTrue(literature._record(paper(pubTypeList={"pubType": ["Preprint"]}))["preprint"])
        self.assertTrue(literature._record(paper(commentCorrectionList={"commentCorrection": [{"type": "Expression of Concern"}]}))["retracted"])
        with self.assertRaises(ValueError): literature._record(paper(source="OTHER"))
        self.assertEqual(literature._record(paper(journalInfo=None))["journal"], "")


class LibraryApiTests(LibraryTests):
    def setUp(self):
        super().setUp()
        self.seed()
        self.client = TestClient(application.app)
        self.client.post("/api/auth/login", json={"email": "agent@example.com", "password": "secure-pass-2026"})

    def tearDown(self):
        self.client.close()
        super().tearDown()

    def test_authenticated_import_review_and_contents(self):
        with patch.object(literature, "_fetch", return_value=response_for()):
            searched = self.client.get("/api/evidence/online/search?topic=adenocarcinoma")
            self.assertEqual(searched.status_code, 200, searched.text)
            imported = self.client.post("/api/evidence/online/import", json={"pmid": "12345678", "topic": "adenocarcinoma"})
        self.assertEqual(imported.status_code, 200, imported.text)
        source_id = imported.json()["source_id"]
        row = next(item for item in self.client.get("/api/evidence/sources").json()["items"] if item["source_id"] == source_id)
        self.assertTrue(row["can_review"])
        self.assertNotIn("owner_user_id", row["metadata"])
        self.assertFalse(row["retrieval_enabled"])
        review = self.client.put(f"/api/evidence/sources/{source_id}/review", json={"enabled": True, "acknowledged": True, "note": "腺癌细胞形态与CT征象的合成测试笔记，仅测试使用，并非医学证据。"})
        self.assertEqual(review.status_code, 200, review.text)
        content = self.client.get(f"/api/evidence/sources/{source_id}/content")
        self.assertIn("不是原文", content.text)
        self.assertIn("no-store", content.headers["cache-control"])

    def test_auth_origin_and_schema_boundaries(self):
        with patch.object(literature, "_fetch") as network:
            rejected = self.client.post("/api/evidence/online/import", headers={"Origin": "https://evil.example"}, json={"pmid": "12345678", "topic": "treatment"})
            self.assertEqual(rejected.status_code, 403)
            self.assertEqual(self.client.post("/api/evidence/online/import", json={"pmid": "12345678", "topic": "treatment", "url": "http://private/"}).status_code, 422)
            self.client.cookies.clear()
            self.assertEqual(self.client.get("/api/evidence/online/topics").status_code, 401)
            self.assertEqual(self.client.get("/api/evidence/online/search?topic=treatment").status_code, 401)
            self.assertEqual(self.client.get("/api/evidence/sources").status_code, 401)
            self.assertEqual(self.client.post("/api/evidence/online/import", json={"pmid": "12345678", "topic": "treatment"}).status_code, 401)
            network.assert_not_called()

    def test_upstream_error_does_not_break_local_sources(self):
        with patch.object(literature, "_fetch", side_effect=literature.LiteratureUnavailable("暂时无法连接")):
            self.assertEqual(self.client.get("/api/evidence/online/search?topic=treatment").status_code, 503)
        self.assertEqual(self.client.get("/api/evidence/sources").status_code, 200)


if __name__ == "__main__":
    unittest.main()
