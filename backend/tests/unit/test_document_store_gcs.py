"""GCS document store (ADR-0014 rule 7) with a fake bucket: no network, no credentials.
Needs the `gcp` extra for the SDK's exception types; skipped otherwise."""

from __future__ import annotations

import pytest

from app.config import Settings
from app.ingestion.document_store import (
    DocumentStoreError,
    GcsDocumentStore,
    InMemoryDocumentStore,
    StoredDocument,
    document_store_from_settings,
)

gexc = pytest.importorskip("google.api_core.exceptions")


class FakeBlob:
    def __init__(self, bucket: FakeBucket, name: str) -> None:
        self.bucket, self.name = bucket, name
        self.metadata: dict[str, str] | None = None
        self.content_type: str | None = None

    def upload_from_string(self, data: bytes, content_type: str, if_generation_match: int) -> None:
        if self.bucket.fail:
            raise gexc.Forbidden("caller lacks storage.objects.create on secret-bucket")
        if if_generation_match == 0 and self.name in self.bucket.objects:
            raise gexc.PreconditionFailed("exists")
        self.content_type = content_type
        self.bucket.objects[self.name] = (data, content_type, dict(self.metadata or {}))

    def download_as_bytes(self) -> bytes:
        return self.bucket.objects[self.name][0]


class FakeBucket:
    def __init__(self, fail: bool = False) -> None:
        self.objects: dict[str, tuple[bytes, str, dict[str, str]]] = {}
        self.fail = fail

    def blob(self, name: str) -> FakeBlob:
        return FakeBlob(self, name)

    def get_blob(self, name: str) -> FakeBlob | None:
        if name not in self.objects:
            return None
        b = FakeBlob(self, name)
        b.content_type = self.objects[name][1]
        return b


class FakeClient:
    def __init__(self, bucket: FakeBucket) -> None:
        self.b = bucket

    def bucket(self, name: str) -> FakeBucket:
        return self.b


def test_gcs_store_writes_once_per_version_and_reads_back() -> None:
    bucket = FakeBucket()
    store = GcsDocumentStore("raw", "/synthetic/mock_v1/sources/", client=FakeClient(bucket))
    v = "sha256:abc123:ingest-2026-11-03"
    store.put(StoredDocument(version=v, media_type="application/pdf", data=b"%PDF-1"))
    store.put(
        StoredDocument(version=v, media_type="application/pdf", data=b"%PDF-2")
    )  # no overwrite
    assert list(bucket.objects) == ["synthetic/mock_v1/sources/sha256/abc123/ingest-2026-11-03"]
    got = store.get(v)
    assert got == StoredDocument(version=v, media_type="application/pdf", data=b"%PDF-1")
    assert bucket.objects[store.object_name(v)][2] == {"c2_version": v}
    assert store.get("sha256:missing:x") is None


def test_gcs_store_errors_name_the_type_only() -> None:
    store = GcsDocumentStore("raw", "p", client=FakeClient(FakeBucket(fail=True)))
    with pytest.raises(DocumentStoreError) as e:
        store.put(StoredDocument(version="v", media_type="application/pdf", data=b"%PDF"))
    assert str(e.value) == "upload failed: Forbidden" and "secret-bucket" not in str(e.value)


def test_store_from_settings() -> None:
    assert isinstance(document_store_from_settings(Settings()), InMemoryDocumentStore)
    with pytest.raises(DocumentStoreError):
        document_store_from_settings(Settings(document_store="gcs"))  # no bucket: refuse
    s = Settings(document_store="gcs", gcs_raw_bucket="use-case-24-project-c2-raw")
    gcs = document_store_from_settings(s)
    assert isinstance(gcs, GcsDocumentStore) and gcs.prefix == "synthetic/mock_v1/sources"
