import time as _time
import logging
from collections import OrderedDict
from concurrent.futures import Future
from copy import deepcopy
from datetime import datetime, time, timedelta, timezone
from threading import RLock
from typing import Optional, Dict, Any, Literal
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from google.api_core.exceptions import FailedPrecondition
from google.cloud.firestore import Query as FirestoreQuery
from google.cloud.firestore_v1.base_query import FieldFilter
from app.valida_token import get_usuario_atual
from app.core.firebase import db
from app.core.agregacoes import contar, somar
from app.core.horarios_pico import contar_reservas_por_horario
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

# A rota antiga permanece disponível até a migração do desktop.
# Este cache é exclusivo da nova rota de reservas, sem valores financeiros.
FUSO_DASHBOARD = ZoneInfo("America/Sao_Paulo")
CACHE_RESERVAS_TTL = 60
CACHE_RESERVAS_MAX = 128
_cache_reservas = OrderedDict()
_consultas_reservas_em_andamento = {}
_cache_reservas_lock = RLock()
_logger = logging.getLogger(__name__)


def _resolver_periodo_reservas(periodo, ano, mes, agora):
    hoje = agora.astimezone(FUSO_DASHBOARD).date()

    if periodo != "mes" and (ano is not None or mes is not None):
        raise HTTPException(
            status_code=422,
            detail="Use ano e mes somente com periodo=mes.",
        )

    if periodo == "ultimos_7_dias":
        # Sete datas de calendário, incluindo hoje (não sete dias + hoje).
        inicio_data = hoje - timedelta(days=6)
        fim_data = hoje + timedelta(days=1)
    else:
        if periodo == "mes" and (ano is None or mes is None):
            raise HTTPException(
                status_code=422,
                detail="Para periodo=mes, informe ano e mes.",
            )
        inicio_data = hoje.replace(day=1)
        if periodo == "mes":
            inicio_data = inicio_data.replace(year=ano, month=mes)
        fim_data = (inicio_data.replace(day=28) + timedelta(days=4)).replace(day=1)

    inicio = datetime.combine(inicio_data, time.min, tzinfo=FUSO_DASHBOARD)
    fim = datetime.combine(fim_data, time.min, tzinfo=FUSO_DASHBOARD)
    return inicio, fim


def _data_dashboard(valor):
    """Firestore representa timestamps em UTC, inclusive datetimes sem fuso."""
    if hasattr(valor, "to_datetime"):
        valor = valor.to_datetime()
    if not isinstance(valor, datetime):
        return None
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=timezone.utc)
    return valor.astimezone(FUSO_DASHBOARD)


def _situacao_dashboard(dados, agora):
    estado = str(dados.get("status") or "").strip().lower()
    if estado in STATUS_CANCELADAS:
        return "canceladas"
    if estado in ("concluida", "finalizada"):
        return "concluidas"
    if estado == "aguardando_pagamento":
        return "aguardando_pagamento"
    if estado == "pendente":
        return "pendentes"
    if estado in ("ativa", "agendada", "confirmada"):
        fim = _data_dashboard(dados.get("fimReserva"))
        inicio = _data_dashboard(dados.get("inicioReserva"))
        if fim is not None:
            return "confirmadas" if fim > agora else "horario_encerrado"
        if inicio is not None and inicio >= agora:
            return "confirmadas"
        return "outros"
    return "outros"


def _autorizar_dashboard_reservas(uid, id_estacionamento):
    if not uid:
        raise HTTPException(status_code=401, detail="Usuário não identificado.")
    if not id_estacionamento or not id_estacionamento.strip():
        docs = (
            database.collection("estacionamento")
            .where(filter=FieldFilter("adminUid", "==", uid))
            .limit(1)
            .stream()
        )
        documento = next(iter(docs), None)
        if documento is None:
            raise HTTPException(
                status_code=404,
                detail="Nenhum estacionamento associado a este usuário foi encontrado.",
            )
        return documento.id

    documento = database.collection("estacionamento").document(id_estacionamento).get()
    if not documento.exists:
        raise HTTPException(status_code=404, detail="Estacionamento não encontrado.")
    if (documento.to_dict() or {}).get("adminUid") != uid:
        perfil = database.collection("usuario").document(uid).get()
        if not perfil.exists or (perfil.to_dict() or {}).get("tipo_user") != "superadmin":
            raise HTTPException(status_code=403, detail="Sem acesso a este estacionamento.")
    return documento.id

def _consultar_reservas_periodo(id_estacionamento, inicio, fim, agora):
    avisos = {}
    rotulos = {
        "confirmadas": "Confirmadas",
        "concluidas": "Concluídas (status registrado)",
        "canceladas": "Canceladas",
        "horario_encerrado": "Horário encerrado sem conclusão",
        "aguardando_pagamento": "Aguardando pagamento",
        "pendentes": "Pendentes",
        "outros": "Outros",
    }
    contagens = dict.fromkeys(rotulos, 0)
    por_dia = OrderedDict()
    faturamento_por_dia = OrderedDict()

    por_horario = [0] * 24

    dia = inicio.date()
    while dia < fim.date():
        data_str = dia.isoformat()
        por_dia[data_str] = {"total": 0, **dict.fromkeys(rotulos, 0)}
        faturamento_por_dia[data_str] = 0.0
        dia += timedelta(days=1)

    consulta = (
        database.collection("reserva")
        .where(filter=FieldFilter("estacionamentoId", "==", id_estacionamento))
        .where(filter=FieldFilter("inicioReserva", ">=", inicio.astimezone(timezone.utc)))
        .where(filter=FieldFilter("inicioReserva", "<", fim.astimezone(timezone.utc)))
        .order_by("inicioReserva")
        .select(["inicioReserva", "fimReserva", "status", "valorTotal"])
    )

    faturamento_total = 0.0

    for documento in consulta.stream(retry=None, timeout=30):
        dados = documento.to_dict() or {}
        data = _data_dashboard(dados.get("inicioReserva"))
        if data is None or not inicio <= data < fim:
            continue

        situacao = _situacao_dashboard(dados, agora)
        contagens[situacao] += 1

        data_str = data.date().isoformat()
        linha = por_dia[data_str]
        linha["total"] += 1
        linha[situacao] += 1

        if situacao != "canceladas":
            por_horario[data.hour] += 1

        valor_reserva = float(dados.get("valorTotal", 0.0) or 0.0)
        faturamento_total += valor_reserva
        if data_str in faturamento_por_dia:
            faturamento_por_dia[data_str] += valor_reserva

    horarios = [
        {
            "hora": h,
            "rotulo": f"{h:02d}h–{(h + 1) % 24:02d}h",
            "total": por_horario[h],
        }
        for h in range(24)
    ]

    return {
        "avisos": avisos,
        "id_estacionamento": id_estacionamento,
        "periodo": {
            "inicio": inicio.date().isoformat(),
            "fim": (fim.date() - timedelta(days=1)).isoformat(),
            "fim_exclusivo": fim.isoformat(),
            "fuso": "America/Sao_Paulo",
            "campo_data": "inicioReserva",
        },
        "resumo": {
            "total": sum(contagens.values()),
            "faturamento_total": round(faturamento_total, 2),
            **contagens
        },
        "graficos": {
            "reservas_por_horario": horarios,
            "reservas_por_dia": [
                {"data": data, **contagem} for data, contagem in por_dia.items()
            ],
            "faturamento_por_dia": [
                {"data": data, "valor": round(val, 2)} for data, val in faturamento_por_dia.items()
            ],
            "situacao_reservas": [
                {"status": estado, "rotulo": rotulo, "total": contagens[estado]}
                for estado, rotulo in rotulos.items()
            ],
            "reservas_por_horario": horarios,
        },
        "criterios": {
            "horarios_pico": "Reservas não canceladas que cruzam cada faixa de uma hora, acumuladas por data no período; fim exclusivo. Horários inválidos ou incompletos ficam fora.",
            "confirmadas": "Ativas, agendadas ou confirmadas com horário ainda válido.",
            "concluidas": "Status concluida ou finalizada; pagamento ainda não validado.",
            "horario_encerrado": "Horário encerrado com status ativo, sem alterar a reserva.",
            "periodo": "Reserva pertence ao período pela data de início, no fuso de São Paulo.",
        },
        "gerado_em": agora.isoformat(),
    }

def _reservas_com_cache(id_estacionamento, inicio, fim):
    chave = (id_estacionamento, inicio.isoformat(), fim.isoformat())
    with _cache_reservas_lock:
        agora_monotonic = _time.monotonic()
        expiradas = [k for k, (limite, _) in _cache_reservas.items() if limite <= agora_monotonic]
        for k in expiradas:
            del _cache_reservas[k]
        entrada = _cache_reservas.get(chave)
        if entrada is not None:
            _cache_reservas.move_to_end(chave)
            limite, dados = entrada
            return deepcopy(dados), True, max(0, int(limite - agora_monotonic))
        futura = _consultas_reservas_em_andamento.get(chave)
        responsavel = futura is None
        if responsavel:
            futura = Future()
            _consultas_reservas_em_andamento[chave] = futura

    if not responsavel:
        # Duas requisições simultâneas do mesmo período compartilham a leitura.
        dados, limite = futura.result()
        return deepcopy(dados), True, max(0, int(limite - _time.monotonic()))

    try:
        dados = _consultar_reservas_periodo(
            id_estacionamento, inicio, fim, datetime.now(FUSO_DASHBOARD)
        )
        limite = _time.monotonic() + CACHE_RESERVAS_TTL
        with _cache_reservas_lock:
            _cache_reservas[chave] = (limite, dados)
            _cache_reservas.move_to_end(chave)
            while len(_cache_reservas) > CACHE_RESERVAS_MAX:
                _cache_reservas.popitem(last=False)
        futura.set_result((dados, limite))
        return deepcopy(dados), False, CACHE_RESERVAS_TTL
    except Exception as exc:
        futura.set_exception(exc)
        raise
    finally:
        with _cache_reservas_lock:
            _consultas_reservas_em_andamento.pop(chave, None)


@router.get("/dashboard/ocupacao")
@router.get("/{id_estacionamento}/dashboard/ocupacao")
def obter_dashboard_ocupacao(
    response: Response,
    id_estacionamento: Optional[str] = None,
    usuario_logado: dict = Depends(get_usuario_atual),
):
    """Retrato atual das vagas, sem carregar reservas ou calcular faturamento."""
    response.headers["Cache-Control"] = "no-store"
    try:
        estacionamento_id = _autorizar_dashboard_reservas(
            usuario_logado.get("uid"), id_estacionamento
        )
        consulta = database.collection("vaga").where(
            filter=FieldFilter("estacionamentoId", "==", estacionamento_id)
        )
        total = max(0, contar(consulta))
        ocupadas = max(0, min(total, contar(consulta.where(
            filter=FieldFilter("disponivel", "==", False)
        ))))
        return {
            "id_estacionamento": estacionamento_id,
            "vagas_total": total,
            "vagas_ocupadas": ocupadas,
            "vagas_disponiveis": total - ocupadas,
            "consultado_em": datetime.now(FUSO_DASHBOARD).isoformat(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        _logger.exception("[DASHBOARD OCUPAÇÃO] Falha ao consultar vagas.")
        raise HTTPException(
            status_code=503,
            detail="Não foi possível consultar a ocupação atual.",
        ) from exc


@router.get("/dashboard/reservas")
@router.get("/{id_estacionamento}/dashboard/reservas")
def obter_dashboard_reservas(
    response: Response,
    id_estacionamento: Optional[str] = None,
    periodo: Literal["ultimos_7_dias", "mes_atual", "mes"] = "mes_atual",
    ano: Optional[int] = Query(None, ge=1900, le=9998),
    mes: Optional[int] = Query(None, ge=1, le=12),
    usuario_logado: dict = Depends(get_usuario_atual),
):
    """Dados de reservas para gráficos; não calcula faturamento ou ocupação."""
    response.headers["Cache-Control"] = "no-store"
    inicio, fim = _resolver_periodo_reservas(
        periodo, ano, mes, datetime.now(FUSO_DASHBOARD)
    )
    try:
        # Autoriza antes do cache para nunca reutilizar dados sem validar acesso.
        estacionamento_id = _autorizar_dashboard_reservas(
            usuario_logado.get("uid"), id_estacionamento
        )
        dados, reutilizado, expira_em = _reservas_com_cache(estacionamento_id, inicio, fim)
        dados["periodo"]["tipo"] = periodo
        dados["cache"] = {
            "reutilizado": reutilizado,
            "validade_segundos": CACHE_RESERVAS_TTL,
            "expira_em_segundos": expira_em,
        }
        return dados
    except HTTPException:
        raise
    except FailedPrecondition as exc:
        _logger.exception("[DASHBOARD RESERVAS] Consulta indisponível; confira o índice Firestore.")
        raise HTTPException(
            status_code=503,
            detail="Consulta indisponível. Confira o índice de reserva no terminal da API e em firestore.indexes.json.",
        ) from exc
    except Exception as exc:
        _logger.exception("[DASHBOARD RESERVAS] Falha ao consultar o período selecionado.")
        raise HTTPException(
            status_code=503,
            detail="Não foi possível carregar as reservas do período. Tente novamente em instantes.",
        ) from exc


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
