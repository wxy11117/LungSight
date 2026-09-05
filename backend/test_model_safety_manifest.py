import json
import unittest

import app as application


class ModelSafetyManifestTests(unittest.TestCase):
    def test_lineage_distinguishes_architecture_from_exact_weights(self):
        manifest = json.loads(application.MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertTrue(manifest["lineage"]["architecture_matches_original_plan"])
        self.assertFalse(manifest["lineage"]["exact_original_weights"])
        self.assertEqual(manifest["lineage"]["source_run"], "lung-training/runs/research-fivefold-20260902-165455")

    def test_unvalidated_clinical_gates_are_fail_closed(self):
        manifest = application.runtime.manifest
        self.assertTrue(manifest["research_only"])
        self.assertFalse(manifest["clinical_use_allowed"])
        self.assertFalse(manifest["input_contract"]["dicom_pipeline_equivalence_verified"])
        self.assertTrue(manifest["abstention"]["case_series"]["forced_abstention"])
        self.assertFalse(manifest["activation"]["deployment_performed"])
        self.assertFalse(manifest["activation"]["promotion_approved"])

    def test_research_thresholds_are_traced_and_not_clinical(self):
        threshold = application.runtime.manifest["abstention"]["single_image"]
        self.assertEqual(threshold["minimum_top_probability"], 0.7)
        self.assertEqual(threshold["minimum_top_two_margin"], 0.2)
        self.assertEqual(threshold["minimum_fold_agreement"], 4)
        self.assertFalse(threshold["clinical_threshold"])
        self.assertIn("weak-label", threshold["selection_source"])


if __name__ == "__main__":
    unittest.main()
