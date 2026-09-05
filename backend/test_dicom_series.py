from __future__ import annotations

import io
import json
import unittest

import numpy as np
from PIL import Image
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.filewriter import dcmwrite
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid

from dicom_series import DicomImportError, prepare_dicom_series, read_dicom_slice


def synthetic_ct(
    *,
    series_uid: str,
    position: float,
    instance: int,
    modality: str = "CT",
    burned_in: str = "NO",
    patient_name: str = "Sensitive^Person",
    lung_present: bool | None = None,
) -> bytes:
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = CTImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.ImplementationClassUID = generate_uid()
    dataset = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
    dataset.SOPClassUID = CTImageStorage
    dataset.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    dataset.Modality = modality
    dataset.SeriesInstanceUID = series_uid
    dataset.StudyInstanceUID = generate_uid()
    dataset.PatientName = patient_name
    dataset.PatientID = "PRIVATE-123"
    dataset.BurnedInAnnotation = burned_in
    dataset.ImagePositionPatient = [0.0, 0.0, position]
    dataset.InstanceNumber = instance
    dataset.SliceThickness = 1.25
    dataset.PixelSpacing = [0.7, 0.7]
    dataset.Rows = 64
    dataset.Columns = 64
    dataset.SamplesPerPixel = 1
    dataset.PhotometricInterpretation = "MONOCHROME2"
    dataset.BitsAllocated = 16
    dataset.BitsStored = 16
    dataset.HighBit = 15
    dataset.PixelRepresentation = 1
    dataset.RescaleSlope = 1
    dataset.RescaleIntercept = -1024
    if lung_present is None:
        pixels = np.arange(64 * 64, dtype=np.int16).reshape(64, 64)
    else:
        yy, xx = np.ogrid[:64, :64]
        hu = np.full((64, 64), -1024, dtype=np.int16)
        body = ((xx - 32) / 27) ** 2 + ((yy - 33) / 29) ** 2 <= 1
        hu[body] = 30
        if lung_present:
            left_lung = ((xx - 22) / 9) ** 2 + ((yy - 31) / 17) ** 2 <= 1
            right_lung = ((xx - 42) / 9) ** 2 + ((yy - 31) / 17) ** 2 <= 1
            hu[body & (left_lung | right_lung)] = -800
        pixels = (hu + 1024).astype(np.int16)
    dataset.PixelData = pixels.tobytes()
    output = io.BytesIO()
    dcmwrite(output, dataset, enforce_file_format=True)
    return output.getvalue()


class DicomSeriesTests(unittest.TestCase):
    def test_series_is_sorted_windowed_and_identifiers_are_not_returned(self) -> None:
        series_uid = generate_uid()
        payloads = [
            synthetic_ct(series_uid=series_uid, position=5.0, instance=3),
            synthetic_ct(series_uid=series_uid, position=-5.0, instance=1),
            synthetic_ct(series_uid=series_uid, position=0.0, instance=2),
        ]
        prepared, failures, summary = prepare_dicom_series(payloads)
        self.assertEqual(failures, [])
        self.assertEqual([item["sort_position"] for item in prepared], [-5.0, 0.0, 5.0])
        self.assertEqual(summary["analyzed_slice_count"], 3)
        self.assertEqual(summary["window"], {"name": "lung", "center_hu": -600, "width_hu": 1500})
        self.assertIn("PatientName", summary["privacy"]["direct_identifier_fields_detected"])
        self.assertIn("PatientID", summary["privacy"]["direct_identifier_fields_detected"])
        self.assertFalse(summary["privacy"]["identifier_values_persisted"])
        self.assertFalse(summary["privacy"]["original_dicom_persisted"])
        self.assertNotIn("Sensitive", json.dumps(summary, ensure_ascii=False))
        with Image.open(io.BytesIO(prepared[0]["payload"])) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.mode, "RGB")
            self.assertEqual(image.size, (64, 64))

    def test_series_is_evenly_subsampled(self) -> None:
        series_uid = generate_uid()
        payloads = [synthetic_ct(series_uid=series_uid, position=float(index), instance=index + 1) for index in range(9)]
        prepared, _, summary = prepare_dicom_series(payloads, maximum_analysis_slices=3)
        self.assertEqual([item["sort_position"] for item in prepared], [0.0, 4.0, 8.0])
        self.assertTrue(summary["subsampled"])

    def test_multiple_series_are_rejected(self) -> None:
        payloads = [
            synthetic_ct(series_uid=generate_uid(), position=0.0, instance=1),
            synthetic_ct(series_uid=generate_uid(), position=1.0, instance=2),
        ]
        with self.assertRaisesRegex(DicomImportError, "多个SeriesInstanceUID"):
            prepare_dicom_series(payloads)

    def test_low_lung_coverage_edges_are_removed_before_sampling(self) -> None:
        series_uid = generate_uid()
        payloads = [
            synthetic_ct(
                series_uid=series_uid,
                position=float(index),
                instance=index + 1,
                lung_present=2 <= index <= 7,
            )
            for index in range(10)
        ]
        prepared, _, summary = prepare_dicom_series(payloads, maximum_analysis_slices=4)
        selection = summary["lung_selection"]
        self.assertEqual(selection["status"], "APPLIED")
        self.assertEqual(selection["eligible_slice_count"], 6)
        self.assertEqual(selection["excluded_edge_slice_count"], 4)
        self.assertEqual(len(prepared), 4)
        self.assertTrue(all(2.0 <= item["sort_position"] <= 7.0 for item in prepared))
        self.assertIn("不是肺分割", selection["scope"])

    def test_non_ct_and_burned_in_annotations_are_rejected(self) -> None:
        uid = generate_uid()
        with self.assertRaisesRegex(DicomImportError, "没有可读取"):
            prepare_dicom_series([synthetic_ct(series_uid=uid, position=0, instance=1, modality="MR")])
        with self.assertRaisesRegex(DicomImportError, "没有可读取"):
            prepare_dicom_series([synthetic_ct(series_uid=uid, position=0, instance=1, burned_in="YES")])
        with self.assertRaisesRegex(DicomImportError, "烧录文字"):
            read_dicom_slice(synthetic_ct(series_uid=uid, position=0, instance=1, burned_in="YES"), 0)


if __name__ == "__main__":
    unittest.main()
