from pydantic import BaseModel, Field,EmailStr
from typing import Optional, Literal
from datetime import datetime

# --- USUÁRIO ---
class UsuarioSchema(BaseModel):
    nome: str = Field(..., examples=["Luan Santana"])
    email: EmailStr = Field(..., examples=["luan@gmail.com"])
    tipoUser: str = 'motorista'
    cnh: str
    foto_url: Optional[str] = 'path_imagem_padrao'
    nomeEmpresa: Optional[str] = None
    cargo: Optional[str] = None

class UsuarioCreate(UsuarioSchema):
    senha: str = Field(..., examples=["senha123"])
    role: str = Field("motorista", examples=["motorista"])

class UsuarioUpdate(BaseModel):
    nome: Optional[str] = None
    email: Optional[EmailStr] = None
    telefone: Optional[str] = None
    senha: Optional[str] = None
    foto_url: Optional[str] = None
    nomeEmpresa: Optional[str] = None
    cargo: Optional[str] = None

# --- VEICULO ---
class VeiculoSchema(BaseModel):
    id: Optional[str] = None
    placa: str
    marca: str
    modelo: str
    apelido:Optional[str] = None
    ano:int
    km:float
    tipo: Literal["Moto","Carro","Caminhão"]
    usuarioEmail: str
    dataCadastro:datetime.datetime

# --- ESTACIONAMENTO ---

class EstacionamentoSchema(BaseModel):
    id: Optional[str] = None
    nome: str
    cnpj: str
    telefone: str = ""
    adminUid: Optional[str] = None
    adminEmail: str = ""
    endereco: str = ""
    cep: str = ""
    quantidadeVagasTotal: int = 1
    vagasDisponiveis: int = 1
    horarioAbertura: str = "08:00"
    horarioFechamento: str = "18:00"
    valorHora: float
    tiposVagasComum: bool = 'false',
    tiposVagasIdosoPcd: bool = 'false',
    quantidadeVagasComum: int = 0
    quantidadeVagasIdosoPcd: int = 0,
    possuiCobertura: bool = 'false',
    numeroPavimentos: int = 0
    tempoMaxReservaHoras: float = 2
    toleranciaReservaMinutos: int = 10
    fotoEstacionamentoUri: str
    distanciaMetros: int
    latitude: float
    longitude: float

# --- ENDEREÇO ---

class Endereco(BaseModel):
    cep: str
    logradouro: str
    complemento: str
    bairro: str
    localidade: str
    uf: str

# --- VAGA ---

class Vaga(BaseModel):
    id: str = "",
    numero: str = "",
    localizacao: str = "",
    preco: float = 0.0,
    tipo: str = "",
    preferencial: bool = 'false',
    disponivel: bool = 'true',
    estacionamentoId: str = ""

# --- RESERVA ---

class Reserva(BaseModel):
    usuarioId: str
    vagaId: str
    inicioReserva: datetime
    fimReserva: datetime
    estacionamentoId : str
    status: Literal['ativa','cancelada','concluida']

# --- RESERVA_HISTORICO ---

class ReservaHistorico:
    vaga: str
    data: str
    horario: str
    usuarioId: str
    estacionamentoId : str

# --- ---------------- CAMERA - ML ------------------------

class LeituraPlacaSchema(BaseModel):
    placa: str = Field(..., example="ABC1D23")
    camera_id: str = Field(..., example="CAM_ENTRADA_01")
    estacionamentoId: str = Field(..., example="estacionamento_01")