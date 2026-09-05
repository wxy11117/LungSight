"""Public literature discovery and explicitly reviewed local knowledge import.

Only preset medical queries and numeric PubMed IDs leave the local backend.
No CT, account information, chat text, or LLM credentials are sent upstream.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx

from knowledge import _source_id, _upsert_source, connect, initialize_knowledge_schema

API_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
CATALOG_PATH = Path(__file__).with_name("medical_library.json")
TOPICS = {
    "adenocarcinoma": ("腺癌：形态与CT", 'lung AND adenocarcinoma AND ("computed tomography" OR morphology OR histology)'),
    "squamous_cell_carcinoma": ("鳞癌：形态与CT", 'lung AND "squamous cell" AND ("computed tomography" OR morphology OR histology)'),
    "large_cell_carcinoma": ("大细胞癌：病理与分型", 'lung AND "large cell carcinoma" AND (histology OR pathology OR "computed tomography")'),
    "normal": ("正常/筛查与结节随访", 'lung AND (screening OR nodule) AND "computed tomography"'),
    "treatment": ("肺癌治疗与指南", 'lung AND cancer AND (treatment OR therapy) AND (guideline OR trial)'),
    "prediction": ("CT预测组织学类型", 'lung AND (histology OR subtype) AND (radiomics OR "deep learning") AND "computed tomography"'),
}


class LiteratureUnavailable(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def initialize_literature_schema(database_path: Path) -> None:
    initialize_knowledge_schema(database_path)
    with connect(database_path) as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS literature_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT NOT NULL,
            user_id TEXT NOT NULL, event_type TEXT NOT NULL, details_json TEXT NOT NULL,
            created_at TEXT NOT NULL)""")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_literature_events_source ON literature_events(source_id, event_id)")


def _audit(connection, source_id: str, user_id: str, event_type: str, details: dict):
    connection.execute("INSERT INTO literature_events(source_id,user_id,event_type,details_json,created_at) VALUES (?,?,?,?,?)",
                       (source_id, user_id, event_type, json.dumps(details, ensure_ascii=False), now()))


def seed_medical_library(database_path: Path) -> dict:
    """Offline, additive and idempotent. Does not delete existing sources."""
    initialize_literature_schema(database_path)
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    with connect(database_path) as connection:
        for entry in catalog["entries"]:
            metadata = {key: value for key, value in entry.items() if key not in {"sections", "enabled", "url"}}
            metadata.update({"origin": "curated_catalog", "checked_at": catalog["checked_at"],
                             "review_status": "CURATED" if entry["enabled"] else "INDEX_ONLY",
                             "content_kind": "中文整理摘要（不是原文）" if entry["enabled"] else "仅资源索引",
                             "copyright": "仅保存原创中文要点与题录；原文及图像许可请在原站核验。"})
            payload = json.dumps(entry, ensure_ascii=False, sort_keys=True).encode("utf-8")
            _upsert_source(connection, title=entry["title"], source_type="MEDICAL_NOTE" if entry["enabled"] else "DATASET_INDEX",
                           version=catalog["version"], publication_date=entry["year"], authority=entry["authority"],
                           scope=entry["limitations"], locator=entry["url"], payload=payload,
                           chunks=[(part["heading"], None, part["text"]) for part in entry["sections"]])
            connection.execute("UPDATE evidence_sources SET metadata_json=?, retrieval_enabled=? WHERE source_id=?",
                               (json.dumps(metadata, ensure_ascii=False), int(entry["enabled"]), _source_id(entry["url"])))
    return {"version": catalog["version"], "sources": len(catalog["entries"]),
            "active": sum(entry["enabled"] for entry in catalog["entries"])}


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", " ", text or ""))).strip()


def _preview(abstract: str) -> str:
    # Do not mirror copyrighted abstracts/full text; the reader follows the
    # publisher link and supplies their own reviewed summary before activation.
    return " ".join(_plain(abstract).split()[:25])[:220]


def _fetch(query: str, *, page_size: int = 8) -> dict:
    try:
        response = httpx.get(API_URL, params={"query": query, "format": "json", "resultType": "core", "pageSize": page_size},
                             headers={"User-Agent": "LungSight-ResearchLibrary/1.0"}, timeout=18, follow_redirects=False)
        response.raise_for_status()
        if len(response.content) > 2_000_000:
            raise LiteratureUnavailable("文献服务返回内容过大，请缩小检索范围")
        data = response.json()
        if (not isinstance(data, dict) or not isinstance(data.get("resultList"), dict)
                or not isinstance(data["resultList"].get("result"), list)
                or any(not isinstance(item, dict) for item in data["resultList"]["result"])):
            raise LiteratureUnavailable("文献服务返回格式异常，请稍后重试")
        return data
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise LiteratureUnavailable("暂时无法连接Europe PMC，已有本地资料仍可使用。请稍后重试。") from exc


def _record(item: dict) -> dict:
    pmid = str(item.get("pmid") or item.get("id") or "")
    if not re.fullmatch(r"\d{1,10}", pmid) or item.get("source") != "MED":
        raise ValueError("仅支持PubMed正式题录")
    types = (item.get("pubTypeList") or {}).get("pubType", []) or []
    corrections = item.get("commentCorrectionList", {})
    warning_text = json.dumps([types, corrections]).lower()
    retracted = any(word in warning_text for word in ("retract", "withdrawn", "expression of concern"))
    preprint = any("preprint" in str(kind).lower() for kind in types)
    preview = _preview(item.get("abstractText", ""))
    return {
        "pmid": pmid, "title": _plain(item.get("title", "")), "doi": item.get("doi", ""),
        "pmcid": item.get("pmcid", ""), "authors": _plain(item.get("authorString", "")),
        "journal": _plain(((item.get("journalInfo") or {}).get("journal") or {}).get("title", "")),
        "publication_date": item.get("firstPublicationDate") or item.get("pubYear", ""),
        "abstract_preview": preview, "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        "abstract_sha256": hashlib.sha256(_plain(item.get("abstractText", "")).encode("utf-8")).hexdigest(),
        "open_access": item.get("isOpenAccess") == "Y", "retracted": retracted, "preprint": preprint,
        "content_kind": "题录与摘要短节选（不是全文）", "pub_types": types,
    }


def _topic_query(topic: str) -> str:
    if topic not in TOPICS:
        raise ValueError("请选择资料库提供的医学检索主题")
    return f"SRC:MED AND ({TOPICS[topic][1]})"


def search_literature(*, topic: str, since: int = 2020) -> dict:
    year = datetime.now(timezone.utc).year
    if since < 2000 or since > year:
        raise ValueError("检索起始年份不在允许范围")
    query = f"{_topic_query(topic)} AND FIRST_PDATE:[{since}-01-01 TO {datetime.now(timezone.utc):%Y-%m-%d}] sort_date:y"
    data = _fetch(query)
    records = []
    for item in data["resultList"]["result"]:
        try:
            records.append(_record(item))
        except ValueError:
            continue
    return {"provider": "Europe PMC（PubMed题录）", "topic": topic, "query": query,
            "total": data.get("hitCount", 0), "items": records, "checked_at": now(),
            "notice": "仅发送预设医学主题，不发送CT或对话；新导入题录默认不参与RAG。"}


def import_literature(database_path: Path, *, pmid: str, topic: str, user_id: str) -> dict:
    if not re.fullmatch(r"\d{1,10}", pmid):
        raise ValueError("PubMed编号格式错误")
    # Re-fetch at import time; never trust client-provided title, text, URLs,
    # classification, or an arbitrary remote address.
    data = _fetch(f"EXT_ID:{pmid} AND ({_topic_query(topic)})", page_size=1)
    matching = [item for item in data["resultList"]["result"] if str(item.get("pmid") or item.get("id")) == pmid]
    if not matching:
        raise ValueError("未找到符合所选肺癌医学主题的PubMed题录")
    record = _record(matching[0])
    source_id = _source_id(record["url"])
    digest = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
    with connect(database_path) as connection:
        existing = connection.execute("SELECT * FROM evidence_sources WHERE source_id=?", (source_id,)).fetchone()
        old_meta = json.loads(existing["metadata_json"]) if existing else {}
        if existing and (existing["source_type"] != "ONLINE_PAPER" or old_meta.get("owner_user_id") != user_id):
            return {"source_id": source_id, "status": "existing", "notice": "此来源已在共享资料库中，未覆盖其内容。"}
        if existing and old_meta.get("upstream_hash") == digest:
            old_meta["checked_at"] = now()
            connection.execute("UPDATE evidence_sources SET metadata_json=? WHERE source_id=?", (json.dumps(old_meta, ensure_ascii=False), source_id))
            _audit(connection, source_id, user_id, "UPSTREAM_CHECKED", {})
            return {"source_id": source_id, "status": "unchanged", "notice": "题录没有变化，保留已有核对状态。"}
        meta = {**record, "origin": "europe_pmc", "category": "literature", "classes": [topic] if topic in {"adenocarcinoma", "squamous_cell_carcinoma", "large_cell_carcinoma", "normal"} else [],
                "owner_user_id": user_id, "checked_at": now(), "upstream_hash": digest,
                "review_status": "BLOCKED" if record["retracted"] or record["preprint"] else "PENDING",
                "previous_note": old_meta.get("review_note", ""), "evidence_level": "待阅读全文并核对", "limitations": "题录不是诊疗依据；未启用，不进入RAG。"}
        _upsert_source(connection, title=record["title"], source_type="ONLINE_PAPER", version="EuropePMC-" + digest[:12],
                       publication_date=record["publication_date"], authority=record["journal"] or "PubMed题录",
                       scope="在线检索导入，待人工核对", locator=record["url"], payload=json.dumps(meta, ensure_ascii=False).encode(),
                       chunks=[("摘要短节选（非全文）", None, record["abstract_preview"] or "原题录没有摘要，请访问原站。")])
        connection.execute("UPDATE evidence_sources SET metadata_json=?, retrieval_enabled=0 WHERE source_id=?",
                           (json.dumps(meta, ensure_ascii=False), source_id))
        _audit(connection, source_id, user_id, "IMPORT_UPDATED" if existing else "IMPORTED_PENDING", {"pmid": pmid, "topic": topic})
    return {"source_id": source_id, "status": "updated" if existing else "created",
            "notice": "已保存到待核对资料。阅读原文并填写中文要点后才能用于RAG；上游变更会使旧核对状态失效。"}


def review_literature(database_path: Path, *, source_id: str, user_id: str, enabled: bool, note: str, acknowledged: bool) -> dict:
    note = note.strip()
    with connect(database_path) as connection:
        row = connection.execute("SELECT * FROM evidence_sources WHERE source_id=?", (source_id,)).fetchone()
        if row is None:
            raise LookupError("资料不存在")
        metadata = json.loads(row["metadata_json"])
        if row["source_type"] != "ONLINE_PAPER" or metadata.get("owner_user_id") != user_id:
            raise PermissionError("只能核对自己导入的在线题录；初始整理资料通过版本管理维护")
        if enabled and (metadata.get("retracted") or metadata.get("preprint")):
            raise ValueError("撤稿、关注声明或预印本条目不能启用为当前参考依据")
        if enabled and (not acknowledged or len(note) < 20 or len(note) > 2000):
            raise ValueError("请阅读原文、填写20–2000字的原创要点，并确认适用范围及局限")
        if enabled:
            metadata.update({"review_note": note, "reviewed_at": now(), "review_status": "USER_REVIEWED",
                             "content_kind": "用户核对后的原创笔记（不是原文）", "limitations": "用户已确认用于本机检索，不代表临床审定或论文正确性保证。"})
            connection.execute("DELETE FROM evidence_chunks WHERE source_id=?", (source_id,))
            connection.execute("INSERT INTO evidence_chunks(source_id,chunk_index,section,content) VALUES (?,0,?,?)",
                               (source_id, "用户核对笔记（非原文）", note))
            connection.execute("UPDATE evidence_sources SET sha256=?, scope=? WHERE source_id=?",
                               (hashlib.sha256(note.encode()).hexdigest(), metadata["limitations"], source_id))
        else:
            metadata["review_status"] = "DISABLED"
        connection.execute("UPDATE evidence_sources SET metadata_json=?, retrieval_enabled=? WHERE source_id=?",
                           (json.dumps(metadata, ensure_ascii=False), int(enabled), source_id))
        _audit(connection, source_id, user_id, "RETRIEVAL_ENABLED" if enabled else "RETRIEVAL_DISABLED", {"acknowledged": acknowledged})
    return {"source_id": source_id, "retrieval_enabled": enabled}


def literature_content(database_path: Path, source_id: str) -> str | None:
    with connect(database_path) as connection:
        row = connection.execute("SELECT * FROM evidence_sources WHERE source_id=?", (source_id,)).fetchone()
        if row is None or row["source_type"] not in {"MEDICAL_NOTE", "ONLINE_PAPER", "DATASET_INDEX"}:
            return None
        chunks = connection.execute("SELECT section,content FROM evidence_chunks WHERE source_id=? ORDER BY chunk_index", (source_id,)).fetchall()
    metadata = json.loads(row["metadata_json"])
    return "\n\n".join([
        row["title"], "原始来源：" + row["locator"], "发表/版本：" + str(row["publication_date"]),
        "内容性质：" + metadata.get("content_kind", "整理摘要"),
        "核对时间：" + str(metadata.get("checked_at", "")),
        "核对情况：" + metadata.get("verification", metadata.get("review_status", "待核对")),
        "适用限制：" + metadata.get("limitations", "仅科研参考"),
        "状态：" + ("已用于本地检索，仍需医生复核" if row["retrieval_enabled"] else "未启用，不参与RAG"),
        *[f"## {part['section']}\n{part['content']}" for part in chunks],
        "此文件不是原论文镜像；请访问原始链接查看全文和图版。新增资料不会训练或改变CT模型权重。",
    ])
