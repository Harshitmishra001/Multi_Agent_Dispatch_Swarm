from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt as _bcrypt
from fastapi import Depends, HTTPException, status, APIRouter
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from backend.config.settings import settings
from backend.db.models import DBUser, SessionLocal


# ---------------------------------------------------------------------------
# Password helpers — using bcrypt directly (passlib 1.7.4 is incompatible
# with bcrypt 4.x/5.x due to the 72-byte wrap-bug detection failure).
# ---------------------------------------------------------------------------

def _hash_password(password: str) -> str:
    """Hash a plain-text password with bcrypt."""
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def _verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain-text password against a stored bcrypt hash."""
    return _bcrypt.checkpw(plain.encode(), hashed.encode())


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/token")


# Single canonical DB dependency — also used by routes.py so a single
# FastAPI dependency_override in tests covers the whole chain.
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        username: str = payload.get("sub")
        role: str = payload.get("role")
        if not username or not role:
            raise exc
    except JWTError:
        raise exc
    user = db.query(DBUser).filter(DBUser.username == username).first()
    if user is None:
        raise exc
    return {"username": user.username, "role": user.role}


async def get_current_reviewer(current_user: dict = Depends(get_current_user)):
    if current_user["role"] not in ("reviewer", "admin"):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return current_user


async def get_current_admin(current_user: dict = Depends(get_current_user)):
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin permissions required")
    return current_user


# ---------- /token endpoint ----------
auth_router = APIRouter()

@auth_router.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(DBUser).filter(DBUser.username == form_data.username).first()
    if not user or not _verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token({"sub": user.username, "role": user.role})
    return {"access_token": token, "token_type": "bearer"}
