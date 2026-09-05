"""Build a de-identified multi-vendor DICOM engineering compatibility matrix.

This command validates decoding and preprocessing only. It does not run the
classifier, create application records, verify labels, or approve training.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from dicom_series import prepare_dicom_series


FORBIDDEN_OUTPUT_KEYS = {
    "patient_research_id", "study_instance_uid", "series_instance_uid", "patient_id",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_case(case: dict, base_dir: Path, safe_index: int) -> dict:
    archive = base_dir / f"NLST-{case['patient_research_id']}" / str(case["download"]["archive"])
    archive = archive.resolve(strict=True)
    actual_sha = sha256_file(archive)
    expected_sha = str(case["download"]["archive_sha256"])
    if actual_sha != expected_sha:
        raise RuntimeError("来源压缩包SHA-256与冻结清单不一致")

    started = time.perf_counter()
    with zipfile.ZipFile(archive) as bundle:
        corrupt_member = bundle.testzip()
        if corrupt_member is not None:
            raise RuntimeError("来源压缩包CRC检查失败")
        members = [item for item in bundle.infolist() if not item.is_dir() and item.filename.lower().endswith(".dcm")]
        if any(item.flag_bits & 0x1 for item in members):
            raise RuntimeError("来源压缩包包含加密DICOM对象")
        if len(members) != int(case["download"]["dicom_object_count"]):
            raise RuntimeError("DICOM对象数与冻结清单不一致")
        payloads = [bundle.read(item) for item in members]

    prepared, failures, summary = prepare_dicom_series(payloads, maximum_analysis_slices=32)
    privacy = summary["privacy"]
    warnings = list(summary.get("warnings", []))
    if failures:
        warnings.append(f"{len(failures)}个对象未完成解析或像素转换")
    if privacy["direct_identifier_fields_detected"]:
        warnings.append("检测到身份字段名称，字段值未输出")
    if privacy["burned_in_annotation"] != ["NO"]:
        warnings.append("烧录文字状态未全部明确为NO，仍需人工像素隐私复核")
    status = "PASS" if not warnings else "PASS_WITH_WARNINGS"
    return {
        "case_code": f"DEVICE-{safe_index:02d}",
        "manufacturer": str(case.get("manufacturer", "UNKNOWN")),
        "manufacturer_model": str(case.get("manufacturer_model", "UNKNOWN")),
        "license_name": str(case.get("license_name", "未记录")),
        "archive_sha256": actual_sha,
        "archive_bytes": archive.stat().st_size,
        "dicom_object_count": len(payloads),
        "readable_slice_count": summary["readable_slice_count"],
        "prepared_slice_count": len(prepared),
        "failed_object_count": len(failures),
        "slice_thickness_mm": summary["slice_thickness_mm"],
        "pixel_spacing_mm": summary["pixel_spacing_mm"],
        "lung_selection": summary["lung_selection"],
        "window": summary["window"],
        "privacy": {
            "direct_identifier_fields_detected": privacy["direct_identifier_fields_detected"],
            "identifier_values_output": False,
            "original_dicom_persisted": False,
            "burned_in_annotation": privacy["burned_in_annotation"],
            "pixel_privacy_review_required": True,
        },
        "engineering_status": status,
        "warnings": warnings,
        "normal_label_verified": False,
        "training_approved": False,
        "classifier_executed": False,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def render_markdown(matrix: dict) -> str:
    rows = []
    for item in matrix["cases"]:
        selection = item["lung_selection"]
        thickness = ", ".join(str(value) for value in item["slice_thickness_mm"]) or "未记录"
        spacing = "; ".join("×".join(str(value) for value in pair) for pair in item["pixel_spacing_mm"]) or "未记录"
        rows.append(
            f"| {item['case_code']} | {item['manufacturer']} | {item['manufacturer_model']} | "
            f"{item['dicom_object_count']} | {item['readable_slice_count']} | "
            f"{selection['eligible_slice_count']} / {selection['excluded_edge_slice_count']} | "
            f"{thickness} | {spacing} | {item['engineering_status']} |"
        )
    warning_sections = []
    for item in matrix["cases"]:
        bullets = "\n".join(f"  - {warning}" for warning in item["warnings"]) or "  - 无"
        warning_sections.append(f"- {item['case_code']}\n{bullets}")
    return f"""# LungSight 多设备 DICOM 工程兼容性矩阵

生成时间：{matrix['created_at']}

## 结论

四种设备来源的公开CT序列均完成压缩包校验、DICOM像素解码、物理层排序、固定肺窗转换和肺野有效层筛选。

本矩阵只证明当前工程入口能够处理这些样例，不证明任意同厂设备均兼容，不评价分类准确率，不验证正常标签，也不批准训练或临床使用。

| 编号 | 厂商 | 型号 | 对象 | 可读 | 肺野有效/排除 | 层厚mm | 像素间距mm | 工程状态 |
|---|---|---:|---:|---:|---:|---:|---:|---|
{chr(10).join(rows)}

## 安全边界

- 输入清单SHA-256：`{matrix['source_manifest_sha256']}`
- DICOM解析代码SHA-256：`{matrix['parser_sha256']}`
- 原始DICOM持久化：否
- 派生PNG持久化：否
- 身份字段值输出：否
- 分类模型执行：否
- 正常标签核验：0/{len(matrix['cases'])}
- 训练批准：0/{len(matrix['cases'])}
- 像素隐私人工复核：仍需要

## 工程提示

{chr(10).join(warning_sections)}

## 下一步

1. 增加压缩传输语法、多帧CT、倾斜层面和缺失几何字段的负向兼容测试。
2. 对更多不同层厚、重建核和设备版本执行同一矩阵。
3. 工程兼容通过不能替代授权人员的像素隐私、图像质量和标签审核。
"""


def assert_safe_matrix(matrix: dict) -> None:
    def visit(value) -> None:
        if isinstance(value, dict):
            forbidden = FORBIDDEN_OUTPUT_KEYS.intersection(str(key).lower() for key in value)
            if forbidden:
                raise RuntimeError(f"兼容性矩阵包含禁止输出的标识字段：{sorted(forbidden)}")
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(matrix)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()

    manifest_path = args.manifest.resolve(strict=True)
    source = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = source.get("cases", [])
    if len(cases) < 4:
        raise RuntimeError("兼容性矩阵至少需要四个设备样例")
    results = [validate_case(case, manifest_path.parent, index + 1) for index, case in enumerate(cases)]
    matrix = {
        "schema_version": "lungsight-dicom-compatibility-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "engineering_compatibility_only",
        "source_manifest_sha256": sha256_file(manifest_path),
        "parser_sha256": sha256_file(Path(__file__).with_name("dicom_series.py")),
        "case_count": len(results),
        "status_counts": {
            status: sum(item["engineering_status"] == status for item in results)
            for status in ("PASS", "PASS_WITH_WARNINGS", "BLOCKED")
        },
        "cases": results,
        "normal_label_verified_count": 0,
        "training_approved_count": 0,
        "clinical_use_allowed": False,
    }
    assert_safe_matrix(matrix)
    output_json = args.output_json.resolve()
    output_md = args.output_md.resolve()
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(matrix, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_markdown(matrix), encoding="utf-8")
    print(json.dumps({
        "status": "PASS", "case_count": len(results), "status_counts": matrix["status_counts"],
        "output_json": str(output_json), "output_md": str(output_md),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
