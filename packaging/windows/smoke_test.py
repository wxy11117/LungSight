"""只操作安装测试实例，验证空账号、推理、影像持久化和 API 隔离。"""
import argparse, json, sqlite3, time, uuid
from pathlib import Path
import httpx

parser=argparse.ArgumentParser()
parser.add_argument('--payload',type=Path,required=True)
parser.add_argument('--data-root',type=Path,required=True)
args=parser.parse_args()
api='http://127.0.0.1:18001'; origin='http://127.0.0.1:18000'
for attempt in range(120):
    try:
        health=httpx.get(api+'/api/health',trust_env=False).json()
        if health.get('models_loaded')==5: break
    except (httpx.HTTPError,ValueError): pass
    time.sleep(1)
else: raise AssertionError('Independent backend failed to start')
db=args.data_root/'data'/'lungsight.sqlite3'
with sqlite3.connect(db) as c:
    assert c.execute('SELECT COUNT(*) FROM users').fetchone()[0]==0
    assert c.execute('SELECT COUNT(*) FROM analysis_tasks').fetchone()[0]==0
with httpx.Client(base_url=api,headers={'Origin':origin},timeout=120,trust_env=False) as client:
    assert client.get('/api/tasks').status_code==401
    pre=client.options('/api/auth/register',headers={'Access-Control-Request-Method':'POST'})
    assert pre.headers.get('access-control-allow-origin')==origin
    assert client.options('/api/auth/register',headers={'Origin':'https://untrusted.example','Access-Control-Request-Method':'POST'}).status_code==400
    password=uuid.uuid4().hex+'Aa9!'
    reg=client.post('/api/auth/register',json={'email':'installer-test@example.com','display_name':'安装验证',
        'password':password,'confirm_password':password,'accepted_terms':True,'accepted_privacy':True,
        'doctor_profile':{'real_name':'测试医生','province':'北京市','city':'北京市','hospital_id':None,
            'hospital_name':'测试医院（虚构）','department':'放射科','professional_title':'主治医师'}})
    assert reg.status_code==201, reg.text
    assert 'lungsight_desktop_session' in client.cookies and 'lungsight_session' not in client.cookies
    assert client.get('/api/auth/me').status_code==200
    assert client.get('/api/tasks').json()['items']==[]
    sources=client.get('/api/evidence/sources'); assert sources.status_code==200
    image=args.payload/'frontend'/'public'/'ct-normal.png'
    with image.open('rb') as f:
        response=client.post('/api/analyze',files={'file':('test-ct.png',f,'image/png')})
    assert response.status_code==200, response.text
    result=response.json(); task=result['task_id']
    assert len(result['prediction']['fold_results'])==5
    assert result['applicability']['clinical_candidate_allowed'] is False
    assert client.get('/api/tasks/'+task+'/image').status_code==200
    assert client.get('/api/tasks/'+task+'/attention').status_code==200
    assert client.get('/api/tasks/'+task+'/report').status_code==200
    client.post('/api/auth/logout')
    assert client.get('/api/tasks/'+task).status_code==401
page=httpx.get(origin+'/auth',trust_env=False); assert page.status_code==200
assert 'LungSight' in page.text
assert httpx.get(origin+'/auth-panel/index.html',trust_env=False).status_code==200
for route in ['/agent','/analysis','/cases','/review','/library','/settings']:
    assert httpx.get(origin+route,trust_env=False,timeout=30).status_code==200, route
report={'health':health,'clean_database_verified':True,'registration':True,'isolated_cookie':True,
        'cors':True,'fivefold_inference':True,'original_image':True,'grad_cam':True,'report_download':True,
        'logout_protection':True,'frontend_auth':True,'all_main_routes':True,'private_model_keys_tested':False}
(args.data_root/'smoke-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
