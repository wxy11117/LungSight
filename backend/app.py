"""LungSight 本地五折 ResNet18 推理服务。

当前服务面向研究数据同类型的二维 CT 图片，并提供保守的本地 DICOM
序列导入；不生成临床诊断、分期、处方或治疗建议。
"""

from __future__ import annotations

import base64
import hashlib
import html
import io
import json
import math
import os
import sqlite3
import sys
import threading
import time
import uuid
import zipfile
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import Cookie, Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAI
from PIL import Image, ImageFilter, ImageOps, ImageStat, UnidentifiedImageError
from pydantic import BaseModel, Field, StrictBool, model_validator

from knowledge import (
    build_bundled_knowledge_base,
    evidence_history,
    initialize_knowledge_schema,
    knowledge_sources,
    retrieve_evidence,
)
from literature import (
    TOPICS, LiteratureUnavailable, import_literature, literature_content,
    review_literature, search_literature, seed_medical_library,
)
from evaluation import (
    dataset_summary,
    get_run as get_evaluation_run,
    initialize_evaluation_schema,
    list_runs as list_evaluation_runs,
    run_evaluation,
)
from auth import (
    get_doctor_profile,
    SESSION_COOKIE_NAME,
    authenticate_user,
    create_session,
    delete_openai_credential,
    get_openai_credential_status,
    get_user_for_session,
    get_llm_settings,
    initialize_auth_schema,
    load_openai_credential,
    load_llm_credential,
    mark_llm_verification,
    mark_openai_verification,
    register_user,
    revoke_session,
    save_openai_credential,
    save_llm_credential,
    select_llm_provider,
    delete_llm_credential,
    update_display_name,
    save_avatar,
    load_avatar,
    list_local_accounts,
)
from profile_images import MAX_AVATAR_BYTES, normalize_avatar
from public_content import PublicPresentationMiddleware, apply_library_presentation, public_payload, public_text, pdf_download_name
from agent_service import (
    LLMProvider,
    OpenAIProvider,
    create_llm_provider,
    create_conversation,
    get_conversation,
    initialize_agent_schema,
    list_conversations,
    set_conversation_pin,
    delete_conversation,
    export_conversation_text,
    run_agent_chat,
    usage_summary,
)
from rag_evaluation import (
    dataset_summary as rag_dataset_summary,
    list_rag_runs,
    run_rag_evaluation,
)
from dicom_series import DicomImportError, prepare_dicom_series
from starlette.concurrency import run_in_threadpool
from analysis_jobs import JobCancelled
from image_geometry import resize_pad_geometry, restore_attention_map

MODEL_LOCK = threading.RLock()


BASE_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = BASE_DIR.parent.parent
MODEL_BUNDLE_DIR = Path(os.environ.get("LUNGSIGHT_MODEL_BUNDLE_DIR", str(BASE_DIR))).resolve()
WEIGHTS_DIR = MODEL_BUNDLE_DIR / "weights"
MANIFEST_PATH = MODEL_BUNDLE_DIR / "model_manifest.json"
DATA_DIR = Path(os.environ.get("LUNGSIGHT_DATA_DIR", str(BASE_DIR / "data"))).resolve()
UPLOADS_DIR = DATA_DIR / "uploads"
ATTENTION_DIR = DATA_DIR / "attention"
DATABASE_PATH = DATA_DIR / "lungsight.sqlite3"
EVALUATION_DATASET_PATH = BASE_DIR / "evaluation_cases.json"
RAG_EVALUATION_DATASET_PATH = BASE_DIR / "rag_evaluation_cases.json"
MAX_UPLOAD_BYTES = int(os.environ.get("LUNGSIGHT_MAX_UPLOAD_BYTES", str(20 * 1024 * 1024)))
MAX_SERIES_FILES = int(os.environ.get("LUNGSIGHT_MAX_SERIES_FILES", "64"))
MAX_DICOM_FILES = int(os.environ.get("LUNGSIGHT_MAX_DICOM_FILES", "512"))
MAX_DICOM_TOTAL_BYTES = int(os.environ.get("LUNGSIGHT_MAX_DICOM_TOTAL_BYTES", str(256 * 1024 * 1024)))
DICOM_ANALYSIS_SLICES = int(os.environ.get("LUNGSIGHT_DICOM_ANALYSIS_SLICES", "32"))
SERIES_MAX_QC_WARNING_RATIO = float(os.environ.get("LUNGSIGHT_SERIES_MAX_QC_WARNING_RATIO", "0.40"))
DICOM_MIN_LUNG_REGION_SLICES = int(os.environ.get("LUNGSIGHT_DICOM_MIN_LUNG_REGION_SLICES", "12"))
SUPPORTED_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
COOKIE_SECURE = os.environ.get("LUNGSIGHT_COOKIE_SECURE", "0") == "1"
ALLOWED_ORIGINS = [
    "http://127.0.0.1:3000", "http://localhost:3000",
    "http://127.0.0.1:5173", "http://localhost:5173",
]


def resolve_managed_media(stored_value: str | None, managed_directory: Path) -> Path | None:
    """Resolve task media inside its current managed directory.

    Older databases stored absolute paths, which break when the complete local
    application directory is moved. Task media is intentionally flat and named
    by task id, so rebinding by filename keeps old records portable while also
    preventing a database value from escaping the managed directory.
    """
    if not stored_value:
        return None
    filename = Path(stored_value).name
    if not filename or filename in {".", ".."}:
        return None
    root = managed_directory.resolve()
    candidate = (root / filename).resolve()
    if candidate.parent != root or not candidate.is_file():
        return None
    return candidate


def portable_media_value(path: Path) -> str:
    """Persist only the managed filename so the local application can move."""
    return path.name


class ProfileNameRequest(BaseModel):
    model_config = {"extra": "forbid"}
    display_name: str = Field(min_length=2, max_length=60)


class DoctorRegistrationProfile(BaseModel):
    model_config = {"extra": "forbid"}
    real_name: str = Field(min_length=2, max_length=60)
    province: str = Field(min_length=2, max_length=20)
    city: str = Field(min_length=2, max_length=60)
    hospital_id: str | None = Field(default=None, max_length=80)
    hospital_name: str = Field(min_length=2, max_length=120)
    department: str = Field(min_length=2, max_length=60)
    professional_title: str = Field(min_length=2, max_length=40)


class LoginIdentity(BaseModel):
    model_config = {"extra": "forbid"}
    email: str | None = Field(default=None, min_length=5, max_length=254)
    phone: str | None = Field(default=None, min_length=8, max_length=30)

    @model_validator(mode="after")
    def single_identity(self):
        if bool(self.email) == bool(self.phone):
            raise ValueError("请选择手机号或邮箱其中一种账号方式")
        return self


class RegisterRequest(LoginIdentity):
    display_name: str = Field(min_length=2, max_length=60)
    password: str = Field(min_length=10, max_length=128)
    confirm_password: str = Field(min_length=10, max_length=128)
    doctor_profile: DoctorRegistrationProfile
    accepted_terms: StrictBool
    accepted_privacy: StrictBool


class LoginRequest(LoginIdentity):
    password: str = Field(min_length=1, max_length=128)


class SwitchAccountRequest(BaseModel):
    model_config = {"extra": "forbid"}
    user_id: str = Field(pattern=r"^USR-[A-F0-9]{12}$")
    password: str = Field(min_length=1, max_length=128)


class OpenAICredentialRequest(BaseModel):
    api_key: str = Field(min_length=20, max_length=300)
    model: str = Field(default="gpt-5.4", min_length=2, max_length=80)


class LLMCredentialRequest(BaseModel):
    provider: Literal["openai", "kimi", "deepseek"]
    api_key: str | None = Field(default=None, min_length=12, max_length=500)
    model: str = Field(min_length=2, max_length=80)


class LLMProviderRequest(BaseModel):
    provider: Literal["openai", "kimi", "deepseek"]
    model: str | None = Field(default=None, min_length=2, max_length=80)


class ReviewRequest(BaseModel):
    decision: Literal["CONFIRM", "CORRECT", "UNDETERMINED"]
    reviewer_name: str = Field(min_length=1, max_length=80)
    corrected_class: str | None = None
    comment: str = Field(default="", max_length=1000)


class EvidenceQueryRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    include_in_report: bool = True
    conversation_id: str | None = Field(default=None, max_length=40)


class AgentConversationRequest(BaseModel):
    title: str = Field(default="新对话", max_length=80)
    linked_task_id: str | None = Field(default=None, max_length=40)


class AgentChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    conversation_id: str | None = Field(default=None, max_length=40)
    linked_task_id: str | None = Field(default=None, max_length=40)


class ConversationPinRequest(BaseModel):
    model_config = {"extra": "forbid"}
    pinned: StrictBool


class ConversationExportRequest(BaseModel):
    model_config = {"extra": "forbid"}
    purpose: Literal["copy", "share"]


class TaskLibraryActionRequest(BaseModel):
    model_config = {"extra": "forbid"}
    action: Literal["STAR", "UNSTAR", "ARCHIVE", "RESTORE"]


def require_user(
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> dict:
    user = get_user_for_session(DATABASE_PATH, session_token)
    if user is None:
        raise HTTPException(status_code=401, detail="请先登录后再进入LungSight工作区")
    return user


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def require_profile_user(user: dict = Depends(require_user), origin: str | None = Header(default=None)) -> dict:
    if origin is not None and origin not in ALLOWED_ORIGINS:
        raise HTTPException(status_code=403, detail="不允许从此来源修改账号资料")
    return user


def require_conversation_user(user: dict = Depends(require_user), origin: str | None = Header(default=None)) -> dict:
    if origin is not None and origin not in ALLOWED_ORIGINS:
        raise HTTPException(status_code=403, detail="不允许从此来源操作问答记录")
    return user


def perceptual_dhash(image: Image.Image) -> str:
    resized = image.convert("L").resize((9, 8), Image.Resampling.BILINEAR)
    pixels = list(resized.getdata())
    value = 0
    for row in range(8):
        for column in range(8):
            value = (value << 1) | int(pixels[row * 9 + column] > pixels[row * 9 + column + 1])
    return f"{value:016x}"


def hash_distance(first: str, second: str) -> int:
    return (int(first, 16) ^ int(second, 16)).bit_count()


def assess_image_quality(image: Image.Image, image_sha256: str) -> dict:
    grayscale = image.convert("L")
    stats = ImageStat.Stat(grayscale)
    mean_luminance = float(stats.mean[0])
    contrast_std = float(stats.stddev[0])
    edge_variance = float(ImageStat.Stat(grayscale.filter(ImageFilter.FIND_EDGES)).var[0])
    histogram = grayscale.histogram()
    pixel_count = max(1, image.width * image.height)
    dark_fraction = sum(histogram[:8]) / pixel_count
    bright_fraction = sum(histogram[248:]) / pixel_count
    image_dhash = perceptual_dhash(image)

    exact_duplicates = 0
    nearest_distance: int | None = None
    with database_connection() as connection:
        exact_duplicates = connection.execute(
            "SELECT COUNT(*) FROM analysis_tasks WHERE image_sha256 = ?", (image_sha256,)
        ).fetchone()[0]
        hashes = connection.execute(
            "SELECT image_dhash FROM analysis_tasks WHERE image_dhash IS NOT NULL LIMIT 5000"
        ).fetchall()
    if hashes:
        nearest_distance = min(hash_distance(image_dhash, row[0]) for row in hashes)

    warnings: list[str] = []
    if min(image.size) < 224:
        warnings.append("原图短边小于224像素，放大预处理可能损失细节")
    if contrast_std < 18:
        warnings.append("影像整体对比度偏低")
    if edge_variance < 35:
        warnings.append("影像边缘信息偏弱，可能存在模糊")
    if dark_fraction > 0.92:
        warnings.append("影像暗部占比异常偏高")
    if bright_fraction > 0.92:
        warnings.append("影像亮部占比异常偏高")
    if exact_duplicates:
        warnings.append(f"检测到{exact_duplicates}条SHA-256完全重复任务")
    elif nearest_distance is not None and nearest_distance <= 4:
        warnings.append("检测到感知哈希近似重复影像")

    return {
        "status": "WARNING" if warnings else "PASS",
        "readable": True,
        "warnings": warnings,
        "metrics": {
            "mean_luminance": round(mean_luminance, 3),
            "contrast_std": round(contrast_std, 3),
            "edge_variance": round(edge_variance, 3),
            "dark_fraction": round(dark_fraction, 6),
            "bright_fraction": round(bright_fraction, 6),
            "perceptual_dhash": image_dhash,
            "exact_duplicate_count": exact_duplicates,
            "nearest_hash_distance": nearest_distance,
        },
        "rule_version": "mvp-image-qc-v1",
    }


def assign_review_priority(quality_control: dict, prediction: dict) -> dict:
    reasons: list[str] = []
    confidence = max(prediction["mean_probability"])
    if prediction["fold_agreement"] <= 3:
        reasons.append("五折一致性不高于3/5")
    if confidence < 0.50:
        reasons.append("最高类别概率低于50%")
    if reasons:
        return {"level": "HIGH_RISK", "label_cn": "高风险人工检查", "reasons": reasons}
    if prediction["reliability"] == "REVIEW_REQUIRED":
        reasons.extend(prediction["warnings"])
    if quality_control["status"] == "WARNING":
        reasons.extend(quality_control["warnings"])
    if reasons:
        return {"level": "PRIORITY", "label_cn": "优先复核", "reasons": reasons}
    return {"level": "ROUTINE", "label_cn": "普通复核", "reasons": ["质控通过且五折输出稳定"]}


@contextmanager
def database_connection():
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
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


def initialize_database() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    ATTENTION_DIR.mkdir(parents=True, exist_ok=True)
    with database_connection() as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS analysis_tasks (
                task_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL,
                file_name TEXT NOT NULL,
                image_path TEXT NOT NULL,
                image_sha256 TEXT NOT NULL,
                top_class TEXT NOT NULL,
                top_class_cn TEXT NOT NULL,
                reliability_level TEXT NOT NULL,
                fold_agreement INTEGER NOT NULL,
                analysis_json TEXT NOT NULL,
                reviewer_name TEXT,
                review_decision TEXT,
                corrected_class TEXT,
                corrected_class_cn TEXT,
                review_comment TEXT,
                reviewed_at TEXT,
                quality_status TEXT NOT NULL DEFAULT 'PASS',
                priority TEXT NOT NULL DEFAULT 'ROUTINE',
                image_dhash TEXT,
                attention_path TEXT,
                owner_user_id TEXT,
                starred_at TEXT,
                archived_at TEXT
            )
            """
        )
        existing_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(analysis_tasks)").fetchall()
        }
        migrations = {
            "quality_status": "ALTER TABLE analysis_tasks ADD COLUMN quality_status TEXT NOT NULL DEFAULT 'PASS'",
            "priority": "ALTER TABLE analysis_tasks ADD COLUMN priority TEXT NOT NULL DEFAULT 'ROUTINE'",
            "image_dhash": "ALTER TABLE analysis_tasks ADD COLUMN image_dhash TEXT",
            "attention_path": "ALTER TABLE analysis_tasks ADD COLUMN attention_path TEXT",
            "owner_user_id": "ALTER TABLE analysis_tasks ADD COLUMN owner_user_id TEXT",
            "starred_at": "ALTER TABLE analysis_tasks ADD COLUMN starred_at TEXT",
            "archived_at": "ALTER TABLE analysis_tasks ADD COLUMN archived_at TEXT",
        }
        for column, statement in migrations.items():
            if column not in existing_columns:
                connection.execute(statement)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                from_status TEXT,
                to_status TEXT,
                actor TEXT NOT NULL,
                details_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(task_id) REFERENCES analysis_tasks(task_id)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_status_created ON analysis_tasks(status, created_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_reliability_created ON analysis_tasks(reliability_level, created_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_class_created ON analysis_tasks(top_class, created_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_priority_created ON analysis_tasks(priority, created_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_owner_created ON analysis_tasks(owner_user_id, created_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_owner_archived_created ON analysis_tasks(owner_user_id, archived_at, created_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_owner_starred ON analysis_tasks(owner_user_id, starred_at DESC) WHERE starred_at IS NOT NULL"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_task_created ON audit_events(task_id, created_at ASC)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS analysis_series (
                series_id TEXT PRIMARY KEY,
                owner_user_id TEXT NOT NULL,
                case_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL,
                aggregate_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS analysis_series_items (
                series_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                slice_index INTEGER NOT NULL,
                PRIMARY KEY(series_id, task_id),
                FOREIGN KEY(series_id) REFERENCES analysis_series(series_id),
                FOREIGN KEY(task_id) REFERENCES analysis_tasks(task_id)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_series_owner_created ON analysis_series(owner_user_id, created_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_series_items_task ON analysis_series_items(task_id)"
        )
        # Migrate legacy absolute media paths only when the matching managed
        # file is present. Missing forensic references remain untouched.
        for row in connection.execute(
            "SELECT task_id, image_path, attention_path FROM analysis_tasks"
        ).fetchall():
            image_path = resolve_managed_media(row["image_path"], UPLOADS_DIR)
            attention_path = resolve_managed_media(row["attention_path"], ATTENTION_DIR)
            image_value = portable_media_value(image_path) if image_path else row["image_path"]
            attention_value = portable_media_value(attention_path) if attention_path else row["attention_path"]
            if image_value != row["image_path"] or attention_value != row["attention_path"]:
                connection.execute(
                    "UPDATE analysis_tasks SET image_path = ?, attention_path = ? WHERE task_id = ?",
                    (image_value, attention_value, row["task_id"]),
                )
        connection.execute("PRAGMA optimize")


def row_to_task(row: sqlite3.Row) -> dict:
    task = json.loads(row["analysis_json"])
    task["status"] = row["status"]
    task["created_at"] = row["created_at"]
    task["updated_at"] = row["updated_at"]
    task["review"] = {
        "reviewer_name": row["reviewer_name"],
        "decision": row["review_decision"],
        "corrected_class": row["corrected_class"],
        "corrected_class_cn": row["corrected_class_cn"],
        "comment": row["review_comment"],
        "reviewed_at": row["reviewed_at"],
    } if row["review_decision"] else None
    quality_control = task.setdefault(
        "quality_control", {"status": row["quality_status"], "warnings": [], "metrics": {}}
    )
    quality_control.setdefault("warnings", [])
    quality_control.setdefault("metrics", {})
    task.setdefault("priority", {"level": row["priority"], "label_cn": "普通复核", "reasons": []})
    task.setdefault(
        "attention",
        {"available": bool(resolve_managed_media(row["attention_path"], ATTENTION_DIR)), "method": "Grad-CAM"},
    )
    return task


def get_task_row(task_id: str, owner_user_id: str) -> sqlite3.Row:
    with database_connection() as connection:
        row = connection.execute(
            "SELECT * FROM analysis_tasks WHERE task_id = ? AND owner_user_id = ?",
            (task_id, owner_user_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return row


def get_series_record(series_id: str, owner_user_id: str) -> dict:
    with database_connection() as connection:
        row = connection.execute(
            "SELECT aggregate_json FROM analysis_series WHERE series_id = ? AND owner_user_id = ?",
            (series_id, owner_user_id),
        ).fetchone()
        item_rows = connection.execute(
            """SELECT task.* FROM analysis_series_items item
               JOIN analysis_tasks task ON task.task_id = item.task_id
               WHERE item.series_id = ? AND task.owner_user_id = ?
               ORDER BY item.slice_index ASC""",
            (series_id, owner_user_id),
        ).fetchall() if row is not None else []
    if row is None:
        raise HTTPException(status_code=404, detail="病例序列不存在")
    result = json.loads(row["aggregate_json"])
    result["items"] = [row_to_task(item) for item in item_rows]
    return result


def persist_task(
    result: dict,
    payload: bytes,
    suffix: str,
    attention_image: Image.Image,
    owner_user_id: str,
) -> None:
    task_id = result["task_id"]
    image_path = UPLOADS_DIR / f"{task_id}{suffix}"
    attention_path = ATTENTION_DIR / f"{task_id}.png"
    image_path.write_bytes(payload)
    attention_image.save(attention_path, format="PNG", optimize=True)
    try:
        with database_connection() as connection:
            connection.execute(
                """
                INSERT INTO analysis_tasks (
                    task_id, created_at, updated_at, status, file_name, image_path,
                    image_sha256, top_class, top_class_cn, reliability_level,
                    fold_agreement, analysis_json, quality_status, priority,
                    image_dhash, attention_path, owner_user_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    result["created_at"],
                    result["created_at"],
                    result["status"],
                    result["input"]["file_name"],
                    portable_media_value(image_path),
                    result["input"]["sha256"],
                    result["prediction"]["top_class"],
                    result["prediction"]["top_class_cn"],
                    result["reliability"]["level"],
                    int(result["reliability"]["fold_agreement"].split("/")[0]),
                    json.dumps(result, ensure_ascii=False),
                    result["quality_control"]["status"],
                    result["priority"]["level"],
                    result["quality_control"]["metrics"]["perceptual_dhash"],
                    portable_media_value(attention_path),
                    owner_user_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO audit_events (
                    task_id, event_type, from_status, to_status, actor, details_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    "ANALYSIS_CREATED",
                    None,
                    result["status"],
                    "LungSight Agent",
                    json.dumps(
                        {
                            "quality_status": result["quality_control"]["status"],
                            "priority": result["priority"]["level"],
                            "top_class": result["prediction"]["top_class"],
                        },
                        ensure_ascii=False,
                    ),
                    result["created_at"],
                ),
            )
    except Exception:
        image_path.unlink(missing_ok=True)
        attention_path.unlink(missing_ok=True)
        raise


def aggregate_series_results(
    results: list[dict],
    *,
    case_name: str,
    failures: list[dict] | None = None,
    series_id: str | None = None,
    case_aggregation_validated: bool = False,
    input_mode: str = "IMAGE_SERIES",
) -> dict:
    """Aggregate research scores while refusing an unvalidated case-level conclusion."""
    if not results:
        raise ValueError("病例序列没有可聚合的有效切片")
    failures = failures or []
    classes = list(results[0]["prediction"]["probabilities"])
    class_labels = dict(zip(runtime.manifest["class_names"], runtime.manifest["class_names_cn"]))
    weighted_totals = {name: 0.0 for name in classes}
    total_weight = 0.0
    slice_votes = {name: 0 for name in classes}
    weights: list[float] = []

    for result in results:
        probabilities = result["prediction"]["probabilities"]
        agreement_text = str(result.get("reliability", {}).get("fold_agreement", "0/5"))
        try:
            fold_agreement = int(agreement_text.split("/", 1)[0])
        except (TypeError, ValueError):
            fold_agreement = 0
        quality_factor = 1.0 if result.get("quality_control", {}).get("status") == "PASS" else 0.65
        reliability_factor = 0.45 + 0.55 * max(0.0, min(1.0, fold_agreement / 5))
        weight = quality_factor * reliability_factor
        weights.append(weight)
        total_weight += weight
        top_class = result["prediction"]["top_class"]
        if top_class in slice_votes:
            slice_votes[top_class] += 1
        for name in classes:
            weighted_totals[name] += weight * float(probabilities.get(name, 0.0))

    aggregate_probabilities = {
        name: round(weighted_totals[name] / max(total_weight, 1e-8), 8) for name in classes
    }
    ranked = sorted(aggregate_probabilities.items(), key=lambda item: item[1], reverse=True)
    top_class, top_probability = ranked[0]
    top_two_margin = top_probability - ranked[1][1] if len(ranked) > 1 else top_probability
    slice_agreement = slice_votes[top_class] / len(results)
    qc_warning_count = sum(result.get("quality_control", {}).get("status") != "PASS" for result in results)
    qc_warning_ratio = qc_warning_count / len(results)

    warnings: list[str] = []
    blocking_reasons: list[str] = []
    if not case_aggregation_validated:
        blocking_reasons.append("当前模型未在病例级完整序列和肿瘤ROI上完成验证")
    if input_mode == "DICOM":
        blocking_reasons.append("DICOM肺窗派生图与训练图片的输入等价性尚未验证")
    if len(results) < 3:
        blocking_reasons.append("有效切片少于3张")
    if top_probability < 0.50:
        blocking_reasons.append("病例级最高概率低于50%")
    if top_two_margin < 0.10:
        blocking_reasons.append("病例级前两类概率差低于10%")
    if slice_agreement < 0.60:
        blocking_reasons.append("支持最高类别的切片不足60%")
    if qc_warning_ratio > SERIES_MAX_QC_WARNING_RATIO:
        blocking_reasons.append(
            f"质控异常切片占比{qc_warning_ratio * 100:.1f}%，超过{SERIES_MAX_QC_WARNING_RATIO * 100:.0f}%门槛"
        )
    warnings.extend(f"{reason}，病例级结果证据不足" for reason in blocking_reasons)
    if qc_warning_count:
        warnings.append(f"{qc_warning_count}张切片存在图像质控提示，聚合时已降低权重")
    if failures:
        warnings.append(f"{len(failures)}张文件分析失败，未纳入病例聚合")

    insufficient = bool(blocking_reasons)
    decision = "INDETERMINATE" if insufficient else "CANDIDATE"
    reliability_level = "REVIEW_REQUIRED" if warnings else "CONSISTENT"
    representative_index = max(
        range(len(results)),
        key=lambda index: weights[index] * float(results[index]["prediction"]["probabilities"].get(top_class, 0.0)),
    )
    representative = results[representative_index]
    now = datetime.now(timezone.utc).isoformat()
    return {
        "series_id": series_id or f"SER-{uuid.uuid4().hex[:10].upper()}",
        "case_name": case_name.strip() or "未命名CT病例",
        "created_at": now,
        "status": "WAITING_FOR_REVIEW",
        "input_mode": input_mode,
        "summary": {
            "uploaded_count": len(results) + len(failures),
            "analyzed_count": len(results),
            "failed_count": len(failures),
            "quality_warning_count": qc_warning_count,
            "quality_warning_ratio": round(qc_warning_ratio, 8),
        },
        "prediction": {
            "decision": decision,
            "top_class": top_class,
            "top_class_cn": class_labels.get(top_class, top_class),
            "top_probability": round(top_probability, 8),
            "probabilities": aggregate_probabilities,
            "slice_agreement": round(slice_agreement, 8),
            "slice_votes": slice_votes,
        },
        "reliability": {
            "level": reliability_level,
            "top_two_margin": round(top_two_margin, 8),
            "warnings": warnings,
            "rule_version": "case-series-weighted-v2",
        },
        "applicability": {
            "case_aggregation_validated": case_aggregation_validated,
            "clinical_candidate_allowed": False,
            "lesion_roi_available": False,
            "dicom_train_serving_equivalence_verified": bool(
                runtime.manifest.get("input_contract", {}).get("dicom_pipeline_equivalence_verified", False)
            ),
            "interpretation": "聚合概率仅用于内部工程观察，不支持病例级组织学或病理结论。",
        },
        "quality_gate": {
            "status": "BLOCKED" if insufficient else "PASS",
            "reasons": blocking_reasons,
            "metrics": {
                "analyzed_slice_count": len(results),
                "quality_warning_ratio": round(qc_warning_ratio, 8),
                "top_probability": round(top_probability, 8),
                "top_two_margin": round(top_two_margin, 8),
                "slice_agreement": round(slice_agreement, 8),
            },
            "thresholds": {
                "minimum_analyzed_slices": 3,
                "maximum_quality_warning_ratio": SERIES_MAX_QC_WARNING_RATIO,
                "minimum_top_probability": 0.50,
                "minimum_top_two_margin": 0.10,
                "minimum_slice_agreement": 0.60,
            },
            "rule_version": "case-quality-gate-v2",
        },
        "representative_slice": {
            "task_id": representative["task_id"],
            "file_name": representative["input"]["file_name"],
        },
        "items": results,
        "failures": failures,
        "next_action": {"type": "DOCTOR_REVIEW", "required": True},
        "disclaimer": "病例级聚合仅为弱标签二维切片的内部研究排序；当前门控禁止输出病例级组织学候选，不等同于DICOM序列诊断、病理类型或临床结论。",
    }


def persist_series(result: dict, owner_user_id: str) -> None:
    context = {
        "series_id": result["series_id"],
        "case_name": result["case_name"],
        "summary": result["summary"],
        "prediction": result["prediction"],
        "reliability": result["reliability"],
        "quality_gate": result.get("quality_gate"),
        "applicability": result.get("applicability"),
        "input_mode": result.get("input_mode", "IMAGE_SERIES"),
        "representative_slice": result["representative_slice"],
        "disclaimer": result["disclaimer"],
    }
    if result.get("input_mode"):
        context["input_mode"] = result["input_mode"]
    if result.get("dicom"):
        context["dicom"] = result["dicom"]
    with database_connection() as connection:
        connection.execute(
            """INSERT INTO analysis_series
               (series_id, owner_user_id, case_name, created_at, updated_at, status, aggregate_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (result["series_id"], owner_user_id, result["case_name"], result["created_at"],
             result["created_at"], result["status"], json.dumps(result, ensure_ascii=False)),
        )
        for index, item in enumerate(result["items"]):
            connection.execute(
                "INSERT INTO analysis_series_items (series_id, task_id, slice_index) VALUES (?, ?, ?)",
                (result["series_id"], item["task_id"], index),
            )
        representative_id = result["representative_slice"]["task_id"]
        row = connection.execute(
            "SELECT analysis_json FROM analysis_tasks WHERE task_id = ? AND owner_user_id = ?",
            (representative_id, owner_user_id),
        ).fetchone()
        if row is not None:
            analysis = json.loads(row["analysis_json"])
            analysis["series_context"] = context
            connection.execute(
                "UPDATE analysis_tasks SET analysis_json = ?, updated_at = ? WHERE task_id = ?",
                (json.dumps(analysis, ensure_ascii=False), result["created_at"], representative_id),
            )


class ModelRuntime:
    def __init__(self) -> None:
        self.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        expected_classes = [
            "adenocarcinoma",
            "large_cell_carcinoma",
            "normal",
            "squamous_cell_carcinoma",
        ]
        if self.manifest.get("class_names") != expected_classes:
            raise RuntimeError("模型类别顺序与应用不兼容")
        if len(self.manifest.get("weights", {})) != 5:
            raise RuntimeError("模型清单必须且只能包含五个折权重")
        if not self.manifest.get("research_only") or self.manifest.get("clinical_use_allowed"):
            raise RuntimeError("当前权重必须以研究用途且禁止临床使用的安全状态加载")
        abstention = self.manifest.get("abstention", {}).get("single_image", {})
        required_thresholds = {
            "minimum_top_probability", "minimum_top_two_margin", "minimum_fold_agreement"
        }
        if not required_thresholds.issubset(abstention):
            raise RuntimeError("模型清单缺少可追溯的单图拒判阈值")
        if not self.manifest.get("abstention", {}).get("case_series", {}).get("forced_abstention"):
            raise RuntimeError("未验证病例聚合必须启用强制拒判")
        self.models = []
        self.device = "uninitialized"
        self.loaded_at: float | None = None
        self.load_error: str | None = None

    @property
    def ready(self) -> bool:
        return len(self.models) == 5

    def require_ready(self) -> None:
        if not self.ready:
            raise HTTPException(503, self.load_error or "五折模型尚未就绪，请在设置页检查本地模型状态。")

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def verify_weights(self) -> list[Path]:
        verified: list[Path] = []
        for filename, expected_hash in self.manifest["weights"].items():
            path = WEIGHTS_DIR / filename
            if not path.is_file():
                raise FileNotFoundError(f"缺少模型权重：{filename}")
            actual_hash = self._sha256(path)
            if actual_hash.lower() != expected_hash.lower():
                raise RuntimeError(f"模型权重校验失败：{filename}")
            verified.append(path)
        return verified

    @staticmethod
    def build_model():
        import torch.nn as nn
        from torchvision.models import resnet18

        class ResNet18FourClass(nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.backbone = resnet18(weights=None)
                feature_dim = self.backbone.fc.in_features
                self.backbone.fc = nn.Identity()
                self.head4 = nn.Sequential(nn.Dropout(0.2), nn.Linear(feature_dim, 4))

            def forward(self, images):
                return self.head4(self.backbone(images))

        return ResNet18FourClass()

    @staticmethod
    def _load_state_dict(path: Path, device):
        import torch

        checkpoint = torch.load(path, map_location=device, weights_only=True)
        if not isinstance(checkpoint, dict):
            raise RuntimeError(f"权重格式错误：{path.name}")
        state = checkpoint.get("ema", checkpoint.get("model", checkpoint))
        if not isinstance(state, dict):
            raise RuntimeError(f"权重中缺少模型参数：{path.name}")
        return state

    @staticmethod
    def transform(image: Image.Image):
        from torchvision import transforms

        class ResizePad:
            def __call__(self, value: Image.Image) -> Image.Image:
                size = 224
                width, height = value.size
                left, top, resized_width, resized_height = resize_pad_geometry(width, height, size)
                resized = value.resize(
                    (resized_width, resized_height),
                    Image.Resampling.BILINEAR,
                )
                canvas = Image.new("RGB", (size, size), (0, 0, 0))
                canvas.paste(resized, (left, top))
                return canvas

        pipeline = transforms.Compose(
            [
                transforms.Lambda(lambda value: value.convert("RGB")),
                ResizePad(),
                transforms.ToTensor(),
                transforms.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225)),
            ]
        )
        return pipeline(image)

    def load(self) -> None:
        import torch

        requested = os.environ.get("LUNGSIGHT_DEVICE", "auto").lower()
        if requested == "cpu":
            device = torch.device("cpu")
        elif requested == "cuda":
            if not torch.cuda.is_available():
                raise RuntimeError("已要求使用 CUDA，但当前环境不可用")
            device = torch.device("cuda")
        else:
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        models = []
        for checkpoint_path in self.verify_weights():
            model = self.build_model().to(device)
            model.load_state_dict(self._load_state_dict(checkpoint_path, device), strict=True)
            model.eval()
            models.append(model)
        self.models = models
        self.device = str(device)
        self.loaded_at = time.time()
        self.load_error = None

    def predict(self, image: Image.Image) -> dict:
        import torch

        if len(self.models) != 5:
            raise RuntimeError("五折模型尚未完整加载")
        tensor = self.transform(image).unsqueeze(0).to(self.device)
        fold_probabilities: list[list[float]] = []
        started = time.perf_counter()
        with torch.inference_mode():
            for model in self.models:
                values = model(tensor).softmax(dim=-1)[0].double().cpu().tolist()
                fold_probabilities.append(values)
        elapsed_ms = (time.perf_counter() - started) * 1000

        mean_probability = [
            sum(fold[index] for fold in fold_probabilities) / len(fold_probabilities)
            for index in range(4)
        ]
        total = sum(mean_probability)
        mean_probability = [value / total for value in mean_probability]
        temperature = float(self.manifest.get("temperature", 1.0))
        if not math.isfinite(temperature) or temperature <= 0:
            raise RuntimeError("模型温度校准参数无效")
        if temperature != 1.0:
            calibrated = [max(value, 1e-12) ** (1.0 / temperature) for value in mean_probability]
            calibrated_total = sum(calibrated)
            mean_probability = [value / calibrated_total for value in calibrated]
        top_index = max(range(4), key=mean_probability.__getitem__)
        votes = [max(range(4), key=fold.__getitem__) for fold in fold_probabilities]
        agreement = sum(vote == top_index for vote in votes)
        ranked = sorted(mean_probability, reverse=True)
        margin = ranked[0] - ranked[1]

        threshold_config = self.manifest["abstention"]["single_image"]
        # Environment overrides may only make the research gate more conservative.
        min_confidence = max(
            float(threshold_config["minimum_top_probability"]),
            float(os.environ.get("LUNGSIGHT_MIN_CONFIDENCE", threshold_config["minimum_top_probability"])),
        )
        min_margin = max(
            float(threshold_config["minimum_top_two_margin"]),
            float(os.environ.get("LUNGSIGHT_MIN_MARGIN", threshold_config["minimum_top_two_margin"])),
        )
        min_agreement = max(
            int(threshold_config["minimum_fold_agreement"]),
            int(os.environ.get("LUNGSIGHT_MIN_FOLD_AGREEMENT", threshold_config["minimum_fold_agreement"])),
        )
        warnings: list[str] = []
        if agreement < min_agreement:
            warnings.append("五折模型判断存在明显分歧")
        if mean_probability[top_index] < min_confidence:
            warnings.append("内部最高分低于研究拒判阈值")
        if margin < min_margin:
            warnings.append("前两类分差低于研究拒判阈值")

        reliability = "STABLE" if not warnings else "REVIEW_REQUIRED"
        return {
            "top_index": top_index,
            "mean_probability": mean_probability,
            "fold_probabilities": fold_probabilities,
            "fold_votes": votes,
            "fold_agreement": agreement,
            "top_two_margin": margin,
            "reliability": reliability,
            "warnings": warnings,
            "decision": "RESEARCH_RANKING" if not warnings else "INDETERMINATE",
            "thresholds": {
                "minimum_top_probability": min_confidence,
                "minimum_top_two_margin": min_margin,
                "minimum_fold_agreement": min_agreement,
                "selection_source": threshold_config.get("selection_source"),
                "clinical_threshold": False,
            },
            "inference_ms": elapsed_ms,
        }

    def generate_attention_map(self, image: Image.Image, top_index: int) -> tuple[Image.Image, float]:
        """生成五折平均 Grad-CAM；它表示模型注意区域，不等同于病灶分割。"""
        import torch
        import torch.nn.functional as functional

        if len(self.models) != 5:
            raise RuntimeError("五折模型尚未完整加载")
        original = image.convert("RGB")
        tensor = self.transform(original).unsqueeze(0).to(self.device)
        fold_maps = []
        started = time.perf_counter()

        for model in self.models:
            captured: dict[str, object] = {}

            def capture_activation(_, __, output):
                captured["activation"] = output
                output.register_hook(lambda gradient: captured.__setitem__("gradient", gradient))

            handle = model.backbone.layer4[-1].register_forward_hook(capture_activation)
            try:
                model.zero_grad(set_to_none=True)
                with torch.enable_grad():
                    logits = model(tensor)
                    logits[0, top_index].backward()
                activation = captured.get("activation")
                gradient = captured.get("gradient")
                if activation is None or gradient is None:
                    raise RuntimeError("无法取得Grad-CAM中间特征")
                weights = gradient.mean(dim=(2, 3), keepdim=True)
                cam = torch.relu((weights * activation).sum(dim=1, keepdim=True))
                cam = restore_attention_map(cam, original.width, original.height)
                cam_min, cam_max = cam.amin(), cam.amax()
                cam = (cam - cam_min) / (cam_max - cam_min + 1e-8)
                fold_maps.append(cam.detach().cpu())
            finally:
                handle.remove()
                model.zero_grad(set_to_none=True)

        average = torch.stack(fold_maps).mean(dim=0)[0, 0]
        average = (average - average.min()) / (average.max() - average.min() + 1e-8)
        mask = Image.fromarray((average.mul(255).byte().numpy()), mode="L")
        heatmap = ImageOps.colorize(mask, black="#061015", mid="#4ee9d6", white="#ff665b")
        blended = Image.blend(original, heatmap, alpha=0.46)
        attention = Image.composite(blended, original, mask.point(lambda value: int(value * 0.9)))
        elapsed_ms = (time.perf_counter() - started) * 1000
        return attention, elapsed_ms


runtime = ModelRuntime()


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    initialize_auth_schema(DATABASE_PATH)
    initialize_knowledge_schema(DATABASE_PATH)
    initialize_evaluation_schema(DATABASE_PATH)
    initialize_agent_schema(DATABASE_PATH)
    with database_connection() as connection:
        source_count = connection.execute("SELECT COUNT(*) FROM evidence_sources").fetchone()[0]
    if source_count == 0:
        build_bundled_knowledge_base(DATABASE_PATH, BASE_DIR.parent)
    seed_medical_library(DATABASE_PATH)
    apply_library_presentation(DATABASE_PATH)
    try:
        runtime.load()
    except FileNotFoundError:
        runtime.models.clear()
        runtime.load_error = "本地模型文件不完整。请修复安装或补齐清单对应的五个权重，然后重启软件。账号、历史记录与问答仍可使用。"
    except Exception:
        runtime.models.clear()
        # Do not expose local paths or dependency exception details over HTTP.
        runtime.load_error = "本地模型未能通过校验或加载。请检查安装完整性与运行环境，然后重启软件。账号、历史记录与问答仍可使用。"
    workbench.queue().start()
    try:
        yield
    finally:
        workbench.queue().stop()
        if not workbench.queue().thread.is_alive():
            runtime.models.clear()


app = FastAPI(title="LungSight Local Inference API", version="1.0.0", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def safe_auth_validation(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/api/auth/"):
        # Pydantic's default error body includes rejected inputs, including passwords.
        return JSONResponse(status_code=422, content={"detail": "填写信息不完整或格式不正确，请检查必填项、账号方式和字段长度。"}, headers={"Cache-Control": "no-store"})
    if request.url.path.startswith("/api/settings/llm"):
        return JSONResponse(status_code=422, content={"detail": "模型服务配置格式不正确，请检查服务商、模型名称和密钥。"}, headers={"Cache-Control": "no-store"})
    return await request_validation_exception_handler(request, exc)


app.add_middleware(PublicPresentationMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


@app.post("/api/auth/register", status_code=201)
def register_account(
    request: RegisterRequest,
    response: Response,
    user_agent: str | None = Header(default=None),
    origin: str | None = Header(default=None),
) -> dict:
    if origin and origin not in ALLOWED_ORIGINS:
        raise HTTPException(status_code=403, detail="不允许的注册来源")
    try:
        user = register_user(
            DATABASE_PATH,
            email=request.email,
            phone=request.phone,
            doctor_profile=request.doctor_profile.model_dump(),
            confirm_password=request.confirm_password,
            display_name=request.display_name,
            password=request.password,
            accepted_terms=request.accepted_terms,
            accepted_privacy=request.accepted_privacy,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409 if "已经注册" in str(exc) else 422, detail=str(exc)) from exc
    token, expires_at = create_session(
        DATABASE_PATH, user_id=user["user_id"], user_agent=user_agent
    )
    set_session_cookie(response, token)
    response.headers["Cache-Control"] = "no-store"
    return {"user": user, "session_expires_at": expires_at}


@app.post("/api/auth/login")
def login_account(
    request: LoginRequest,
    response: Response,
    user_agent: str | None = Header(default=None),
    origin: str | None = Header(default=None),
) -> dict:
    if origin and origin not in ALLOWED_ORIGINS:
        raise HTTPException(status_code=403, detail="不允许的登录来源")
    try:
        user = authenticate_user(DATABASE_PATH, email=request.email, phone=request.phone, password=request.password)
    except PermissionError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    if user is None:
        raise HTTPException(status_code=401, detail="账号或密码不正确")
    token, expires_at = create_session(
        DATABASE_PATH, user_id=user["user_id"], user_agent=user_agent
    )
    set_session_cookie(response, token)
    response.headers["Cache-Control"] = "no-store"
    return {"user": user, "session_expires_at": expires_at}


@app.get("/api/auth/me")
def current_account(response: Response, user: dict = Depends(require_user)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return {"user": user}


@app.get("/api/auth/accounts")
def local_accounts(response: Response, user: dict = Depends(require_user)) -> dict:
    response.headers["Cache-Control"] = "private, no-store"
    return {"items": list_local_accounts(DATABASE_PATH, current_user_id=user["user_id"])}


@app.get("/api/auth/accounts/{account_id}/avatar")
def local_account_avatar(account_id: str, user: dict = Depends(require_user)) -> Response:
    accounts = list_local_accounts(DATABASE_PATH, current_user_id=user["user_id"])
    if not any(account["user_id"] == account_id for account in accounts):
        raise HTTPException(status_code=404, detail="账号不存在或不可用")
    image = load_avatar(DATABASE_PATH, user_id=account_id)
    if image is None:
        raise HTTPException(status_code=404, detail="该账号尚未上传头像")
    return Response(image, media_type="image/png", headers={
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
        "Content-Disposition": 'inline; filename="avatar.png"',
    })


@app.post("/api/auth/switch")
def switch_account(
    request: SwitchAccountRequest,
    response: Response,
    user_agent: str | None = Header(default=None),
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    current_user: dict = Depends(require_profile_user),
) -> dict:
    try:
        target_user = authenticate_user(DATABASE_PATH, user_id=request.user_id, password=request.password)
    except PermissionError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    if target_user is None:
        raise HTTPException(status_code=401, detail="密码验证失败，请重新输入")
    token, expires_at = create_session(DATABASE_PATH, user_id=target_user["user_id"], user_agent=user_agent)
    revoke_session(DATABASE_PATH, session_token)
    set_session_cookie(response, token)
    response.headers["Cache-Control"] = "no-store"
    return {"user": target_user, "session_expires_at": expires_at, "previous_user_id": current_user["user_id"]}


@app.get("/api/auth/doctor-profile")
def current_doctor_profile(response: Response, user: dict = Depends(require_user)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return {"profile": get_doctor_profile(DATABASE_PATH, user_id=user["user_id"])}


@app.put("/api/auth/profile")
def update_profile(request: ProfileNameRequest, user: dict = Depends(require_profile_user)) -> dict:
    try:
        return {"user": update_display_name(DATABASE_PATH, user_id=user["user_id"], display_name=request.display_name)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.post("/api/auth/avatar")
async def upload_avatar(file: UploadFile = File(...), user: dict = Depends(require_profile_user)) -> dict:
    try:
        payload = await file.read(MAX_AVATAR_BYTES + 1)
        if len(payload) > MAX_AVATAR_BYTES:
            raise HTTPException(status_code=413, detail="头像图片不能超过3MB")
        image_png = normalize_avatar(payload)
        return {"user": save_avatar(DATABASE_PATH, user_id=user["user_id"], image_png=image_png)}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    finally:
        await file.close()


@app.get("/api/auth/avatar")
def current_avatar(user: dict = Depends(require_user)) -> Response:
    image = load_avatar(DATABASE_PATH, user_id=user["user_id"])
    if image is None:
        raise HTTPException(status_code=404, detail="尚未上传头像")
    return Response(image, media_type="image/png", headers={
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
        "Content-Disposition": 'inline; filename="avatar.png"',
    })


@app.post("/api/auth/logout", status_code=204)
def logout_account(
    response: Response,
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> Response:
    revoke_session(DATABASE_PATH, session_token)
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        secure=COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )
    response.status_code = 204
    return response


@app.get("/api/settings/openai")
def openai_settings(user: dict = Depends(require_user)) -> dict:
    return get_openai_credential_status(DATABASE_PATH, user_id=user["user_id"])


@app.put("/api/settings/openai")
def update_openai_settings(
    request: OpenAICredentialRequest,
    user: dict = Depends(require_user),
) -> dict:
    try:
        return save_openai_credential(
            DATABASE_PATH,
            DATA_DIR,
            user_id=user["user_id"],
            api_key=request.api_key,
            model=request.model,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/settings/openai", status_code=204)
def remove_openai_settings(
    response: Response,
    user: dict = Depends(require_user),
) -> Response:
    delete_openai_credential(DATABASE_PATH, user_id=user["user_id"])
    response.status_code = 204
    return response


@app.post("/api/settings/openai/test")
def test_openai_settings(user: dict = Depends(require_user)) -> dict:
    try:
        api_key, model = load_openai_credential(
            DATABASE_PATH, DATA_DIR, user_id=user["user_id"]
        )
        client = OpenAI(api_key=api_key, timeout=12.0, max_retries=0)
        client.models.retrieve(model)
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AuthenticationError as exc:
        status = mark_openai_verification(
            DATABASE_PATH, user_id=user["user_id"], success=False, error="API Key验证失败"
        )
        raise HTTPException(status_code=401, detail=status["last_error"]) from exc
    except APIStatusError as exc:
        message = f"OpenAI返回状态码 {exc.status_code}，请检查模型权限与账户状态"
        status = mark_openai_verification(
            DATABASE_PATH, user_id=user["user_id"], success=False, error=message
        )
        raise HTTPException(status_code=502, detail=status["last_error"]) from exc
    except APIConnectionError as exc:
        message = "无法连接OpenAI，请检查网络或代理设置"
        status = mark_openai_verification(
            DATABASE_PATH, user_id=user["user_id"], success=False, error=message
        )
        raise HTTPException(status_code=503, detail=status["last_error"]) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return mark_openai_verification(DATABASE_PATH, user_id=user["user_id"], success=True)


@app.get("/api/settings/llm")
def llm_settings(user: dict = Depends(require_user)) -> dict:
    return get_llm_settings(DATABASE_PATH, user_id=user["user_id"])


@app.put("/api/settings/llm")
def update_llm_settings(
    request: LLMCredentialRequest,
    user: dict = Depends(require_user),
) -> dict:
    try:
        if request.api_key:
            return save_llm_credential(
                DATABASE_PATH, DATA_DIR, user_id=user["user_id"], provider=request.provider,
                api_key=request.api_key, model=request.model, select=True,
            )
        return select_llm_provider(
            DATABASE_PATH, user_id=user["user_id"], provider=request.provider, model=request.model
        )
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/settings/llm/select")
def choose_llm_provider(
    request: LLMProviderRequest,
    user: dict = Depends(require_user),
) -> dict:
    try:
        return select_llm_provider(
            DATABASE_PATH, user_id=user["user_id"], provider=request.provider, model=request.model
        )
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/settings/llm/{provider}")
def remove_llm_settings(provider: str, user: dict = Depends(require_user)) -> dict:
    try:
        return delete_llm_credential(DATABASE_PATH, user_id=user["user_id"], provider=provider)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/settings/llm/test")
def test_llm_settings(
    request: LLMProviderRequest,
    user: dict = Depends(require_user),
) -> dict:
    try:
        provider_id, api_key, model = load_llm_credential(
            DATABASE_PATH, DATA_DIR, user_id=user["user_id"], provider=request.provider
        )
        provider = create_llm_provider(provider=provider_id, api_key=api_key, model=model)
        getattr(provider, "check_connection")()
    except ValueError as exc:
        message = str(exc)
        mark_llm_verification(DATABASE_PATH, user_id=user["user_id"], provider=request.provider, success=False, error=message)
        raise HTTPException(status_code=422, detail=message) from exc
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AuthenticationError as exc:
        mark_llm_verification(
            DATABASE_PATH, user_id=user["user_id"], provider=request.provider,
            success=False, error="API Key验证失败",
        )
        raise HTTPException(status_code=401, detail="API Key验证失败") from exc
    except APIStatusError as exc:
        message = f"服务商返回状态码 {exc.status_code}，请检查模型权限与账户状态"
        mark_llm_verification(
            DATABASE_PATH, user_id=user["user_id"], provider=request.provider,
            success=False, error=message,
        )
        raise HTTPException(status_code=502, detail=message) from exc
    except APIConnectionError as exc:
        message = "无法连接模型服务商，请检查网络或代理设置"
        mark_llm_verification(
            DATABASE_PATH, user_id=user["user_id"], provider=request.provider,
            success=False, error=message,
        )
        raise HTTPException(status_code=503, detail=message) from exc
    return mark_llm_verification(
        DATABASE_PATH, user_id=user["user_id"], provider=request.provider, success=True
    )


def load_agent_provider(user_id: str) -> LLMProvider | None:
    """Resolve the only production provider without exposing credentials."""
    try:
        provider, api_key, model = load_llm_credential(
            DATABASE_PATH, DATA_DIR, user_id=user_id
        )
    except LookupError:
        return None
    return create_llm_provider(provider=provider, api_key=api_key, model=model)


def ct_context_for_agent(task_id: str | None, user_id: str) -> dict | None:
    if not task_id:
        return None
    row = get_task_row(task_id, user_id)
    analysis = json.loads(row["analysis_json"])
    top_class = row["top_class"]
    prediction = analysis.get("prediction", {})
    reliability = analysis.get("reliability", {})
    quality = analysis.get("quality_control", {})
    attention = analysis.get("attention", {})
    return {
        "task_id": row["task_id"],
        "status": row["status"],
        "top_class": top_class,
        "top_class_cn": row["top_class_cn"],
        "top_probability": prediction.get("probabilities", {}).get(top_class),
        "probabilities": prediction.get("probabilities", {}),
        "reliability_level": row["reliability_level"],
        "fold_agreement": row["fold_agreement"],
        "top_two_margin": reliability.get("top_two_margin"),
        "reliability_warnings": reliability.get("warnings", []),
        "quality_status": row["quality_status"],
        "quality_warnings": quality.get("warnings", []),
        "quality_metrics": quality.get("metrics", {}),
        "attention_method": attention.get("method"),
        "attention_scope": attention.get("scope"),
        "review_decision": row["review_decision"],
        "corrected_class_cn": row["corrected_class_cn"],
        "model_version": analysis.get("model", {}).get("version", "unknown"),
        "research_only": bool(analysis.get("model", {}).get("research_only", True)),
        "weak_labels": bool(analysis.get("model", {}).get("weak_labels", True)),
        "prediction_decision": prediction.get("decision", "INDETERMINATE"),
        "applicability": analysis.get("applicability", {}),
        "series_context": analysis.get("series_context"),
    }


def execute_agent_chat(request: AgentChatRequest, user: dict) -> dict:
    effective_task_id = request.linked_task_id
    if request.conversation_id:
        try:
            existing = get_conversation(
                DATABASE_PATH, user_id=user["user_id"], conversation_id=request.conversation_id
            )
            if effective_task_id is not None and effective_task_id != existing.get("linked_task_id"):
                raise HTTPException(status_code=422, detail="已有对话不能切换关联病例，请新建对话")
            effective_task_id = existing.get("linked_task_id")
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    ct_context = ct_context_for_agent(effective_task_id, user["user_id"])
    try:
        return run_agent_chat(
            DATABASE_PATH,
            user_id=user["user_id"],
            question=request.question,
            conversation_id=request.conversation_id,
            linked_task_id=effective_task_id,
            ct_context=ct_context,
            provider=load_agent_provider(user["user_id"]),
            mode="ct_hybrid" if ct_context else "medical_general",
        )
    except LookupError as exc:
        message = str(exc)
        status_code = 409 if "API Key" in message else 404
        raise HTTPException(status_code=status_code, detail=message) from exc
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=502, detail="模型返回内容未通过结构化校验，请重试") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail="模型服务API Key验证失败") from exc
    except APIStatusError as exc:
        raise HTTPException(status_code=502, detail=f"模型服务回答失败（状态码 {exc.status_code}）") from exc
    except APIConnectionError as exc:
        raise HTTPException(status_code=503, detail="暂时无法连接模型服务，请稍后重试") from exc


@app.post("/api/evidence/search")
def search_evidence(
    request: EvidenceQueryRequest,
    user: dict = Depends(require_user),
) -> dict:
    del user
    return retrieve_evidence(DATABASE_PATH, question=request.question, limit=5)


@app.post("/api/agent/conversations", status_code=201)
def new_agent_conversation(
    request: AgentConversationRequest,
    user: dict = Depends(require_user),
) -> dict:
    if request.linked_task_id:
        get_task_row(request.linked_task_id, user["user_id"])
    return create_conversation(
        DATABASE_PATH, user_id=user["user_id"], title=request.title,
        linked_task_id=request.linked_task_id,
    )


@app.get("/api/agent/conversations")
def agent_conversations(
    limit: int = Query(default=50, ge=1, le=100),
    user: dict = Depends(require_user),
) -> dict:
    return {"items": list_conversations(DATABASE_PATH, user_id=user["user_id"], limit=limit)}


@app.get("/api/agent/conversations/{conversation_id}")
def agent_conversation(conversation_id: str, user: dict = Depends(require_user)) -> dict:
    try:
        return get_conversation(
            DATABASE_PATH, user_id=user["user_id"], conversation_id=conversation_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/agent/conversations/{conversation_id}", status_code=204)
def delete_agent_conversation(conversation_id: str,
                               user: dict = Depends(require_conversation_user)) -> Response:
    try:
        delete_conversation(DATABASE_PATH, user_id=user["user_id"], conversation_id=conversation_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@app.put("/api/agent/conversations/{conversation_id}/pin")
def pin_agent_conversation(conversation_id: str, request: ConversationPinRequest,
                           user: dict = Depends(require_conversation_user)) -> dict:
    try:
        return set_conversation_pin(DATABASE_PATH, user_id=user["user_id"],
                                    conversation_id=conversation_id, pinned=request.pinned)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/agent/conversations/{conversation_id}/export")
def export_agent_conversation(conversation_id: str, request: ConversationExportRequest,
                              response: Response, user: dict = Depends(require_conversation_user)) -> dict:
    response.headers["Cache-Control"] = "no-store"
    try:
        return export_conversation_text(DATABASE_PATH, user_id=user["user_id"],
                                        conversation_id=conversation_id, purpose=request.purpose)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/agent/usage")
def agent_usage(user: dict = Depends(require_user)) -> dict:
    return usage_summary(DATABASE_PATH, user_id=user["user_id"])


@app.post("/api/agent/chat")
def agent_chat(request: AgentChatRequest, user: dict = Depends(require_user)) -> dict:
    return execute_agent_chat(request, user)


@app.post("/api/agent/chat/stream")
def agent_chat_stream(request: AgentChatRequest, user: dict = Depends(require_user)):
    result = public_payload(execute_agent_chat(request, user))

    def events():
        yield json.dumps({
            "type": "meta", "conversation_id": result["conversation_id"],
            "message_id": result["message_id"], "support_level": result["support_level"],
            "risk_level": result["risk_level"], "privacy": result["privacy"],
        }, ensure_ascii=False) + "\n"
        answer = result["answer"]
        for start in range(0, len(answer), 14):
            yield json.dumps({"type": "delta", "delta": answer[start:start + 14]}, ensure_ascii=False) + "\n"
        yield json.dumps({"type": "done", "result": result}, ensure_ascii=False) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson")


@app.get("/api/agent/evaluation/dataset")
def rag_agent_evaluation_dataset(user: dict = Depends(require_user)) -> dict:
    del user
    return rag_dataset_summary(RAG_EVALUATION_DATASET_PATH)


@app.get("/api/agent/evaluation/runs")
def rag_agent_evaluation_runs(
    limit: int = Query(default=8, ge=1, le=50),
    user: dict = Depends(require_user),
) -> dict:
    return {"items": list_rag_runs(DATABASE_PATH, user_id=user["user_id"], limit=limit)}


@app.post("/api/agent/evaluation/run")
def run_rag_agent_evaluation(user: dict = Depends(require_user)) -> dict:
    return run_rag_evaluation(
        DATABASE_PATH, RAG_EVALUATION_DATASET_PATH, user_id=user["user_id"]
    )


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok" if len(runtime.models) == 5 else "unavailable",
        "models_loaded": len(runtime.models),
        "device": runtime.device,
        "model_ready": runtime.ready,
        "model_error": runtime.load_error,
        "expected_models": 5,
    }


@app.get("/api/model")
def model_info() -> dict:
    return {
        "name": runtime.manifest["model_name"],
        "version": runtime.manifest["model_version"],
        "classes": runtime.manifest["class_names"],
        "classes_cn": runtime.manifest["class_names_cn"],
        "folds": len(runtime.models),
        "device": runtime.device,
        "supported_formats": sorted(SUPPORTED_SUFFIXES),
        "dicom_series_supported": True,
        "dicom_analysis_slice_limit": DICOM_ANALYSIS_SLICES,
        "scope": "研究原型：对与训练域相近的二维肺部CT导出图进行闭集内部排序",
        "task_definition": runtime.manifest.get("task_definition", {}),
        "lineage": runtime.manifest.get("lineage", {}),
        "input_contract": runtime.manifest.get("input_contract", {}),
        "abstention": runtime.manifest.get("abstention", {}),
        "promotion_gates": runtime.manifest.get("promotion_gates", {}),
        "activation": runtime.manifest.get("activation", {}),
        "research_only": bool(runtime.manifest.get("research_only", False)),
        "weak_labels": bool(runtime.manifest.get("weak_labels", False)),
        "clinical_use_allowed": bool(runtime.manifest.get("clinical_use_allowed", False)),
        "temperature": float(runtime.manifest.get("temperature", 1.0)),
    }


@app.post("/api/analyze")
async def analyze(
    file: UploadFile = File(...),
    user: dict = Depends(require_user),
) -> dict:
    suffix = Path(file.filename or "upload").suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(status_code=415, detail="当前版本仅支持PNG、JPG、BMP和TIFF二维图片")

    payload = await file.read(MAX_UPLOAD_BYTES + 1)
    if not payload:
        raise HTTPException(status_code=400, detail="上传文件为空")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="图片超过20MB限制")

    return await run_in_threadpool(analyze_image_payload, payload, file.filename or "upload", user)


def analyze_image_payload(payload: bytes, filename: str, user: dict, *, task_id=None, progress=lambda stage: None) -> dict:
    runtime.require_ready()
    suffix = Path(filename).suffix.lower()
    try:
        with Image.open(io.BytesIO(payload)) as opened:
            opened.verify()
        with Image.open(io.BytesIO(payload)) as opened:
            image = opened.convert("RGB")
            width, height = image.size
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=400, detail="文件不是可读取的二维图片") from exc

    if width < 64 or height < 64:
        raise HTTPException(status_code=400, detail="图片尺寸过小，无法进入当前模型")

    image_sha256 = hashlib.sha256(payload).hexdigest()
    progress("QUALITY")
    quality_control = assess_image_quality(image, image_sha256)
    try:
        progress("INFERENCE")
        with MODEL_LOCK:
            prediction = runtime.predict(image)
            progress("ATTENTION")
            attention_image, attention_ms = runtime.generate_attention_map(image, prediction["top_index"])
    except JobCancelled:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"模型推理失败：{exc}") from exc
    priority = assign_review_priority(quality_control, prediction)

    classes = runtime.manifest["class_names"]
    classes_cn = runtime.manifest["class_names_cn"]
    top_index = prediction["top_index"]
    probabilities = {
        name: round(prediction["mean_probability"][index], 8)
        for index, name in enumerate(classes)
    }
    fold_results = [
        {
            "fold": index,
            "probabilities": {
                name: round(values[class_index], 8)
                for class_index, name in enumerate(classes)
            },
            "top_class": classes[prediction["fold_votes"][index]],
        }
        for index, values in enumerate(prediction["fold_probabilities"])
    ]

    created_at = datetime.now(timezone.utc).isoformat()
    result = {
        "task_id": task_id or f"CT-{uuid.uuid4().hex[:10].upper()}",
        "created_at": created_at,
        "status": "WAITING_FOR_REVIEW",
        "input": {
            "file_name": Path(filename).name,
            "format": suffix.removeprefix(".").upper(),
            "sha256": image_sha256,
            "image_size": [width, height],
            "bytes": len(payload),
        },
        "quality_control": quality_control,
        "model": {
            "name": runtime.manifest["model_name"],
            "version": runtime.manifest["model_version"],
            "folds": 5,
            "weights_verified": True,
            "device": runtime.device,
            "inference_ms": round(prediction["inference_ms"], 3),
            "attention_ms": round(attention_ms, 3),
            "research_only": bool(runtime.manifest.get("research_only", False)),
            "weak_labels": bool(runtime.manifest.get("weak_labels", False)),
            "temperature": float(runtime.manifest.get("temperature", 1.0)),
            "architecture_matches_original_plan": bool(
                runtime.manifest.get("lineage", {}).get("architecture_matches_original_plan", False)
            ),
            "exact_original_weights": bool(
                runtime.manifest.get("lineage", {}).get("exact_original_weights", False)
            ),
        },
        "prediction": {
            "decision": prediction["decision"],
            "top_class": classes[top_index],
            "top_class_cn": classes_cn[top_index],
            "probabilities": probabilities,
            "fold_results": fold_results,
        },
        "reliability": {
            "level": prediction["reliability"],
            "fold_agreement": f"{prediction['fold_agreement']}/5",
            "top_two_margin": round(prediction["top_two_margin"], 8),
            "warnings": prediction["warnings"],
            "thresholds": prediction["thresholds"],
            "rule_version": "research-abstention-v2",
        },
        "applicability": {
            "status": "RESEARCH_ONLY" if prediction["decision"] == "RESEARCH_RANKING" else "ABSTAINED",
            "within_training_domain_verified": False,
            "clinical_candidate_allowed": False,
            "pathology_conclusion_allowed": False,
            "case_aggregation_allowed": False,
            "reasons": [
                "上传图片与训练域的一致性无法由当前系统自动确认",
                "训练标签来自目录弱标签且患者独立性未验证",
                "未完成外部临床验证和病灶ROI验证",
            ] + prediction["warnings"],
        },
        "priority": priority,
        "attention": {
            "available": True,
            "method": "five-fold-mean-grad-cam",
            "scope": "模型注意区域，仅用于解释分类依据，不等同于病灶定位或分割",
        },
        "next_action": {
            "type": "DOCTOR_REVIEW",
            "required": True,
        },
        "disclaimer": "结果来自弱标签研究原型，仅用于科研与辅助分析，不构成临床诊断、分期、处方或治疗建议。",
    }
    progress("SAVING")
    try:
        persist_task(result, payload, suffix, attention_image, user["user_id"])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"任务保存失败：{exc}") from exc
    return result


@app.post("/api/analyze/series")
async def analyze_series(
    files: list[UploadFile] = File(...),
    case_name: str = Form(default="未命名CT病例", max_length=120),
    user: dict = Depends(require_user),
) -> dict:
    if not files:
        raise HTTPException(status_code=400, detail="请选择至少一张CT切片")
    if len(files) > MAX_SERIES_FILES:
        raise HTTPException(status_code=413, detail=f"单个病例最多上传{MAX_SERIES_FILES}张二维切片")

    results: list[dict] = []
    failures: list[dict] = []
    for upload in files:
        filename = Path(upload.filename or "upload").name
        try:
            results.append(await analyze(file=upload, user=user))
        except HTTPException as exc:
            failures.append({"file_name": filename, "status_code": exc.status_code, "detail": exc.detail})
        except Exception:
            failures.append({"file_name": filename, "status_code": 500, "detail": "本地分析失败"})
        finally:
            await upload.close()
    if not results:
        raise HTTPException(status_code=422, detail={"message": "病例内没有切片成功完成分析", "failures": failures})

    result = aggregate_series_results(
        results, case_name=case_name, failures=failures,
        case_aggregation_validated=False, input_mode="IMAGE_SERIES",
    )
    try:
        persist_series(result, user["user_id"])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"病例级结果保存失败：{exc}") from exc
    return result


@app.post("/api/analyze/dicom-series")
async def analyze_dicom_series(
    files: list[UploadFile] = File(...),
    case_name: str = Form(default="未命名DICOM病例", max_length=120),
    privacy_acknowledged: bool = Form(default=False),
    user: dict = Depends(require_user),
) -> dict:
    """Import one local CT DICOM series without persisting source objects or identifiers."""
    if not privacy_acknowledged:
        raise HTTPException(status_code=422, detail="请先确认数据已获授权，并知悉像素隐私仍需人工复核")
    if not files:
        raise HTTPException(status_code=400, detail="请选择至少一个DICOM文件")
    if len(files) > MAX_DICOM_FILES:
        raise HTTPException(status_code=413, detail=f"单个序列最多上传{MAX_DICOM_FILES}个DICOM文件")

    payloads: list[bytes] = []
    total_bytes = 0
    try:
        for upload in files:
            payload = await upload.read(MAX_UPLOAD_BYTES + 1)
            if not payload:
                raise HTTPException(status_code=400, detail="DICOM序列中存在空文件")
            if len(payload) > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="单个DICOM文件超过20MB限制")
            total_bytes += len(payload)
            if total_bytes > MAX_DICOM_TOTAL_BYTES:
                raise HTTPException(status_code=413, detail="DICOM序列总大小超过256MB限制")
            payloads.append(payload)
    finally:
        for upload in files:
            await upload.close()

    try:
        prepared, failures, dicom_summary = prepare_dicom_series(
            payloads, maximum_analysis_slices=DICOM_ANALYSIS_SLICES
        )
    except DicomImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    results: list[dict] = []
    for item in prepared:
        derived = UploadFile(filename=item["file_name"], file=io.BytesIO(item["payload"]))
        try:
            results.append(await analyze(file=derived, user=user))
        except HTTPException as exc:
            failures.append({
                "file_name": item["file_name"], "status_code": exc.status_code, "detail": exc.detail,
            })
        except Exception:
            failures.append({
                "file_name": item["file_name"], "status_code": 500, "detail": "本地分析失败",
            })
        finally:
            await derived.close()
    if not results:
        raise HTTPException(
            status_code=422,
            detail={"message": "DICOM序列没有切片成功完成分析", "failures": failures},
        )

    result = aggregate_series_results(
        results, case_name=case_name, failures=failures,
        case_aggregation_validated=False, input_mode="DICOM",
    )
    complete_dicom_result(result, dicom_summary)
    try:
        persist_series(result, user["user_id"])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"DICOM病例结果保存失败：{exc}") from exc
    return result


@app.get("/api/series")
def list_series(
    limit: int = Query(default=50, ge=1, le=200),
    user: dict = Depends(require_user),
) -> dict:
    with database_connection() as connection:
        rows = connection.execute(
            """SELECT aggregate_json FROM analysis_series
               WHERE owner_user_id = ? ORDER BY created_at DESC LIMIT ?""",
            (user["user_id"], limit),
        ).fetchall()
    return {"items": [json.loads(row["aggregate_json"]) for row in rows]}


@app.get("/api/series/{series_id}")
def get_series(series_id: str, user: dict = Depends(require_user)) -> dict:
    return get_series_record(series_id, user["user_id"])


@app.get("/api/series/{series_id}/report")
def download_series_report(series_id: str, user: dict = Depends(require_user)):
    series = get_series_record(series_id, user["user_id"])
    labels = dict(zip(runtime.manifest["class_names"], runtime.manifest["class_names_cn"]))
    probabilities = series["prediction"]["probabilities"]
    probability_rows = "".join(
        f"<tr><td>{html.escape(labels.get(key, key))}</td><td>{value * 100:.2f}%</td></tr>"
        for key, value in probabilities.items()
    )
    slice_rows = "".join(
        "<tr>"
        f"<td>{index + 1}</td><td>{html.escape(item['input']['file_name'])}</td>"
        f"<td>{html.escape(item['prediction']['top_class_cn'])}</td>"
        f"<td>{item['prediction']['probabilities'][item['prediction']['top_class']] * 100:.2f}%</td>"
        f"<td>{html.escape(item['reliability']['fold_agreement'])}</td>"
        f"<td>{html.escape(item['quality_control']['status'])}</td>"
        f"<td>{html.escape(item['status'])}</td></tr>"
        for index, item in enumerate(series["items"])
    )
    warning_text = "；".join(series["reliability"].get("warnings", [])) or "无病例级工程警告"
    representative_id = series["representative_slice"]["task_id"]
    representative_row = get_task_row(representative_id, user["user_id"])
    image_path = resolve_managed_media(representative_row["image_path"], UPLOADS_DIR)
    suffix_mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".bmp": "image/bmp", ".tif": "image/tiff", ".tiff": "image/tiff"}
    image_mime = suffix_mime.get(image_path.suffix.lower(), "image/png") if image_path else "image/png"
    original_data = base64.b64encode(image_path.read_bytes()).decode("ascii") if image_path else ""
    attention_path = resolve_managed_media(representative_row["attention_path"], ATTENTION_DIR)
    attention_data = base64.b64encode(attention_path.read_bytes()).decode("ascii") if attention_path else ""
    images_html = ""
    if original_data:
        images_html += f'<figure><img src="data:{image_mime};base64,{original_data}" alt="病例代表切片"><figcaption>代表切片：{html.escape(series["representative_slice"]["file_name"])}</figcaption></figure>'
    if attention_data:
        images_html += '<figure><img src="data:image/png;base64,' + attention_data + '" alt="代表切片Grad-CAM"><figcaption>代表切片五折平均 Grad-CAM（非病灶分割）</figcaption></figure>'

    annotations_html = ''.join(
        f'<section><h3>{html.escape(item["input"]["file_name"])}</h3>{notes}</section>'
        for item in series['items']
        if (notes := workbench.annotation_report(item['task_id'], user['user_id']))
    )
    evidence_queries = [
        item for task in series['items'] for item in evidence_history(DATABASE_PATH, task['task_id'])
        if item.get("include_in_report")
    ]
    evidence_parts: list[str] = []
    for item in evidence_queries:
        cards = item.get("evidence") or item.get("citations") or []
        citations = "".join(
            f"<li>[{html.escape(card.get('citation_id', '—'))}] {html.escape(card.get('title', '未命名来源'))}</li>"
            for card in cards
        )
        evidence_parts.append(
            f"<article class=\"evidence\"><h3>{html.escape(item.get('question', '病例解释'))}</h3>"
            f"<p>{html.escape(item.get('answer', '')).replace(chr(10), '<br>')}</p>"
            f"<ul>{citations}</ul><small>支持状态：{html.escape(item.get('support_level', '未记录'))}</small></article>"
        )
    evidence_html = "".join(evidence_parts) or "<p>尚未为该病例生成并附加AI循证解释。</p>"
    decision_label = "仅显示内部研究排序" if series["prediction"]["decision"] == "CANDIDATE" else "病例级结论已阻断"
    score_label = "模型内部最高分（不作为病例候选）"
    gate = series.get("quality_gate", {})
    gate_reasons = "；".join(gate.get("reasons", [])) or "全部工程阈值通过"
    gate_html = (
        f"<h2>病例级质量门控</h2><p>状态：<strong>{html.escape(gate.get('status', '未记录'))}</strong><br>"
        f"依据：{html.escape(gate_reasons)}<br>规则版本：{html.escape(gate.get('rule_version', '未记录'))}</p>"
    )
    dicom_html = ""
    if series.get("dicom"):
        dicom = series["dicom"]
        privacy = dicom.get("privacy", {})
        fields = "、".join(privacy.get("direct_identifier_fields_detected", [])) or "未检测到已配置的直接身份字段"
        dicom_html = (
            "<h2>DICOM 导入摘要</h2>"
            f"<p>输入文件：{int(dicom.get('input_file_count', 0))}；"
            f"可读切片：{int(dicom.get('readable_slice_count', 0))}；"
            f"进入模型：{int(dicom.get('analyzed_slice_count', 0))}；"
            f"等距抽样：{'是' if dicom.get('subsampled') else '否'}；"
            f"肺窗：中心 {int(dicom.get('window', {}).get('center_hu', -600))} HU / "
            f"宽度 {int(dicom.get('window', {}).get('width_hu', 1500))} HU；"
            f"肺野有效区间：{int(dicom.get('lung_selection', {}).get('eligible_slice_count', dicom.get('readable_slice_count', 0)))} 层；"
            f"边缘低覆盖排除：{int(dicom.get('lung_selection', {}).get('excluded_edge_slice_count', 0))} 层。</p>"
            f"<p class=\"warning\">检测到的身份字段名称：{html.escape(fields)}。"
            "身份字段值与原始 DICOM 均未保存；像素区域仍需人工隐私复核。</p>"
        )
    document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{html.escape(series_id)} 病例序列报告</title>
<style>body{{max-width:1000px;margin:36px auto;padding:0 24px;font:14px/1.7 Arial,"Microsoft YaHei",sans-serif;color:#17272b}}h1{{font-size:28px}}h2{{margin-top:28px;padding-bottom:8px;border-bottom:1px solid #dce7e8;font-size:18px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:8px;border-bottom:1px solid #edf2f2;text-align:left}}th{{background:#f4f8f8}}.meta{{color:#587076}}.warning{{padding:12px;background:#fff8e8;border-left:3px solid #d9a834}}.notice{{margin-top:34px;padding:14px;background:#eef8f7;color:#496466}}.images{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}figure{{margin:0}}img{{width:100%;max-height:390px;object-fit:contain;background:#071015}}figcaption{{margin-top:5px;color:#587076;font-size:12px}}.evidence{{margin:12px 0;padding:14px;border:1px solid #dce7e8;border-radius:8px}}.evidence h3{{margin:0 0 8px;font-size:15px}}.evidence p{{margin:0}}.evidence li,.evidence small{{color:#587076;font-size:12px}}@media print{{body{{margin:0}}}}</style></head>
<body><h1>LungSight 病例级二维 CT 辅助分析报告</h1>
<p class="meta">病例编号：{html.escape(series_id)}<br>病例名称：{html.escape(series['case_name'])}<br>创建时间：{html.escape(series['created_at'])}<br>当前状态：{html.escape(series['status'])}</p>
{dicom_html}
{gate_html}
<h2>病例级聚合结果</h2><p>结果状态：<strong>{decision_label}</strong><br>{score_label}：<strong>{html.escape(series['prediction']['top_class_cn'])}</strong>（{series['prediction']['top_probability'] * 100:.2f}%）<br>切片一致率：{series['prediction']['slice_agreement'] * 100:.2f}%<br>有效切片：{series['summary']['analyzed_count']} / {series['summary']['uploaded_count']}<br>代表切片：{html.escape(series['representative_slice']['file_name'])}</p>
<table>{probability_rows}</table><p class="warning">病例级提示：{html.escape(warning_text)}</p>
<h2>代表切片与注意力图</h2><div class="images">{images_html}</div>
<h2>逐切片结果与复核状态</h2><table><tr><th>#</th><th>文件</th><th>最高类别</th><th>概率</th><th>五折一致性</th><th>质控</th><th>复核状态</th></tr>{slice_rows}</table>
<h2>病例AI循证解释</h2>{annotations_html}{evidence_html}
<p class="notice">{html.escape(series['disclaimer'])} 所有切片结果及病例级聚合均须由具备资质的专业人员结合完整DICOM序列、临床信息和病理结果复核。</p></body></html>"""
    return Response(
        content=public_text(document),
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{series_id}-case-report.html"'},
    )


@app.get("/api/tasks")
def list_tasks(
    status: str | None = None,
    class_name: str | None = None,
    reliability: str | None = None,
    priority: str | None = None,
    archived: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    user: dict = Depends(require_user),
) -> dict:
    conditions: list[str] = ["owner_user_id = ?", "archived_at IS NOT NULL" if archived else "archived_at IS NULL"]
    values: list[object] = [user["user_id"]]
    if status:
        conditions.append("status = ?")
        values.append(status)
    if class_name:
        conditions.append("top_class = ?")
        values.append(class_name)
    if reliability:
        conditions.append("reliability_level = ?")
        values.append(reliability)
    if priority:
        conditions.append("priority = ?")
        values.append(priority)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    values.append(limit)
    with database_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT task_id, created_at, updated_at, status, file_name, top_class,
                   top_class_cn, reliability_level, fold_agreement, analysis_json,
                   reviewer_name, review_decision, corrected_class_cn, reviewed_at,
                   quality_status, priority, attention_path, starred_at, archived_at
            FROM analysis_tasks
            {where_clause}
            ORDER BY (starred_at IS NOT NULL) DESC, starred_at DESC, created_at DESC
            LIMIT ?
            """,
            values,
        ).fetchall()
        counts = connection.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN status = 'WAITING_FOR_REVIEW' THEN 1 ELSE 0 END) AS waiting,
                   SUM(CASE WHEN status IN ('CONFIRMED', 'CORRECTED', 'UNDETERMINED') THEN 1 ELSE 0 END) AS reviewed,
                   SUM(CASE WHEN reliability_level = 'REVIEW_REQUIRED' THEN 1 ELSE 0 END) AS flagged,
                   SUM(CASE WHEN priority IN ('PRIORITY', 'HIGH_RISK') AND status = 'WAITING_FOR_REVIEW' THEN 1 ELSE 0 END) AS urgent,
                   (SELECT COUNT(*) FROM analysis_tasks archived_task
                    WHERE archived_task.owner_user_id = ? AND archived_task.archived_at IS NOT NULL) AS archived
            FROM analysis_tasks
            WHERE owner_user_id = ? AND archived_at IS NULL
            """
            , (user["user_id"], user["user_id"])
        ).fetchone()
    items = []
    for row in rows:
        analysis = json.loads(row["analysis_json"])
        items.append(
            {
                "task_id": row["task_id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "status": row["status"],
                "file_name": row["file_name"],
                "top_class": row["top_class"],
                "top_class_cn": row["top_class_cn"],
                "top_probability": analysis["prediction"]["probabilities"][row["top_class"]],
                "reliability_level": row["reliability_level"],
                "fold_agreement": f"{row['fold_agreement']}/5",
                "quality_status": row["quality_status"],
                "priority": row["priority"],
                "attention_available": bool(row["attention_path"]),
                "reviewer_name": row["reviewer_name"],
                "review_decision": row["review_decision"],
                "corrected_class_cn": row["corrected_class_cn"],
                "reviewed_at": row["reviewed_at"],
                "starred_at": row["starred_at"],
                "archived_at": row["archived_at"],
            }
        )
    return {
        "items": items,
        "counts": {
            "total": counts["total"] or 0,
            "waiting": counts["waiting"] or 0,
            "reviewed": counts["reviewed"] or 0,
            "flagged": counts["flagged"] or 0,
            "urgent": counts["urgent"] or 0,
            "archived": counts["archived"] or 0,
        },
    }


@app.patch("/api/tasks/{task_id}/library")
def update_task_library_state(
    task_id: str,
    request: TaskLibraryActionRequest,
    user: dict = Depends(require_user),
) -> dict:
    row = get_task_row(task_id, user["user_id"])
    now = datetime.now(timezone.utc).isoformat()
    updates = {
        "STAR": ("starred_at", now, "CASE_STARRED"),
        "UNSTAR": ("starred_at", None, "CASE_UNSTARRED"),
        "ARCHIVE": ("archived_at", now, "CASE_ARCHIVED"),
        "RESTORE": ("archived_at", None, "CASE_RESTORED"),
    }
    column, value, event_type = updates[request.action]
    if request.action == "ARCHIVE" and row["archived_at"]:
        raise HTTPException(status_code=409, detail="该病例已经归档")
    if request.action == "RESTORE" and not row["archived_at"]:
        raise HTTPException(status_code=409, detail="该病例不在归档中")
    with database_connection() as connection:
        connection.execute(
            f"UPDATE analysis_tasks SET {column} = ?, updated_at = ? WHERE task_id = ? AND owner_user_id = ?",
            (value, now, task_id, user["user_id"]),
        )
        connection.execute(
            """INSERT INTO audit_events
               (task_id, event_type, from_status, to_status, actor, details_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                task_id, event_type, row["status"], row["status"],
                user.get("display_name") or user["user_id"],
                json.dumps({"action": request.action}, ensure_ascii=False), now,
            ),
        )
    return {
        "task_id": task_id,
        "starred_at": value if column == "starred_at" else row["starred_at"],
        "archived_at": value if column == "archived_at" else row["archived_at"],
    }


@app.delete("/api/tasks/{task_id}")
def permanently_delete_task(task_id: str, user: dict = Depends(require_user)) -> dict:
    row = get_task_row(task_id, user["user_id"])
    workbench.queue()  # Ensure migration tables exist for older installations.
    image_path = resolve_managed_media(row["image_path"], UPLOADS_DIR)
    attention_path = resolve_managed_media(row["attention_path"], ATTENTION_DIR)
    with database_connection() as connection:
        connection.execute('BEGIN IMMEDIATE')
        workbench.forget_task(connection, task_id)
        series_ids = [
            item["series_id"] for item in connection.execute(
                "SELECT series_id FROM analysis_series_items WHERE task_id = ?", (task_id,)
            ).fetchall()
        ]
        connection.execute(
            "UPDATE agent_conversations SET linked_task_id = NULL WHERE linked_task_id = ? AND user_id = ?",
            (task_id, user["user_id"]),
        )
        connection.execute("DELETE FROM evidence_queries WHERE task_id = ?", (task_id,))
        connection.execute("DELETE FROM audit_events WHERE task_id = ?", (task_id,))
        connection.execute("DELETE FROM analysis_series_items WHERE task_id = ?", (task_id,))
        connection.execute(
            "DELETE FROM analysis_tasks WHERE task_id = ? AND owner_user_id = ?",
            (task_id, user["user_id"]),
        )
        for series_id in series_ids:
            remaining = connection.execute(
                "SELECT 1 FROM analysis_series_items WHERE series_id = ? LIMIT 1", (series_id,)
            ).fetchone()
            if remaining is None:
                connection.execute(
                    "DELETE FROM analysis_series WHERE series_id = ? AND owner_user_id = ?",
                    (series_id, user["user_id"]),
                )
    removed_media = 0
    for path in {image_path, attention_path} - {None}:
        try:
            path.unlink(missing_ok=True)
            removed_media += 1
        except OSError:
            pass
    return {"task_id": task_id, "deleted": True, "removed_media": removed_media}


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str, user: dict = Depends(require_user)) -> dict:
    return row_to_task(get_task_row(task_id, user["user_id"]))


@app.get("/api/tasks/{task_id}/image")
def get_task_image(task_id: str, user: dict = Depends(require_user)):
    row = get_task_row(task_id, user["user_id"])
    image_path = resolve_managed_media(row["image_path"], UPLOADS_DIR)
    if image_path is None:
        raise HTTPException(status_code=404, detail="任务影像不存在")
    return FileResponse(
        image_path,
        filename=row["file_name"],
        headers={"Cache-Control": "private, no-store"},
    )


@app.get("/api/tasks/{task_id}/attention")
def get_task_attention(task_id: str, user: dict = Depends(require_user)):
    row = get_task_row(task_id, user["user_id"])
    attention_path = resolve_managed_media(row["attention_path"], ATTENTION_DIR)
    if attention_path is None:
        raise HTTPException(status_code=404, detail="该任务没有可用的Grad-CAM注意力图")
    return FileResponse(
        attention_path,
        media_type="image/png",
        filename=f"{task_id}-gradcam.png",
        headers={"Cache-Control": "private, no-store"},
    )


@app.get("/api/tasks/{task_id}/audit")
def get_task_audit(task_id: str, user: dict = Depends(require_user)) -> dict:
    get_task_row(task_id, user["user_id"])
    with database_connection() as connection:
        rows = connection.execute(
            """
            SELECT event_id, event_type, from_status, to_status, actor, details_json, created_at
            FROM audit_events WHERE task_id = ? ORDER BY created_at ASC, event_id ASC
            """,
            (task_id,),
        ).fetchall()
    return {
        "items": [
            {
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "from_status": row["from_status"],
                "to_status": row["to_status"],
                "actor": row["actor"],
                "details": json.loads(row["details_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
    }


@app.get("/api/evidence/sources")
def get_evidence_sources(user: dict = Depends(require_user)) -> dict:
    result = knowledge_sources(DATABASE_PATH)
    for item in result["items"]:
        metadata = item["metadata"]
        item["can_review"] = item["source_type"] == "ONLINE_PAPER" and metadata.get("owner_user_id") == user["user_id"]
        for private_key in ("owner_user_id", "previous_note", "upstream_hash"):
            metadata.pop(private_key, None)
    return result


class LiteratureImportRequest(BaseModel):
    model_config = {"extra": "forbid"}
    pmid: str = Field(pattern=r"^\d{1,10}$")
    topic: str = Field(max_length=50)


class LiteratureReviewRequest(BaseModel):
    model_config = {"extra": "forbid"}
    enabled: StrictBool
    note: str = Field(default="", max_length=2000)
    acknowledged: StrictBool = False


@app.get("/api/evidence/online/topics")
def get_literature_topics(_: dict = Depends(require_user)) -> dict:
    return {"items": [{"value": key, "label": value[0]} for key, value in TOPICS.items()]}


@app.get("/api/evidence/online/search")
def find_online_literature(topic: str, since: int = 2020, _: dict = Depends(require_user)) -> dict:
    try:
        return search_literature(topic=topic, since=since)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LiteratureUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/evidence/online/import")
def import_online_literature(request: LiteratureImportRequest, user: dict = Depends(require_conversation_user)) -> dict:
    try:
        return import_literature(DATABASE_PATH, pmid=request.pmid, topic=request.topic, user_id=user["user_id"])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LiteratureUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.put("/api/evidence/sources/{source_id}/review")
def review_online_literature(source_id: str, request: LiteratureReviewRequest, user: dict = Depends(require_conversation_user)) -> dict:
    try:
        return review_literature(DATABASE_PATH, source_id=source_id, user_id=user["user_id"],
                                enabled=request.enabled, note=request.note, acknowledged=request.acknowledged)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/evaluation/dataset")
def get_evaluation_dataset(_: dict = Depends(require_user)) -> dict:
    return dataset_summary(EVALUATION_DATASET_PATH)


@app.get("/api/evaluation/runs")
def get_evaluation_runs(
    limit: int = Query(default=10, ge=1, le=50),
    _: dict = Depends(require_user),
) -> dict:
    return {"items": list_evaluation_runs(DATABASE_PATH, limit)}


@app.get("/api/evaluation/runs/{run_id}")
def get_evaluation_run_detail(run_id: str, _: dict = Depends(require_user)) -> dict:
    result = get_evaluation_run(DATABASE_PATH, run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="评测运行记录不存在")
    return result


@app.post("/api/evaluation/run")
def execute_evaluation(_: dict = Depends(require_user)) -> dict:
    return run_evaluation(DATABASE_PATH, EVALUATION_DATASET_PATH)


@app.get("/api/evidence/sources/{source_id}/content")
def get_evidence_source_content(source_id: str, _: dict = Depends(require_user)):
    note = literature_content(DATABASE_PATH, source_id)
    if note is not None:
        return Response(content=public_text(note), media_type="text/plain; charset=utf-8", headers={"Cache-Control": "no-store"})
    with database_connection() as connection:
        row = connection.execute(
            "SELECT title, source_type, locator, metadata_json FROM evidence_sources WHERE source_id = ?", (source_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="证据来源不存在")
    if json.loads(row["metadata_json"]).get("public_hidden"):
        raise HTTPException(status_code=404, detail="该内部资料不在公开资料库中")
    locator = row["locator"]
    if "::" in locator:
        archive_name, entry = locator.split("::", 1)
        archive_path = (WORKSPACE_ROOT / archive_name).resolve()
        if archive_path.parent != WORKSPACE_ROOT.resolve() or not archive_path.is_file():
            raise HTTPException(status_code=404, detail="证据程序包不存在")
        with zipfile.ZipFile(archive_path) as archive:
            try:
                payload = archive.read(entry)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="程序包内证据文件不存在") from exc
        return Response(
            content=public_text(payload.decode("utf-8", errors="replace")),
            media_type="application/json" if entry.lower().endswith(".json") else "text/plain; charset=utf-8",
            headers={"Content-Disposition": f'inline; filename="{Path(entry).name}"'},
        )
    source_path = (WORKSPACE_ROOT / locator).resolve()
    if WORKSPACE_ROOT.resolve() not in source_path.parents or not source_path.is_file():
        raise HTTPException(status_code=404, detail="本地证据文件不存在")
    if source_path.suffix.lower() == ".pdf":
        return FileResponse(source_path, filename=pdf_download_name(row["title"]), media_type="application/pdf")
    if source_path.suffix.lower() in {".md", ".json", ".txt", ".py"}:
        return Response(content=public_text(source_path.read_text(encoding="utf-8")), media_type="text/plain; charset=utf-8")
    return FileResponse(source_path, filename=source_path.name)


@app.get("/api/tasks/{task_id}/evidence/history")
def get_evidence_history(task_id: str, user: dict = Depends(require_user)) -> dict:
    get_task_row(task_id, user["user_id"])
    return {"items": evidence_history(DATABASE_PATH, task_id)}


@app.post("/api/tasks/{task_id}/evidence/query")
def query_evidence(
    task_id: str,
    request: EvidenceQueryRequest,
    user: dict = Depends(require_user),
) -> dict:
    row = get_task_row(task_id, user["user_id"])
    chat = execute_agent_chat(AgentChatRequest(
        question=request.question, linked_task_id=task_id, conversation_id=request.conversation_id,
    ), user)
    result = {
        **chat, "query_id": f"EVD-{uuid.uuid4().hex[:12].upper()}",
        "evidence": chat["citations"], "limitations": [*chat["uncertainty"], chat["disclaimer"]],
        "include_in_report": request.include_in_report,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    with database_connection() as connection:
        connection.execute(
            """INSERT INTO evidence_queries
               (query_id, task_id, question, support_level, answer_json, include_in_report, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (result["query_id"], task_id, result["question"], result["support_level"],
             json.dumps(result, ensure_ascii=False), int(request.include_in_report), result["created_at"]),
        )
        connection.execute(
            """
            INSERT INTO audit_events (
                task_id, event_type, from_status, to_status, actor, details_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                "EVIDENCE_QUERY",
                row["status"],
                row["status"],
                "CT Hybrid Agent",
                json.dumps(
                    {
                        "query_id": result["query_id"],
                        "support_level": result["support_level"],
                        "evidence_count": len(result["evidence"]),
                        "include_in_report": request.include_in_report,
                    },
                    ensure_ascii=False,
                ),
                result["created_at"],
            ),
        )
    return result


@app.post("/api/tasks/{task_id}/review")
def review_task(
    task_id: str,
    review: ReviewRequest,
    user: dict = Depends(require_user),
) -> dict:
    row = get_task_row(task_id, user["user_id"])
    if row["status"] != "WAITING_FOR_REVIEW":
        raise HTTPException(status_code=409, detail="该任务已经完成复核")

    classes = runtime.manifest["class_names"]
    classes_cn = runtime.manifest["class_names_cn"]
    corrected_class = None
    corrected_class_cn = None
    if review.decision == "CORRECT":
        if review.corrected_class not in classes:
            raise HTTPException(status_code=422, detail="修正类别无效")
        corrected_class = review.corrected_class
        corrected_class_cn = classes_cn[classes.index(corrected_class)]

    status_by_decision = {
        "CONFIRM": "CONFIRMED",
        "CORRECT": "CORRECTED",
        "UNDETERMINED": "UNDETERMINED",
    }
    updated_at = datetime.now(timezone.utc).isoformat()
    with database_connection() as connection:
        connection.execute(
            """
            UPDATE analysis_tasks
            SET status = ?, updated_at = ?, reviewer_name = ?, review_decision = ?,
                corrected_class = ?, corrected_class_cn = ?, review_comment = ?, reviewed_at = ?
            WHERE task_id = ? AND status = 'WAITING_FOR_REVIEW'
            """,
            (
                status_by_decision[review.decision],
                updated_at,
                review.reviewer_name.strip(),
                review.decision,
                corrected_class,
                corrected_class_cn,
                review.comment.strip(),
                updated_at,
                task_id,
            ),
        )
        connection.execute(
            """
            INSERT INTO audit_events (
                task_id, event_type, from_status, to_status, actor, details_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                "REVIEW_SUBMITTED",
                row["status"],
                status_by_decision[review.decision],
                review.reviewer_name.strip(),
                json.dumps(
                    {
                        "decision": review.decision,
                        "corrected_class": corrected_class,
                        "comment": review.comment.strip(),
                    },
                    ensure_ascii=False,
                ),
                updated_at,
            ),
        )
    return row_to_task(get_task_row(task_id, user["user_id"]))


@app.get("/api/tasks/{task_id}/report")
def download_report(task_id: str, user: dict = Depends(require_user)):
    row = get_task_row(task_id, user["user_id"])
    task = row_to_task(row)
    probabilities = task["prediction"]["probabilities"]
    labels = dict(zip(runtime.manifest["class_names"], runtime.manifest["class_names_cn"]))
    probability_rows = "".join(
        f"<tr><td>{html.escape(labels[key])}</td><td>{value * 100:.2f}%</td></tr>"
        for key, value in probabilities.items()
    )
    warnings = task["reliability"]["warnings"]
    warnings_text = "；".join(warnings) if warnings else "无工程可靠性警告"
    qc_warnings = task["quality_control"].get("warnings", [])
    qc_warnings_text = "；".join(qc_warnings) if qc_warnings else "影像工程质控通过"
    priority = task["priority"]
    metrics = task["quality_control"].get("metrics", {})

    image_path = resolve_managed_media(row["image_path"], UPLOADS_DIR)
    suffix_mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".bmp": "image/bmp", ".tif": "image/tiff", ".tiff": "image/tiff"}
    image_mime = suffix_mime.get(image_path.suffix.lower(), "image/png") if image_path else "image/png"
    original_data = base64.b64encode(image_path.read_bytes()).decode("ascii") if image_path else ""
    attention_path = resolve_managed_media(row["attention_path"], ATTENTION_DIR)
    attention_data = base64.b64encode(attention_path.read_bytes()).decode("ascii") if attention_path else ""
    images_html = ""
    if original_data:
        images_html += f'<figure><img src="data:{image_mime};base64,{original_data}" alt="原始二维CT"><figcaption>原始二维 CT</figcaption></figure>'
    if attention_data:
        images_html += f'<figure><img src="data:image/png;base64,{attention_data}" alt="五折平均Grad-CAM"><figcaption>五折平均 Grad-CAM 注意力图（非病灶分割）</figcaption></figure>'

    with database_connection() as connection:
        audit_rows = connection.execute(
            "SELECT event_type, actor, from_status, to_status, created_at FROM audit_events WHERE task_id = ? ORDER BY created_at ASC",
            (task_id,),
        ).fetchall()
    audit_html = "".join(
        f"<tr><td>{html.escape(event['created_at'])}</td><td>{html.escape(event['event_type'])}</td><td>{html.escape(event['actor'])}</td><td>{html.escape(event['to_status'] or '')}</td></tr>"
        for event in audit_rows
    ) or "<tr><td colspan=\"4\">暂无审计事件</td></tr>"
    evidence_queries = [item for item in evidence_history(DATABASE_PATH, task_id) if item.get("include_in_report")]
    evidence_parts: list[str] = []
    for item in evidence_queries:
        citation_parts = []
        for card in item["evidence"]:
            page_label = f"，第{card['page_number']}页" if card.get("page_number") else ""
            citation_parts.append(
                f"<li>[{html.escape(card['citation_id'])}] {html.escape(card['title'])} - "
                f"{html.escape(card['locator'])}{page_label}</li>"
            )
        answer_html = html.escape(item["answer"]).replace("\n", "<br>")
        limitations_html = html.escape("；".join(item.get("limitations", [])))
        evidence_parts.append(
            f"<article class=\"evidence\"><h3>{html.escape(item['question'])}</h3>"
            f"<p>{answer_html}</p><ul>{''.join(citation_parts)}</ul>"
            f"<small>来源状态：{html.escape(item['support_level'])}；本地引文核对不代表临床验证。</small>"
            f"<p class=\"warning\">{limitations_html}</p></article>"
        )
    evidence_html = "".join(evidence_parts) or "<p>本报告尚未附加循证问答。</p>"
    review = task.get("review")
    review_text = "等待医生复核"
    if review:
        decision_labels = {"CONFIRM": "确认模型结果", "CORRECT": "修正模型结果", "UNDETERMINED": "无法判断"}
        corrected = f"；修正为：{html.escape(review['corrected_class_cn'])}" if review.get("corrected_class_cn") else ""
        review_text = (
            f"{decision_labels[review['decision']]}{corrected}；复核人：{html.escape(review['reviewer_name'])}；"
            f"意见：{html.escape(review.get('comment') or '未填写')}"
        )
    annotations_html = workbench.annotation_report(task_id, user["user_id"])
    document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{html.escape(task_id)} 分析报告</title>
<style>body{{max-width:900px;margin:40px auto;padding:0 24px;font:14px/1.7 Arial,"Microsoft YaHei",sans-serif;color:#17272b}}h1{{font-size:28px}}h2{{margin-top:28px;font-size:17px;border-bottom:1px solid #dce7e8;padding-bottom:8px}}table{{width:100%;border-collapse:collapse}}td{{padding:9px;border-bottom:1px solid #edf2f2}}td:last-child{{text-align:right;font-family:monospace}}.meta{{color:#587076}}.warning{{padding:12px;background:#fff8e8;border-left:3px solid #d9a834}}.notice{{margin-top:35px;padding:14px;background:#eef8f7;color:#496466}}.images{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}figure{{margin:0}}img{{width:100%;max-height:390px;object-fit:contain;background:#071015}}figcaption{{margin-top:5px;color:#587076;font-size:12px}}.evidence{{margin:12px 0;padding:14px;border:1px solid #dce7e8;border-radius:8px}}.evidence h3{{margin:0 0 8px;font-size:15px}}.evidence p{{margin:0}}.evidence li,.evidence small{{color:#587076;font-size:12px}}@media print{{body{{margin:0}}}}</style></head>
<body><h1>LungSight 二维 CT 辅助分析报告</h1><p class="meta">任务编号：{html.escape(task_id)}<br>生成时间：{html.escape(task['updated_at'])}<br>任务状态：{html.escape(task['status'])}</p>
<h2>影像与模型</h2><p>文件：{html.escape(task['input']['file_name'])}<br>SHA-256：{html.escape(task['input']['sha256'])}<br>尺寸：{task['input']['image_size'][0]} × {task['input']['image_size'][1]}<br>模型：{html.escape(task['model']['name'])} / {html.escape(task['model']['version'])}</p>
<div class="images">{images_html}</div>{annotations_html}<h2>质控与优先级</h2><p>质控状态：<strong>{html.escape(task['quality_control']['status'])}</strong><br>复核优先级：<strong>{html.escape(priority['label_cn'])}</strong><br>亮度均值：{metrics.get('mean_luminance', '—')}；对比度：{metrics.get('contrast_std', '—')}；边缘方差：{metrics.get('edge_variance', '—')}</p><p class="warning">质控提示：{html.escape(qc_warnings_text)}</p>
<h2>模型内部研究排序</h2><p>内部最高排序（非诊断）：<strong>{html.escape(task['prediction']['top_class_cn'])}</strong><br>五折一致性：{html.escape(task['reliability']['fold_agreement'])}<br>可靠性：{html.escape(task['reliability']['level'])}</p><table>{probability_rows}</table>
<p class="warning">可靠性提示：{html.escape(warnings_text)}</p><h2>医生复核</h2><p>{review_text}</p><h2>循证协作记录</h2>{evidence_html}<h2>审计记录</h2><table><tr><td>时间</td><td>事件</td><td>执行者</td><td>状态</td></tr>{audit_html}</table>
<p class="notice">{html.escape(task['disclaimer'])}</p></body></html>"""
    return Response(
        content=public_text(document),
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{task_id}-report.html"'},
    )


def complete_dicom_result(result, dicom_summary):
    dicom_summary["analyzed_slice_count"] = len(result["items"])
    result["dicom"] = dicom_summary
    result["summary"]["uploaded_count"] = dicom_summary["input_file_count"]
    result["summary"]["analyzed_count"] = len(result["items"])
    result["summary"]["failed_count"] = len(result["failures"])
    warnings = result["reliability"]["warnings"]
    warnings.extend(dicom_summary.get("warnings", []))
    lung_selection = dicom_summary.get("lung_selection", {})
    if lung_selection.get("excluded_edge_slice_count", 0):
        warnings.append(
            f"肺野覆盖筛选排除了{lung_selection['excluded_edge_slice_count']}层边缘低覆盖切片"
        )
    if dicom_summary["subsampled"]:
        warnings.append(
            f"已从{dicom_summary['readable_slice_count']}层中等距抽取最多{DICOM_ANALYSIS_SLICES}层进入原型分析"
        )
    privacy = dicom_summary["privacy"]
    if privacy["direct_identifier_fields_detected"]:
        warnings.append("检测到DICOM身份字段；字段值未保存，像素隐私仍需人工复核")
    if privacy["burned_in_annotation"] != ["NO"]:
        warnings.append("部分DICOM未明确声明无烧录文字，需人工检查像素区域")
    dicom_blockers: list[str] = []
    if lung_selection:
        gate = result["quality_gate"]
        gate["thresholds"]["minimum_dicom_lung_region_slices"] = DICOM_MIN_LUNG_REGION_SLICES
        gate["metrics"]["dicom_lung_region_slices"] = int(lung_selection.get("eligible_slice_count", 0))
        if lung_selection.get("status") != "APPLIED":
            dicom_blockers.append("无法稳定定位连续肺野有效区间")
        if int(lung_selection.get("eligible_slice_count", 0)) < DICOM_MIN_LUNG_REGION_SLICES:
            dicom_blockers.append(f"肺野有效区间少于{DICOM_MIN_LUNG_REGION_SLICES}层")
    if dicom_blockers:
        gate = result["quality_gate"]
        for reason in dicom_blockers:
            if reason not in gate["reasons"]:
                gate["reasons"].append(reason)
                warnings.append(f"{reason}，病例级结果证据不足")
        gate["status"] = "BLOCKED"
        result["prediction"]["decision"] = "INDETERMINATE"
    result["reliability"]["level"] = "REVIEW_REQUIRED"
    result["reliability"]["rule_version"] = "dicom-series-weighted-v1"
    result["disclaimer"] = (
        "DICOM已在本机转换为固定肺窗派生切片；原始DICOM及身份字段值未保存。"
        "该弱标签研究原型不是诊断设备，像素隐私和全部结果均须由专业人员复核。"
    )
    return result


from workbench import Workbench
workbench = Workbench(sys.modules[__name__])
