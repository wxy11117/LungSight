"""可复现的白名单分发构建；不拷贝开发者数据库、密钥或病例。"""
import argparse, hashlib, json, os, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()
def copy(src, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
def ignore(directory, names):
    return [n for n in names if n in {'__pycache__', 'tests', 'test', 'idlelib', 'ensurepip', 'pip', 'Scripts'} or n.endswith(('.pyc', '.pyo')) or n == 'direct_url.json']

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--node', type=Path, required=True)
    parser.add_argument('--python-base', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    args=parser.parse_args()
    project=args.project.resolve(); backend=project/'backend'
    # 全新构建目录，绝不递归删除任何已有目录。
    build=HERE/'build-beta1'
    if build.exists() and not args.resume: raise SystemExit('构建目录已存在，请选择新的版本目录，不覆盖已有包。')
    build.mkdir(exist_ok=True); payload=build/'payload'; payload.mkdir(exist_ok=True)
    appdest=payload/'lung-vision-site'/'backend'
    modules=['app','auth','agent_service','dicom_series','knowledge','literature','medical_policy','profile_images','public_content','registration','evaluation','rag_evaluation']
    for module in modules: copy(backend/(module+'.py'),appdest/(module+'.py'))
    for name in ['schema.sql','model_manifest.json','medical_library.json','evaluation_cases.json','rag_evaluation_cases.json']:
        copy(backend/name,appdest/name)
    copy(HERE/'desktop_backend.py', appdest/'desktop_backend.py')
    copy(project/'config'/'registration-catalog.json', payload/'lung-vision-site'/'config'/'registration-catalog.json')
    for name in ['MODEL_CARD_RESEARCH_2026-09-03.md','MODEL_PROMOTION_GATES.md']:
        copy(project/'docs'/name,payload/'lung-vision-site'/'docs'/name)
    manifest=json.loads((backend/'model_manifest.json').read_text(encoding='utf-8'))
    assert len(manifest['weights'])==5
    for name,expected in manifest['weights'].items():
        assert Path(name).name==name
        src=backend/'weights'/name
        assert digest(src)==expected, 'Model checksum mismatch: '+name
        copy(src,appdest/'weights'/name)
    print('Models copied and verified', flush=True)
    runtime=payload/'runtime'/'python'; runtime.mkdir(parents=True,exist_ok=True)
    base=args.python_base
    for name in ['python.exe','pythonw.exe','python3.dll','python311.dll','vcruntime140.dll','vcruntime140_1.dll','LICENSE.txt']:
        copy(base/name,runtime/name)
    for name in ['Lib','DLLs']:
        if not args.resume: shutil.copytree(base/name,runtime/name,ignore=ignore)
    site=backend/'.venv'/'Lib'/'site-packages'
    if not args.resume: shutil.copytree(site,runtime/'Lib'/'site-packages',dirs_exist_ok=True,ignore=ignore)
    # _pth 隔离 PATH、注册表和用户 site-packages，但明确包含业务模块。
    (runtime/'python311._pth').write_text('.\nLib\nDLLs\nLib/site-packages\n../../lung-vision-site/backend\n',encoding='utf-8')
    copy(args.node,payload/'runtime'/'node.exe')
    print('Runtime copied', flush=True)
    dist=build/'dist'
    if not args.resume: shutil.copytree(project/'dist',dist,ignore=shutil.ignore_patterns('standalone'))
    if not (payload/'frontend').exists():
        subprocess.run([str(args.node),str(HERE/'emit_frontend.mjs'),str(project),str(dist)],check=True)
        shutil.move(str(dist/'standalone'),str(payload/'frontend'))
    subprocess.run([str(args.node),str(HERE/'copy_runtime_peers.mjs'),str(project),str(payload/'frontend')],check=True)
    # 构建产物机械替换本地端口，不更改开发站点，也不触碰任何密钥。
    replacements=0
    for file in (payload/'frontend').rglob('*'):
        if file.is_file() and file.suffix in {'.js','.html','.json'} and 'node_modules' not in file.parts:
            text=file.read_text(encoding='utf-8')
            updated=text.replace('http://127.0.0.1:8001','http://127.0.0.1:18001').replace('http://127.0.0.1:3000','http://127.0.0.1:18000')
            if updated!=text: file.write_text(updated,encoding='utf-8')
            if 'http://127.0.0.1:18001' in updated: replacements+=1
    assert replacements>0
    copy(HERE/'INSTALL_README.txt',payload/'INSTALL_README.txt')
    licenses=payload/'THIRD_PARTY_NOTICES'; licenses.mkdir(exist_ok=True)
    copy(HERE/'tools'/'NODE_LICENSE.txt',licenses/'NODE_LICENSE.txt')
    for name in ['LICENSE','LICENSE.md','LICENSE.txt']:
        candidate=project/'node_modules'/'vinext'/name
        if candidate.exists(): copy(candidate,licenses/('VINEXT_'+name))
    # 保留实际分发依赖随附的许可证，额外整理清单，便于后续许可审核。
    license_index=[]
    for file in payload.rglob('*'):
        if file.is_file() and ('license' in file.name.lower() or 'copying' in file.name.lower() or file.name.lower()=='notice'):
            license_index.append(str(file.relative_to(payload)))
    (licenses/'LICENSE_INDEX.txt').write_text('\n'.join(license_index),encoding='utf-8')
    csc=r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'
    subprocess.run([csc,'/nologo','/target:winexe','/platform:x64','/optimize+', '/win32icon:'+str(HERE/'app-icon.ico'),'/out:'+str(payload/'LungSight.exe'),'/r:System.Windows.Forms.dll','/r:System.Drawing.dll',str(HERE/'LungSightLauncher.cs')],check=True)
    files=[]
    for file in sorted(payload.rglob('*')):
        if not file.is_file() or file.name=='BUNDLE_MANIFEST.json': continue
        assert file.suffix not in {'.sqlite3','.sqlite','.db','.key'}, 'Private data found: '+str(file)
        assert file.name not in {'.env','credential_secret.key'}
        files.append({'path':file.relative_to(payload).as_posix(),'bytes':file.stat().st_size,'sha256':digest(file)})
    (payload/'BUNDLE_MANIFEST.json').write_text(json.dumps({'version':'0.1.0-beta.1','model_version':manifest['model_version'],'frontend_port':18000,'backend_port':18001,'files':files},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'payload':str(payload),'files':len(files),'bytes':sum(f['bytes'] for f in files)},ensure_ascii=False),flush=True)

if __name__=='__main__': main()
