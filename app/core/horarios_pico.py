"""Contagem de reservas por faixa horária, acumulada nas datas do período."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

FUSO = ZoneInfo("America/Sao_Paulo")


def _instante(valor):
    if hasattr(valor, "to_datetime"):
        valor = valor.to_datetime()
    if not isinstance(valor, datetime):
        return None
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=timezone.utc)
    return valor.astimezone(timezone.utc)


def contar_reservas_por_horario(reservas, inicio_periodo, fim_periodo):
    """Cada reserva conta uma vez por data/faixa cruzada, com fim exclusivo.

    Intervalos são recortados ao período. Canceladas e horários incompletos ou
    inválidos não entram. Não mede ocupação física nem pico simultâneo instantâneo.
    """
    inicio_periodo = _instante(inicio_periodo)
    fim_periodo = _instante(fim_periodo)
    totais = [0] * 24
    for reserva in reservas:
        status = str(reserva.get("status") or "").strip().lower()
        if status in ("cancelada", "cancelado"):
            continue
        inicio = _instante(reserva.get("inicioReserva"))
        fim = _instante(reserva.get("fimReserva"))
        if inicio is None or fim is None or fim <= inicio:
            continue
        inicio, fim = max(inicio, inicio_periodo), min(fim, fim_periodo)
        if inicio >= fim:
            continue
        faixa = inicio.astimezone(FUSO).replace(minute=0, second=0, microsecond=0)
        faixa = faixa.astimezone(timezone.utc)
        vistas = set()
        while faixa < fim:
            local = faixa.astimezone(FUSO)
            # Uma hora repetida pelo horário de verão conta uma vez por data.
            chave = (local.date(), local.hour)
            if chave not in vistas:
                totais[local.hour] += 1
                vistas.add(chave)
            faixa += timedelta(hours=1)
    return [
        {"hora": hora, "rotulo": f"{hora:02d}h–{(hora + 1) % 24:02d}h", "total": total}
        for hora, total in enumerate(totais)
    ]
