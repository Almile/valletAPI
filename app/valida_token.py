from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from firebase_admin import auth

security = HTTPBearer()

def get_usuario_atual(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """
    Decodifica e valida o ID Token fornecido no cabeçalho Authorization.
    Verifica se o token é válido enão foi revogado pelo logout.
    """
    token = credentials.credentials
    try:
        decoded_token = auth.verify_id_token(token, check_revoked=True)
        return decoded_token

    except auth.RevokedIdTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="O token de acesso foi revogado. Faça login novamente.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except auth.ExpiredIdTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="O token de acesso expirou.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except auth.InvalidIdTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token do Firebase inválido.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Erro na autenticação: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )