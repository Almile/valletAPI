from typing import List
from fastapi import APIRouter, HTTPException, Depends, status
from firebase_admin import firestore
from app.models.schemas import Vaga, VagaCreate, VagaUpdate, VagasLoteCreate
from app.valida_token import get_usuario_atual
from app.core.firebase import db
from app.core.vagas_resumo import sincronizar_resumo

router = APIRouter()
database = db

@router.post("/criar", response_model=Vaga, status_code=status.HTTP_201_CREATED)
def criar_vaga(
    vaga: VagaCreate,
    usuario_logado: dict = Depends(get_usuario_atual)
):
    """
    Cria uma única vaga vinculada a um estacionamento.
    """
    try:
        nova_vaga_ref = database.collection("vaga").document()
        dados_vaga = vaga.model_dump()
        dados_vaga["id"] = nova_vaga_ref.id

        nova_vaga_ref.set(dados_vaga)
        sincronizar_resumo(dados_vaga.get("estacionamentoId"))
        return Vaga(**dados_vaga)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao criar vaga: {str(e)}"
        )

@router.post("/criar_lote", response_model=List[Vaga], status_code=status.HTTP_201_CREATED)
def criar_vagas_em_lote(
    dados_lote: VagasLoteCreate,
    usuario_logado: dict = Depends(get_usuario_atual)
):
    """
    Cria múltiplas vagas sequenciais automaticamente para um estacionamento.
    Exemplo: prefixo 'A-' e quantidade 5 gera vagas: A-1, A-2, A-3, A-4, A-5.
    """
    try:
        batch = database.batch()
        vagas_criadas = []

        for i in range(1, dados_lote.quantidade + 1):
            vaga_ref = database.collection("vaga").document()
            
            vaga_data = {
                "id": vaga_ref.id,
                "numero": f"{dados_lote.prefixo}{i}",
                "localizacao": dados_lote.localizacao,
                "preco": dados_lote.preco,
                "tipo": dados_lote.tipo,
                "preferencial": dados_lote.preferencial,
                "disponivel": True,
                "estacionamentoId": dados_lote.estacionamentoId
            }

            batch.set(vaga_ref, vaga_data)
            vagas_criadas.append(vaga_data)

        batch.commit()
        sincronizar_resumo(dados_lote.estacionamentoId)
        
        return [Vaga(**v) for v in vagas_criadas]

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao criar vagas em lote: {str(e)}"
        )


@router.get("/estacionamento/{estacionamento_id}", response_model=List[Vaga])
def listar_vagas_por_estacionamento(
    estacionamento_id: str,
    usuario_logado: dict = Depends(get_usuario_atual)
):
    """
    Retorna todas as vagas cadastradas para um estacionamento específico.
    """
    try:
        query = database.collection("vaga").where("estacionamentoId", "==", estacionamento_id)
        docs = query.stream()

        vagas = []
        for doc in docs:
            dados = doc.to_dict()
            if "id" not in dados:
                dados["id"] = doc.id
            vagas.append(Vaga(**dados))

        return vagas

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao buscar vagas do estacionamento: {str(e)}"
        )


@router.patch("/atualizar/{vaga_id}", response_model=Vaga)
def editar_vaga(
    vaga_id: str,
    dados: VagaUpdate,
    usuario_logado: dict = Depends(get_usuario_atual)
):
    """
    Atualiza dados específicos de uma vaga pelo ID.
    """
    try:
        vaga_ref = database.collection("vaga").document(vaga_id)
        doc = vaga_ref.get()

        if not doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Vaga não encontrada."
            )

        novos_dados = dados.model_dump(exclude_unset=True)
        if novos_dados:
            vaga_ref.update(novos_dados)

        vaga_atualizada = vaga_ref.get().to_dict()
        if "id" not in vaga_atualizada:
            vaga_atualizada["id"] = vaga_id

        sincronizar_resumo(vaga_atualizada.get("estacionamentoId"))

        return Vaga(**vaga_atualizada)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao atualizar vaga: {str(e)}"
        )


@router.delete("/excluir/{vaga_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir_vaga(
    vaga_id: str,
    usuario_logado: dict = Depends(get_usuario_atual)
):
    """
    Remove uma vaga pelo ID.
    """
    try:
        vaga_ref = database.collection("vaga").document(vaga_id)
        doc = vaga_ref.get()

        if not doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Vaga não encontrada."
            )

        estacionamento_id = (doc.to_dict() or {}).get("estacionamentoId")
        vaga_ref.delete()
        sincronizar_resumo(estacionamento_id)
        return None

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao excluir vaga: {str(e)}"
        )