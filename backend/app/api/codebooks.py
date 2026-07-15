"""Short, resource-oriented aliases required by the public API contract."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_manager_ambulance
from app.db.session import get_db
from app.models.ambulance import Ambulance
from app.schemas.competence import CompetenceCreate, CompetenceResponse, CompetenceUpdate
from app.services.competence_service import create_competence, delete_competence, list_competences, update_competence

router = APIRouter()

@router.get("", response_model=list[CompetenceResponse])
def list_competences_alias(ambulance: Ambulance = Depends(get_manager_ambulance), db: Session = Depends(get_db)):
    return list_competences(db, ambulance.id)

@router.post("", response_model=CompetenceResponse, status_code=201)
def create_competence_alias(data: CompetenceCreate, ambulance: Ambulance = Depends(get_manager_ambulance), db: Session = Depends(get_db)):
    return create_competence(db, ambulance.id, data)

@router.put("/{competence_id}", response_model=CompetenceResponse)
def update_competence_alias(competence_id: int, data: CompetenceUpdate, ambulance: Ambulance = Depends(get_manager_ambulance), db: Session = Depends(get_db)):
    return update_competence(db, competence_id, ambulance.id, data)

@router.delete("/{competence_id}", status_code=204)
def delete_competence_alias(competence_id: int, ambulance: Ambulance = Depends(get_manager_ambulance), db: Session = Depends(get_db)):
    delete_competence(db, competence_id, ambulance.id)
