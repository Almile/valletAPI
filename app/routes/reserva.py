from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from google.cloud.firestore import Query as FirestoreQuery
from google.cloud.firestore_v1.base_query import FieldFilter
from google.api_core.exceptions import AlreadyExists, FailedPrecondition
from app.valida_token import get_usuario_atual
from app.core.firebase import db

router = APIRouter()
database = db
FUSO_RESERVAS = ZoneInfo("America/Sao_Paulo")
_logger = logging.getLogger(__name__)


def _data(valor):
    if hasattr(valor, "to_datetime"):
        valor = valor.to_datetime()
    if isinstance(valor, str):
        try:
            valor = datetime.fromisoformat(valor.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(valor, datetime):
        return None
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=timezone.utc)
    return valor.astimezone(FUSO_RESERVAS)


@router.get("/")
def listar_reservas_estacionamento(
    id_estacionamento: Optional[str] = None,
    placa: Optional[str] = Query(None),
    usuario: Optional[str] = Query(None),
    data_inicio: Optional[str] = Query(None),
    data_fim: Optional[str] = Query(None),
    status_filtro: Optional[str] = Query(None, alias="status"),
    limite: int = Query(24, ge=1, le=48),
    cursor: Optional[str] = Query(None),
    direcao: str = Query("proxima", pattern="^(proxima|anterior)$"),
    usuario_logado: dict = Depends(get_usuario_atual),
):
    uid = usuario_logado.get("uid")

    try:
        inicio_filtro = (
            datetime.strptime(data_inicio, "%Y-%m-%d").date()
            if data_inicio else None
        )
        fim_filtro = (
            datetime.strptime(data_fim, "%Y-%m-%d").date()
            if data_fim else None
        )
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Informe as datas no formato AAAA-MM-DD."
        )

    if inicio_filtro and fim_filtro and inicio_filtro > fim_filtro:
        raise HTTPException(status_code=400, detail="A data inicial deve ser anterior ou igual à final.")

    if fim_filtro and fim_filtro.year == 9999 and fim_filtro.month == 12 and fim_filtro.day == 31:
        raise HTTPException(status_code=400, detail="Data final fora do intervalo permitido.")

    try:
        if (
            not id_estacionamento
            or id_estacionamento.strip() in ["", "None", "null"]
            or id_estacionamento == uid
        ):
            estacionamentos = list(
                database.collection("estacionamento")
                .where("adminUid", "==", uid)
                .limit(1)
                .stream()
            )

            if not estacionamentos:
                return {
                    "reservas": [],
                    "tem_anterior": False,
                    "tem_proxima": False
                }

            estacionamento = estacionamentos[0]
            id_estacionamento = estacionamento.id

        else:
            estacionamento = (
                database.collection("estacionamento")
                .document(id_estacionamento)
                .get()
            )

            if not estacionamento.exists:
                raise HTTPException(
                    status_code=404,
                    detail="Estacionamento não encontrado."
                )

            if (estacionamento.to_dict() or {}).get("adminUid") != uid:
                perfil = database.collection("usuario").document(uid).get()

                if (
                    not perfil.exists
                    or (perfil.to_dict() or {}).get("tipo_user") != "superadmin"
                ):
                    raise HTTPException(
                        status_code=403,
                        detail="Sem acesso a este estacionamento."
                    )

        referencia = database.collection("reserva")

        anteriores = direcao == "anterior" and bool(cursor)

        sentido = (
            FirestoreQuery.ASCENDING
            if anteriores
            else FirestoreQuery.DESCENDING
        )

        consulta = referencia.where(filter=FieldFilter("estacionamentoId", "==", id_estacionamento))
        if inicio_filtro:
            inicio = datetime.combine(inicio_filtro, time.min, tzinfo=FUSO_RESERVAS)
            consulta = consulta.where(filter=FieldFilter(
                "inicioReserva", ">=", inicio.astimezone(timezone.utc)
            ))
        if fim_filtro:
            fim_exclusivo = datetime.combine(fim_filtro + timedelta(days=1), time.min, tzinfo=FUSO_RESERVAS)
            consulta = consulta.where(filter=FieldFilter(
                "inicioReserva", "<", fim_exclusivo.astimezone(timezone.utc)
            ))
        consulta = consulta.order_by("inicioReserva", direction=sentido).order_by("__name__", direction=sentido)

        posicao = None

        if cursor:
            if "/" in cursor:
                raise HTTPException(
                    status_code=400,
                    detail="Cursor inválido."
                )

            posicao = referencia.document(cursor).get()
            dados_cursor = posicao.to_dict() or {}

            if (
                not posicao.exists
                or dados_cursor.get("estacionamentoId") != id_estacionamento
                or not dados_cursor.get("inicioReserva")
            ):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Esta página não está mais disponível. "
                        "Reabra a lista de reservas."
                    )
                )

        usuarios = {}
        veiculos = {}
        vagas = {}

        def montar_item(doc, r, estado, inicio, fim):
            usuario_id = r.get("usuarioId")

            nome = (
                r.get("usuarioNome")
                or r.get("nomeMotorista")
                or r.get("nomeUsuario")
                or r.get("nome")
            )

            foto = "/static/default_profile.png"
            telefone = ""
            placa_reserva = r.get("placa")

            if usuario_id:
                if usuario_id not in usuarios:
                    u_doc = (
                        database.collection("usuario")
                        .document(usuario_id)
                        .get()
                    )
                    usuarios[usuario_id] = u_doc.to_dict() or {}

                u = usuarios[usuario_id]

                foto = u.get("fotoPerfil") or foto
                telefone = u.get("telefone") or ""

                nome = (
                    nome
                    or u.get("nome")
                    or u.get("usuarioNome")
                    or u.get("nomeMotorista")
                )

                if not placa_reserva:
                    if usuario_id not in veiculos:
                        docs = (
                            database.collection("veiculo")
                            .where("usuarioId", "==", usuario_id)
                            .limit(1)
                            .stream()
                        )

                        veiculos[usuario_id] = next(
                            (v.to_dict() for v in docs),
                            {}
                        ) or {}

                    v = veiculos[usuario_id]

                    placa_reserva = (
                        v.get("placa")
                        or v.get("placaCarro")
                        or v.get("carPlate")
                    )

            return {
                "id": doc.id,
                "placa": placa_reserva or "—",
                "usuario": nome or "Não identificado",
                "telefone": telefone,
                "foto": foto,
                "status": estado,
                "inicio": (
                    inicio.strftime("%d/%m/%Y %H:%M")
                    if inicio else "—"
                ),
                "fim": (
                    fim.strftime("%d/%m/%Y %H:%M")
                    if fim else "—"
                ),
            }

        anteriores = direcao == "anterior" and posicao is not None
        encontrados = []

        while len(encontrados) <= limite:
            pagina_query = consulta

            if posicao is not None:
                pagina_query = pagina_query.start_after(posicao)

            quantidade = limite + 1 - len(encontrados)

            docs = list(
                pagina_query
                .limit(quantidade)
                .stream()
            )

            if not docs:
                break

            for doc in docs:
                r = doc.to_dict() or {}

                estado = str(
                    r.get("status") or "desconhecida"
                ).strip().lower()

                if estado == "finalizada":
                    estado = "concluida"

                if status_filtro and status_filtro.lower() != estado:
                    continue

                inicio = _data(r.get("inicioReserva"))
                fim = _data(r.get("fimReserva"))


                item = None

                if usuario or placa:
                    item = montar_item(
                        doc, r, estado, inicio, fim
                    )

                    if (
                        usuario
                        and usuario.casefold()
                        not in item["usuario"].casefold()
                    ):
                        continue

                    if (
                        placa
                        and placa.casefold()
                        not in item["placa"].casefold()
                    ):
                        continue

                encontrados.append(
                    (doc, r, estado, inicio, fim, item)
                )

            posicao = docs[-1]

            if len(docs) < quantidade:
                break

        existe_mais = len(encontrados) > limite
        selecionados = encontrados[:limite]

        if anteriores:
            selecionados.reverse()

        lista = []

        for doc, r, estado, inicio, fim, item in selecionados:
            item = item or montar_item(
                doc, r, estado, inicio, fim
            )

            vaga_id = r.get("vagaId")

            if vaga_id and vaga_id not in vagas:
                vaga_doc = (
                    database.collection("vaga")
                    .document(vaga_id)
                    .get()
                )

                vagas[vaga_id] = (
                    (vaga_doc.to_dict() or {}).get("numero") or "—"
                )

            item["numero_vaga"] = vagas.get(vaga_id, "—")
            lista.append(item)

        return {
            "reservas": lista,
            "tem_anterior": (
                existe_mais
                if anteriores
                else bool(cursor and lista)
            ),
            "tem_proxima": (
                bool(cursor and lista)
                if anteriores
                else existe_mais
            ),
            "cursor_anterior": lista[0]["id"] if lista else None,
            "cursor_proxima": lista[-1]["id"] if lista else None,
            "limite": limite,
        }

    except HTTPException:
        raise

    except FailedPrecondition as erro:
        _logger.exception("[RESERVAS] Confira o índice estacionamentoId/inicioReserva no Firestore.")
        raise HTTPException(status_code=503, detail="Consulta indisponível. Confira o índice de reservas no terminal da API.") from erro

    except Exception as erro:
        print(f"[RESERVAS] Erro ao consultar reservas: {erro}")

        raise HTTPException(
            status_code=500,
            detail=(
                "Não foi possível consultar as reservas. "
                "Confira o terminal da API."
            )
        )

@router.post("/{reserva_id}/notificar-inicio")
def notificar_inicio_reserva(
    reserva_id: str,
    usuario_logado: dict = Depends(get_usuario_atual),
):
    """Registra o início na central do gestor; chamadas repetidas não duplicam o evento."""
    uid = usuario_logado.get("uid")
    if not uid:
        raise HTTPException(status_code=401, detail="Usuário não identificado.")
    try:
        reserva_doc = database.collection("reserva").document(reserva_id).get()
        if not reserva_doc.exists:
            raise HTTPException(status_code=404, detail="Reserva não encontrada.")
        reserva = reserva_doc.to_dict() or {}
        if reserva.get("usuarioId") != uid:
            raise HTTPException(status_code=403, detail="Sem acesso a esta reserva.")
        estacionamento_id = reserva.get("estacionamentoId")
        vaga_id = reserva.get("vagaId")
        inicio = _data(reserva.get("inicioReserva"))
        if not estacionamento_id or not vaga_id or inicio is None:
            raise HTTPException(status_code=409, detail="Reserva sem vínculo ou data de início válidos.")
        # Timestamp.now() do app usa o relógio do aparelho; tolera pequeno desvio.
        if inicio > datetime.now(FUSO_RESERVAS) + timedelta(seconds=60):
            raise HTTPException(status_code=409, detail="Esta reserva ainda não foi iniciada.")
        estacionamento = database.collection("estacionamento").document(estacionamento_id).get()
        if not estacionamento.exists:
            raise HTTPException(status_code=404, detail="Estacionamento não encontrado.")
        vaga_doc = database.collection("vaga").document(vaga_id).get()
        if not vaga_doc.exists:
            raise HTTPException(status_code=404, detail="Vaga não encontrada.")
        vaga = vaga_doc.to_dict() or {}
        if vaga.get("estacionamentoId") != estacionamento_id:
            raise HTTPException(status_code=409, detail="A vaga não pertence ao estacionamento da reserva.")
        numero = str(vaga.get("numero") or vaga_id)
        notificacao_id = f"reserva_iniciada_{reserva_id}"
        referencia = database.collection("notificacoes_admin").document(notificacao_id)
        dados = {
            "tipo": "reserva_iniciada",
            "titulo": "Reserva iniciada",
            "mensagem": f"Uma reserva foi iniciada na vaga {numero}.",
            "motivo": f"Uma reserva foi iniciada na vaga {numero}.",
            "estacionamentoId": estacionamento_id,
            "vagaId": vaga_id,
            "vagaNumero": numero,
            "usuarioId": uid,
            "reservaId": reserva_id,
            "placa": str(reserva.get("placa") or ""),
            "timestamp": inicio.astimezone(timezone.utc),
            "lida": False,
        }
        try:
            referencia.create(dados)
            criada = True
        except AlreadyExists:
            criada = False
        _logger.info("[RESERVA INICIADA] reserva=%s criada=%s", reserva_id, criada)
        return {"notificacao_id": notificacao_id, "criada": criada}
    except HTTPException:
        raise
    except Exception as erro:
        _logger.exception("[RESERVA INICIADA] Falha ao registrar evento reserva=%s", reserva_id)
        raise HTTPException(status_code=503, detail="Não foi possível registrar a notificação de início.") from erro
