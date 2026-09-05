from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import app as application
from auth_test_helpers import registration_fields


def slice_result(
    task_id: str,
    probabilities: dict[str, float],
    *,
    quality: str = "PASS",
    fold_agreement: str = "5/5",
) -> dict:
    top_class = max(probabilities, key=probabilities.get)
    labels = {
        "adenocarcinoma": "腺癌",
        "large_cell_carcinoma": "大细胞癌",
        "normal": "正常肺部",
        "squamous_cell_carcinoma": "鳞状细胞癌",
    }
    return {
        "task_id": task_id,
        "input": {"file_name": f"{task_id}.png"},
        "prediction": {
            "top_class": top_class,
            "top_class_cn": labels[top_class],
            "probabilities": probabilities,
        },
        "reliability": {"fold_agreement": fold_agreement, "warnings": []},
        "quality_control": {"status": quality, "warnings": []},
    }


class SeriesAggregationTests(unittest.TestCase):
    def test_consistent_slices_produce_candidate(self) -> None:
        results = [
            slice_result(
                f"CT-{index}",
                {
                    "adenocarcinoma": 0.72 + index * 0.02,
                    "large_cell_carcinoma": 0.08,
                    "normal": 0.06,
                    "squamous_cell_carcinoma": 0.14 - index * 0.02,
                },
            )
            for index in range(3)
        ]
        series = application.aggregate_series_results(
            results, case_name="病例A", case_aggregation_validated=True
        )
        self.assertEqual(series["prediction"]["decision"], "CANDIDATE")
        self.assertEqual(series["prediction"]["top_class"], "adenocarcinoma")
        self.assertEqual(series["prediction"]["slice_agreement"], 1.0)
        self.assertEqual(series["summary"]["analyzed_count"], 3)
        self.assertEqual(series["reliability"]["warnings"], [])
        self.assertEqual(series["quality_gate"]["status"], "PASS")

    def test_runtime_default_forces_unvalidated_case_abstention(self) -> None:
        probabilities = {
            "adenocarcinoma": 0.82,
            "large_cell_carcinoma": 0.05,
            "normal": 0.03,
            "squamous_cell_carcinoma": 0.10,
        }
        results = [slice_result(f"CT-GATE-{index}", probabilities) for index in range(5)]
        series = application.aggregate_series_results(results, case_name="未验证病例")
        self.assertEqual(series["prediction"]["decision"], "INDETERMINATE")
        self.assertEqual(series["quality_gate"]["status"], "BLOCKED")
        self.assertFalse(series["applicability"]["case_aggregation_validated"])
        self.assertIn("当前模型未在病例级完整序列和肿瘤ROI上完成验证", series["quality_gate"]["reasons"])

    def test_short_conflicting_series_is_indeterminate(self) -> None:
        results = [
            slice_result("CT-A", {
                "adenocarcinoma": 0.55, "large_cell_carcinoma": 0.10,
                "normal": 0.05, "squamous_cell_carcinoma": 0.30,
            }),
            slice_result("CT-B", {
                "adenocarcinoma": 0.20, "large_cell_carcinoma": 0.10,
                "normal": 0.05, "squamous_cell_carcinoma": 0.65,
            }),
        ]
        series = application.aggregate_series_results(results, case_name="病例B")
        self.assertEqual(series["prediction"]["decision"], "INDETERMINATE")
        self.assertIn("有效切片少于3张，病例级结果证据不足", series["reliability"]["warnings"])
        self.assertTrue(any("支持最高类别的切片不足60%" in item for item in series["reliability"]["warnings"]))

    def test_quality_warning_is_downweighted_and_reported(self) -> None:
        results = [
            slice_result("CT-1", {
                "adenocarcinoma": 0.70, "large_cell_carcinoma": 0.10,
                "normal": 0.05, "squamous_cell_carcinoma": 0.15,
            }),
            slice_result("CT-2", {
                "adenocarcinoma": 0.68, "large_cell_carcinoma": 0.10,
                "normal": 0.07, "squamous_cell_carcinoma": 0.15,
            }),
            slice_result("CT-3", {
                "adenocarcinoma": 0.01, "large_cell_carcinoma": 0.00,
                "normal": 0.00, "squamous_cell_carcinoma": 0.99,
            }, quality="WARNING"),
        ]
        series = application.aggregate_series_results(
            results,
            case_name="病例C",
            failures=[{"file_name": "broken.png", "status_code": 400, "detail": "不可读取"}],
        )
        self.assertEqual(series["prediction"]["top_class"], "adenocarcinoma")
        self.assertEqual(series["summary"]["quality_warning_count"], 1)
        self.assertEqual(series["summary"]["failed_count"], 1)
        self.assertTrue(any("降低权重" in item for item in series["reliability"]["warnings"]))

    def test_high_quality_warning_ratio_blocks_case_candidate(self) -> None:
        probabilities = {
            "adenocarcinoma": 0.80,
            "large_cell_carcinoma": 0.05,
            "normal": 0.05,
            "squamous_cell_carcinoma": 0.10,
        }
        results = [
            slice_result("CT-QC-1", probabilities, quality="WARNING"),
            slice_result("CT-QC-2", probabilities, quality="WARNING"),
            slice_result("CT-QC-3", probabilities),
        ]
        series = application.aggregate_series_results(results, case_name="质控阻断病例")
        self.assertEqual(series["prediction"]["decision"], "INDETERMINATE")
        self.assertEqual(series["quality_gate"]["status"], "BLOCKED")
        self.assertAlmostEqual(series["summary"]["quality_warning_ratio"], 2 / 3, places=7)
        self.assertTrue(any("超过40%门槛" in item for item in series["quality_gate"]["reasons"]))


class SeriesSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.original_database_path = application.DATABASE_PATH
        self.original_data_dir = application.DATA_DIR
        application.DATA_DIR = Path(self.temporary.name)
        application.DATABASE_PATH = application.DATA_DIR / "series-test.sqlite3"
        application.initialize_database()
        application.initialize_auth_schema(application.DATABASE_PATH)
        application.initialize_agent_schema(application.DATABASE_PATH)
        application.initialize_knowledge_schema(application.DATABASE_PATH)
        self.client = TestClient(application.app)

    def tearDown(self) -> None:
        self.client.close()
        application.DATABASE_PATH = self.original_database_path
        application.DATA_DIR = self.original_data_dir
        self.temporary.cleanup()

    def test_series_tables_and_owner_index_exist(self) -> None:
        with application.database_connection() as connection:
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_schema WHERE type = 'table'"
                ).fetchall()
            }
            indexes = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_schema WHERE type = 'index'"
                ).fetchall()
            }
        self.assertIn("analysis_series", tables)
        self.assertIn("analysis_series_items", tables)
        self.assertIn("idx_series_owner_created", indexes)

    def test_series_history_requires_login(self) -> None:
        self.assertEqual(self.client.get("/api/series").status_code, 401)

    def test_series_endpoint_aggregates_authenticated_uploads(self) -> None:
        registered = self.client.post(
            "/api/auth/register",
            json={
                **registration_fields("series-pass-2026"),
                "email": "series@example.com",
                "display_name": "序列测试",
                "password": "series-pass-2026",
                "accepted_terms": True,
                "accepted_privacy": True,
            },
        )
        self.assertEqual(registered.status_code, 201)
        probabilities = {
            "adenocarcinoma": 0.75,
            "large_cell_carcinoma": 0.08,
            "normal": 0.05,
            "squamous_cell_carcinoma": 0.12,
        }
        counter = iter(range(3))

        async def fake_analyze(*, file, user):
            del file, user
            return slice_result(f"CT-ENDPOINT-{next(counter)}", probabilities)

        from unittest.mock import patch
        with patch.object(application, "analyze", side_effect=fake_analyze), \
             patch.object(application, "persist_series") as persist:
            response = self.client.post(
                "/api/analyze/series",
                data={"case_name": "匿名病例001"},
                files=[
                    ("files", (f"slice-{index}.png", b"test", "image/png"))
                    for index in range(3)
                ],
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["prediction"]["decision"], "INDETERMINATE")
        self.assertEqual(response.json()["quality_gate"]["status"], "BLOCKED")
        self.assertEqual(response.json()["summary"]["analyzed_count"], 3)
        persist.assert_called_once()

    def test_dicom_series_requires_privacy_acknowledgement(self) -> None:
        registered = self.client.post(
            "/api/auth/register",
            json={
                **registration_fields("dicom-ack-pass-2026"),
                "email": "dicom-ack@example.com",
                "display_name": "DICOM授权测试",
                "password": "dicom-ack-pass-2026",
                "accepted_terms": True,
                "accepted_privacy": True,
            },
        )
        self.assertEqual(registered.status_code, 201)
        response = self.client.post(
            "/api/analyze/dicom-series",
            data={"case_name": "匿名DICOM病例", "privacy_acknowledged": "false"},
            files=[("files", ("secret-name.dcm", b"DICOM", "application/dicom"))],
        )
        self.assertEqual(response.status_code, 422)

    def test_dicom_series_uses_derived_slices_and_safe_summary(self) -> None:
        registered = self.client.post(
            "/api/auth/register",
            json={
                **registration_fields("dicom-route-pass-2026"),
                "email": "dicom-route@example.com",
                "display_name": "DICOM接口测试",
                "password": "dicom-route-pass-2026",
                "accepted_terms": True,
                "accepted_privacy": True,
            },
        )
        self.assertEqual(registered.status_code, 201)
        probabilities = {
            "adenocarcinoma": 0.75,
            "large_cell_carcinoma": 0.08,
            "normal": 0.05,
            "squamous_cell_carcinoma": 0.12,
        }
        counter = iter(range(3))

        async def fake_analyze(*, file, user):
            del user
            self.assertTrue(file.filename.startswith("dicom-slice-"))
            return slice_result(f"CT-DICOM-{next(counter)}", probabilities)

        prepared = [
            {"file_name": f"dicom-slice-{index + 1:03d}.png", "payload": b"PNG"}
            for index in range(3)
        ]
        summary = {
            "input_file_count": 3, "readable_slice_count": 3, "analyzed_slice_count": 3,
            "subsampled": False, "maximum_analysis_slices": 32,
            "window": {"name": "lung", "center_hu": -600, "width_hu": 1500},
            "privacy": {
                "direct_identifier_fields_detected": ["PatientName"],
                "identifier_values_persisted": False, "original_dicom_persisted": False,
                "burned_in_annotation": ["NO"], "pixel_privacy_review_required": True,
            },
        }
        from unittest.mock import patch
        with patch.object(application, "prepare_dicom_series", return_value=(prepared, [], summary)), \
             patch.object(application, "analyze", side_effect=fake_analyze), \
             patch.object(application, "persist_series") as persist:
            response = self.client.post(
                "/api/analyze/dicom-series",
                data={"case_name": "匿名DICOM病例", "privacy_acknowledged": "true"},
                files=[("files", ("secret-name.dcm", b"DICOM", "application/dicom")) for _ in range(3)],
            )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["input_mode"], "DICOM")
        self.assertEqual(payload["summary"]["uploaded_count"], 3)
        self.assertEqual(payload["dicom"]["privacy"]["original_dicom_persisted"], False)
        self.assertNotIn("secret-name", json.dumps(payload, ensure_ascii=False))
        self.assertEqual(payload["reliability"]["level"], "REVIEW_REQUIRED")
        self.assertEqual(payload["prediction"]["decision"], "INDETERMINATE")
        self.assertIn("DICOM肺窗派生图与训练图片的输入等价性尚未验证", payload["quality_gate"]["reasons"])
        persist.assert_called_once()

    def test_series_record_and_representative_context_are_persisted(self) -> None:
        probabilities = {
            "adenocarcinoma": 0.75,
            "large_cell_carcinoma": 0.08,
            "normal": 0.05,
            "squamous_cell_carcinoma": 0.12,
        }
        results = [slice_result(f"CT-DB-{index}", probabilities) for index in range(3)]
        with application.database_connection() as connection:
            for result in results:
                connection.execute(
                    """INSERT INTO analysis_tasks
                       (task_id, created_at, updated_at, status, file_name, image_path,
                        image_sha256, top_class, top_class_cn, reliability_level,
                        fold_agreement, analysis_json, owner_user_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        result["task_id"], "2026-09-03T00:00:00+00:00", "2026-09-03T00:00:00+00:00",
                        "WAITING_FOR_REVIEW", result["input"]["file_name"], "test.png",
                        f"sha-{result['task_id']}", result["prediction"]["top_class"],
                        result["prediction"]["top_class_cn"], "CONSISTENT", 5,
                        json.dumps(result, ensure_ascii=False), "USR-TEST",
                    ),
                )
        series = application.aggregate_series_results(results, case_name="持久化病例")
        application.persist_series(series, "USR-TEST")
        with application.database_connection() as connection:
            stored = connection.execute(
                "SELECT aggregate_json FROM analysis_series WHERE series_id = ?", (series["series_id"],)
            ).fetchone()
            item_count = connection.execute(
                "SELECT COUNT(*) FROM analysis_series_items WHERE series_id = ?", (series["series_id"],)
            ).fetchone()[0]
            representative = connection.execute(
                "SELECT analysis_json FROM analysis_tasks WHERE task_id = ?",
                (series["representative_slice"]["task_id"],),
            ).fetchone()
        self.assertIsNotNone(stored)
        self.assertEqual(item_count, 3)
        self.assertEqual(
            json.loads(representative["analysis_json"])["series_context"]["series_id"],
            series["series_id"],
        )
        report = application.download_series_report(series["series_id"], {"user_id": "USR-TEST"})
        report_text = report.body.decode("utf-8")
        self.assertIn("病例级二维 CT 辅助分析报告", report_text)
        self.assertIn("持久化病例", report_text)
        self.assertIn("逐切片结果与复核状态", report_text)
        self.assertIn("attachment", report.headers["content-disposition"])


if __name__ == "__main__":
    unittest.main()
