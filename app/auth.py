from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwk, jwt
from jose.utils import base64url_decode
from typing import Dict
import httpx
from app.config import settings

bearer_scheme = HTTPBearer()
_jwks: Dict = {}

async def get_jwks():
    global _jwks
    if not _jwks:
        url = f"{settings.KEYCLOAK_BASE_URL}/realms/{settings.KEYCLOAK_REALM}/protocol/openid-connect/certs"
        async with httpx.AsyncClient() as client:
            res = await client.get(url)
            res.raise_for_status()
            _jwks = res.json()
    return _jwks

async def verify_token(http_auth: HTTPAuthorizationCredentials = Security(bearer_scheme)):
    token = http_auth.credentials
    jwks = await get_jwks()
    unverified_header = jwt.get_unverified_header(token)
    kid = unverified_header.get('kid')
    key = next((key for key in jwks['keys'] if key['kid'] == kid), None)
    if not key:
        raise HTTPException(status_code=401, detail="Invalid token header")
    public_key = jwk.construct(key)
    message, encoded_signature = token.rsplit('.', 1)
    decoded_signature = base64url_decode(encoded_signature.encode('utf-8'))
    if not public_key.verify(message.encode('utf-8'), decoded_signature):
        raise HTTPException(status_code=401, detail="Signature verification failed")
    try:
        claims = jwt.decode(token, public_key, algorithms=[unverified_header['alg']], audience=settings.KEYCLOAK_CLIENT_ID, issuer=f"{settings.KEYCLOAK_BASE_URL}/realms/{settings.KEYCLOAK_REALM}")
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Token verification failed: {str(e)}")
    return claims
