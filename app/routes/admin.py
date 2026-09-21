from datetime import datetime, time
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from app.valida_token import get_usuario_atual
from app.core.firebase import db

router = APIRouter()
database = db


@router.get("/{id_estacionamento}/dashboard")
@router.get("/dashboard")  # Trata chamadas em que o ID do estacionamento não vai na URL
def obter_dashboard_estacionamento(
    id_estacionamento: Optional[str] = None,
    usuario_logado: dict = Depends(get_usuario_atual)
):
    """
    Retorna métricas e dados consolidados para o dashboard do gestor.
    Se id_estacionamento for None, tenta buscar o primeiro estacionamento vinculado ao admin logado.
    """
    uid = usuario_logado.get("uid")

    try:
        # 1. Se id_estacionamento for omitido ou string vazia, descobre o estacionamento do admin
        if not id_estacionamento or id_estacionamento.strip() == "":
            est_docs = database.collection("estacionamento").where("adminUid", "==", uid).limit(1).stream()
            est_lista = [doc for doc in est_docs]
            
            if not est_lista:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Nenhum estacionamento associado a este usuário foi encontrado."
                )
            id_estacionamento = est_lista[0].id
            doc_estacionamento = est_lista[0]
        else:
            doc_estacionamento = database.collection("estacionamento").document(id_estacionamento).get()
            if not doc_estacionamento.exists:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Estacionamento não encontrado."
                )

        dados_est = doc_estacionamento.to_dict()

        # 2. Leitura de Vagas (totais e ocupadas)
        vagas_total = dados_est.get("quantidadeVagasTotal", 0)
        vagas_disponiveis = dados_est.get("vagasDisponiveis", vagas_total)
        vagas_ocupadas = max(0, vagas_total - vagas_disponiveis)

        # 3. Métricas de Reservas do Dia
        hoje_inicio = datetime.combine(datetime.now().date(), time.min)
        hoje_fim = datetime.combine(datetime.now().date(), time.max)

        # Consultando reservas no Firestore para este estacionamento
        reservas_ref = database.collection("reserva").where("estacionamentoId", "==", id_estacionamento)
        reservas_docs = list(reservas_ref.stream())

        reservas_hoje = 0
        reservas_pendentes = 0
        reservas_canceladas = 0
        receita_total = 0.0
        receita_cancelada_total = 0.0
        ultimas_reservas = []

        for doc in reservas_docs:
            res_data = doc.to_dict()
            res_id = doc.id
            status_reserva = res_data.get("status", "ativa").lower()
            
            # Tratamento de datas do Firestore (Timestamp -> datetime)
            data_criacao = res_data.get("dataCriacao")
            if hasattr(data_criacao, "to_datetime"):
                data_criacao = data_criacao.to_datetime()

            # Checa se a reserva foi criada hoje
            if data_criacao and hoje_inicio <= data_criacao <= hoje_fim:
                reservas_hoje += 1

            # Contagem por status
            if status_reserva in ["ativa", "pendente"]:
                reservas_pendentes += 1
            elif status_reserva == "cancelada":
                reservas_canceladas += 1
                receita_cancelada_total += res_data.get("valorTotal", 0.0)

            # Soma de receita de reservas concluídas / ativas
            if status_reserva in ["concluida", "ativa"]:
                receita_total += res_data.get("valorTotal", 0.0)

            # Estrutura dados das últimas reservas para exibir no Dashboard
            ultimas_reservas.append({
                "id": res_id,
                "usuario": res_data.get("usuarioEmail") or res_data.get("usuarioId", "N/A"),
                "vaga": res_data.get("vagaId", "N/A"),
                "status": status_reserva.capitalize(),
                "valor": f"{res_data.get('valorTotal', 0.0):,.2f}".replace(".", ","),
                "data": data_criacao.strftime("%d/%m/%Y %H:%M") if data_criacao else "N/A"
            })

        # Ordena últimas 5 reservas por data de criação mais recente
        ultimas_reservas = sorted(
            ultimas_reservas, 
            key=lambda x: x["data"], 
            reverse=True
        )[:5]

        # 4. Resposta no formato exato que a view 'gestor' do Django consome
        return {
            "id_estacionamento": id_estacionamento,
            "vagas_total": vagas_total,
            "vagas_ocupadas": vagas_ocupadas,
            "reservas_hoje": reservas_hoje,
            "reservas_pendentes": reservas_pendentes,
            "reservas_canceladas": reservas_canceladas,
            "receita_mensal": f"{receita_total:,.2f}".replace(".", ","),
            "receita_cancelada": f"{receita_cancelada_total:,.2f}".replace(".", ","),
            "ultimas_reservas": ultimas_reservas
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao gerar métricas do dashboard: {str(e)}"
        )