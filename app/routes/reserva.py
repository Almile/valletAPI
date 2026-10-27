from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from google.cloud.firestore import Query as FirestoreQuery
from app.valida_token import get_usuario_atual
from app.core.firebase import db

router = APIRouter()
database = db


def _data(valor):
    if isinstance(valor, datetime):
        return valor

    if hasattr(valor, "to_datetime"):
        return valor.to_datetime()

    if valor:
        try:
            return datetime.fromisoformat(str(valor))
        except ValueError:
            pass

    return None


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

        consulta = (
            referencia
            .where("estacionamentoId", "==", id_estacionamento)
            .order_by("inicioReserva", direction=sentido)
            .order_by("__name__", direction=sentido)
        )

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

                if inicio_filtro and (
                    inicio is None or inicio.date() < inicio_filtro
                ):
                    continue

                if fim_filtro and (
                    fim is None or fim.date() > fim_filtro
                ):
                    continue

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

    except Exception as erro:
        print(f"[RESERVAS] Erro ao consultar reservas: {erro}")

        raise HTTPException(
            status_code=500,
            detail=(
                "Não foi possível consultar as reservas. "
                "Confira o terminal da API."
            )
        )