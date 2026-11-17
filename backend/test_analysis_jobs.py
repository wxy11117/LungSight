"""Isolated queue regression tests: no weights, network, or clinical records."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

from analysis_jobs import AnalysisQueue


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.calls = []

        def process(payload, name, owner, task_id, progress):
            self.calls.append(name)
            progress('INFERENCE')
            return {'task_id': task_id, 'file_name': name}

        self.queue = AnalysisQueue(Path(self.temp.name) / 'queue.sqlite3', process, lambda *_: 'SERIES-TEST')

    def tearDown(self):
        self.queue.stop()
        self.temp.cleanup()

    def submit(self, owner='owner'):
        return self.queue.submit(owner, 'Synthetic test', 'image', [
            {'file_name': name, 'payload': b'synthetic pixels'} for name in ['one.png', 'two.png', 'three.png']
        ])

    def test_partial_retry_keeps_successful_ids_and_removes_success_payloads(self):
        process = self.queue.processor
        fail = True

        def flaky(payload, name, owner, task_id, progress):
            if name == 'two.png' and fail:
                raise RuntimeError('secret-key-must-not-be-exposed')
            return process(payload, name, owner, task_id, progress)

        self.queue.processor = flaky
        job = self.submit()
        self.queue.process_one()
        partial = self.queue.get(job['job_id'], 'owner')
        self.assertEqual((partial['state'], partial['completed'], partial['failed']), ('PARTIAL', 2, 1))
        self.assertNotIn('secret-key', str(partial))
        successful_ids = {result['task_id'] for result in partial['results']}
        with self.queue.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM analysis_job_items WHERE payload IS NOT NULL').fetchone()[0], 1)
        fail = False
        self.queue.retry(job['job_id'], 'owner')
        self.queue.process_one()
        complete = self.queue.get(job['job_id'], 'owner')
        self.assertEqual((complete['state'], complete['completed']), ('SUCCEEDED', 3))
        self.assertTrue(successful_ids <= {result['task_id'] for result in complete['results']})
        self.assertCountEqual(self.calls, ['one.png', 'two.png', 'three.png'])
        self.assertFalse(any(item['retryable'] for item in complete['items']))

    def test_cancel_between_slices_then_resume_retains_first_result(self):
        process = self.queue.processor
        job = self.submit()

        def cancel_after_first(*args):
            result = process(*args)
            self.queue.cancel(job['job_id'], 'owner')
            return result

        self.queue.processor = cancel_after_first
        self.queue.process_one()
        stopped = self.queue.get(job['job_id'], 'owner')
        self.assertEqual((stopped['state'], stopped['completed']), ('CANCELLED', 1))
        self.assertEqual([i['state'] for i in stopped['items']], ['SUCCEEDED', 'CANCELLED', 'CANCELLED'])
        self.queue.processor = process
        self.queue.retry(job['job_id'], 'owner')
        self.queue.process_one()
        self.assertEqual(self.queue.get(job['job_id'], 'owner')['completed'], 3)
        self.assertEqual(self.calls.count('one.png'), 1)

    def test_restart_requires_explicit_resume_and_releases_running_item(self):
        job = self.submit()
        with self.queue.connection() as db:
            db.execute("UPDATE analysis_jobs SET state='RUNNING'")
            db.execute("UPDATE analysis_job_items SET state='RUNNING' WHERE ordinal=0")
        reopened = AnalysisQueue(self.queue.database, self.queue.processor, self.queue.finalize)
        reopened.recover()
        recovered = reopened.get(job['job_id'], 'owner')
        self.assertEqual(recovered['state'], 'INTERRUPTED')
        self.assertEqual(recovered['items'][0]['state'], 'READY')
        self.assertFalse(reopened.process_one())
        reopened.retry(job['job_id'], 'owner')
        self.assertTrue(reopened.process_one())
        self.assertEqual(reopened.get(job['job_id'], 'owner')['state'], 'SUCCEEDED')

    def test_owner_isolation_and_cancellation_of_queued_job(self):
        job = self.submit()
        for action in [self.queue.get, self.queue.cancel, self.queue.retry]:
            with self.assertRaises(KeyError):
                action(job['job_id'], 'another-owner')
        self.assertEqual(self.queue.list('another-owner'), [])
        self.queue.cancel(job['job_id'], 'owner')
        self.assertFalse(self.queue.process_one())
        self.assertEqual(self.calls, [])

    def test_finalization_retry_does_not_repeat_inference(self):
        self.queue.finalize = Mock(side_effect=[RuntimeError('disk failed'), 'SERIES-RETRY'])
        job = self.submit()
        self.queue.process_one()
        self.assertEqual(self.queue.get(job['job_id'], 'owner')['state'], 'FAILED')
        self.queue.retry(job['job_id'], 'owner')
        self.queue.process_one()
        final = self.queue.get(job['job_id'], 'owner')
        self.assertEqual((final['state'], final['series_id']), ('SUCCEEDED', 'SERIES-RETRY'))
        self.assertEqual(len(self.calls), 3)

    def test_invalid_inputs_are_terminal_and_need_reselection(self):
        job = self.queue.submit('owner', 'invalid', 'image', [{'file_name': 'broken.png', 'error': 'Unreadable image'}])
        self.queue.process_one()
        self.assertEqual(self.queue.get(job['job_id'], 'owner')['state'], 'FAILED')
        with self.assertRaises(ValueError):
            self.queue.retry(job['job_id'], 'owner')

    def test_stage_progress_is_readable_while_worker_is_busy(self):
        entered, release = threading.Event(), threading.Event()
        process = self.queue.processor

        def slow(*args):
            args[-1]('ATTENTION')
            entered.set()
            self.assertTrue(release.wait(3))
            return process(*args)

        self.queue.processor = slow
        job = self.submit()
        worker = threading.Thread(target=self.queue.process_one)
        worker.start()
        try:
            self.assertTrue(entered.wait(3))
            progress = self.queue.get(job['job_id'], 'owner')
            self.assertEqual((progress['state'], progress['items'][0]['stage']), ('RUNNING', 'ATTENTION'))
            self.queue.cancel(job['job_id'], 'owner')
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.queue.get(job['job_id'], 'owner')['state'], 'CANCELLED')

    def test_retry_obeys_per_owner_queue_limit(self):
        old = self.submit()
        self.queue.cancel(old['job_id'], 'owner')
        self.submit()
        self.submit()
        with self.assertRaises(ValueError):
            self.queue.retry(old['job_id'], 'owner')


if __name__ == '__main__':
    unittest.main()
