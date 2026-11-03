from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from google.cloud.firestore_v1.base_query import FieldFilter
from firebase_admin import messaging
from firebase_admin.exceptions import FirebaseError
from app.core.firebase import db

router = APIRouter()

def buscar_token_motorista(placa: str):
    """Busca o token FCM e UID do motorista associado à placa do veículo."""
    try:
        placa_clean = placa.strip().upper().replace("-", "")
        veiculo_doc = db.collection('veiculo').document(placa_clean).get()
        
        if not veiculo_doc.exists:
            veiculo_doc = db.collection('veiculo').document(placa_clean.lower()).get()

        if not veiculo_doc.exists:
            print(f"Veículo {placa_clean} não encontrado no Firestore.")
            return None, None

        veiculo_data = veiculo_doc.to_dict()
        usuario_email = (
            veiculo_data.get('usuarioEmail') or 
            veiculo_data.get('usuario_email')
        )
        
        if not usuario_email:
            return None, None

        usuario_email_clean = usuario_email.strip().lower()
        usuarios_ref = db.collection('usuario').where(filter=FieldFilter('email', '==', usuario_email_clean)).limit(1).get()
        
        if not usuarios_ref:
            usuarios_ref = db.collection('usuario').where(filter=FieldFilter('email', '==', usuario_email.strip())).limit(1).get()

        if not usuarios_ref:
            return None, None

        usuario_doc = usuarios_ref[0]
        usuario_data = usuario_doc.to_dict()
        token = usuario_data.get('fcm_token')
        
        return token, usuario_doc.id
    except Exception as e:
        print(f"Erro ao buscar motorista: {e}")
        return None, None


def buscar_token_admin(id_estacionamento: str):
    """Busca o token FCM e o UID do admin do estacionamento."""
    try:
        estacionamento_doc = db.collection('estacionamento').document(id_estacionamento).get()
        if not estacionamento_doc.exists:
            return None, None

        uid_admin = estacionamento_doc.get('adminUid')
        if not uid_admin:
            return None, None

        usuario_doc = db.collection('usuario').document(uid_admin).get()
        if usuario_doc.exists:
            return usuario_doc.get('fcm_token'), uid_admin
            
        return None, None
    except Exception as e:
        print(f"Erro ao buscar admin: {e}")
        return None, None


def verificar_reserva(uid_motorista: str, id_vaga: str) -> bool:
    """Verifica se há reserva ativa para este motorista nesta vaga."""
    try:
        reserva_ref = db.collection('reserva')\
            .where(filter=FieldFilter('usuarioId', '==', uid_motorista))\
            .where(filter=FieldFilter('vagaId', '==', id_vaga))\
            .where(filter=FieldFilter('status', '==', 'ativa'))\
            .limit(1).get()
        return len(reserva_ref) > 0
    except Exception as e:
        print(f"Erro ao verificar reserva: {e}")
        return False

def disparar_notificacao_fcm(token: str, titulo: str, corpo: str, dados: dict, uid_usuario: Optional[str] = None):
    """Envia notificação via Firebase Cloud Messaging com dados extras."""
    if not token:
        return False
    try:
        safe_dados = {k: str(v) for k, v in (dados or {}).items()}
        
        message = messaging.Message(
            notification=messaging.Notification(
                title=titulo,
                body=corpo
            ),
            data=safe_dados,
            android=messaging.AndroidConfig(
                priority='high',
                notification=messaging.AndroidNotification(
                    sound='default',
                    channel_id='default_channel_id',
                    priority='high',
                    default_sound=True,
                    default_vibrate_timings=True
                )
            ),
            token=token
        )
        
        response = messaging.send(message)
        print(f"FCM enviado com sucesso: {response}")
        return True

    except messaging.UnregisteredError:
        print(f"Token expirado/inválido (NotRegistered) para o usuário UID: {uid_usuario}")
        if uid_usuario and isinstance(uid_usuario, str) and uid_usuario.strip():
            try:
                db.collection('usuario').document(uid_usuario).update({'fcm_token': None})
                print(f"Token 'fcm_token' removido estritamente do usuário {uid_usuario}.")
            except Exception as clean_err:
                print(f"Erro ao limpar token antigo do usuário {uid_usuario}: {clean_err}")
        return False

    except Exception as e:
        print(f"Erro no envio FCM: {e}")
        return False

def salvar_notificacao_admin(
    id_vaga: str,
    numero_vaga: str,
    id_estacionamento: str,
    placa: str,
    usuario_id: str,
    tipo: str = 'sistema_alerta_estacionamento',
    motivo: Optional[str] = None,
    dados_adicionais: Optional[dict] = None
):
    """Registra notificação na coleção 'notificacoes_admin' no Firestore."""
    try:
        notificacao_data = {
            'vagaId': id_vaga,
            'placa': placa,
            'usuarioId': usuario_id or 'desconhecido',
            'motivo': motivo or f"Veículo {placa} estacionou na Vaga {numero_vaga}",
            'timestamp': datetime.now(),
            'tipo': tipo,
            'vagaNumero': numero_vaga,
            'estacionamentoId': id_estacionamento,
            'lida': False,
            'dadosAdicionais': dados_adicionais or {},
        }
        db.collection('notificacoes_admin').add(notificacao_data)
    except Exception as e:
        print(f"Erro ao salvar notificação admin no Firestore: {e}")

@router.post("/api/v1/eventos/placa-detectada")
async def receber_placa_detectada(
    id_estacionamento: str = Form(...),
    id_vaga: str = Form(...),
    numero_vaga: str = Form(...),
    placa: str = Form(...),
    confianca: float = Form(...),
    imagem_corte: Optional[UploadFile] = File(None)
):
    """
    Endpoint de recepção do pipeline de Visão Computacional.
    Grava ocupação no Firestore e dispara alertas de FCM.
    """
    print(f"Processando evento: Placa {placa} na Vaga {numero_vaga}")

    try:
        vaga_ref = db.collection('vaga').document(id_vaga)
        vaga_data = {
            'placa_atual': placa,
            'ocupada': True,
            'status': 'OCUPADA',
            'numero': numero_vaga,
            'id_estacionamento': id_estacionamento,
            'ultima_atualizacao': datetime.now()
        }
        vaga_ref.set(vaga_data, merge=True)

        token_motorista, uid_motorista = buscar_token_motorista(placa)
        
        if token_motorista and uid_motorista:
            disparar_notificacao_fcm(
                token=token_motorista,
                titulo="Seu veículo foi estacionado!",
                corpo=f"Sua placa {placa} foi identificada na Vaga {numero_vaga}.",
                dados={
                    'vagaId': id_vaga,
                    'placa': placa,
                    'tipo': 'estacionamento',
                    'usuarioId': uid_motorista
                },
                uid_usuario=uid_motorista
            )

        token_admin, uid_admin = buscar_token_admin(id_estacionamento)
        
        tem_reserva = False
        if uid_motorista:
            tem_reserva = verificar_reserva(uid_motorista, id_vaga)

        if tem_reserva:
            tipo_notificacao = 'estacionamento_reservado'
            titulo_admin   = "Veículo com reserva estacionado"
            corpo_admin    = f"O veículo reservado {placa} entrou na Vaga {numero_vaga}."
            motivo_admin   = f"Veículo {placa} com reserva ativa entrou na Vaga {numero_vaga}."
        else:
            tipo_notificacao = 'estacionamento_sem_reserva'
            titulo_admin   = "Veículo sem reserva estacionado"
            corpo_admin    = f"Veículo {placa} estacionou na Vaga {numero_vaga}."
            motivo_admin   = f"Veículo {placa} estacionou na Vaga {numero_vaga} sem reserva ativa."

        token_admin, uid_admin = buscar_token_admin(id_estacionamento)
        if token_admin and uid_admin:
            disparar_notificacao_fcm(
                token=token_admin,
                titulo=titulo_admin,
                corpo=corpo_admin,
                dados={
                    'vagaId': id_vaga,
                    'placa': placa,
                    'tipo': tipo_notificacao,
                    'usuarioId': uid_motorista or 'desconhecido',
                    'vagaNumero': numero_vaga
                },
                uid_usuario=uid_admin
            )

        salvar_notificacao_admin(
            id_vaga=id_vaga,
            numero_vaga=numero_vaga,
            id_estacionamento=id_estacionamento,
            placa=placa,
            usuario_id=uid_motorista,
            tipo=tipo_notificacao,
            motivo=motivo_admin
        )

        salvar_notificacao_admin(
            id_vaga=id_vaga,
            numero_vaga=numero_vaga,
            id_estacionamento=id_estacionamento,
            placa=placa,
            usuario_id=uid_motorista
        )

        if imagem_corte:
            conteudo = await imagem_corte.read()

        return {
            "status": "sucesso",
            "mensagem": f"Evento processado para a placa {placa}.",
            "vaga": numero_vaga,
            "motorista_notificado": bool(token_motorista)
        }

    except Exception as e:
        print(f"Erro no processamento da API: {e}")
        raise HTTPException(status_code=500, detail=str(e))