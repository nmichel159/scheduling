import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import auth  # Ak si vytvoríš router v api
from app.api import unavailability
from app.api import ambulance_employee
from app.api import competence
from app.api import user_competence
from app.api import users
from app.api import roles, ambulances
from app.api import codebooks
from app.api import employee_competences
from app.api import schedules
from app.core.config import settings
import app.models  # Import all models so they are registered in Base.metadata
from app.services.audit_service import install_audit_hooks
from app.services.automatic_schedule_generation_service import (
    automatic_schedule_generation_loop,
)

# Register transactional audit hooks once for all application sessions.
install_audit_hooks()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Run the monthly schedule clock for the lifetime of this server process."""
    stop_event = asyncio.Event()
    scheduler_task = None
    if settings.AUTOMATIC_SCHEDULE_GENERATION_ENABLED:
        scheduler_task = asyncio.create_task(
            automatic_schedule_generation_loop(stop_event),
            name="automatic-monthly-schedule-generation",
        )
    try:
        yield
    finally:
        stop_event.set()
        if scheduler_task is not None:
            await scheduler_task


app = FastAPI(title="Scheduling API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.FRONTEND_ORIGINS.split(",") if origin.strip()],
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
app.include_router(users.router, prefix="/users", tags=["Users"])
app.include_router(roles.router, prefix="/roles", tags=["Roles"])
app.include_router(ambulances.router, prefix="/ambulances", tags=["Ambulances"])
app.include_router(codebooks.router, prefix="/competences", tags=["Competences"])
app.include_router(employee_competences.router, prefix="/employees/competences", tags=["Employee Competences"])
app.include_router(schedules.router, prefix="/schedules", tags=["Schedules"])
app.include_router(schedules.ambulance_router, prefix="/ambulances", tags=["Schedules"])

@app.get("/")
def health_check():
    return {"status": "ok"}
