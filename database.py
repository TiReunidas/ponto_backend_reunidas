from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

# --- CONEXÃO 1: Nosso banco de dados (PostgreSQL) ---
# Lembre-se de substituir 'sua_senha_forte' pela senha real
SQLALCHEMY_DATABASE_URL_APP = "postgresql://ponto_user:ReunidasP2025@localhost/ponto_rh"
engine_app = create_engine(SQLALCHEMY_DATABASE_URL_APP)
SessionLocal_App = sessionmaker(autocommit=False, autoflush=False, bind=engine_app)
Base = declarative_base()

# --- CONEXÃO 2: Banco do sistema principal (SQL Server) ---
# Substitua com os dados reais do banco de dados principal
main_server = '172.16.1.223'
main_database = 'P12_BI'
main_username = 'sa'
main_password = 'Rp%40T3ch%2350'
    
SQLALCHEMY_DATABASE_URL_MAIN = (
    f"mssql+pyodbc://{main_username}:{main_password}@{main_server}/{main_database}"
    "?driver=ODBC+Driver+18+for+SQL+Server"
    "&TrustServerCertificate=yes"
)
    
engine_main = create_engine(SQLALCHEMY_DATABASE_URL_MAIN)
SessionLocal_Main = sessionmaker(autocommit=False, autoflush=False, bind=engine_main)

