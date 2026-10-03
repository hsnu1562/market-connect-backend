from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from ..models import StallCertification, StallCertificationDocument


MAX_DOCUMENTS = 3
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024

_FILE_TYPES = {
    ".pdf": ("application/pdf", lambda data: data.startswith(b"%PDF-")),
    ".png": ("image/png", lambda data: data.startswith(b"\x89PNG\r\n\x1a\n")),
    ".jpg": ("image/jpeg", lambda data: data.startswith(b"\xff\xd8\xff")),
    ".jpeg": ("image/jpeg", lambda data: data.startswith(b"\xff\xd8\xff")),
}


@dataclass(frozen=True)
class ValidatedDocument:
    filename: str
    content_type: str
    data: bytes
    sha256: str


def validate_document_uploads(files: list[FileStorage]) -> list[ValidatedDocument]:
    uploads = [item for item in files if item and item.filename]
    if len(uploads) > MAX_DOCUMENTS:
        raise ValueError(f"每次最多上傳 {MAX_DOCUMENTS} 份證明文件。")

    validated = []
    seen_digests = set()
    for upload in uploads:
        filename = secure_filename(Path(upload.filename).name)
        if not filename:
            raise ValueError("證明文件名稱無效，請重新命名後再上傳。")

        suffix = Path(filename).suffix.lower()
        file_type = _FILE_TYPES.get(suffix)
        if file_type is None:
            raise ValueError("證明文件只接受 PDF、JPG 或 PNG 格式。")

        data = upload.stream.read(MAX_DOCUMENT_BYTES + 1)
        if not data:
            raise ValueError(f"{filename} 是空白檔案。")
        if len(data) > MAX_DOCUMENT_BYTES:
            raise ValueError(f"{filename} 超過 5 MB 上限。")

        content_type, has_valid_signature = file_type
        if not has_valid_signature(data):
            raise ValueError(f"{filename} 的內容與副檔名不符。")

        digest = hashlib.sha256(data).hexdigest()
        if digest in seen_digests:
            raise ValueError("請勿重複上傳相同的證明文件。")
        seen_digests.add(digest)
        validated.append(
            ValidatedDocument(
                filename=filename,
                content_type=content_type,
                data=data,
                sha256=digest,
            )
        )
    return validated


def replace_certification_documents(
    certification: StallCertification,
    uploads: list[ValidatedDocument],
) -> None:
    if certification.id is None:
        raise ValueError("Certification must be persisted before adding documents.")

    certification.documents.clear()
    key = _document_key()
    for upload in uploads:
        nonce = os.urandom(12)
        aad = _document_aad(
            certification.id,
            upload.filename,
            upload.content_type,
            len(upload.data),
            upload.sha256,
        )
        certification.documents.append(
            StallCertificationDocument(
                original_filename=upload.filename,
                content_type=upload.content_type,
                byte_size=len(upload.data),
                sha256=upload.sha256,
                nonce=nonce,
                ciphertext=AESGCM(key).encrypt(nonce, upload.data, aad),
            )
        )


def decrypt_certification_document(document: StallCertificationDocument) -> bytes:
    aad = _document_aad(
        document.certification_id,
        document.original_filename,
        document.content_type,
        document.byte_size,
        document.sha256,
    )
    return AESGCM(_document_key()).decrypt(document.nonce, document.ciphertext, aad)


def _document_key() -> bytes:
    secret_key = current_app.config.get("SECRET_KEY")
    if isinstance(secret_key, str):
        secret_key = secret_key.encode("utf-8")
    if not secret_key:
        raise RuntimeError("SECRET_KEY is required for certification document encryption.")
    return hmac.new(
        secret_key,
        b"spacis-certification-documents-v1",
        hashlib.sha256,
    ).digest()


def _document_aad(
    certification_id: int,
    filename: str,
    content_type: str,
    byte_size: int,
    digest: str,
) -> bytes:
    return json.dumps(
        [certification_id, filename, content_type, byte_size, digest],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")
