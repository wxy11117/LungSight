"""封包前生成文件完整性清单，不包含用户数据或构建工具。"""
import hashlib, json, shutil
from pathlib import Path
root=Path(__file__).resolve().parent
payload=root/'build-beta1'/'payload'
shutil.copy2(root/'INSTALL_README.txt',payload/'INSTALL_README.txt')
files=[]
for file in sorted(payload.rglob('*')):
    if not file.is_file() or file.name=='BUNDLE_MANIFEST.json': continue
    assert file.suffix not in {'.sqlite3','.sqlite','.db','.key'}, 'Private data: '+str(file)
    assert file.name not in {'.env','credential_secret.key'}
    with file.open('rb') as stream: sha=hashlib.file_digest(stream,'sha256').hexdigest()
    files.append({'path':file.relative_to(payload).as_posix(),'bytes':file.stat().st_size,'sha256':sha})
manifest={'version':'0.1.0-beta.1','model_version':'research-fivefold-20260902-165455','frontend_port':18000,'backend_port':18001,'files':files}
(payload/'BUNDLE_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'files':len(files),'bytes':sum(f['bytes'] for f in files),'privacy_scan':'passed'}))
