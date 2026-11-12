import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from fastapi import HTTPException
from app.cancelamento import validar_cancelamento, cancelar_transacao

class CancelamentoTest(unittest.TestCase):
    def setUp(self):
        self.agora = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
        self.r = dict(usuarioId="u", status="ativa", vagaId="v", estacionamentoId="e",
                      inicioReserva=self.agora - timedelta(minutes=9),
                      fimReserva=self.agora + timedelta(hours=1))

    def test_limites(self):
        for segundos, permitido in [(0, True), (599.999, True), (600, False), (601, False)]:
            with self.subTest(segundos=segundos):
                self.r["inicioReserva"] = self.agora - timedelta(seconds=segundos)
                if permitido:
                    validar_cancelamento(self.r, "u", self.agora)
                else:
                    with self.assertRaises(HTTPException):
                        validar_cancelamento(self.r, "u", self.agora)

    def test_renovacao_nao_reabre_janela(self):
        self.r["inicioReserva"] = self.agora - timedelta(minutes=11)
        self.r["fimReserva"] = self.agora + timedelta(hours=4)
        with self.assertRaises(HTTPException):
            validar_cancelamento(self.r, "u", self.agora)

    def test_datas_invalidas(self):
        for inicio in (None, "hoje", datetime(2026, 1, 1), self.agora + timedelta(seconds=1),
                       datetime(1970, 1, 1, tzinfo=timezone.utc)):
            self.r["inicioReserva"] = inicio
            with self.assertRaises(HTTPException):
                validar_cancelamento(self.r, "u", self.agora)

    def test_status_e_proprietario(self):
        with self.assertRaises(HTTPException):
            validar_cancelamento(self.r, "outro", self.agora)
        for status in ("cancelada", "finalizada", "", None):
            self.r["status"] = status
            with self.assertRaises(HTTPException):
                validar_cancelamento(self.r, "u", self.agora)

    def preparar(self):
        db, tx = MagicMock(), MagicMock()
        reserva_ref, vaga_ref = MagicMock(), MagicMock()
        def collection(nome):
            if nome == "reserva":
                col = MagicMock()
                col.document.return_value = reserva_ref
                col.where.return_value.where.return_value.stream.return_value = [MagicMock(id="r")]
                return col
            return MagicMock(document=MagicMock(return_value=vaga_ref))
        db.collection.side_effect = collection
        reserva_ref.get.return_value.to_dict.return_value = self.r
        vaga_ref.get.return_value.to_dict.return_value = dict(disponivel=False, estacionamentoId="e")
        return db, tx, reserva_ref, vaga_ref

    @patch("app.cancelamento.datetime")
    def test_escrita_conjunta(self, clock):
        # Preserva isinstance usado pela política e injeta o instante na transação.
        clock.now.return_value = self.agora
        db, tx, reserva_ref, vaga_ref = self.preparar()
        with patch("app.cancelamento.validar_cancelamento") as validar:
            resultado = cancelar_transacao(tx, db, "r", "u", "v")
            self.assertEqual(validar.call_count, 2)
        self.assertEqual(resultado["status"], "cancelada")
        self.assertEqual(tx.update.call_count, 2)
        tx.update.assert_any_call(reserva_ref, {"status": "cancelada"})
        tx.update.assert_any_call(vaga_ref, {"disponivel": True})

    def test_conflitos_nao_escrevem(self):
        # Simula os snapshots atuais lidos de novo na execução/retry da transação.
        self.r["inicioReserva"] = datetime.now(timezone.utc) - timedelta(minutes=1)
        for dados in (dict(disponivel=True, estacionamentoId="e"),
                      dict(disponivel=False, estacionamentoId="outro"),
                      dict(disponivel=False, estacionamentoId="e", reservaId="outra")):
            db, tx, _, vaga_ref = self.preparar()
            vaga_ref.get.return_value.to_dict.return_value = dados
            with self.assertRaises(HTTPException):
                cancelar_transacao(tx, db, "r", "u", "v")
            tx.update.assert_not_called()

    def test_prazo_expira_entre_leitura_e_escrita(self):
        db, tx, _, _ = self.preparar()
        with patch("app.cancelamento.validar_cancelamento",
                   side_effect=[None, HTTPException(409, "Prazo encerrado")]):
            with self.assertRaises(HTTPException):
                cancelar_transacao(tx, db, "r", "u", "v")
        tx.update.assert_not_called()

    def test_snapshot_terminal_ou_de_outro_dono_nao_escreve(self):
        self.r["inicioReserva"] = datetime.now(timezone.utc) - timedelta(minutes=1)
        for campos in (dict(status="cancelada"), dict(status="finalizada"),
                       dict(usuarioId="outro")):
            original = self.r.copy()
            self.r.update(campos)
            db, tx, _, _ = self.preparar()
            with self.assertRaises(HTTPException):
                cancelar_transacao(tx, db, "r", "u", "v")
            tx.update.assert_not_called()
            self.r = original

    def test_vinculo_mudou_desde_o_clique(self):
        self.r["inicioReserva"] = datetime.now(timezone.utc) - timedelta(minutes=1)
        db, tx, _, _ = self.preparar()
        with self.assertRaises(HTTPException):
            cancelar_transacao(tx, db, "r", "u", "vaga-antiga")
        tx.update.assert_not_called()

    def test_outra_ocupacao_impede_liberacao(self):
        self.r["inicioReserva"] = datetime.now(timezone.utc) - timedelta(minutes=1)
        db, tx, _, _ = self.preparar()
        original = db.collection.side_effect
        def collection(nome):
            col = original(nome)
            if nome == "reserva":
                col.where.return_value.where.return_value.stream.return_value = [MagicMock(id="r"), MagicMock(id="nova")]
            return col
        db.collection.side_effect = collection
        with self.assertRaises(HTTPException):
            cancelar_transacao(tx, db, "r", "u", "v")
        tx.update.assert_not_called()

if __name__ == "__main__":
    unittest.main()
