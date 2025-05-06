import os
from pydantic import AnyHttpUrl
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    MONGODB_URI: str
    KEYCLOAK_BASE_URL: AnyHttpUrl
    KEYCLOAK_REALM: str
    KEYCLOAK_CLIENT_ID: str
    KEYCLOAK_CLIENT_SECRET: str
    # For admin API (registration and user management)
    KEYCLOAK_ADMIN_CLIENT_ID: str
    KEYCLOAK_ADMIN_CLIENT_SECRET: str
    GROQ_API_KEY: str

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()