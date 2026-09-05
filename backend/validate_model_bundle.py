"""Validate a LungSight five-fold bundle without changing the active model."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

from PIL import Image


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--bundle", type=Path, required=True)
    result.add_argument("--image", type=Path, required=True)
    return result


def main() -> int:
    arguments = parser().parse_args()
    bundle = arguments.bundle.resolve(strict=True)
    image_path = arguments.image.resolve(strict=True)
    if not (bundle / "model_manifest.json").is_file():
        raise FileNotFoundError("模型目录缺少 model_manifest.json")

    os.environ["LUNGSIGHT_MODEL_BUNDLE_DIR"] = str(bundle)
    import app as application

    runtime = application.ModelRuntime()
    paths = runtime.verify_weights()
    runtime.load()
    with Image.open(image_path) as opened:
        image = opened.convert("RGB")
    prediction = runtime.predict(image)
    attention, attention_ms = runtime.generate_attention_map(image, prediction["top_index"])
    probabilities = prediction["mean_probability"]
    if len(paths) != 5 or len(runtime.models) != 5:
        raise RuntimeError("五折权重未完整加载")
    if not all(math.isfinite(value) and 0 <= value <= 1 for value in probabilities):
        raise RuntimeError("模型概率包含无效值")
    if not math.isclose(sum(probabilities), 1.0, rel_tol=0, abs_tol=1e-6):
        raise RuntimeError("模型概率之和不为1")
    if attention.size != image.size:
        raise RuntimeError("Grad-CAM输出尺寸与输入不一致")

    print(json.dumps({
        "status": "engineering_validation_passed",
        "model_version": runtime.manifest["model_version"],
        "weights_verified": len(paths),
        "device": runtime.device,
        "probabilities": dict(zip(runtime.manifest["class_names"], probabilities)),
        "fold_agreement": f"{prediction['fold_agreement']}/5",
        "attention_size": list(attention.size),
        "attention_ms": round(attention_ms, 3),
        "research_only": bool(runtime.manifest.get("research_only", False)),
        "clinical_use_allowed": bool(runtime.manifest.get("clinical_use_allowed", False)),
    }, ensure_ascii=False, indent=2))
    runtime.models.clear()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
