from __future__ import annotations

import uuid
from collections.abc import Sequence

from app.db.models import Conversation, Message, MessageRole
from app.db.repositories.base import TenantScopedRepository


class ConversationRepository(TenantScopedRepository[Conversation]):
    model = Conversation


class MessageRepository(TenantScopedRepository[Message]):
    model = Message

    async def recent_turns(self, conversation_id: uuid.UUID, turns: int) -> list[tuple[str, str]]:
        """The last `turns` (question, answer) pairs of a conversation, oldest
        first — the history sent to the LLM for follow-up questions."""
        if turns <= 0:
            return []
        stmt = (
            self._scoped()
            .where(Message.conversation_id == conversation_id)
            # A question and its answer are saved in one transaction, so they
            # share created_at. PostgreSQL orders enums by declaration
            # (USER < ASSISTANT), so role DESC puts each answer before its
            # question — the order the loop below expects.
            .order_by(Message.created_at.desc(), Message.role.desc())
            .limit(turns * 2)
        )
        recent: Sequence[Message] = (await self.session.execute(stmt)).scalars().all()
        pairs: list[tuple[str, str]] = []
        pending_answer: str | None = None
        for message in recent:  # newest first: answers come before their questions
            if message.role is MessageRole.ASSISTANT:
                pending_answer = message.content
            elif pending_answer is not None:
                pairs.append((message.content, pending_answer))
                pending_answer = None
        return list(reversed(pairs))
