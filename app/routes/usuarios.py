from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, status, Query
from firebase_admin import auth, firestore
from app.models.schemas import UsuarioResponse, UsuarioUpdate
from app.valida_token import get_usuario_atual
from app.core.firebase import db

router = APIRouter()
database = db

@router.get("/", response_model=List[UsuarioResponse])
def listar_usuarios(
    tipo: Optional[str] = Query(None, description="Filtra usuários pelo tipo (ex: admin, motorista)"),
    usuario_logado: dict = Depends(get_usuario_atual)
):
    """
    Lista usuários cadastrados no sistema. 
    Se o parâmetro `tipo` for informado (ex: /usuarios?tipo=admin), filtra por tipo.
    """
    try:
        usuarios_ref = database.collection("usuario")

        if tipo:
            query = usuarios_ref.where("tipo_user", "==", tipo)
            docs = query.stream()
        else:
            docs = usuarios_ref.stream()

        lista_usuarios = []
        for doc in docs:
            dados = doc.to_dict()
            if "uid" not in dados:
                dados["uid"] = doc.id
            lista_usuarios.append(UsuarioResponse(**dados))

        return lista_usuarios

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao buscar usuários: {str(e)}"
        )


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