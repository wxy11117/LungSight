"""Registration field validation; affiliation is self-declared, never authorization."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

CATALOG = json.loads((Path(__file__).resolve().parent.parent / "config" / "registration-catalog.json").read_text(encoding="utf-8"))


def normalize_phone(value: str) -> str:
    clean = re.sub(r"[ \-]", "", value.strip())
    if not clean.startswith("+"):
        clean = "+86" + clean
    if not re.fullmatch(r"(?:\+861[3-9][0-9]{9}|\+852[4-9][0-9]{7}|\+8536[0-9]{7}|\+8869[0-9]{8})", clean):
        raise ValueError("请输入有效手机号，并选择正确的区号")
    return clean


def masked_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    prefix = "+86" if phone.startswith("+861") else phone[:4]
    number = phone[len(prefix):]
    return f"{prefix} {number[:3]}{'*' * (len(number) - 5)}{number[-2:]}"


def clean_text(value: str, label: str, minimum: int, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"请填写{label}")
    clean = value.strip()
    if not minimum <= len(clean) <= maximum:
        raise ValueError(f"{label}需要{minimum}至{maximum}个字符")
    if any(unicodedata.category(c).startswith("C") or c in "\u2028\u2029<>" for c in clean):
        raise ValueError(f"{label}不能包含控制字符或尖括号")
    return clean


def validate_doctor_profile(profile: dict) -> dict:
    fields = {
        "real_name": ("医生姓名", 2, 60), "province": ("省级地区", 2, 20),
        "city": ("城市或地区", 2, 60), "hospital_name": ("医院全称", 2, 120),
        "department": ("科室", 2, 60), "professional_title": ("职称", 2, 40),
    }
    if set(profile) - set(fields) - {"hospital_id"}:
        raise ValueError("医生资料包含不支持的字段")
    clean = {key: clean_text(profile.get(key), *constraints) for key, constraints in fields.items()}
    if clean["province"] not in CATALOG["provinces"]:
        raise ValueError("请选择有效的省级地区")
    hospital_id = profile.get("hospital_id") or None
    if hospital_id:
        hospital = next((item for item in CATALOG["hospitals"] if item["id"] == hospital_id), None)
        if hospital is None or any(clean[key] != hospital[key] for key in ("province", "city")) or clean["hospital_name"] != hospital["name"]:
            raise ValueError("所选医院与地区或名称不一致，请重新选择或手动填写")
    clean["hospital_id"] = hospital_id
    return clean
