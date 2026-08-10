"""Read and synchronize the employee competence table for an ambulance."""

from fastapi import HTTPException, status
from sqlalchemy import and_
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
    db: Session, ambulance_id: int
) -> list[AmbulanceEmployeeCompetenceRow]:
    rows = (
        db.query(
            UserAmbulance.user_id,
            User.email,
            User.full_name,
            Competence.id.label("competence_id"),
            Competence.name.label("competence_name"),
        )
        .join(User, User.id == UserAmbulance.user_id)
        .outerjoin(
            UserCompetence,
            and_(
                UserCompetence.user_id == UserAmbulance.user_id,
                UserCompetence.is_active.is_(True),
            ),
        )
        .outerjoin(
            Competence,
            and_(
                Competence.id == UserCompetence.competence_id,
                Competence.ambulance_id == ambulance_id,
                Competence.is_active.is_(True),
            ),
        )
        .filter(
            UserAmbulance.ambulance_id == ambulance_id,
            UserAmbulance.is_active.is_(True),
            User.is_active.is_(True),
        )
        .order_by(User.full_name, User.email, Competence.name)
        .all()
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


def update_employee_competence_table(
    db: Session, ambulance_id: int, data: AmbulanceEmployeeCompetenceTableUpdate
) -> list[AmbulanceEmployeeCompetenceRow]:
    employee_ids = {
        user_id for (user_id,) in db.query(UserAmbulance.user_id).filter(
            UserAmbulance.ambulance_id == ambulance_id,
            UserAmbulance.is_active.is_(True),
        ).all()
    }
    submitted_ids = {row.user_id for row in data.employees}
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

    for row in data.employees:
        desired = set(row.competence_ids)
        existing = (
            db.query(UserCompetence)
            .join(Competence, UserCompetence.competence_id == Competence.id)
            .filter(
                UserCompetence.user_id == row.user_id,
                Competence.ambulance_id == ambulance_id,
            )
            .all()
        )
        existing_ids = {item.competence_id for item in existing}
        for item in existing:
            item.is_active = item.competence_id in desired
        for competence_id in desired - existing_ids:
            db.add(UserCompetence(user_id=row.user_id, competence_id=competence_id, is_active=True))

    db.commit()
    return get_employee_competence_table(db, ambulance_id)
