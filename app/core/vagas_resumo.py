"""Cálculo de resumo de vagas com agregações Firestore."""

from google.cloud.firestore_v1.base_query import FieldFilter

from app.core.firebase import db

database = db


def _montar_resumo(
    total: int, disponiveis: int, preferenciais: int, motos: int
) -> dict:
    total = max(0, int(total))
    disponiveis = max(0, min(total, int(disponiveis)))
    preferenciais = max(0, min(total, int(preferenciais)))
    motos = max(0, min(total, int(motos)))
    carros = total - motos

    return {
        "quantidadeVagasTotal": total,
        "vagasDisponiveis": disponiveis,
        "quantidadeVagasCarro": carros,
        "quantidadeVagasMoto": motos,
        "quantidadeVagasPreferencial": preferenciais,
        "possuiVagasMoto": motos > 0,
        "possuiVagasPreferencial": preferenciais > 0,
        "tipoVagasCarro": carros > 0,
        "tipoVagasMoto": motos > 0,
        "tipoVagasPreferencial": preferenciais > 0,
    }


def resumo_vagas(vagas) -> dict:
    """Calcula o resumo a partir de uma lista de vagas já carregada em memória."""
    vagas = list(vagas)
    total = len(vagas)
    disponiveis = sum(1 for vaga in vagas if vaga.get("disponivel", True))
    motos = sum(
        1 for vaga in vagas if str(vaga.get("tipo", "carro")).casefold() == "moto"
    )
    preferenciais = sum(
        1
        for vaga in vagas
        if vaga.get("preferencial") or vaga.get("tipo") == "IdosoPcd"
    )
    return _montar_resumo(total, disponiveis, preferenciais, motos)


def _contar(consulta) -> int:
    """Executa um count() e devolve o valor inteiro."""
    resultado = consulta.count(alias="total").get()
    if not resultado or not resultado[0]:
        return 0
    return int(resultado[0][0].value or 0)


def resumo_vagas_por_consulta(estacionamento_id: str) -> dict:
    """Calcula o resumo sem ler os documentos de vaga."""
    colecao = database.collection("vaga")
    do_estacionamento = colecao.where(
        filter=FieldFilter("estacionamentoId", "==", estacionamento_id)
    )

    total = _contar(do_estacionamento)
    indisponiveis = _contar(
        do_estacionamento.where(filter=FieldFilter("disponivel", "==", False))
    )
    motos = _contar(
        do_estacionamento.where(filter=FieldFilter("tipo", "==", "moto"))
    )
    preferencial_true = _contar(
        do_estacionamento.where(filter=FieldFilter("preferencial", "==", True))
    )
    tipo_idoso = _contar(
        do_estacionamento.where(filter=FieldFilter("tipo", "==", "IdosoPcd"))
    )
    ambos = _contar(
        do_estacionamento.where(
            filter=FieldFilter("preferencial", "==", True)
        ).where(filter=FieldFilter("tipo", "==", "IdosoPcd"))
    )

    preferenciais = preferencial_true + tipo_idoso - ambos
    return _montar_resumo(total, total - indisponiveis, preferenciais, motos)


def atualizar_resumo_estacionamento(estacionamento_id: str):
    """Recalcula e persiste o resumo no documento do estacionamento."""
    resumo = resumo_vagas_por_consulta(estacionamento_id)
    database.collection("estacionamento").document(estacionamento_id).update(resumo)
    return resumo


def sincronizar_resumo(estacionamento_id: str):
    """Versão tolerante a falhas para usar em rotas de escrita de vagas."""
    if not estacionamento_id:
        return None

    try:
        return atualizar_resumo_estacionamento(estacionamento_id)
    except Exception as exc:
        print(f"[vagas_resumo] Falha ao atualizar resumo de {estacionamento_id}: {exc}")
        return None
