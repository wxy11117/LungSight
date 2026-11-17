"""安装版入口：隔离账号、数据库和端口，不读取开发版私人数据。"""
import os
from pathlib import Path

if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    os.environ['LUNGSIGHT_MODEL_BUNDLE_DIR'] = str(root)
    os.environ['LUNGSIGHT_DEVICE'] = 'cpu'
    os.environ.setdefault('LUNGSIGHT_DATA_DIR', str(Path(os.environ['LOCALAPPDATA']) / 'LungSight' / 'data'))
    # Cookie 不按端口隔离，必须在 FastAPI 声明 Cookie 参数之前设置独立名称。
    import auth
    auth.SESSION_COOKIE_NAME = 'lungsight_desktop_session'
    import app
    from literature import seed_medical_library
    from knowledge import connect, _upsert_source, _chunk_text
    app.ALLOWED_ORIGINS[:] = ['http://127.0.0.1:18000', 'http://localhost:18000']
    app.initialize_database()
    seed_medical_library(app.DATABASE_PATH)
    # 只索引随包自有模型说明和原创文献摘要，不需要开发者的论文压缩包。
    for name in ['MODEL_CARD_RESEARCH_2026-09-03.md', 'MODEL_PROMOTION_GATES.md']:
        doc = root.parent / 'docs' / name
        if doc.exists():
            payload = doc.read_bytes()
            with connect(app.DATABASE_PATH) as connection:
                _upsert_source(connection, title=payload.decode('utf-8').splitlines()[0].lstrip('# '),
                    source_type='MODEL_NOTE', version=app.runtime.manifest['model_version'], publication_date=None,
                    authority='LungSight model documentation', scope='研究用途，不用于独立临床诊断',
                    locator='lung-vision-site/docs/' + name, payload=payload,
                    chunks=[(section, None, content) for section, content in _chunk_text(payload.decode('utf-8'))])
    import uvicorn
    uvicorn.run(app.app, host='127.0.0.1', port=18001, access_log=False)
