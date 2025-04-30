from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from typing import Any
import httpx
from app.config import settings
from app.schemas import TokenRequest, TokenResponse, ProfileUpdate, UserOut
from app.auth import verify_token

router = APIRouter(prefix="/api/auth", tags=["Auth"])


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    username: str,
    email: str,
    password: str,
) -> Any:
    """
    1) Fetch an admin access_token from Keycloak
    2) Create a new Keycloak user
    """
    # Ensure no trailing slash in KEYCLOAK_BASE_URL
    base_url = str(settings.KEYCLOAK_BASE_URL).rstrip('/')

    # 1. get admin token
    token_url = (
        f"{base_url}/realms/"
        f"{settings.KEYCLOAK_REALM}/protocol/openid-connect/token"
    )
    data = {
        "grant_type": "client_credentials",
        "client_id": settings.KEYCLOAK_ADMIN_CLIENT_ID,
        "client_secret": settings.KEYCLOAK_ADMIN_CLIENT_SECRET,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(token_url, data=data)
        if resp.status_code != 200:
            detail = (
                f"Failed to get admin token: {resp.text} "
                f"(status {resp.status_code}). "
            )
            raise HTTPException(
                status_code=resp.status_code,
                detail=detail
            )
        admin_token = resp.json()["access_token"]

    # 2. create the user
    user_url = (
        f"{base_url}/admin/realms/"
        f"{settings.KEYCLOAK_REALM}/users"
    )
    payload = {
        "username": username,
        "email": email,
        "enabled": True,
        "credentials": [
            {"type": "password", "value": password, "temporary": False}
        ],
    }
    headers = {"Authorization": f"Bearer {admin_token}"}

    async with httpx.AsyncClient() as client:
        resp = await client.post(user_url, json=payload, headers=headers)
        if resp.status_code != 201:
            detail = (
                f"Failed to create user: {resp.text} "
                f"(status {resp.status_code}). "
            )
            raise HTTPException(
                status_code=resp.status_code, detail=detail
            )

        # Get the user id from the Location header
        location = resp.headers.get("Location")
        user_id = None
        if location:
            user_id = location.rstrip('/').split('/')[-1]
        if not user_id:
            # fallback: try to get user by username
            search_url = (
                f"{base_url}/admin/realms/"
                f"{settings.KEYCLOAK_REALM}/users?username={username}"
            )
            search_resp = await client.get(search_url, headers=headers)
            if search_resp.status_code == 200 and search_resp.json():
                user_id = search_resp.json()[0].get("id")

        # Send verification email if user_id found
        if user_id:
            verify_url = (
                f"{base_url}/admin/realms/"
                f"{settings.KEYCLOAK_REALM}/users/{user_id}/send-verify-email"
            )
            verify_resp = await client.put(verify_url, headers=headers)
            if verify_resp.status_code not in (204, 202):
                # Not fatal, but log/send info if needed
                pass

    return {"message": "user created"}


@router.post("/login", response_model=TokenResponse)
async def login(form_data: TokenRequest):
    """
    Password-grant against Keycloak’s token endpoint.
    """
    token_url = (
        f"{settings.KEYCLOAK_BASE_URL}/realms/"
        f"{settings.KEYCLOAK_REALM}/protocol/openid-connect/token"
    )
    data = {
        "grant_type": "password",
        "client_id": settings.KEYCLOAK_CLIENT_ID,
        "client_secret": settings.KEYCLOAK_CLIENT_SECRET,
        "username": form_data.username,
        "password": form_data.password,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(token_url, data=data)
        if resp.status_code != 200:
            detail = (
                f"Failed to login: {resp.text} "
                f"(status {resp.status_code}). "
            )
            raise HTTPException(
                status_code=resp.status_code, detail=detail
            )
        return resp.json()


@router.get("/profile", response_model=UserOut)
async def get_profile(claims: dict = Depends(verify_token)):
    """
    Call Keycloak’s userinfo endpoint and return the core fields.
    """
    url = (
        f"{settings.KEYCLOAK_BASE_URL}realms/"
        f"{settings.KEYCLOAK_REALM}/protocol/openid-connect/userinfo"
    )
    print(claims)
    headers = {"Authorization": f"Bearer {claims['token']}"}
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        info = resp.json()

    return {
        "_id": info["sub"],
        "username": info.get("preferred_username"),
        "email": info.get("email"),
        "created_at": None,
        "last_login": None,
    }


@router.put("/profile", response_model=UserOut)
async def update_profile(
    update: ProfileUpdate, claims: dict = Depends(verify_token)
):
    """
    Update Keycloak user via Admin API.
    """
    # 1) get admin token (same as in register)
    token_url = (
        f"{settings.KEYCLOAK_BASE_URL}/realms/"
        f"{settings.KEYCLOAK_REALM}/protocol/openid-connect/token"
    )
    data = {
        "grant_type": "client_credentials",
        "client_id": settings.KEYCLOAK_ADMIN_CLIENT_ID,
        "client_secret": settings.KEYCLOAK_ADMIN_CLIENT_SECRET,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(token_url, data=data)
        resp.raise_for_status()
        admin_token = resp.json()["access_token"]

    # 2) patch the user
    headers = {"Authorization": f"Bearer {admin_token}"}
    user_id = claims["sub"]

    if update.username or update.email:
        payload = {}
        if update.username:
            payload['username'] = update.username
        if update.email:
            payload['email'] = update.email

    user_url = (
        f"{settings.KEYCLOAK_BASE_URL}/admin/realms/"
        f"{settings.KEYCLOAK_REALM}/users/{user_id}"
    )

    async with httpx.AsyncClient() as client:
        resp = await client.put(user_url, json=payload, headers=headers)
        resp.raise_for_status()

    # Return updated info
    return await get_profile(claims)