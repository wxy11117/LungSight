"""Synthetic registration data for isolated tests; never use a real account."""
def registration_fields(password="test-pass-2026"):
    return {
        "confirm_password": password,
        "doctor_profile": {
            "real_name": "测试医生", "province": "北京市", "city": "北京市",
            "hospital_id": None, "hospital_name": "测试医院（虚构）",
            "department": "放射科", "professional_title": "主治医师",
        },
    }
