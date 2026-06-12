from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.notification import NotificationRead


class ApplicableProcedure(BaseModel):
    procedure_id: Optional[str] = None
    name: str
    reason: str


class NextAction(BaseModel):
    action: str
    urgency: str
    deadline: Optional[str] = None
    rationale: str


class StructuredEvaluation(BaseModel):
    summary: str
    applicable_procedures: list[ApplicableProcedure] = []
    next_actions: list[NextAction] = []
    open_questions: list[str] = []


class AssistantEvaluationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    notification_id: UUID
    summary: str
    structured: dict
    procedures_used: list[str]
    model: str
    error: Optional[str] = None
    evaluated_at: datetime


class AssistantFeedItem(BaseModel):
    """Dashboard row: a notification, its latest evaluation, the cross-version
    event summary, and a precomputed urgency rollup."""

    notification: NotificationRead
    evaluation: Optional[AssistantEvaluationRead] = None
    urgency: str
    top_action: Optional[str] = None
    event_summary: Optional[str] = None
    event_publication_count: Optional[int] = None
    event_key: Optional[str] = None


class AssistantFeed(BaseModel):
    items: list[AssistantFeedItem]
    window_hours: int
