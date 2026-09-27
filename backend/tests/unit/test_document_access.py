"""Phase 20: document-level access building blocks."""

import uuid

from app.db.repositories.document_repository import DocumentAccess
from app.vectorstore.qdrant import tenant_filter


def test_hidden_documents_become_a_must_not_clause_after_the_tenant():
    flt = tenant_filter("t-a", exclude_document_ids=["d-1", "d-2"])
    assert flt.must[0].key == "tenant_id"  # the tenant condition always comes first
    (excluded,) = flt.must_not
    assert excluded.key == "document_id" and set(excluded.match.any) == {"d-1", "d-2"}
    assert tenant_filter("t-a").must_not is None


def test_read_all_sees_everything_and_users_get_a_visibility_condition():
    assert DocumentAccess.system().visible() is None
    assert DocumentAccess.for_user(uuid.uuid4(), uuid.uuid4(), read_all=True).visible() is None
    user = DocumentAccess.for_user(uuid.uuid4(), uuid.uuid4(), read_all=False)
    sql = str(user.visible())
    assert "visibility" in sql and "uploaded_by_id" in sql and "document_grants" in sql
