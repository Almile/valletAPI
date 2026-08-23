import os
from dotenv import load_dotenv
import httpx
from fastapi import APIRouter, HTTPException, Depends, Form, File, UploadFile
from firebase_admin import auth, firestore

from typing import Optional
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

FIREBASE_API_KEY = os.getenv("FIREBASE_WEB_API_KEY")

router = APIRouter()

security = HTTPBearer(auto_error=False)

@router.get("/")
def home():
    return {"message":"get auth"}