from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.dependencies import require_admin_role
from app.db.session import get_db
from app.models.ambulance import Ambulance
from app.models.user import User
from app.schemas.ambulance import AmbulanceCreate, AmbulanceUpdate, AmbulanceResponse

router = APIRouter()

def _active(db, urgent=None):
    query = db.query(Ambulance).filter(Ambulance.is_active.is_(True))
    if urgent is not None: query = query.filter(Ambulance.isurgent.is_(urgent))
    return query.order_by(Ambulance.name).all()

@router.get("/standard", response_model=list[AmbulanceResponse])
def get_standard_ambulances(db: Session = Depends(get_db)): return _active(db, False)

@router.get("/urgent", response_model=list[AmbulanceResponse])
def get_urgent_ambulances(db: Session = Depends(get_db)): return _active(db, True)

@router.get("", response_model=list[AmbulanceResponse])
def list_ambulances(db: Session = Depends(get_db)): return _active(db)

@router.post("", response_model=AmbulanceResponse, status_code=201)
def create_ambulance(data: AmbulanceCreate, _: User = Depends(require_admin_role), db: Session = Depends(get_db)):
    item = Ambulance(**data.model_dump()); db.add(item); db.commit(); db.refresh(item); return item

@router.put("/{ambulance_id}", response_model=AmbulanceResponse)
def update_ambulance(ambulance_id: int, data: AmbulanceUpdate, _: User = Depends(require_admin_role), db: Session = Depends(get_db)):
    item = db.query(Ambulance).filter(Ambulance.id == ambulance_id, Ambulance.is_active.is_(True)).first()
    if not item: raise HTTPException(404, "Ambulance not found")
    for key, value in data.model_dump(exclude_unset=True).items(): setattr(item, key, value)
    db.commit(); db.refresh(item); return item

@router.delete("/{ambulance_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ambulance(ambulance_id: int, _: User = Depends(require_admin_role), db: Session = Depends(get_db)):
    item = db.query(Ambulance).filter(Ambulance.id == ambulance_id, Ambulance.is_active.is_(True)).first()
    if not item: raise HTTPException(404, "Ambulance not found")
    item.is_active = False; item.managed_by_user_id = None; db.commit()

@router.put("/{ambulance_id}/manager/{manager_id}", response_model=AmbulanceResponse)
def assign_manager_to_ambulance(ambulance_id: int, manager_id: int, _: User = Depends(require_admin_role), db: Session = Depends(get_db)):
    item = db.query(Ambulance).filter(Ambulance.id == ambulance_id, Ambulance.is_active.is_(True)).first()
    manager = db.query(User).filter(User.id == manager_id, User.is_active.is_(True)).first()
    if not item or not manager: raise HTTPException(404, "Ambulance or manager not found")
    if not any(ur.role and ur.role.is_active and ur.role.level >= 2 for ur in manager.user_roles):
        raise HTTPException(400, "Assigned user must have a manager role")
    item.managed_by_user_id = manager.id; db.commit(); db.refresh(item); return item

@router.delete("/{ambulance_id}/manager", status_code=204)
def remove_manager_from_ambulance(ambulance_id: int, _: User = Depends(require_admin_role), db: Session = Depends(get_db)):
    item = db.query(Ambulance).filter(Ambulance.id == ambulance_id, Ambulance.is_active.is_(True)).first()
    if not item: raise HTTPException(404, "Ambulance not found")
    item.managed_by_user_id = None; db.commit()
