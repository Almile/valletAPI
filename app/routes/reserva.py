from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from firebase_admin import firestore
from google.cloud.firestore import Query as FirestoreQuery
from google.cloud.firestore_v1.base_query import FieldFilter
from google.api_core.exceptions import AlreadyExists, FailedPrecondition
from app.models.schemas import ReservaCriar, ReservaEstender
from app.valida_token import get_usuario_atual
from app.core.firebase import db
from app.core.vagas_resumo import sincronizar_resumo

from app.cancelamento import executar_cancelamento

router = APIRouter()


@router.post("/{reserva_id}/cancelar")
def cancelar_reserva(
    reserva_id: str,
    vaga_id: Optional[str] = Query(
        None, min_length=1, pattern=r"^[^/]+$",
        description="Opcional; quando omitido, é obtido da própria reserva.",
    ),
    usuario_logado: dict = Depends(get_usuario_atual),
):
    uid = usuario_logado.get("uid")
    if not uid:
        raise HTTPException(401, "Usuário não identificado.")
    if not reserva_id or "/" in reserva_id:
        raise HTTPException(400, "Identificador de reserva inválido.")
    try:
        # Mantém compatibilidade com o app antigo, que envia vaga_id, e permite
        # que novos clientes cancelem informando apenas o ID da reserva.
        if not vaga_id:
            reserva_doc = database.collection("reserva").document(reserva_id).get()
            if not reserva_doc.exists:
                raise HTTPException(404, "Reserva não encontrada.")
            dados_reserva = reserva_doc.to_dict() or {}
            if dados_reserva.get("usuarioId") != uid:
                raise HTTPException(403, "Sem acesso a esta reserva.")
            vaga_id = dados_reserva.get("vagaId")
            if not isinstance(vaga_id, str) or not vaga_id or "/" in vaga_id:
                raise HTTPException(409, "Reserva sem vínculo de vaga válido.")

        resultado = executar_cancelamento(
            database.transaction(), database, reserva_id, uid, vaga_id
        )
        sincronizar_resumo(resultado.get("estacionamentoId"))
        return resultado
    except HTTPException:
        raise
    except Exception as erro:
        _logger.exception("Falha ao cancelar reserva")
        raise HTTPException(503, "Não foi possível confirmar o cancelamento. Tente novamente.") from erro

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


def _utc(valor):
    data = _data(valor)
    return data.astimezone(timezone.utc) if data else None


def _normalizar_status(valor) -> str:
    estado = str(valor or "").strip().lower()
    if estado in ("finalizada", "concluída", "concluido"):
        return "concluida"
    if estado in ("cancelado",):
        return "cancelada"
    return estado


def _buscar_documentos(colecao: str, ids) -> dict:
    ids = [str(i) for i in ids if i]
    if not ids:
        return {}
    referencias = [database.collection(colecao).document(i) for i in ids]
    return {
        doc.id: (doc.to_dict() or {})
        for doc in database.get_all(referencias)
        if doc.exists
    }


def _obter_placa(uid: str, placa_informada: Optional[str]) -> str:
    if placa_informada:
        return placa_informada.strip().upper()
    try:
        veiculos = list(
            database.collection("veiculo")
            .where(filter=FieldFilter("usuarioId", "==", uid))
            .stream()
        )
        if not veiculos:
            return ""
        escolhido = None
        for doc in veiculos:
            dados = doc.to_dict() or {}
            if dados.get("padrao") is True:
                escolhido = dados
                break
        escolhido = escolhido or (veiculos[0].to_dict() or {})
        return str(
            escolhido.get("placa")
            or escolhido.get("placaCarro")
            or escolhido.get("carPlate")
            or ""
        ).strip().upper()
    except Exception as erro:
        _logger.warning("[RESERVAS] Não foi possível obter a placa padrão: %s", erro)
        return ""


@firestore.transactional
def _criar_reserva_transacao(
    transaction,
    database,
    reserva_id: str,
    uid: str,
    usuario: dict,
    vaga_id: str,
    estacionamento_esperado: Optional[str],
    inicio: datetime,
    fim: datetime,
    placa: str,
):
    """Reserva a vaga de forma atômica, evitando duas reservas simultâneas."""
    agora = datetime.now(timezone.utc)
    vaga_ref = database.collection("vaga").document(vaga_id)
    vaga_doc = vaga_ref.get(transaction=transaction)

    if not vaga_doc.exists:
        raise HTTPException(404, "Vaga não encontrada.")

    vaga = vaga_doc.to_dict() or {}
    estacionamento_id = vaga.get("estacionamentoId")
    if not estacionamento_id:
        raise HTTPException(409, "A vaga não está vinculada a um estacionamento.")
    if estacionamento_esperado and estacionamento_esperado != estacionamento_id:
        raise HTTPException(409, "A vaga não pertence ao estacionamento informado.")
    if vaga.get("disponivel") is False:
        raise HTTPException(409, "Esta vaga já está ocupada ou reservada.")

    est_doc = (
        database.collection("estacionamento")
        .document(estacionamento_id)
        .get(transaction=transaction)
    )
    if not est_doc.exists:
        raise HTTPException(404, "Estacionamento não encontrado.")

    estacionamento = est_doc.to_dict() or {}

    tolerancia = estacionamento.get("toleranciaReservaMinutos", 10)
    try:
        tolerancia = max(0, int(tolerancia))
    except (TypeError, ValueError):
        tolerancia = 10
    if inicio < agora - timedelta(minutes=tolerancia):
        raise HTTPException(400, "A reserva não pode começar no passado.")

    max_horas = estacionamento.get("tempoMaxReservaHoras")
    try:
        max_horas = 2.0 if max_horas is None else float(max_horas)
    except (TypeError, ValueError):
        max_horas = 2.0

    duracao_horas = (fim - inicio).total_seconds() / 3600
    if duracao_horas <= 0:
        raise HTTPException(400, "O fim da reserva deve ser posterior ao início.")
    if max_horas > 0 and duracao_horas > max_horas + 1e-6:
        raise HTTPException(
            400,
            f"A reserva excede o tempo máximo de {max_horas:g} hora(s) deste estacionamento.",
        )

    try:
        valor_hora = float(vaga.get("preco") or estacionamento.get("valorHora") or 0)
    except (TypeError, ValueError):
        valor_hora = 0.0
    valor_hora = max(0.0, valor_hora)
    valor_total = round(valor_hora * duracao_horas, 2)

    reserva_ref = database.collection("reserva").document(reserva_id)
    dados = {
        "usuarioId": uid,
        "usuarioNome": usuario.get("nome") or usuario.get("usuarioNome") or "",
        "usuarioEmail": usuario.get("email") or "",
        "estacionamentoId": estacionamento_id,
        "estacionamentoNome": estacionamento.get("nome") or "",
        "vagaId": vaga_id,
        "vagaNumero": str(vaga.get("numero") or ""),
        "placa": placa,
        "inicioReserva": inicio.astimezone(timezone.utc),
        "fimReserva": fim.astimezone(timezone.utc),
        "duracaoHoras": round(duracao_horas, 2),
        "valorHora": valor_hora,
        "valorTotal": valor_total,
        "status": "ativa",
        "dataCriacao": firestore.SERVER_TIMESTAMP,
    }

    transaction.set(reserva_ref, dados)
    transaction.update(
        vaga_ref,
        {"disponivel": False, "reservaId": reserva_id},
    )
    return dados


@firestore.transactional
def _estender_reserva_transacao(
    transaction,
    database,
    reserva_id: str,
    uid: str,
    fim_reserva: Optional[datetime],
    horas_adicionais: Optional[float],
    minutos_adicionais: Optional[int],
):
    agora = datetime.now(timezone.utc)
    reserva_ref = database.collection("reserva").document(reserva_id)
    reserva_doc = reserva_ref.get(transaction=transaction)

    if not reserva_doc.exists:
        raise HTTPException(404, "Reserva não encontrada.")

    reserva = reserva_doc.to_dict() or {}
    if reserva.get("usuarioId") != uid:
        raise HTTPException(403, "Sem acesso a esta reserva.")
    if _normalizar_status(reserva.get("status")) != "ativa":
        raise HTTPException(409, "A reserva não está ativa.")

    inicio = _utc(reserva.get("inicioReserva"))
    fim_atual = _utc(reserva.get("fimReserva"))
    if inicio is None:
        raise HTTPException(409, "Reserva sem data de início válida.")

    base = max(fim_atual, agora) if fim_atual else agora

    if fim_reserva is not None:
        novo_fim = (
            fim_reserva.replace(tzinfo=FUSO_RESERVAS)
            if fim_reserva.tzinfo is None
            else fim_reserva
        ).astimezone(timezone.utc)
    else:
        acrescimo = timedelta(
            hours=horas_adicionais or 0,
            minutes=minutos_adicionais or 0,
        )
        if acrescimo <= timedelta(0):
            raise HTTPException(400, "Informe um tempo adicional maior que zero.")
        novo_fim = base + acrescimo

    if novo_fim <= base:
        raise HTTPException(400, "O novo fim deve ser posterior ao horário atual da reserva.")

    estacionamento_id = reserva.get("estacionamentoId")
    est_doc = None
    if estacionamento_id:
        est_doc = (
            database.collection("estacionamento")
            .document(estacionamento_id)
            .get(transaction=transaction)
        )
    estacionamento = (est_doc.to_dict() or {}) if est_doc and est_doc.exists else {}

    max_horas = estacionamento.get("tempoMaxReservaHoras")
    try:
        max_horas = 2.0 if max_horas is None else float(max_horas)
    except (TypeError, ValueError):
        max_horas = 2.0

    duracao_horas = (novo_fim - inicio).total_seconds() / 3600
    if max_horas > 0 and duracao_horas > max_horas + 1e-6:
        raise HTTPException(
            400,
            f"A reserva excede o tempo máximo de {max_horas:g} hora(s) deste estacionamento.",
        )

    try:
        valor_hora = float(
            reserva.get("valorHora") or estacionamento.get("valorHora") or 0
        )
    except (TypeError, ValueError):
        valor_hora = 0.0
    valor_hora = max(0.0, valor_hora)
    valor_total = round(valor_hora * duracao_horas, 2)

    transaction.update(
        reserva_ref,
        {
            "fimReserva": novo_fim,
            "duracaoHoras": round(duracao_horas, 2),
            "valorHora": valor_hora,
            "valorTotal": valor_total,
            "dataAtualizacao": firestore.SERVER_TIMESTAMP,
        },
    )

    return {
        "id": reserva_id,
        "usuarioId": uid,
        "vagaId": reserva.get("vagaId"),
        "estacionamentoId": estacionamento_id,
        "inicioReserva": inicio,
        "fimReserva": novo_fim,
        "duracaoHoras": round(duracao_horas, 2),
        "valorHora": valor_hora,
        "valorTotal": valor_total,
        "status": "ativa",
    }


@router.post("/criar", status_code=201)
def criar_reserva(
    dados: ReservaCriar,
    usuario_logado: dict = Depends(get_usuario_atual),
):
    """
    Cria uma reserva de vaga para o motorista autenticado.

    Aceita ``fimReserva`` ou ``duracaoHoras``. A vaga fica indisponível de
    imediato e a operação é transacional para evitar reservas duplicadas.
    """
    uid = usuario_logado.get("uid")
    if not uid:
        raise HTTPException(401, "Usuário não identificado.")

    usuario_doc = database.collection("usuario").document(uid).get()
    if not usuario_doc.exists:
        raise HTTPException(404, "Perfil de usuário não encontrado.")
    usuario = usuario_doc.to_dict() or {}

    inicio = dados.inicioReserva or datetime.now(timezone.utc)
    if inicio.tzinfo is None:
        inicio = inicio.replace(tzinfo=FUSO_RESERVAS)

    if dados.fimReserva is not None:
        fim = dados.fimReserva
        if fim.tzinfo is None:
            fim = fim.replace(tzinfo=FUSO_RESERVAS)
    else:
        fim = inicio + timedelta(hours=float(dados.duracaoHoras))

    if fim <= inicio:
        raise HTTPException(400, "O fim da reserva deve ser posterior ao início.")

    reserva_id = database.collection("reserva").document().id
    placa = _obter_placa(uid, dados.placa)

    try:
        dados_reserva = _criar_reserva_transacao(
            database.transaction(),
            database,
            reserva_id,
            uid,
            usuario,
            dados.vagaId,
            dados.estacionamentoId,
            inicio,
            fim,
            placa,
        )
    except HTTPException:
        raise
    except Exception as erro:
        _logger.exception("[RESERVAS] Falha ao criar reserva")
        raise HTTPException(503, "Não foi possível criar a reserva. Tente novamente.") from erro

    sincronizar_resumo(dados_reserva.get("estacionamentoId"))

    resposta = {
        **dados_reserva,
        "id": reserva_id,
        "dataCriacao": datetime.now(timezone.utc),
    }
    return resposta


@router.get("/historico")
def historico_reservas(
    status_filtro: Optional[str] = Query(None, alias="status"),
    limite: int = Query(20, ge=1, le=50),
    cursor: Optional[str] = Query(None),
    usuario_logado: dict = Depends(get_usuario_atual),
):
    """
    Histórico de reservas do usuário autenticado, das mais recentes para as
    mais antigas. O cursor é o ID da última reserva recebida.
    """
    uid = usuario_logado.get("uid")
    if not uid:
        raise HTTPException(401, "Usuário não identificado.")
    if cursor and "/" in cursor:
        raise HTTPException(400, "Cursor inválido.")

    status_busca = _normalizar_status(status_filtro) if status_filtro else None
    agora = datetime.now(FUSO_RESERVAS)

    try:
        consulta = (
            database.collection("reserva")
            .where(filter=FieldFilter("usuarioId", "==", uid))
            .order_by("inicioReserva", direction=FirestoreQuery.DESCENDING)
            .order_by("__name__", direction=FirestoreQuery.DESCENDING)
        )

        posicao = None
        if cursor:
            posicao = database.collection("reserva").document(cursor).get()
            dados_cursor = posicao.to_dict() or {}
            if (
                not posicao.exists
                or dados_cursor.get("usuarioId") != uid
                or not dados_cursor.get("inicioReserva")
            ):
                raise HTTPException(400, "Cursor inválido ou expirado.")

        encontrados = []
        lidos = 0
        MAX_LEITURA = 500

        while len(encontrados) <= limite and lidos < MAX_LEITURA:
            pagina = consulta
            if posicao is not None:
                pagina = pagina.start_after(posicao)

            quantidade = limite + 1 - len(encontrados)
            docs = list(pagina.limit(quantidade).stream())
            if not docs:
                break

            lidos += len(docs)
            for doc in docs:
                dados = doc.to_dict() or {}
                estado = _normalizar_status(dados.get("status"))
                if status_busca and estado != status_busca:
                    continue
                encontrados.append((doc, dados, estado))

            posicao = docs[-1]
            if len(docs) < quantidade:
                break

        tem_proxima = len(encontrados) > limite
        selecionados = encontrados[:limite]

        estacionamentos = _buscar_documentos(
            "estacionamento",
            {d.get("estacionamentoId") for _, d, _ in selecionados},
        )
        vagas = _buscar_documentos(
            "vaga",
            {d.get("vagaId") for _, d, _ in selecionados},
        )

        reservas = []
        for doc, dados, estado in selecionados:
            inicio = _data(dados.get("inicioReserva"))
            fim = _data(dados.get("fimReserva"))
            criada_em = _data(dados.get("dataCriacao"))

            estacionamento_id = dados.get("estacionamentoId")
            vaga_id = dados.get("vagaId")
            estacionamento = estacionamentos.get(estacionamento_id) or {}
            vaga = vagas.get(vaga_id) or {}

            try:
                valor_total = round(float(dados.get("valorTotal") or 0), 2)
            except (TypeError, ValueError):
                valor_total = 0.0

            pode_cancelar = bool(
                estado == "ativa"
                and inicio is not None
                and inicio <= agora
                and (agora - inicio) < timedelta(minutes=10)
            )

            reservas.append({
                "id": doc.id,
                "estacionamentoId": estacionamento_id,
                "estacionamentoNome": (
                    dados.get("estacionamentoNome")
                    or estacionamento.get("nome")
                    or ""
                ),
                "vagaId": vaga_id,
                "vagaNumero": (
                    dados.get("vagaNumero")
                    or dados.get("numeroVaga")
                    or vaga.get("numero")
                    or ""
                ),
                "placa": dados.get("placa") or "",
                "status": estado,
                "inicioReserva": inicio.isoformat() if inicio else None,
                "fimReserva": fim.isoformat() if fim else None,
                "dataCriacao": criada_em.isoformat() if criada_em else None,
                "valorTotal": valor_total,
                "podeCancelar": pode_cancelar,
                "podeEstender": estado == "ativa",
            })

        return {
            "reservas": reservas,
            "quantidade": len(reservas),
            "tem_proxima": tem_proxima,
            "cursor_proxima": selecionados[-1][0].id if selecionados else None,
            "limite": limite,
        }

    except HTTPException:
        raise
    except FailedPrecondition as erro:
        _logger.exception(
            "[RESERVAS] Confira o índice usuarioId/inicioReserva no Firestore."
        )
        raise HTTPException(
            503,
            "Consulta indisponível. Confira o índice de histórico de reservas no Firestore.",
        ) from erro
    except Exception as erro:
        _logger.exception("[RESERVAS] Falha ao consultar histórico")
        raise HTTPException(
            503, "Não foi possível consultar o histórico de reservas."
        ) from erro


@router.patch("/{reserva_id}/estender")
def estender_reserva(
    reserva_id: str,
    dados: ReservaEstender,
    usuario_logado: dict = Depends(get_usuario_atual),
):
    """Aumenta o tempo de uma reserva ativa do usuário autenticado."""
    uid = usuario_logado.get("uid")
    if not uid:
        raise HTTPException(401, "Usuário não identificado.")
    if not reserva_id or "/" in reserva_id:
        raise HTTPException(400, "Identificador de reserva inválido.")

    try:
        return _estender_reserva_transacao(
            database.transaction(),
            database,
            reserva_id,
            uid,
            dados.fimReserva,
            dados.horasAdicionais,
            dados.minutosAdicionais,
        )
    except HTTPException:
        raise
    except Exception as erro:
        _logger.exception("[RESERVAS] Falha ao estender reserva")
        raise HTTPException(
            503, "Não foi possível atualizar a reserva. Tente novamente."
        ) from erro


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
