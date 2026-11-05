import time as _time
from datetime import datetime, time
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from google.cloud.firestore import Query as FirestoreQuery
from google.cloud.firestore_v1.base_query import FieldFilter
from app.valida_token import get_usuario_atual
from app.core.firebase import db
from app.core.agregacoes import contar, somar
from app.core.vagas_resumo import resumo_vagas_por_consulta

router = APIRouter()
database = db

STATUS_PENDENTES = ("ativa", "pendente", "agendada", "confirmada")
STATUS_CANCELADAS = ("cancelada", "cancelado")
STATUS_RECEITA = ("concluida", "finalizada", "ativa", "confirmada")

# Evita repetir a agregação que falha e o aviso no log a cada dashboard
# enquanto o índice composto de receita não for criado.
_aviso_receita_ate = 0.0
INTERVALO_AVISO_RECEITA = 600


def _data_reserva(dados: dict):
    """Normaliza ``dataCriacao``/``inicioReserva`` para um datetime sem fuso."""
    raw = dados.get("dataCriacao") or dados.get("inicioReserva")

    if hasattr(raw, "to_datetime"):
        raw = raw.to_datetime()

    if isinstance(raw, datetime):
        if raw.tzinfo is not None:
            raw = raw.replace(tzinfo=None)
        return raw

    return None


def _somar_receita(consulta) -> float:
    """Soma ``valorTotal`` usando agregação.

    Enquanto o índice composto de receita não existir no projeto, o Firestore
    recusa a agregação. Nesse caso caímos para a leitura apenas das reservas
    filtradas, preservando o valor exibido no dashboard.
    """
    global _aviso_receita_ate

    agora = _time.monotonic()

    if agora >= _aviso_receita_ate:
        try:
            return somar(consulta, "valorTotal")
        except Exception as exc:
            _aviso_receita_ate = agora + INTERVALO_AVISO_RECEITA
            print(
                "[DASHBOARD] Agregação de receita indisponível; "
                f"usando fallback ({type(exc).__name__})."
            )

    total = 0.0
    for doc in consulta.stream():
        total += float((doc.to_dict() or {}).get("valorTotal", 0.0) or 0.0)
    return total


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
            est_docs = (
                database.collection("estacionamento")
                .where(filter=FieldFilter("adminUid", "==", uid))
                .limit(1)
                .stream()
            )
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
        # Contagens e somas usam agregações do Firestore. Apenas as 5 reservas
        # mais recentes são lidas como documentos.
        hoje_inicio = datetime.combine(datetime.now().date(), time.min)
        hoje_fim = datetime.combine(datetime.now().date(), time.max)

        reservas_ref = database.collection("reserva").where(
            filter=FieldFilter("estacionamentoId", "==", id_estacionamento)
        )

        reservas_hoje = contar(
            reservas_ref
            .where(filter=FieldFilter("inicioReserva", ">=", hoje_inicio))
            .where(filter=FieldFilter("inicioReserva", "<=", hoje_fim))
        )

        reservas_pendentes = contar(
            reservas_ref.where(
                filter=FieldFilter("status", "in", list(STATUS_PENDENTES))
            )
        )

        consulta_canceladas = reservas_ref.where(
            filter=FieldFilter("status", "in", list(STATUS_CANCELADAS))
        )
        reservas_canceladas = contar(consulta_canceladas)
        receita_cancelada_total = _somar_receita(consulta_canceladas)

        consulta_receita = reservas_ref.where(
            filter=FieldFilter("status", "in", list(STATUS_RECEITA))
        )
        receita_total = _somar_receita(consulta_receita)

        ultimos_docs = list(
            reservas_ref
            .order_by("inicioReserva", direction=FirestoreQuery.DESCENDING)
            .limit(5)
            .stream()
        )

        ultimas_reservas = []

        for doc in ultimos_docs:
            res_data = doc.to_dict() or {}
            status_reserva = str(res_data.get("status", "")).strip().lower()
            dt_obj = _data_reserva(res_data)

            ultimas_reservas.append({
                "id": doc.id,
                "status": status_reserva.capitalize(),
                "valor": f"{float(res_data.get('valorTotal', 0.0) or 0.0):,.2f}".replace(".", ","),
                "inicioReserva": dt_obj.isoformat() if dt_obj else "",
                "_usuario_id": res_data.get("usuarioId"),
                "_vaga_id": res_data.get("vagaId"),
            })

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