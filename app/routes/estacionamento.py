from fastapi import APIRouter, Depends, HTTPException
from app.models.schemas import EstacionamentoSchema
from app.valida_token import get_usuario_atual
from app.core.firebase import db
from firebase_admin import firestore

router = APIRouter()
database = db

@router.post("/criar_estacionamento", response_model=EstacionamentoSchema)
def criar_estacionamento(
    estacionamento: EstacionamentoSchema,
    usuario_logado: dict = Depends(get_usuario_atual)
):
    """
    Cria um novo estacionamento associado ao usuário logado.
    """
    try:
        estacionamento_dict = estacionamento.model_dump()
        estacionamento_dict["adminUid"] = usuario_logado.get("uid")
        estacionamento_dict["adminEmail"] = usuario_logado.get("email")
        estacionamento_dict["data_criacao"] = firestore.SERVER_TIMESTAMP

        doc_ref = database.collection("estacionamento").document()
        doc_ref.set(estacionamento_dict)

        estacionamento_response = EstacionamentoSchema(**estacionamento_dict, id=doc_ref.id)
        return estacionamento_response

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao criar estacionamento: {str(e)}"
        )

@router.get("/listar_estacionamentos_usuario", response_model=list[EstacionamentoSchema])
def listar_estacionamentos(usuario_logado: dict = Depends(get_usuario_atual)):
    """
    Lista todos os estacionamentos associados ao usuário logado.
    """
    try:
        estacionamentos_ref = database.collection("estacionamento").where("adminUid", "==", usuario_logado.get("uid"))
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