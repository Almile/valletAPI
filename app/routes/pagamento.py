import os
import mercadopago
from fastapi import APIRouter, HTTPException
from datetime import datetime
from app.models.schemas import RequisicaoPagamento
from app.core.firebase import db
import traceback
from dotenv import load_dotenv

load_dotenv() 

router = APIRouter()

@router.post("/pix")
def criar_pagamento_pix(dados: RequisicaoPagamento):
    try:    
        if dados.valor <= 0:
            raise HTTPException(status_code=400, detail="Valor de pagamento inválido.")

        reserva_ref = db.collection("reserva").document(dados.reserva_id)
        reserva_doc = reserva_ref.get()

        if not reserva_doc.exists:
            raise HTTPException(status_code=404, detail="Reserva não encontrada.")

        usuario_doc = db.collection("usuario").document(dados.usuario_id).get()
        email_usuario = usuario_doc.to_dict().get("email") if usuario_doc.exists else "teste@vallet.com"

        token = os.getenv("MERCADO_PAGO_ACCESS_TOKEN", "").strip()
        if not token:
            raise HTTPException(status_code=500, detail="O .env não foi lido ou o Token está vazio.")

        sdk = mercadopago.SDK(token)

        payment_data = {
            "transaction_amount": float(dados.valor),
            "description": f"Reserva Vallet - {dados.reserva_id}",
            "payment_method_id": "pix",
            "payer": {
                "email": email_usuario
            }
        }

        payment_response = sdk.payment().create(payment_data)
        payment = payment_response["response"]

        if "id" not in payment:
            raise HTTPException(status_code=500, detail=f"Erro no Mercado Pago: {payment.get('message', 'Erro desconhecido')}")

        id_transacao = str(payment["id"])
        status_pagamento = payment["status"]
        
        qr_code = payment["point_of_interaction"]["transaction_data"]["qr_code"]
        qr_code_base64 = payment["point_of_interaction"]["transaction_data"]["qr_code_base64"]

        dados_transacao = {
            "id_transacao": id_transacao,
            "valor": dados.valor,
            "metodo": "pix",
            "status": status_pagamento,
            "usuario_id": dados.usuario_id,
            "reserva_id": dados.reserva_id,
            "criado_em": datetime.utcnow().isoformat()
        }
        db.collection("pagamento").document(id_transacao).set(dados_transacao)

        reserva_ref.update({
            "status": "aguardando_pagamento",
            "pagamento_id": id_transacao
        })

        return {
            "id_transacao": id_transacao,
            "status": status_pagamento,
            "qr_code": qr_code,
            "qr_code_base64": qr_code_base64,
            "mensagem": "Pix gerado com sucesso no Mercado Pago!"
        }

    except Exception as e:
        print("===== ERRO DETALHADO NA API =====")
        traceback.print_exc()
        print("==================================")
        raise HTTPException(status_code=500, detail=f"Erro interno: {str(e)}")