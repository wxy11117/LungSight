"""LungSight 本地循证知识库与抽取式问答。

检索模型方法资料、已整理医学资料及用户核对启用的文献笔记；不生成临床诊断。
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader
from public_content import public_payload, public_text


DOMAIN_TERMS = [
    "resnet18", "dinov2", "biomedclip", "accuracy", "macro-f1", "recall",
    "准确率", "宏平均", "召回率", "数据审计", "去重", "重复", "近重复",
    "交叉验证", "分层分组", "折外预测", "温度缩放", "概率融合", "腺癌",
    "大细胞癌", "正常肺部", "鳞状细胞癌", "肺鳞癌", "局限", "泛化",
    "测试集", "训练集", "验证集", "样本", "模型选择", "置信区间",
    "肺癌", "鳞癌", "细胞形态", "形态", "病理", "细胞", "磨玻璃", "空洞", "毛刺",
    "支气管", "分型", "治疗", "靶向", "免疫", "分期", "筛查", "随访", "结节",
    "腺腔", "腺泡", "黏液", "角化", "细胞间桥", "放射组学", "大细胞", "征象",
    "adenocarcinoma", "squamous", "histology", "radiomics", "morphology",
]

EXPANSIONS = {
    "为什么选择": ["最终选择", "保守筛选规则", "候选方案", "91.92", "94.61", "93.41"],
    "为何选择": ["最终选择", "保守筛选规则", "候选方案", "91.92", "94.61", "93.41"],
    "表现": ["accuracy", "macro-f1", "recall", "准确率", "90.66", "90.98"],
    "性能": ["accuracy", "macro-f1", "recall", "准确率", "90.66", "90.98"],
    "局限": ["外部泛化", "进一步验证", "嵌套交叉验证"],
    "可靠": ["数据审计", "分层分组", "置信区间"],
    "数据泄漏": ["重复信息跨折", "未去重", "数据泄漏"],
    "误诊": ["召回率", "混淆矩阵", "重点类别"],
    "所有医院": ["外部泛化", "独立数据", "进一步验证"],
    "直接使用": ["外部泛化", "独立数据", "进一步验证"],
    "临床使用": ["外部泛化", "独立数据", "进一步验证"],
    "数据有多少": ["613", "72", "315", "1000"],
    "accuracy和macro-f1": ["90.66", "90.98", "0.9066", "0.9098", "505", "52"],
    "四个类别的召回率": ["87.56", "88.15", "100.00", "94.61", "表 25"],
    "dinov2层级分类": ["0.8259", "0.8275", "82.59", "82.75"],
    "biomedclip直接四分类": ["0.8330", "0.8275", "83.30", "82.75"],
    "温度缩放": ["0.5360", "0.3144", "nll", "分类指标不变"],
    "融合模型提高": ["91.92", "94.61", "93.41", "肺鳞状细胞癌"],
    "五折模型概率平均": ["为降低单个训练折随机性对测试结果的影响", "五个折模型", "等权平均", "随机性", "式（50）"],
    "保守工程筛选": ["0.5 个百分点", "至少4 个验证折", "recall 均不得下降"],
    "小样本ct": ["预训练数据分布与本项目肺部ct切片仍存在差异", "局部纹理", "病灶边缘", "有限样本", "预训练域"],
    "一共包含": ["全部1000张图像", "613", "72", "315"],
    "用于建模": ["557 张", "有效建模样本池"],
    "group_id": ["降低已识别重复或近重复图像跨折造成的评价偏差", "不跨折", "重复信息", "性能高估", "数据泄漏"],
    "表观性能高估": ["94.44", "90.66", "3.77 个百分点", "未去重随机五折"],
    "哈希方法": ["文件 sha-256", "解码像素 sha-256", "感知哈希"],
    "外部测试": ["提前停止", "最佳权重选择", "嵌套交叉验证", "独立数据"],
    "不能直接外推": ["38 个正常", "wilson 95%", "90.82", "更大规模外部数据"],
    "外部泛化能力": ["嵌套交叉验证", "多中心", "独立数据", "患者编号"],
    "最大预测概率": ["真实诊断正确率", "相对预测确定程度", "五折概率平均"],
    "使用范围": ["研究数据范围内的二维 ct 图像排序", "肺部 ct 四分类研究原型", "二维 ct", "闭集排序", "辅助分析", "不能替代"],
    "支持哪些二维图片格式": ["支持上传 png、jpg、bmp 或 tiff 图片", "png", "jpg", "bmp", "tiff"],
    "正式部署模型": ["model_version", "fold_count", "resnet18_fold_0", "fivefold"],
    "哪个api": ["post /api/analyze", "本地 api"],
    "上传到云端": ["影像只在本机进入模型，不上传云端", "只在本机", "不上传云端", "本地推理"],
    "肺鳞癌": ["鳞状细胞癌", "squamous"],
    "鳞癌": ["鳞状细胞癌", "角化", "squamous"],
    "磨玻璃": ["ground-glass", "ground glass", "腺癌"],
    "细胞形态": ["病理", "腺腔", "角化", "细胞间桥", "形态学"],
    "大细胞癌": ["large cell", "未分化", "重分类"],
    "靶向治疗": ["生物标志物", "targeted"],
    "怎么通过ct": ["影像征象", "组织学", "放射组学"],
}

UNSAFE_PATTERNS = [
    "这个患者应该", "这位患者应该", "给这个患者", "给患者开", "用药剂量",
    "处方", "治疗方案", "确诊为", "分期为", "是否需要手术", "能活多久",
]


@contextmanager
def connect(database_path: Path):
    connection = sqlite3.connect(database_path, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_knowledge_schema(database_path: Path) -> None:
    with connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS evidence_sources (
                source_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                source_type TEXT NOT NULL,
                version TEXT NOT NULL,
                publication_date TEXT,
                authority TEXT NOT NULL,
                scope TEXT NOT NULL,
                locator TEXT NOT NULL UNIQUE,
                sha256 TEXT NOT NULL,
                imported_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS evidence_chunks (
                chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                section TEXT NOT NULL,
                page_number INTEGER,
                content TEXT NOT NULL,
                UNIQUE(source_id, chunk_index),
                FOREIGN KEY(source_id) REFERENCES evidence_sources(source_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS evidence_queries (
                query_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                question TEXT NOT NULL,
                support_level TEXT NOT NULL,
                answer_json TEXT NOT NULL,
                include_in_report INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                FOREIGN KEY(task_id) REFERENCES analysis_tasks(task_id)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_evidence_chunks_source ON evidence_chunks(source_id, chunk_index)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_evidence_queries_task_created ON evidence_queries(task_id, created_at DESC)"
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(evidence_sources)")}
        if "metadata_json" not in columns:
            connection.execute("ALTER TABLE evidence_sources ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'")
        if "retrieval_enabled" not in columns:
            connection.execute("ALTER TABLE evidence_sources ADD COLUMN retrieval_enabled INTEGER NOT NULL DEFAULT 1")
        connection.execute("PRAGMA optimize")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _chunk_text(text: str, max_chars: int = 950) -> list[tuple[str, str]]:
    raw = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    # PDF extractors retain visual line wrapping. Join those soft line breaks so
    # evidence excerpts end at semantic punctuation instead of mid-sentence.
    raw = re.sub(r"(?<!\n)\n(?!\n)", " ", raw)
    cleaned = re.sub(r"[ \t]+", " ", raw).strip()
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n|\f", cleaned) if item.strip()]
    chunks: list[tuple[str, str]] = []
    section = "正文"
    buffer = ""
    for paragraph in paragraphs:
        heading_match = re.match(r"^((?:\d+(?:\.\d+){0,3}|附录\s*\d+|摘要|关键词|参考文献)[^。]{0,80})$", paragraph)
        if heading_match:
            section = heading_match.group(1)[:100]
        sentences = [item for item in re.split(r"(?<=[。！？；])", paragraph) if item.strip()]
        parts: list[str] = []
        sentence_buffer = ""
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence_buffer and len(sentence_buffer) + len(sentence) + 1 > max_chars:
                parts.append(sentence_buffer)
                sentence_buffer = ""
            if len(sentence) > max_chars:
                if sentence_buffer:
                    parts.append(sentence_buffer)
                    sentence_buffer = ""
                parts.extend(sentence[start:start + max_chars] for start in range(0, len(sentence), max_chars))
            else:
                sentence_buffer = f"{sentence_buffer} {sentence}".strip()
        if sentence_buffer:
            parts.append(sentence_buffer)
        for part in parts:
            if buffer and len(buffer) + len(part) + 1 <= max_chars:
                buffer = f"{buffer}\n{part}"
            else:
                if buffer:
                    chunks.append((section, buffer))
                buffer = part
    if buffer:
        chunks.append((section, buffer))
    return chunks


def _source_id(locator: str) -> str:
    return f"SRC-{hashlib.sha1(locator.encode('utf-8')).hexdigest()[:12].upper()}"


def _upsert_source(
    connection: sqlite3.Connection,
    *,
    title: str,
    source_type: str,
    version: str,
    publication_date: str | None,
    authority: str,
    scope: str,
    locator: str,
    payload: bytes,
    chunks: list[tuple[str, int | None, str]],
) -> None:
    source_id = _source_id(locator)
    digest = _sha256(payload)
    existing = connection.execute(
        "SELECT sha256 FROM evidence_sources WHERE source_id = ?", (source_id,)
    ).fetchone()
    if existing and existing["sha256"] == digest:
        connection.execute(
            """UPDATE evidence_sources
               SET title = ?, source_type = ?, version = ?, publication_date = ?,
                   authority = ?, scope = ?, locator = ?
               WHERE source_id = ?""",
            (title, source_type, version, publication_date, authority, scope, locator, source_id),
        )
        return
    imported_at = datetime.now(timezone.utc).isoformat()
    connection.execute("DELETE FROM evidence_chunks WHERE source_id = ?", (source_id,))
    connection.execute(
        """
        INSERT INTO evidence_sources (
            source_id, title, source_type, version, publication_date, authority,
            scope, locator, sha256, imported_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id) DO UPDATE SET
            title=excluded.title, source_type=excluded.source_type, version=excluded.version,
            publication_date=excluded.publication_date, authority=excluded.authority,
            scope=excluded.scope, locator=excluded.locator, sha256=excluded.sha256,
            imported_at=excluded.imported_at
        """,
        (source_id, title, source_type, version, publication_date, authority, scope, locator, digest, imported_at),
    )
    connection.executemany(
        """
        INSERT INTO evidence_chunks (source_id, chunk_index, section, page_number, content)
        VALUES (?, ?, ?, ?, ?)
        """,
        [(source_id, index, section, page, content) for index, (section, page, content) in enumerate(chunks)],
    )


def build_knowledge_base(
    database_path: Path,
    workspace_root: Path,
    *,
    force: bool = False,
) -> dict:
    initialize_knowledge_schema(database_path)
    if force:
        with connect(database_path) as connection:
            connection.execute("DELETE FROM evidence_chunks")
            connection.execute("DELETE FROM evidence_sources")
    pdf_sources = [
        {
            "path": workspace_root / "关于肺部CT图像四分类与稳健预测.pdf",
            "title": "关于肺部CT图像四分类与稳健预测",
            "version": "模型方法论文-2026",
            "authority": "模型方法研究论文",
            "scope": "数据治理、模型训练、性能评估、模型选择与局限",
        },
        {
            "path": workspace_root / "B题" / "B题 肺癌疾病诊断图像识别与分类问题.pdf",
            "title": "肺癌疾病诊断图像识别与分类问题",
            "version": "研究任务说明-2026",
            "authority": "内部任务说明",
            "scope": "原始任务、数据说明与评价方式；不作为医学证据",
        },
    ]
    with connect(database_path) as connection:
        for item in pdf_sources:
            path = item["path"]
            payload = path.read_bytes()
            reader = PdfReader(path)
            chunks: list[tuple[str, int | None, str]] = []
            for page_number, page in enumerate(reader.pages, start=1):
                page_text = page.extract_text() or ""
                for section, content in _chunk_text(page_text):
                    chunks.append((section, page_number, content))
            _upsert_source(
                connection,
                title=item["title"],
                source_type="PDF",
                version=item["version"],
                publication_date="2026",
                authority=item["authority"],
                scope=item["scope"],
                locator=str(path.relative_to(workspace_root)),
                payload=payload,
                chunks=chunks,
            )

        file_sources = [
            (workspace_root / "lung-vision-site" / "README.md", "LungSight本地MVP说明", "项目文档", "当前版本", "系统能力与安全边界"),
            (workspace_root / "lung-vision-site" / "backend" / "README.md", "LungSight推理服务说明", "项目文档", "当前版本", "接口、复核状态与优先级规则"),
            (workspace_root / "lung-vision-site" / "backend" / "model_manifest.json", "模型版本与权重清单", "模型清单", "research-fivefold-20260902", "模型类别、版本、权重完整性与适用性门控"),
            (workspace_root / "lung-vision-site" / "docs" / "MODEL_CARD_RESEARCH_2026-09-03.md", "LungSight五折ResNet18研究模型卡", "模型卡", "2026-09-03", "模型任务、数据、验证、阈值、适用性与安全边界"),
            (workspace_root / "lung-vision-site" / "docs" / "MODEL_PROMOTION_GATES.md", "LungSight模型晋级门控", "模型治理", "2026-09-03", "患者级、DICOM、ROI、外部验证与临床晋级条件"),
        ]
        for path, title, authority, version, scope in file_sources:
            payload = path.read_bytes()
            text = payload.decode("utf-8", errors="replace")
            chunks = [(section, None, content) for section, content in _chunk_text(text)]
            _upsert_source(
                connection,
                title=title,
                source_type=path.suffix.removeprefix(".").upper(),
                version=version,
                publication_date=None,
                authority=authority,
                scope=scope,
                locator=str(path.relative_to(workspace_root)),
                payload=payload,
                chunks=chunks,
            )

        archive_sources = [
            (workspace_root / "src.zip", "README.md", "模型推理程序说明", "模型程序包", "2026-src", "原始程序结构与运行方式"),
            (workspace_root / "src.zip", "main.py", "模型推理主程序", "模型程序包", "2026-src", "原始推理入口、模型结构与预处理"),
            (workspace_root / "research_reproduction.zip", "MODEL_RESOURCES.md", "模型资源说明", "复现实验包", "2026-reproduction", "候选模型资源与权重来源"),
            (workspace_root / "research_reproduction.zip", "REPRODUCE.md", "复现实验指南", "复现实验包", "2026-reproduction", "环境、数据审计与实验复现流程"),
            (workspace_root / "research_reproduction.zip", "reference_results/oof/final_model_selection.json", "最终模型筛选记录", "复现实验结果", "2026-reference", "候选模型工程筛选结果"),
            (workspace_root / "research_reproduction.zip", "reference_results/oof/oof_metrics.json", "折外预测指标", "复现实验结果", "2026-reference", "候选模型OOF性能指标"),
            (workspace_root / "research_reproduction.zip", "reference_results/audit/audit_summary.json", "数据审计汇总", "复现实验结果", "2026-reference", "重复样本、冲突与有效样本统计"),
        ]
        opened_archives: dict[Path, zipfile.ZipFile] = {}
        try:
            for archive_path, entry, title, authority, version, scope in archive_sources:
                archive = opened_archives.setdefault(archive_path, zipfile.ZipFile(archive_path))
                payload = archive.read(entry)
                text = payload.decode("utf-8", errors="replace")
                chunks = [(section, None, content) for section, content in _chunk_text(text)]
                _upsert_source(
                    connection,
                    title=title,
                    source_type="ZIP_ENTRY",
                    version=version,
                    publication_date="2026",
                    authority=authority,
                    scope=scope,
                    locator=f"{archive_path.name}::{entry}",
                    payload=payload,
                    chunks=chunks,
                )
        finally:
            for archive in opened_archives.values():
                archive.close()

        connection.execute("PRAGMA optimize")
        source_count = connection.execute("SELECT COUNT(*) FROM evidence_sources").fetchone()[0]
        chunk_count = connection.execute("SELECT COUNT(*) FROM evidence_chunks").fetchone()[0]
    return {"sources": source_count, "chunks": chunk_count}


def _query_terms(question: str) -> list[str]:
    lowered = question.lower()
    terms = {term for term in DOMAIN_TERMS if term in lowered}
    terms.update(re.findall(r"[a-z][a-z0-9_.%-]{2,}|\d+(?:\.\d+)?%?", lowered))
    matched_triggers = [trigger for trigger in EXPANSIONS if trigger in lowered]
    has_specific_trigger = any(trigger not in {"表现", "性能"} for trigger in matched_triggers)
    for trigger in matched_triggers:
        if has_specific_trigger and trigger in {"表现", "性能"}:
            continue
        additions = EXPANSIONS[trigger]
        if trigger in lowered:
            terms.update(item.lower() for item in additions)
    if not terms:
        chinese_runs = re.findall(r"[\u4e00-\u9fff]{2,8}", question)
        terms.update(chinese_runs[:5])
    return sorted(terms, key=len, reverse=True)


def _score_text(text: str, title: str, terms: list[str]) -> float:
    lowered = text.lower()
    title_lower = title.lower()
    score = 0.0
    for term in terms:
        occurrences = min(lowered.count(term), 5)
        if re.fullmatch(r"\d+(?:\.\d+)?%?", term):
            weight = 5.0
        else:
            weight = min(6.0, max(1.0, len(term) / 2.5))
        score += occurrences * weight
        if term in title_lower:
            score += 4.0
    return score


def _best_excerpt(content: str, terms: list[str], max_chars: int = 360) -> str:
    sentences = [item.strip() for item in re.split(r"(?<=[。！？；])", content) if item.strip()]
    def sentence_quality(sentence: str) -> float:
        score = _score_text(sentence, "", terms) * 10
        if any(marker in sentence for marker in ("因此", "但", "然而", "表明", "结果", "最终", "由于", "需要")):
            score += 8
        if 45 <= len(sentence) <= max_chars:
            score += 5
        if not any(mark in sentence for mark in "。！？；，") and sum(character.isdigit() for character in sentence) > 6:
            score -= 12
        return score
    qualities = [sentence_quality(sentence) for sentence in sentences]
    eligible = [index for index, sentence in enumerate(sentences) if 12 <= len(sentence) <= max_chars]
    if eligible:
        best_index = max(eligible, key=lambda index: (qualities[index], len(sentences[index])))
        selected_parts = [sentences[best_index]]
        for neighbor in (best_index - 1, best_index + 1):
            if 0 <= neighbor < len(sentences) and _score_text(sentences[neighbor], "", terms) > 0:
                candidate = " ".join(
                    [sentences[neighbor], *selected_parts] if neighbor < best_index else [*selected_parts, sentences[neighbor]]
                )
                if len(candidate) <= max_chars:
                    selected_parts = [candidate]
        return selected_parts[0]

    ranked = sorted(sentences or [content], key=sentence_quality, reverse=True)
    selected = ranked[0]
    matching_terms = [term for term in terms if term in selected.lower()]
    if matching_terms:
        anchor = selected.lower().find(max(matching_terms, key=len))
        start = max(0, anchor - max_chars // 3)
        return selected[start:start + max_chars].strip()
    return selected[:max_chars].strip()


def _excerpt_rank(excerpt: str, terms: list[str], base_score: float) -> float:
    """Prefer decision-bearing prose over a table that merely mentions a model."""
    score = base_score + _score_text(excerpt, "", terms) * 2
    decision_markers = (
        "因此", "最终", "最优", "唯一", "合理性", "但", "然而",
        "下降", "提高", "仍需", "限定", "不能", "不予保留",
    )
    score += sum(4 for marker in decision_markers if marker in excerpt)
    if re.match(r"^(?:表\s*A?\d+|A\d+(?:\.\d+)*)", excerpt):
        score -= 8
    digit_count = sum(character.isdigit() for character in excerpt)
    if digit_count > 24:
        score -= 20
    if len(excerpt) > 300 and any(marker in excerpt for marker in ("∑", "arg max", '"candidate_')):
        score -= 20
    return score


def _authority_rank(authority: str) -> float:
    return {
        "模型方法研究论文": 12.0,
        "模型程序包": 4.0,
        "模型方法研究论文": 12.0,
        "内部任务说明": -20.0,
        "复现实验结果": 8.0,
        "复现实验包": 5.0,
        "程序提交包": 4.0,
        "模型清单": 6.0,
        "模型卡": 14.0,
        "模型治理": 12.0,
        "项目文档": 6.0,
    }.get(authority, 0.0)


def retrieve_evidence(database_path: Path, *, question: str, limit: int = 5) -> dict:
    """Retrieve traceable evidence without requiring or mutating a CT task.

    This is the shared retrieval boundary for the review workflow and the
    general medical Agent. It intentionally returns source metadata and short
    excerpts only; callers decide how (or whether) an LLM may use them.
    """
    clean_question = question.strip()
    terms = _query_terms(clean_question)
    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT c.chunk_id, c.section, c.page_number, c.content,
                   s.source_id, s.title, s.source_type, s.version,
                   s.publication_date, s.authority, s.scope, s.locator, s.sha256, s.metadata_json
            FROM evidence_chunks c
            JOIN evidence_sources s ON s.source_id = c.source_id
            WHERE s.retrieval_enabled = 1
            """
        ).fetchall()

    candidates = []
    clinical_intent = any(term in clean_question for term in ("形态", "细胞", "病理", "征象", "磨玻璃", "空洞", "治疗", "靶向", "免疫", "筛查", "随访", "分型"))
    project_intent = any(term in clean_question.lower() for term in ("resnet", "最终选择", "五折模型概率", "程序包", "上传", "api", "数据去重"))
    for row in rows:
        base_score = _score_text(row["content"], row["title"], terms)
        if base_score <= 0:
            continue
        excerpt = _best_excerpt(row["content"], terms)
        rank = _excerpt_rank(excerpt, terms, base_score) + _authority_rank(row["authority"])
        metadata = json.loads(row["metadata_json"] or "{}")
        if metadata.get("public_hidden"):
            continue
        if clinical_intent and not project_intent:
            rank += (30 if metadata.get("category") in {"guideline", "pathology", "ct_features", "prediction"}
                     else 10 if metadata.get("review_status") == "USER_REVIEWED" else -15)
            if any(term in clean_question for term in ("治疗", "靶向", "免疫")) and metadata.get("category") == "guideline":
                rank += 18
        if row["source_type"] == "MEDICAL_NOTE":
            excerpt = f"【文献整理摘要，非原文；{row['publication_date']}；{metadata.get('evidence_level', '研究参考')}】{excerpt}\n适用限制：{metadata.get('limitations', '需查阅原文并由医生复核')}"
        elif row["source_type"] == "ONLINE_PAPER":
            excerpt = f"【用户核对笔记，非原文或临床审定；{row['publication_date']}】{excerpt}"
        normalized_excerpt = public_text(excerpt)
        if normalized_excerpt != excerpt:
            normalized_excerpt = "【研究资料节选，展示名称已规范化；非临床验证】" + normalized_excerpt
        candidates.append((row, normalized_excerpt, rank))

    evidence = []
    seen: set[tuple[str, str]] = set()
    for row, excerpt, score in sorted(candidates, key=lambda item: item[2], reverse=True):
        identity = (row["source_id"], excerpt)
        if identity in seen:
            continue
        seen.add(identity)
        evidence.append(
            public_payload({
                "citation_id": f"E{len(evidence) + 1}",
                "chunk_id": row["chunk_id"],
                "source_id": row["source_id"],
                "title": row["title"],
                "source_type": row["source_type"],
                "version": row["version"],
                "publication_date": row["publication_date"],
                "authority": row["authority"],
                "scope": row["scope"],
                "locator": row["locator"],
                "page_number": row["page_number"],
                "section": row["section"],
                "sha256": row["sha256"],
                "excerpt": excerpt,
                "score": round(score, 3),
                "source_metadata": {key: value for key, value in json.loads(row["metadata_json"] or "{}").items()
                                    if key not in {"owner_user_id", "previous_note", "review_note", "upstream_hash"}},
            })
        )
        if len(evidence) >= max(1, min(limit, 12)):
            break
    return {"question": clean_question, "terms": terms, "evidence": evidence}


def answer_evidence_question(
    database_path: Path,
    *,
    task_id: str,
    question: str,
    include_in_report: bool,
    persist: bool = True,
) -> dict:
    clean_question = question.strip()
    created_at = datetime.now(timezone.utc).isoformat()
    query_id = f"EV-{uuid.uuid4().hex[:10].upper()}"
    if any(pattern in clean_question for pattern in UNSAFE_PATTERNS):
        result = {
            "query_id": query_id,
            "task_id": task_id,
            "question": clean_question,
            "support_level": "REFUSED",
            "answer": "该问题要求患者级诊断或治疗决策，超出本地循证 Agent 的安全边界。请由具备资质的临床团队结合完整病史、影像、病理和指南作出判断。",
            "evidence": [],
            "limitations": ["当前知识库不提供患者级诊断、分期、处方或治疗方案"],
            "created_at": created_at,
        }
    else:
        evidence = retrieve_evidence(
            database_path, question=clean_question, limit=5
        )["evidence"]

        if not evidence:
            support = "INSUFFICIENT"
            answer = "当前本地资料无法为这个问题提供可定位证据。请补充权威指南或论文后再检索，不能依据模型输出自行推断。"
        else:
            support = "SUPPORTED" if len(evidence) >= 2 or evidence[0]["score"] >= 18 else "PARTIALLY_SUPPORTED"
            statements = [f"- {item['excerpt']} [{item['citation_id']}]" for item in evidence[:3]]
            answer = "基于本地已核验资料，可提取以下信息：\n" + "\n".join(statements)
        result = {
            "query_id": query_id,
            "task_id": task_id,
            "question": clean_question,
            "support_level": support,
            "answer": answer,
            "evidence": evidence,
            "limitations": [
                "资料覆盖模型方法文档、医学文献整理要点与已启用笔记；文献摘要和笔记不是原文或临床审定",
                "回答采用抽取式证据组合，不生成患者级临床结论",
            ],
            "created_at": created_at,
        }

    if persist:
        with connect(database_path) as connection:
            connection.execute(
                """
                INSERT INTO evidence_queries (
                    query_id, task_id, question, support_level, answer_json, include_in_report, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    query_id, task_id, clean_question, result["support_level"],
                    json.dumps(result, ensure_ascii=False), int(include_in_report), created_at,
                ),
            )
    result["include_in_report"] = include_in_report
    return result


def evidence_history(database_path: Path, task_id: str) -> list[dict]:
    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT answer_json, include_in_report FROM evidence_queries
            WHERE task_id = ? ORDER BY created_at DESC
            """,
            (task_id,),
        ).fetchall()
    items = []
    for row in rows:
        item = json.loads(row["answer_json"])
        item["include_in_report"] = bool(row["include_in_report"])
        items.append(item)
    return items


def knowledge_sources(database_path: Path) -> dict:
    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT s.*, COUNT(c.chunk_id) AS chunk_count
            FROM evidence_sources s LEFT JOIN evidence_chunks c ON c.source_id = s.source_id
            GROUP BY s.source_id ORDER BY s.authority, s.title
            """
        ).fetchall()
    rows = [row for row in rows if not json.loads(row["metadata_json"] or "{}").get("public_hidden")]
    return {
        "items": [{**{key: row[key] for key in row.keys() if key != "metadata_json"},
                   "retrieval_enabled": bool(row["retrieval_enabled"]),
                   "metadata": json.loads(row["metadata_json"] or "{}")} for row in rows],
        "counts": {
            "sources": len(rows),
            "chunks": sum(row["chunk_count"] for row in rows),
            "active_sources": sum(bool(row["retrieval_enabled"]) for row in rows),
        },
        "scope": "本机共享资料库：模型方法资料、医学文献整理摘要及经用户核对启用的笔记。未启用条目不进入RAG；资料不代表临床审定或模型已重新训练。",
    }
