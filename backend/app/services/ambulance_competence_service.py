"""Read and synchronize the employee competence table for an ambulance."""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.associations import UserAmbulance, UserCompetence
from app.models.competence import Competence
from app.models.user import User
from app.schemas.ambulance_competences import (
    AmbulanceEmployeeCompetenceRow,
    AmbulanceEmployeeCompetenceTableUpdate,
    CompetenceTableItem,
)


def get_employee_competence_table(
    db: Session,
    ambulance_id: int,
    after_id: int | None = None,
    limit: int | None = None,
    user_ids: set[int] | None = None,
) -> list[AmbulanceEmployeeCompetenceRow]:
    rows = _get_employee_competence_rows(
        db,
        ambulance_id,
        after_id=after_id,
        limit=limit,
        user_ids=user_ids,
    )
    employees: dict[int, AmbulanceEmployeeCompetenceRow] = {}
    for row in rows:
        employee = employees.setdefault(
            row.user_id,
            AmbulanceEmployeeCompetenceRow(
                user_id=row.user_id,
                email=row.email,
                full_name=row.full_name,
                competences=[],
            ),
        )
        if row.competence_id is not None:
            employee.competences.append(
                CompetenceTableItem(id=row.competence_id, name=row.competence_name)
            )
    return list(employees.values())


def _get_employee_competence_rows(
    db: Session,
    ambulance_id: int,
    after_id: int | None = None,
    limit: int | None = None,
    user_ids: set[int] | None = None,
) -> list:
    """Load only assignments whose competence belongs to this ambulance."""
    employee_ids_query = (
        db.query(UserAmbulance.user_id.label("user_id"))
        .join(User, User.id == UserAmbulance.user_id)
        .filter(
            UserAmbulance.ambulance_id == ambulance_id,
            UserAmbulance.is_active.is_(True),
            User.is_active.is_(True),
        )
    )
    if after_id is not None:
        employee_ids_query = employee_ids_query.filter(
            UserAmbulance.user_id > after_id
        )
    if user_ids is not None:
        if not user_ids:
            return []
        employee_ids_query = employee_ids_query.filter(
            UserAmbulance.user_id.in_(user_ids)
        )
    if after_id is not None or limit is not None:
        employee_ids_query = employee_ids_query.order_by(UserAmbulance.user_id)
    if limit is not None:
        employee_ids_query = employee_ids_query.limit(limit)
    employee_ids = employee_ids_query.subquery()

    competence_assignments = (
        db.query(
            UserCompetence.user_id.label("user_id"),
            Competence.id.label("competence_id"),
            Competence.name.label("competence_name"),
        )
        .join(Competence, Competence.id == UserCompetence.competence_id)
        .filter(
            UserCompetence.is_active.is_(True),
            Competence.ambulance_id == ambulance_id,
            Competence.is_active.is_(True),
        )
        .subquery()
    )
    rows = (
        db.query(
            employee_ids.c.user_id,
            User.email,
            User.full_name,
            competence_assignments.c.competence_id,
            competence_assignments.c.competence_name,
        )
        .select_from(employee_ids)
        .join(User, User.id == employee_ids.c.user_id)
        .outerjoin(
            competence_assignments,
            competence_assignments.c.user_id == employee_ids.c.user_id,
        )
    )
    if after_id is not None or limit is not None:
        rows = rows.order_by(
            employee_ids.c.user_id,
            competence_assignments.c.competence_name,
        )
    else:
        rows = rows.order_by(
            User.full_name,
            User.email,
            competence_assignments.c.competence_name,
        )
    rows = rows.all()
    return rows


def update_employee_competence_table(
    db: Session, ambulance_id: int, data: AmbulanceEmployeeCompetenceTableUpdate
) -> list[AmbulanceEmployeeCompetenceRow]:
    submitted_ids = {row.user_id for row in data.employees}
    employee_ids = {
        user_id for (user_id,) in db.query(UserAmbulance.user_id).filter(
            UserAmbulance.user_id.in_(submitted_ids),
            UserAmbulance.ambulance_id == ambulance_id,
            UserAmbulance.is_active.is_(True),
        ).all()
    }
    if not submitted_ids.issubset(employee_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Every submitted user must be an active employee of this ambulance.",
        )

    competence_ids = {competence_id for row in data.employees for competence_id in row.competence_ids}
    valid_ids = {
        competence_id for (competence_id,) in db.query(Competence.id).filter(
            Competence.id.in_(competence_ids),
            Competence.ambulance_id == ambulance_id,
            Competence.is_active.is_(True),
        ).all()
    }
    if competence_ids != valid_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Every competence must belong to this ambulance and be active.",
        )

    existing_by_user: dict[int, list[UserCompetence]] = {
        user_id: [] for user_id in submitted_ids
    }
    if submitted_ids:
        existing_rows = (
            db.query(UserCompetence)
            .join(Competence, UserCompetence.competence_id == Competence.id)
            .filter(
                UserCompetence.user_id.in_(submitted_ids),
                Competence.ambulance_id == ambulance_id,
            )
            .all()
        )
        for item in existing_rows:
            existing_by_user[item.user_id].append(item)

    for row in data.employees:
        desired = set(row.competence_ids)
        existing = existing_by_user[row.user_id]
        existing_ids = {item.competence_id for item in existing}
        for item in existing:
            item.is_active = item.competence_id in desired
        for competence_id in desired - existing_ids:
            item = UserCompetence(
                user_id=row.user_id,
                competence_id=competence_id,
                is_active=True,
            )
            db.add(item)
            existing.append(item)

    db.commit()
    return get_employee_competence_table(
        db,
        ambulance_id,
        user_ids=submitted_ids,
    )
