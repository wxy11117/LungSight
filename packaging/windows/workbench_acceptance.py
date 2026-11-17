"""Real-model acceptance with public PNGs and synthetic DICOM; no private credentials."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import threading
import socket
import uuid
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from auth_test_helpers import registration_fields
from test_dicom_series import synthetic_ct
from pydicom.uid import generate_uid

parser = argparse.ArgumentParser()
parser.add_argument('--api', default='http://127.0.0.1:8001')
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--payload', type=Path, help='Test bundled Python/Node directly in owned subprocesses')
parser.add_argument('--data-root', type=Path)
parser.add_argument('--serve', action='store_true', help='Start and stop an owned real backend for this run')
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
client = httpx.Client(base_url=args.api, timeout=120, trust_env=False)
report = {'fixture_scope': 'repository public PNGs and synthetic DICOM; engineering only', 'checks': {}}
server = None
server_thread = None
packaged_backend = None
packaged_frontend = None
package_env = None
package_logs = []


def start_packaged_backend():
    return subprocess.Popen([str(args.payload.resolve() / 'runtime' / 'python' / 'python.exe'), '-u', 'desktop_backend.py'],
                            cwd=args.payload.resolve() / 'lung-vision-site' / 'backend', env=package_env,
                            stdout=package_logs[0], stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)


def stop_owned(process):
    if process is not None and process.poll() is None:
        process.terminate()
        process.wait(timeout=20)


def await_health():
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            if client.get('/api/health').json().get('model_ready'):
                return
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(.5)
    raise AssertionError('Packaged backend failed to become ready')


def ok(response, code=200):
    assert response.status_code == code, (response.status_code, response.text[:300])
    return response.json()


def job(job_id):
    return ok(client.get('/api/analysis-jobs/' + job_id))


def wait(job_id, predicate=lambda value: value['state'] not in {'QUEUED', 'RUNNING', 'CANCELLING'}):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        value = job(job_id)
        if predicate(value):
            return value
        time.sleep(.1)
    raise AssertionError('Timed out waiting for job')


def submit(files, mode='image'):
    return ok(client.post('/api/analysis-jobs', data={'mode': mode, 'case_name': '工程验收：公开或合成输入', 'privacy_acknowledged': 'true'}, files=files), 202)['job_id']


try:
    if args.payload:
        assert args.data_root and not args.serve and args.api == 'http://127.0.0.1:18001'
        for port in [18000, 18001]:
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', port))  # Refuse to touch an existing service.
        package_env = dict(os.environ, LUNGSIGHT_DATA_DIR=str(args.data_root.resolve() / 'data'), PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', HOST='127.0.0.1', PORT='18000', NODE_ENV='production')
        for name in ['PYTHONHOME', 'PYTHONPATH', 'NODE_OPTIONS', 'LUNGSIGHT_CREDENTIAL_SECRET']:
            package_env.pop(name, None)
        package_logs = [(args.output / name).open('w', encoding='utf-8') for name in ['backend.log', 'frontend.log']]
        packaged_backend = start_packaged_backend()
        packaged_frontend = subprocess.Popen([str(args.payload.resolve() / 'runtime' / 'node.exe'), 'server.js'], cwd=args.payload.resolve() / 'frontend', env=package_env, stdout=package_logs[1], stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        await_health()
        subprocess.run([sys.executable, str(Path(__file__).with_name('smoke_test.py')), '--payload', str(args.payload.resolve()), '--data-root', str(args.data_root.resolve())], check=True, timeout=180)
    if args.serve:
        import uvicorn
        address = urlparse(args.api)
        assert address.hostname == '127.0.0.1' and address.port
        server = uvicorn.Server(uvicorn.Config('app:app', host=address.hostname, port=address.port, log_level='warning'))
        server_thread = threading.Thread(target=server.run, daemon=True)
        server_thread.start()
        deadline = time.monotonic() + 60
        while not server.started and time.monotonic() < deadline and server_thread.is_alive():
            time.sleep(.2)
        assert server.started, 'Owned backend did not start; check port and runtime'
    report['health'] = ok(client.get('/api/health'))
    assert report['health']['model_ready'] and report['health']['models_loaded'] == 5
    password = uuid.uuid4().hex + 'Aa9!'
    ok(client.post('/api/auth/register', json={**registration_fields(password), 'email': f'acceptance-{uuid.uuid4().hex[:10]}@example.com', 'display_name': '工程验收虚构账号', 'password': password, 'accepted_terms': True, 'accepted_privacy': True}), 201)
    pngs = [('files', (name, (ROOT / 'public' / name).read_bytes(), 'image/png')) for name in ['ct-normal.png', 'ct-adeno.png', 'ct-squamous.png']]
    started = time.monotonic()
    images = wait(submit(pngs))
    report['three_image_wall_seconds'] = round(time.monotonic() - started, 3)
    assert images['state'] == 'SUCCEEDED' and images['completed'] == 3
    report['model_timing_ms'] = [{key: item['model'][key] for key in ['inference_ms', 'attention_ms']} for item in images['results']]
    for item in images['results']:
        assert item['model']['folds'] == 5 and item['attention']['available']
        assert not item['applicability']['clinical_candidate_allowed']
        for suffix in ['image', 'attention']:
            assert client.get(f"/api/tasks/{item['task_id']}/{suffix}").status_code == 200
    assert not any(item['retryable'] for item in images['items'])
    series = ok(client.get('/api/series/' + images['series_id']))
    assert series['prediction']['decision'] == 'INDETERMINATE'
    report['checks']['real_fivefold_and_grad_cam'] = True
    task = images['results'][1]['task_id']
    annotation = {'revision': 0, 'items': [{'id': 'acceptance-note', 'x': .25, 'y': .75, 'note': '工程合成备注 <script>not executable</script>'}]}
    ok(client.put(f'/api/tasks/{task}/annotations', json=annotation))
    assert client.put(f'/api/tasks/{task}/annotations', json=annotation).status_code == 409
    review = {'decision': 'UNDETERMINED', 'reviewer_name': '工程验收（虚构）', 'comment': '仅验证流程；不是专业临床复核结论。'}
    ok(client.post(f'/api/tasks/{task}/review', json=review))
    assert client.post(f'/api/tasks/{task}/review', json=review).status_code == 409
    exported = client.get('/api/series/' + images['series_id'] + '/report')
    assert exported.status_code == 200 and '&lt;script&gt;' in exported.text and '<script>' not in exported.text
    (args.output / 'public-example-series-report.html').write_text(exported.text, encoding='utf-8')
    report['checks']['annotations_conflict_review_lock_report'] = True
    uid = generate_uid()
    dicoms = [('files', (f'synthetic-{i}.dcm', synthetic_ct(series_uid=uid, position=i * 1.25, instance=i + 1, patient_name='Synthetic^Engineering', lung_present=True), 'application/dicom')) for i in range(4)]
    dicom_job = wait(submit(dicoms, 'dicom'))
    assert dicom_job['state'] == 'SUCCEEDED' and dicom_job['completed'] > 0
    dicom_series = ok(client.get('/api/series/' + dicom_job['series_id']))
    assert dicom_series['prediction']['decision'] == 'INDETERMINATE'
    assert not dicom_series['dicom']['privacy']['original_dicom_persisted']
    assert not dicom_series['dicom']['privacy']['identifier_values_persisted']
    assert 'Synthetic^Engineering' not in json.dumps(dicom_series)
    report['checks']['synthetic_dicom_window_privacy_case_gate'] = True
    partial = wait(submit([pngs[0], ('files', ('broken.png', b'invalid input', 'image/png'))]))
    assert partial['state'] == 'PARTIAL' and partial['completed'] == 1 and partial['failed'] == 1
    report['checks']['partial_invalid_input_keeps_success'] = True
    many = pngs * 4
    cancel_id = submit(many)
    wait(cancel_id, lambda value: value['completed'] >= 1)
    ok(client.post(f'/api/analysis-jobs/{cancel_id}/cancel'))
    stopped = wait(cancel_id)
    assert stopped['state'] == 'CANCELLED' and 0 < stopped['completed'] < stopped['total']
    successful = {item['task_id']: item['attempts'] for item in stopped['items'] if item['state'] == 'SUCCEEDED'}
    ok(client.post(f'/api/analysis-jobs/{cancel_id}/retry'))
    resumed = wait(cancel_id)
    assert resumed['state'] == 'SUCCEEDED'
    assert all(item['attempts'] == successful[item['task_id']] for item in resumed['items'] if item['task_id'] in successful)
    report['checks']['cancel_resume_reuses_completed_slices'] = True
    clear_id = submit(many)
    ok(client.post(f'/api/analysis-jobs/{clear_id}/cancel'))
    wait(clear_id)
    cleared = ok(client.post(f'/api/analysis-jobs/{clear_id}/clear-inputs'))
    assert not any(item['retryable'] for item in cleared['items'])
    assert client.post(f'/api/analysis-jobs/{clear_id}/retry').status_code == 409
    report['checks']['explicit_cache_release'] = True
    if args.payload:
        restart_id = submit(many)
        before = wait(restart_id, lambda value: value['completed'] >= 1)
        assert before['completed'] < before['total']
        successful = {item['task_id']: item['attempts'] for item in before['items'] if item['state'] == 'SUCCEEDED'}
        stop_owned(packaged_backend)
        packaged_backend = start_packaged_backend()
        await_health()
        restored = job(restart_id)
        assert restored['state'] == 'INTERRUPTED', restored['state']
        ok(client.post(f'/api/analysis-jobs/{restart_id}/retry'))
        completed = wait(restart_id)
        assert completed['state'] == 'SUCCEEDED'
        assert all(item['attempts'] == successful[item['task_id']] for item in completed['items'] if item['task_id'] in successful)
        report['checks']['actual_packaged_backend_restart_and_resume'] = True
    report['series_id'] = images['series_id']
    report['checks']['unauthenticated_media_denied'] = httpx.get(args.api + f'/api/tasks/{task}/image', trust_env=False).status_code == 401
    assert report['checks']['unauthenticated_media_denied']
    (args.output / 'workbench-acceptance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
finally:
    client.close()
    if server:
        server.should_exit = True
        server_thread.join(timeout=30)
    stop_owned(packaged_frontend)
    stop_owned(packaged_backend)
    for stream in package_logs:
        stream.close()
