import os
import firebase_admin
from firebase_admin import credentials
from dotenv import load_dotenv

load_dotenv()

cred_path = os.getenv("FIREBASE_CREDENTIALS_PATH")

try:
    if not cred_path:
        raise ValueError("A variável FIREBASE_CREDENTIALS_PATH não foi encontrada no .env ou nas variáveis do sistema.")

    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred)
        
    print("✅ Firebase conectado com sucesso!")
    print(f"Projeto ativo: {firebase_admin.get_app().project_id}")

except Exception as e:
    print("❌ Falha na conexão com o Firebase:")
    print(e)