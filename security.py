import os
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

# --- Configuração de Segurança ---
SECRET_KEY = "your-super-secret-key-that-is-long-and-random" 
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# --- Credenciais do Administrador ---
# Em um ambiente de produção, carregue isso de variáveis de ambiente!
# Ex: ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
ADMIN_USERNAME = "admin"
# Senha "admin" com hash. Gere o seu próprio hash se quiser mudar a senha.
ADMIN_HASHED_PASSWORD = pwd_context.hash("admin")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica se a senha fornecida corresponde ao hash."""
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Cria um novo token de acesso (JWT)."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# --- Dependência de Autenticação ---

async def get_current_user(token: str = Depends(oauth2_scheme)):
    """
    Dependência que apenas valida se o token JWT é válido.
    Não precisa mais consultar o banco de dados.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        # Apenas retornamos o nome de usuário do token.
        return {"username": username}
    except JWTError:
        raise credentials_exception