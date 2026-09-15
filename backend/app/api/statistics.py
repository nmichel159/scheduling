from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import require_analyst_role
from app.db.session import get_db
from app.models.ambulance import Ambulance
from app.models.user import User
from app.schemas.statistics import YearlyStatistics
from app.services.statistics_service import get_yearly_statistics

router = APIRouter()

#: Same bounds the schedule endpoints validate years against.
MIN_YEAR = 2000
MAX_YEAR = 2100


@router.get(
    "/yearly",
    response_model=YearlyStatistics,
    summary="Hospital-wide duty statistics for one calendar year",
)
def get_yearly_statistics_endpoint(
    year: int | None = Query(
        None,
        description="Calendar year to report; defaults to the running year",
    ),
    ambulance_id: int | None = Query(
        None,
        description="Restrict every figure to one ambulance; omit for the whole hospital",
    ),
    _: User = Depends(require_analyst_role),
    db: Session = Depends(get_db),
) -> YearlyStatistics:
    """Report duties and people for one year, hospital-wide or per workplace."""
    selected_year = year if year is not None else date.today().year
    if not MIN_YEAR <= selected_year <= MAX_YEAR:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="year must be valid.",
        )
    if ambulance_id is not None:
        # 404 rather than an empty report: an unknown or retired id is a bad
        # request, not a workplace that happened to plan nothing.
        exists = (
            db.query(Ambulance.id)
            .filter(Ambulance.id == ambulance_id, Ambulance.is_active.is_(True))
            .first()
        )
        if not exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Ambulance with id {ambulance_id} not found or inactive.",
            )
    return get_yearly_statistics(db, selected_year, ambulance_id=ambulance_id)
