from __future__ import annotations

import unittest

from validate_dicom_compatibility import assert_safe_matrix, render_markdown


class DicomCompatibilityReportTests(unittest.TestCase):
    def test_safe_matrix_rejects_source_identifiers(self) -> None:
        for key in ("patient_research_id", "study_instance_uid", "series_instance_uid", "patient_id"):
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, "禁止输出"):
                assert_safe_matrix({"cases": [{key: "private-value"}]})

    def test_markdown_keeps_engineering_and_training_boundaries(self) -> None:
        matrix = {
            "created_at": "2026-09-03T00:00:00+00:00",
            "source_manifest_sha256": "source-sha",
            "parser_sha256": "parser-sha",
            "cases": [{
                "case_code": "DEVICE-01", "manufacturer": "Vendor", "manufacturer_model": "Model",
                "dicom_object_count": 10, "readable_slice_count": 10,
                "slice_thickness_mm": [1.0], "pixel_spacing_mm": [[0.7, 0.7]],
                "lung_selection": {"eligible_slice_count": 8, "excluded_edge_slice_count": 2},
                "engineering_status": "PASS_WITH_WARNINGS", "warnings": ["仍需人工复核"],
            }],
        }
        assert_safe_matrix(matrix)
        report = render_markdown(matrix)
        self.assertIn("不评价分类准确率", report)
        self.assertIn("训练批准：0/1", report)
        self.assertIn("像素隐私人工复核：仍需要", report)
        self.assertNotIn("private-value", report)


if __name__ == "__main__":
    unittest.main()
