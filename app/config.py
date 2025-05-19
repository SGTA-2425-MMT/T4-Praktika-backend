import os
from pydantic import AnyHttpUrl
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    MONGODB_URI: str
    # Configuración JWT
    SECRET_KEY: str = "6d67b0e232cecb398267d002b8f9995703a6f05993df3359a96c1a71495ddcbf"  # Deberías cambiar esta clave en producción
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 horas
    GROQ_API_KEY: str

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()