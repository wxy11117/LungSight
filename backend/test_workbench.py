"""Workbench HTTP integration with synthetic pixels and an explicit model double."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image, PngImagePlugin
from pydicom.uid import generate_uid

import app as api
from auth_test_helpers import registration_fields
from test_dicom_series import synthetic_ct
from workbench import normalize_image


def png_bytes(size=(96, 64)):
    output = io.BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text('PatientName', 'Synthetic metadata must be removed')
    Image.new('RGB', size, '#888888').save(output, format='PNG', pnginfo=metadata)
    return output.getvalue()


def prediction(_image):
    return {'top_index': 0, 'mean_probability': [.7, .1, .1, .1],
            'fold_probabilities': [[.7, .1, .1, .1]] * 5, 'fold_votes': [0] * 5,
            'fold_agreement': 5, 'top_two_margin': .6, 'reliability': 'STABLE',
            'warnings': [], 'thresholds': {}, 'decision': 'RESEARCH_RANKING', 'inference_ms': 1}


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.old = {key: getattr(api, key) for key in ['DATA_DIR', 'DATABASE_PATH', 'UPLOADS_DIR', 'ATTENTION_DIR']}
        api.DATA_DIR, api.DATABASE_PATH = root, root / 'workbench.sqlite3'
        api.UPLOADS_DIR, api.ATTENTION_DIR = root / 'uploads', root / 'attention'
        api.initialize_database()
        for initialize in [api.initialize_auth_schema, api.initialize_agent_schema, api.initialize_knowledge_schema]:
            initialize(api.DATABASE_PATH)
        self.client = TestClient(api.app)
        response = self.client.post('/api/auth/register', json={
            **registration_fields('synthetic-pass-2026'), 'email': 'workbench@example.com',
            'display_name': 'Synthetic test user', 'password': 'synthetic-pass-2026',
            'accepted_terms': True, 'accepted_privacy': True,
        })
        self.assertEqual(response.status_code, 201, response.text)
        self.owner = response.json()['user']['user_id']
        self.predict = patch.object(api.runtime, 'predict', side_effect=prediction).start()
        self.attention = patch.object(api.runtime, 'generate_attention_map', side_effect=lambda image, _: (image.copy(), 1)).start()
        self.queue = api.workbench.queue()

    def tearDown(self):
        self.queue.stop()
        self.client.close()
        patch.stopall()
        for name, value in self.old.items():
            setattr(api, name, value)
        self.temp.cleanup()

    def submit(self, count=1):
        response = self.client.post('/api/analysis-jobs', data={'case_name': 'Synthetic case', 'mode': 'image'},
                                    files=[('files', (f'slice-{i}.png', png_bytes(), 'image/png')) for i in range(count)])
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(self.predict.call_count, 0, 'submission must not run model inference')
        self.queue.process_one()
        return self.client.get('/api/analysis-jobs/' + response.json()['job_id']).json()

    def test_queue_persists_real_task_media_and_annotations_round_trip_into_report(self):
        job = self.submit()
        self.assertEqual(job['state'], 'SUCCEEDED')
        task_id = job['results'][0]['task_id']
        prefix = f'/api/tasks/{task_id}'
        self.assertEqual(self.client.get(prefix + '/image').status_code, 200)
        notes = {'revision': 0, 'items': [{'id': 'point-1', 'x': .25, 'y': .75, 'note': '人工 <script>alert(1)</script> 标记'}]}
        saved = self.client.put(prefix + '/annotations', json=notes)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()['revision'], 1)
        self.assertEqual(self.client.get(prefix + '/annotations').json()['items'], notes['items'])
        self.assertEqual(self.client.put(prefix + '/annotations', json=notes).status_code, 409)
        report = self.client.get(prefix + '/report')
        self.assertEqual(report.status_code, 200, report.text[:300])
        self.assertIn('人工影像标记', report.text)
        self.assertIn('25.0%', report.text)
        self.assertNotIn('<script>', report.text)
        self.assertIn('&lt;script&gt;', report.text)
        events = self.client.get(prefix + '/audit').json()['items']
        self.assertEqual(events[-1]['event_type'], 'ANNOTATIONS_UPDATED')
        self.assertEqual(self.client.get(prefix).json()['review'], None)

    def test_annotation_validation_and_account_isolation(self):
        job = self.submit()
        task_id = job['results'][0]['task_id']
        path = f'/api/tasks/{task_id}/annotations'
        point = {'id': 'one', 'x': .5, 'y': .5, 'note': 'Synthetic note'}
        for items in [[{**point, 'x': 1.1}], [point, point], [{**point, 'note': '   '}]]:
            self.assertEqual(self.client.put(path, json={'revision': 0, 'items': items}).status_code, 422)
        api.app.dependency_overrides[api.require_user] = lambda: {'user_id': 'other', 'display_name': 'Other test user'}
        try:
            self.assertEqual(self.client.get(path).status_code, 404)
            self.assertEqual(self.client.put(path, json={'revision': 0, 'items': [point]}).status_code, 404)
            self.assertEqual(self.client.get('/api/analysis-jobs/' + job['job_id']).status_code, 404)
            self.assertEqual(self.client.get('/api/analysis-jobs').json()['items'], [])
        finally:
            api.app.dependency_overrides.clear()

    def test_sequence_context_is_ordered_and_review_is_kept_separate(self):
        job = self.submit(3)
        self.assertEqual(job['state'], 'SUCCEEDED')
        first = job['results'][0]['task_id']
        context = self.client.get(f'/api/tasks/{first}/series-context').json()
        self.assertEqual(context['series_id'], job['series_id'])
        self.assertEqual([item['task_id'] for item in context['items']], [item['task_id'] for item in job['results']])
        series = self.client.get('/api/series/' + job['series_id']).json()
        self.assertEqual(series['prediction']['decision'], 'INDETERMINATE')
        review = {'decision': 'UNDETERMINED', 'reviewer_name': 'Synthetic reviewer', 'comment': 'Automated test only'}
        response = self.client.post(f'/api/tasks/{first}/review', json=review)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.post(f'/api/tasks/{first}/review', json=review).status_code, 409)

    def test_existing_task_reused_after_crash_before_queue_acknowledgement(self):
        job = self.submit()
        with self.queue.connection() as db:
            db.execute("UPDATE analysis_jobs SET state='RUNNING'")
            db.execute("UPDATE analysis_job_items SET state='RUNNING',result_json=NULL,payload=?", (png_bytes(),))
        self.queue.recover()
        self.queue.retry(job['job_id'], self.owner)
        self.queue.process_one()
        self.assertEqual(self.predict.call_count, 1)
        with api.database_connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM analysis_tasks').fetchone()[0], 1)

    def test_dicom_queue_keeps_only_derived_pixels_and_preserves_case_gate(self):
        uid = generate_uid()
        files = [('files', ('private-name.dcm', synthetic_ct(series_uid=uid, position=i, instance=i + 1), 'application/dicom')) for i in range(3)]
        refused = self.client.post('/api/analysis-jobs', data={'mode': 'dicom'}, files=files)
        self.assertEqual(refused.status_code, 422)
        response = self.client.post('/api/analysis-jobs', data={'mode': 'dicom', 'privacy_acknowledged': 'true'}, files=files)
        self.assertEqual(response.status_code, 202, response.text)
        with self.queue.connection() as db:
            for item in db.execute('SELECT payload,file_name FROM analysis_job_items'):
                self.assertTrue(item['payload'].startswith(b'\x89PNG'))
                self.assertNotIn('private-name', item['file_name'])
            metadata = db.execute('SELECT metadata_json FROM analysis_jobs').fetchone()[0]
            self.assertNotIn('Sensitive^Person', metadata)
            self.assertNotIn('PRIVATE-123', metadata)
        self.queue.process_one()
        done = self.client.get('/api/analysis-jobs/' + response.json()['job_id']).json()
        self.assertEqual(done['state'], 'SUCCEEDED')
        series = self.client.get('/api/series/' + done['series_id']).json()
        self.assertEqual(series['prediction']['decision'], 'INDETERMINATE')
        self.assertEqual(series['quality_gate']['status'], 'BLOCKED')
        self.assertFalse(series['dicom']['privacy']['original_dicom_persisted'])

    def test_decoding_removes_text_metadata_and_rejects_invalid_images(self):
        with Image.open(io.BytesIO(normalize_image(png_bytes()))) as decoded:
            self.assertNotIn('PatientName', decoded.info)
            self.assertEqual(decoded.size, (96, 64))
        for content in [b'not an image', png_bytes((20, 20))]:
            with self.assertRaises(ValueError):
                normalize_image(content)

    def test_permanent_task_delete_cleans_notes_and_queue_snapshot(self):
        job = self.submit()
        task_id = job['results'][0]['task_id']
        self.client.put(f'/api/tasks/{task_id}/annotations', json={'revision': 0, 'items': [
            {'id': 'point', 'x': .2, 'y': .3, 'note': 'Synthetic deletion test'}]})
        response = self.client.delete(f'/api/tasks/{task_id}')
        self.assertEqual(response.status_code, 200, response.text)
        snapshot = self.client.get('/api/analysis-jobs/' + job['job_id']).json()
        self.assertEqual(snapshot['results'], [])
        self.assertFalse(snapshot['items'][0]['retryable'])
        with self.queue.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM image_annotations').fetchone()[0], 0)

    def test_series_report_includes_annotation_on_non_representative_slice(self):
        job = self.submit(3)
        series = self.client.get('/api/series/' + job['series_id']).json()
        task_id = next(item['task_id'] for item in job['results'] if item['task_id'] != series['representative_slice']['task_id'])
        self.client.put(f'/api/tasks/{task_id}/annotations', json={'revision': 0, 'items': [
            {'id': 'point', 'x': .2, 'y': .3, 'note': 'Non-representative slice note'}]})
        response = self.client.get('/api/series/' + job['series_id'] + '/report')
        self.assertEqual(response.status_code, 200, response.text[:200])
        self.assertIn('Non-representative slice note', response.text)


if __name__ == '__main__':
    unittest.main()
