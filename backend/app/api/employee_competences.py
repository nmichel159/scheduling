from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.dependencies import get_manager_ambulance
from app.db.session import get_db
from app.models.ambulance import Ambulance
from app.schemas.user_competence import UserCompetenceAssign, UserCompetenceResponse
from app.services.user_competence_service import assign_competence, list_user_competences, remove_competence

router = APIRouter()

@router.get("", response_model=list[UserCompetenceResponse])
def list_employee_competences(user_id: int = Query(...), ambulance: Ambulance = Depends(get_manager_ambulance), db: Session = Depends(get_db)):
    return list_user_competences(db, ambulance.id, user_id)

@router.post("", response_model=UserCompetenceResponse, status_code=201)
def assign_employee_competence(data: UserCompetenceAssign, user_id: int = Query(...), ambulance: Ambulance = Depends(get_manager_ambulance), db: Session = Depends(get_db)):
    return assign_competence(db, ambulance.id, user_id, data.competence_id)

@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def remove_employee_competence(user_id: int = Query(...), competence_id: int = Query(...), ambulance: Ambulance = Depends(get_manager_ambulance), db: Session = Depends(get_db)):
    remove_competence(db, ambulance.id, user_id, competence_id)
