from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, status, Query
from firebase_admin import auth, firestore
from app.models.schemas import UsuarioResponse, UsuarioUpdate
from app.valida_token import get_usuario_atual
from app.core.firebase import db

router = APIRouter()
database = db


def _usuario_com_estacionamento(uid: str, dados: dict, mapa_por_id=None, mapa_por_admin=None) -> dict:
    """
    Inclui o ID e o nome do estacionamento vinculado ao usuário.
    """
    resultado = dict(dados or {})
    resultado["uid"] = resultado.get("uid") or uid

    if resultado.get("tipo_user") in ("admin", "administrador"):
        if mapa_por_admin is not None:
            vinculado = mapa_por_admin.get(uid)
            if vinculado:
                resultado["estacionamentoId"], resultado["estacionamentoNome"] = vinculado
        else:
            est_docs = database.collection("estacionamento").where("adminUid", "==", uid).limit(1).stream()
            for est_doc in est_docs:
                est_data = est_doc.to_dict() or {}
                resultado["estacionamentoId"] = est_doc.id
                resultado["estacionamentoNome"] = est_data.get("nome")
                break

    elif resultado.get("estacionamentoId"):
        estacionamento_id = str(resultado["estacionamentoId"])
        if mapa_por_id is not None:
            if estacionamento_id in mapa_por_id:
                resultado["estacionamentoNome"] = mapa_por_id[estacionamento_id]
        else:
            est_doc = database.collection("estacionamento").document(estacionamento_id).get()
            if est_doc.exists:
                resultado["estacionamentoNome"] = (est_doc.to_dict() or {}).get("nome")

    return resultado


def _mapa_estacionamentos():
    """Carrega os estacionamentos uma única vez para evitar N+1.
    """
    por_id = {}
    por_admin = {}

    for doc in database.collection("estacionamento").stream():
        dados = doc.to_dict() or {}
        por_id[doc.id] = dados.get("nome")

        admin_uid = dados.get("adminUid")
        if admin_uid and admin_uid not in por_admin:
            por_admin[admin_uid] = (doc.id, dados.get("nome"))

    return por_id, por_admin

@router.get("/listar_admins_disponiveis")
def listar_admins_disponiveis(usuario_logado: dict = Depends(get_usuario_atual)):
    """
    Lista apenas admins que ainda não estão vinculados a nenhum estacionamento.
    """
    try:
        admins_docs = (database.collection("usuario").where("tipo_user", "in", ["admin", "administrador"]).where("ativo", "!=", False).stream())
        admins = []
        for doc in admins_docs:
            data = doc.to_dict()
            data["uid"] = doc.id
            admins.append(data)

        estacionamentos_docs = database.collection("estacionamento").stream()
        admins_vinculados = set()
        for doc in estacionamentos_docs:
            data = doc.to_dict()
            if data.get("adminUid"):
                admins_vinculados.add(data["adminUid"])

        admins_disponiveis = [a for a in admins if a["uid"] not in admins_vinculados]

        return admins_disponiveis

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao listar administradores disponíveis: {str(e)}"
        )

@router.get("/", response_model=List[UsuarioResponse])
def listar_usuarios(
    tipo: Optional[str] = Query(None, description="Filtra usuários pelo tipo (ex: admin, motorista)"),
    usuario_logado: dict = Depends(get_usuario_atual)
):
    """Lista usuários cadastrados e inclui o estacionamento vinculado, se houver."""
    try:
        usuarios_ref = database.collection("usuario")
        docs = usuarios_ref.where("tipo_user", "==", tipo).stream() if tipo else usuarios_ref.stream()

        mapa_por_id, mapa_por_admin = _mapa_estacionamentos()

        lista_usuarios = []
        for doc in docs:
            dados = _usuario_com_estacionamento(
                doc.id,
                doc.to_dict() or {},
                mapa_por_id=mapa_por_id,
                mapa_por_admin=mapa_por_admin,
            )
            lista_usuarios.append(UsuarioResponse(**dados))
        return lista_usuarios
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao buscar usuários: {str(e)}"
        )


@router.get("/{uid}", response_model=UsuarioResponse)
def obter_usuario_por_uid(
    uid: str,
    usuario_logado: dict = Depends(get_usuario_atual)
):
    """Obtém os dados detalhados de um usuário para o painel administrativo."""
    try:
        solicitante_uid = usuario_logado.get("uid")
        solicitante_doc = database.collection("usuario").document(solicitante_uid).get()
        solicitante = (solicitante_doc.to_dict() or {}) if solicitante_doc.exists else {}

        if solicitante.get("tipo_user") != "superadmin" and solicitante_uid != uid:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Você não tem permissão para visualizar os dados deste usuário."
            )

        usuario_doc = database.collection("usuario").document(uid).get()
        if not usuario_doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Gerente não encontrado."
            )

        dados = _usuario_com_estacionamento(usuario_doc.id, usuario_doc.to_dict() or {})
        if dados.get("tipo_user") not in ("admin", "administrador") and solicitante_uid != uid:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Gerente não encontrado."
            )
        return UsuarioResponse(**dados)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao buscar usuário: {str(e)}"
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

    try:
        solicitante_uid = usuario_logado.get("uid")
        solicitante_doc = database.collection("usuario").document(solicitante_uid).get()
        solicitante = (solicitante_doc.to_dict() or {}) if solicitante_doc.exists else {}

        if solicitante.get("tipo_user") != "superadmin" and solicitante_uid != uid:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Você não tem permissão para visualizar os dados deste usuário."
            )
        usuario_ref = database.collection("usuario").document(uid)
        usuario_ref.update(dados.model_dump(exclude_unset=True))
        usuario_atualizado = usuario_ref.get().to_dict()
        return UsuarioResponse(**usuario_atualizado)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao atualizar usuário: {str(e)}"
        )