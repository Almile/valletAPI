from decimal import Decimal
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, EmailStr, SecretStr, computed_field, model_validator
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
    fotoPerfil: Optional[str] = 'https://res.cloudinary.com/dkmbs6lyk/image/upload/v1794715283/copy_of_whatsapp_image_2026-11-15_at_005804_txbpkw.jpg'
    telefone: Optional[str] = None
    cargo: Optional[str] = None
    fcm_token: Optional[str] = None
    ativo: bool = True

class UsuarioCreate(UsuarioSchema):
    senha: str = Field(..., min_length=6, examples=["senha123"])

class UsuarioUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: Optional[str] = Field(default=None, min_length=1)
    email: Optional[EmailStr] = None
    senha: Optional[SecretStr] = Field(default=None, min_length=6, max_length=128, exclude=True, repr=False)
    telefone: Optional[str] = None
    cnh: Optional[str] = None
    fotoPerfil: Optional[str] = None
    cargo: Optional[str] = None
    estacionamentoId: Optional[str] = None

    @model_validator(mode="after")
    def validar_atualizacao(self):
        for campo in ("nome", "email", "senha"):
            if campo in self.model_fields_set and getattr(self, campo) is None:
                raise ValueError(f"O campo {campo} não pode ser nulo.")
        if self.nome is not None:
            self.nome = self.nome.strip()
            if not self.nome:
                raise ValueError("O nome não pode ficar vazio.")
        if self.estacionamentoId is not None:
            self.estacionamentoId = self.estacionamentoId.strip()
            if "/" in self.estacionamentoId:
                raise ValueError("Identificador de estacionamento inválido.")
            self.estacionamentoId = self.estacionamentoId or None
        return self


class UsuarioResponse(UsuarioSchema):
    uid: str
    data_criacao: Optional[datetime] = None
    ultima_atualizacao_token: Optional[datetime] = None
    estacionamentoId: Optional[str] = None
    estacionamentoNome: Optional[str] = None


class PerfilUpdate(BaseModel):
    """Campos que o próprio usuário pode alterar no seu perfil.

    Tipo de usuário, vínculos e cargos não fazem parte deste schema para evitar
    escalonamento de privilégios pela rota de perfil.
    """

    model_config = ConfigDict(extra="forbid")

    nome: Optional[str] = Field(default=None, min_length=1)
    email: Optional[EmailStr] = None
    telefone: Optional[str] = None
    cnh: Optional[str] = None
    fotoPerfil: Optional[str] = None
    senha: Optional[SecretStr] = Field(
        default=None, min_length=6, max_length=128, exclude=True, repr=False
    )

    @model_validator(mode="after")
    def validar_perfil(self):
        for campo in ("nome", "email", "senha"):
            if campo in self.model_fields_set and getattr(self, campo) is None:
                raise ValueError(f"O campo {campo} não pode ser nulo.")
        if self.nome is not None:
            self.nome = self.nome.strip()
            if not self.nome:
                raise ValueError("O nome não pode ficar vazio.")
        return self

# --- VEICULO ---
class VeiculoCreate(BaseModel):
    placa: str = Field(..., examples=["ABC1D23"])
    marca: str
    modelo: str
    apelido: Optional[str] = None
    padrao: bool = False
    ano: int
    cor: str
    tipo: Literal["Moto", "Carro"]

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

class EstacionamentoBase(BaseModel):
    nome: str
    cnpj: str
    telefone: Optional[str] = ""
    
    adminUid: str
    
    endereco: Optional[Union[Endereco, str]] = None
    
    quantidadeVagasTotal: Optional[int] = 0
    vagasDisponiveis: Optional[int] = 0
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
    fotoEstacionamentoUri: Optional[str] = "https://res.cloudinary.com/dkmbs6lyk/image/upload/v1794715677/copy_of_vallet_logo_r6gvzr.png"
    distanciaMetros: Optional[int] = 0
    latitude: Optional[float] = 0.0
    longitude: Optional[float] = 0.0
    geohash: Optional[str] = None

    @model_validator(mode="after")
    def normalizar_funcionamento_24h(self):
        if self.funciona24h:
            # Os horários são neutros; o booleano determina o funcionamento contínuo.
            self.horarioAbertura = "00:00"
            self.horarioFechamento = "00:00"
        return self


class TipoVagaBase(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def normalizar_tipo_vaga(cls, dados):
        if not isinstance(dados, dict) or "tipo" not in dados:
            return dados
        dados = dict(dados)
        if not isinstance(dados["tipo"], str) or not dados["tipo"].strip():
            raise ValueError("Informe um tipo de vaga válido.")
        tipo = dados["tipo"].strip().casefold()
        chave = tipo.replace(" ", "").replace("_", "").replace("/", "").replace("-", "")
        if chave in ("comum", "carro"):
            dados["tipo"] = "carro"
        elif chave == "moto":
            dados["tipo"] = "moto"
        elif chave in ("preferencial", "idosopcd", "pcd", "idoso"):
            dados["tipo"] = "carro"
            dados["preferencial"] = True
        # Tipos antigos desconhecidos permanecem legíveis no modelo de resposta.
        # Os modelos de entrada restringem os novos cadastros a carro/moto.
        return dados


class VagaInicial(TipoVagaBase):
    numero: str = Field(..., min_length=1, max_length=100)
    localizacao: str = Field(default="", max_length=200)
    preco: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    tipo: Literal["carro", "moto"] = "carro"
    preferencial: bool = False

    @model_validator(mode="after")
    def normalizar_vaga(self):
        self.numero = self.numero.strip()
        if not self.numero:
            raise ValueError("Informe o identificador da vaga.")
        self.localizacao = self.localizacao.strip()
        return self


class EstacionamentoCreate(EstacionamentoBase):
    # Campo exclusivo da requisição de cadastro; não é salvo no estacionamento.
    vagasIniciais: list[VagaInicial] = Field(default_factory=list, max_length=499)

    @model_validator(mode="after")
    def validar_identificadores_vagas(self):
        identificadores = [vaga.numero.casefold() for vaga in self.vagasIniciais]
        if len(identificadores) != len(set(identificadores)):
            raise ValueError("Existem vagas com identificadores repetidos.")
        return self


class EstacionamentoSchema(EstacionamentoBase):
    id: Optional[str] = None
    adminEmail: Optional[str] = None
    adminNome: Optional[str] = None

    @computed_field
    @property
    def etiquetaFuncionamento(self) -> str:
        if self.funciona24h:
            return "Full time"
        return f"{self.horarioAbertura or '-'} às {self.horarioFechamento or '-'}"


class EstacionamentoProximo(EstacionamentoSchema):
    """Estacionamento com a distância calculada em relação ao usuário."""

    distanciaMetros: int = 0
    distanciaKm: float = 0.0


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
    geohash: Optional[str] = None
    fotoEstacionamentoUri: Optional[str] = None

# --- VAGA ---

class Vaga(TipoVagaBase):
    id: Optional[str] = None
    numero: str
    localizacao: str = ""
    preco: float = 0.0
    tipo: str = "carro"
    preferencial: bool = False
    disponivel: bool = True
    estacionamentoId: str

# --- SCHEMAS AUXILIARES PARA VAGAS ---

class VagaCreate(TipoVagaBase):
    numero: str
    localizacao: Optional[str] = ""
    preco: Optional[float] = 0.0
    tipo: Literal["carro", "moto"] = "carro"
    preferencial: bool = False
    disponivel: bool = True
    estacionamentoId: str

class VagaUpdate(TipoVagaBase):
    numero: Optional[str] = None
    localizacao: Optional[str] = None
    preco: Optional[float] = None
    tipo: Optional[Literal["carro", "moto"]] = None
    preferencial: Optional[bool] = None
    disponivel: Optional[bool] = None

class VagasLoteCreate(TipoVagaBase):
    estacionamentoId: str
    quantidade: int = Field(..., gt=0, description="Quantidade de vagas a gerar")
    prefixo: Optional[str] = Field("A-", description="Prefixo para o número da vaga, ex: A-1, A-2")
    tipo: Literal["carro", "moto"] = "carro"
    preco: Optional[float] = 0.0
    preferencial: bool = False
    localizacao: Optional[str] = ""
    
# --- RESERVA ---

class ReservaCreate(BaseModel):
    vagaId: str
    estacionamentoId: str
    inicioReserva: datetime
    fimReserva: datetime

class ReservaCriar(BaseModel):
    """Dados enviados pelo motorista ao reservar uma vaga."""

    model_config = ConfigDict(extra="forbid")

    vagaId: str = Field(..., min_length=1, max_length=1500, pattern=r"^[^/]+$")
    estacionamentoId: Optional[str] = Field(
        default=None, min_length=1, max_length=1500, pattern=r"^[^/]+$"
    )
    inicioReserva: Optional[datetime] = None
    fimReserva: Optional[datetime] = None
    duracaoHoras: Optional[float] = Field(default=None, gt=0, le=24 * 7, allow_inf_nan=False)
    placa: Optional[str] = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def validar_duracao(self):
        if self.fimReserva is None and self.duracaoHoras is None:
            raise ValueError("Informe fimReserva ou duracaoHoras.")
        if self.placa is not None:
            self.placa = self.placa.strip().upper() or None
        return self


class ReservaEstender(BaseModel):
    """Aumenta o tempo de uma reserva ativa."""

    model_config = ConfigDict(extra="forbid")

    fimReserva: Optional[datetime] = None
    horasAdicionais: Optional[float] = Field(
        default=None, gt=0, le=24 * 7, allow_inf_nan=False
    )
    minutosAdicionais: Optional[int] = Field(default=None, gt=0, le=60 * 24 * 7)

    @model_validator(mode="after")
    def validar_estender(self):
        if (
            self.fimReserva is None
            and self.horasAdicionais is None
            and self.minutosAdicionais is None
        ):
            raise ValueError("Informe fimReserva, horasAdicionais ou minutosAdicionais.")
        return self


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
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    valor: Decimal = Field(gt=0, max_digits=12, decimal_places=2, allow_inf_nan=False)
    metodo: Literal["pix"] = "pix"
    numero_cartao: str | None = Field(default=None, exclude=True)
    usuario_id: str | None = Field(default=None, validation_alias=AliasChoices("usuario_id", "usuarioId"))
    reserva_id: str = Field(min_length=1, max_length=1500, pattern=r"^[^/]+$", validation_alias=AliasChoices("reserva_id", "reservaId"))
