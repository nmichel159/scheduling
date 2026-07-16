from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.dependencies import get_current_user, get_manager_ambulance
from app.db.session import get_db
from app.models.ambulance import Ambulance
from app.models.user import User
from app.schemas.schedule import ScheduleResponse, ScheduleUpdate
from app.services.schedule_service import get_user_schedule, get_ambulance_schedule, update_ambulance_schedule

router = APIRouter()
ambulance_router = APIRouter()

@router.get("/me", response_model=list[ScheduleResponse])
def get_my_schedule(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return get_user_schedule(db, current_user.id)

@ambulance_router.get("/{ambulance_id}/schedule", response_model=list[ScheduleResponse])
def get_ambulance_schedule_endpoint(ambulance: Ambulance = Depends(get_manager_ambulance), db: Session = Depends(get_db)):
    return get_ambulance_schedule(db, ambulance.id)

@ambulance_router.put("/{ambulance_id}/schedule", response_model=list[ScheduleResponse])
def update_ambulance_schedule_endpoint(data: ScheduleUpdate, ambulance: Ambulance = Depends(get_manager_ambulance), db: Session = Depends(get_db)):
    return update_ambulance_schedule(db, ambulance.id, data)
