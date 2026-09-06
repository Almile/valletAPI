from fastapi import APIRouter, HTTPException
from datetime import datetime
import uuid
from app.models.schemas import RequisicaoPagamento
from app.core.firebase import db

router = APIRouter()

@router.post("/simular")
def simular_pagamento(dados: RequisicaoPagamento):
    if dados.valor <= 0:
        raise HTTPException(status_code=400, detail="Valor de pagamento inválido.")


    reserva_ref = db.collection("reserva").document(dados.reserva_id)
    reserva_doc = reserva_ref.get()

    if not reserva_doc.exists:
        raise HTTPException(status_code=404, detail="Reserva não encontrada.")

    status_pagamento = "aprovado"
    motivo = None

    if dados.metodo == "cartao_credito" and dados.numero_cartao == "0000000000000000":
        status_pagamento = "recusado"
        motivo = "Cartão recusado pela operadora (simulação)"

    id_transacao = str(uuid.uuid4())

    dados_transacao = {
        "id_transacao": id_transacao,
        "valor": dados.valor,
        "metodo": dados.metodo,
        "status": status_pagamento,
        "usuario_id": dados.usuario_id,
        "reserva_id": dados.reserva_id,
        "criado_em": datetime.utcnow().isoformat()
    }
    db.collection("pagamento").document(id_transacao).set(dados_transacao)

    if status_pagamento == "aprovado":
        reserva_ref.update({
            "status": "pago",
            "pago_em": datetime.utcnow().isoformat()
        })
        return {
            "id_transacao": id_transacao,
            "status": status_pagamento,
            "mensagem": "Pagamento aprovado e status da reserva atualizado com sucesso!"
        }

    return {
        "id_transacao": id_transacao,
        "status": status_pagamento,
        "motivo": motivo,
        "mensagem": "Pagamento recusado."
    }