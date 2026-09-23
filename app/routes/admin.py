from datetime import datetime, time
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from app.valida_token import get_usuario_atual
from app.core.firebase import db

router = APIRouter()
database = db


@router.get("/{id_estacionamento}/dashboard")
@router.get("/dashboard")
def obter_dashboard_estacionamento(
    id_estacionamento: Optional[str] = None,
    usuario_logado: dict = Depends(get_usuario_atual)
):
    uid = usuario_logado.get("uid")

    try:
        # 1. Identificação do estacionamento
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

        dados_est = doc_estacionamento.to_dict() or {}

        # 2. Leitura de Vagas
        vagas_total = dados_est.get("quantidadeVagasTotal", 0)
        vagas_disponiveis = dados_est.get("vagasDisponiveis", vagas_total)
        vagas_ocupadas = max(0, vagas_total - vagas_disponiveis)

        # 3. Métricas de Reservas
        hoje_inicio = datetime.combine(datetime.now().date(), time.min)
        hoje_fim = datetime.combine(datetime.now().date(), time.max)

        reservas_ref = database.collection("reserva").where("estacionamentoId", "==", id_estacionamento)
        reservas_docs = list(reservas_ref.stream())

        reservas_hoje = 0
        reservas_pendentes = 0
        reservas_canceladas = 0
        receita_total = 0.0
        receita_cancelada_total = 0.0
        ultimas_reservas = []

        for doc in reservas_docs:
            res_data = doc.to_dict() or {}
            res_id = doc.id
            
            # Normaliza o status garantindo que não quebre por None ou espaços
            status_reserva = str(res_data.get("status", "")).strip().lower()
            
            # Tratamento da data
            raw_data = res_data.get("dataCriacao") or res_data.get("inicioReserva")
            dt_obj = None

            if hasattr(raw_data, "to_datetime"):
                dt_obj = raw_data.to_datetime()
            elif isinstance(raw_data, datetime):
                dt_obj = raw_data

            if dt_obj and dt_obj.tzinfo is not None:
                dt_obj = dt_obj.replace(tzinfo=None)

            # 1. Checa se foi criada hoje
            if dt_obj and hoje_inicio <= dt_obj <= hoje_fim:
                reservas_hoje += 1

            # 2. Contagem flexível por status
            if status_reserva in ["ativa", "pendente", "agendada", "confirmada"]:
                reservas_pendentes += 1
            elif status_reserva in ["cancelada", "cancelado"]:
                reservas_canceladas += 1
                receita_cancelada_total += float(res_data.get("valorTotal", 0.0) or 0.0)

            if status_reserva in ["concluida", "finalizada", "ativa", "confirmada"]:
                receita_total += float(res_data.get("valorTotal", 0.0) or 0.0)

            # Montagem segura do dicionário para a lista
            ultimas_reservas.append({
                "id": res_id,
                "usuario": res_data.get("usuarioEmail") or res_data.get("usuarioId", "N/A"),
                "nome_vaga_completo": res_data.get("vagaId") or res_data.get("vagaNumero") or "Vaga N/A",
                "status": status_reserva.capitalize(),
                "valor": f"{float(res_data.get('valorTotal', 0.0) or 0.0):,.2f}".replace(".", ","),
                "inicioReserva": dt_obj.isoformat() if dt_obj else "",
                "_dt_sort": dt_obj or datetime.min  # Usado exclusivamente para ordenação
            })

        # Ordena com fallback de segurança e pega as 5 mais recentes
        ultimas_reservas = sorted(
            ultimas_reservas, 
            key=lambda x: x["_dt_sort"], 
            reverse=True
        )[:5]

        # Limpa o campo auxiliar de ordenação da resposta
        for r in ultimas_reservas:
            r.pop("_dt_sort", None)

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
        # Exibe o log detalhado no terminal em caso de erro interno
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao gerar métricas do dashboard: {str(e)}"
        )