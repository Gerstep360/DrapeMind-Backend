from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models import Role, User, UserStatus
from app.schemas.api import LoginRequest, RegisterRequest, TokenResponse, UserOut

router = APIRouter()


def _authenticate(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(func.lower(User.email) == email.lower()))
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Email o contrasena incorrectos")
    if user.estado != UserStatus.ACTIVO:
        raise HTTPException(status_code=403, detail="La cuenta no esta activa")
    return user


def _token(user: User) -> TokenResponse:
    token, expires_in = create_access_token(user.id, user.rol.value)
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.post(
    "/register", response_model=UserOut, status_code=status.HTTP_201_CREATED,
    summary="Registrar cliente", description="CU-01. Crea una cuenta con rol CLIENTE; nunca acepta un rol desde el cliente.",
)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> User:
    user = User(
        nombre=payload.nombre.strip(), email=str(payload.email).lower(),
        password_hash=hash_password(payload.password), telefono=payload.telefono,
        rol=Role.CLIENTE, estado=UserStatus.ACTIVO,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "El email ya esta registrado") from exc
    db.refresh(user)
    return user


@router.post(
    "/login", response_model=TokenResponse, summary="Iniciar sesion (JSON)",
    description="CU-02. Login para Flutter/Angular con email y contrasena; devuelve JWT Bearer.",
)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    return _token(_authenticate(db, str(payload.email), payload.password))


@router.post(
    "/token", response_model=TokenResponse, summary="Iniciar sesion OAuth2",
    description="Variante OAuth2 para el boton Authorize de Swagger. username corresponde al email.",
)
def oauth_token(
    form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
) -> TokenResponse:
    return _token(_authenticate(db, form.username, form.password))


@router.get("/me", response_model=UserOut, summary="Consultar usuario autenticado")
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
