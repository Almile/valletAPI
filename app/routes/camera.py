from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from google.cloud.firestore_v1.base_query import FieldFilter
from firebase_admin import messaging
from firebase_admin.exceptions import FirebaseError
from app.core.firebase import db
from datetime import datetime, timezone
import cloudinary.uploader
import asyncio
import time

router = APIRouter()

def enviar_imagem_cloudinary(conteudo: bytes, nome: str) -> Optional[str]:
    """Sobe a imagem e devolve a URL https pública. Retorna None se falhar."""
    try:
        res = cloudinary.uploader.upload(
            conteudo,
            folder="vallet/placas",
            public_id=f"{nome}_{int(time.time())}",
            resource_type="image",
        )
        return res.get("secure_url")
    except Exception as e:
        print(f"Erro ao enviar imagem ao Cloudinary: {e}")
        return None

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
        usuario_email = ( veiculo_data.get('usuarioEmail'))
        
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

def disparar_notificacao_fcm(token: str, titulo: str, corpo: str, dados: dict,
                             uid_usuario: Optional[str] = None, imagem: Optional[str] = None):
    """Envia notificação via Firebase Cloud Messaging com dados extras."""
    if not token:
        return False
    try:
        safe_dados = {k: str(v) for k, v in (dados or {}).items() if v is not None}
        if imagem:
            safe_dados['imagem'] = imagem

        message = messaging.Message(
            notification=messaging.Notification(title=titulo, body=corpo, image=imagem),
            data=safe_dados,
            android=messaging.AndroidConfig(
                priority='high',
                notification=messaging.AndroidNotification(
                    sound='default',
                    channel_id='default_channel_id',
                    priority='high',
                    default_sound=True,
                    default_vibrate_timings=True,
                    image=imagem
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
    dados_adicionais: Optional[dict] = None,
    imagem: Optional[str] = None
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
            'imagem': imagem,
        }
        db.collection('notificacoes_admin').add(notificacao_data)
    except Exception as e:
        print(f"Erro ao salvar notificação admin no Firestore: {e}")

def processar_entrada_em_segundo_plano(id_estacionamento: str, id_vaga: str,
                                       numero_vaga: str, placa: str,
                                       conteudo_imagem: Optional[bytes]):
    """Cloudinary, consultas e FCM fora do caminho crítico da resposta.

    A vaga já foi gravada quando esta função roda; o leitor e os dashboards
    veem a mudança imediatamente, sem esperar upload de imagem ou notificação.
    """
    try:
        url_imagem = None
        if conteudo_imagem:
            url_imagem = enviar_imagem_cloudinary(conteudo_imagem, f"{id_vaga}_{placa}")

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

        tem_reserva = False
        if uid_motorista:
            tem_reserva = verificar_reserva(uid_motorista, id_vaga)

        if tem_reserva:
            tipo_notificacao = 'estacionamento_reservado'
            corpo_admin    = f"O veículo reservado {placa} entrou na Vaga {numero_vaga}."
            motivo_admin   = f"Veículo {placa} com reserva ativa entrou na Vaga {numero_vaga}."
        else:
            tipo_notificacao = 'estacionamento_sem_reserva'
            corpo_admin    = f"Veículo {placa} estacionou na Vaga {numero_vaga}."
            motivo_admin   = f"Veículo {placa} estacionou na Vaga {numero_vaga} sem reserva ativa."

        notificar_admin(
            id_estacionamento, tipo_notificacao, corpo_admin, motivo=motivo_admin,
            id_vaga=id_vaga, numero_vaga=numero_vaga, placa=placa,
            usuario_id=uid_motorista, imagem=url_imagem
        )
    except Exception as e:
        print(f"Erro no processamento em segundo plano da entrada: {e}")


@router.post("/placa-detectada")
async def receber_placa_detectada(
    background_tasks: BackgroundTasks,
    id_estacionamento: str = Form(...),
    id_vaga: str = Form(...),
    numero_vaga: str = Form(...),
    placa: str = Form(...),
    confianca: float = Form(...),
    imagem_corte: UploadFile = File(None),
    notificar: bool = Form(True),
):
    """
    Endpoint de recepção do pipeline de Visão Computacional.
    Grava a ocupação imediatamente e deixa imagem/notificações em background.
    """
    print(f"Processando evento: Placa {placa} na Vaga {numero_vaga}")

    try:
        conteudo = None
        if imagem_corte:
            conteudo = await imagem_corte.read()

        db.collection('vaga').document(id_vaga).set({
            'placa_atual': placa,
            'ocupada': True,
            'status': 'OCUPADA',
            'numero': numero_vaga,
            'id_estacionamento': id_estacionamento,
            'ultima_atualizacao': datetime.now()
        }, merge=True)

        if notificar:
            background_tasks.add_task(
                processar_entrada_em_segundo_plano,
                id_estacionamento, id_vaga, numero_vaga, placa, conteudo
            )

        return {
            "status": "sucesso",
            "mensagem": f"Evento processado para a placa {placa}.",
            "vaga": numero_vaga
        }

    except Exception as e:
        print(f"Erro no processamento da API: {e}")
        raise HTTPException(status_code=500, detail=str(e))

TIPOS_ALERTA_SISTEMA = {"obstrucao_camera", "sistema_erro", "sistema_alerta_estacionamento"}
TITULOS = {
    "obstrucao_camera": "Possível obstrução da câmera",
    "sistema_erro": "Falha no leitor de placas",
    "sistema_alerta_estacionamento": "Alerta do estacionamento",
    "alerta_saida": "Veículo saiu da vaga",
    "pagamento_nao_confirmado": "Pagamento de reserva não confirmado",
}

def notificar_admin(id_estacionamento: str, tipo: str, corpo: str, motivo: Optional[str] = None,
                    id_vaga: Optional[str] = None, numero_vaga: Optional[str] = None,
                    placa: Optional[str] = None, imagem: Optional[str] = None,
                    usuario_id: Optional[str] = None, dados_adicionais: Optional[dict] = None):
    """Sobe para o admin e registro em notificacoes_admin."""
    token_admin, uid_admin = buscar_token_admin(id_estacionamento)
    if token_admin and uid_admin:
        disparar_notificacao_fcm(
            token=token_admin,
            titulo=TITULOS.get(tipo, "Alerta"),
            corpo=corpo,
            dados={'tipo': tipo, 'vagaId': id_vaga or '', 'placa': placa or '',
                   'vagaNumero': numero_vaga or '', 'usuarioId': usuario_id or 'desconhecido'},
            uid_usuario=uid_admin,
            imagem=imagem
        )
    salvar_notificacao_admin(
        id_vaga=id_vaga, numero_vaga=numero_vaga, id_estacionamento=id_estacionamento,
        placa=placa, usuario_id=usuario_id, tipo=tipo, motivo=motivo or corpo,
        dados_adicionais=dados_adicionais, imagem=imagem
    )

def processar_saida_em_segundo_plano(id_estacionamento: str, id_vaga: str,
                                     numero_vaga: str, placa: str):
    try:
        _, uid_motorista = buscar_token_motorista(placa)
        notificar_admin(
            id_estacionamento, "alerta_saida",
            corpo=f"Veículo {placa} saiu da Vaga {numero_vaga}.",
            motivo=f"Veículo {placa} deixou a Vaga {numero_vaga}.",
            id_vaga=id_vaga, numero_vaga=numero_vaga, placa=placa, usuario_id=uid_motorista
        )
    except Exception as e:
        print(f"Erro no processamento em segundo plano da saída: {e}")


@router.post("/saida-detectada")
async def receber_saida_detectada(
    background_tasks: BackgroundTasks,
    id_estacionamento: str = Form(...),
    id_vaga: str = Form(...),
    numero_vaga: str = Form(...),
    placa: str = Form(...),
    notificar: bool = Form(True),
):
    try:
        db.collection('vaga').document(id_vaga).set({
            'placa_atual': None, 'ocupada': False, 'status': 'LIVRE',
            'ultima_atualizacao': datetime.now()
        }, merge=True)

        if notificar:
            background_tasks.add_task(
                processar_saida_em_segundo_plano,
                id_estacionamento, id_vaga, numero_vaga, placa
            )
        return {"status": "sucesso", "vaga": numero_vaga}
    except Exception as e:
        print(f"Erro ao processar saída: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/alerta-sistema")
async def receber_alerta_sistema(
    id_estacionamento: str = Form(...),
    tipo: str = Form(...),
    motivo: str = Form(...),
    id_vaga: Optional[str] = Form(None),
    numero_vaga: Optional[str] = Form(None),
):
    if tipo not in TIPOS_ALERTA_SISTEMA:
        raise HTTPException(status_code=400, detail=f"tipo inválido: {tipo}")
    await asyncio.to_thread(
        notificar_admin, id_estacionamento, tipo,
        motivo, id_vaga=id_vaga, numero_vaga=numero_vaga
    )
    return {"status": "sucesso", "tipo": tipo}

HEARTBEAT_TIMEOUT_S = 120
_ultimo_heartbeat: dict = {}
_leitores_offline: set = set()


@router.post("/heartbeat")
async def receber_heartbeat(id_estacionamento: str = Form(...)):
    _ultimo_heartbeat[id_estacionamento] = time.time()
    if id_estacionamento in _leitores_offline:
        _leitores_offline.discard(id_estacionamento)
        await asyncio.to_thread(
            notificar_admin, id_estacionamento, "sistema_alerta_estacionamento",
            "O leitor de placas voltou a responder."
        )
    return {"status": "ok"}


async def monitorar_leitores():
    """Gera sistema_erro quando o leitor para de mandar heartbeat."""
    while True:
        await asyncio.sleep(30)
        try:
            agora = time.time()
            for est, ts in list(_ultimo_heartbeat.items()):
                if agora - ts > HEARTBEAT_TIMEOUT_S and est not in _leitores_offline:
                    _leitores_offline.add(est)
                    minutos = int((agora - ts) // 60)
                    await asyncio.to_thread(
                        notificar_admin, est, "sistema_erro",
                        f"O leitor de placas está sem resposta há mais de {minutos} min."
                    )
        except Exception as e:
            print(f"Erro no monitor de leitores: {e}")


CAMPO_FIM_RESERVA = "fimReserva"
CAMPO_PAGAMENTO = "status"
STATUS_PAGO = {"pago", "confirmado", "aprovado"}

def _verificar_pagamentos():
    agora = datetime.now(timezone.utc)
    reservas = db.collection('reserva').where(filter=FieldFilter('status', '==', 'ativa')).get()
    for doc in reservas:
        r = doc.to_dict()
        fim = r.get(CAMPO_FIM_RESERVA)
        if not fim or r.get('pagamentoNotificado'):
            continue
        if str(r.get(CAMPO_PAGAMENTO, '')).lower() in STATUS_PAGO:
            continue
        if fim.tzinfo is None:
            fim = fim.replace(tzinfo=timezone.utc)
        if fim > agora:
            continue

        est = r.get('estacionamentoId')
        if not est:
            continue
        vaga_id = r.get('vagaId')
        placa = r.get('placa') or 'N/D'
        notificar_admin(
            est, "pagamento_nao_confirmado",
            corpo=f"A reserva da vaga terminou e o pagamento não foi confirmado (placa {placa}).",
            id_vaga=vaga_id, placa=placa, usuario_id=r.get('usuarioId')
        )
        doc.reference.update({'pagamentoNotificado': True})


async def monitorar_pagamentos():
    while True:
        await asyncio.sleep(60)
        try:
            await asyncio.to_thread(_verificar_pagamentos)
        except Exception as e:
            print(f"Erro no monitor de pagamentos: {e}")