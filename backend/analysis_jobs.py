"""Durable, owner-scoped local analysis queue. Only normalized images are stored.

One worker processes slices in order. Restart recovery requires an explicit resume;
successful slices are never rerun. Cancellation is cooperative at stage boundaries.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class JobCancelled(Exception):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


class AnalysisQueue:
    def __init__(self, database: Path, processor, finalize):
        self.database = database
        self.processor = processor
        self.finalize = finalize
        self.wake = threading.Event()
        self.stopping = threading.Event()
        self.thread = None
        self.initialize()

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self):
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS analysis_jobs (
                    job_id TEXT PRIMARY KEY, owner_user_id TEXT NOT NULL,
                    case_name TEXT NOT NULL, mode TEXT NOT NULL, state TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL, series_id TEXT, error TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_owner ON analysis_jobs(owner_user_id, created_at);
                CREATE TABLE IF NOT EXISTS analysis_job_items (
                    job_id TEXT NOT NULL, ordinal INTEGER NOT NULL, file_name TEXT NOT NULL,
                    state TEXT NOT NULL, stage TEXT NOT NULL, payload BLOB,
                    task_id TEXT NOT NULL, result_json TEXT, error TEXT NOT NULL DEFAULT '',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(job_id, ordinal)
                );
            """)

    def recover(self):
        with self.connection() as db:
            db.execute("""UPDATE analysis_jobs SET state = 'INTERRUPTED', updated_at = ?,
                       error = '服务曾中断；已完成切片保留，可继续剩余任务。'
                       WHERE state IN ('QUEUED', 'RUNNING')""", (now(),))
            db.execute("UPDATE analysis_jobs SET state = 'CANCELLED' WHERE state = 'CANCELLING'")
            db.execute("UPDATE analysis_job_items SET state = 'READY', stage = 'WAITING' WHERE state = 'RUNNING'")

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stopping.clear()
        self.recover()
        self.thread = threading.Thread(target=self._loop, name='lungsight-analysis', daemon=True)
        self.thread.start()

    def stop(self):
        self.stopping.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=10)

    def submit(self, owner, case_name, mode, items, metadata=None):
        job_id = 'JOB-' + uuid.uuid4().hex[:16].upper()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            active = db.execute("SELECT COUNT(*) FROM analysis_jobs WHERE state IN ('QUEUED','RUNNING','CANCELLING')").fetchone()[0]
            own = db.execute("SELECT COUNT(*) FROM analysis_jobs WHERE owner_user_id = ? AND state IN ('QUEUED','RUNNING','CANCELLING')", (owner,)).fetchone()[0]
            if active >= 8 or own >= 2:
                raise ValueError('队列已满，请等待当前任务完成后再提交。')
            db.execute("INSERT INTO analysis_jobs(job_id,owner_user_id,case_name,mode,state,created_at,updated_at,metadata_json) VALUES (?,?,?,?,?,?,?,?)",
                       (job_id, owner, case_name, mode, 'QUEUED', now(), now(), json.dumps(metadata or {}, ensure_ascii=False)))
            for index, item in enumerate(items):
                error = item.get('error', '')
                db.execute("INSERT INTO analysis_job_items(job_id,ordinal,file_name,state,stage,payload,task_id,error) VALUES (?,?,?,?,?,?,?,?)",
                           (job_id, index, item['file_name'], 'FAILED' if error else 'READY', 'INVALID' if error else 'WAITING',
                            item.get('payload'), 'CT-' + uuid.uuid4().hex[:16].upper(), error))
        self.wake.set()
        return self.get(job_id, owner)

    def _owned(self, db, job_id, owner):
        row = db.execute('SELECT * FROM analysis_jobs WHERE job_id = ? AND owner_user_id = ?', (job_id, owner)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return row

    def get(self, job_id, owner):
        with self.connection() as db:
            job = dict(self._owned(db, job_id, owner))
            items = db.execute('SELECT ordinal,file_name,state,stage,task_id,result_json,error,attempts,payload IS NOT NULL AS retryable FROM analysis_job_items WHERE job_id = ? ORDER BY ordinal', (job_id,)).fetchall()
        results = []
        public_items = []
        for row in items:
            item = dict(row)
            result = item.pop('result_json')
            if result:
                results.append(json.loads(result))
            item['retryable'] = bool(item['retryable']) and item['state'] != 'SUCCEEDED'
            public_items.append(item)
        job.pop('metadata_json')
        job.pop('owner_user_id')
        job['items'] = public_items
        job['results'] = results
        job['total'] = len(items)
        job['completed'] = sum(row['state'] == 'SUCCEEDED' for row in items)
        job['failed'] = sum(row['state'] == 'FAILED' for row in items)
        return job

    def list(self, owner):
        with self.connection() as db:
            ids = [r[0] for r in db.execute("SELECT job_id FROM analysis_jobs WHERE owner_user_id = ? ORDER BY state IN ('QUEUED','RUNNING','CANCELLING','INTERRUPTED') DESC, created_at DESC LIMIT 20", (owner,))]
        return [self.get(job_id, owner) for job_id in ids]

    def cancel(self, job_id, owner):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = self._owned(db, job_id, owner)
            if row['state'] in {'QUEUED', 'RUNNING', 'CANCELLING'}:
                state = 'CANCELLED' if row['state'] == 'QUEUED' else 'CANCELLING'
                db.execute('UPDATE analysis_jobs SET cancel_requested = 1, state = ?, updated_at = ? WHERE job_id = ?', (state, now(), job_id))
                if state == 'CANCELLED':
                    db.execute("UPDATE analysis_job_items SET state = 'CANCELLED' WHERE job_id = ? AND state = 'READY'", (job_id,))
        return self.get(job_id, owner)

    def retry(self, job_id, owner):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            job = self._owned(db, job_id, owner)
            if job['state'] not in {'PARTIAL', 'FAILED', 'CANCELLED', 'INTERRUPTED'}:
                raise ValueError('当前任务不能重试。')
            if db.execute("SELECT COUNT(*) FROM analysis_jobs WHERE state IN ('QUEUED','RUNNING','CANCELLING')").fetchone()[0] >= 8:
                raise ValueError('队列已满，请稍后再试。')
            if db.execute("SELECT COUNT(*) FROM analysis_jobs WHERE owner_user_id = ? AND state IN ('QUEUED','RUNNING','CANCELLING')", (owner,)).fetchone()[0] >= 2:
                raise ValueError('当前账号已有两个任务，请稍后再试。')
            if not job['error'] and not db.execute("SELECT 1 FROM analysis_job_items WHERE job_id = ? AND state != 'SUCCEEDED' AND payload IS NOT NULL", (job_id,)).fetchone():
                raise ValueError('没有可重试的输入，请重新选择文件。')
            # Invalid input without retained normalized pixels needs reselection.
            db.execute("UPDATE analysis_job_items SET state = 'READY', stage = 'WAITING', error = '' WHERE job_id = ? AND state != 'SUCCEEDED' AND payload IS NOT NULL", (job_id,))
            # A finalization failure can be retried even with all slices complete.
            db.execute("UPDATE analysis_jobs SET state = 'QUEUED', cancel_requested = 0, series_id = NULL, error = '', updated_at = ? WHERE job_id = ?", (now(), job_id))
        self.wake.set()
        return self.get(job_id, owner)

    def process_one(self):
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM analysis_jobs WHERE state = 'QUEUED' ORDER BY created_at LIMIT 1").fetchone()
            if row is None:
                return False
            job = dict(row)
            db.execute("UPDATE analysis_jobs SET state = 'RUNNING', updated_at = ? WHERE job_id = ?", (now(), job['job_id']))
        job_id = job['job_id']
        while not self.stopping.is_set():
            with self.connection() as db:
                if db.execute('SELECT cancel_requested FROM analysis_jobs WHERE job_id = ?', (job_id,)).fetchone()[0]:
                    break
                item = db.execute("SELECT * FROM analysis_job_items WHERE job_id = ? AND state = 'READY' ORDER BY ordinal LIMIT 1", (job_id,)).fetchone()
                if item is None:
                    break
                item = dict(item)
                db.execute("UPDATE analysis_job_items SET state = 'RUNNING', attempts = attempts + 1 WHERE job_id = ? AND ordinal = ?", (job_id, item['ordinal']))

            def progress(stage):
                with self.connection() as db:
                    cancelled = db.execute('SELECT cancel_requested FROM analysis_jobs WHERE job_id = ?', (job_id,)).fetchone()[0]
                    if cancelled or self.stopping.is_set():
                        raise JobCancelled()
                    db.execute('UPDATE analysis_job_items SET stage = ? WHERE job_id = ? AND ordinal = ?', (stage, job_id, item['ordinal']))
                    db.execute('UPDATE analysis_jobs SET updated_at = ? WHERE job_id = ?', (now(), job_id))
            try:
                progress('READING')
                result = self.processor(item['payload'], item['file_name'], job['owner_user_id'], item['task_id'], progress)
                with self.connection() as db:
                    db.execute("UPDATE analysis_job_items SET state = 'SUCCEEDED', stage = 'DONE', result_json = ?, payload = NULL, error = '' WHERE job_id = ? AND ordinal = ?",
                               (json.dumps(result, ensure_ascii=False), job_id, item['ordinal']))
            except JobCancelled:
                with self.connection() as db:
                    db.execute("UPDATE analysis_job_items SET state = 'READY', stage = 'WAITING' WHERE job_id = ? AND ordinal = ?", (job_id, item['ordinal']))
                break
            except Exception:
                # Do not persist exception traces, local paths, or provider credentials.
                with self.connection() as db:
                    db.execute("UPDATE analysis_job_items SET state = 'FAILED', stage = 'FAILED', error = '分析未完成，请检查本地模型服务后重试。' WHERE job_id = ? AND ordinal = ?", (job_id, item['ordinal']))
        snapshot = self.get(job_id, job['owner_user_id'])
        state = ('INTERRUPTED' if self.stopping.is_set() else 'CANCELLED' if snapshot['cancel_requested'] else
                 'SUCCEEDED' if snapshot['completed'] == snapshot['total'] else 'PARTIAL' if snapshot['completed'] else 'FAILED')
        error = ''
        series_id = snapshot['series_id']
        if state != 'INTERRUPTED' and snapshot['results'] and not series_id:
            try:
                series_id = self.finalize(job, snapshot)
            except Exception:
                state, error = 'FAILED', '切片已保留，病例汇总保存失败，可重试完成归档。'
        with self.connection() as db:
            db.execute("UPDATE analysis_job_items SET state = 'CANCELLED' WHERE job_id = ? AND state = 'READY' AND ? = 'CANCELLED'", (job_id, state))
            db.execute('UPDATE analysis_jobs SET state = ?, series_id = ?, error = ?, updated_at = ? WHERE job_id = ?', (state, series_id, error, now(), job_id))
        return True

    def _loop(self):
        storage_failure = False
        while not self.stopping.is_set():
            try:
                if storage_failure:
                    # Recovery is explicit: do not silently rerun a possibly saved slice.
                    with self.connection() as db:
                        db.execute("UPDATE analysis_jobs SET state = 'INTERRUPTED', error = '本地存储曾不可用；请检查磁盘后继续任务。', updated_at = ? WHERE state IN ('RUNNING','CANCELLING')", (now(),))
                        db.execute("UPDATE analysis_job_items SET state = 'READY', stage = 'WAITING' WHERE state = 'RUNNING'")
                    storage_failure = False
                worked = self.process_one()
            except Exception:
                # A storage outage must not spin or silently kill the worker.
                storage_failure = True
                worked = False
            if not worked:
                self.wake.wait(1)
                self.wake.clear()
