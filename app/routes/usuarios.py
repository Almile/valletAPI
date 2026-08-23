
from fastapi import APIRouter, HTTPException, Depends, Form, File, UploadFile
from firebase_admin import auth, firestore

from typing import Optional
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials


router = APIRouter()

security = HTTPBearer(auto_error=False)

@router.get("/")
def home():
    return {"message":"get auth"}