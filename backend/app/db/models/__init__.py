"""Import every model so `Base.metadata` is complete for Alembic autogenerate."""

from app.db.models.audit import AuditLog
from app.db.models.conversation import Conversation, Message, MessageRole
from app.db.models.document import ContractType, Document, DocumentStatus, DocumentVersion
from app.db.models.evaluation import EvaluationRun
from app.db.models.job import JobStatus, JobType, ProcessingJob
from app.db.models.organization import Organization
from app.db.models.user import User

__all__ = [
    "AuditLog",
    "ContractType",
    "Conversation",
    "Document",
    "DocumentStatus",
    "DocumentVersion",
    "EvaluationRun",
    "JobStatus",
    "JobType",
    "Message",
    "MessageRole",
    "Organization",
    "ProcessingJob",
    "User",
]
