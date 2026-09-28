"""FastAPI router for the scheduling rules of a workplace.

The rules and their defaults are code; what these endpoints read and write
is one workplace's choices among them. They belong to whoever schedules the
workplace, so reads and writes alike are scoped by ``get_manager_ambulance``.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_manager_ambulance
from app.db.session import get_db
from app.models.ambulance import Ambulance
from app.schemas.constraint_setting import (
    ConstraintSettingEntry,
    ConstraintSettingList,
    ConstraintSettingUpdate,
)
from app.services.constraint_setting_service import (
    ConstraintSettingError,
    constraint_entries,
    reset_constraint_settings,
    save_constraint_settings,
)

router = APIRouter()


def _list_response(db: Session, ambulance_id: int) -> ConstraintSettingList:
    return ConstraintSettingList(
        ambulance_id=ambulance_id,
        entries=[
            ConstraintSettingEntry(**entry)
            for entry in constraint_entries(db, ambulance_id)
        ],
    )


@router.get(
    "/{ambulance_id}/constraints",
    response_model=ConstraintSettingList,
    summary="Every scheduling rule of a workplace",
)
def list_constraint_settings_endpoint(
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> ConstraintSettingList:
    """List every rule with the workplace's setting and the default."""
    return _list_response(db, ambulance.id)


@router.put(
    "/{ambulance_id}/constraints",
    response_model=ConstraintSettingList,
    summary="Set how strictly the workplace applies its rules",
)
def update_constraint_settings_endpoint(
    data: ConstraintSettingUpdate,
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> ConstraintSettingList:
    """Store the named rules' settings; a refused one leaves all unchanged."""
    try:
        save_constraint_settings(
            db,
            ambulance.id,
            [(entry.code, entry.is_strict, entry.weight) for entry in data.entries],
        )
    except ConstraintSettingError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    return _list_response(db, ambulance.id)


@router.delete(
    "/{ambulance_id}/constraints",
    response_model=ConstraintSettingList,
    summary="Hand every rule of the workplace back to its default",
)
def reset_constraint_settings_endpoint(
    ambulance: Ambulance = Depends(get_manager_ambulance),
    db: Session = Depends(get_db),
) -> ConstraintSettingList:
    """Forget everything the workplace set."""
    reset_constraint_settings(db, ambulance.id)
    return _list_response(db, ambulance.id)
