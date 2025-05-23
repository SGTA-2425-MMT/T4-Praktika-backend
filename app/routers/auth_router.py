from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Body, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from typing import Dict
from app.config import settings
from app.schemas import TokenResponse, ProfileUpdate, UserOut, UserCreate
from app.auth import (
    get_current_user, 
    authenticate_user, 
    create_access_token, 
    get_password_hash
)
from app.db import db

router = APIRouter(prefix="/api/auth", tags=["Auth"])

@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    user: UserCreate = None, 
    username: str = None,
    email: str = None,
    password: str = None
) -> Dict[str, str]:
    """
    Registra un nuevo usuario en la base de datos. 
    Acepta datos tanto en el cuerpo JSON como en parámetros de consulta.
    """
    # Si no hay un cuerpo UserCreate pero hay parámetros de consulta, usamos esos
    if user is None:
        if not all([username, email, password]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Se requieren los campos username, email y password"
            )
        user = UserCreate(username=username, email=email, password=password)
    
    # Verificar si el usuario ya existe
    existing_user = await db.users.find_one({"username": user.username})
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El nombre de usuario ya está en uso"
        )
        
    # Verificar si el email ya existe
    existing_email = await db.users.find_one({"email": user.email})
    if existing_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El correo electrónico ya está registrado"
        )
        
    # Crear el usuario
    hashed_password = get_password_hash(user.password)
    user_data = {
        "username": user.username,
        "email": user.email,
        "password_hash": hashed_password,
        "created_at": datetime.now(tz=timezone.utc),
        "last_login": None,
        "is_active": True
    }
    
    result = await db.users.insert_one(user_data)
    
    return {"id": str(result.inserted_id), "message": "Usuario registrado correctamente"}
    
@router.post("/token", response_model=TokenResponse)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    Autentica un usuario y devuelve un token de acceso
    """
    user = await authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nombre de usuario o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    # Crear token de acceso
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user["_id"])},
        expires_delta=access_token_expires
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60  # Convertir minutos a segundos
    }
    
@router.get("/me", response_model=UserOut)
async def get_me(current_user: dict = Depends(get_current_user)):
    """
    Devuelve información del usuario actual
    """
    return {
        "_id": str(current_user["_id"]),
        "username": current_user["username"],
        "email": current_user["email"],
        "created_at": current_user["created_at"],
        "last_login": current_user.get("last_login")
    }
    
@router.put("/me", response_model=UserOut)
async def update_me(
    profile: ProfileUpdate,
    current_user: dict = Depends(get_current_user)
):
    """
    Actualiza el perfil del usuario actual
    """
    user_id = current_user["_id"]
    update_data = {}
    
    # Solo actualizamos los campos que se proporcionan
    if profile.username is not None:
        # Verificar si el nombre de usuario ya existe
        if profile.username != current_user["username"]:
            existing_user = await db.users.find_one({"username": profile.username})
            if existing_user:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="El nombre de usuario ya está en uso"
                )
        update_data["username"] = profile.username
        
    if profile.email is not None:
        # Verificar si el correo ya existe
        if profile.email != current_user["email"]:
            existing_email = await db.users.find_one({"email": profile.email})
            if existing_email:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="El correo electrónico ya está registrado"
                )
        update_data["email"] = profile.email
    
    if update_data:
        await db.users.update_one({"_id": user_id}, {"$set": update_data})
        
    # Obtener usuario actualizado
    updated_user = await db.users.find_one({"_id": user_id})
    
    return {
        "_id": str(updated_user["_id"]),
        "username": updated_user["username"],
        "email": updated_user["email"],
        "created_at": updated_user["created_at"],
        "last_login": updated_user.get("last_login")
    }
