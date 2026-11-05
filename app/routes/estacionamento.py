from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from app.models.schemas import Endereco, EstacionamentoSchema, EstacionamentoBase, EstacionamentoCreate, EstacionamentoUpdate
from app.valida_token import get_usuario_atual
from app.core.firebase import db
from app.core.vagas_resumo import resumo_vagas, resumo_vagas_por_consulta
from firebase_admin import firestore
from pydantic import ValidationError
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
import pygeohash as pgh
import cloudinary.uploader

router = APIRouter()
database = db
geolocator = Nominatim(user_agent="vallet_projeto_app")

def atualizar_resumo_resposta(dados, estacionamento_id):
    """Inclui o resumo de vagas sem ler todos os documentos da coleção.

    A versão anterior fazia ``stream()`` em todas as vagas do estacionamento
    a cada listagem, o que era o principal consumidor de leituras do Firestore.
    """
    dados.update(resumo_vagas_por_consulta(estacionamento_id))
    return dados


@router.post("/criar_estacionamento", response_model=EstacionamentoSchema, status_code=status.HTTP_201_CREATED)
def criar_estacionamento(
    estacionamento: EstacionamentoCreate,
    usuario_logado: dict = Depends(get_usuario_atual)
):
    """
    Permite apenas que um 'superadmin' crie um estacionamento e o associe a um 'admin'.
    """
    solicitante_uid = usuario_logado.get("uid")

    try:
        solicitante_doc = database.collection("usuario").document(solicitante_uid).get()
        if not solicitante_doc.exists or solicitante_doc.to_dict().get("tipo_user") != "superadmin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Apenas usuários com perfil 'superadmin' podem cadastrar estacionamentos."
            )

        admin_doc = database.collection("usuario").document(estacionamento.adminUid).get()
        if not admin_doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="O administrador (adminUid) informado não foi encontrado."
            )
        dados_admin = admin_doc.to_dict()
        
        if dados_admin.get("tipo_user") not in ["admin", "administrador", "superadmin"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="O usuário selecionado para gerenciar o estacionamento não possui perfil de administrador."
            )

        estacionamento_existente = database.collection("estacionamento").where("adminUid", "==", estacionamento.adminUid).limit(1).stream()
        if any(True for _ in estacionamento_existente):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Este administrador já está vinculado a um estacionamento. Cada admin pode gerenciar apenas um."
            )

        endereco_str = ""
        if isinstance(estacionamento.endereco, str):
            endereco_str = estacionamento.endereco
            print(f"DEBUG: Endereço string: {endereco_str}")
        elif isinstance(estacionamento.endereco, Endereco):
            logradouro_limpo = estacionamento.endereco.logradouro.split(',')[0].strip()
            cidade = estacionamento.endereco.cidade
            uf = estacionamento.endereco.uf
            
            endereco_str = f"{logradouro_limpo}, {cidade}, {uf}, Brasil"
            print(f"DEBUG: Endereço montado (Endereco): {endereco_str}")
        elif isinstance(estacionamento.endereco, dict):
            logradouro_limpo = estacionamento.endereco.get("logradouro", "").split(',')[0].strip()
            cidade = estacionamento.endereco.get("cidade", "")
            uf = estacionamento.endereco.get("uf", "")
            
            endereco_str = f"{logradouro_limpo}, {cidade}, {uf}, Brasil"
            print(f"DEBUG: Endereço montado (dict): {endereco_str}")
        else:
            print(f"DEBUG: Tipo de endereço não reconhecido: {type(estacionamento.endereco)}")

        if endereco_str and (estacionamento.latitude == 0.0 or estacionamento.longitude == 0.0):
            try:
                location = geolocator.geocode(endereco_str, timeout=10, country_codes='BR')
                if location:
                    estacionamento.latitude = location.latitude
                    estacionamento.longitude = location.longitude
                    estacionamento.geohash = pgh.encode(latitude=location.latitude, longitude=location.longitude, precision=9)
                else:
                    print(f"Aviso: Endereço não encontrado no mapa: {endereco_str}")
            except (GeocoderTimedOut, GeocoderServiceError) as e:
                print(f"Erro de geocodificação: {e}")

        estacionamento_dict = estacionamento.model_dump(exclude={"vagasIniciais"})
        vagas_iniciais = [vaga.model_dump() for vaga in estacionamento.vagasIniciais]
        estacionamento_dict.update(resumo_vagas(vagas_iniciais))
        # As vagas iniciais são criadas livres. Quantidades enviadas manualmente são ignoradas.
        estacionamento_dict["adminEmail"] = dados_admin.get("email")
        estacionamento_dict["criadoPorUid"] = solicitante_uid
        estacionamento_dict["data_criacao"] = firestore.SERVER_TIMESTAMP

        doc_ref = database.collection("estacionamento").document()
        batch = database.batch()
        batch.set(doc_ref, estacionamento_dict)
        for vaga in vagas_iniciais:
            vaga_ref = database.collection("vaga").document()
            batch.set(vaga_ref, {
                **vaga, "id": vaga_ref.id,
                "estacionamentoId": doc_ref.id, "disponivel": True,
            })
        resposta = EstacionamentoSchema(**estacionamento_dict, id=doc_ref.id)
        batch.commit()

        return resposta

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao criar estacionamento: {str(e)}"
        )


@router.post("/upload_imagem", status_code=status.HTTP_200_OK)
async def upload_imagem_estacionamento(
    file: UploadFile = File(...),
    usuario_logado: dict = Depends(get_usuario_atual)
):
    """
    Faz upload de uma imagem de estacionamento para o Cloudinary.
    Retorna a URL segura da imagem.
    """
    if not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O arquivo enviado não é uma imagem."
        )

    try:
        resultado = cloudinary.uploader.upload(
            file.file,
            folder="vallet/estacionamentos",
            resource_type="image",
            transformation=[
                {"width": 1200, "height": 800, "crop": "limit"},
                {"quality": "auto"}
            ]
        )
        return {
            "url": resultado.get("secure_url"),
            "public_id": resultado.get("public_id")
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao fazer upload da imagem: {str(e)}"
        )

@router.get("/buscar_estacionamento/{estacionamento_id}", response_model=EstacionamentoSchema)
def buscar_estacionamento_por_id(
    estacionamento_id: str,
    usuario_logado: dict = Depends(get_usuario_atual)
):
    """
    Busca os detalhes de um estacionamento específico pelo ID.
    Valida se o usuário logado tem acesso (superadmin ou o próprio admin do estacionamento).
    """
    try:
        uid = usuario_logado.get("uid")

        user_doc = database.collection("usuario").document(uid).get()
        tipo_user = user_doc.to_dict().get("tipo_user") if user_doc.exists else "motorista"

        estacionamento_ref = database.collection("estacionamento").document(estacionamento_id)
        doc = estacionamento_ref.get()

        if not doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Estacionamento não encontrado."
            )

        dados = doc.to_dict()
        dados["id"] = doc.id

        if tipo_user != "superadmin" and dados.get("adminUid") != uid:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Você não tem permissão para visualizar os detalhes deste estacionamento."
            )

        return EstacionamentoSchema(**atualizar_resumo_resposta(dados, estacionamento_id))

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao buscar estacionamento: {str(e)}"
        )

@router.get("/listar_estacionamentos_usuario", response_model=list[EstacionamentoSchema])
def listar_estacionamentos(usuario_logado: dict = Depends(get_usuario_atual)):
    """
    Lista os estacionamentos.
    Se for superadmin: traz todos.
    Se for admin: traz apenas os vinculados ao seu adminUid.
    """
    try:
        uid = usuario_logado.get("uid")
        
        user_doc = database.collection("usuario").document(uid).get()
        tipo_user = user_doc.to_dict().get("tipo_user") if user_doc.exists else "motorista"

        if tipo_user == "superadmin":
            estacionamentos_ref = database.collection("estacionamento")
        else:
            estacionamentos_ref = database.collection("estacionamento").where("adminUid", "==", uid)

        estacionamentos_docs = estacionamentos_ref.stream()

        estacionamentos_list = []
        for doc in estacionamentos_docs:
            estacionamento_data = doc.to_dict()
            estacionamento_data["id"] = doc.id
            estacionamentos_list.append(EstacionamentoSchema(**atualizar_resumo_resposta(estacionamento_data, doc.id)))

        return estacionamentos_list

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao listar estacionamentos: {str(e)}"
        )

@router.patch("/atualizar_estacionamento/{estacionamento_id}", response_model=EstacionamentoSchema)
def atualizar_estacionamento(
    estacionamento_id: str,
    alteracoes: EstacionamentoUpdate,
    usuario_logado: dict = Depends(get_usuario_atual),
):
    """Atualiza os campos enviados, preservando metadados e os demais dados.
    Se o endereço for alterado, recalcula latitude e longitude automaticamente.
    """
    try:
        uid = usuario_logado.get("uid")
        usuario_doc = database.collection("usuario").document(uid).get()
        tipo_user = usuario_doc.to_dict().get("tipo_user") if usuario_doc.exists else None
        ref = database.collection("estacionamento").document(estacionamento_id)
        doc = ref.get()
        if not doc.exists:
            raise HTTPException(status_code=404, detail="Estacionamento não encontrado.")
        atuais = doc.to_dict()
        if tipo_user != "superadmin" and not (
            tipo_user in ("admin", "administrador") and atuais.get("adminUid") == uid
        ):
            raise HTTPException(status_code=403, detail="Você não tem permissão para editar este estacionamento.")

        novos = alteracoes.model_dump(exclude_unset=True)
        if not novos:
            return EstacionamentoSchema(**{**atuais, "id": doc.id})
        
            if "adminUid" in novos and novos["adminUid"] != atuais.get("adminUid"):
                est_existente = database.collection("estacionamento").where("adminUid", "==", novos["adminUid"]).limit(1).stream()
                for doc in est_existente:
                    if doc.id != estacionamento_id:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="O novo administrador já está vinculado a outro estacionamento."
                        )
            if tipo_user != "superadmin" and novos["adminUid"] != atuais.get("adminUid"):
                raise HTTPException(status_code=403, detail="Apenas superadmin pode alterar o administrador responsável.")
            admin_doc = database.collection("usuario").document(novos["adminUid"]).get()
            if not admin_doc.exists:
                raise HTTPException(status_code=404, detail="Administrador não encontrado.")
            admin = admin_doc.to_dict()
            if admin.get("tipo_user") not in ("admin", "administrador", "superadmin"):
                raise HTTPException(status_code=400, detail="O responsável deve possuir perfil de administrador.")
            novos["adminEmail"] = admin.get("email")

        
        endereco_foi_alterado = "endereco" in novos
        if endereco_foi_alterado:
            if isinstance(novos["endereco"], dict) and isinstance(atuais.get("endereco"), dict):
                novos["endereco"] = {**atuais["endereco"], **novos["endereco"]}
            
            endereco_para_busca = ""
            if isinstance(novos["endereco"], str):
                endereco_para_busca = novos["endereco"]
            elif isinstance(novos["endereco"], dict):
                logradouro_limpo = novos["endereco"].get("logradouro", "").split(',')[0].strip()
                
                partes = [
                    logradouro_limpo,
                    novos["endereco"].get("numero", ""),
                    novos["endereco"].get("cidade", ""),
                    novos["endereco"].get("uf", "")
                ]
                endereco_para_busca = ", ".join([p for p in partes if p]) + ", Brasil"

            if endereco_para_busca:
                try:
                    location = geolocator.geocode(endereco_para_busca, timeout=10, country_codes='BR')
                    if location:
                        novos["latitude"] = location.latitude
                        novos["longitude"] = location.longitude
                        novos["geohash"] = pgh.encode(latitude=location.latitude, longitude=location.longitude, precision=9)
                    else:
                        print(f"Aviso: Endereço não encontrado no mapa durante atualização: {endereco_para_busca}")
                except (GeocoderTimedOut, GeocoderServiceError) as e:
                    print(f"Erro de geocodificação na atualização: {e}")
                
        if isinstance(novos.get("endereco"), dict):
            novos["endereco"].pop("localidade", None)
        if isinstance(atuais.get("endereco"), dict):
            atuais["endereco"].pop("localidade", None)

        resultado = {**atuais, **novos}
        validado = EstacionamentoBase.model_validate(resultado)
        
        if "endereco" in novos:
            endereco = validado.model_dump()["endereco"]
            novos["endereco"] = ({**novos["endereco"], **endereco}
                                if isinstance(endereco, dict) else endereco)
                
        if validado.funciona24h:
            novos["horarioAbertura"] = validado.horarioAbertura
            novos["horarioFechamento"] = validado.horarioFechamento
            
        novos["data_atualizacao"] = firestore.SERVER_TIMESTAMP
        ref.update(novos)
        
        return EstacionamentoSchema(**{**atuais, **novos, "id": doc.id})
        
    except HTTPException:
        raise
    except ValidationError:
        raise HTTPException(status_code=422, detail="Dados de estacionamento inválidos.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao atualizar estacionamento: {str(e)}")

@router.delete("/excluir_estacionamento/{estacionamento_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir_estacionamento(
    estacionamento_id: str,
    usuario_logado: dict = Depends(get_usuario_atual)
):
    """
    Exclui um estacionamento e todos os seus dados vinculados (vagas, favoritos, notificações).
    Apenas 'superadmin' ou o 'admin' responsável pelo estacionamento podem realizar esta ação.
    """
    try:
        uid = usuario_logado.get("uid")
        
        solicitante_doc = database.collection("usuario").document(uid).get()
        if not solicitante_doc.exists:
            raise HTTPException(status_code=404, detail="Usuário solicitante não encontrado.")
        
        dados_solicitante = solicitante_doc.to_dict()
        tipo_user = dados_solicitante.get("tipo_user")

        est_ref = database.collection("estacionamento").document(estacionamento_id)
        est_doc = est_ref.get()

        if not est_doc.exists:
            raise HTTPException(status_code=404, detail="Estacionamento não encontrado.")

        dados_estacionamento = est_doc.to_dict()
        admin_uid_estacionamento = dados_estacionamento.get("adminUid")

        if tipo_user != "superadmin" and admin_uid_estacionamento != uid:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Você não tem permissão para excluir este estacionamento."
            )

        batch = database.batch()

        # Excluir Vagas
        vagas_query = database.collection("vaga").where("estacionamentoId", "==", estacionamento_id)
        for doc in vagas_query.stream():
            batch.delete(doc.reference)

        # Excluir Favoritos
        favoritos_query = database.collection("favoritos").where("estacionamentoId", "==", estacionamento_id)
        for doc in favoritos_query.stream():
            batch.delete(doc.reference)

        # Excluir Notificações
        notificacoes_query = database.collection("notificacoes_admin").where("estacionamentoId", "==", estacionamento_id)
        for doc in notificacoes_query.stream():
            batch.delete(doc.reference)
            
        # Excluir ou Cancelar Reservas
        reservas_query = database.collection("reserva").where("estacionamentoId", "==", estacionamento_id)
        for doc in reservas_query.stream():
            dados_reserva = doc.to_dict()
            if dados_reserva.get("status") not in ["cancelada", "concluida", "finalizada"]:
                batch.update(doc.reference, {"status": "cancelada", "motivo_cancelamento": "Estacionamento excluído"})

        # Excluir o próprio Estacionamento
        batch.delete(est_ref)

        # Commit de todas as operações
        batch.commit()

        return None

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao excluir estacionamento e dados vinculados: {str(e)}"
        )
