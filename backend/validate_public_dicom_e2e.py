"""Run an isolated, real-model DICOM endpoint validation against a public CT archive.

The source archive is read in memory. All API-created records live in a temporary
directory and are deleted when the run ends. The emitted report contains no DICOM
identifier values and is not a label, accuracy result, or training approval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def expected_archive_sha(manifest_path: Path, archive_path: Path) -> tuple[str, str, str]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    matches = [item for item in manifest.get("downloads", []) if item.get("file") == archive_path.name]
    if len(matches) != 1:
        raise RuntimeError("来源清单中无法唯一定位CT压缩包")
    return str(matches[0]["sha256"]), str(manifest.get("collection", "公开CT集合")), str(manifest.get("license", "未记录"))


def markdown_report(*, collection: str, license_name: str, source_sha: str, elapsed: float, result: dict,
                    stored_png_count: int, html_report_sha: str) -> str:
    dicom = result["dicom"]
    privacy = dicom["privacy"]
    lung_selection = dicom.get("lung_selection", {})
    warnings = result["reliability"].get("warnings", [])
    quality_gate = result.get("quality_gate", {})
    gate_reasons = "；".join(quality_gate.get("reasons", [])) or "全部工程阈值通过"
    fields = "、".join(privacy.get("direct_identifier_fields_detected", [])) or "无"
    warning_lines = "\n".join(f"- {item}" for item in warnings) or "- 无"
    return f"""# LungSight 公开 DICOM 端到端工程验证

验证时间：{datetime.now(timezone.utc).isoformat()}

## 结论

真实公开CT序列已通过隔离环境中的正式DICOM接口、真实五折模型、Grad-CAM、病例级聚合、数据库留痕和HTML报告生成闭环。

本记录只证明工程管线可运行，不证明分类正确，不是训练标签、临床审核或临床使用授权。

## 输入与隔离

- 来源集合：{collection}
- 来源许可：{license_name}
- 来源压缩包SHA-256：`{source_sha}`
- 原始DICOM持久化：否
- 身份字段值持久化：否
- 正式账号与正式数据库改动：否
- 检测到的身份字段名称：{fields}
- 像素隐私人工复核：仍需要

## 管线结果

- 输入DICOM对象：{dicom['input_file_count']}
- 可读取单帧CT切片：{dicom['readable_slice_count']}
- 肺野覆盖有效区间：{lung_selection.get('eligible_slice_count', dicom['readable_slice_count'])}
- 排除边缘低覆盖切片：{lung_selection.get('excluded_edge_slice_count', 0)}
- 肺野筛选状态：{lung_selection.get('status', '未记录')}
- 进入模型的等距切片：{dicom['analyzed_slice_count']}
- 是否触发等距抽样：{'是' if dicom['subsampled'] else '否'}
- 肺窗：中心 {dicom['window']['center_hu']} HU，宽度 {dicom['window']['width_hu']} HU
- 隔离目录临时PNG（肺窗切片与Grad-CAM合计）：{stored_png_count}
- 病例聚合状态：{result['prediction']['decision']}
- 质量门控状态：{quality_gate.get('status', '未记录')}
- 质量门控依据：{gate_reasons}
- 模型内部最高分类：{result['prediction']['top_class_cn']}
- 模型内部最高概率：{result['prediction']['top_probability'] * 100:.2f}%
- 切片一致率：{result['prediction']['slice_agreement'] * 100:.2f}%
- 可靠性状态：{result['reliability']['level']}
- HTML报告SHA-256：`{html_report_sha}`
- 总耗时：{elapsed:.2f} 秒

## 自动警告

{warning_lines}

## 后续关口

1. 使用更多不同设备、重建核和层厚的已授权序列做工程兼容性验证。
2. 由授权人员完成像素隐私检查。
3. 只有具有可追溯病理标签并通过患者级划分的数据才能进入正式五折训练。
4. 独立验证完成前不得替换当前模型或宣称临床准确率。
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    archive = args.archive.resolve(strict=True)
    manifest = args.manifest.resolve(strict=True)
    output = args.output.resolve()
    expected_sha, collection, license_name = expected_archive_sha(manifest, archive)
    actual_sha = sha256_file(archive)
    if actual_sha != expected_sha:
        raise RuntimeError("CT压缩包SHA-256与来源清单不一致")

    with zipfile.ZipFile(archive) as bundle:
        members = [item for item in bundle.infolist() if not item.is_dir() and item.filename.lower().endswith(".dcm")]
        if not members:
            raise RuntimeError("CT压缩包中没有DICOM对象")
        if any(item.flag_bits & 0x1 for item in members):
            raise RuntimeError("CT压缩包包含加密成员")
        dicom_payloads = [bundle.read(item) for item in members]

    with tempfile.TemporaryDirectory(prefix="lungsight-dicom-e2e-") as temporary:
        temporary_path = Path(temporary)
        os.environ["LUNGSIGHT_DATA_DIR"] = str(temporary_path / "data")
        import app as application
        from fastapi.testclient import TestClient

        started = time.perf_counter()
        with TestClient(application.app) as client:
            password = "isolated-dicom-e2e-2026"
            registration = client.post("/api/auth/register", json={
                "email": "dicom-e2e@example.invalid",
                "phone": None,
                "display_name": "隔离DICOM工程验证",
                "password": password,
                "confirm_password": password,
                "doctor_profile": {
                    "real_name": "工程验证用户", "province": "北京市", "city": "北京市",
                    "hospital_id": None, "hospital_name": "隔离测试机构（虚构）",
                    "department": "工程测试", "professional_title": "测试人员",
                },
                "accepted_terms": True,
                "accepted_privacy": True,
            })
            registration.raise_for_status()
            response = client.post(
                "/api/analyze/dicom-series",
                data={"case_name": "公开CT工程样例", "privacy_acknowledged": "true"},
                files=[
                    ("files", (f"dicom-{index + 1:04d}.dcm", payload, "application/dicom"))
                    for index, payload in enumerate(dicom_payloads)
                ],
            )
            response.raise_for_status()
            result = response.json()
            report_response = client.get(f"/api/series/{result['series_id']}/report")
            report_response.raise_for_status()
            if "DICOM 导入摘要" not in report_response.text:
                raise RuntimeError("病例报告缺少DICOM导入摘要")
            html_report_sha = hashlib.sha256(report_response.content).hexdigest()
            stored_files = [path for path in (temporary_path / "data").rglob("*") if path.is_file()]
            if any(path.suffix.lower() == ".dcm" for path in stored_files):
                raise RuntimeError("隔离数据目录中发现不应持久化的DICOM对象")
            stored_png_count = len([path for path in stored_files if path.suffix.lower() == ".png"])
        elapsed = time.perf_counter() - started

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown_report(
        collection=collection, license_name=license_name, source_sha=actual_sha,
        elapsed=elapsed, result=result, stored_png_count=stored_png_count,
        html_report_sha=html_report_sha,
    ), encoding="utf-8")
    print(json.dumps({
        "status": "PASS", "report": str(output), "input_count": result["dicom"]["input_file_count"],
        "analyzed_count": result["dicom"]["analyzed_slice_count"],
        "decision": result["prediction"]["decision"], "elapsed_seconds": round(elapsed, 2),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
