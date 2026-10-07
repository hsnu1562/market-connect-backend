from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from ..models import Stall, StallPhoto


MAX_STALL_PHOTOS = 5
MAX_STALL_PHOTO_BYTES = 4 * 1024 * 1024

_PHOTO_TYPES = {
    ".jpg": ("image/jpeg", lambda data: data.startswith(b"\xff\xd8\xff")),
    ".jpeg": ("image/jpeg", lambda data: data.startswith(b"\xff\xd8\xff")),
    ".png": ("image/png", lambda data: data.startswith(b"\x89PNG\r\n\x1a\n")),
    ".webp": (
        "image/webp",
        lambda data: len(data) >= 12
        and data.startswith(b"RIFF")
        and data[8:12] == b"WEBP",
    ),
}


@dataclass(frozen=True)
class ValidatedStallPhoto:
    filename: str
    content_type: str
    data: bytes
    sha256: str


def validate_stall_photo_uploads(files: list[FileStorage]) -> list[ValidatedStallPhoto]:
    uploads = [item for item in files if item and item.filename]
    if not uploads:
        raise ValueError("請上傳至少一張攤位照片。")
    if len(uploads) > MAX_STALL_PHOTOS:
        raise ValueError(f"每個攤位最多上傳 {MAX_STALL_PHOTOS} 張照片。")

    validated = []
    seen_digests = set()
    for upload in uploads:
        filename = secure_filename(Path(upload.filename).name)
        if not filename:
            raise ValueError("照片檔名無效，請重新命名後再上傳。")

        suffix = Path(filename).suffix.lower()
        photo_type = _PHOTO_TYPES.get(suffix)
        if photo_type is None:
            raise ValueError("攤位照片只接受 JPG、PNG 或 WebP 格式。")

        data = upload.stream.read(MAX_STALL_PHOTO_BYTES + 1)
        if not data:
            raise ValueError(f"{filename} 是空白檔案。")
        if len(data) > MAX_STALL_PHOTO_BYTES:
            raise ValueError(f"{filename} 超過 4 MB 上限。")

        content_type, has_valid_signature = photo_type
        if not has_valid_signature(data):
            raise ValueError(f"{filename} 的內容與副檔名不符。")

        digest = hashlib.sha256(data).hexdigest()
        if digest in seen_digests:
            raise ValueError("請勿重複上傳相同的攤位照片。")
        seen_digests.add(digest)
        validated.append(
            ValidatedStallPhoto(
                filename=filename,
                content_type=content_type,
                data=data,
                sha256=digest,
            )
        )
    return validated


def attach_stall_photos(stall: Stall, uploads: list[ValidatedStallPhoto]) -> None:
    if stall.photos:
        raise ValueError("Stall already has photos attached.")

    for display_order, upload in enumerate(uploads):
        stall.photos.append(
            StallPhoto(
                original_filename=upload.filename,
                content_type=upload.content_type,
                byte_size=len(upload.data),
                sha256=upload.sha256,
                display_order=display_order,
                data=upload.data,
            )
        )
