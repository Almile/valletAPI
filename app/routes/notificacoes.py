from datetime import datetime
from typing import Optional, Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Query, Body, status
from pydantic import BaseModel
from app.valida_token import get_usuario_atual
from app.core.firebase import db

router = APIRouter()
database = db

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
    est_docs = database.collection("estacionamento").where("adminUid", "==", uid).limit(1).stream()
    est_lista = [doc for doc in est_docs]
    return est_lista[0].id if est_lista else ""

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
        
        notif_ref = database.collection("notificacoes_admin")
        if estacionamento_id:
            notif_ref = notif_ref.where("estacionamentoId", "==", estacionamento_id)

        docs = list(notif_ref.stream())

        lista = []
        nao_lidas = 0
        tipos_set = set()

        for doc in docs:
            n = doc.to_dict()
            n_id = doc.id

            n_tipo = str(n.get("tipo") or "alerta").lower()
            tipos_set.add(n_tipo)

            lida = bool(n.get("lida", False))
            if not lida:
                nao_lidas += 1

            if apenas_nao_lidas in ["on", "true", "1"] and lida:
                continue

            if tipo and tipo.lower() != n_tipo:
                continue

            n_placa = str(n.get("placa") or "").upper()
            if placa and placa.upper() not in n_placa:
                continue

            # Ajuste de leitura do TIMESTAMP do Firestore
            dt_criacao = n.get("timestamp") or n.get("dataCriacao") or n.get("criadoEm")
            if hasattr(dt_criacao, "to_datetime"):
                dt_criacao = dt_criacao.to_datetime()
            elif isinstance(dt_criacao, str):
                try:
                    dt_criacao = datetime.fromisoformat(dt_criacao)
                except Exception:
                    dt_criacao = None

            # Filtros de Período
            if data_inicio and dt_criacao:
                dt_ini = datetime.strptime(data_inicio, "%Y-%m-%d").date()
                if dt_criacao.date() < dt_ini:
                    continue

            if data_fim and dt_criacao:
                dt_fim = datetime.strptime(data_fim, "%Y-%m-%d").date()
                if dt_criacao.date() > dt_fim:
                    continue

            # Mapeamento com fallback para 'motivo'
            lista.append({
                "id": n_id,
                "titulo": n.get("titulo") or "Alerta do Sistema",
                "mensagem": n.get("mensagem") or n.get("motivo") or "",
                "tipo": n_tipo,
                "placa": n_placa or "—",
                "vaga_numero": n.get("vagaNumero") or n.get("numeroVaga") or "—",
                "lida": lida,
                "data": dt_criacao.strftime("%d/%m/%Y %H:%M") if dt_criacao else "—",
                "_sort_key": dt_criacao.isoformat() if dt_criacao else ""
            })

        lista.sort(key=lambda x: x["_sort_key"], reverse=True)

        return {
            "notificacoes": lista,
            "nao_lidas": nao_lidas,
            "total": len(docs),
            "tipos_notificacao": sorted(list(tipos_set)),
            "id_estacionamento": estacionamento_id # Garante passagem para o JS no template
        }

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

            notificacoes = (
                database.collection("notificacoes_admin")
                .where("estacionamentoId", "==", estacionamento_id)
                .stream()
            )

            quantidade = 0

            for doc in notificacoes:
                dados = doc.to_dict() or {}

                if not dados.get("lida", False):
                    doc.reference.update({"lida": True})
                    quantidade += 1

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
    limit: int = Query(20),
    offset: int = Query(0),
    apenas_nao_lidas: str = Query("false"),
    usuario_logado: dict = Depends(get_usuario_atual)
):
    try:
        estacionamento_id = _obter_estacionamento_id(usuario_logado)
        ref = database.collection("notificacoes_admin")
        if estacionamento_id:
            ref = ref.where("estacionamentoId", "==", estacionamento_id)

        docs = list(ref.stream())
        
        total = len(docs)
        nao_lidas_count = sum(1 for d in docs if not d.to_dict().get("lida", False))

        # Paginação simples
        itens = docs[offset : offset + limit]
        resultado = []

        for d in itens:
            data = d.to_dict()
            data["id"] = d.id
            resultado.append(data)

        return {
            "notificacoes": resultado,
            "total": total,
            "nao_lidas": nao_lidas_count
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
        
        ref = database.collection("notificacoes_admin").where("lida", "==", False)
        if estacionamento_id:
            ref = ref.where("estacionamentoId", "==", estacionamento_id)

        novas_docs = list(ref.stream())
        
        has_new = len(novas_docs) > 0
        return {
            "has_new": has_new,
            "unread_count": len(novas_docs),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/updates/")
def obter_atualizacoes_notificacoes(
    ultima_atualizacao: Optional[str] = Query(""),
    limit: int = Query(20),
    usuario_logado: dict = Depends(get_usuario_atual)
):
    try:
        estacionamento_id = _obter_estacionamento_id(usuario_logado)
        
        ref = database.collection("notificacoes_admin")
        if estacionamento_id:
            ref = ref.where("estacionamentoId", "==", estacionamento_id)

        docs = list(ref.stream())
        nao_lidas = sum(1 for d in docs if not d.to_dict().get("lida", False))

        return {
            "updates": [d.to_dict() for d in docs[:limit]],
            "nao_lidas": nao_lidas,
            "ultima_atualizacao": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))