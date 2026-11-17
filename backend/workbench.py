"""Authenticated workbench routes, annotations and local queue integration."""
from __future__ import annotations

import html
import io
import json
from pathlib import Path
from typing import Literal

from fastapi import Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from PIL import Image, ImageOps, UnidentifiedImageError

from analysis_jobs import AnalysisQueue, now


class PointNote(BaseModel):
    model_config = {'extra': 'forbid', 'allow_inf_nan': False}
    id: str = Field(pattern=r'^[a-zA-Z0-9-]{1,60}$')
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    note: str = Field(min_length=1, max_length=500)


class AnnotationUpdate(BaseModel):
    model_config = {'extra': 'forbid'}
    revision: int = Field(ge=0)
    items: list[PointNote] = Field(max_length=50)


def normalize_image(payload):
    """Decode only bounded images, remove metadata, normalize orientation."""
    try:
        with Image.open(io.BytesIO(payload)) as image:
            if min(image.size) < 64 or image.width * image.height > 20_000_000:
                raise ValueError('图片需至少64×64像素，且不超过2000万像素。')
            normalized = ImageOps.exif_transpose(image).convert('RGB')
            normalized.info.clear()
            output = io.BytesIO()
            normalized.save(output, format='PNG')
            return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError('文件不是可读取的二维图片，请重新选择。') from exc


class Workbench:
    def __init__(self, api):
        self.api = api
        self._queue = None
        self.install_routes()

    def queue(self):
        if self._queue is None or self._queue.database != self.api.DATABASE_PATH:
            self._queue = AnalysisQueue(self.api.DATABASE_PATH, self.process, self.finalize)
            with self._queue.connection() as db:
                db.execute('CREATE TABLE IF NOT EXISTS image_annotations (task_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, items_json TEXT NOT NULL, updated_at TEXT NOT NULL)')
        return self._queue

    def process(self, payload, filename, owner, task_id, progress):
        # Idempotency after a crash between saving a task and updating the queue.
        try:
            return self.api.row_to_task(self.api.get_task_row(task_id, owner))
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
        return self.api.analyze_image_payload(payload, filename, {'user_id': owner}, task_id=task_id, progress=progress)

    def finalize(self, job, snapshot):
        if job['mode'] == 'image' and snapshot['total'] == 1:
            return None
        metadata = json.loads(job['metadata_json'])
        failures = metadata.get('failures', []) + [
            {'file_name': item['file_name'], 'status_code': 422, 'detail': item['error'] or '该切片未完成分析'}
            for item in snapshot['items'] if item['state'] != 'SUCCEEDED'
        ]
        series = self.api.aggregate_series_results(snapshot['results'], case_name=job['case_name'], failures=failures,
                                                   case_aggregation_validated=False, input_mode='DICOM' if job['mode'] == 'dicom' else 'IMAGE_SERIES')
        if job['mode'] == 'dicom':
            self.api.complete_dicom_result(series, metadata['dicom'])
        self.api.persist_series(series, job['owner_user_id'])
        return series['series_id']

    def annotations(self, task_id, owner):
        self.api.get_task_row(task_id, owner)
        with self.queue().connection() as db:
            row = db.execute('SELECT * FROM image_annotations WHERE task_id = ?', (task_id,)).fetchone()
        return {'revision': row['revision'], 'items': json.loads(row['items_json'])} if row else {'revision': 0, 'items': []}

    def annotation_report(self, task_id, owner):
        notes = self.annotations(task_id, owner)['items']
        if not notes:
            return ''
        rows = ''.join(f'<li>标记 {i + 1}（横向 {n["x"]:.1%}，纵向 {n["y"]:.1%}）：{html.escape(n["note"])}</li>' for i, n in enumerate(notes))
        return '<h2>人工影像标记</h2><p>相对原图左上角的位置；研究备注，不是自动病灶定位。</p><ol>' + rows + '</ol>'

    def forget_task(self, db, task_id):
        active = db.execute("SELECT 1 FROM analysis_jobs j JOIN analysis_job_items i ON j.job_id=i.job_id WHERE i.task_id=? AND j.state IN ('QUEUED','RUNNING','CANCELLING')", (task_id,)).fetchone()
        if active:
            raise HTTPException(409, '该切片所属任务仍在处理，请先取消任务或等待完成后再删除。')
        db.execute('DELETE FROM image_annotations WHERE task_id=?', (task_id,))
        db.execute("UPDATE analysis_jobs SET series_id=NULL, state='PARTIAL' WHERE job_id IN (SELECT job_id FROM analysis_job_items WHERE task_id=?)", (task_id,))
        db.execute("UPDATE analysis_job_items SET result_json=NULL,payload=NULL,file_name='已删除切片',state='DELETED',stage='DELETED',error='' WHERE task_id=?", (task_id,))

    def install_routes(self):
        api = self.api
        app = api.app

        def queue_call(action, *args):
            try:
                return getattr(self.queue(), action)(*args)
            except KeyError as exc:
                raise HTTPException(404, '任务不存在') from exc
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc

        @app.get('/api/analysis-jobs')
        def list_jobs(user: dict = Depends(api.require_user)):
            return {'items': self.queue().list(user['user_id'])}

        @app.get('/api/analysis-jobs/{job_id}')
        def get_job(job_id: str, user: dict = Depends(api.require_user)):
            return queue_call('get', job_id, user['user_id'])

        @app.post('/api/analysis-jobs/{job_id}/cancel')
        def cancel_job(job_id: str, user: dict = Depends(api.require_user)):
            return queue_call('cancel', job_id, user['user_id'])

        @app.post('/api/analysis-jobs/{job_id}/retry')
        def retry_job(job_id: str, user: dict = Depends(api.require_user)):
            return queue_call('retry', job_id, user['user_id'])

        @app.post('/api/analysis-jobs', status_code=202)
        async def submit_job(files: list[UploadFile] = File(...), mode: Literal['image', 'dicom'] = Form('image'),
                             case_name: str = Form('未命名影像任务', max_length=120), privacy_acknowledged: bool = Form(False),
                             user: dict = Depends(api.require_user)):
            maximum = api.MAX_DICOM_FILES if mode == 'dicom' else api.MAX_SERIES_FILES
            if not 1 <= len(files) <= maximum:
                raise HTTPException(413, f'请选择1至{maximum}个文件。')
            if mode == 'dicom' and not privacy_acknowledged:
                raise HTTPException(422, '请先确认数据授权与像素隐私复核要求。')
            payloads, names, total = [], [], 0
            try:
                for upload in files:
                    payload = await upload.read(api.MAX_UPLOAD_BYTES + 1)
                    total += len(payload)
                    if len(payload) > api.MAX_UPLOAD_BYTES or total > api.MAX_DICOM_TOTAL_BYTES:
                        raise HTTPException(413, '单文件不能超过20MB，单批总大小不能超过256MB。')
                    payloads.append(payload)
                    names.append(Path(upload.filename or 'image').stem[:120] + '.png')
            finally:
                for upload in files:
                    await upload.close()
            metadata = {}
            if mode == 'dicom':
                try:
                    prepared, failures, summary = await run_in_threadpool(api.prepare_dicom_series, payloads, maximum_analysis_slices=api.DICOM_ANALYSIS_SLICES)
                except api.DicomImportError as exc:
                    raise HTTPException(422, str(exc)) from exc
                items = [{'file_name': item['file_name'], 'payload': item['payload']} for item in prepared]
                metadata = {'dicom': summary, 'failures': failures}
            else:
                items = []
                normalized_total = 0
                for payload, name in zip(payloads, names):
                    try:
                        clean = await run_in_threadpool(normalize_image, payload)
                        normalized_total += len(clean)
                        if normalized_total > api.MAX_DICOM_TOTAL_BYTES:
                            raise HTTPException(413, '规范化后的图片总量超过256MB，请减少本批文件。')
                        items.append({'file_name': name, 'payload': clean})
                    except ValueError as exc:
                        items.append({'file_name': name, 'error': str(exc)})
            if sum(len(item.get('payload', b'')) for item in items) > api.MAX_DICOM_TOTAL_BYTES:
                raise HTTPException(413, '规范化后的图片总量超过256MB，请减少本批文件。')
            return queue_call('submit', user['user_id'], case_name.strip() or '未命名影像任务', mode, items, metadata)

        @app.get('/api/tasks/{task_id}/annotations')
        def get_annotations(task_id: str, user: dict = Depends(api.require_user)):
            return self.annotations(task_id, user['user_id'])

        @app.put('/api/tasks/{task_id}/annotations')
        def save_annotations(task_id: str, request: AnnotationUpdate, user: dict = Depends(api.require_user)):
            task = api.get_task_row(task_id, user['user_id'])
            if len({item.id for item in request.items}) != len(request.items) or any(not item.note.strip() for item in request.items):
                raise HTTPException(422, '标记编号不可重复，备注不可为空。')
            with self.queue().connection() as db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT revision FROM image_annotations WHERE task_id = ?', (task_id,)).fetchone()
                revision = row[0] if row else 0
                if revision != request.revision:
                    raise HTTPException(409, '标记已在另一窗口更新，请重新载入后再编辑。')
                payload = json.dumps([item.model_dump() for item in request.items], ensure_ascii=False)
                db.execute('INSERT INTO image_annotations VALUES (?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET revision=excluded.revision,items_json=excluded.items_json,updated_at=excluded.updated_at',
                           (task_id, revision + 1, payload, now()))
                db.execute('INSERT INTO audit_events(task_id,event_type,from_status,to_status,actor,details_json,created_at) VALUES (?,?,?,?,?,?,?)',
                           (task_id, 'ANNOTATIONS_UPDATED', task['status'], task['status'], user['display_name'], json.dumps({'revision': revision + 1, 'count': len(request.items)}), now()))
            return {'revision': revision + 1, 'items': [item.model_dump() for item in request.items]}

        @app.get('/api/tasks/{task_id}/series-context')
        def task_series(task_id: str, user: dict = Depends(api.require_user)):
            api.get_task_row(task_id, user['user_id'])
            with api.database_connection() as db:
                row = db.execute('SELECT s.series_id,s.case_name FROM analysis_series s JOIN analysis_series_items i ON s.series_id=i.series_id WHERE i.task_id=? AND s.owner_user_id=? ORDER BY s.created_at DESC LIMIT 1', (task_id, user['user_id'])).fetchone()
                if row is None:
                    return {'series_id': None, 'items': []}
                items = db.execute('SELECT t.task_id,t.file_name,t.status FROM analysis_series_items i JOIN analysis_tasks t ON i.task_id=t.task_id WHERE i.series_id=? AND t.owner_user_id=? ORDER BY i.slice_index', (row['series_id'], user['user_id'])).fetchall()
            return {**dict(row), 'items': [dict(item) for item in items]}
