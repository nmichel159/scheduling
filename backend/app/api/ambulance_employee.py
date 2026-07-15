"""
FastAPI router for Ambulance Employee Management endpoints.

All endpoints require Role Level >= 2 and verify that the
authenticated manager owns the target ambulance.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_manager_ambulance
from app.db.session import get_db
from app.models.ambulance import Ambulance
from app.schemas.ambulance_employee import (
    AmbulanceListResponse,
    AmbulanceEmployeeAdd,
    AmbulanceEmployeeResponse,
    EmployeeListResponse,
)
from app.schemas.ambulance_competences import (
    AmbulanceEmployeeCompetenceRow,
    AmbulanceEmployeeCompetenceTableUpdate,
)
from app.services.ambulance_employee_service import (
    add_employee,
    list_employee_ambulances,
    list_employees,
    list_manager_ambulances,
    remove_employee,
)
from app.services.ambulance_competence_service import (
    get_employee_competence_table,
    update_employee_competence_table,
)

router = APIRouter()


@router.get(
    "/{ambulance_id}/employees/competences",
    response_model=list[AmbulanceEmployeeCompetenceRow],
    summary="List employees and their competences for an ambulance",
)
def list_employee_competence_table(
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
):
    return get_employee_competence_table(db, ambulance.id)


@router.put(
    "/{ambulance_id}/employees/competences",
    response_model=list[AmbulanceEmployeeCompetenceRow],
    summary="Replace employee competences for an ambulance",
)
def update_employee_competence_table_endpoint(
    data: AmbulanceEmployeeCompetenceTableUpdate,
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
):
    return update_employee_competence_table(db, ambulance.id, data)


@router.get(
    "/employees/{user_id}/ambulances",
    response_model=list[AmbulanceListResponse],
    summary="List ambulances where an employee works",
)
def list_employee_ambulances_endpoint(
    user_id: int,
    db: Session = Depends(get_db),
) -> list[AmbulanceListResponse]:
    """Retrieve all active ambulances assigned to an employee."""
    return list_employee_ambulances(db, user_id)


@router.get(
    "/managers/{user_id}/ambulances",
    response_model=list[AmbulanceListResponse],
    summary="List ambulances managed by a user",
)
def list_manager_ambulances_endpoint(
    user_id: int,
    db: Session = Depends(get_db),
) -> list[AmbulanceListResponse]:
    """Retrieve all active ambulances where the user is the manager."""
    return list_manager_ambulances(db, user_id)

@router.get("/me/managed", response_model=list[AmbulanceListResponse])
def my_managed_ambulances(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    return list_manager_ambulances(db, current_user.id)

@router.get("/me/assigned", response_model=list[AmbulanceListResponse])
def my_assigned_ambulances(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    return list_employee_ambulances(db, current_user.id)


@router.get(
    "/{ambulance_id}/employees",
    response_model=list[EmployeeListResponse],
    summary="List employees assigned to an ambulance",
)
def list_employees_endpoint(
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> list[EmployeeListResponse]:
    """Retrieve all active employees assigned to the manager's ambulance."""
    return list_employees(db, ambulance.id)


@router.post(
    "/{ambulance_id}/employees",
    response_model=AmbulanceEmployeeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add an employee to an ambulance",
)
def add_employee_endpoint(
    data: AmbulanceEmployeeAdd,
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> AmbulanceEmployeeResponse:
    """Assign an employee to the manager's ambulance."""
    return add_employee(db, ambulance.id, data.user_id)


@router.delete(
    "/{ambulance_id}/employees/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove an employee from an ambulance",
)
def remove_employee_endpoint(
    user_id: int,
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> None:
    """Remove an employee from the manager's ambulance."""
    remove_employee(db, ambulance.id, user_id)
