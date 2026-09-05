"""Presentation aliases only: preserve original files, histories and model hashes."""
import json
import re
from pathlib import Path

ARTICLE_TITLE = "关于肺部CT图像四分类与稳健预测"
ARTICLE_FILENAME = ARTICLE_TITLE + ".pdf"
LEGACY_PAPER_LOCATORS = {
    "APMCM-B-2610268.pdf": ARTICLE_FILENAME,
    "训练依据PDF.pdf": ARTICLE_FILENAME,
}


def public_text(value: str) -> str:
    # Longest contextual labels first; do not alter scientific results or units.
    replacements = [
        ("2026年APMCM亚太地区大模型竞赛B题", "肺部影像分类任务说明"),
        ("APMCM-B-2610268.pdf", ARTICLE_FILENAME),
        ("项目竞赛论文", "模型方法研究论文"), ("竞赛提交论文", "模型方法研究论文"),
        ("竞赛程序包说明", "模型推理程序说明"), ("竞赛主程序", "模型推理主程序"),
        ("程序提交包", "模型程序包"), ("正式提交程序", "模型程序"),
        ("竞赛数据同类型", "已验证数据范围内的"), ("竞赛给定的", "研究使用的"),
        ("竞赛模型演示", "模型研究演示"), ("竞赛展示", "模型演示"),
        ("竞赛题目", "研究任务说明"), ("竞赛", "研究"),
        ("亚太地区大模型", "医学影像"), ("赛题", "研究任务"),
    ]
    for before, after in replacements:
        value = value.replace(before, after)
    return re.sub("apmcm", "LungSight", value, flags=re.I)


def public_payload(value):
    if isinstance(value, str):
        return public_text(value)
    if isinstance(value, list):
        return [public_payload(item) for item in value]
    if isinstance(value, dict):
        # IDs, hashes and externally resolved links must remain exact.
        preserve = {"source_id", "chunk_id", "conversation_id", "message_id", "task_id", "user_id", "sha256", "upstream_hash", "url", "doi"}
        return {key: item if key in preserve else public_payload(item) for key, item in value.items()}
    return value


def pdf_download_name(title: str, fallback: str = "医学研究文献") -> str:
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", public_text(title)).strip(" .")[:150]
    return (clean or fallback).removesuffix(".pdf") + ".pdf"


def apply_library_presentation(database_path: Path) -> None:
    from knowledge import connect
    with connect(database_path) as connection:
        for row in connection.execute("SELECT source_id,title,authority,version,scope,locator,metadata_json FROM evidence_sources").fetchall():
            meta = json.loads(row["metadata_json"] or "{}")
            # Keep assignment/administrative sources on disk and in the DB for
            # provenance, but exclude them from the medical-facing library/RAG.
            locator = row["locator"].replace("\\", "/")
            stable_locator = LEGACY_PAPER_LOCATORS.get(locator, locator)
            hidden = row["authority"] == "竞赛题目" or "B题/" in locator or locator in {
                "lung-vision-site/README.md", "lung-vision-site/backend/README.md",
                "src.zip::README.md", "src.zip::main.py",
                "research_reproduction.zip::MODEL_RESOURCES.md", "research_reproduction.zip::REPRODUCE.md",
            }
            if hidden:
                meta["public_hidden"] = True
                connection.execute("UPDATE evidence_sources SET retrieval_enabled=0,metadata_json=? WHERE source_id=?",
                                   (json.dumps(meta, ensure_ascii=False), row["source_id"]))
                continue
            connection.execute("UPDATE evidence_sources SET title=?,authority=?,version=?,scope=?,locator=? WHERE source_id=?",
                               (*[public_text(row[key]) for key in ("title", "authority", "version", "scope")], stable_locator, row["source_id"]))


class PublicPresentationMiddleware:
    """Normalize legacy JSON display data; never rewrite stored records or PDFs.

    Streaming responses are normalized before chunking in the route, so a label
    spanning two stream chunks cannot leak or corrupt the event protocol.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        prefixes = ("/api/agent/", "/api/evidence/", "/api/tasks", "/api/model", "/api/analyze", "/api/evaluation/")
        if scope["type"] != "http" or not scope.get("path", "").startswith(prefixes):
            return await self.app(scope, receive, send)
        start, chunks = None, []

        async def normalized_send(message):
            nonlocal start
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                if headers.get(b"content-type", b"").startswith(b"application/json"):
                    start = message
                    return
            if start is not None and message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
                if message.get("more_body", False):
                    return
                original = b"".join(chunks)
                try:
                    body = json.dumps(public_payload(json.loads(original)), ensure_ascii=False).encode("utf-8")
                except (ValueError, UnicodeError):
                    body = original
                headers = [(key, value) for key, value in start.get("headers", []) if key != b"content-length"]
                await send({**start, "headers": [*headers, (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body, "more_body": False})
                return
            await send(message)

        await self.app(scope, receive, normalized_send)
