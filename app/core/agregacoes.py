"""Helpers para agregações do Firestore.

As funções abaixo evitam carregar documentos apenas para contar ou somar
valores. Elas usam as agregações nativas do Firestore, que são cobradas por
entrada de índice processada em vez de uma leitura completa por documento.
"""

from app.core.firebase import db  # noqa: F401  (mantém o cliente inicializado)


def contar(consulta) -> int:
    """Executa um ``count()`` e devolve o valor inteiro."""
    resultado = consulta.count(alias="total").get()

    if not resultado or not resultado[0]:
        return 0

    return int(resultado[0][0].value or 0)


def somar(consulta, campo: str) -> float:
    """Executa um ``sum()`` e devolve o valor float.

    Pode levantar ``FailedPrecondition`` quando o projeto ainda não possui o
    índice composto exigido pelo Firestore. Quem chama deve tratar esse caso.
    """
    resultado = consulta.sum(campo, alias="soma").get()

    if not resultado or not resultado[0]:
        return 0.0

    return float(resultado[0][0].value or 0.0)
