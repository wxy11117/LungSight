"""Conservative local DICOM-to-PNG preparation for the LungSight research prototype.

Only anonymized derived pixels and non-identifying acquisition summaries leave this
module. Original DICOM payloads and identifier values are never returned.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

import numpy as np
from PIL import Image
from pydicom import dcmread
from pydicom.dataset import Dataset
from pydicom.errors import InvalidDicomError
from pydicom.pixels import apply_modality_lut


DIRECT_IDENTIFIER_FIELDS = (
    "PatientName",
    "PatientID",
    "PatientBirthDate",
    "PatientAddress",
    "PatientTelephoneNumbers",
    "OtherPatientIDs",
    "OtherPatientNames",
    "AccessionNumber",
    "InstitutionName",
    "InstitutionAddress",
    "ReferringPhysicianName",
    "PerformingPhysicianName",
    "OperatorsName",
    "StudyID",
)


class DicomImportError(ValueError):
    pass


@dataclass
class ParsedDicomSlice:
    dataset: Dataset
    source_index: int
    safe_name: str
    sort_position: float
    instance_number: int
    series_fingerprint: str
    identifier_fields: list[str]
    burned_in_annotation: str


LUNG_AIR_MIN_HU = -1050.0
LUNG_AIR_MAX_HU = -300.0
LUNG_REGION_RELATIVE_THRESHOLD = 0.55
LUNG_REGION_ABSOLUTE_THRESHOLD = 0.015


def _number(value, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _safe_int(value, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def read_dicom_slice(payload: bytes, source_index: int) -> ParsedDicomSlice:
    if not payload:
        raise DicomImportError("文件为空")
    try:
        dataset = dcmread(io.BytesIO(payload), force=False)
    except (InvalidDicomError, OSError, ValueError) as exc:
        raise DicomImportError("不是可读取的DICOM文件") from exc
    if str(dataset.get("Modality", "")).upper() != "CT":
        raise DicomImportError("影像模态不是CT")
    if "PixelData" not in dataset:
        raise DicomImportError("DICOM缺少像素数据")
    frames = _safe_int(dataset.get("NumberOfFrames", 1), 1)
    if frames != 1:
        raise DicomImportError("当前版本暂不支持多帧DICOM对象")
    samples_per_pixel = _safe_int(dataset.get("SamplesPerPixel", 1), 1)
    if samples_per_pixel != 1:
        raise DicomImportError("当前版本仅支持单通道CT像素")

    burned_in = str(dataset.get("BurnedInAnnotation", "NOT_DECLARED")).upper()
    if burned_in == "YES":
        raise DicomImportError("DICOM声明存在烧录文字，出于隐私安全已拦截")
    series_uid = str(dataset.get("SeriesInstanceUID", "")).strip()
    if not series_uid:
        raise DicomImportError("DICOM缺少SeriesInstanceUID，无法确认序列归属")
    identifier_fields = [
        keyword for keyword in DIRECT_IDENTIFIER_FIELDS
        if str(dataset.get(keyword, "")).strip()
    ]
    image_position = dataset.get("ImagePositionPatient")
    if image_position is not None and len(image_position) >= 3:
        position = _number(image_position[2], float(source_index))
    elif dataset.get("SliceLocation") is not None:
        position = _number(dataset.get("SliceLocation"), float(source_index))
    else:
        position = _number(dataset.get("InstanceNumber"), float(source_index))
    instance_number = _safe_int(dataset.get("InstanceNumber"), source_index + 1)
    return ParsedDicomSlice(
        dataset=dataset,
        source_index=source_index,
        safe_name=f"dicom-{source_index + 1:04d}.png",
        sort_position=position,
        instance_number=instance_number,
        series_fingerprint=_fingerprint(series_uid),
        identifier_fields=identifier_fields,
        burned_in_annotation=burned_in,
    )


def dicom_hu_values(item: ParsedDicomSlice) -> np.ndarray:
    dataset = item.dataset
    try:
        pixels = dataset.pixel_array
    except Exception as exc:
        transfer_syntax = str(getattr(getattr(dataset, "file_meta", None), "TransferSyntaxUID", "未知"))
        raise DicomImportError(f"像素解码失败，可能是不支持的压缩传输语法（{transfer_syntax}）") from exc
    if pixels.ndim != 2:
        raise DicomImportError("当前版本仅支持单层二维CT像素矩阵")
    try:
        hu_values = np.asarray(apply_modality_lut(pixels, dataset), dtype=np.float32)
    except Exception as exc:
        raise DicomImportError("CT模态灰度转换失败") from exc
    if not np.isfinite(hu_values).any():
        raise DicomImportError("像素数据没有有效数值")
    return hu_values


def estimate_lung_coverage(item: ParsedDicomSlice) -> dict:
    """Estimate bilateral low-density lung coverage without claiming segmentation."""
    hu_values = dicom_hu_values(item)
    height, width = hu_values.shape
    finite = np.isfinite(hu_values)
    tissue = finite & (hu_values > -500.0)
    row_has_tissue = tissue.any(axis=1)
    first_tissue = np.argmax(tissue, axis=1)
    last_tissue = width - 1 - np.argmax(tissue[:, ::-1], axis=1)
    body_rows = row_has_tissue & ((last_tissue - first_tissue + 1) >= max(1, int(width * 0.25)))
    columns = np.arange(width)[None, :]
    body_envelope = body_rows[:, None] & (columns >= first_tissue[:, None]) & (columns <= last_tissue[:, None])
    border = max(1, int(height * 0.04))
    body_envelope[:border, :] = False
    body_envelope[-border:, :] = False
    lung_like = body_envelope & finite & (hu_values >= LUNG_AIR_MIN_HU) & (hu_values <= LUNG_AIR_MAX_HU)
    left = float(lung_like[:, : width // 2].sum()) / float(height * width)
    right = float(lung_like[:, width // 2 :].sum()) / float(height * width)
    total = left + right
    balance = min(left, right) / max(left, right, 1e-8)
    score = total * (0.65 + 0.35 * balance)
    return {
        "score": float(score),
        "low_density_area_ratio": float(total),
        "bilateral_balance": float(balance),
    }


def select_lung_region(items: list[ParsedDicomSlice]) -> tuple[list[ParsedDicomSlice], dict, list[str]]:
    """Keep the continuous span with meaningful bilateral lung-like coverage."""
    warnings: list[str] = []
    measurements: list[dict] = []
    for item in items:
        try:
            measurements.append(estimate_lung_coverage(item))
        except DicomImportError:
            measurements.append({"score": 0.0, "low_density_area_ratio": 0.0, "bilateral_balance": 0.0})
    scores = [float(item["score"]) for item in measurements]
    maximum_score = max(scores, default=0.0)
    threshold = max(LUNG_REGION_ABSOLUTE_THRESHOLD, maximum_score * LUNG_REGION_RELATIVE_THRESHOLD)
    qualifying = [index for index, score in enumerate(scores) if score >= threshold]
    if len(qualifying) < 3:
        warnings.append("肺野覆盖启发式无法稳定定位有效区间，已保守使用完整可读序列")
        selected = items
        start_index, end_index = 0, max(0, len(items) - 1)
        status = "FALLBACK_ALL"
    else:
        start_index, end_index = qualifying[0], qualifying[-1]
        selected = items[start_index : end_index + 1]
        status = "APPLIED"
    return selected, {
        "status": status,
        "method": "adaptive-bilateral-low-density-envelope-v1",
        "scope": "肺野覆盖启发式，仅用于选择分析层面，不是肺分割或病灶定位",
        "input_slice_count": len(items),
        "eligible_slice_count": len(selected),
        "excluded_edge_slice_count": len(items) - len(selected),
        "relative_threshold": LUNG_REGION_RELATIVE_THRESHOLD,
        "effective_score_threshold": round(threshold, 8),
        "maximum_score": round(maximum_score, 8),
    }, warnings


def dicom_to_lung_window_png(item: ParsedDicomSlice) -> bytes:
    dataset = item.dataset
    hu_values = dicom_hu_values(item)

    # Fixed lung window for deterministic preprocessing across scanners.
    lower, upper = -1350.0, 150.0  # center -600 HU, width 1500 HU
    normalized = np.clip((hu_values - lower) / (upper - lower), 0.0, 1.0)
    image_array = np.rint(normalized * 255.0).astype(np.uint8)
    if str(dataset.get("PhotometricInterpretation", "MONOCHROME2")).upper() == "MONOCHROME1":
        image_array = 255 - image_array
    image = Image.fromarray(image_array, mode="L").convert("RGB")
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _sample_evenly(items: list[ParsedDicomSlice], maximum: int) -> list[ParsedDicomSlice]:
    if len(items) <= maximum:
        return items
    indices = np.linspace(0, len(items) - 1, maximum, dtype=int)
    return [items[int(index)] for index in indices]


def prepare_dicom_series(
    payloads: list[bytes],
    *,
    maximum_analysis_slices: int = 32,
) -> tuple[list[dict], list[dict], dict]:
    parsed: list[ParsedDicomSlice] = []
    failures: list[dict] = []
    for index, payload in enumerate(payloads):
        try:
            parsed.append(read_dicom_slice(payload, index))
        except DicomImportError as exc:
            failures.append({"file_name": f"DICOM文件 {index + 1:04d}", "status_code": 422, "detail": str(exc)})
    if not parsed:
        raise DicomImportError("没有可读取的单帧CT DICOM切片")
    fingerprints = {item.series_fingerprint for item in parsed}
    if len(fingerprints) != 1:
        raise DicomImportError("检测到多个SeriesInstanceUID，请一次只上传一个CT序列")

    parsed.sort(key=lambda item: (item.sort_position, item.instance_number, item.source_index))
    lung_region, lung_selection, selection_warnings = select_lung_region(parsed)
    selected = _sample_evenly(lung_region, maximum_analysis_slices)
    prepared: list[dict] = []
    for output_index, item in enumerate(selected):
        try:
            prepared.append({
                "file_name": f"dicom-slice-{output_index + 1:03d}.png",
                "payload": dicom_to_lung_window_png(item),
                "source_index": item.source_index,
                "sort_position": item.sort_position,
                "instance_number": item.instance_number,
                "lung_coverage_score": round(estimate_lung_coverage(item)["score"], 8),
            })
        except DicomImportError as exc:
            failures.append({"file_name": f"DICOM文件 {item.source_index + 1:04d}", "status_code": 422, "detail": str(exc)})
    if not prepared:
        raise DicomImportError("DICOM序列没有切片能够完成像素解码和肺窗转换")

    identifier_fields = sorted({field for item in parsed for field in item.identifier_fields})
    burned_values = {item.burned_in_annotation for item in parsed}
    thickness_values = sorted({
        round(_number(item.dataset.get("SliceThickness"), 0.0), 4)
        for item in parsed if item.dataset.get("SliceThickness") is not None
    })
    pixel_spacing_values = sorted({
        tuple(round(_number(value, 0.0), 4) for value in item.dataset.get("PixelSpacing", [])[:2])
        for item in parsed if item.dataset.get("PixelSpacing") is not None
    })
    summary = {
        "modality": "CT",
        "input_file_count": len(payloads),
        "readable_slice_count": len(parsed),
        "analyzed_slice_count": len(prepared),
        "subsampled": len(selected) < len(parsed),
        "maximum_analysis_slices": maximum_analysis_slices,
        "series_fingerprint": next(iter(fingerprints)),
        "sort_method": "ImagePositionPatient/SliceLocation/InstanceNumber",
        "window": {"name": "lung", "center_hu": -600, "width_hu": 1500},
        "slice_thickness_mm": thickness_values,
        "pixel_spacing_mm": [list(values) for values in pixel_spacing_values],
        "lung_selection": lung_selection,
        "selection_role": "coverage quality control and deterministic subsampling only",
        "lesion_localized": False,
        "tumor_roi_available": False,
        "training_pipeline_equivalence_verified": False,
        "case_level_subtype_prediction_eligible": False,
        "warnings": selection_warnings,
        "privacy": {
            "direct_identifier_fields_detected": identifier_fields,
            "identifier_values_persisted": False,
            "original_dicom_persisted": False,
            "burned_in_annotation": sorted(burned_values),
            "pixel_privacy_review_required": True,
        },
    }
    return prepared, failures, summary
