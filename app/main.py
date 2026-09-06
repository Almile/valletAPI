from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from app.routes import auth,usuarios, estacionamento, veiculo, pagamento
from fastapi.security import HTTPBearer

security = HTTPBearer()

app = FastAPI(title="API - Vallet", swagger_ui_parameters={"persistAuthorization": True})

# Configura o CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rotas
app.include_router(auth.router, prefix="/auth", tags=["Autenticação"])
app.include_router(usuarios.router, prefix="/usuarios", tags=["Usuarios"],dependencies=[Depends(security)])
app.include_router(estacionamento.router, prefix="/estacionamento", tags=["Estacionamento"],dependencies=[Depends(security)])
app.include_router(veiculo.router, prefix="/veiculo", tags=["Veículo"],dependencies=[Depends(security)])
app.include_router(pagamento.router, prefix="/pagamento", tags=["Pagamento"])

@app.get("/")
def home():
    return {"message": "API Vallet"}