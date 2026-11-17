"""Shared letterbox geometry for preprocessing and inverse attention mapping."""


def resize_pad_geometry(width: int, height: int, size: int = 224):
    if min(width, height, size) <= 0:
        raise ValueError('Image dimensions must be positive')
    scale = min(size / width, size / height)
    resized_width = max(1, round(width * scale))
    resized_height = max(1, round(height * scale))
    return ((size - resized_width) // 2, (size - resized_height) // 2,
            resized_width, resized_height)


def restore_attention_map(cam, width: int, height: int):
    """Undo the input letterbox before projecting an attention map onto pixels."""
    import torch.nn.functional as functional
    cam = functional.interpolate(cam, size=(224, 224), mode='bilinear', align_corners=False)
    left, top, inner_width, inner_height = resize_pad_geometry(width, height)
    content = cam[:, :, top:top + inner_height, left:left + inner_width]
    return functional.interpolate(content, size=(height, width), mode='bilinear', align_corners=False)
