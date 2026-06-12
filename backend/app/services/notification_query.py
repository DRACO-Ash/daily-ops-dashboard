"""Read-time deduplication for notification queries.

UDL re-publishes the same logical notice multiple times: each
publication arrives as a distinct UDL `id` and lands as its own row in
the `notification` table (the ingest unique constraint is on
`udl_id`, which is correct for preserving every UDL payload). For
operator-facing views we want one row per logical notice — the
latest version.

Grouping key, in order of preference:
  1. event_id (UDL Event_Id; stable across re-publications)
  2. notso_identifier (NOTSO ticket number)
  3. udl_id (fallback so rows without either grouping field still
     pass through as themselves rather than being merged with each
     other arbitrarily)

`Notification.created_at` ties order within a group when udl_created_at
is identical or missing.
"""

from typing import Iterable, Optional

from sqlalchemy import func
from sqlalchemy.orm import aliased
from sqlalchemy.sql import Select, select

from app.models.notification import Notification


def notification_group_key():
    """SQL expression that groups multiple UDL records into one logical notice."""
    return func.coalesce(
        Notification.event_id,
        Notification.notso_identifier,
        Notification.udl_id,
    )


def deduped_notifications_select(conditions: Optional[Iterable] = None) -> Select:
    """Return a SELECT yielding the latest Notification row per logical notice.

    Uses Postgres DISTINCT ON: the ORDER BY must lead with the grouping
    key, then with the freshness columns the operator cares about.
    Wrap this in a subquery before applying user sort / pagination.
    """
    group_key = notification_group_key()
    stmt: Select = select(Notification)
    if conditions:
        stmt = stmt.where(*conditions)
    return stmt.distinct(group_key).order_by(
        group_key,
        Notification.udl_created_at.desc().nullslast(),
        Notification.created_at.desc(),
    )


def deduped_notifications_subquery(conditions: Optional[Iterable] = None):
    """Subquery convenience for callers that need to alias + paginate."""
    return deduped_notifications_select(conditions).subquery()


def aliased_deduped_notifications(conditions: Optional[Iterable] = None):
    """Return (alias, subquery) where alias is an aliased Notification mapped
    onto the deduped subquery. Use the alias for ORDER BY / column access in
    the outer query, and the subquery for COUNT."""
    subq = deduped_notifications_subquery(conditions)
    return aliased(Notification, subq), subq
