import re
from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MattermostMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mm_post_id: str
    channel_id: str
    channel_name: Optional[str] = None
    user_id: str
    user_display_name: Optional[str] = None
    posted_at: datetime
    message: str
    post_type: Optional[str] = None
    root_id: Optional[str] = None
    edited_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class MattermostMessagePage(BaseModel):
    items: list[MattermostMessageRead]
    total: int
    limit: int
    offset: int


# Asks ------------------------------------------------------------------------

# Limits on user-supplied extraction patterns. Python's `re` has no match
# timeout, so length caps on both the pattern and the text it runs over
# bound the cost of a pathological pattern; only operators and admins
# can save one.
MAX_PATTERN_LENGTH = 200
MAX_TERMS = 20

AskScope = Literal["posts", "thread_starts", "first_per_thread"]
ExtractSource = Literal["message", "thread_title"]


class AskExtract(BaseModel):
    """Pull one value out of each result, e.g. a thread ID from its title.

    `pattern` is a regular expression; the first capture group is kept,
    or the whole match when the pattern has no group.
    """

    pattern: str = Field(min_length=1, max_length=MAX_PATTERN_LENGTH)
    source: ExtractSource = "message"

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, value: str) -> str:
        try:
            compiled = re.compile(value)
        except re.error as exc:
            raise ValueError(f"Invalid pattern: {exc}") from exc
        if compiled.groups > 1:
            raise ValueError("Use at most one capture group")
        return value


class AskSpec(BaseModel):
    """What to pull.

    `terms` must all appear; when `any_terms` is given, at least one of
    those must appear too. So "COSMOS 2589" plus any of "photometric",
    "brightness", "magnitude" is terms=["COSMOS 2589"] with those three
    as any_terms. Matching is literal and case-insensitive. At least one
    of terms, any_terms, authors or channels must narrow the pull.
    """

    model_config = ConfigDict(extra="forbid")

    terms: list[str] = Field(default_factory=list, max_length=MAX_TERMS)
    any_terms: list[str] = Field(default_factory=list, max_length=MAX_TERMS)
    authors: list[str] = Field(default_factory=list, max_length=MAX_TERMS)
    channels: list[str] = Field(default_factory=list, max_length=MAX_TERMS)
    after: Optional[date] = None
    before: Optional[date] = None
    include_archived: bool = True
    scope: AskScope = "posts"
    extract: Optional[AskExtract] = None

    @field_validator("terms", "any_terms", "authors", "channels")
    @classmethod
    def _clean(cls, values: list[str]) -> list[str]:
        cleaned = [v.strip() for v in values if v and v.strip()]
        if any(len(v) > 100 for v in cleaned):
            raise ValueError("Each entry must be 100 characters or fewer")
        return cleaned

    @model_validator(mode="after")
    def _narrowed(self) -> "AskSpec":
        if not (self.terms or self.any_terms or self.authors or self.channels):
            raise ValueError("Give at least one of terms, any_terms, authors or channels")
        if self.after and self.before and self.after > self.before:
            raise ValueError("'after' must be on or before 'before'")
        return self


class AskCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    question: Optional[str] = Field(default=None, max_length=2000)
    spec: AskSpec
    refresh_minutes: Optional[int] = Field(default=None, ge=15, le=10080)


class AskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    question: Optional[str] = None
    spec: AskSpec
    refresh_minutes: Optional[int] = None
    next_run_at: Optional[datetime] = None
    last_run_at: Optional[datetime] = None
    last_status: Optional[str] = None
    last_error: Optional[str] = None
    result_count: int = 0
    created_at: datetime
    updated_at: datetime


class AskResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    mm_post_id: str
    channel_id: str
    channel_name: Optional[str] = None
    channel_archived: bool = False
    thread_id: str
    thread_title: Optional[str] = None
    thread_started_at: Optional[datetime] = None
    author: Optional[str] = None
    posted_at: datetime
    extracted: Optional[str] = None
    excerpt: str
    permalink: Optional[str] = None


class AskResultPage(BaseModel):
    items: list[AskResultRead]
    total: int
    limit: int
    offset: int


class AskSuggestRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)


class AskSuggestion(BaseModel):
    name: str
    spec: AskSpec
    explanation: str


# Full-history jobs -------------------------------------------------------------

HistoryJobStatus = Literal["scheduled", "running", "done", "failed", "cancelled"]


class HistoryJobCreate(BaseModel):
    """Pull the full history of `channel_ids` (all of the bot's channels
    when empty), starting at `run_after` (now when omitted)."""

    channel_ids: list[str] = Field(default_factory=list, max_length=200)
    run_after: Optional[datetime] = None


class HistoryJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    channel_ids: list[str]
    run_after: datetime
    status: HistoryJobStatus
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    counts: dict[str, int] = Field(default_factory=dict)
    failed_channel_ids: list[str] = Field(default_factory=list)
    error: Optional[str] = None
    created_at: datetime


class MattermostChannelRead(BaseModel):
    id: str
    name: str
    display_name: Optional[str] = None
    type: str
    archived: bool
    history_complete: bool = False
