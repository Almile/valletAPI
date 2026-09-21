from fastapi import APIRouter, Depends, HTTPException, status
from app.models.schemas import EstacionamentoSchema, EstacionamentoCreate
from app.valida_token import get_usuario_atual
from app.core.firebase import db
from firebase_admin import firestore

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