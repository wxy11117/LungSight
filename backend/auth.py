"""LungSight 本地账号、会话和 OpenAI 凭据存储。

账号与会话都由后端负责。浏览器只持有 HttpOnly 会话 Cookie，
OpenAI API Key 使用 Fernet 在 SQLite 落盘前加密。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken
from registration import masked_phone, normalize_phone, validate_doctor_profile


SESSION_COOKIE_NAME = "lungsight_session"
SESSION_HOURS = int(os.environ.get("LUNGSIGHT_SESSION_HOURS", "12"))
MAX_LOGIN_FAILURES = 5
LOCK_MINUTES = 15
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)

LLM_PROVIDERS = {
    "openai": {
        "label": "OpenAI · ChatGPT",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-5.4",
        "models": ["gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano"],
    },
    "kimi": {
        "label": "Kimi · 月之暗面",
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "kimi-k3",
        "models": ["kimi-k3", "kimi-k2.6"],
    },
    "deepseek": {
        "label": "DeepSeek · 深度求索",
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-v4-flash",
        "models": ["deepseek-v4-flash", "deepseek-v4-pro"],
    },
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if len(normalized) > 254 or not EMAIL_PATTERN.fullmatch(normalized):
        raise ValueError("请输入有效的电子邮箱")
    return normalized


def validate_password(password: str) -> None:
    if len(password) < 10:
        raise ValueError("密码至少需要10个字符")
    if len(password) > 128:
        raise ValueError("密码不能超过128个字符")
    if not any(character.isalpha() for character in password) or not any(
        character.isdigit() for character in password
    ):
        raise ValueError("密码必须同时包含字母和数字")


def validate_display_name(display_name: str) -> str:
    clean_name = display_name.strip()
    if not 2 <= len(clean_name) <= 60:
        raise ValueError("昵称需要2至60个字符")
    if any(unicodedata.category(character).startswith("C") or character in "\u2028\u2029" for character in clean_name):
        raise ValueError("昵称不能包含换行或不可见控制字符")
    return clean_name


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


def initialize_auth_schema(database_path: Path) -> None:
    with connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                failed_login_count INTEGER NOT NULL DEFAULT 0,
                locked_until TEXT,
                accepted_terms_at TEXT NOT NULL,
                accepted_privacy_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_login_at TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked_at TEXT,
                user_agent TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
            """
        )
        # Additive migration: preserve existing accounts, credentials and sessions.
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(users)")}
        if "avatar_version" not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN avatar_version TEXT")
        if "phone" not in columns:
            connection.execute("ALTER TABLE users ADD COLUMN phone TEXT")
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone ON users(phone) WHERE phone IS NOT NULL")
        connection.execute("""CREATE TABLE IF NOT EXISTS doctor_profiles (
            user_id TEXT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
            profile_json TEXT NOT NULL,
            declared_at TEXT NOT NULL
        )""")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_avatars (
                user_id TEXT PRIMARY KEY,
                image_png BLOB NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS openai_credentials (
                credential_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL UNIQUE,
                encrypted_api_key TEXT NOT NULL,
                key_suffix TEXT NOT NULL,
                model TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'SAVED',
                verified_at TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS llm_credentials (
                credential_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                encrypted_api_key TEXT NOT NULL,
                key_suffix TEXT NOT NULL,
                model TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'SAVED',
                verified_at TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, provider),
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_llm_preferences (
                user_id TEXT PRIMARY KEY,
                selected_provider TEXT NOT NULL DEFAULT 'openai',
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS account_audit_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                event_type TEXT NOT NULL,
                details TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_sessions_user_expires ON user_sessions(user_id, expires_at)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_account_audit_user_created ON account_audit_events(user_id, created_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_llm_credentials_user_provider ON llm_credentials(user_id, provider)"
        )
        # Preserve credentials created by the original OpenAI-only release.
        connection.execute(
            """
            INSERT OR IGNORE INTO llm_credentials (
                credential_id, user_id, provider, encrypted_api_key, key_suffix, model,
                status, verified_at, last_error, created_at, updated_at
            )
            SELECT 'LLM-' || credential_id, user_id, 'openai', encrypted_api_key,
                   key_suffix, model, status, verified_at, last_error, created_at, updated_at
            FROM openai_credentials
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO user_llm_preferences (user_id, selected_provider, updated_at)
            SELECT user_id, 'openai', updated_at FROM openai_credentials
            """
        )
        connection.execute("PRAGMA optimize")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _public_user(row: sqlite3.Row) -> dict:
    return {
        "user_id": row["user_id"],
        # Legacy schema requires a unique, non-null email. Phone-only accounts
        # use an internal non-email sentinel that is never exposed or accepted for login.
        "email": row["email"] if EMAIL_PATTERN.fullmatch(row["email"]) else None,
        "phone_masked": masked_phone(row["phone"]),
        "identity_verification": "UNVERIFIED",
        "display_name": row["display_name"],
        "status": row["status"],
        "created_at": row["created_at"],
        "last_login_at": row["last_login_at"],
        "avatar_url": f'/api/auth/avatar?v={row["avatar_version"]}' if row["avatar_version"] else None,
    }


def _masked_email(email: str) -> str | None:
    if not EMAIL_PATTERN.fullmatch(email):
        return None
    local, domain = email.split("@", 1)
    visible = local[:2] if len(local) > 1 else local[:1]
    return f"{visible}{'*' * max(3, len(local) - len(visible))}@{domain}"


def list_local_accounts(database_path: Path, *, current_user_id: str) -> list[dict]:
    """Return safe account-picker rows to an already authenticated local user."""
    with connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT user_id, email, phone, display_name, avatar_version, created_at, last_login_at
            FROM users
            WHERE status = 'ACTIVE'
            ORDER BY CASE WHEN user_id = ? THEN 0 ELSE 1 END,
                     COALESCE(last_login_at, created_at) DESC,
                     user_id ASC
            """,
            (current_user_id,),
        ).fetchall()
    return [{
        "user_id": row["user_id"],
        "display_name": row["display_name"],
        "identity_hint": _masked_email(row["email"]) or masked_phone(row["phone"]),
        "last_login_at": row["last_login_at"],
        "is_current": row["user_id"] == current_user_id,
        "avatar_url": f'/api/auth/accounts/{row["user_id"]}/avatar?v={row["avatar_version"]}' if row["avatar_version"] else None,
    } for row in rows]


def _audit(connection: sqlite3.Connection, user_id: str | None, event_type: str, details: str) -> None:
    connection.execute(
        "INSERT INTO account_audit_events (user_id, event_type, details, created_at) VALUES (?, ?, ?, ?)",
        (user_id, event_type, details[:1000], iso_now()),
    )


def update_display_name(database_path: Path, *, user_id: str, display_name: str) -> dict:
    clean_name = validate_display_name(display_name)
    with connect(database_path) as connection:
        changed = connection.execute(
            "UPDATE users SET display_name = ?, updated_at = ? WHERE user_id = ? AND status = 'ACTIVE'",
            (clean_name, iso_now(), user_id),
        )
        if changed.rowcount != 1:
            raise LookupError("账号不可用，请重新登录")
        _audit(connection, user_id, "PROFILE_NAME_UPDATED", "用户更新昵称")
        row = connection.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return _public_user(row)


def save_avatar(database_path: Path, *, user_id: str, image_png: bytes) -> dict:
    version = hashlib.sha256(image_png).hexdigest()
    updated_at = iso_now()
    with connect(database_path) as connection:
        changed = connection.execute(
            "UPDATE users SET avatar_version = ?, updated_at = ? WHERE user_id = ? AND status = 'ACTIVE'",
            (version, updated_at, user_id),
        )
        if changed.rowcount != 1:
            raise LookupError("账号不可用，请重新登录")
        connection.execute(
            """INSERT INTO user_avatars (user_id, image_png, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET image_png = excluded.image_png, updated_at = excluded.updated_at""",
            (user_id, image_png, updated_at),
        )
        _audit(connection, user_id, "PROFILE_AVATAR_UPDATED", "用户更新头像，已清除图像元数据")
        row = connection.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return _public_user(row)


def load_avatar(database_path: Path, *, user_id: str) -> bytes | None:
    with connect(database_path) as connection:
        row = connection.execute("SELECT image_png FROM user_avatars WHERE user_id = ?", (user_id,)).fetchone()
    return bytes(row["image_png"]) if row else None


def register_user(
    database_path: Path,
    *,
    email: str | None = None,
    display_name: str,
    password: str,
    accepted_terms: bool,
    accepted_privacy: bool,
    phone: str | None = None,
    doctor_profile: dict | None = None,
    confirm_password: str | None = None,
) -> dict:
    if bool(email) == bool(phone):
        raise ValueError("请选择手机号或邮箱其中一种注册方式")
    normalized_email = normalize_email(email) if email else None
    normalized_phone = normalize_phone(phone) if phone else None
    clean_profile = validate_doctor_profile(doctor_profile) if doctor_profile is not None else None
    if (clean_profile is not None or normalized_phone is not None) and password != confirm_password:
        raise ValueError("两次输入的密码不一致")
    clean_name = validate_display_name(display_name)
    validate_password(password)
    if not accepted_terms or not accepted_privacy:
        raise ValueError("注册前需要同意用户协议和隐私政策")
    created_at = iso_now()
    user_id = f"USR-{uuid.uuid4().hex[:12].upper()}"
    try:
        with connect(database_path) as connection:
            connection.execute(
                """
                INSERT INTO users (
                    user_id, email, phone, display_name, password_hash, status,
                    accepted_terms_at, accepted_privacy_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?, ?, ?, ?)
                """,
                (
                    user_id,
                    normalized_email or f"phone-account:{user_id}",
                    normalized_phone,
                    clean_name,
                    PASSWORD_HASHER.hash(password),
                    created_at,
                    created_at,
                    created_at,
                    created_at,
                ),
            )
            if clean_profile is not None:
                connection.execute("INSERT INTO doctor_profiles (user_id, profile_json, declared_at) VALUES (?, ?, ?)",
                                   (user_id, json.dumps(clean_profile, ensure_ascii=False), created_at))
                _audit(connection, user_id, "DOCTOR_PROFILE_DECLARED", "用户自填医院与医生资料，未核验")
            _audit(connection, user_id, "ACCOUNT_REGISTERED", "产品账号创建")
            row = connection.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    except sqlite3.IntegrityError as exc:
        if "users.email" in str(exc) or "users.phone" in str(exc):
            raise ValueError("该手机号或邮箱已经注册，请登录或更换注册方式") from exc
        raise
    return _public_user(row)


def authenticate_user(database_path: Path, *, email: str | None = None, phone: str | None = None, user_id: str | None = None, password: str) -> dict | None:
    if sum(bool(value) for value in (email, phone, user_id)) != 1:
        return None
    try:
        identifier = user_id.strip() if user_id else normalize_phone(phone) if phone else normalize_email(email)
    except ValueError:
        return None
    if user_id and not re.fullmatch(r"USR-[A-F0-9]{12}", identifier):
        return None
    with connect(database_path) as connection:
        column = "user_id" if user_id else "phone" if phone else "email"
        row = connection.execute(f"SELECT * FROM users WHERE {column} = ?", (identifier,)).fetchone()
        if row is None or row["status"] != "ACTIVE":
            return None
        if row["locked_until"]:
            locked_until = datetime.fromisoformat(row["locked_until"])
            if locked_until > utc_now():
                raise PermissionError("登录尝试过多，请稍后再试")
        try:
            password_ok = PASSWORD_HASHER.verify(row["password_hash"], password)
        except (VerifyMismatchError, InvalidHashError):
            password_ok = False
        if not password_ok:
            failures = int(row["failed_login_count"]) + 1
            locked_until = None
            if failures >= MAX_LOGIN_FAILURES:
                locked_until = (utc_now() + timedelta(minutes=LOCK_MINUTES)).isoformat()
                failures = 0
            connection.execute(
                "UPDATE users SET failed_login_count = ?, locked_until = ?, updated_at = ? WHERE user_id = ?",
                (failures, locked_until, iso_now(), row["user_id"]),
            )
            _audit(connection, row["user_id"], "LOGIN_FAILED", "密码验证失败")
            return None
        if PASSWORD_HASHER.check_needs_rehash(row["password_hash"]):
            connection.execute(
                "UPDATE users SET password_hash = ? WHERE user_id = ?",
                (PASSWORD_HASHER.hash(password), row["user_id"]),
            )
        logged_in_at = iso_now()
        connection.execute(
            """
            UPDATE users SET failed_login_count = 0, locked_until = NULL,
                last_login_at = ?, updated_at = ? WHERE user_id = ?
            """,
            (logged_in_at, logged_in_at, row["user_id"]),
        )
        _audit(connection, row["user_id"], "LOGIN_SUCCEEDED", "账号登录成功")
        refreshed = connection.execute("SELECT * FROM users WHERE user_id = ?", (row["user_id"],)).fetchone()
    return _public_user(refreshed)


def get_doctor_profile(database_path: Path, *, user_id: str) -> dict | None:
    with connect(database_path) as connection:
        row = connection.execute("SELECT profile_json, declared_at FROM doctor_profiles WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        return None
    return {**json.loads(row["profile_json"]), "verification_status": "SELF_DECLARED", "declared_at": row["declared_at"]}


def create_session(database_path: Path, *, user_id: str, user_agent: str | None) -> tuple[str, str]:
    token = secrets.token_urlsafe(48)
    created_at = utc_now()
    expires_at = created_at + timedelta(hours=SESSION_HOURS)
    with connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO user_sessions (
                session_id, user_id, token_hash, created_at, expires_at, user_agent
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                f"SES-{uuid.uuid4().hex[:14].upper()}",
                user_id,
                _token_hash(token),
                created_at.isoformat(),
                expires_at.isoformat(),
                (user_agent or "")[:300],
            ),
        )
        connection.execute(
            "DELETE FROM user_sessions WHERE expires_at <= ? OR revoked_at IS NOT NULL",
            (created_at.isoformat(),),
        )
    return token, expires_at.isoformat()


def get_user_for_session(database_path: Path, token: str | None) -> dict | None:
    if not token:
        return None
    with connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT u.*, s.session_id, s.expires_at
            FROM user_sessions s
            JOIN users u ON u.user_id = s.user_id
            WHERE s.token_hash = ? AND s.revoked_at IS NULL AND s.expires_at > ?
            """,
            (_token_hash(token), iso_now()),
        ).fetchone()
    if row is None or row["status"] != "ACTIVE":
        return None
    user = _public_user(row)
    user["session_expires_at"] = row["expires_at"]
    return user


def revoke_session(database_path: Path, token: str | None) -> None:
    if not token:
        return
    with connect(database_path) as connection:
        row = connection.execute(
            "SELECT user_id FROM user_sessions WHERE token_hash = ?", (_token_hash(token),)
        ).fetchone()
        connection.execute(
            "UPDATE user_sessions SET revoked_at = ? WHERE token_hash = ?",
            (iso_now(), _token_hash(token)),
        )
        if row:
            _audit(connection, row["user_id"], "SESSION_REVOKED", "用户主动退出登录")


def _credential_cipher(data_dir: Path) -> Fernet:
    configured = os.environ.get("LUNGSIGHT_CREDENTIAL_SECRET", "").strip()
    if configured:
        key = configured.encode("ascii")
    else:
        secret_path = data_dir / "credential_secret.key"
        if secret_path.is_file():
            key = secret_path.read_bytes().strip()
        else:
            data_dir.mkdir(parents=True, exist_ok=True)
            key = Fernet.generate_key()
            secret_path.write_bytes(key)
            try:
                secret_path.chmod(0o600)
            except OSError:
                pass
    try:
        return Fernet(key)
    except (ValueError, TypeError) as exc:
        raise RuntimeError("LUNGSIGHT_CREDENTIAL_SECRET 不是有效的Fernet密钥") from exc


def save_openai_credential(
    database_path: Path,
    data_dir: Path,
    *,
    user_id: str,
    api_key: str,
    model: str,
) -> dict:
    clean_key = api_key.strip()
    clean_model = model.strip()
    if len(clean_key) < 20 or not clean_key.startswith("sk-"):
        raise ValueError("OpenAI API Key格式不正确")
    if not 2 <= len(clean_model) <= 80 or not re.fullmatch(r"[A-Za-z0-9._:-]+", clean_model):
        raise ValueError("OpenAI模型名称格式不正确")
    encrypted = _credential_cipher(data_dir).encrypt(clean_key.encode("utf-8")).decode("ascii")
    now = iso_now()
    with connect(database_path) as connection:
        existing = connection.execute(
            "SELECT credential_id, created_at FROM openai_credentials WHERE user_id = ?", (user_id,)
        ).fetchone()
        credential_id = existing["credential_id"] if existing else f"OAI-{uuid.uuid4().hex[:12].upper()}"
        created_at = existing["created_at"] if existing else now
        connection.execute(
            """
            INSERT INTO openai_credentials (
                credential_id, user_id, encrypted_api_key, key_suffix, model,
                status, verified_at, last_error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'SAVED', NULL, NULL, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                encrypted_api_key = excluded.encrypted_api_key,
                key_suffix = excluded.key_suffix,
                model = excluded.model,
                status = 'SAVED', verified_at = NULL, last_error = NULL,
                updated_at = excluded.updated_at
            """,
            (credential_id, user_id, encrypted, clean_key[-4:], clean_model, created_at, now),
        )
        _audit(connection, user_id, "OPENAI_CREDENTIAL_SAVED", f"模型配置为 {clean_model}")
    return get_openai_credential_status(database_path, user_id=user_id)


def get_openai_credential_status(database_path: Path, *, user_id: str) -> dict:
    with connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT key_suffix, model, status, verified_at, last_error, created_at, updated_at
            FROM openai_credentials WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
    if row is None:
        return {
            "configured": False,
            "masked_key": None,
            "model": os.environ.get("LUNGSIGHT_OPENAI_MODEL", "gpt-5.4"),
            "status": "NOT_CONFIGURED",
            "verified_at": None,
            "last_error": None,
        }
    return {
        "configured": True,
        "masked_key": f"sk-••••••••{row['key_suffix']}",
        "model": row["model"],
        "status": row["status"],
        "verified_at": row["verified_at"],
        "last_error": row["last_error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def load_openai_credential(database_path: Path, data_dir: Path, *, user_id: str) -> tuple[str, str]:
    with connect(database_path) as connection:
        row = connection.execute(
            "SELECT encrypted_api_key, model FROM openai_credentials WHERE user_id = ?", (user_id,)
        ).fetchone()
    if row is None:
        raise LookupError("尚未配置OpenAI API Key")
    try:
        api_key = _credential_cipher(data_dir).decrypt(row["encrypted_api_key"].encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("OpenAI API Key无法解密，请重新保存") from exc
    return api_key, row["model"]


def mark_openai_verification(
    database_path: Path,
    *,
    user_id: str,
    success: bool,
    error: str | None = None,
) -> dict:
    now = iso_now()
    with connect(database_path) as connection:
        connection.execute(
            """
            UPDATE openai_credentials
            SET status = ?, verified_at = ?, last_error = ?, updated_at = ?
            WHERE user_id = ?
            """,
            ("VERIFIED" if success else "ERROR", now if success else None, (error or "")[:500] or None, now, user_id),
        )
        _audit(
            connection,
            user_id,
            "OPENAI_CONNECTION_VERIFIED" if success else "OPENAI_CONNECTION_FAILED",
            "OpenAI连接验证成功" if success else (error or "OpenAI连接验证失败")[:500],
        )
    return get_openai_credential_status(database_path, user_id=user_id)


def delete_openai_credential(database_path: Path, *, user_id: str) -> None:
    with connect(database_path) as connection:
        connection.execute("DELETE FROM openai_credentials WHERE user_id = ?", (user_id,))
        _audit(connection, user_id, "OPENAI_CREDENTIAL_DELETED", "OpenAI凭据已删除")


def _provider_config(provider: str) -> dict:
    clean_provider = provider.strip().lower()
    if clean_provider not in LLM_PROVIDERS:
        raise ValueError("暂不支持该模型服务商")
    return {"id": clean_provider, **LLM_PROVIDERS[clean_provider]}


def _validate_llm_credential(provider: str, api_key: str, model: str) -> tuple[str, str, dict]:
    config = _provider_config(provider)
    clean_key = api_key.strip()
    clean_model = model.strip()
    if len(clean_key) < 12 or any(character.isspace() for character in clean_key):
        raise ValueError(f"{config['label']} API Key格式不正确")
    if provider == "openai" and (len(clean_key) < 20 or not clean_key.startswith("sk-")):
        raise ValueError("OpenAI API Key格式不正确")
    if not 2 <= len(clean_model) <= 80 or not re.fullmatch(r"[A-Za-z0-9._:-]+", clean_model):
        raise ValueError("模型名称格式不正确")
    return clean_key, clean_model, config


def save_llm_credential(
    database_path: Path,
    data_dir: Path,
    *,
    user_id: str,
    provider: str,
    api_key: str,
    model: str,
    select: bool = True,
) -> dict:
    clean_provider = provider.strip().lower()
    clean_key, clean_model, config = _validate_llm_credential(clean_provider, api_key, model)
    encrypted = _credential_cipher(data_dir).encrypt(clean_key.encode("utf-8")).decode("ascii")
    now = iso_now()
    with connect(database_path) as connection:
        existing = connection.execute(
            "SELECT credential_id, created_at FROM llm_credentials WHERE user_id = ? AND provider = ?",
            (user_id, clean_provider),
        ).fetchone()
        credential_id = existing["credential_id"] if existing else f"LLM-{uuid.uuid4().hex[:12].upper()}"
        created_at = existing["created_at"] if existing else now
        connection.execute(
            """
            INSERT INTO llm_credentials (
                credential_id, user_id, provider, encrypted_api_key, key_suffix, model,
                status, verified_at, last_error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'SAVED', NULL, NULL, ?, ?)
            ON CONFLICT(user_id, provider) DO UPDATE SET
                encrypted_api_key = excluded.encrypted_api_key,
                key_suffix = excluded.key_suffix,
                model = excluded.model,
                status = 'SAVED', verified_at = NULL, last_error = NULL,
                updated_at = excluded.updated_at
            """,
            (credential_id, user_id, clean_provider, encrypted, clean_key[-4:], clean_model, created_at, now),
        )
        if select:
            connection.execute(
                """INSERT INTO user_llm_preferences (user_id, selected_provider, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(user_id) DO UPDATE SET selected_provider = excluded.selected_provider,
                       updated_at = excluded.updated_at""",
                (user_id, clean_provider, now),
            )
        _audit(connection, user_id, "LLM_CREDENTIAL_SAVED", f"{config['label']} · {clean_model}")
    return get_llm_settings(database_path, user_id=user_id)


def get_llm_settings(database_path: Path, *, user_id: str) -> dict:
    with connect(database_path) as connection:
        preference = connection.execute(
            "SELECT selected_provider FROM user_llm_preferences WHERE user_id = ?", (user_id,)
        ).fetchone()
        rows = connection.execute(
            """SELECT provider, key_suffix, model, status, verified_at, last_error, created_at, updated_at
               FROM llm_credentials WHERE user_id = ?""",
            (user_id,),
        ).fetchall()
    configured = {row["provider"]: row for row in rows}
    selected = preference["selected_provider"] if preference else "openai"
    if selected not in LLM_PROVIDERS:
        selected = "openai"
    providers = []
    for provider_id, base in LLM_PROVIDERS.items():
        row = configured.get(provider_id)
        providers.append({
            "id": provider_id,
            "label": base["label"],
            "base_url": base["base_url"],
            "models": base["models"],
            "configured": row is not None,
            "masked_key": f"••••••••{row['key_suffix']}" if row else None,
            "model": row["model"] if row else base["default_model"],
            "status": row["status"] if row else "NOT_CONFIGURED",
            "verified_at": row["verified_at"] if row else None,
            "last_error": row["last_error"] if row else None,
            "updated_at": row["updated_at"] if row else None,
        })
    return {"selected_provider": selected, "providers": providers}


def select_llm_provider(database_path: Path, *, user_id: str, provider: str, model: str | None = None) -> dict:
    clean_provider = provider.strip().lower()
    config = _provider_config(clean_provider)
    now = iso_now()
    with connect(database_path) as connection:
        row = connection.execute(
            "SELECT model FROM llm_credentials WHERE user_id = ? AND provider = ?",
            (user_id, clean_provider),
        ).fetchone()
        if row is None:
            raise LookupError(f"请先保存{config['label']}的API Key")
        if model is not None:
            clean_model = model.strip()
            if not 2 <= len(clean_model) <= 80 or not re.fullmatch(r"[A-Za-z0-9._:-]+", clean_model):
                raise ValueError("模型名称格式不正确")
            connection.execute(
                "UPDATE llm_credentials SET model = ?, updated_at = ? WHERE user_id = ? AND provider = ?",
                (clean_model, now, user_id, clean_provider),
            )
        connection.execute(
            """INSERT INTO user_llm_preferences (user_id, selected_provider, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET selected_provider = excluded.selected_provider,
                   updated_at = excluded.updated_at""",
            (user_id, clean_provider, now),
        )
        _audit(connection, user_id, "LLM_PROVIDER_SELECTED", f"启用 {config['label']}")
    return get_llm_settings(database_path, user_id=user_id)


def load_llm_credential(
    database_path: Path, data_dir: Path, *, user_id: str, provider: str | None = None
) -> tuple[str, str, str]:
    with connect(database_path) as connection:
        if provider is None:
            preference = connection.execute(
                "SELECT selected_provider FROM user_llm_preferences WHERE user_id = ?", (user_id,)
            ).fetchone()
            clean_provider = preference["selected_provider"] if preference else "openai"
        else:
            clean_provider = provider.strip().lower()
        _provider_config(clean_provider)
        row = connection.execute(
            """SELECT encrypted_api_key, model FROM llm_credentials
               WHERE user_id = ? AND provider = ?""",
            (user_id, clean_provider),
        ).fetchone()
    if row is None:
        raise LookupError(f"尚未配置{LLM_PROVIDERS[clean_provider]['label']} API Key")
    try:
        api_key = _credential_cipher(data_dir).decrypt(row["encrypted_api_key"].encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("模型API Key无法解密，请重新保存") from exc
    return clean_provider, api_key, row["model"]


def mark_llm_verification(
    database_path: Path, *, user_id: str, provider: str, success: bool, error: str | None = None
) -> dict:
    clean_provider = provider.strip().lower()
    config = _provider_config(clean_provider)
    now = iso_now()
    with connect(database_path) as connection:
        connection.execute(
            """UPDATE llm_credentials SET status = ?, verified_at = ?, last_error = ?, updated_at = ?
               WHERE user_id = ? AND provider = ?""",
            ("VERIFIED" if success else "ERROR", now if success else None,
             (error or "")[:500] or None, now, user_id, clean_provider),
        )
        _audit(connection, user_id,
               "LLM_CONNECTION_VERIFIED" if success else "LLM_CONNECTION_FAILED",
               f"{config['label']}：{'连接成功' if success else (error or '连接失败')[:400]}")
    return get_llm_settings(database_path, user_id=user_id)


def delete_llm_credential(database_path: Path, *, user_id: str, provider: str) -> dict:
    clean_provider = provider.strip().lower()
    config = _provider_config(clean_provider)
    with connect(database_path) as connection:
        connection.execute(
            "DELETE FROM llm_credentials WHERE user_id = ? AND provider = ?", (user_id, clean_provider)
        )
        preference = connection.execute(
            "SELECT selected_provider FROM user_llm_preferences WHERE user_id = ?", (user_id,)
        ).fetchone()
        if preference and preference["selected_provider"] == clean_provider:
            fallback = connection.execute(
                "SELECT provider FROM llm_credentials WHERE user_id = ? ORDER BY updated_at DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            connection.execute(
                "UPDATE user_llm_preferences SET selected_provider = ?, updated_at = ? WHERE user_id = ?",
                (fallback["provider"] if fallback else "openai", iso_now(), user_id),
            )
        _audit(connection, user_id, "LLM_CREDENTIAL_DELETED", f"删除 {config['label']} 凭据")
    return get_llm_settings(database_path, user_id=user_id)
