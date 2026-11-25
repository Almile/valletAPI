import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.core.horarios_pico import contar_reservas_por_horario

FUSO = ZoneInfo("America/Sao_Paulo")


class HorariosPicoTests(unittest.TestCase):
    def setUp(self):
        self.inicio = datetime(2026, 11, 1, tzinfo=FUSO)
        self.fim = datetime(2026, 12, 1, tzinfo=FUSO)

    def contar(self, reservas):
        return [faixa["total"] for faixa in contar_reservas_por_horario(reservas, self.inicio, self.fim)]

    def reserva(self, inicio, fim, status="ativa"):
        return {"inicioReserva": datetime.fromisoformat(inicio).replace(tzinfo=FUSO),
                "fimReserva": datetime.fromisoformat(fim).replace(tzinfo=FUSO), "status": status}

    def test_intervalo_de_nove_a_doze_tem_fim_exclusivo(self):
        totais = self.contar([self.reserva("2026-11-02T09:00", "2026-11-02T12:00")])
        self.assertEqual(totais[9:13], [1, 1, 1, 0])
        self.assertEqual(sum(totais), 3)

    def test_minutos_parciais_e_sobreposicao(self):
        totais = self.contar([self.reserva("2026-11-02T09:45", "2026-11-02T10:15"),
                              self.reserva("2026-11-02T10:00", "2026-11-02T11:00")])
        self.assertEqual(totais[9:12], [1, 2, 0])

    def test_canceladas_sao_excluidas(self):
        reservas = [self.reserva("2026-11-02T09:00", "2026-11-02T10:00", status)
                    for status in ("cancelada", " CANCELADO ", "concluida")]
        self.assertEqual(self.contar(reservas)[9], 1)

    def test_reserva_iniciada_antes_do_periodo_e_recortada(self):
        totais = self.contar([self.reserva("2026-10-31T23:00", "2026-11-01T02:00")])
        self.assertEqual(totais[:3], [1, 1, 0])
        self.assertEqual(totais[23], 0)

    def test_fim_do_periodo_e_exclusivo(self):
        totais = self.contar([self.reserva("2026-11-30T23:30", "2026-12-01T02:00")])
        self.assertEqual(totais[23], 1)
        self.assertEqual(totais[0], 0)

    def test_acumula_por_data_inclusive_em_reservas_de_varios_dias(self):
        totais = self.contar([self.reserva("2026-11-02T09:00", "2026-11-03T10:00")])
        self.assertEqual(totais[9], 2)
        self.assertEqual(totais[10], 1)

    def test_utc_e_datetime_sem_fuso_sao_convertidos_para_sao_paulo(self):
        reserva = {"inicioReserva": datetime(2026, 11, 2, 12, tzinfo=timezone.utc),
                   "fimReserva": datetime(2026, 11, 2, 13)}
        self.assertEqual(self.contar([reserva])[9], 1)

    def test_datas_ausentes_invalidas_invertidas_e_fora_do_periodo(self):
        reservas = [{}, {"inicioReserva": "invalido", "fimReserva": "invalido"},
                    self.reserva("2026-11-02T12:00", "2026-11-02T09:00"),
                    self.reserva("2026-11-02T12:00", "2026-11-02T12:00"),
                    self.reserva("2026-10-31T10:00", "2026-11-01T00:00"),
                    self.reserva("2026-12-01T00:00", "2026-12-01T01:00")]
        self.assertEqual(sum(self.contar(reservas)), 0)

    def test_vazio_tem_as_vinte_quatro_faixas(self):
        faixas = contar_reservas_por_horario([], self.inicio, self.fim)
        self.assertEqual(len(faixas), 24)
        self.assertEqual(faixas[-1], {"hora": 23, "rotulo": "23h–00h", "total": 0})


if __name__ == "__main__":
    unittest.main()
