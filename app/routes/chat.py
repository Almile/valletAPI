from fastapi import APIRouter, Depends, HTTPException, status
from firebase_admin import auth

from app.core.firebase import db
from app.valida_token import get_usuario_atual

router = APIRouter()
database = db

TIPOS_GESTOR = {"admin", "administrador", "gestor"}


def _perfil_para_chat(uid: str) -> dict:
    """Resolve quem é o usuário e qual sala de conversa ele pode acessar.
    """
    usuario_doc = database.collection("usuario").document(uid).get()
    if not usuario_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Perfil de usuário não encontrado no Firestore.",
        )

    dados = usuario_doc.to_dict() or {}
    if dados.get("ativo") is False:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sua conta está desativada.",
        )

    tipo = str(dados.get("tipo_user") or "").strip().lower()
    nome = str(dados.get("nome") or "").strip() or "Usuário"

    if tipo == "superadmin":
        return {
            "uid": uid,
            "nome": nome,
            "tipo": "superadmin",
            "estacionamentoId": "",
            "estacionamentoNome": "",
        }

    if tipo not in TIPOS_GESTOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Somente administradores e gestores podem usar o chat.",
        )

    estacionamento_id = str(dados.get("estacionamentoId") or "").strip()
    estacionamento_nome = str(dados.get("estacionamentoNome") or "").strip()

    if not estacionamento_id:
        documentos = list(
            database.collection("estacionamento")
            .where("adminUid", "==", uid)
            .limit(1)
            .stream()
        )
        if documentos:
            estacionamento_id = documentos[0].id
            estacionamento_nome = (
                (documentos[0].to_dict() or {}).get("nome") or estacionamento_nome
            )

    if not estacionamento_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Vincule este gestor a um estacionamento para usar o chat."
            ),
        )

    return {
        "uid": uid,
        "nome": nome,
        "tipo": "gestor",
        "estacionamentoId": estacionamento_id,
        "estacionamentoNome": estacionamento_nome,
    }


@router.post("/token")
def criar_token_chat(usuario_logado: dict = Depends(get_usuario_atual)):
    """Gera um token de curta duração para o SDK do Firebase no navegador.    """
    uid = (
        usuario_logado.get("uid")
        or usuario_logado.get("sub")
        or usuario_logado.get("user_id")
    )
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token sem identificador de usuário.",
        )

    perfil = _perfil_para_chat(uid)

    claims = {
        "tipo_user": perfil["tipo"],
        "nome": perfil["nome"],
    }
    if perfil["estacionamentoId"]:
        claims["estacionamentoId"] = perfil["estacionamentoId"]

    try:
        token = auth.create_custom_token(uid, claims)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Não foi possível iniciar o chat: {exc}",
        ) from exc

    if isinstance(token, bytes):
        token = token.decode("utf-8")

    return {
        "token": token,
        "uid": perfil["uid"],
        "nome": perfil["nome"],
        "tipo": perfil["tipo"],
        "estacionamentoId": perfil["estacionamentoId"],
        "estacionamentoNome": perfil["estacionamentoNome"],
    }
