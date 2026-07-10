"""
FastAPI router for Ambulance Employee Management endpoints.

All endpoints require Role Level >= 2 and verify that the
authenticated manager owns the target ambulance.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_manager_ambulance
from app.db.session import get_db
from app.models.ambulance import Ambulance
from app.schemas.ambulance_employee import (
    AmbulanceEmployeeAdd,
    AmbulanceEmployeeResponse,
    EmployeeListResponse,
)
from app.services.ambulance_employee_service import (
    add_employee,
    list_employees,
    remove_employee,
)

router = APIRouter()


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
