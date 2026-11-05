from datetime import datetime, time
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from app.valida_token import get_usuario_atual
from app.core.firebase import db
from app.core.vagas_resumo import resumo_vagas_por_consulta

router = APIRouter()
database = db


def _buscar_documentos_por_id(colecao: str, ids) -> Dict[str, dict]:
    """Busca vários documentos em lote e devolve um mapa {id: dados}."""
    ids = [str(i) for i in ids if i]
    if not ids:
        return {}

    referencias = [database.collection(colecao).document(i) for i in ids]
    resultado = {}
    for doc in database.get_all(referencias):
        if doc.exists:
            resultado[doc.id] = doc.to_dict() or {}
    return resultado


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

        try:
            resumo_vagas = resumo_vagas_por_consulta(id_estacionamento)
        except Exception as exc:
            print(f"Erro ao agregar vagas do estacionamento {id_estacionamento}: {exc}")
            resumo_vagas = {}

        vagas_total = resumo_vagas.get(
            "quantidadeVagasTotal", dados_est.get("quantidadeVagasTotal", 0)
        )
        vagas_disponiveis = resumo_vagas.get(
            "vagasDisponiveis", dados_est.get("vagasDisponiveis", vagas_total)
        )
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

            usuario_id = res_data.get("usuarioId")
            vaga_id = res_data.get("vagaId")

            ultimas_reservas.append({
                "id": res_id,
                "status": status_reserva.capitalize(),
                "valor": f"{float(res_data.get('valorTotal', 0.0) or 0.0):,.2f}".replace(".", ","),
                "inicioReserva": dt_obj.isoformat() if dt_obj else "",
                "_dt_sort": dt_obj or datetime.min,
                "_usuario_id": usuario_id,
                "_vaga_id": vaga_id,
            })

        # Ordena com fallback de segurança e pega as 5 mais recentes
        ultimas_reservas = sorted(
            ultimas_reservas, 
            key=lambda x: x["_dt_sort"], 
            reverse=True
        )[:5]

        usuarios = _buscar_documentos_por_id(
            "usuario",
            {r.get("_usuario_id") for r in ultimas_reservas if r.get("_usuario_id")},
        )
        vagas = _buscar_documentos_por_id(
            "vaga",
            {r.get("_vaga_id") for r in ultimas_reservas if r.get("_vaga_id")},
        )

        for r in ultimas_reservas:
            usuario_id = r.pop("_usuario_id", None)
            vaga_id = r.pop("_vaga_id", None)

            usuario = usuarios.get(usuario_id) or {}
            vaga = vagas.get(vaga_id) or {}

            r["usuario"] = usuario.get("nome") or usuario.get("email") or "N/A"
            r["nome_vaga_completo"] = vaga.get("numero") or "N/A"
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
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao gerar métricas do dashboard: {str(e)}"
        )