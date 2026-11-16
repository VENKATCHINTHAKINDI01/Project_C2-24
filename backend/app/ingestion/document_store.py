"""Source-document store (ADR-0014 rule 7; plan §3.5, §4.6).

The exact bytes each indexed record was extracted from, keyed by version (content hash +
extractor version, as the ingestion pipeline records it). Core modules use only the
`DocumentStore` interface. `InMemoryDocumentStore` is the SANDBOX stand-in for a private Cloud
Storage bucket; `GcsDocumentStore` is the GCP implementation (C2_DOCUMENT_STORE=gcs).
Nothing here checks access: callers serve bytes only after `can_access` (ADR-0014 rule 1).
"""

from __future__ import annotations

import importlib
from pathlib import PurePath
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from app.config import Settings


class DocumentStoreError(Exception):
    """Storage failed. Callers fail closed (the file is not served / ingestion stops)."""


PREVIEWABLE = frozenset({"application/pdf", "image/jpeg", "image/png"})

_OFFICE = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
_EXT = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    _OFFICE[".docx"]: ".docx",
    _OFFICE[".xlsx"]: ".xlsx",
}


def media_type(data: bytes, filename: str) -> str:
    """Media type from the content itself (CLAUDE.md §5.1: an extension proves nothing). Office
    files are ZIP containers, so only there does the extension pick between Word and Excel."""
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"PK\x03\x04"):
        return _OFFICE.get(PurePath(filename).suffix.lower(), "application/octet-stream")
    return "application/octet-stream"


def extension(media: str) -> str:
    return _EXT.get(media, ".bin")


class StoredDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str  # sha256 prefix + pipeline version (ingestion `_version`)
    media_type: str
    data: bytes

    @property
    def previewable(self) -> bool:
        return self.media_type in PREVIEWABLE


class DocumentStore(Protocol):
    def put(self, doc: StoredDocument) -> None: ...

    def get(self, version: str) -> StoredDocument | None: ...


class InMemoryDocumentStore:
    """SANDBOX stand-in for the private Cloud Storage bucket (synthetic corpus only)."""

    def __init__(self) -> None:
        self._docs: dict[str, StoredDocument] = {}

    def put(self, doc: StoredDocument) -> None:
        self._docs.setdefault(doc.version, doc)  # content-addressed: same version, same bytes

    def get(self, version: str) -> StoredDocument | None:
        return self._docs.get(version)


def _api_errors() -> Any:
    """google.api_core.exceptions (installed with the `gcp` extra)."""
    return importlib.import_module("google.api_core.exceptions")


class GcsDocumentStore:
    """Private Cloud Storage bucket (plan §3.5; ADR-0014 rules 2, 3, 7). One object per version,
    named from the version, so the exact bytes a citation came from stay addressable. Written once
    (`if_generation_match=0`), never overwritten or deleted; the bucket keeps object versions too.
    The SDK is imported lazily (`gcp` extra); errors surface as `DocumentStoreError`, no content."""

    def __init__(self, bucket: str, prefix: str, *, client: Any = None) -> None:
        if not bucket:
            raise DocumentStoreError("GCS document store needs a bucket name")
        self.bucket_name, self.prefix = bucket, prefix.strip("/")
        self._client = client
        self._bucket: Any = None

    def _b(self) -> Any:
        if self._bucket is None:
            if self._client is None:
                try:  # optional `gcp` extra; imported by name (the package ships no type stubs)
                    storage = importlib.import_module("google.cloud.storage")
                except ImportError as exc:  # pragma: no cover - depends on installed extras
                    raise DocumentStoreError("google-cloud-storage not installed") from exc
                self._client = storage.Client()
            self._bucket = self._client.bucket(self.bucket_name)
        return self._bucket

    def object_name(self, version: str) -> str:
        return f"{self.prefix}/{version.replace(':', '/')}"

    def put(self, doc: StoredDocument) -> None:
        blob = self._b().blob(self.object_name(doc.version))
        blob.metadata = {"c2_version": doc.version}
        try:
            blob.upload_from_string(doc.data, content_type=doc.media_type, if_generation_match=0)
        except Exception as exc:
            if isinstance(exc, _api_errors().PreconditionFailed):
                return  # already stored: content-addressed, same version = same bytes
            raise DocumentStoreError(f"upload failed: {type(exc).__name__}") from exc

    def get(self, version: str) -> StoredDocument | None:
        try:
            blob = self._b().get_blob(self.object_name(version))  # None when absent
            if blob is None:
                return None
            data = blob.download_as_bytes()
        except Exception as exc:
            if isinstance(exc, _api_errors().NotFound):
                return None
            raise DocumentStoreError(f"download failed: {type(exc).__name__}") from exc
        media = blob.content_type or "application/octet-stream"
        return StoredDocument(version=version, media_type=media, data=data)


def document_store_from_settings(settings: Settings) -> DocumentStore:
    """`memory` (sandbox default) or `gcs` (private raw bucket). Bad config fails at startup."""
    if settings.document_store == "gcs":
        return GcsDocumentStore(settings.gcs_raw_bucket or "", settings.gcs_documents_prefix)
    return InMemoryDocumentStore()
