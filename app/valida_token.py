from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from firebase_admin import auth

security = HTTPBearer()
security_opcional = HTTPBearer(auto_error=False)


def _decodificar_token(token: str) -> dict:
    try:
        return auth.verify_id_token(
            token,
            check_revoked=False,
            clock_skew_seconds=60
        )

    except auth.ExpiredIdTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="O token de acesso expirou.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except auth.InvalidIdTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token do Firebase inválido: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Erro na autenticação: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_usuario_atual(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    return _decodificar_token(credentials.credentials)


def get_usuario_opcional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_opcional),
) -> Optional[dict]:
    """Autentica quando há token, mas permite chamadas públicas sem token."""
    if credentials is None:
        return None
    return _decodificar_token(credentials.credentials)
