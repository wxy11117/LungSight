"""Display cleanup, hidden internal sources and unchanged title-named PDFs."""
import hashlib
import json
import re
import unittest
from urllib.parse import unquote
from unittest.mock import patch

from fastapi.testclient import TestClient
import app as application
import test_agent
from knowledge import connect, knowledge_sources, retrieve_evidence
from public_content import ARTICLE_TITLE, apply_library_presentation, pdf_download_name, public_payload, public_text


class PublicContentTests(unittest.TestCase):
    setUp = test_agent.AgentPipelineTests.setUp
    tearDown = test_agent.AgentPipelineTests.tearDown

    def client(self):
        client = TestClient(application.app)
        client.post('/api/auth/login', json={'email': 'agent@example.com', 'password': 'secure-pass-2026'})
        return client

    def test_normalizes_display_without_changing_identifiers_or_numbers(self):
        result = public_payload({'title': '竞赛程序包说明', 'version': 'apmcm-2026-fivefold', 'score': .9066,
                                 'source_id': 'APMCM-stable-id', 'sha256': 'stablehash', 'doi': '10.abc/APMCM'})
        self.assertEqual(result['title'], '模型推理程序说明')
        self.assertEqual(result['source_id'], 'APMCM-stable-id')
        self.assertEqual(result['doi'], '10.abc/APMCM')
        self.assertEqual(result['score'], .9066)
        self.assertEqual(public_text('APMCM-B-2610268.pdf'), ARTICLE_TITLE + '.pdf')
        self.assertNotRegex(pdf_download_name('某标题<>:/\\?*'), r'[<>:"/\\|?*]')

    def test_hidden_assignment_remains_in_db_but_not_library_retrieval_or_download(self):
        with connect(self.database_path) as connection:
            connection.execute("UPDATE evidence_sources SET authority='竞赛题目',locator='B题/内部说明.pdf' WHERE source_id='SRC-1'")
        apply_library_presentation(self.database_path)
        self.assertEqual(knowledge_sources(self.database_path)['counts']['sources'], 0)
        self.assertFalse(retrieve_evidence(self.database_path, question='ResNet18')['evidence'])
        with connect(self.database_path) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM evidence_sources').fetchone()[0], 1)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM evidence_chunks').fetchone()[0], 1)
        with self.client() as client:
            self.assertEqual(client.get('/api/evidence/sources/SRC-1/content').status_code, 404)

    def test_pdf_filename_uses_article_title_and_bytes_remain_identical(self):
        # Read-only check against the actual paper. No modified PDF is created.
        original = application.WORKSPACE_ROOT / (ARTICLE_TITLE + '.pdf')
        with connect(self.database_path) as connection:
            connection.execute("UPDATE evidence_sources SET title=?,locator=?,source_type='PDF' WHERE source_id='SRC-1'",
                               (ARTICLE_TITLE, original.name))
        with self.client() as client:
            response = client.get('/api/evidence/sources/SRC-1/content')
        self.assertEqual(response.status_code, 200)
        filename = unquote(response.headers['content-disposition'])
        self.assertIn(ARTICLE_TITLE + '.pdf', filename)
        self.assertNotIn('APMCM', filename)
        self.assertEqual(hashlib.sha256(response.content).digest(), hashlib.sha256(original.read_bytes()).digest())

    def test_legacy_json_and_stream_display_clean_but_stored_history_unchanged(self):
        provider = test_agent.MockLLMProvider()
        with self.client() as client, patch.object(application, 'load_agent_provider', return_value=provider):
            response = client.post('/api/agent/chat/stream', json={'question': '为什么最终选择ResNet18？'})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertNotRegex(response.text, r'竞赛|(?i:apmcm)')
            lines = [json.loads(line) for line in response.text.splitlines()]
            result = lines[-1]['result']
            self.assertEqual(''.join(line['delta'] for line in lines if line['type'] == 'delta'), result['answer'])
            with connect(self.database_path) as connection:
                connection.execute("UPDATE agent_conversations SET title='APMCM竞赛模型解释' WHERE conversation_id=?", (result['conversation_id'],))
            self.assertNotRegex(client.get('/api/agent/conversations').text, r'竞赛|(?i:apmcm)')
            with connect(self.database_path) as connection:
                self.assertIn('APMCM', connection.execute('SELECT title FROM agent_conversations').fetchone()[0])
            self.assertNotRegex(client.get('/api/evidence/sources').text, r'竞赛|(?i:apmcm)')


if __name__ == '__main__':
    unittest.main()
