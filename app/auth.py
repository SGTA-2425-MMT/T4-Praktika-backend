from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwk, jwt
from jose.utils import base64url_decode
import httpx
from typing import Dict, Any, Union
from app.config import settings

bearer_scheme = HTTPBearer()
_jwks: Dict[str, Any] = {}

async def get_jwks():
    global _jwks
    if not _jwks:
        url = (
            f"{settings.KEYCLOAK_BASE_URL}/realms/"
            f"{settings.KEYCLOAK_REALM}/protocol/openid-connect/certs"
        )
        async with httpx.AsyncClient() as client:
            res = await client.get(url)
            res.raise_for_status()
            _jwks = res.json()
    return _jwks

async def verify_token(
    http_auth: HTTPAuthorizationCredentials = Security(bearer_scheme)
):
    token = http_auth.credentials
    jwks = await get_jwks()

    # ——— Signature verification ———
    unverified_header = jwt.get_unverified_header(token)
    kid = unverified_header["kid"]
    key_dict = next((k for k in jwks["keys"] if k["kid"] == kid), None)
    if not key_dict:
        raise HTTPException(status_code=401, detail="Invalid token header")
    public_key = jwk.construct(key_dict)
    message, encoded_sig = token.rsplit(".", 1)
    decoded_sig = base64url_decode(encoded_sig.encode('utf-8'))
    if not public_key.verify(message.encode(), decoded_sig):
        raise HTTPException(status_code=401, detail="Signature verification failed")

    unverified_claims = jwt.get_unverified_claims(token)
    actual_aud = unverified_claims.get("aud")
    if not isinstance(actual_aud, str):
        if isinstance(actual_aud, (list, tuple)) and actual_aud:
            actual_aud = actual_aud[0]
        else:
            raise HTTPException(status_code=401, detail="Token missing audience")

    actual_iss = unverified_claims.get("iss")
    if not isinstance(actual_iss, str):
        if isinstance(actual_iss, (list, tuple)) and actual_iss:
            actual_iss = actual_iss[0]
        else:
            raise HTTPException(status_code=401, detail="Token missing issuer")

    # ——— Decode without audience check ———
    try:
        claims = jwt.decode(
            token,
            public_key,
            algorithms=[unverified_header["alg"]],
            audience=actual_aud,
            issuer=actual_iss,
            options={
                "verify_signature": True,
                "verify_aud": False,
                "exp": True
            }
        )
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Token verification failed: {e}")

    # 3) Manual audience check
    aud: Union[str, list] = claims.get("aud")
    valid_aud = settings.KEYCLOAK_CLIENT_ID
    if isinstance(aud, list):
        if valid_aud not in aud:
            raise HTTPException(
                status_code=401,
                detail=(
                    f"Invalid audience: {aud}. Expected: {valid_aud}. "
                    "You are using a token issued for the 'account' client. "
                    "To fix: "
                    "1) Make sure you authenticate against your application client (client_id: civilizatu-frontend-stable) in Keycloak, "
                    "not the 'account' client. "
                    "2) If using Postman or similar, set the correct client_id in the OAuth2 flow. "
                    "3) If using a frontend, ensure it requests tokens for the correct client."
                )
            )
    else:
        if aud != valid_aud:
            raise HTTPException(
                status_code=401,
                detail=(
                    f"Invalid audience: {aud}. Expected: {valid_aud}. "
                    "You are using a token issued for the 'account' client. "
                    "To fix: "
                    "1) Make sure you authenticate against your application client (client_id: civilizatu-frontend-stable) in Keycloak, "
                    "not the 'account' client. "
                    "2) If using Postman or similar, set the correct client_id in the OAuth2 flow. "
                    "3) If using a frontend, ensure it requests tokens for the correct client."
                )
            )

    return {**claims, "token": token}
