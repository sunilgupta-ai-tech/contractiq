import pytest

from app.storage.local import LocalObjectStorage
from app.vectorstore.qdrant import tenant_filter


def test_tenant_condition_is_always_first_must_clause():
    f = tenant_filter("org-a", document_ids=["d1"], version_ids=["v2"])
    assert f.must[0].key == "tenant_id"
    assert f.must[0].match.value == "org-a"
    assert len(f.must) == 3


def test_tenant_filter_without_optional_scopes():
    f = tenant_filter("org-a")
    assert [c.key for c in f.must] == ["tenant_id"]


async def test_local_storage_blocks_path_traversal(tmp_path):
    storage = LocalObjectStorage(str(tmp_path / "root"))
    with pytest.raises(ValueError):
        await storage.put("../../etc/passwd", b"x", "text/plain")
    await storage.put("tenants/a/doc.pdf", b"%PDF", "application/pdf")
    assert await storage.get("tenants/a/doc.pdf") == b"%PDF"


async def test_delete_prefix_removes_one_document_folder_only(tmp_path):
    storage = LocalObjectStorage(str(tmp_path))
    mine = "tenants/a/documents/d1/"
    for key in (f"{mine}v1/original.pdf", f"{mine}v1/parsed.json", f"{mine}v1/images/p1.png"):
        await storage.put(key, b"x", "application/octet-stream")
    await storage.put("tenants/a/documents/d2/v1/original.pdf", b"x", "application/pdf")

    await storage.delete_prefix(mine)
    assert not await storage.exists(f"{mine}v1/parsed.json")
    assert await storage.exists("tenants/a/documents/d2/v1/original.pdf")  # sibling untouched

    for dangerous in ("", "/", "../"):
        with pytest.raises(ValueError):
            await storage.delete_prefix(dangerous)
