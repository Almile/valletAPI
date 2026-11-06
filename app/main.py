from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from app.routes import auth,usuarios, estacionamento, veiculo, pagamento, admin,reserva, notificacoes, camera,vaga
from fastapi.security import HTTPBearer
import asyncio
from contextlib import asynccontextmanager

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
app.include_router(admin.router, prefix="/admin", tags=["Administração"],dependencies=[Depends(security)])
app.include_router(estacionamento.router, prefix="/estacionamento", tags=["Estacionamento"],dependencies=[Depends(security)])
app.include_router(veiculo.router, prefix="/veiculo", tags=["Veículo"],dependencies=[Depends(security)])
app.include_router(pagamento.router, prefix="/pagamento", tags=["Pagamento"])
app.include_router(reserva.router, prefix="/reserva", tags=["Reserva"],dependencies=[Depends(security)])
app.include_router(notificacoes.router, prefix="/notificacoes", tags=["Notificações"],dependencies=[Depends(security)])
app.include_router(camera.router, prefix="/camera", tags=["Câmera"])
app.include_router(vaga.router, prefix="/vaga", tags=["Vaga"],dependencies=[Depends(security)])

@app.get("/")
def home():
    return {"message": "API Vallet"}


@app.get("/health", tags=["Infra"])
def health():
    """Verificação leve de disponibilidade (não consome leituras do Firestore)."""
    return {"status": "ok"}

# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     tarefas = [
#         asyncio.create_task(camera.monitorar_leitores()),
#         asyncio.create_task(camera.monitorar_pagamentos()),
#     ]
#     yield
#     for t in tarefas:
#         t.cancel()

# app = FastAPI(lifespan=lifespan)