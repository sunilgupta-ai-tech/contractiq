from __future__ import annotations

from app.db.models import Document, DocumentVersion, ProcessingJob
from app.db.repositories.base import TenantScopedRepository


class DocumentRepository(TenantScopedRepository[Document]):
    model = Document


class DocumentVersionRepository(TenantScopedRepository[DocumentVersion]):
    model = DocumentVersion


class JobRepository(TenantScopedRepository[ProcessingJob]):
    model = ProcessingJob
