from __future__ import annotations

import math
import unittest
from unittest.mock import patch

import app as application


class FixedModel:
    def __init__(self, logits):
        import torch

        self.logits = torch.tensor([logits], dtype=torch.float32)

    def __call__(self, _tensor):
        return self.logits


class ModelRuntimeTests(unittest.TestCase):
    def test_manifest_has_five_compatible_folds(self):
        self.assertEqual(len(application.runtime.manifest["weights"]), 5)
        self.assertEqual(
            application.runtime.manifest["class_names"],
            ["adenocarcinoma", "large_cell_carcinoma", "normal", "squamous_cell_carcinoma"],
        )

    def test_temperature_calibration_is_applied_after_fold_mean(self):
        runtime = application.ModelRuntime()
        runtime.models = [FixedModel([2.0, 1.0, 0.0, -1.0]) for _ in range(5)]
        runtime.device = "cpu"
        runtime.manifest["temperature"] = 0.5
        with patch.object(runtime, "transform") as transform:
            import torch

            transform.return_value = torch.zeros((3, 224, 224), dtype=torch.float32)
            result = runtime.predict(application.Image.new("RGB", (224, 224)))
        probabilities = result["mean_probability"]
        self.assertTrue(all(math.isfinite(value) for value in probabilities))
        self.assertAlmostEqual(sum(probabilities), 1.0, places=7)
        self.assertGreater(probabilities[0], result["fold_probabilities"][0][0])

    def test_invalid_temperature_is_rejected(self):
        runtime = application.ModelRuntime()
        runtime.models = [FixedModel([1.0, 0.0, 0.0, 0.0]) for _ in range(5)]
        runtime.device = "cpu"
        runtime.manifest["temperature"] = 0
        with patch.object(runtime, "transform") as transform:
            import torch

            transform.return_value = torch.zeros((3, 224, 224), dtype=torch.float32)
            with self.assertRaisesRegex(RuntimeError, "温度校准参数无效"):
                runtime.predict(application.Image.new("RGB", (224, 224)))


if __name__ == "__main__":
    unittest.main()
