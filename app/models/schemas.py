from pydantic import BaseModel, Field,EmailStr
from typing import Optional, Literal
from datetime import datetime

class FCMTokenUpdate(BaseModel):
    fcm_token: str

# --- USUÁRIO ---
class UsuarioSchema(BaseModel):
    nome: str = Field(..., examples=["Luan Santana"])
    email: EmailStr = Field(..., examples=["luan@gmail.com"])
    cnh: Optional[str] = None
    tipo_user: str = Field("motorista", examples=["motorista"])
    fotoPerfil: Optional[str] = 'path_imagem_padrao'
    telefone: Optional[str] = None
    cargo: Optional[str] = None
    fcm_token: Optional[str] = None

class UsuarioCreate(UsuarioSchema):
    senha: str = Field(..., min_length=6, examples=["senha123"])

class UsuarioUpdate(BaseModel):
    nome: Optional[str] = None
    telefone: Optional[str] = None
    cnh: Optional[str] = None
    fotoPerfil: Optional[str] = None
    cargo: Optional[str] = None

class UsuarioResponse(UsuarioSchema):
    uid: str
    data_criacao: Optional[datetime] = None
    ultima_atualizacao_token: Optional[datetime] = None

# --- VEICULO ---
class VeiculoCreate(BaseModel):
    placa: str = Field(..., examples=["ABC1D23"])
    marca: str
    modelo: str
    apelido: Optional[str] = None
    padrao: bool = False
    ano: int
    km: float = 0.0
    tipo: Literal["Moto", "Carro", "Caminhão"]

class VeiculoResponse(VeiculoCreate):
    id: Optional[str] = None
    usuarioId: str
    usuarioEmail: str
    dataCadastro: datetime

# --- ESTACIONAMENTO ---

class Endereco(BaseModel):
    cep: str
    logradouro: str
    complemento: Optional[str] = ""
    bairro: str
    localidade: str
    uf: str

class EstacionamentoSchema(BaseModel):
    id: Optional[str] = None
    nome: str
    cnpj: str
    telefone: str = ""
    adminUid: str
    adminEmail: str
    endereco: Optional[Endereco] = None
    
    # Capadidade e Vagas
    quantidadeVagasTotal: int = 1
    vagasDisponiveis: int = 1
    quantidadeVagasComum: int = 0
    quantidadeVagasIdosoPcd: int = 0

    tiposVagasComum: bool = False
    tiposVagasIdosoPcd: bool = False
    possuiCobertura: bool = False
    numeroPavimentos: int = 1

    # Operação
    horarioAbertura: str = "08:00"
    horarioFechamento: str = "18:00"
    valorHora: float
    
    # Regras de Reserva
    tempoMaxReservaHoras: float = 2.0
    toleranciaReservaMinutos: int = 10
    
    # Localização
    fotoEstacionamentoUri: Optional[str] = None
    distanciaMetros: Optional[int] = 0
    latitude: float
    longitude: float


# --- VAGA ---

class Vaga(BaseModel):
    id: Optional[str] = None
    numero: str
    localizacao: str = ""
    preco: float = 0.0
    tipo: Literal["Comum", "IdosoPcd", "Moto"] = "Comum"
    preferencial: bool = False
    disponivel: bool = True
    estacionamentoId: str

# --- RESERVA ---

class ReservaCreate(BaseModel):
    vagaId: str
    estacionamentoId: str
    inicioReserva: datetime
    fimReserva: datetime

class Reserva(ReservaCreate):
    id: Optional[str] = None
    usuarioId: str
    status: Literal['ativa', 'cancelada', 'concluida'] = 'ativa'
    dataCriacao: datetime

# --- RESERVA_HISTORICO ---

class ReservaHistorico(BaseModel):
    id: Optional[str] = None
    reservaId: str
    vagaId: str
    usuarioId: str
    estacionamentoId: str
    dataConclusao: datetime

# --- ---------------- CAMERA - ML ------------------------

class LeituraPlacaSchema(BaseModel):
    placa: str = Field(..., examples=["ABC1D23"])
    camera_id: str = Field(..., examples=["CAM_ENTRADA_01"])
    estacionamentoId: str = Field(..., examples=["estacionamento_01"])
    timestamp: datetime = Field(default_factory=datetime.now)

# --- ---------------- PAGAMENTO ------------------------

class RequisicaoPagamento(BaseModel):
    valor: float
    metodo: str
    numero_cartao: str | None = None
    usuario_id: str | None = None
    reserva_id: str  