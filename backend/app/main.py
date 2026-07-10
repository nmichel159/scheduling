from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.db.session import engine, Base
from app.api import auth  # Ak si vytvoríš router v api
from app.api import unavailability
from app.api import ambulance_employee
from app.api import competence
from app.api import user_competence
import app.models  # Import all models so they are registered in Base.metadata

# Vytvorenie tabuliek pri štarte
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Scheduling API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pripojenie routerov
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(unavailability.router, prefix="/unavailabilities", tags=["Unavailabilities"])
app.include_router(ambulance_employee.router, prefix="/ambulances", tags=["Ambulance Employees"])
app.include_router(competence.router, prefix="/ambulances", tags=["Competences"])
app.include_router(user_competence.router, prefix="/ambulances", tags=["User Competences"])

@app.get("/")
def health_check():
    return {"status": "ok"}