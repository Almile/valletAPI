from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from app.valida_token import get_usuario_atual
from app.core.firebase import db

# Instância do router e database
router = APIRouter()
database = db

@router.get("/{id_estacionamento}/reservas/")
@router.get("/reservas/")
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
        # 1. Se id_estacionamento não for informado, busca o primeiro vinculado ao admin logado
        if not id_estacionamento or id_estacionamento.strip() == "":
            est_docs = database.collection("estacionamento").where("adminUid", "==", uid).limit(1).stream()
            est_lista = [doc for doc in est_docs]
            if not est_lista:
                return {"reservas": []}
            id_estacionamento = est_lista[0].id

        # 2. Busca reservas do estacionamento
        reservas_ref = database.collection("reserva").where("estacionamentoId", "==", id_estacionamento)
        reservas_docs = list(reservas_ref.stream())

        lista = []

        for doc in reservas_docs:
            r = doc.to_dict()
            res_id = doc.id

            # Trata normalização de status
            status_reserva = str(r.get("status") or "desconhecida").lower()
            if status_reserva == "finalizada":
                status_reserva = "concluida"

            nome_usuario = r.get("usuarioNome") or r.get("nomeMotorista") or r.get("nomeUsuario") or r.get("nome")
            usuario_id = r.get("usuarioId")
            
            foto = "/static/default_profile.png"
            telefone = ""
            placa_veiculo = r.get("placa")  # Tenta pegar direto do documento da reserva primeiro

            # 3. Busca dados complementares do Usuário e Veículo no Firestore
            if usuario_id:
                try:
                    u_doc = database.collection("usuario").document(usuario_id).get()
                    if u_doc.exists:
                        u = u_doc.to_dict()
                        foto = u.get("fotoPerfil") or foto
                        telefone = u.get("telefone") or ""
                        if not nome_usuario:
                            nome_usuario = u.get("nome") or u.get("usuarioNome") or u.get("nomeMotorista")

                    # Se a placa não estava gravada na reserva, busca na coleção 'veiculo'
                    if not placa_veiculo:
                        veiculos_docs = database.collection("veiculo").where("usuarioId", "==", usuario_id).limit(1).stream()
                        veiculos = [v.to_dict() for v in veiculos_docs]
                        if veiculos:
                            v = veiculos[0]
                            placa_veiculo = v.get("placa") or v.get("placaCarro") or v.get("carPlate")
                except Exception:
                    pass

            # 4. Tratamento das Datas (inicioReserva e fimReserva)
            inicio_dt, fim_dt = None, None
            try:
                raw_inicio = r.get("inicioReserva")
                raw_fim = r.get("fimReserva")
                
                # Suporta tanto ISO String quanto Timestamp nativo do Firestore
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

            # 5. Aplicação dos Filtros em Memória
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

            # 6. Busca Número da Vaga
            numero_vaga = "—"
            vaga_id = r.get("vagaId")
            if vaga_id:
                try:
                    vaga_doc = database.collection("vaga").document(vaga_id).get()
                    if vaga_doc.exists:
                        numero_vaga = vaga_doc.to_dict().get("numero") or "—"
                except Exception:
                    pass

            # Estrutura final enviada para o Django
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

        # Ordena da reserva mais recente para a mais antiga
        lista.sort(key=lambda x: x["_sort_key"], reverse=True)

        return {"reservas": lista}

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao consultar reservas: {str(e)}"
        )