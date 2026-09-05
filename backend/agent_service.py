"""Grounded medical RAG orchestration for LungSight.

The pipeline is deliberately narrow: sanitize user input, enforce medical
safety boundaries, retrieve local evidence, ask one provider for a structured
answer, verify every citation, and persist the complete trace.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from openai import OpenAI

from knowledge import retrieve_evidence
from medical_policy import (
    MEDICAL_DISCLAIMER, MEDICAL_RESPONSE_SCHEMA, MODES, assess_open_medical_risk,
    medical_prompt, normalize_medical_response, refusal_payload,
)


DISCLAIMER = (
    "本回答仅依据当前本地知识库与已保存的CT结构化结果生成，用于科研和辅助信息整理；"
    "不构成诊断、处方或治疗建议，不能替代具备资质的临床医生。"
)

EMERGENCY_PATTERNS = (
    "呼吸困难", "无法呼吸", "意识丧失", "昏迷", "持续胸痛", "大量咯血",
    "咯血不止", "血氧很低", "急救", "拨打120", "call 120",
)
DECISION_PATTERNS = (
    "确诊", "诊断为", "我是不是", "患者是不是", "这个患者是", "分期",
    "处方", "开药", "用药剂量", "吃多少", "停药", "换药", "治疗方案",
    "怎么治疗", "是否需要手术", "要不要手术", "放疗方案", "化疗方案",
    "能活多久", "预后多久",
)

PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("EMAIL", re.compile(r"(?<![A-Z0-9._%+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![A-Z0-9.-])", re.I)),
    ("PHONE", re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")),
    ("NATIONAL_ID", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
    ("PATIENT_ID", re.compile(r"(?i)(?:姓名|住院号|门诊号|病历号|patient\s*id)\s*[:：]\s*[\w\-\u4e00-\u9fff]{2,30}")),
)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect(database_path: Path):
    connection = sqlite3.connect(database_path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_agent_schema(database_path: Path) -> None:
    with connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS agent_conversations (
                conversation_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                linked_task_id TEXT,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_message_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id),
                FOREIGN KEY(linked_task_id) REFERENCES analysis_tasks(task_id)
            );
            CREATE TABLE IF NOT EXISTS agent_messages (
                message_id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                support_level TEXT,
                risk_level TEXT,
                provider TEXT,
                model TEXT,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                latency_ms REAL NOT NULL DEFAULT 0,
                retrieval_query TEXT,
                safety_json TEXT NOT NULL DEFAULT '{}',
                response_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES agent_conversations(conversation_id),
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            );
            CREATE TABLE IF NOT EXISTS agent_message_citations (
                citation_row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT NOT NULL,
                citation_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                title TEXT NOT NULL,
                excerpt TEXT NOT NULL,
                locator TEXT NOT NULL,
                page_number INTEGER,
                section TEXT,
                score REAL NOT NULL DEFAULT 0,
                verified INTEGER NOT NULL DEFAULT 0,
                UNIQUE(message_id, citation_id),
                FOREIGN KEY(message_id) REFERENCES agent_messages(message_id)
            );
            CREATE TABLE IF NOT EXISTS agent_usage_records (
                usage_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                total_tokens INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id),
                FOREIGN KEY(conversation_id) REFERENCES agent_conversations(conversation_id),
                FOREIGN KEY(message_id) REFERENCES agent_messages(message_id)
            );
            CREATE TABLE IF NOT EXISTS agent_audit_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                conversation_id TEXT,
                message_id TEXT,
                event_type TEXT NOT NULL,
                details_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id),
                FOREIGN KEY(conversation_id) REFERENCES agent_conversations(conversation_id),
                FOREIGN KEY(message_id) REFERENCES agent_messages(message_id)
            );
            CREATE TABLE IF NOT EXISTS rag_evaluation_runs (
                run_id TEXT PRIMARY KEY,
                user_id TEXT,
                dataset_version TEXT NOT NULL,
                total_cases INTEGER NOT NULL,
                passed_cases INTEGER NOT NULL,
                faithfulness_score REAL NOT NULL,
                citation_score REAL NOT NULL,
                refusal_score REAL NOT NULL,
                privacy_score REAL NOT NULL,
                overall_score REAL NOT NULL,
                results_json TEXT NOT NULL,
                completed_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_agent_conversations_user_updated
                ON agent_conversations(user_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_agent_messages_conversation_created
                ON agent_messages(conversation_id, created_at ASC);
            CREATE INDEX IF NOT EXISTS idx_agent_citations_message
                ON agent_message_citations(message_id, ordinal ASC);
            CREATE INDEX IF NOT EXISTS idx_agent_usage_user_created
                ON agent_usage_records(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_agent_audit_user_created
                ON agent_audit_events(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_rag_evaluation_completed
                ON rag_evaluation_runs(completed_at DESC);
            """
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(agent_conversations)")}
        if "pinned_at" not in columns:
            connection.execute("ALTER TABLE agent_conversations ADD COLUMN pinned_at TEXT")
        connection.execute("PRAGMA optimize")


def deidentify(text: str) -> tuple[str, dict]:
    sanitized = text.strip()
    counts: dict[str, int] = {}
    for label, pattern in PII_PATTERNS:
        sanitized, count = pattern.subn(f"[{label}_REDACTED]", sanitized)
        if count:
            counts[label] = count
    return sanitized, {"redaction_count": sum(counts.values()), "redaction_types": sorted(counts)}


def assess_medical_risk(question: str) -> dict:
    lowered = question.lower()
    emergency = [item for item in EMERGENCY_PATTERNS if item.lower() in lowered]
    decisions = [item for item in DECISION_PATTERNS if item.lower() in lowered]
    if emergency:
        return {
            "allowed": False,
            "risk_level": "HIGH",
            "category": "EMERGENCY",
            "matched_rules": emergency,
            "message": "描述中可能存在紧急危险信号。请立即联系当地急救服务（中国大陆请拨打120）或前往急诊，不要等待Agent判断。",
        }
    if decisions:
        return {
            "allowed": False,
            "risk_level": "HIGH",
            "category": "CLINICAL_DECISION",
            "matched_rules": decisions,
            "message": "该问题要求患者级诊断、处方或治疗决策，超出本Agent的安全边界。请由具备资质的临床团队结合完整病史、影像、病理及适用指南判断。",
        }
    return {"allowed": True, "risk_level": "LOW", "category": "INFORMATION", "matched_rules": []}


@dataclass
class ProviderResult:
    payload: dict
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class LLMProvider(Protocol):
    name: str
    model: str

    def answer(self, *, question: str, evidence: list[dict], history: list[dict], mode: str = "grounded") -> ProviderResult:
        ...


AGENT_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "answer": {"type": "string"},
        "support_level": {"type": "string", "enum": ["SUPPORTED", "PARTIALLY_SUPPORTED", "INSUFFICIENT"]},
        "risk_level": {"type": "string", "enum": ["LOW", "MEDIUM"]},
        "uncertainty": {"type": "array", "items": {"type": "string"}},
        "next_steps": {"type": "array", "items": {"type": "string"}},
        "citation_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["answer", "support_level", "risk_level", "uncertainty", "next_steps", "citation_ids"],
}


def _grounding_prompt() -> str:
    return (
        "你是LungSight医学循证信息Agent。只能依据提供的证据回答，不得使用外部知识补全。"
        "不得诊断、开药或制定治疗方案。每个事实必须由citation_ids中的证据支持；证据不足时明确说明。"
        "不要输出原始个人信息。使用谨慎、清晰的中文，并区分模型分类结果与临床诊断。"
    )


def _grounding_payload(question: str, evidence: list[dict], history: list[dict]) -> dict:
    return {
        "question": question,
        "recent_history": history[-6:],
        "evidence": [
            {
                "citation_id": item["citation_id"], "title": item["title"],
                "page_number": item.get("page_number"),
                "excerpt": item["excerpt"],
            }
            for item in evidence
        ],
    }


def _parse_json_payload(content: str) -> dict:
    clean = (content or "").strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", clean, flags=re.I)
    start, end = clean.find("{"), clean.rfind("}")
    if start < 0 or end < start:
        raise json.JSONDecodeError("没有找到JSON对象", clean, 0)
    return json.loads(clean[start:end + 1])


class OpenAIProvider:
    name = "openai"

    def __init__(self, *, api_key: str, model: str) -> None:
        self.model = model
        self.client = OpenAI(api_key=api_key, timeout=45.0, max_retries=1)

    def answer(self, *, question: str, evidence: list[dict], history: list[dict], mode: str = "grounded") -> ProviderResult:
        response = self.client.responses.create(
            model=self.model,
            store=False,
            input=[
                {"role": "developer", "content": _grounding_prompt() if mode == "grounded" else medical_prompt(mode)},
                {"role": "user", "content": json.dumps(_grounding_payload(question, evidence, history), ensure_ascii=False)},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "lungsight_grounded_answer",
                    "strict": True,
                    "schema": AGENT_RESPONSE_SCHEMA if mode == "grounded" else MEDICAL_RESPONSE_SCHEMA,
                }
            },
        )
        refused = any(
            getattr(part, "type", None) == "refusal"
            for item in getattr(response, "output", [])
            for part in (getattr(item, "content", None) or [])
        )
        payload = _provider_refusal(mode) if refused else json.loads(response.output_text)
        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", input_tokens + output_tokens) or 0)
        return ProviderResult(payload, input_tokens, output_tokens, total_tokens)

    def check_connection(self) -> None:
        self.client.models.retrieve(self.model)


class OpenAICompatibleChatProvider:
    """Kimi/DeepSeek adapter using their official OpenAI-compatible endpoints."""

    def __init__(self, *, name: str, api_key: str, model: str, base_url: str) -> None:
        self.name = name
        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=45.0, max_retries=1)

    def answer(self, *, question: str, evidence: list[dict], history: list[dict], mode: str = "grounded") -> ProviderResult:
        schema = AGENT_RESPONSE_SCHEMA if mode == "grounded" else MEDICAL_RESPONSE_SCHEMA
        schema_instruction = "只输出一个JSON对象，不要使用Markdown代码块。必须符合此JSON Schema：" + json.dumps(schema, ensure_ascii=False)
        completion = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": f"{_grounding_prompt() if mode == 'grounded' else medical_prompt(mode)}{schema_instruction}"},
                {"role": "user", "content": json.dumps(_grounding_payload(question, evidence, history), ensure_ascii=False)},
            ],
            temperature=0.1,
        )
        message = completion.choices[0].message
        payload = _provider_refusal(mode) if getattr(message, "refusal", None) else _parse_json_payload(message.content or "")
        usage = getattr(completion, "usage", None)
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total_tokens = int(getattr(usage, "total_tokens", input_tokens + output_tokens) or 0)
        return ProviderResult(payload, input_tokens, output_tokens, total_tokens)

    def check_connection(self) -> None:
        self.client.models.list()


def create_llm_provider(*, provider: str, api_key: str, model: str) -> LLMProvider:
    if provider == "openai":
        return OpenAIProvider(api_key=api_key, model=model)
    if provider == "kimi":
        return OpenAICompatibleChatProvider(
            name="kimi", api_key=api_key, model=model, base_url="https://api.moonshot.cn/v1"
        )
    if provider == "deepseek":
        return OpenAICompatibleChatProvider(
            name="deepseek", api_key=api_key, model=model, base_url="https://api.deepseek.com"
        )
    raise ValueError("暂不支持该模型服务商")


def _provider_refusal(mode: str) -> dict:
    if mode == "grounded":
        return _local_response(support_level="REFUSED", risk_level="HIGH", answer="模型服务未能安全回答本问题。",
                               uncertainty=[], next_steps=[])
    return {"medical_relevance": True, "safety_action": "refuse", "medical_answer": "",
            "local_evidence": [], "uncertainty": [], "next_steps": []}


class MockLLMProvider:
    """Deterministic provider for tests and RAG regression only."""

    name = "mock-openai"
    model = "mock-gpt"

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def answer(self, *, question: str, evidence: list[dict], history: list[dict], mode: str = "grounded") -> ProviderResult:
        self.calls.append({"question": question, "evidence": evidence, "history": history, "mode": mode})
        selected = evidence[:2]
        if mode != "grounded":
            return ProviderResult({
                "medical_relevance": True, "safety_action": "answer",
                "medical_answer": "这是模拟医学知识解读，用于离线流程测试，不是实际医学建议。",
                "local_evidence": [{"citation_id": item["citation_id"], "quote": item["excerpt"]} for item in selected],
                "uncertainty": ["模拟回答不用于临床"], "next_steps": ["请核查适用的医学资料"],
            }, input_tokens=64, output_tokens=32, total_tokens=96)
        answer = "\n".join(f"{item['excerpt']} [{item['citation_id']}]" for item in selected)
        return ProviderResult(
            {
                "answer": answer,
                "support_level": "SUPPORTED" if len(selected) > 1 else "PARTIALLY_SUPPORTED",
                "risk_level": "LOW",
                "uncertainty": ["仅覆盖当前本地证据范围"],
                "next_steps": ["结合原始材料复核引用上下文"],
                "citation_ids": [item["citation_id"] for item in selected],
            },
            input_tokens=64,
            output_tokens=32,
            total_tokens=96,
        )


def _audit(connection: sqlite3.Connection, *, user_id: str, event_type: str,
           conversation_id: str | None = None, message_id: str | None = None,
           details: dict | None = None) -> None:
    connection.execute(
        """INSERT INTO agent_audit_events
           (user_id, conversation_id, message_id, event_type, details_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_id, conversation_id, message_id, event_type,
         json.dumps(details or {}, ensure_ascii=False), iso_now()),
    )


def create_conversation(database_path: Path, *, user_id: str, title: str = "新对话",
                        linked_task_id: str | None = None) -> dict:
    now = iso_now()
    conversation_id = f"CONV-{uuid.uuid4().hex[:12].upper()}"
    clean_title = (title.strip() or "新对话")[:80]
    with connect(database_path) as connection:
        connection.execute(
            """INSERT INTO agent_conversations
               (conversation_id, user_id, title, linked_task_id, created_at, updated_at, last_message_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (conversation_id, user_id, clean_title, linked_task_id, now, now, now),
        )
        _audit(connection, user_id=user_id, conversation_id=conversation_id,
               event_type="CONVERSATION_CREATED", details={"linked_task_id": linked_task_id})
        connection.commit()
    return {"conversation_id": conversation_id, "title": clean_title,
            "linked_task_id": linked_task_id, "status": "ACTIVE",
            "created_at": now, "updated_at": now, "last_message_at": now,
            "message_count": 0, "pinned_at": None}


def list_conversations(database_path: Path, *, user_id: str, limit: int = 50) -> list[dict]:
    with connect(database_path) as connection:
        rows = connection.execute(
            """SELECT c.*, COUNT(m.message_id) AS message_count
               FROM agent_conversations c
               LEFT JOIN agent_messages m ON m.conversation_id = c.conversation_id
               WHERE c.user_id = ? AND c.status = 'ACTIVE'
               GROUP BY c.conversation_id
               ORDER BY (c.pinned_at IS NOT NULL) DESC, c.pinned_at DESC,
                        c.last_message_at DESC, c.conversation_id ASC LIMIT ?""",
            (user_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def _owned_conversation(connection: sqlite3.Connection, conversation_id: str,
                        user_id: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM agent_conversations WHERE conversation_id = ? AND user_id = ? AND status = 'ACTIVE'",
        (conversation_id, user_id),
    ).fetchone()
    if row is None:
        raise LookupError("对话不存在")
    return row


def get_conversation(database_path: Path, *, user_id: str, conversation_id: str) -> dict:
    with connect(database_path) as connection:
        conversation = _owned_conversation(connection, conversation_id, user_id)
        rows = connection.execute(
            "SELECT * FROM agent_messages WHERE conversation_id = ? ORDER BY created_at ASC",
            (conversation_id,),
        ).fetchall()
        messages = []
        for row in rows:
            item = dict(row)
            item["safety"] = json.loads(item.pop("safety_json") or "{}")
            item["response"] = json.loads(item.pop("response_json") or "{}")
            citations = connection.execute(
                """SELECT citation_id, source_id, title, excerpt, locator, page_number,
                          section, score, verified
                   FROM agent_message_citations WHERE message_id = ? ORDER BY ordinal ASC""",
                (row["message_id"],),
            ).fetchall()
            item["citations"] = [{**dict(citation), "verified": bool(citation["verified"])} for citation in citations]
            messages.append(item)
    return {**dict(conversation), "messages": messages}


def set_conversation_pin(database_path: Path, *, user_id: str, conversation_id: str,
                         pinned: bool) -> dict:
    with connect(database_path) as connection:
        conversation = _owned_conversation(connection, conversation_id, user_id)
        pinned_at = (conversation["pinned_at"] or iso_now()) if pinned else None
        if pinned_at != conversation["pinned_at"]:
            connection.execute(
                "UPDATE agent_conversations SET pinned_at = ? WHERE conversation_id = ? AND user_id = ?",
                (pinned_at, conversation_id, user_id),
            )
            _audit(connection, user_id=user_id, conversation_id=conversation_id,
                   event_type="CONVERSATION_PINNED" if pinned else "CONVERSATION_UNPINNED")
    return {"conversation_id": conversation_id, "pinned_at": pinned_at}


def delete_conversation(database_path: Path, *, user_id: str, conversation_id: str) -> None:
    # Hide from all normal conversation APIs, retaining usage and audit evidence.
    with connect(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        conversation = connection.execute(
            """SELECT status FROM agent_conversations
               WHERE conversation_id = ? AND user_id = ? AND status IN ('ACTIVE', 'DELETED')""",
            (conversation_id, user_id),
        ).fetchone()
        if conversation is None:
            raise LookupError("对话不存在")
        if conversation["status"] == "DELETED":
            return
        connection.execute(
            """UPDATE agent_conversations SET status = 'DELETED', pinned_at = NULL, updated_at = ?
               WHERE conversation_id = ? AND user_id = ?""",
            (iso_now(), conversation_id, user_id),
        )
        _audit(connection, user_id=user_id, conversation_id=conversation_id,
               event_type="CONVERSATION_DELETED", details={"mode": "soft_delete"})


def export_conversation_text(database_path: Path, *, user_id: str, conversation_id: str,
                             purpose: str) -> dict:
    if purpose not in {"copy", "share"}:
        raise ValueError("不支持的导出用途")
    conversation = get_conversation(database_path, user_id=user_id, conversation_id=conversation_id)

    def clean(value: str) -> str:
        # Reapply privacy filtering to old titles, answers and source text as well.
        sanitized = deidentify(value)[0]
        sanitized = re.sub(r"\b(?:USR|CONV|CT)-[A-Z0-9]+\b", "[内部编号已隐藏]", sanitized)
        return re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "[密钥已隐藏]", sanitized)

    title = clean(conversation["title"])
    lines = ["LungSight 问答记录", title, "", MEDICAL_DISCLAIMER,
             "分享前请再次核对敏感信息；自动脱敏不能保证识别所有个人信息。", ""]
    for message in conversation["messages"]:
        lines.extend(["提问" if message["role"] == "user" else "LungSight Agent", clean(message["content"])])
        if message["role"] == "assistant":
            support = {"SUPPORTED": "证据支持", "PARTIALLY_SUPPORTED": "部分支持",
                       "INSUFFICIENT": "证据不足", "REFUSED": "安全拒答",
                       "MIXED": "本地摘录 + 模型解读", "GENERAL_KNOWLEDGE": "模型通用医学知识"}.get(message.get("support_level"), "未标注")
            risk = {"LOW": "低", "MEDIUM": "中", "HIGH": "高"}.get(message.get("risk_level"), "未标注")
            lines.append(f"支持程度：{support}；风险等级：{risk}")
            uncertainty = message.get("response", {}).get("uncertainty", [])
            if isinstance(uncertainty, list):
                lines.extend(f"不确定性：{clean(item)}" for item in uncertainty if isinstance(item, str))
            for citation in message["citations"]:
                page = f" · 第{citation['page_number']}页" if citation.get("page_number") is not None else ""
                state = "来源已核验（仅定位，非临床验证）" if citation["verified"] else "未核验"
                lines.append(f"[{clean(citation['citation_id'])}] {clean(citation['title'])}{page} · {state}")
                lines.append(clean(citation["excerpt"]))
        lines.append("")
    if not conversation["messages"]:
        lines.append("本对话暂无问答内容。")
    with connect(database_path) as connection:
        _audit(connection, user_id=user_id, conversation_id=conversation_id,
               event_type="CONVERSATION_EXPORT_PREPARED", details={"purpose": purpose})
    return {"title": title, "text": "\n".join(lines),
            "filename": f"LungSight-问答记录-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.txt"}


def usage_summary(database_path: Path, *, user_id: str) -> dict:
    with connect(database_path) as connection:
        row = connection.execute(
            """SELECT COUNT(*) AS calls, COALESCE(SUM(input_tokens),0) AS input_tokens,
                      COALESCE(SUM(output_tokens),0) AS output_tokens,
                      COALESCE(SUM(total_tokens),0) AS total_tokens
               FROM agent_usage_records WHERE user_id = ?""",
            (user_id,),
        ).fetchone()
    return dict(row)


def _synthetic_ct_evidence(ct_context: dict | None) -> list[dict]:
    if not ct_context:
        return []
    probability = ct_context.get("top_probability")
    probability_text = f"，模型概率 {probability:.1%}" if isinstance(probability, (float, int)) else ""
    probability_items = ct_context.get("probabilities") or {}
    probability_summary = "；".join(
        f"{name}={value:.1%}" for name, value in probability_items.items()
        if isinstance(value, (int, float))
    ) or "未记录"
    reliability_warnings = "；".join(ct_context.get("reliability_warnings") or []) or "无"
    quality_warnings = "；".join(ct_context.get("quality_warnings") or []) or "无"
    attention_scope = ct_context.get("attention_scope") or "注意力图仅表示模型关注区域，不等同于病灶定位或分割"
    prediction_decision = ct_context.get("prediction_decision", "INDETERMINATE")
    applicability = ct_context.get("applicability") or {}
    decision_text = "达到内部研究排序门槛" if prediction_decision == "RESEARCH_RANKING" else "已触发拒判"
    excerpt = (
        f"CT任务 {ct_context['task_id']} 的结构化模型结果为“{ct_context.get('top_class_cn', '未知')}”"
        f"{probability_text}，可靠性标记为 {ct_context.get('reliability_level', '未知')}，"
        f"复核状态为 {ct_context.get('status', '未知')}，单图决策为 {prediction_decision}（{decision_text}）。"
        "这里的类别名称只是闭集模型内部排序，不是病理诊断、患癌概率或细胞形态识别结果。"
    )
    excerpt += (
        f" 四类概率：{probability_summary}。质控：{ct_context.get('quality_status', '未知')}；"
        f"五折一致性：{ct_context.get('fold_agreement', '未知')}；前两类概率差：{ct_context.get('top_two_margin', '未记录')}；"
        f"可靠性提示：{reliability_warnings}；质控提示：{quality_warnings}。"
        f"解释方法：{ct_context.get('attention_method') or '未记录'}；解释边界：{attention_scope}。"
        f"医生复核决定：{ct_context.get('review_decision') or '尚未复核'}；"
        f"医生修正分类：{ct_context.get('corrected_class_cn') or '无修正记录'}。"
        "原始预测与医生修正不得混淆，最终诊断仍须临床和病理确认。"
        "原始CT像素不会发送给大模型；大模型只能解释上述结构化输出与检索资料，不能独立阅片。"
    )
    applicability_reasons = "；".join(applicability.get("reasons") or [])
    if applicability_reasons:
        excerpt += f" 适用性限制：{applicability_reasons}。"
    series = ct_context.get("series_context") or {}
    if series:
        series_prediction = series.get("prediction") or {}
        series_summary = series.get("summary") or {}
        series_reliability = series.get("reliability") or {}
        series_gate = series.get("quality_gate") or {}
        series_applicability = series.get("applicability") or {}
        series_probabilities = "；".join(
            f"{name}={value:.1%}" for name, value in (series_prediction.get("probabilities") or {}).items()
            if isinstance(value, (int, float))
        ) or "未记录"
        excerpt += (
            f" 当前任务是病例序列 {series.get('series_id', '未知')} 的代表切片；"
            f"病例名：{series.get('case_name', '未命名')}，成功分析"
            f"{series_summary.get('analyzed_count', '未知')}张，失败{series_summary.get('failed_count', 0)}张。"
            f"病例级内部最高排序为“{series_prediction.get('top_class_cn', '未知')}”，"
            f"决策状态 {series_prediction.get('decision', '未知')}，四类聚合概率：{series_probabilities}；"
            f"切片一致率：{series_prediction.get('slice_agreement', '未记录')}；"
            f"病例级提示：{'；'.join(series_reliability.get('warnings') or []) or '无'}。"
            f"质量门控 {series_gate.get('status', '未知')}，阻断原因：{'；'.join(series_gate.get('reasons') or []) or '无'}。"
            f"病例聚合验证状态：{series_applicability.get('case_aggregation_validated', False)}。"
            "病例聚合只是二维切片工程观察；当门控为BLOCKED或验证状态为false时，"
            "大模型不得把内部最高排序解释为病例候选、组织学类型或诊断结论。"
        )
    return [{
        "citation_id": "CT1", "chunk_id": None, "source_id": ct_context["task_id"],
        "title": f"CT结构化结果 · {ct_context['task_id']}", "source_type": "ct-structured-result",
        "version": ct_context.get("model_version", "unknown"), "publication_date": None,
        "authority": "本地模型结果", "scope": "研究原型二维CT闭集内部排序",
        "locator": f"/review?task={ct_context['task_id']}", "page_number": None,
        "section": "prediction/reliability/review", "sha256": "", "excerpt": excerpt,
        "score": 100.0,
    }]


def _local_response(*, support_level: str, risk_level: str, answer: str,
                    uncertainty: list[str], next_steps: list[str]) -> dict:
    return {
        "answer": answer, "support_level": support_level, "risk_level": risk_level,
        "uncertainty": uncertainty, "next_steps": next_steps,
        "citation_ids": [], "disclaimer": DISCLAIMER,
    }


def run_agent_chat(database_path: Path, *, user_id: str, question: str,
                   provider: LLMProvider | None, conversation_id: str | None = None,
                   linked_task_id: str | None = None, ct_context: dict | None = None,
                   mode: str = "grounded") -> dict:
    started = time.perf_counter()
    if mode not in MODES or (mode == "ct_hybrid" and (not ct_context or ct_context.get("task_id") != linked_task_id)):
        raise ValueError("问答模式与关联CT记录不一致")
    if conversation_id:
        with connect(database_path) as connection:
            existing = _owned_conversation(connection, conversation_id, user_id)
            if existing["linked_task_id"] != linked_task_id:
                raise ValueError("已有对话不能切换关联病例，请新建对话")
    sanitized, privacy = deidentify(question)
    if not sanitized:
        raise ValueError("问题不能为空")
    safety = {**(assess_medical_risk(sanitized) if mode == "grounded" else assess_open_medical_risk(sanitized)),
              **privacy, "answer_mode": mode}
    retrieval = retrieve_evidence(database_path, question=sanitized, limit=5)
    retrieved_evidence = retrieval["evidence"]
    if retrieved_evidence and retrieved_evidence[0].get("score", 0) < 8:
        retrieved_evidence = []
    evidence = _synthetic_ct_evidence(ct_context) + retrieved_evidence
    # General medical chat can answer even if local retrieval has no match.
    if safety["allowed"] and (evidence or mode != "grounded") and provider is None:
        raise LookupError("尚未配置当前模型服务商的API Key，请先在Agent右侧完成配置")

    if conversation_id is None:
        conversation = create_conversation(
            database_path, user_id=user_id, title=sanitized[:42], linked_task_id=linked_task_id
        )
        conversation_id = conversation["conversation_id"]

    user_message_id = f"MSG-{uuid.uuid4().hex[:14].upper()}"
    now = iso_now()
    with connect(database_path) as connection:
        conversation = _owned_conversation(connection, conversation_id, user_id)
        effective_task_id = linked_task_id if linked_task_id is not None else conversation["linked_task_id"]
        connection.execute(
            """INSERT INTO agent_messages
               (message_id, conversation_id, user_id, role, content, risk_level,
                retrieval_query, safety_json, response_json, created_at)
               VALUES (?, ?, ?, 'user', ?, ?, ?, ?, '{}', ?)""",
            (user_message_id, conversation_id, user_id, sanitized, safety["risk_level"],
             sanitized, json.dumps(safety, ensure_ascii=False), now),
        )
        connection.execute(
            """UPDATE agent_conversations SET linked_task_id = ?, updated_at = ?, last_message_at = ?,
                      title = CASE WHEN title = '新对话' THEN ? ELSE title END
               WHERE conversation_id = ?""",
            (effective_task_id, now, now, sanitized[:42], conversation_id),
        )
        _audit(connection, user_id=user_id, conversation_id=conversation_id,
               message_id=user_message_id, event_type="QUESTION_SANITIZED",
               details={"redaction_count": privacy["redaction_count"], "risk_category": safety["category"], "answer_mode": mode})
        connection.commit()

    if not safety["allowed"]:
        response_payload = _local_response(
            support_level="REFUSED", risk_level="HIGH", answer=safety["message"],
            uncertainty=["Agent未执行患者级诊疗判断"],
            next_steps=["由临床专业人员评估"],
        )
        if mode != "grounded":
            response_payload = refusal_payload(mode, message=safety["message"], risk=safety["risk_level"], category=safety["category"])
        provider_result = ProviderResult(response_payload)
        evidence = []
        provider_name, model = "safety-engine", "rules-v1"
    elif not evidence and mode == "grounded":
        response_payload = _local_response(
            support_level="INSUFFICIENT", risk_level="LOW",
            answer="当前知识库与关联CT结构化结果中没有足以回答该问题的可定位证据，因此不能生成结论。",
            uncertainty=["缺少可核验来源"],
            next_steps=["补充适用的权威指南、论文或结构化病例资料后再提问"],
        )
        provider_result = ProviderResult(response_payload)
        provider_name, model = "retrieval-gate", "rules-v1"
    else:
        assert provider is not None
        with connect(database_path) as connection:
            history_rows = connection.execute(
                """SELECT role, content FROM agent_messages
                   WHERE conversation_id = ? AND message_id != ?
                   ORDER BY created_at DESC LIMIT 6""",
                (conversation_id, user_message_id),
            ).fetchall()
        history = [{"role": row["role"], "content": deidentify(row["content"])[0]} for row in reversed(history_rows)]
        # Also sanitize imported evidence; raw image files and identity fields
        # are never sent to a cloud model.
        evidence = [{**item, "excerpt": deidentify(item["excerpt"])[0], "title": deidentify(item["title"])[0]} for item in evidence]
        provider_result = provider.answer(question=sanitized, evidence=evidence, history=history, mode=mode)
        response_payload = (dict(provider_result.payload) if mode == "grounded" else
                            normalize_medical_response(provider_result.payload, evidence, mode))
        response_payload["answer"] = deidentify(response_payload["answer"])[0]
        for field in ("uncertainty", "next_steps"):
            response_payload[field] = [deidentify(item)[0] for item in response_payload.get(field, [])]
        provider_name, model = provider.name, provider.model

    allowed_ids = {item["citation_id"] for item in evidence}
    claimed_ids = [item for item in response_payload.get("citation_ids", []) if item in allowed_ids]
    response_payload["citation_ids"] = list(dict.fromkeys(claimed_ids))
    response_payload["disclaimer"] = DISCLAIMER if mode == "grounded" else MEDICAL_DISCLAIMER
    response_payload["answer_mode"] = mode
    if mode != "grounded":
        safety["category"] = response_payload.get("policy_category", safety["category"])
        safety["risk_level"] = response_payload["risk_level"]
    if response_payload.get("support_level") in {"SUPPORTED", "PARTIALLY_SUPPORTED"} and not claimed_ids:
        response_payload["support_level"] = "INSUFFICIENT"
        response_payload["answer"] = "模型回答未通过引用核验，已阻止输出。请补充或重新检索证据。"
        response_payload.setdefault("uncertainty", []).append("没有通过核验的引用")

    verified_evidence = [item for item in evidence if item["citation_id"] in claimed_ids]
    assistant_message_id = f"MSG-{uuid.uuid4().hex[:14].upper()}"
    completed_at = iso_now()
    latency_ms = round((time.perf_counter() - started) * 1000, 3)
    with connect(database_path) as connection:
        connection.execute(
            """INSERT INTO agent_messages
               (message_id, conversation_id, user_id, role, content, support_level, risk_level,
                provider, model, input_tokens, output_tokens, total_tokens, latency_ms,
                retrieval_query, safety_json, response_json, created_at)
               VALUES (?, ?, ?, 'assistant', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (assistant_message_id, conversation_id, user_id, response_payload["answer"],
             response_payload["support_level"], response_payload["risk_level"], provider_name, model,
             provider_result.input_tokens, provider_result.output_tokens, provider_result.total_tokens,
             latency_ms, sanitized, json.dumps(safety, ensure_ascii=False),
             json.dumps(response_payload, ensure_ascii=False), completed_at),
        )
        for ordinal, item in enumerate(verified_evidence, start=1):
            connection.execute(
                """INSERT INTO agent_message_citations
                   (message_id, citation_id, source_id, ordinal, title, excerpt, locator,
                    page_number, section, score, verified)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (assistant_message_id, item["citation_id"], item["source_id"], ordinal,
                 item["title"], item["excerpt"], item["locator"], item.get("page_number"),
                 item.get("section"), item.get("score", 0)),
            )
        if provider_result.total_tokens:
            connection.execute(
                """INSERT INTO agent_usage_records
                   (usage_id, user_id, conversation_id, message_id, provider, model,
                    input_tokens, output_tokens, total_tokens, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (f"USE-{uuid.uuid4().hex[:12].upper()}", user_id, conversation_id,
                 assistant_message_id, provider_name, model, provider_result.input_tokens,
                 provider_result.output_tokens, provider_result.total_tokens, completed_at),
            )
        connection.execute(
            "UPDATE agent_conversations SET updated_at = ?, last_message_at = ? WHERE conversation_id = ?",
            (completed_at, completed_at, conversation_id),
        )
        _audit(connection, user_id=user_id, conversation_id=conversation_id,
               message_id=assistant_message_id, event_type="ANSWER_COMPLETED",
               details={"support_level": response_payload["support_level"],
                        "citation_count": len(verified_evidence), "provider": provider_name,
                        "latency_ms": latency_ms, "answer_mode": mode,
                        "knowledge_sources": response_payload.get("knowledge_sources", []),
                        "policy_category": safety["category"]})
        connection.commit()

    return {
        "conversation_id": conversation_id,
        "user_message_id": user_message_id,
        "message_id": assistant_message_id,
        "question": sanitized,
        **response_payload,
        "citations": verified_evidence,
        "usage": {"input_tokens": provider_result.input_tokens,
                  "output_tokens": provider_result.output_tokens,
                  "total_tokens": provider_result.total_tokens},
        "provider": provider_name, "model": model, "latency_ms": latency_ms,
        "privacy": privacy,
    }
