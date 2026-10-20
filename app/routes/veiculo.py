from fastapi import APIRouter, Depends, HTTPException
from app.models.schemas import UsuarioResponse, VeiculoCreate, VeiculoResponse
from app.valida_token import get_usuario_atual
from app.core.firebase import db
from firebase_admin import firestore

router = APIRouter()
database = db

@router.post("/criar_veiculo", response_model=VeiculoResponse)
def criar_veiculo(
    veiculo: VeiculoCreate,
    usuario_logado: dict = Depends(get_usuario_atual)
):
    """
    Cria um novo veículo associado ao usuário logado.
    """
    try:
        veiculo_dict = veiculo.model_dump()
        veiculo_dict["usuarioId"] = usuario_logado.get("uid")
        veiculo_dict["usuarioEmail"] = usuario_logado.get("email")
        veiculo_dict["dataCadastro"] = firestore.SERVER_TIMESTAMP

        doc_ref = database.collection("veiculo").document()
        doc_ref.set(veiculo_dict)

        veiculo_response = VeiculoResponse(**veiculo_dict, id=doc_ref.id)
        return veiculo_response

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao criar veículo: {str(e)}"
        )


@router.get("/veiculos_usuario", response_model=list[VeiculoResponse])
def listar_veiculos(usuario_logado: dict = Depends(get_usuario_atual)):
    """
    Lista todos os veículos associados ao usuário logado.
    """
    try:
        veiculos_ref = database.collection("veiculo").where("usuarioId", "==", usuario_logado.get("uid"))
        veiculos_docs = veiculos_ref.stream()

        veiculos_list = []
        for doc in veiculos_docs:
            veiculo_data = doc.to_dict()
            veiculo_data["id"] = doc.id
            veiculos_list.append(VeiculoResponse(**veiculo_data))

        return veiculos_list

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao listar veículos: {str(e)}"
        )

@router.get("/todos_veiculos", response_model=list[VeiculoResponse])
def listar_todos_veiculos():
    """
    Lista todos os veículos cadastrados no sistema.
    """
    try:
        veiculos_ref = database.collection("veiculo")
        veiculos_docs = veiculos_ref.stream()

        veiculos_list = []
        for doc in veiculos_docs:
            veiculo_data = doc.to_dict()
            veiculo_data["id"] = doc.id
            veiculos_list.append(VeiculoResponse(**veiculo_data))

        return veiculos_list

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao listar todos os veículos: {str(e)}"
        )

@router.get("/obter_veiculo/{veiculo_id}", response_model=VeiculoResponse)
def obter_veiculo(veiculo_id: str, usuario_logado: dict = Depends(get_usuario_atual)):
    """
    Obtém os detalhes de um veículo específico associado ao usuário logado.
    """
    try:
        doc_ref = database.collection("veiculo").document(veiculo_id)
        doc = doc_ref.get()

        if not doc.exists:
            raise HTTPException(
                status_code=404,
                detail="Veículo não encontrado."
            )

        veiculo_data = doc.to_dict()
        if veiculo_data["usuarioId"] != usuario_logado.get("uid"):
            raise HTTPException(
                status_code=403,
                detail="Acesso negado ao veículo."
            )

        veiculo_data["id"] = doc.id
        return VeiculoResponse(**veiculo_data)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao obter veículo: {str(e)}"
        )

@router.get("/achar_usuario_por_veiculo/{veiculo_id}", response_model=UsuarioResponse)
def achar_usuario_por_veiculo(veiculo_id: str, usuario_logado: dict = Depends(get_usuario_atual)):
    """
    Acha o usuário associado a um veículo específico.
    """
    try:
        doc_ref = database.collection("veiculo").document(veiculo_id)
        doc = doc_ref.get()

        if not doc.exists:
            raise HTTPException(
                status_code=404,
                detail="Veículo não encontrado."
            )

        veiculo_data = doc.to_dict()
        if veiculo_data["usuarioId"] != usuario_logado.get("uid"):
            raise HTTPException(
                status_code=403,
                detail="Acesso negado ao veículo."
            )

        usuario_ref = database.collection("usuario").document(veiculo_data["usuarioId"])
        usuario_doc = usuario_ref.get()

        if not usuario_doc.exists:
            raise HTTPException(
                status_code=404,
                detail="Usuário não encontrado."
            )

        usuario_data = usuario_doc.to_dict()
        usuario_data["id"] = usuario_doc.id
        return UsuarioResponse(**usuario_data)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao achar usuário por veículo: {str(e)}"
        )

@router.put("/atualizar_veiculo/{veiculo_id}", response_model=VeiculoResponse)
def atualizar_veiculo(
    veiculo_id: str,
    veiculo_atualizado: VeiculoCreate,
    usuario_logado: dict = Depends(get_usuario_atual)
):
    """
    Atualiza um veículo do usuário conectado.
    Preserva a cor existente quando esse campo não é enviado.
    """
    try:
        doc_ref = database.collection("veiculo").document(veiculo_id)
        doc = doc_ref.get()

        if not doc.exists:
            raise HTTPException(
                status_code=404,
                detail="Veículo não encontrado."
            )

        veiculo_data = doc.to_dict()

        if veiculo_data["usuarioId"] != usuario_logado.get("uid"):
            raise HTTPException(
                status_code=403,
                detail="Acesso negado ao veículo."
            )

        veiculo_dict = veiculo_atualizado.model_dump()

        if "cor" not in veiculo_atualizado.model_fields_set:
            veiculo_dict.pop("cor", None)
        else:
            veiculo_dict["cor"] = veiculo_atualizado.cor.strip()

        doc_ref.update(veiculo_dict)

        veiculo_data.update(veiculo_dict)
        veiculo_data["id"] = doc.id

        return VeiculoResponse(**veiculo_data)

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao atualizar veículo: {str(e)}"
        )

@router.delete("/deletar_veiculo/{veiculo_id}", status_code=204)
def deletar_veiculo(veiculo_id: str, usuario_logado: dict = Depends(get_usuario_atual)):
    """
    Deleta um veículo específico associado ao usuário logado.
    """
    try:
        doc_ref = database.collection("veiculo").document(veiculo_id)
        doc = doc_ref.get()

        if not doc.exists:
            raise HTTPException(
                status_code=404,
                detail="Veículo não encontrado."
            )

        veiculo_data = doc.to_dict()
        if veiculo_data["usuarioId"] != usuario_logado.get("uid"):
            raise HTTPException(
                status_code=403,
                detail="Acesso negado ao veículo."
            )

        doc_ref.delete()
        return {"mensagem": "Veículo deletado com sucesso."}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao deletar veículo: {str(e)}"
        )