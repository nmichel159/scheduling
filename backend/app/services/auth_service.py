import requests
from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.models.user import User

def authenticate_google_user(db: Session, token: str):
    # 1. Overenie u Google
    res = requests.get(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {token}"}
    )
    if res.status_code != 200:
        raise HTTPException(status_code=400, detail="Invalid Google token")
    
    info = res.json()
    
    # 2. SQL UPSERT
    user = db.query(User).filter(User.email == info['email']).first()
    
    if not user:
        user = User(
            email=info['email'],
            full_name=info.get('name'),
            google_id=info.get('sub'),
            picture_url=info.get('picture'),
            login_count=1
        )
        db.add(user)
    else:
        user.login_count += 1
        user.picture_url = info.get('picture')

    db.commit()
    db.refresh(user)
    return user