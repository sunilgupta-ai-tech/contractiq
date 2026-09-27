from __future__ import annotations

import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import ColumnElement, Select, delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.db.models import (
    ContractType,
    Document,
    DocumentGrant,
    DocumentStatus,
    DocumentVersion,
    DocumentVisibility,
    FileType,
    ProcessingJob,
)
from app.db.repositories.base import TenantScopedRepository


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass(frozen=True)
class DocumentAccess:
    """Which documents of the tenant a caller may see (Phase 20).

    A RESTRICTED document is visible to its uploader, to users and roles
    granted access, and to holders of document:read_all. Every repository
    that reads documents takes one of these explicitly, so no call site can
    forget the rule: `system()` is for the worker, which processes whatever
    it is given and serves no user.
    """

    user_id: uuid.UUID | None
    role_id: uuid.UUID | None
    read_all: bool

    @classmethod
    def system(cls) -> DocumentAccess:
        return cls(user_id=None, role_id=None, read_all=True)

    @classmethod
    def for_user(cls, user_id: uuid.UUID, role_id: uuid.UUID, *, read_all: bool) -> DocumentAccess:
        return cls(user_id=user_id, role_id=role_id, read_all=read_all)

    def visible(self) -> ColumnElement[bool] | None:
        """The SQL condition on `Document`, or None when everything is visible."""
        if self.read_all:
            return None
        granted = exists().where(
            DocumentGrant.document_id == Document.id,
            or_(DocumentGrant.user_id == self.user_id, DocumentGrant.role_id == self.role_id),
        )
        return or_(
            Document.visibility == DocumentVisibility.ORGANIZATION,
            Document.uploaded_by_id == self.user_id,
            granted,
        )


class DocumentSort(StrEnum):
    """Library ordering. `id` breaks ties so pages never overlap or skip."""

    NEWEST = "newest"
    OLDEST = "oldest"
    NAME = "name"


_ORDER = {
    DocumentSort.NEWEST: (Document.updated_at.desc(), Document.id),
    DocumentSort.OLDEST: (Document.updated_at.asc(), Document.id),
    DocumentSort.NAME: (func.lower(Document.title).asc(), Document.id),
}


class DocumentRepository(TenantScopedRepository[Document]):
    model = Document

    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, *, access: DocumentAccess
    ) -> None:
        super().__init__(session, tenant_id)
        self.access = access

    def _scoped(self) -> Select[tuple[Document]]:
        stmt = super()._scoped()
        condition = self.access.visible()
        return stmt if condition is None else stmt.where(condition)

    async def hidden_ids(self) -> list[str]:
        """This tenant's documents the caller may NOT see. Search excludes
        them (Phase 20), so no chunk of theirs can reach the model."""
        condition = self.access.visible()
        if condition is None:
            return []
        stmt = select(Document.id).where(Document.organization_id == self.tenant_id, ~condition)
        return [str(i) for i in (await self.session.execute(stmt)).scalars()]

    async def corpus_version(self) -> str:
        """Changes whenever any document of the tenant is added, processed,
        changed or removed (Phase 21 answer cache)."""
        count, latest = (
            await self.session.execute(
                select(func.count(), func.max(Document.updated_at)).where(
                    Document.organization_id == self.tenant_id
                )
            )
        ).one()
        return f"{count}:{latest.isoformat() if latest else '-'}"

    async def is_visible(self, document_id: uuid.UUID) -> bool:
        stmt = select(func.count()).select_from(
            self._scoped().where(Document.id == document_id).subquery()
        )
        return bool((await self.session.execute(stmt)).scalar_one())

    def _filtered(
        self,
        *,
        status: DocumentStatus | Collection[DocumentStatus] | None = None,
        contract_type: ContractType | None = None,
        file_type: FileType | None = None,
        search: str | None = None,
        needs_review: bool | None = None,
    ) -> Select[tuple[Document]]:
        stmt = self._scoped()
        if needs_review is not None:
            stmt = stmt.where(Document.needs_review.is_(needs_review))
        if isinstance(status, DocumentStatus):
            stmt = stmt.where(Document.status == status)
        elif status:  # any of several, e.g. every in-progress pipeline stage
            stmt = stmt.where(Document.status.in_(set(status)))
        if contract_type is not None:
            stmt = stmt.where(Document.contract_type == contract_type)
        if file_type is not None:
            stmt = stmt.where(Document.file_type == file_type)
        if search:
            pattern = f"%{_escape_like(search)}%"
            # Title, counterparty, or the file name of any version
            # ("invoice.jpg" is found by "invoice" or ".jpg").
            filename_match = exists().where(
                DocumentVersion.document_id == Document.id,
                DocumentVersion.organization_id == self.tenant_id,
                DocumentVersion.original_filename.ilike(pattern, escape="\\"),
            )
            stmt = stmt.where(
                or_(
                    Document.title.ilike(pattern, escape="\\"),
                    Document.counterparty.ilike(pattern, escape="\\"),
                    filename_match,
                )
            )
        return stmt

    async def file_type_counts(
        self,
        *,
        status: DocumentStatus | Collection[DocumentStatus] | None = None,
        search: str | None = None,
    ) -> dict[FileType, int]:
        """Documents per file type for the library tabs, under the same
        status/search filters as the list (one grouped query)."""
        matching = self._filtered(status=status, search=search).subquery()
        rows = await self.session.execute(
            select(matching.c.file_type, func.count()).group_by(matching.c.file_type)
        )
        counts = dict.fromkeys(FileType, 0)
        for file_type, count in rows.all():
            counts[FileType(file_type)] = int(count)
        return counts

    async def search(
        self,
        *,
        offset: int,
        limit: int,
        status: DocumentStatus | Collection[DocumentStatus] | None = None,
        contract_type: ContractType | None = None,
        file_type: FileType | None = None,
        search: str | None = None,
        sort: DocumentSort = DocumentSort.NEWEST,
        needs_review: bool | None = None,
    ) -> tuple[Sequence[Document], int]:
        """A page of documents (with versions loaded) and the total match count."""
        stmt = self._filtered(
            status=status,
            contract_type=contract_type,
            file_type=file_type,
            search=search,
            needs_review=needs_review,
        )
        total = (
            await self.session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        page = (
            stmt.options(selectinload(Document.versions))
            .order_by(*_ORDER[sort])
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
    """Versions are visible when their document is (Phase 20)."""

    model = DocumentVersion

    def __init__(
        self, session: AsyncSession, tenant_id: uuid.UUID, *, access: DocumentAccess
    ) -> None:
        super().__init__(session, tenant_id)
        self.access = access

    def _scoped(self) -> Select[tuple[DocumentVersion]]:
        stmt = super()._scoped()
        condition = self.access.visible()
        if condition is None:
            return stmt
        return stmt.where(exists().where(Document.id == DocumentVersion.document_id, condition))

    async def find_live_duplicate(self, sha256: str) -> DocumentVersion | None:
        """An earlier upload of identical bytes in this tenant that did not fail.

        Deliberately tenant-scoped (and, independently, under row-level
        security): matching across tenants would tell one organization that
        another holds the same document. The file name plays no part: the
        same name with different content is a different document.

        NOT limited to the documents the caller can see: a copy of a
        restricted document is still a duplicate (the caller is then told
        only that it exists, not where — see DocumentService).
        """
        stmt = (
            super()
            ._scoped()
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
