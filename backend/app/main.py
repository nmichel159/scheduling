from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.db.session import engine, Base
from app.api import auth # Ak si vytvoríš router v api

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

@app.get("/")
def health_check():
    return {"status": "ok"}