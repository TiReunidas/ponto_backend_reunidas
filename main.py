import os
import shutil
import logging
import uuid
import calendar
import numpy as np
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from deepface import DeepFace
import cv2
import models
from database import SessionLocal_App, engine_app, SessionLocal_Main
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import List, Dict
from pydantic import BaseModel
from datetime import date, datetime, time
from collections import defaultdict
# Importamos a função de cálculo de distância diretamente
from deepface.modules.verification import find_cosine_distance
import main_system_queries
import holidays
from fastapi import Body
from pydantic import BaseModel, Field
from typing import List, Optional

br_holidays = holidays.Brazil()

# Cria as tabelas no banco de dados (se não existirem) ao iniciar
models.Base.metadata.create_all(bind=engine_app)

# --- Configuração ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = FastAPI()

# --- Definição de Pastas ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REFERENCE_DIR = os.path.join(BASE_DIR, "fotos_referencia")
PUNCH_DIR = os.path.join(BASE_DIR, "fotos_batidas")
ENCODINGS_DIR = os.path.join(BASE_DIR, "encodings")
os.makedirs(REFERENCE_DIR, exist_ok=True)
os.makedirs(PUNCH_DIR, exist_ok=True)
os.makedirs(ENCODINGS_DIR, exist_ok=True)

# <<< Nosso Limite de Sensibilidade Personalizado >>>
MODEL_THRESHOLD = 0.50

# --- Servir Arquivos Estáticos ---
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
app.mount("/punch-photos", StaticFiles(directory=PUNCH_DIR), name="punch_photos")

# --- Conexão com os Bancos de Dados ---
def get_db_app():
    db = SessionLocal_App()
    try:
        yield db
    finally:
        db.close()

def get_db_main():
    db = SessionLocal_Main()
    try:
        yield db
    finally:
        db.close()

# --- Pydantic Models ---
class CalculationRequest(BaseModel):
    employee_id: str
    year: int
    month: int
    main_system_hours_50: float = 0.0
    main_system_hours_100: float = 0.0

class PunchUpdateRequest(BaseModel):
    timestamp: int
    type: str

class PunchCreateRequest(BaseModel):
    employee_id: str
    timestamp: int
    type: str

class ReportRequest(BaseModel):
    employee_ids: List[str] # Uma lista de IDs. Se vazia, consideraremos "todos".
    start_date: date
    end_date: date


# --- Funções Auxiliares ---
def create_face_encoding(image_path: str):
    try:
        embedding_objs = DeepFace.represent(img_path=image_path, model_name="VGG-Face", enforce_detection=True, detector_backend='opencv')
        if not embedding_objs: return None
        return embedding_objs[0]['embedding']
    except Exception as e:
        logger.error(f"Erro ao criar encoding para a imagem {os.path.basename(image_path)}: {e}")
        return None

def perform_calculation(app_punches: List[models.Punch], main_system_hours: float):
    if not app_punches or len(app_punches) < 2:
        return {"hours_at_50": 0, "hours_at_100": 0, "total_app_hours": 0}
    total_app_milliseconds = 0
    paired_punches = sorted(app_punches, key=lambda p: p.timestamp)
    for i in range(0, len(paired_punches) - 1, 2):
        entrada = paired_punches[i]
        saida = paired_punches[i+1]
        if entrada.type == "Entrada" and saida.type == "Saída":
            total_app_milliseconds += (saida.timestamp - entrada.timestamp)
    total_app_hours = total_app_milliseconds / (1000 * 60 * 60)
    total_overtime_hours = total_app_hours + main_system_hours
    threshold = 2.0
    total_hours_at_50 = min(total_overtime_hours, threshold)
    total_hours_at_100 = max(0, total_overtime_hours - threshold)
    app_hours_at_50 = max(0, total_hours_at_50 - main_system_hours)
    app_hours_at_100 = total_app_hours - app_hours_at_50
    return {"hours_at_50": round(app_hours_at_50, 2), "hours_at_100": round(app_hours_at_100, 2), "total_app_hours": round(total_app_hours, 2)}

# =================================================================
# ENDPOINTS DA API
# =================================================================
@app.get("/")
async def read_index():
    return FileResponse(os.path.join(BASE_DIR, "static", "index.html"))

@app.get("/employees")
def get_employees(db: Session = Depends(get_db_app)):
    employees = db.query(models.Employee).order_by(models.Employee.name).all()
    return {"employees": [{"employee_id": emp.employee_id, "name": emp.name} for emp in employees]}

@app.get("/punches/{employee_id}")
def get_punches_for_employee(employee_id: str, db: Session = Depends(get_db_app)):
    punches = db.query(models.Punch).filter(models.Punch.employee_id == employee_id).order_by(models.Punch.timestamp.desc()).all()
    return {"punches": [{"id": p.id, "timestamp": p.timestamp, "type": p.type, "photo_path": os.path.basename(p.photo_path) if p.photo_path else None, "verified": p.verified} for p in punches]}

@app.post("/employees")
async def register_employee(employee_id: str = Form(...), employee_name: str = Form(...), photo: UploadFile = File(...), db: Session = Depends(get_db_app)):
    existing_employee = db.query(models.Employee).filter(models.Employee.employee_id == employee_id).first()
    if existing_employee:
        raise HTTPException(status_code=400, detail="Matrícula já cadastrada.")
    reference_photo_path = os.path.join(REFERENCE_DIR, f"{employee_id}.jpg")
    with open(reference_photo_path, "wb") as buffer:
        shutil.copyfileobj(photo.file, buffer)
    encoding = create_face_encoding(reference_photo_path)
    if encoding is None:
        os.remove(reference_photo_path)
        raise HTTPException(status_code=400, detail="Nenhum rosto detectado na foto de referência.")
    encoding_path = os.path.join(ENCODINGS_DIR, f"{employee_id}.npy")
    np.save(encoding_path, np.array(encoding))
    new_employee = models.Employee(employee_id=employee_id, name=employee_name)
    db.add(new_employee)
    db.commit()
    db.refresh(new_employee)
    return {"status": "success", "message": f"Funcionário {employee_name} cadastrado com sucesso!"}

# --- ENDPOINT /punch COM A LÓGICA CORRETA E ESTÁVEL ---
@app.post("/punch")
async def create_punch(employee_id: str = Form(...), timestamp: int = Form(...), photo: UploadFile = File(...), db: Session = Depends(get_db_app)):
    logger.info(f"--- INICIANDO PROCESSO PARA MATRÍCULA: {employee_id} ---")
    encoding_path = os.path.join(ENCODINGS_DIR, f"{employee_id}.npy")
    if not os.path.exists(encoding_path):
        raise HTTPException(status_code=404, detail="Funcionário não possui verificação facial cadastrada.")
    reference_encoding = np.load(encoding_path)
    punch_photo_path = os.path.join(PUNCH_DIR, f"{employee_id}-{uuid.uuid4()}.jpg")
    with open(punch_photo_path, "wb") as buffer:
        shutil.copyfileobj(photo.file, buffer)
    logger.info(f"Foto da batida salva em: {punch_photo_path}")
    is_match = False
    try:
        logger.info("Gerando encoding da foto da batida...")
        punch_encoding = create_face_encoding(punch_photo_path)
        if punch_encoding is not None:
            logger.info("Comparando as duas digitais faciais...")
            distance = find_cosine_distance(reference_encoding, punch_encoding)
            is_match = distance <= MODEL_THRESHOLD
            logger.info(f"Distância: {distance}, Limite: {MODEL_THRESHOLD}")
        else:
            logger.warning("Não foi possível gerar a digital da foto da batida (nenhum rosto encontrado).")
            is_match = False
    except Exception as e:
        logger.error(f"Ocorreu um erro inesperado durante a comparação: {e}")
        is_match = False
    logger.info(f"Resultado final da verificação para {employee_id}: {'Match' if is_match else 'No Match'}")
    last_punch = db.query(models.Punch).filter(models.Punch.employee_id == employee_id).order_by(models.Punch.timestamp.desc()).first()
    punch_type = "Entrada"
    if last_punch and last_punch.type == "Entrada":
        punch_type = "Saída"
    new_punch = models.Punch(employee_id=employee_id, timestamp=timestamp, type=punch_type, photo_path=punch_photo_path, verified=is_match)
    db.add(new_punch)
    db.commit()
    db.refresh(new_punch)
    logger.info(f"Ponto de '{punch_type}' para {employee_id} salvo no banco com ID: {new_punch.id}")
    if is_match:
        try:
            os.remove(punch_photo_path)
            logger.info(f"Foto da batida {punch_photo_path} apagada (verificação OK).")
        except Exception as e:
            logger.error(f"Erro ao tentar apagar a foto da batida: {e}")
    return {"status": "success", "message": "Ponto processado.", "verified": bool(is_match)}

# --- ENDPOINTS DE GESTÃO E CÁLCULO ---
@app.put("/punches/{punch_id}")
def update_punch(punch_id: int, request: PunchUpdateRequest, db: Session = Depends(get_db_app)):
    punch_to_update = db.query(models.Punch).filter(models.Punch.id == punch_id).first()
    if not punch_to_update:
        raise HTTPException(status_code=404, detail="Registro de ponto não encontrado.")
    punch_to_update.timestamp = request.timestamp
    punch_to_update.type = request.type
    db.commit()
    return {"status": "success", "message": "Registro atualizado com sucesso."}

@app.delete("/punches/{punch_id}")
def delete_punch(punch_id: int, db: Session = Depends(get_db_app)):
    punch_to_delete = db.query(models.Punch).filter(models.Punch.id == punch_id).first()
    if not punch_to_delete:
        raise HTTPException(status_code=404, detail="Registro de ponto não encontrado.")
    if punch_to_delete.photo_path and os.path.exists(punch_to_delete.photo_path):
        try:
            os.remove(punch_to_delete.photo_path)
            logger.info(f"Arquivo de foto associado ({punch_to_delete.photo_path}) apagado.")
        except Exception as e:
            logger.error(f"Erro ao tentar apagar o arquivo de foto {punch_to_delete.photo_path}: {e}")
    db.delete(punch_to_delete)
    db.commit()
    return {"status": "success", "message": "Registro apagado com sucesso."}

@app.post("/punches/manual")
def create_manual_punch(request: PunchCreateRequest, db: Session = Depends(get_db_app)):
    new_punch = models.Punch(employee_id=request.employee_id, timestamp=request.timestamp, type=request.type, photo_path=None, verified=True)
    db.add(new_punch)
    db.commit()
    db.refresh(new_punch)
    return {"status": "success", "message": "Registro manual adicionado com sucesso."}

@app.post("/calculate")
def calculate_overtime(request: CalculationRequest, db_app: Session = Depends(get_db_app)):
    logger.info(f"Iniciando cálculo final para Matrícula: {request.employee_id} para {request.month}/{request.year}")

    # =========================================================================
    # PASSO 1: Pegar os totais do Sistema Principal (já calculados e confirmados pelo usuário na tela)
    # =========================================================================
    main_system_total_50 = request.main_system_hours_50
    main_system_total_100 = request.main_system_hours_100

    # =========================================================================
    # PASSO 2: Buscar as batidas de ponto registradas SOMENTE neste novo sistema
    # =========================================================================
    _, num_days_in_month = calendar.monthrange(request.year, request.month)
    start_date = date(request.year, request.month, 1)
    end_date = date(request.year, request.month, num_days_in_month)
    start_ts = int(datetime.combine(start_date, time.min).timestamp() * 1000)
    end_ts = int(datetime.combine(end_date, time.max).timestamp() * 1000)
    
    punches = db_app.query(models.Punch).filter(
        models.Punch.employee_id == request.employee_id,
        models.Punch.timestamp.between(start_ts, end_ts),
        models.Punch.verified == True
    ).order_by(models.Punch.timestamp.asc()).all()
    
    punches_by_day: Dict[date, List] = defaultdict(list)
    for punch in punches:
        punch_date = datetime.fromtimestamp(punch.timestamp / 1000).date()
        punches_by_day[punch_date].append(punch)

    # =========================================================================
    # PASSO 3: Calcular as horas extras GERADAS PELO NOVO SISTEMA
    # =========================================================================
    app_total_50 = 0.0
    app_total_100 = 0.0

    for day, day_punches in punches_by_day.items():
        is_special_day = (day.weekday() == 6 or day in br_holidays)

        # --- LÓGICA PARA DOMINGOS E FERIADOS (AGORA MAIS FLEXÍVEL) ---
        if is_special_day:
            punches_count = len(day_punches)
            total_minutes_worked = 0

            # Ignora dias com número ímpar ou insuficiente de batidas
            if punches_count < 2 or punches_count % 2 != 0:
                logger.warning(f"Dia especial ({day}) com número inválido de batidas ({punches_count}). As batidas deste dia foram ignoradas.")
                continue

            timestamps_ms = sorted([p.timestamp for p in day_punches])

            # CENÁRIO 1: Trabalho com almoço (4 batidas)
            if punches_count == 4:
                duration_ms = (timestamps_ms[1] - timestamps_ms[0]) + (timestamps_ms[3] - timestamps_ms[2])
                total_minutes_worked = duration_ms / 60000.0  # milissegundos para minutos
            
            # CENÁRIO 2: Trabalho direto sem almoço (2 batidas)
            elif punches_count == 2:
                duration_ms = timestamps_ms[1] - timestamps_ms[0]
                total_minutes_worked = duration_ms / 60000.0  # milissegundos para minutos
            
            # Todas as horas trabalhadas em dias especiais são 100%
            if total_minutes_worked > 0:
                app_total_100 += (total_minutes_worked / 60.0)
        
        # --- LÓGICA PARA DIAS NORMAIS (permanece a mesma) ---
        else:
            if len(day_punches) >= 2:
                minutes_punches = sorted([datetime.fromtimestamp(p.timestamp / 1000).hour * 60 + datetime.fromtimestamp(p.timestamp / 1000).minute for p in day_punches])
                worked_minutes = minutes_punches[-1] - minutes_punches[0]
                
                if worked_minutes > 0:
                    overtime_hours = worked_minutes / 60.0
                    if overtime_hours > 2.0:
                        app_total_50 += 2.0
                        app_total_100 += (overtime_hours - 2.0)
                    else:
                        app_total_50 += overtime_hours


    # =========================================================================
    # PASSO 4: Somar os totais do Sistema Principal com os totais do Novo Sistema
    # =========================================================================
    final_total_50 = main_system_total_50 + app_total_50
    final_total_100 = main_system_total_100 + app_total_100

    return {
        "status": "success",
        "calculation": {
            "month": request.month,
            "year": request.year,
            "app_hours_50": round(app_total_50, 2), # Adicionando para clareza no resultado
            "app_hours_100": round(app_total_100, 2), # Adicionando para clareza no resultado
            "final_total_hours_50": round(final_total_50, 2),
            "final_total_hours_100": round(final_total_100, 2)
        }
    }


@app.get("/main-system-hours")
def get_main_system_hours(
    employee_id: str = Query(..., description="Matrícula completa do funcionário (ex: 010112345)"),
    year: int = Query(..., description="Ano do cálculo"),
    month: int = Query(..., description="Mês do cálculo"),
    db: Session = Depends(get_db_main)
):
    """
    Busca as horas extras do sistema principal para um dado funcionário e mês,
    já totalizando e separando em 50% e 100%.
    Este é o PASSO 1 do fluxo, responsável por popular os campos na tela.
    """
    try:
        # 1. Busca o dicionário contendo as horas extras de CADA DIA do mês.
        daily_overtime = main_system_queries.get_overtime_from_main_system(
            db=db,
            employee_id=employee_id,
            year=year,
            month=month
        )
    except Exception as e:
        # Se a busca no banco de dados principal falhar, retorne um erro claro.
        raise HTTPException(
            status_code=500,
            detail=f"Não foi possível buscar os dados do sistema principal. Erro: {e}"
        )

    # 2. Inicializa os contadores para os totais do mês.
    total_hours_50 = 0.0
    total_hours_100 = 0.0

    # 3. Itera sobre as horas de cada dia para calcular os totais mensais.
    # A regra aplicada é: as primeiras 2h extras do dia são 50%, o restante é 100%.
    for daily_hours in daily_overtime.values():
        if daily_hours > 2.0:
            total_hours_50 += 2.0  # Adiciona as primeiras 2 horas ao total de 50%
            total_hours_100 += (daily_hours - 2.0)  # Adiciona o excedente ao total de 100%
        else:
            total_hours_50 += daily_hours  # Se for 2h ou menos, tudo vai para o total de 50%
            
    # 4. Retorna a resposta JSON no formato que o frontend espera.
    return {
        "status": "success",
        "main_system_hours_50": round(total_hours_50, 2),
        "main_system_hours_100": round(total_hours_100, 2)
    }


@app.post("/report")
def generate_report(request: ReportRequest, db_app: Session = Depends(get_db_app), db_main: Session = Depends(get_db_main)):
    """
    Gera um relatório consolidado de horas extras para múltiplos funcionários
    dentro de um período de tempo.
    """
    employee_ids_to_process = request.employee_ids

    # Se a lista de IDs estiver vazia, pegamos todos os funcionários
    if not employee_ids_to_process:
        # Você precisaria de uma função que retorne todos os funcionários
        # Ex: all_employees = db_app.query(models.Employee).all()
        # employee_ids_to_process = [emp.employee_id for emp in all_employees]
        pass # Implementar a busca de todos os funcionários

    report_data = []

    for emp_id in employee_ids_to_process:
        # =================================================================
        # REUTILIZE A LÓGICA DE CÁLCULO QUE JÁ TEMOS AQUI
        # Esta parte seria uma nova função que você pode chamar tanto aqui
        # quanto na rota /calculate para evitar duplicar código.
        # =================================================================
        
        # Exemplo simplificado:
        # 1. Calcular horas do sistema principal para o período
        main_system_hours = calculate_main_system_totals(db_main, emp_id, request.start_date, request.end_date)
        
        # 2. Calcular horas do novo sistema para o período
        new_system_hours = calculate_new_system_totals(db_app, emp_id, request.start_date, request.end_date)

        # 3. Adicionar os dados compilados à lista do relatório
        report_data.append({
            "employee_id": emp_id,
            # "employee_name": ... (buscar o nome do funcionário),
            "main_system_hours_50": main_system_hours.get("total_50", 0),
            "main_system_hours_100": main_system_hours.get("total_100", 0),
            "new_system_hours_50": new_system_hours.get("total_50", 0),
            "new_system_hours_100": new_system_hours.get("total_100", 0),
        })

    return {"status": "success", "data": report_data}

