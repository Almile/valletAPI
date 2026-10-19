from pydantic import BaseModel, Field, EmailStr, computed_field, model_validator
from typing import Optional, Literal, Union
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
    estacionamentoId: Optional[str] = None

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
    estacionamentoNome: Optional[str] = None
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
    cor: str
    tipo: Literal["Moto", "Carro", "Caminhão"]

class VeiculoResponse(VeiculoCreate):
    id: Optional[str] = None
    usuarioId: str
    usuarioEmail: str
    dataCadastro: datetime

# --- ESTACIONAMENTO ---
class Endereco(BaseModel):
    cep: Optional[str] = ""
    logradouro: Optional[str] = ""
    complemento: Optional[str] = ""
    numero: Optional[str] = ""
    bairro: Optional[str] = ""
    cidade: Optional[str] = ""
    uf: Optional[str] = ""

    @model_validator(mode="before")
    @classmethod
    def aceitar_localidade_antiga(cls, dados):
        if isinstance(dados, dict) and not dados.get("cidade") and dados.get("localidade"):
            dados = {**dados, "cidade": dados["localidade"]}
        return dados

class EstacionamentoCreate(BaseModel):
    nome: str
    cnpj: str
    telefone: Optional[str] = ""
    
    adminUid: str
    
    endereco: Optional[Union[Endereco, str]] = None
    
    quantidadeVagasTotal: Optional[int] = 1
    vagasDisponiveis: Optional[int] = 1
    quantidadeVagasComum: Optional[int] = 0
    quantidadeVagasIdosoPcd: Optional[int] = 0

    possuiVagasPcd: bool = False
    quantidadeVagasPcd: int = 0
    possuiVagasIdoso: bool = False
    quantidadeVagasIdoso: int = 0

    tiposVagasComum: Optional[bool] = False
    tiposVagasIdosoPcd: Optional[bool] = False
    possuiCobertura: Optional[bool] = False
    numeroPavimentos: Optional[int] = 1

    # Operação
    funciona24h: bool = Field(
        default=False,
        description="Quando ativo, o estacionamento funciona continuamente, sem horário de fechamento.",
    )
    horarioAbertura: Optional[str] = "08:00"
    horarioFechamento: Optional[str] = "18:00"
    valorHora: Optional[float] = 0.0
    
    # Regras de Reserva
    tempoMaxReservaHoras: Optional[float] = 2.0
    toleranciaReservaMinutos: Optional[int] = 10
    
    # Localização
    fotoEstacionamentoUri: Optional[str] = None
    distanciaMetros: Optional[int] = 0
    latitude: Optional[float] = 0.0
    longitude: Optional[float] = 0.0


    @model_validator(mode="after")
    def normalizar_funcionamento_24h(self):
        if self.funciona24h:
            # Os horários são neutros; o booleano determina o funcionamento contínuo.
            self.horarioAbertura = "00:00"
            self.horarioFechamento = "00:00"
        return self


class EstacionamentoSchema(EstacionamentoCreate):
    id: Optional[str] = None
    adminEmail: Optional[str] = None

    @computed_field
    @property
    def etiquetaFuncionamento(self) -> str:
        if self.funciona24h:
            return "Full time"
        return f"{self.horarioAbertura or '-'} às {self.horarioFechamento or '-'}"


class EstacionamentoUpdate(BaseModel):
    nome: Optional[str] = Field(default=None, min_length=1)
    cnpj: Optional[str] = Field(default=None, min_length=1)
    telefone: Optional[str] = None
    adminUid: Optional[str] = None
    endereco: Optional[Union[Endereco, str]] = None
    quantidadeVagasTotal: Optional[int] = Field(default=None, ge=1)
    quantidadeVagasComum: Optional[int] = Field(default=None, ge=0)
    quantidadeVagasIdosoPcd: Optional[int] = Field(default=None, ge=0)
    tiposVagasComum: Optional[bool] = None
    tiposVagasIdosoPcd: Optional[bool] = None
    possuiVagasPcd: Optional[bool] = None
    quantidadeVagasPcd: Optional[int] = Field(default=None, ge=0)
    possuiVagasIdoso: Optional[bool] = None
    quantidadeVagasIdoso: Optional[int] = Field(default=None, ge=0)
    valorHora: Optional[float] = Field(default=None, ge=0)
    funciona24h: Optional[bool] = None
    horarioAbertura: Optional[str] = None
    horarioFechamento: Optional[str] = None

# --- VAGA ---

class Vaga(BaseModel):
    id: Optional[str] = None
    numero: str
    localizacao: str = ""
    preco: float = 0.0
    tipo: str = "Carro"
    preferencial: bool = False
    disponivel: bool = True
    estacionamentoId: str

# --- SCHEMAS AUXILIARES PARA VAGAS ---

class VagaCreate(BaseModel):
    numero: str
    localizacao: Optional[str] = ""
    preco: Optional[float] = 0.0
    tipo: str = "Carro"
    preferencial: bool = False
    disponivel: bool = True
    estacionamentoId: str

class VagaUpdate(BaseModel):
    numero: Optional[str] = None
    localizacao: Optional[str] = None
    preco: Optional[float] = None
    tipo: str = "Carro"
    preferencial: Optional[bool] = None
    disponivel: Optional[bool] = None

class VagasLoteCreate(BaseModel):
    estacionamentoId: str
    quantidade: int = Field(..., gt=0, description="Quantidade de vagas a gerar")
    prefixo: Optional[str] = Field("A-", description="Prefixo para o número da vaga, ex: A-1, A-2")
    tipo: str = "Carro"
    preco: Optional[float] = 0.0
    preferencial: bool = False
    localizacao: Optional[str] = ""
    
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