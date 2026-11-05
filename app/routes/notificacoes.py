import time
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from google.cloud.firestore import Query as FirestoreQuery
from google.cloud.firestore_v1.base_query import FieldFilter
from pydantic import BaseModel
from app.valida_token import get_usuario_atual
from app.core.firebase import db
from app.core.agregacoes import contar

router = APIRouter()
database = db

# A lista nunca carrega a coleção inteira. O teto mantém a página previsível
# mesmo quando o estacionamento acumular milhares de notificações.
TETO_LISTA = 200
TETO_FALLBACK = 500

# Quando o índice composto ainda não existe, evita repetir a tentativa e o
# aviso no log a cada carregamento. O fallback continua sendo usado.
_aviso_indice_ate = 0.0
INTERVALO_AVISO_INDICE = 600


class AcaoNotificacaoSchema(BaseModel):
    acao: str
    notificacao_id: Optional[str] = None


class APIPayloadSchema(BaseModel):
    acao: Optional[str] = None
    notificacao_id: Optional[str] = None
    notificacoes_ids: Optional[list[str]] = None


def _obter_estacionamento_id(usuario_logado: dict, id_header: Optional[str] = None) -> str:
    if id_header and id_header.strip():
        return id_header
    uid = usuario_logado.get("uid")
    est_docs = (
        database.collection("estacionamento")
        .where(filter=FieldFilter("adminUid", "==", uid))
        .limit(1)
        .stream()
    )
    est_lista = [doc for doc in est_docs]
    return est_lista[0].id if est_lista else ""


def _consulta_base(estacionamento_id: str):
    colecao = database.collection("notificacoes_admin")

    if estacionamento_id:
        return colecao.where(
            filter=FieldFilter("estacionamentoId", "==", estacionamento_id)
        )

    return colecao


def _resumo_notificacoes(estacionamento_id: str):
    """Devolve (total, não lidas) usando apenas agregações ``count()``.

    Documentos antigos sem o campo ``lida`` continuam sendo tratados como não
    lidos, igual ao restante da aplicação. Por isso o cálculo é
    ``total - lidas`` em vez de contar diretamente ``lida == False``.
    """
    base = _consulta_base(estacionamento_id)
    total = contar(base)
    lidas = contar(base.where(filter=FieldFilter("lida", "==", True)))
    return total, max(0, total - lidas)


def _carregar_notificacoes(estacionamento_id: str, teto: int = TETO_LISTA):
    """Carrega no máximo ``teto`` notificações, das mais recentes para as antigas.

    O caminho ideal usa o índice composto (estacionamentoId, timestamp). Se o
    projeto ainda não tiver esse índice, caímos para uma consulta global
    ordenada e limitada, filtrando o estacionamento em memória.
    """
    global _aviso_indice_ate

    if estacionamento_id:
        agora = time.monotonic()

        if agora >= _aviso_indice_ate:
            try:
                return list(
                    _consulta_base(estacionamento_id)
                    .order_by("timestamp", direction=FirestoreQuery.DESCENDING)
                    .limit(teto)
                    .stream()
                )
            except Exception as exc:
                _aviso_indice_ate = agora + INTERVALO_AVISO_INDICE
                print(
                    "[NOTIFICACOES] Índice composto indisponível; "
                    "usando consulta limitada de fallback "
                    f"({type(exc).__name__})."
                )

    limite_global = TETO_FALLBACK if estacionamento_id else teto
    docs = list(
        database.collection("notificacoes_admin")
        .order_by("timestamp", direction=FirestoreQuery.DESCENDING)
        .limit(limite_global)
        .stream()
    )

    if estacionamento_id:
        docs = [
            doc
            for doc in docs
            if str((doc.to_dict() or {}).get("estacionamentoId") or "") == estacionamento_id
        ]

    return docs[:teto]


def _data_notificacao(dados: dict):
    valor = dados.get("timestamp") or dados.get("dataCriacao") or dados.get("criadoEm")

    if hasattr(valor, "to_datetime"):
        return valor.to_datetime()

    if isinstance(valor, str):
        try:
            return datetime.fromisoformat(valor)
        except ValueError:
            return None

    return valor if isinstance(valor, datetime) else None


@router.get("/resumo/")
def resumo_notificacoes(
    usuario_logado: dict = Depends(get_usuario_atual)
):
    """Endpoint leve usado pelo Django para o badge de notificações."""
    try:
        estacionamento_id = _obter_estacionamento_id(usuario_logado)
        total, nao_lidas = _resumo_notificacoes(estacionamento_id)

        return {
            "total": total,
            "nao_lidas": nao_lidas,
            "id_estacionamento": estacionamento_id,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao resumir notificações: {str(e)}"
        )


@router.get("/")
def listar_notificacoes_page(
    tipo: Optional[str] = Query(""),
    placa: Optional[str] = Query(""),
    data_inicio: Optional[str] = Query(""),
    data_fim: Optional[str] = Query(""),
    apenas_nao_lidas: Optional[str] = Query(""),
    usuario_logado: dict = Depends(get_usuario_atual)
):
    try:
        estacionamento_id = _obter_estacionamento_id(usuario_logado)
        total, nao_lidas = _resumo_notificacoes(estacionamento_id)
        docs = _carregar_notificacoes(estacionamento_id)

        tipo_busca = (tipo or "").strip().lower()
        placa_busca = (placa or "").strip().upper()
        somente_nao_lidas = apenas_nao_lidas in ["on", "true", "1"]

        dt_ini = (
            datetime.strptime(data_inicio, "%Y-%m-%d").date()
            if data_inicio else None
        )
        dt_fim = (
            datetime.strptime(data_fim, "%Y-%m-%d").date()
            if data_fim else None
        )

        lista = []
        tipos_set = set()

        for doc in docs:
            n = doc.to_dict() or {}
            n_id = doc.id

            n_tipo = str(n.get("tipo") or "alerta").lower()
            tipos_set.add(n_tipo)

            lida = bool(n.get("lida", False))

            if somente_nao_lidas and lida:
                continue

            if tipo_busca and tipo_busca != n_tipo:
                continue

            n_placa = str(n.get("placa") or "").upper()
            if placa_busca and placa_busca not in n_placa:
                continue

            dt_criacao = _data_notificacao(n)

            if dt_ini and dt_criacao and dt_criacao.date() < dt_ini:
                continue

            if dt_fim and dt_criacao and dt_criacao.date() > dt_fim:
                continue

            lista.append({
                "id": n_id,
                "titulo": n.get("titulo") or "Alerta do Sistema",
                "mensagem": n.get("mensagem") or n.get("motivo") or "",
                "tipo": n_tipo,
                "placa": n_placa or "—",
                "vaga_numero": n.get("vagaNumero") or n.get("numeroVaga") or "—",
                "lida": lida,
                "data": dt_criacao.strftime("%d/%m/%Y %H:%M") if dt_criacao else "—",
            })

        if tipo_busca:
            tipos_set.add(tipo_busca)

        return {
            "notificacoes": lista,
            "nao_lidas": nao_lidas,
            "total": total,
            "tipos_notificacao": sorted(tipos_set),
            "id_estacionamento": estacionamento_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao buscar notificações: {str(e)}"
        )


@router.post("/acao/")
def executar_acao_notificacao(
    payload: AcaoNotificacaoSchema,
    usuario_logado: dict = Depends(get_usuario_atual)
):
    try:
        if payload.acao == "marcar_todas_como_lidas":
            estacionamento_id = _obter_estacionamento_id(usuario_logado)

            if not estacionamento_id:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Nenhum estacionamento associado a este usuário."
                )

            # Ação pouco frequente: percorre as notificações do estacionamento
            # para também normalizar documentos antigos sem o campo ``lida``.
            notificacoes = _consulta_base(estacionamento_id).stream()

            lote = database.batch()
            quantidade = 0

            for doc in notificacoes:
                if (doc.to_dict() or {}).get("lida", False):
                    continue

                lote.update(doc.reference, {"lida": True})
                quantidade += 1

                if quantidade % 450 == 0:
                    lote.commit()
                    lote = database.batch()

            if quantidade % 450:
                lote.commit()

            return {
                "success": True,
                "message": "Todas as notificações foram marcadas como lidas.",
                "quantidade": quantidade
            }

        if not payload.notificacao_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Informe o ID da notificação."
            )

        doc_ref = (
            database.collection("notificacoes_admin")
            .document(payload.notificacao_id)
        )

        if payload.acao == "marcar_lida":
            doc_ref.update({"lida": True})
        elif payload.acao == "excluir":
            doc_ref.delete()
        else:
            doc_ref.update({
                "lida": True,
                "statusAcao": payload.acao
            })

        return {
            "success": True,
            "message": "Ação executada com sucesso!"
        }

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao processar ação: {str(e)}"
        )


@router.get("/api/")
def api_listar_notificacoes(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    apenas_nao_lidas: str = Query("false"),
    usuario_logado: dict = Depends(get_usuario_atual)
):
    try:
        estacionamento_id = _obter_estacionamento_id(usuario_logado)
        total, nao_lidas_count = _resumo_notificacoes(estacionamento_id)

        docs = _carregar_notificacoes(
            estacionamento_id,
            teto=max(TETO_LISTA, offset + limit),
        )

        if apenas_nao_lidas in ["true", "1", "on"]:
            docs = [
                d for d in docs
                if not (d.to_dict() or {}).get("lida", False)
            ]

        itens = docs[offset: offset + limit]
        resultado = []

        for d in itens:
            data = d.to_dict() or {}
            data["id"] = d.id
            resultado.append(data)

        return {
            "notificacoes": resultado,
            "total": total,
            "nao_lidas": nao_lidas_count,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/")
def api_acao_notificacao(
    payload: APIPayloadSchema,
    usuario_logado: dict = Depends(get_usuario_atual)
):
    try:
        if payload.notificacao_id:
            doc_ref = database.collection("notificacoes_admin").document(payload.notificacao_id)
            doc_ref.update({"lida": True})
        elif payload.notificacoes_ids:
            for nid in payload.notificacoes_ids:
                database.collection("notificacoes_admin").document(nid).update({"lida": True})

        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/check-new/")
def checar_novas_notificacoes(
    last_check: Optional[str] = Query(""),
    usuario_logado: dict = Depends(get_usuario_atual)
):
    try:
        estacionamento_id = _obter_estacionamento_id(usuario_logado)
        _, nao_lidas = _resumo_notificacoes(estacionamento_id)

        return {
            "has_new": nao_lidas > 0,
            "unread_count": nao_lidas,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/updates/")
def obter_atualizacoes_notificacoes(
    ultima_atualizacao: Optional[str] = Query(""),
    limit: int = Query(20, ge=1, le=100),
    usuario_logado: dict = Depends(get_usuario_atual)
):
    try:
        estacionamento_id = _obter_estacionamento_id(usuario_logado)
        _, nao_lidas = _resumo_notificacoes(estacionamento_id)
        docs = _carregar_notificacoes(
            estacionamento_id,
            teto=max(TETO_LISTA, limit),
        )

        return {
            "updates": [d.to_dict() for d in docs[:limit]],
            "nao_lidas": nao_lidas,
            "ultima_atualizacao": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
