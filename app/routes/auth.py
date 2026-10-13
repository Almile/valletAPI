import os
import httpx
from fastapi import APIRouter, HTTPException, Depends, status
from firebase_admin import auth, firestore
from app.models.schemas import UsuarioCreate, FCMTokenUpdate
from app.valida_token import get_usuario_atual
from app.core.firebase import db

router = APIRouter()
database = db

@router.post("/login")
async def login(email: str, senha: str):
    """
    Realiza a autenticação de e-mail e senha utilizando a API do Firebase de forma assíncrona.
    """
    api_key = os.getenv("FIREBASE_WEB_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="FIREBASE_WEB_API_KEY não configurada no ambiente."
        )

    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={api_key}"
    payload = {
        "email": email,
        "password": senha,
        "returnSecureToken": True
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, timeout=10.0)
            data = response.json()
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Erro de conexão com o serviço de autenticação: {exc}"
            )

    if response.status_code != 200:
        erro_msg = data.get("error", {}).get("message", "Erro ao autenticar.")
        if erro_msg in ["EMAIL_NOT_FOUND", "INVALID_PASSWORD", "INVALID_LOGIN_CREDENTIALS"]:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="E-mail ou senha incorretos."
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Falha no login: {erro_msg}"
        )

    return {
        "mensagem": "Login realizado com sucesso!",
        "idToken": data["idToken"],
        "refreshToken": data["refreshToken"],
        "expiresIn": data["expiresIn"],
        "localId": data["localId"]
    }

@router.post("/criar_usuario", status_code=status.HTTP_201_CREATED)
def criar_usuario(
    dados: UsuarioCreate,
    usuario_logado: dict = Depends(get_usuario_atual)
):
    """
    Cria um novo usuário.
    Se o novo usuário for um 'admin', exige que o criador seja 'superadmin'.
    """
    solicitante_uid = usuario_logado.get("uid")

    if dados.tipo_user in ["admin", "administrador"]:
        solicitante_doc = database.collection("usuario").document(solicitante_uid).get()
        
        if not solicitante_doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Usuário autenticado não encontrado no banco de dados."
            )

        dados_solicitante = solicitante_doc.to_dict()
        tipo_solicitante = dados_solicitante.get("tipo_user")

        if tipo_solicitante != "superadmin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Voce não tem permissão para cadastrar novos administradores."
            )

    try:
        estacionamento_nome = None
        if dados.estacionamentoId:
            estacionamento_doc = database.collection("estacionamento").document(
                dados.estacionamentoId
            ).get()
            if not estacionamento_doc.exists:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Estacionamento selecionado não foi encontrado."
                )
            estacionamento_nome = (estacionamento_doc.to_dict() or {}).get("nome")

        dados_usuario = auth.create_user(
            email=dados.email,
            password=dados.senha,
            display_name=dados.nome
        )

        payload_firestore = {
            "uid": dados_usuario.uid,
            "nome": dados.nome,
            "email": dados.email,
            "tipo_user": dados.tipo_user or "motorista",
            "cnh": dados.cnh or "",
            "telefone": dados.telefone or "",
            "fotoPerfil": dados.fotoPerfil or "",
            "cargo": dados.cargo or "",
            "estacionamentoId": dados.estacionamentoId or None,
            "estacionamentoNome": estacionamento_nome,
            "fcm_token": dados.fcm_token,
            "data_criacao": firestore.SERVER_TIMESTAMP,
            "ultima_atualizacao_token": None
        }
        
        database.collection("usuario").document(dados_usuario.uid).set(payload_firestore)

        return {
            "mensagem": "Usuário registrado com sucesso!",
            "uid": dados_usuario.uid,
            "email": dados.email,
            "nome": dados.nome,
            "tipo_user": dados.tipo_user
        }
    
    except HTTPException:
        raise
    except auth.EmailAlreadyExistsError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este e-mail já está em uso."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao criar usuário: {str(e)}"
        )

@router.post("/fcm_token", status_code=status.HTTP_200_OK)
def atualizar_fcm_token(
    dados: FCMTokenUpdate,
    usuario_logado: dict = Depends(get_usuario_atual)
):
    """
    Atualiza o token de notificação FCM do usuário logado no Firestore.
    """
    uid = usuario_logado.get("uid")

    try:
        doc_ref = database.collection("usuario").document(uid)
        
        if not doc_ref.get().exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Usuário não encontrado para atualizar o token."
            )

        doc_ref.update({
            "fcm_token": dados.fcm_token,
            "ultima_atualizacao_token": firestore.SERVER_TIMESTAMP
        })
        
        return {"mensagem": "FCM Token atualizado com sucesso!"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao atualizar FCM Token: {str(e)}"
        )

@router.get("/me")
def obter_perfil_logado(usuario_logado: dict = Depends(get_usuario_atual)):
    """
    Busca o perfil completo do usuário no Firestore usando o UID do token JWT.
    """
    uid = usuario_logado.get("uid")
    
    doc = database.collection("usuario").document(uid).get()
    
    if not doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Perfil de usuário não encontrado no Firestore."
        )
        
    return doc.to_dict()

@router.post("/logout", status_code=status.HTTP_200_OK)
def logout(usuario_logado: dict = Depends(get_usuario_atual)):
    """
    Revoga os tokens de atualização do Firebase Auth para o usuário.
    """
    try:
        uid = usuario_logado["uid"]
        auth.revoke_refresh_tokens(uid)
        return {
            "status": "sucesso",
            "mensagem": "Sessões revogadas com sucesso."
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao realizar logout: {str(e)}"
        )