from fastapi import APIRouter, HTTPException, Depends, status
from firebase_admin import auth, firestore
from app.models.schemas import UsuarioResponse, UsuarioUpdate
from app.valida_token import get_usuario_atual
from app.core.firebase import db

router = APIRouter()
database = db

@router.patch("/atualizar_usuario/{uid}", response_model=UsuarioResponse)
def atualizar_usuario(
    uid: str,
    dados: UsuarioUpdate,
    usuario_logado: dict = Depends(get_usuario_atual)
):
    """
    Atualiza os dados do usuário no Firestore.
    """
    if uid != usuario_logado.get("uid"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para atualizar este usuário."
        )

    try:
        usuario_ref = database.collection("usuario").document(uid)
        usuario_ref.update(dados.model_dump(exclude_unset=True))
        usuario_atualizado = usuario_ref.get().to_dict()
        return UsuarioResponse(**usuario_atualizado)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao atualizar usuário: {str(e)}"
        )