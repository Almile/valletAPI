from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

PRAZO_ENCERRADO = "O prazo de cancelamento encerrou. Para encerrar a reserva, utilize Finalizar."


def validar_cancelamento(reserva, uid, agora):
    if reserva.get("usuarioId") != uid:
        raise HTTPException(403, "Sem acesso a esta reserva.")
    if reserva.get("status") != "ativa":
        raise HTTPException(409, "A reserva não está ativa.")
    inicio = reserva.get("inicioReserva")
    # Strings, datas sem fuso, datas futuras e ausência não recebem janela nova.
    if (not isinstance(inicio, datetime) or inicio.tzinfo is None
            or inicio.timestamp() <= 0 or inicio > agora):
        raise HTTPException(409, "Reserva sem data de início válida para cancelamento.")
    if agora - inicio >= timedelta(minutes=10):
        raise HTTPException(409, PRAZO_ENCERRADO)


def cancelar_transacao(transaction, database, reserva_id, uid, vaga_esperada):
    ref = database.collection("reserva").document(reserva_id)
    snapshot = ref.get(transaction=transaction)
    if not snapshot.exists:
        raise HTTPException(404, "Reserva não encontrada.")
    reserva = snapshot.to_dict()
    validar_cancelamento(reserva, uid, datetime.now(timezone.utc))
    vaga_id = reserva.get("vagaId")
    if not isinstance(vaga_id, str) or not vaga_id or "/" in vaga_id or vaga_id != vaga_esperada:
        raise HTTPException(409, "Vínculo da vaga inválido.")
    vaga_ref = database.collection("vaga").document(vaga_id)
    vaga_doc = vaga_ref.get(transaction=transaction)
    vaga = vaga_doc.to_dict() or {}
    if (not vaga_doc.exists or vaga.get("disponivel") is not False
            or not reserva.get("estacionamentoId")
            or vaga.get("estacionamentoId") != reserva.get("estacionamentoId")
            or vaga.get("reservaId", reserva_id) != reserva_id):
        raise HTTPException(409, "O vínculo ou o estado da vaga mudou. Reabra a reserva.")
    # O esquema legado não tem reservaId na vaga: valida todas as ocupações ativas.
    ocupacoes = list(database.collection("reserva")
                     .where(filter=FieldFilter("vagaId", "==", vaga_id))
                     .where(filter=FieldFilter("status", "==", "ativa"))
                     .stream(transaction=transaction))
    if len(ocupacoes) != 1 or ocupacoes[0].id != reserva_id:
        raise HTTPException(409, "A ocupação da vaga mudou. Reabra a reserva.")
    # Revalida o limite imediatamente antes de enfileirar as duas escritas.
    validar_cancelamento(reserva, uid, datetime.now(timezone.utc))
    transaction.update(ref, {"status": "cancelada"})
    transaction.update(vaga_ref, {"disponivel": True})
    return {
        "reservaId": reserva_id,
        "vagaId": vaga_id,
        "estacionamentoId": reserva.get("estacionamentoId"),
        "status": "cancelada",
    }


@firestore.transactional
def executar_cancelamento(transaction, database, reserva_id, uid, vaga_esperada):
    return cancelar_transacao(transaction, database, reserva_id, uid, vaga_esperada)
