"""
POST /query orchestration: validation, conversation, pipeline, persistence.

    1. validate scope   every document/version id must exist in the caller's
                        tenant (else 404 — foreign ids look like unknown ids)
    2. conversation     continue the caller's own conversation, or start one
    3. history          last N question/answer pairs, for follow-ups
    4. QAPipeline       retrieve -> rerank -> context -> generate -> cite
    5. persist          user + assistant messages (citations, model, tokens,
                        latency, request id) in one transaction

Failures of external services are mapped to a clean 503, never a 500 with
internals: a missing key or unknown model is "not configured", a timeout or
rate limit is "temporarily unavailable".
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict
from typing import TYPE_CHECKING

from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ServiceUnavailableError
from app.core.logging import get_logger, request_id_ctx
from app.db.models import Conversation, Message, MessageRole
from app.db.repositories.conversation_repository import (
    ConversationRepository,
    MessageRepository,
)
from app.db.repositories.document_repository import (
    DocumentRepository,
    DocumentVersionRepository,
)
from app.llm.base import EmbeddingConfigError, EmbeddingError, LLMConfigError, LLMError
from app.rag.pipelines.qa import QAPipeline, RagAnswer
from app.schemas.query import CitationOut, QueryRequest, QueryResponse, StepOut, UsageOut
from app.services.reranking_service import reranker_for
from app.services.retrieval_service import RetrievalService

if TYPE_CHECKING:
    from app.core.resources import Resources

logger = get_logger(__name__)

NOT_CONFIGURED = "Question answering is not configured on this server."
UNAVAILABLE = "Question answering is temporarily unavailable. Please try again shortly."


class QueryService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        resources: Resources,
    ) -> None:
        self.session = session
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.resources = resources
        self.conversations = ConversationRepository(session, tenant_id)
        self.messages = MessageRepository(session, tenant_id)

    async def ask(self, request: QueryRequest) -> QueryResponse:
        started = time.perf_counter()
        await self._validate_scope(request)
        conversation = await self._conversation(request)
        history = await self.messages.recent_turns(
            conversation.id, self.resources.settings.conversation_history_turns
        )

        result = await self._run_pipeline(request, history)
        latency_ms = int((time.perf_counter() - started) * 1000)

        self.session.add(
            Message(
                organization_id=self.tenant_id,
                conversation_id=conversation.id,
                role=MessageRole.USER,
                content=request.question,
                citations=[],
            )
        )
        assistant = Message(
            organization_id=self.tenant_id,
            conversation_id=conversation.id,
            role=MessageRole.ASSISTANT,
            content=result.answer,
            citations=[asdict(c) for c in result.citations],
            trace_id=request_id_ctx.get(),
            model=result.model,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            latency_ms=latency_ms,
        )
        self.session.add(assistant)
        await self.session.commit()
        return _response(request, conversation.id, assistant.id, result, latency_ms)

    async def _validate_scope(self, request: QueryRequest) -> None:
        documents = DocumentRepository(self.session, self.tenant_id)
        if await documents.count_ids(request.document_ids) != len(set(request.document_ids)):
            raise NotFoundError("One or more of the selected documents were not found.")
        versions = DocumentVersionRepository(self.session, self.tenant_id)
        if await versions.count_ids(request.version_ids) != len(set(request.version_ids)):
            raise NotFoundError("One or more of the selected versions were not found.")

    async def _conversation(self, request: QueryRequest) -> Conversation:
        if request.conversation_id is not None:
            conversation = await self.conversations.get(request.conversation_id)
            # Conversations are private to their author, even within a tenant.
            if conversation.user_id != self.user_id:
                raise NotFoundError()
            return conversation
        conversation = await self.conversations.add(
            Conversation(
                user_id=self.user_id,
                title=request.question[:120],
                document_ids=[str(d) for d in request.document_ids],
            )
        )
        return conversation

    async def _run_pipeline(
        self, request: QueryRequest, history: list[tuple[str, str]]
    ) -> RagAnswer:
        try:
            # Building the components is where configuration problems show up
            # (missing key, unknown RERANKER) — reported as "not configured".
            pipeline = QAPipeline(
                RetrievalService(self.resources),
                reranker_for(self.resources.settings),
                self.resources.llm(),
                self.resources.settings,
            )
            self.resources.embeddings()
        except (EmbeddingConfigError, LLMConfigError, ValueError) as exc:
            raise ServiceUnavailableError(NOT_CONFIGURED, internal_detail=repr(exc)) from exc
        try:
            return await pipeline.answer(
                request.question,
                tenant_id=str(self.tenant_id),
                document_ids=[str(d) for d in request.document_ids] or None,
                version_ids=[str(v) for v in request.version_ids] or None,
                history=history,
            )
        except (EmbeddingConfigError, LLMConfigError) as exc:  # e.g. key rejected by provider
            raise ServiceUnavailableError(NOT_CONFIGURED, internal_detail=repr(exc)) from exc
        except (
            EmbeddingError,
            LLMError,
            UnexpectedResponse,
            ResponseHandlingException,
        ) as exc:
            raise ServiceUnavailableError(UNAVAILABLE, internal_detail=repr(exc)) from exc


def _response(
    request: QueryRequest,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    result: RagAnswer,
    latency_ms: int,
) -> QueryResponse:
    return QueryResponse(
        id=message_id,
        conversation_id=conversation_id,
        question=request.question,
        answer=result.answer,
        citations=[CitationOut(**asdict(c)) for c in result.citations],
        insufficient_evidence=result.insufficient_evidence,
        cited_fraction=result.cited_fraction,
        steps=[StepOut(**asdict(s)) for s in result.steps],
        model=result.model,
        prompt_version=result.prompt_version,
        latency_ms=latency_ms,
        usage=UsageOut(
            prompt_tokens=result.prompt_tokens, completion_tokens=result.completion_tokens
        ),
    )
