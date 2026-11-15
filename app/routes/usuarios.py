from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, HTTPException, Depends, status, Query
from firebase_admin import auth, firestore
from firebase_admin import exceptions as firebase_exceptions
from google.api_core.exceptions import FailedPrecondition, Conflict, Aborted
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
        consulta_admins = (
            database.collection("usuario")
            .where("tipo_user", "in", ["admin", "administrador"])
            .where("ativo", "!=", False)
        )

        with ThreadPoolExecutor(max_workers=2) as executor:
            futuro_admins = executor.submit(lambda: list(consulta_admins.stream()))
            futuro_estacionamentos = executor.submit(
                lambda: list(database.collection("estacionamento").stream())
            )
            admins_docs = futuro_admins.result()
            estacionamentos_docs = futuro_estacionamentos.result()

        admins = []
        for doc in admins_docs:
            data = doc.to_dict()
            data["uid"] = doc.id
            admins.append(data)

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
    """Atualiza credenciais no Authentication e perfil/vínculo no Firestore."""
    credenciais_atualizadas = False
    try:
        solicitante_uid = usuario_logado.get("uid")
        solicitante_doc = database.collection("usuario").document(solicitante_uid).get()
        solicitante = (solicitante_doc.to_dict() or {}) if solicitante_doc.exists else {}
        superadmin = solicitante.get("tipo_user") == "superadmin"
        if not superadmin and solicitante_uid != uid:
            raise HTTPException(status_code=403, detail="Você não tem permissão para editar este usuário.")

        usuario_ref = database.collection("usuario").document(uid)
        usuario_doc = usuario_ref.get()
        if not usuario_doc.exists:
            raise HTTPException(status_code=404, detail="Usuário não encontrado.")
        atuais = usuario_doc.to_dict() or {}
        novos = dados.model_dump(exclude_unset=True, exclude={"senha"})
        nova_senha = dados.senha.get_secret_value() if dados.senha is not None else None
        if not novos and nova_senha is None:
            raise HTTPException(status_code=400, detail="Nenhum campo foi informado para atualização.")

        mudou_vinculo = "estacionamentoId" in dados.model_fields_set
        if mudou_vinculo:
            if not superadmin:
                raise HTTPException(status_code=403, detail="Apenas superadmin pode alterar o vínculo do gerente.")
            if atuais.get("tipo_user") not in ("admin", "administrador"):
                raise HTTPException(status_code=400, detail="Somente administradores podem receber este vínculo.")

        # O vínculo usado nas consultas é estacionamento.adminUid, não apenas usuario.estacionamentoId.
        vinculados = []
        if mudou_vinculo or "email" in novos:
            vinculados = list(database.collection("estacionamento").where("adminUid", "==", uid).stream())
        destino = None
        if mudou_vinculo and dados.estacionamentoId:
            destino = database.collection("estacionamento").document(dados.estacionamentoId).get()
            if not destino.exists:
                raise HTTPException(status_code=404, detail="Estacionamento não encontrado.")
            responsavel = (destino.to_dict() or {}).get("adminUid")
            if responsavel and responsavel != uid:
                raise HTTPException(status_code=409, detail="O estacionamento selecionado já possui outro administrador responsável.")

        email_final = str(novos.get("email", atuais.get("email", "")))
        alteracoes_estacionamentos = {}
        if mudou_vinculo:
            for doc in vinculados:
                if destino is None or doc.id != destino.id:
                    alteracoes_estacionamentos[doc.id] = (doc, {"adminUid": "", "adminEmail": ""})
            if destino is not None:
                alteracoes_estacionamentos[destino.id] = (destino, {"adminUid": uid, "adminEmail": email_final})
            novos["estacionamentoId"] = destino.id if destino else None
            novos["estacionamentoNome"] = (destino.to_dict() or {}).get("nome") if destino else None
        elif "email" in novos:
            for doc in vinculados:
                alteracoes_estacionamentos[doc.id] = (doc, {"adminEmail": email_final})

        if len(alteracoes_estacionamentos) + bool(novos) > 500:
            raise HTTPException(status_code=400, detail="Há vínculos demais para esta atualização. Revise os vínculos do gerente.")

        # Valida a resposta antes de executar alterações externas.
        UsuarioResponse(**{**atuais, **novos, "uid": uid})
        batch = database.batch()
        if novos:
            batch.update(usuario_ref, novos, option=firestore.LastUpdateOption(usuario_doc.update_time))
        for doc, alteracoes in alteracoes_estacionamentos.values():
            batch.update(doc.reference, alteracoes, option=firestore.LastUpdateOption(doc.update_time))

        credenciais = {}
        if "email" in novos:
            credenciais["email"] = email_final
            credenciais["email_verified"] = False
        if nova_senha is not None:
            credenciais["password"] = nova_senha
        if credenciais:
            auth.update_user(uid, **credenciais)
            credenciais_atualizadas = True

        # Troca somente de senha não deve executar update({}) nem gravar senha no perfil.
        if novos or alteracoes_estacionamentos:
            try:
                batch.commit()
            except (FailedPrecondition, Conflict, Aborted):
                detalhe = "Os dados foram alterados por outra operação. Recarregue o gerente e confira o vínculo."
                if credenciais_atualizadas:
                    detalhe = "As credenciais foram atualizadas, mas o perfil/vínculo não pôde ser salvo. " + detalhe
                raise HTTPException(status_code=409, detail=detalhe)
            except Exception:
                detalhe = "Não foi possível salvar os dados de perfil e vínculo."
                if credenciais_atualizadas:
                    detalhe = "As credenciais foram atualizadas, mas não foi possível salvar o perfil/vínculo. Confira os dados antes de tentar novamente."
                raise HTTPException(status_code=503, detail=detalhe)

        atualizados = {**atuais, **novos}
        return UsuarioResponse(**_usuario_com_estacionamento(uid, atualizados))
    except HTTPException:
        raise
    except auth.EmailAlreadyExistsError:
        raise HTTPException(status_code=409, detail="Este e-mail já está em uso por outra conta.")
    except auth.UserNotFoundError:
        raise HTTPException(status_code=404, detail="Conta não encontrada no Firebase Authentication.")
    except firebase_exceptions.FirebaseError:
        raise HTTPException(status_code=503, detail="Não foi possível atualizar a conta no Firebase Authentication. Tente novamente.")
    except ValueError:
        raise HTTPException(status_code=400, detail="Os dados informados para atualização são inválidos.")
    except Exception:
        detalhe = "Não foi possível concluir a atualização do usuário."
        if credenciais_atualizadas:
            detalhe = "As credenciais foram atualizadas, mas não foi possível concluir a confirmação do perfil. Consulte os dados antes de tentar novamente."
        raise HTTPException(status_code=500, detail=detalhe)
