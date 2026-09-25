from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.db.models import (
    ContractType,
    Document,
    DocumentStatus,
    DocumentVersion,
    ProcessingJob,
)
from app.db.repositories.base import TenantScopedRepository


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class DocumentRepository(TenantScopedRepository[Document]):
    model = Document

    def _filtered(
        self,
        *,
        status: DocumentStatus | None = None,
        contract_type: ContractType | None = None,
        search: str | None = None,
    ) -> Select[tuple[Document]]:
        stmt = self._scoped()
        if status is not None:
            stmt = stmt.where(Document.status == status)
        if contract_type is not None:
            stmt = stmt.where(Document.contract_type == contract_type)
        if search:
            pattern = f"%{_escape_like(search)}%"
            stmt = stmt.where(
                or_(
                    Document.title.ilike(pattern, escape="\\"),
                    Document.counterparty.ilike(pattern, escape="\\"),
                )
            )
        return stmt

    async def search(
        self,
        *,
        offset: int,
        limit: int,
        status: DocumentStatus | None = None,
        contract_type: ContractType | None = None,
        search: str | None = None,
    ) -> tuple[Sequence[Document], int]:
        """A page of documents (with versions loaded) and the total match count."""
        stmt = self._filtered(status=status, contract_type=contract_type, search=search)
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        page = (
            stmt.options(selectinload(Document.versions))
            .order_by(Document.updated_at.desc(), Document.id)
            .offset(offset)
            .limit(min(limit, 200))
        )
        return (await self.session.execute(page)).scalars().all(), int(total)

    async def get_with_versions(self, document_id: uuid.UUID) -> Document:
        # populate_existing: a document already in the session (e.g. just
        # given a new version) must reload its versions, not reuse a stale list.
        stmt = (
            self._scoped()
            .where(Document.id == document_id)
            .options(selectinload(Document.versions))
            .execution_options(populate_existing=True)
        )
        document = (await self.session.execute(stmt)).scalar_one_or_none()
        if document is None:
            raise NotFoundError("Document not found.")
        return document

    async def delete_by_id(self, document_id: uuid.UUID) -> None:
        """Delete in SQL so PostgreSQL's ON DELETE CASCADE removes versions
        and jobs, instead of the ORM loading every child row first."""
        await self.session.execute(
            delete(Document).where(
                Document.id == document_id, Document.organization_id == self.tenant_id
            )
        )


class DocumentVersionRepository(TenantScopedRepository[DocumentVersion]):
    model = DocumentVersion

    async def find_live_duplicate(self, sha256: str) -> DocumentVersion | None:
        """An earlier upload of identical bytes in this tenant that did not fail.

        Deliberately tenant-scoped: matching across tenants would tell one
        organization that another holds the same contract.
        """
        stmt = (
            self._scoped()
            .where(DocumentVersion.sha256 == sha256)
            .where(DocumentVersion.status != DocumentStatus.FAILED)
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()


class JobRepository(TenantScopedRepository[ProcessingJob]):
    model = ProcessingJob

    async def latest_for_version(self, version_id: uuid.UUID) -> ProcessingJob | None:
        stmt = (
            self._scoped()
            .where(ProcessingJob.document_version_id == version_id)
            .order_by(ProcessingJob.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()
