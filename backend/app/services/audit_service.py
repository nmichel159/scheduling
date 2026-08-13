"""Transactional audit hooks for authenticated ORM writes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.models.audit import AuditLog


AUDIT_ACTOR_KEY = "audit_actor_user_id"
_AUDIT_PENDING_KEY = "audit_pending_changes"
_AUDIT_HOOKS_INSTALLED = False


@dataclass(frozen=True)
class _PendingAudit:
    """Describe one ORM change until generated primary keys are available."""

    instance: Any
    action: str
    entity_type: str
    fields: tuple[str, ...]


def _changed_column_names(instance: Any, *, creating: bool = False) -> tuple[str, ...]:
    """Return column names only; audit rows never duplicate business values."""
    state = inspect(instance)
    if creating:
        return tuple(
            sorted(
                attribute.key
                for attribute in state.mapper.column_attrs
                if getattr(instance, attribute.key, None) is not None
            )
        )
    return tuple(
        sorted(
            attribute.key
            for attribute in state.mapper.column_attrs
            if state.attrs[attribute.key].history.has_changes()
        )
    )


def _entity_id(instance: Any) -> str:
    """Serialize a simple or composite ORM primary key deterministically."""
    state = inspect(instance)
    values = [getattr(instance, column.key, None) for column in state.mapper.primary_key]
    return ":".join(str(value) for value in values)


def _collect_audit_changes(session: Session, _flush_context: Any, _instances: Any) -> None:
    """Collect authenticated ORM mutations before SQL is emitted."""
    actor_user_id = session.info.get(AUDIT_ACTOR_KEY)
    if actor_user_id is None:
        return

    pending: list[_PendingAudit] = []
    for instance in session.new:
        if isinstance(instance, AuditLog):
            continue
        state = inspect(instance)
        pending.append(
            _PendingAudit(
                instance=instance,
                action="CREATE",
                entity_type=state.mapper.local_table.name,
                fields=_changed_column_names(instance, creating=True),
            )
        )
    for instance in session.dirty:
        if isinstance(instance, AuditLog) or not session.is_modified(
            instance,
            include_collections=False,
        ):
            continue
        state = inspect(instance)
        pending.append(
            _PendingAudit(
                instance=instance,
                action="UPDATE",
                entity_type=state.mapper.local_table.name,
                fields=_changed_column_names(instance),
            )
        )
    for instance in session.deleted:
        if isinstance(instance, AuditLog):
            continue
        state = inspect(instance)
        pending.append(
            _PendingAudit(
                instance=instance,
                action="DELETE",
                entity_type=state.mapper.local_table.name,
                fields=(),
            )
        )

    if pending:
        session.info.setdefault(_AUDIT_PENDING_KEY, []).extend(pending)


def _write_audit_changes(session: Session, _flush_context: Any) -> None:
    """Add audit records after generated primary keys become available."""
    pending: list[_PendingAudit] = session.info.pop(_AUDIT_PENDING_KEY, [])
    actor_user_id = session.info.get(AUDIT_ACTOR_KEY)
    if not pending or actor_user_id is None:
        return

    session.add_all(
        AuditLog(
            user_id=actor_user_id,
            action=item.action,
            entity_type=item.entity_type,
            entity_id=_entity_id(item.instance),
            changes={"fields": list(item.fields)},
        )
        for item in pending
    )


def install_audit_hooks() -> None:
    """Install idempotent SQLAlchemy hooks; audit rows share the write transaction."""
    global _AUDIT_HOOKS_INSTALLED
    if _AUDIT_HOOKS_INSTALLED:
        return
    event.listen(Session, "before_flush", _collect_audit_changes)
    event.listen(Session, "after_flush_postexec", _write_audit_changes)
    _AUDIT_HOOKS_INSTALLED = True
