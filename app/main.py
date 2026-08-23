from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from app.routes import auth,usuarios
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

@app.get("/")
def home():
    return {"message": "API Vallet"}