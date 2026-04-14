import os
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker, Session

# 1. DYNAMICKÁ KONFIGURÁCIA
# os.getenv hľadá premennú v systéme. 
# Ak ju nenájde (napr. bežíš lokálne bez Dockeru), použije tú druhú hodnotu ako zálohu.
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql://postgres:password@localhost:5432/appdb"
)

# Render niekedy posiela URL začínajúcu na "postgres://", 
# ale SQLAlchemy vyžaduje "postgresql://". Toto je dôležitý fix pre produkciu:
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# 2. MODELY
class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    text = Column(String, index=True)

# Inicializácia databázy
Base.metadata.create_all(bind=engine)

# 3. FASTAPI APLIKÁCIA
app = FastAPI(title="Scheduling API")

# DYNAMICKÝ CORS
# V produkcii budeš chcieť povoliť tvoju adresu z Vercelu.
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# DEPENDENCY
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 4. ENDPOINTY
@app.get("/message")
def read_message(db: Session = Depends(get_db)):
    msg = db.query(Message).first()
    if msg is None:
        return {"message": "No data found"}
    return {"message": msg.text}