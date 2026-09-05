"""Bounded avatar decoding; only normalized, metadata-free PNG bytes are stored."""

import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_AVATAR_BYTES = 3 * 1024 * 1024
MAX_AVATAR_EDGE = 4096
MAX_AVATAR_PIXELS = 16_000_000


def normalize_avatar(payload: bytes) -> bytes:
    if not payload:
        raise ValueError("请选择非空图片")
    if len(payload) > MAX_AVATAR_BYTES:
        raise ValueError("头像图片不能超过3MB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(payload)) as source:
                if source.format not in {"PNG", "JPEG", "WEBP"}:
                    raise ValueError("头像仅支持PNG、JPEG或WebP静态图片")
                if max(source.size) > MAX_AVATAR_EDGE or source.width * source.height > MAX_AVATAR_PIXELS:
                    raise ValueError("头像边长不能超过4096像素，且总像素不能超过1600万")
                if getattr(source, "n_frames", 1) != 1:
                    raise ValueError("请上传静态图片，不支持动画头像")
                source.load()
                cropped = ImageOps.fit(ImageOps.exif_transpose(source).convert("RGBA"), (256, 256), method=Image.Resampling.LANCZOS)
                # A fresh image discards EXIF, GPS, comments, ICC and PNG text chunks.
                clean = Image.new("RGBA", (256, 256))
                clean.paste(cropped)
                output = io.BytesIO()
                clean.save(output, format="PNG")
                return output.getvalue()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("头像图片分辨率过大，请缩小后上传") from exc
    except (UnidentifiedImageError, OSError, SyntaxError, EOFError) as exc:
        raise ValueError("无法读取该图片，请上传完整的PNG、JPEG或WebP文件") from exc
