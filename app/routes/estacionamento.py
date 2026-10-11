from fastapi import APIRouter, Depends, HTTPException, status
from app.models.schemas import EstacionamentoSchema, EstacionamentoCreate, EstacionamentoUpdate
from app.valida_token import get_usuario_atual
from app.core.firebase import db
from firebase_admin import firestore
from pydantic import ValidationError

router = APIRouter()
database = db

@router.post("/criar_estacionamento", response_model=EstacionamentoSchema, status_code=status.HTTP_201_CREATED)
def criar_estacionamento(
    estacionamento: EstacionamentoCreate,
    usuario_logado: dict = Depends(get_usuario_atual)
):
    """
    Permite apenas que um 'superadmin' crie um estacionamento e o associe a um 'admin'.
    """
    solicitante_uid = usuario_logado.get("uid")

    try:
        solicitante_doc = database.collection("usuario").document(solicitante_uid).get()
        if not solicitante_doc.exists or solicitante_doc.to_dict().get("tipo_user") != "superadmin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Apenas usuários com perfil 'superadmin' podem cadastrar estacionamentos."
            )

        admin_doc = database.collection("usuario").document(estacionamento.adminUid).get()
        if not admin_doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="O administrador (adminUid) informado não foi encontrado."
            )
            
        dados_admin = admin_doc.to_dict()
        if dados_admin.get("tipo_user") not in ["admin", "administrador", "superadmin"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="O usuário selecionado para gerenciar o estacionamento não possui perfil de administrador."
            )

        estacionamento_dict = estacionamento.model_dump()
        estacionamento_dict["adminEmail"] = dados_admin.get("email")
        estacionamento_dict["criadoPorUid"] = solicitante_uid
        estacionamento_dict["data_criacao"] = firestore.SERVER_TIMESTAMP

        doc_ref = database.collection("estacionamento").document()
        doc_ref.set(estacionamento_dict)

        return EstacionamentoSchema(**estacionamento_dict, id=doc_ref.id)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao criar estacionamento: {str(e)}"
        )

@router.get("/buscar_estacionamento/{estacionamento_id}", response_model=EstacionamentoSchema)
def buscar_estacionamento_por_id(
    estacionamento_id: str,
    usuario_logado: dict = Depends(get_usuario_atual)
):
    """
    Busca os detalhes de um estacionamento específico pelo ID.
    Valida se o usuário logado tem acesso (superadmin ou o próprio admin do estacionamento).
    """
    try:
        uid = usuario_logado.get("uid")

        user_doc = database.collection("usuario").document(uid).get()
        tipo_user = user_doc.to_dict().get("tipo_user") if user_doc.exists else "motorista"

        estacionamento_ref = database.collection("estacionamento").document(estacionamento_id)
        doc = estacionamento_ref.get()

        if not doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Estacionamento não encontrado."
            )

        dados = doc.to_dict()
        dados["id"] = doc.id

        if tipo_user != "superadmin" and dados.get("adminUid") != uid:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Você não tem permissão para visualizar os detalhes deste estacionamento."
            )

        return EstacionamentoSchema(**dados)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao buscar estacionamento: {str(e)}"
        )

@router.get("/listar_estacionamentos_usuario", response_model=list[EstacionamentoSchema])
def listar_estacionamentos(usuario_logado: dict = Depends(get_usuario_atual)):
    """
    Lista os estacionamentos.
    Se for superadmin: traz todos.
    Se for admin: traz apenas os vinculados ao seu adminUid.
    """
    try:
        uid = usuario_logado.get("uid")
        
        user_doc = database.collection("usuario").document(uid).get()
        tipo_user = user_doc.to_dict().get("tipo_user") if user_doc.exists else "motorista"

        if tipo_user == "superadmin":
            estacionamentos_ref = database.collection("estacionamento")
        else:
            estacionamentos_ref = database.collection("estacionamento").where("adminUid", "==", uid)

        estacionamentos_docs = estacionamentos_ref.stream()

        estacionamentos_list = []
        for doc in estacionamentos_docs:
            estacionamento_data = doc.to_dict()
            estacionamento_data["id"] = doc.id
            estacionamentos_list.append(EstacionamentoSchema(**estacionamento_data))

        return estacionamentos_list

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao listar estacionamentos: {str(e)}"
        )

@router.patch("/atualizar_estacionamento/{estacionamento_id}", response_model=EstacionamentoSchema)
def atualizar_estacionamento(
    estacionamento_id: str,
    alteracoes: EstacionamentoUpdate,
    usuario_logado: dict = Depends(get_usuario_atual),
):
    """Atualiza os campos enviados, preservando metadados e os demais dados."""
    try:
        uid = usuario_logado.get("uid")
        usuario_doc = database.collection("usuario").document(uid).get()
        tipo_user = usuario_doc.to_dict().get("tipo_user") if usuario_doc.exists else None
        ref = database.collection("estacionamento").document(estacionamento_id)
        doc = ref.get()
        if not doc.exists:
            raise HTTPException(status_code=404, detail="Estacionamento não encontrado.")
        atuais = doc.to_dict()
        if tipo_user != "superadmin" and not (
            tipo_user in ("admin", "administrador") and atuais.get("adminUid") == uid
        ):
            raise HTTPException(status_code=403, detail="Você não tem permissão para editar este estacionamento.")

        novos = alteracoes.model_dump(exclude_unset=True)
        if not novos:
            return EstacionamentoSchema(**{**atuais, "id": doc.id})
        if "adminUid" in novos:
            if tipo_user != "superadmin" and novos["adminUid"] != atuais.get("adminUid"):
                raise HTTPException(status_code=403, detail="Apenas superadmin pode alterar o administrador responsável.")
            admin_doc = database.collection("usuario").document(novos["adminUid"]).get()
            if not admin_doc.exists:
                raise HTTPException(status_code=404, detail="Administrador não encontrado.")
            admin = admin_doc.to_dict()
            if admin.get("tipo_user") not in ("admin", "administrador", "superadmin"):
                raise HTTPException(status_code=400, detail="O responsável deve possuir perfil de administrador.")
            novos["adminEmail"] = admin.get("email")

        if isinstance(novos.get("endereco"), dict) and isinstance(atuais.get("endereco"), dict):
            novos["endereco"] = {**atuais["endereco"], **novos["endereco"]}
        resultado = {**atuais, **novos}
        validado = EstacionamentoCreate.model_validate(resultado)
        if "endereco" in novos:
            endereco = validado.model_dump()["endereco"]
            novos["endereco"] = ({**novos["endereco"], **endereco}
                                if isinstance(endereco, dict) else endereco)
            if isinstance(novos["endereco"], dict):
                novos["endereco"].pop("localidade", None)
        if validado.funciona24h:
            novos["horarioAbertura"] = validado.horarioAbertura
            novos["horarioFechamento"] = validado.horarioFechamento
        novos["data_atualizacao"] = firestore.SERVER_TIMESTAMP
        ref.update(novos)
        return EstacionamentoSchema(**{**atuais, **novos, "id": doc.id})
    except HTTPException:
        raise
    except ValidationError:
        raise HTTPException(status_code=422, detail="Dados de estacionamento inválidos.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao atualizar estacionamento: {str(e)}")

@router.delete("/excluir_estacionamento/{estacionamento_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir_estacionamento(
    estacionamento_id: str,
    usuario_logado: dict = Depends(get_usuario_atual)
):
    """
    Exclui um estacionamento e todos os seus dados vinculados (vagas, favoritos, notificações).
    Apenas 'superadmin' ou o 'admin' responsável pelo estacionamento podem realizar esta ação.
    """
    try:
        uid = usuario_logado.get("uid")
        
        solicitante_doc = database.collection("usuario").document(uid).get()
        if not solicitante_doc.exists:
            raise HTTPException(status_code=404, detail="Usuário solicitante não encontrado.")
        
        dados_solicitante = solicitante_doc.to_dict()
        tipo_user = dados_solicitante.get("tipo_user")

        est_ref = database.collection("estacionamento").document(estacionamento_id)
        est_doc = est_ref.get()

        if not est_doc.exists:
            raise HTTPException(status_code=404, detail="Estacionamento não encontrado.")

        dados_estacionamento = est_doc.to_dict()
        admin_uid_estacionamento = dados_estacionamento.get("adminUid")

        if tipo_user != "superadmin" and admin_uid_estacionamento != uid:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Você não tem permissão para excluir este estacionamento."
            )

        batch = database.batch()

        # Excluir Vagas
        vagas_query = database.collection("vaga").where("estacionamentoId", "==", estacionamento_id)
        for doc in vagas_query.stream():
            batch.delete(doc.reference)

        # Excluir Favoritos
        favoritos_query = database.collection("favoritos").where("estacionamentoId", "==", estacionamento_id)
        for doc in favoritos_query.stream():
            batch.delete(doc.reference)

        # Excluir Notificações
        notificacoes_query = database.collection("notificacoes_admin").where("estacionamentoId", "==", estacionamento_id)
        for doc in notificacoes_query.stream():
            batch.delete(doc.reference)
            
        # Excluir ou Cancelar Reservas
        reservas_query = database.collection("reserva").where("estacionamentoId", "==", estacionamento_id)
        for doc in reservas_query.stream():
            dados_reserva = doc.to_dict()
            if dados_reserva.get("status") not in ["cancelada", "concluida", "finalizada"]:
                batch.update(doc.reference, {"status": "cancelada", "motivo_cancelamento": "Estacionamento excluído"})

        # Excluir o próprio Estacionamento
        batch.delete(est_ref)

        # Commit de todas as operações
        batch.commit()

        return None

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao excluir estacionamento e dados vinculados: {str(e)}"
        )