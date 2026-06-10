from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


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
