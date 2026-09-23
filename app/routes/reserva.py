from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from app.valida_token import get_usuario_atual
from app.core.firebase import db

router = APIRouter()
database = db

@router.get("/")
def listar_reservas_estacionamento(
    id_estacionamento: Optional[str] = None,
    placa: Optional[str] = Query(None),
    usuario: Optional[str] = Query(None),
    data_inicio: Optional[str] = Query(None),
    data_fim: Optional[str] = Query(None),
    status_filtro: Optional[str] = Query(None, alias="status"),
    usuario_logado: dict = Depends(get_usuario_atual)
):
    uid = usuario_logado.get("uid")

    try:
        # Se id_estacionamento não foi informado ou for igual ao UID do próprio Admin,
        # busca o ID do documento de estacionamento correto vinculado a este adminUid
        if not id_estacionamento or id_estacionamento.strip() in ["", "None", "null"] or id_estacionamento == uid:
            est_docs = database.collection("estacionamento").where("adminUid", "==", uid).limit(1).stream()
            est_lista = [doc for doc in est_docs]
            if not est_lista:
                return {"reservas": []}
            id_estacionamento = est_lista[0].id  # Pega o ID real do documento do estacionamento

        # Busca reservas usando o ID real do estacionamento
        reservas_ref = database.collection("reserva").where("estacionamentoId", "==", id_estacionamento)
        reservas_docs = list(reservas_ref.stream())

        lista = []

        for doc in reservas_docs:
            r = doc.to_dict()
            res_id = doc.id

            status_reserva = str(r.get("status") or "desconhecida").lower()
            if status_reserva == "finalizada":
                status_reserva = "concluida"

            nome_usuario = r.get("usuarioNome") or r.get("nomeMotorista") or r.get("nomeUsuario") or r.get("nome")
            usuario_id = r.get("usuarioId")
            
            foto = "/static/default_profile.png"
            telefone = ""
            placa_veiculo = r.get("placa")

            if usuario_id:
                try:
                    u_doc = database.collection("usuario").document(usuario_id).get()
                    if u_doc.exists:
                        u = u_doc.to_dict()
                        foto = u.get("fotoPerfil") or foto
                        telefone = u.get("telefone") or ""
                        if not nome_usuario:
                            nome_usuario = u.get("nome") or u.get("usuarioNome") or u.get("nomeMotorista")

                    if not placa_veiculo:
                        veiculos_docs = database.collection("veiculo").where("usuarioId", "==", usuario_id).limit(1).stream()
                        veiculos = [v.to_dict() for v in veiculos_docs]
                        if veiculos:
                            v = veiculos[0]
                            placa_veiculo = v.get("placa") or v.get("placaCarro") or v.get("carPlate")
                except Exception:
                    pass

            inicio_dt, fim_dt = None, None
            try:
                raw_inicio = r.get("inicioReserva")
                raw_fim = r.get("fimReserva")
                
                if hasattr(raw_inicio, "to_datetime"):
                    inicio_dt = raw_inicio.to_datetime()
                elif raw_inicio:
                    inicio_dt = datetime.fromisoformat(str(raw_inicio))

                if hasattr(raw_fim, "to_datetime"):
                    fim_dt = raw_fim.to_datetime()
                elif raw_fim:
                    fim_dt = datetime.fromisoformat(str(raw_fim))
            except Exception:
                pass

            if placa and (not placa_veiculo or placa.lower() not in placa_veiculo.lower()):
                continue

            if usuario and (not nome_usuario or usuario.lower() not in nome_usuario.lower()):
                continue

            if status_filtro and status_filtro.lower() != status_reserva:
                continue

            if data_inicio and inicio_dt:
                dt_ini = datetime.strptime(data_inicio, "%Y-%m-%d").date()
                if inicio_dt.date() < dt_ini:
                    continue

            if data_fim and fim_dt:
                dt_fim = datetime.strptime(data_fim, "%Y-%m-%d").date()
                if fim_dt.date() > dt_fim:
                    continue

            numero_vaga = "—"
            vaga_id = r.get("vagaId")
            if vaga_id:
                try:
                    vaga_doc = database.collection("vaga").document(vaga_id).get()
                    if vaga_doc.exists:
                        numero_vaga = vaga_doc.to_dict().get("numero") or "—"
                except Exception:
                    pass

            lista.append({
                "id": res_id,
                "placa": placa_veiculo or "—",
                "usuario": nome_usuario or "Não identificado",
                "telefone": telefone,
                "foto": foto,
                "status": status_reserva,
                "numero_vaga": numero_vaga,
                "inicio": inicio_dt.strftime("%d/%m/%Y %H:%M") if inicio_dt else "—",
                "fim": fim_dt.strftime("%d/%m/%Y %H:%M") if fim_dt else "—",
                "_sort_key": inicio_dt.isoformat() if inicio_dt else ""
            })

        lista.sort(key=lambda x: x["_sort_key"], reverse=True)

        return {"reservas": lista}

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao consultar reservas: {str(e)}"
        )