import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException

from .config import settings
from .db import AsyncSessionLocal, init_db
from .redis_client import get_redis
from .repositories.users_repo import (
    create_user,
    get_user_by_email,
    get_user_by_id,
    get_user_by_identifier,
    get_user_by_username,
)
from .schemas import (
    MeRequest,
    MeResponse,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    SignupRequest,
    TokenResponse,
    VerifyRequest,
    VerifyResponse,
)
from .security import (
    AuthError,
    blacklist_access_token,
    consume_refresh_token,
    create_access_token,
    hash_password,
    is_blacklisted,
    issue_refresh_token,
    revoke_refresh_token,
    verify_access_token,
    verify_password,
)
from .seed import seed_default_user_if_empty

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("auth-service")


def require_internal_service_key(x_service_key: str = Header(default="")) -> None:
    if x_service_key != settings.internal_service_key:
        raise HTTPException(status_code=403, detail="Invalid internal service key")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    app.state.redis = await get_redis()
    async with AsyncSessionLocal() as session:
        await seed_default_user_if_empty(session)
    logger.info("[App] Users table ready. Redis connected.")
    yield
    await app.state.redis.aclose()
    logger.info("[App] Shutdown complete.")


app = FastAPI(
    title="Auth Service",
    description="Servicio interno de autenticacion y validacion de tokens.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/", tags=["Health"])
async def root():
    return {"service": "auth-service", "status": "ok", "version": "1.0.0"}


@app.post(
    "/internal/auth/signup",
    response_model=TokenResponse,
    tags=["Internal"],
    summary="Registra un usuario y emite tokens",
)
async def internal_signup(
    payload: SignupRequest,
    _: None = Depends(require_internal_service_key),
):
    async with AsyncSessionLocal() as session:
        existing_username = await get_user_by_username(session, payload.username)
        if existing_username:
            raise HTTPException(status_code=409, detail="Username ya existe")

        existing_email = await get_user_by_email(session, payload.email)
        if existing_email:
            raise HTTPException(status_code=409, detail="Email ya existe")

        user = await create_user(
            session,
            username=payload.username,
            email=payload.email,
            password_hash=hash_password(payload.password),
            role=payload.role,
        )

    access_token = create_access_token(
        user_id=user.user_id,
        role=user.role,
        secret_key=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        expires_minutes=settings.jwt_access_token_minutes,
    )
    refresh_token = await issue_refresh_token(
        app.state.redis,
        user_id=user.user_id,
        refresh_days=settings.jwt_refresh_token_days,
    )
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.jwt_access_token_minutes * 60,
        role=user.role,
    )


@app.post(
    "/internal/auth/login",
    response_model=TokenResponse,
    tags=["Internal"],
    summary="Valida credenciales y emite tokens",
)
async def internal_login(
    payload: LoginRequest,
    _: None = Depends(require_internal_service_key),
):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_identifier(session, payload.username)

    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Credenciales invalidas")

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Credenciales invalidas")

    access_token = create_access_token(
        user_id=user.user_id,
        role=user.role,
        secret_key=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        expires_minutes=settings.jwt_access_token_minutes,
    )
    refresh_token = await issue_refresh_token(
        app.state.redis,
        user_id=user.user_id,
        refresh_days=settings.jwt_refresh_token_days,
    )
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.jwt_access_token_minutes * 60,
        role=user.role,
    )


@app.post(
    "/internal/auth/refresh",
    response_model=TokenResponse,
    tags=["Internal"],
    summary="Rota refresh token y emite nuevo access token",
)
async def internal_refresh(
    payload: RefreshRequest,
    _: None = Depends(require_internal_service_key),
):
    user_id = await consume_refresh_token(app.state.redis, payload.refresh_token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Refresh token invalido o expirado")

    async with AsyncSessionLocal() as session:
        user = await get_user_by_id(session, user_id)

    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Usuario no encontrado o inactivo")

    access_token = create_access_token(
        user_id=user.user_id,
        role=user.role,
        secret_key=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        expires_minutes=settings.jwt_access_token_minutes,
    )
    refresh_token = await issue_refresh_token(
        app.state.redis,
        user_id=user.user_id,
        refresh_days=settings.jwt_refresh_token_days,
    )
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.jwt_access_token_minutes * 60,
        role=user.role,
    )


@app.post(
    "/internal/auth/verify",
    response_model=VerifyResponse,
    tags=["Internal"],
    summary="Valida access token y devuelve user context",
)
async def internal_verify(
    payload: VerifyRequest,
    _: None = Depends(require_internal_service_key),
):
    try:
        token_payload = verify_access_token(
            payload.access_token,
            secret_key=settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=exc.detail) from exc

    jti = token_payload.get("jti", "")
    if await is_blacklisted(app.state.redis, jti):
        raise HTTPException(status_code=401, detail="Token revocado")

    async with AsyncSessionLocal() as session:
        user = await get_user_by_id(session, token_payload["sub"])

    if not user or not user.is_active:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    return VerifyResponse(
        user_id=token_payload["sub"],
        username=user.username,
        role=user.role,
        jti=jti,
        exp=int(token_payload.get("exp", 0)),
    )


@app.post(
    "/internal/auth/logout",
    tags=["Internal"],
    summary="Revoca access token y opcionalmente refresh token",
)
async def internal_logout(
    payload: LogoutRequest,
    _: None = Depends(require_internal_service_key),
):
    try:
        token_payload = verify_access_token(
            payload.access_token,
            secret_key=settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
        await blacklist_access_token(app.state.redis, token_payload)
    except AuthError:
        # No filtramos si el token ya expiro o era invalido.
        pass

    if payload.refresh_token:
        await revoke_refresh_token(app.state.redis, payload.refresh_token)

    return {"status": "ok"}


@app.post(
    "/internal/auth/me",
    response_model=MeResponse,
    tags=["Internal"],
    summary="Retorna perfil del usuario autenticado",
)
async def internal_me(
    payload: MeRequest,
    _: None = Depends(require_internal_service_key),
):
    try:
        token_payload = verify_access_token(
            payload.access_token,
            secret_key=settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=exc.detail) from exc

    jti = token_payload.get("jti", "")
    if await is_blacklisted(app.state.redis, jti):
        raise HTTPException(status_code=401, detail="Token revocado")

    async with AsyncSessionLocal() as session:
        user = await get_user_by_id(session, token_payload["sub"])

    if not user or not user.is_active:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    return MeResponse(
        user_id=user.user_id, username=user.username, email=user.email, role=user.role
    )
