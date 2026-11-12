"""Nesta versão todos os pagamentos são demonstrações registradas pelo app."""
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from fastapi import APIRouter, Depends, HTTPException
from app.core.firebase import db
from app.valida_token import get_usuario_atual

router = APIRouter()


@router.post("/pix")
def criar_pagamento_pix(usuario: dict = Depends(get_usuario_atual)):
    # Impede que aplicativos antigos iniciem uma cobrança bancária nesta versão.
    raise HTTPException(status_code=501, detail="Esta versão usa pagamento de demonstração no aplicativo e não gera Pix bancário.")


@router.get("/{pagamento_id}/status")
def consultar_status(pagamento_id: str, usuario: dict = Depends(get_usuario_atual)):
    uid = usuario.get("uid")
    if not uid:
        raise HTTPException(status_code=401, detail="Usuário não identificado.")
    if not pagamento_id.strip() or "/" in pagamento_id or len(pagamento_id.encode()) > 1500:
        raise HTTPException(status_code=422, detail="Identificador inválido.")
    try:
        doc = db.collection("pagamento").document(pagamento_id).get()
        if not doc.exists:
            raise HTTPException(status_code=404, detail="Pagamento não encontrado.")
        dados = doc.to_dict() or {}
        if dados.get("usuario_id") != uid:
            raise HTTPException(status_code=403, detail="Sem acesso a este pagamento.")
        try:
            valor = Decimal(str(dados.get("valor")))
            if not valor.is_finite() or valor <= 0 or valor > Decimal("9999999999.99"):
                raise ValueError()
            valor = valor.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError, TypeError):
            raise HTTPException(status_code=503, detail="O registro possui um valor inválido.")
        confirmado = dados.get("confirmado_em")
        return {
            "id_transacao": doc.id,
            "reserva_id": dados.get("reserva_id"),
            "status": dados.get("status"),
            "valor": str(valor),
            "confirmado_em": confirmado.isoformat() if isinstance(confirmado, datetime) else confirmado,
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Não foi possível consultar o pagamento.")
