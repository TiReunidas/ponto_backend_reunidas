import logging
import os
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import date, datetime, time, timedelta
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
import holidays
import calendar
import pandas as pd
from fastapi import File, UploadFile

from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi.middleware.cors import CORSMiddleware

import models
from database import SessionLocal_App, engine_app, SessionLocal_Main
import main_system_queries
from main_system_queries import (
    get_schedule_times_for_day,
    get_raw_punches_for_period
)

# --- CONFIGURAÇÕES GERAIS ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

br_holidays = holidays.Brazil(state='GO')
br_holidays.update({"2025-01-21": "Aniversário de Goiatuba"})

models.Base.metadata.create_all(bind=engine_app)
app = FastAPI()

origins = ["*"]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# --- DEPENDÊNCIAS DE BANCO E SEGURANÇA ---
def get_db_app():
    db = SessionLocal_App()
    try: yield db
    finally: db.close()

def get_db_main():
    db = SessionLocal_Main()
    try: yield db
    finally: db.close()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

SECRET_KEY = "SUA_CHAVE_SECRETA_MUITO_FORTE_E_LONGA"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def verify_password(plain_password, hashed_password): return pwd_context.verify(plain_password, hashed_password)
def get_password_hash(password): return pwd_context.hash(password)
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db_app)):
    credentials_exception = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None: raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = db.query(models.AppUser).filter(models.AppUser.username == username).first()
    if user is None: raise credentials_exception
    return user

# --- LÓGICA DE CÁLCULO DE CICLO ---
def get_cycle_week(work_date: date, start_date: date, weeks_in_cycle: int) -> int:
    if not start_date or not weeks_in_cycle or weeks_in_cycle == 0: return 1
    days_passed = (work_date - start_date).days
    if days_passed < 0: return 1
    current_week = (days_passed // 7) % weeks_in_cycle + 1
    return current_week

# --- Pydantic Models ---
class UserCreate(BaseModel): username: str; password: str
class Token(BaseModel): access_token: str; token_type: str
class RelatorioRequest(BaseModel):
    matricula: str
    data_inicio: str
    data_fim: str
class ExternalPunchRequest(BaseModel): employee_id: str; work_date: date; entry1: Optional[time] = None; exit1: Optional[time] = None; entry2: Optional[time] = None; exit2: Optional[time] = None
class CalculatedMinutes(BaseModel):
    normal: int
    overtime_50: int
    overtime_100: int
    undertime: int
class DailyBreakdown(BaseModel):
    date: date
    main_system_punches: Dict[str, Optional[time]]
    app_punches: Dict[str, Optional[time]]
    calculated_minutes: CalculatedMinutes
    status: Optional[str] = None
class DetailedReportData(BaseModel):
    employee_id: str
    employee_name: str
    shift_description: str
    daily_breakdown: List[DailyBreakdown]
    totals_in_minutes: CalculatedMinutes
class MonthlyReportRequest(BaseModel):
    employee_ids: List[str]
    year: int
    month: int
    cycle_start_date: date
class ManualOverrideRequest(BaseModel):
    employee_id: str
    start_date: date
    end_date: date
    override_type: str
    description: Optional[str] = None

# --- LÓGICA DE NEGÓCIO ---

def _combine_punches(main_punches: Dict[str, Optional[time]], app_punches: Dict[str, Optional[time]]) -> Dict[str, Optional[time]]:
    return {
        key: app_punches.get(key) or main_punches.get(key)
        for key in ["entry1", "exit1", "entry2", "exit2"]
    }

def _calculate_minutes_from_punches(punches: List[datetime]) -> int:
    total_seconds = 0
    for i in range(0, len(punches) - (len(punches) % 2), 2):
        start_dt = punches[i]
        end_dt = punches[i+1]
        total_seconds += (end_dt - start_dt).total_seconds()
    return int(round(total_seconds / 60))

def calculate_daily_balance(work_date: date, worked_minutes: int, planned_minutes: int, day_type: Optional[str]) -> Dict[str, int]:
    calculated = {"normal": 0, "overtime_50": 0, "overtime_100": 0, "undertime": 0}
    is_holiday_or_dsr = work_date in br_holidays or (day_type and day_type in ['D', 'C'])
    if is_holiday_or_dsr:
        if worked_minutes > 0:
            calculated["overtime_100"] = worked_minutes
    else:
        if planned_minutes > 0:
            balance = worked_minutes - planned_minutes
            if balance > 0:
                calculated["normal"] = planned_minutes
                overtime_50 = min(balance, 120)
                overtime_100 = balance - overtime_50
                calculated["overtime_50"] = int(overtime_50)
                if overtime_100 > 0:
                    calculated["overtime_100"] = int(overtime_100)
            else:
                calculated["normal"] = worked_minutes
                calculated["undertime"] = balance
        elif worked_minutes > 0:
             calculated["overtime_50"] = worked_minutes
    return {k: int(v) for k, v in calculated.items()}

# --- ENDPOINTS ---
@app.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db_app)):
    user = db.query(models.AppUser).filter(models.AppUser.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password", headers={"WWW-Authenticate": "Bearer"})
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": user.username}, expires_delta=access_token_expires)
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/users/register")
def register_user(user: UserCreate, db: Session = Depends(get_db_app)):
    if db.query(models.AppUser).filter(models.AppUser.username == user.username).first():
        raise HTTPException(status_code=400, detail="Username already registered")
    new_user = models.AppUser(username=user.username, hashed_password=get_password_hash(user.password))
    db.add(new_user); db.commit(); db.refresh(new_user)
    return {"status": "success", "username": new_user.username}

@app.get("/employees/main")
def get_all_employees(db: Session = Depends(get_db_main), current_user: models.AppUser = Depends(get_current_user)):
    return {"status": "success", "employees": main_system_queries.get_all_employees_from_main_system(db)}

@app.post("/get-relatorio-funcionario")
async def get_relatorio_funcionario_endpoint(data: RelatorioRequest, db: Session = Depends(get_db_main)):
    try:
        matricula = data.matricula
        data_inicio = datetime.strptime(data.data_inicio, "%Y-%m-%d").date()
        data_fim = datetime.strptime(data.data_fim, "%Y-%m-%d").date()
        filial = matricula[:4]
        turno = main_system_queries.get_employee_shift_code(db, matricula)
        if not turno:
            raise HTTPException(status_code=404, detail="Turno do funcionário não encontrado.")
        shift_details = main_system_queries.get_shift_info(db, turno)
        weeks_in_cycle = shift_details.get("weeks_in_cycle", 1)
        start_date_protheus = date(1980, 1, 6)
        all_punches = get_raw_punches_for_period(db, matricula, data_inicio - timedelta(days=1), data_fim + timedelta(days=1))
        dias_relatorio = []
        data_atual = data_inicio
        while data_atual <= data_fim:
            days_diff = (data_atual - start_date_protheus).days
            cycle_week = (days_diff // 7) % weeks_in_cycle + 1 if weeks_in_cycle > 0 else 1
            day_of_week_protheus = (data_atual.isoweekday() % 7) + 1
            escala_info = main_system_queries.get_work_schedule_info_for_day(db, turno, filial, cycle_week, day_of_week_protheus)
            jornada_prevista_minutos = escala_info.get("minutes", 0)
            tipo_dia = escala_info.get("type", "S")
            batidas_do_dia = {"entry1": None, "exit1": None, "entry2": None, "exit2": None}
            horario_previsto = ""
            horas_trabalhadas_str = "00:00"
            if tipo_dia not in ["F", "D"]:
                schedule_times = get_schedule_times_for_day(db, turno, filial, cycle_week, day_of_week_protheus)
                if schedule_times.get("start") and schedule_times.get("end"):
                    start_time = schedule_times["start"]
                    end_time = schedule_times["end"]
                    horario_previsto = f"{start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}"
                    shift_start_dt = datetime.combine(data_atual, start_time)
                    shift_end_dt = datetime.combine(data_atual, end_time)
                    if shift_end_dt < shift_start_dt: shift_end_dt += timedelta(days=1)
                    search_window_start = shift_start_dt - timedelta(hours=2)
                    search_window_end = shift_end_dt + timedelta(hours=4)
                    punches_for_this_shift = sorted([p for p in all_punches if search_window_start <= p <= search_window_end])
                    if punches_for_this_shift:
                        worked_minutes = _calculate_minutes_from_punches(punches_for_this_shift)
                        horas_trabalhadas_str = f"{worked_minutes // 60:02d}:{worked_minutes % 60:02d}"
                        if len(punches_for_this_shift) >= 1: batidas_do_dia["entry1"] = punches_for_this_shift[0].time().strftime('%H:%M')
                        if len(punches_for_this_shift) >= 2: batidas_do_dia["exit1"] = punches_for_this_shift[1].time().strftime('%H:%M')
                        if len(punches_for_this_shift) >= 3: batidas_do_dia["entry2"] = punches_for_this_shift[2].time().strftime('%H:%M')
                        if len(punches_for_this_shift) >= 4: batidas_do_dia["exit2"] = punches_for_this_shift[3].time().strftime('%H:%M')
            dias_relatorio.append({
                "data": data_atual.strftime("%d/%m/%Y"),
                "dia_semana": ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"][data_atual.weekday()],
                "horario_previsto": horario_previsto,
                "jornada_prevista": f"{jornada_prevista_minutos // 60:02d}:{jornada_prevista_minutos % 60:02d}",
                "batidas": batidas_do_dia,
                "horas_trabalhadas": horas_trabalhadas_str,
                "tipo_dia": tipo_dia
            })
            data_atual += timedelta(days=1)
        return {"dias": dias_relatorio}
    except Exception as e:
        logger.error(f"Erro ao gerar relatório para {data.matricula}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Erro interno ao gerar relatório: {str(e)}")

@app.post("/report/monthly", response_model=List[DetailedReportData])
def generate_detailed_monthly_report(request: MonthlyReportRequest, db_app: Session = Depends(get_db_app), db_main: Session = Depends(get_db_main), current_user: models.AppUser = Depends(get_current_user)):
    report_data = []
    all_employees_map = {emp['employee_id']: emp['name'] for emp in main_system_queries.get_all_employees_from_main_system(db_main)}
    start_date = date(request.year, request.month, 1)
    _, num_days_in_month = calendar.monthrange(request.year, request.month)
    end_date = date(request.year, request.month, num_days_in_month)
    
    for emp_id in request.employee_ids:
        default_shift_code = main_system_queries.get_employee_shift_code(db_main, emp_id)
        if not default_shift_code:
            logger.warning(f"Pulando funcionário {emp_id}: turno padrão não encontrado.")
            continue
        default_shift_info = main_system_queries.get_shift_info(db_main, default_shift_code)
        is_overnight_shift = default_shift_info.get("planned_start_time") and default_shift_info["planned_start_time"].hour >= 18
        
        main_system_punches_list = get_raw_punches_for_period(db_main, emp_id, start_date - timedelta(days=1), end_date + timedelta(days=1))
        
        app_punches_db = db_app.query(models.ExternalPunch).filter(
            models.ExternalPunch.employee_id == emp_id,
            models.ExternalPunch.work_date >= start_date,
            models.ExternalPunch.work_date <= end_date
        ).all()
        
        app_punches_map = {p.work_date: {"entry1": p.entry1, "exit1": p.exit1, "entry2": p.entry2, "exit2": p.exit2} for p in app_punches_db}

        daily_breakdown_list = []
        totals_in_minutes = {"normal": 0, "overtime_50": 0, "overtime_100": 0, "undertime": 0}

        for day in range(1, num_days_in_month + 1):
            current_date = date(request.year, request.month, day)
            filial = emp_id[:4]
            weeks_in_cycle = default_shift_info.get("weeks_in_cycle", 1)
            day_of_week_protheus = (current_date.isoweekday() % 7) + 1
            # Recalcula cycle_week DENTRO do loop para garantir que está correto para cada dia
            days_diff = (current_date - request.cycle_start_date).days
            cycle_week = (days_diff // 7) % weeks_in_cycle + 1 if weeks_in_cycle > 0 and days_diff >= 0 else 1

            planned_minutes = 0
            day_type = None # Inicia como None para garantir que seja definido
            status = None
            
            manual_override = db_app.query(models.ManualOverride).filter_by(employee_id=emp_id, work_date=current_date).first()
            if manual_override:
                status = manual_override.override_type
                calculated_minutes = {"normal": 0, "overtime_50": 0, "overtime_100": 0, "undertime": 0}
                main_punches_for_day = {}
            else:
                # --- LÓGICA DE PRIORIDADE CORRIGIDA ---
                # 1. Checa a planilha de escala primeiro
                daily_schedule_app = db_app.query(models.EscalaDiaria).filter_by(employee_id=emp_id, work_date=current_date).first()
                if daily_schedule_app:
                    if daily_schedule_app.day_type == 'FOLGA':
                        day_type = 'D'
                        status = 'D'
                    else: # É 'TRABALHO' na planilha
                        day_type = 'S' # Força a ser um dia de trabalho
                        shift_code = daily_schedule_app.shift_code or default_shift_code
                        planned_minutes = main_system_queries.get_standard_shift_minutes(db_main, shift_code)
                else: 
                    # 2. Se não está na planilha, usa a escala padrão do Protheus
                    schedule_info = main_system_queries.get_work_schedule_info_for_day(db_main, default_shift_code, filial, cycle_week, day_of_week_protheus)
                    planned_minutes = schedule_info.get('minutes', 0)
                    day_type = schedule_info.get('type', 'S')

                # 3. Busca as batidas apenas se o dia for definido como de trabalho
                main_punches_for_day = {}
                if day_type not in ['F', 'D', 'C']:
                    schedule_times = get_schedule_times_for_day(db_main, default_shift_code, filial, cycle_week, day_of_week_protheus)
                    if schedule_times.get("start"):
                        start_time = schedule_times["start"]
                        end_time = schedule_times.get("end") or time(23, 59)
                        shift_start_dt = datetime.combine(current_date, start_time)
                        shift_end_dt = datetime.combine(current_date, end_time)
                        if shift_end_dt < shift_start_dt: shift_end_dt += timedelta(days=1)
                        
                        search_window_start = shift_start_dt - timedelta(hours=2)
                        search_window_end = shift_end_dt + timedelta(hours=4)
                        
                        punches_for_this_shift = sorted([p for p in main_system_punches_list if search_window_start <= p <= search_window_end])
                        
                        if punches_for_this_shift:
                            if len(punches_for_this_shift) >= 1: main_punches_for_day["entry1"] = punches_for_this_shift[0].time()
                            if len(punches_for_this_shift) >= 2: main_punches_for_day["exit1"]  = punches_for_this_shift[1].time()
                            if len(punches_for_this_shift) >= 3: main_punches_for_day["entry2"] = punches_for_this_shift[2].time()
                            if len(punches_for_this_shift) >= 4: main_punches_for_day["exit2"]  = punches_for_this_shift[3].time()

                app_punches_for_day = app_punches_map.get(current_date, {})
                combined_punches_map = _combine_punches(main_punches_for_day, app_punches_for_day)
                
                temp_punches = []
                if combined_punches_map.get("entry1"): temp_punches.append(datetime.combine(current_date, combined_punches_map["entry1"]))
                if combined_punches_map.get("exit1"):
                    exit_dt = datetime.combine(current_date, combined_punches_map["exit1"])
                    if temp_punches and exit_dt < temp_punches[-1]: exit_dt += timedelta(days=1)
                    temp_punches.append(exit_dt)
                if combined_punches_map.get("entry2"):
                    entry_dt = datetime.combine(current_date, combined_punches_map["entry2"])
                    if temp_punches and entry_dt < temp_punches[-1]: entry_dt += timedelta(days=1)
                    temp_punches.append(entry_dt)
                if combined_punches_map.get("exit2"):
                    exit_dt = datetime.combine(current_date, combined_punches_map["exit2"])
                    if temp_punches and exit_dt < temp_punches[-1]: exit_dt += timedelta(days=1)
                    temp_punches.append(exit_dt)
                
                worked_minutes = _calculate_minutes_from_punches(temp_punches)
                calculated_minutes = calculate_daily_balance(current_date, worked_minutes, planned_minutes, day_type)
            
            daily_breakdown_list.append(DailyBreakdown(
                date=current_date,
                main_system_punches=main_punches_for_day,
                app_punches=app_punches_map.get(current_date, {}),
                calculated_minutes=calculated_minutes,
                status=status
            ))
            for key in totals_in_minutes: totals_in_minutes[key] += calculated_minutes.get(key, 0)

        report_data.append(DetailedReportData(
            employee_id=emp_id,
            employee_name=all_employees_map.get(emp_id, "Nome não encontrado"),
            shift_description=f"{default_shift_info['description']} ({'Noturno' if is_overnight_shift else 'Diurno'})",
            daily_breakdown=daily_breakdown_list,
            totals_in_minutes=totals_in_minutes
        ))
    return report_data


# --- OUTROS ENDPOINTS (O RESTO DO SEU CÓDIGO) ---
@app.post("/punches/external", status_code=201)
def receive_external_punches(request: ExternalPunchRequest, db: Session = Depends(get_db_app), current_user: models.AppUser = Depends(get_current_user)):
    existing_punch = db.query(models.ExternalPunch).filter_by(employee_id=request.employee_id, work_date=request.work_date).first()
    if existing_punch:
        for key, value in request.dict().items(): setattr(existing_punch, key, value)
        existing_punch.status = "pending"; message = "Registro de ponto externo atualizado."
    else:
        existing_punch = models.ExternalPunch(**request.dict()); db.add(existing_punch); message = "Registro de ponto externo criado."
    db.commit(); db.refresh(existing_punch)
    return {"status": "success", "message": message, "data": existing_punch}

@app.get("/punches/external/{employee_id}/{work_date}")
def get_external_punches_for_day(employee_id: str, work_date: date, db: Session = Depends(get_db_app), current_user: models.AppUser = Depends(get_current_user)):
    punches = db.query(models.ExternalPunch).filter_by(employee_id=employee_id, work_date=work_date).first()
    if not punches: raise HTTPException(status_code=404, detail="Nenhum registro de ponto externo encontrado para esta data.")
    return punches

@app.post("/overrides", status_code=201)
def create_or_update_override_range(request: ManualOverrideRequest, db: Session = Depends(get_db_app), current_user: models.AppUser = Depends(get_current_user)):
    if request.start_date > request.end_date:
        raise HTTPException(status_code=400, detail="A data de início não pode ser posterior à data de fim.")
    days_to_process = (request.end_date - request.start_date).days + 1
    count = 0
    for i in range(days_to_process):
        current_date = request.start_date + timedelta(days=i)
        existing = db.query(models.ManualOverride).filter_by(employee_id=request.employee_id, work_date=current_date).first()
        if existing:
            existing.override_type = request.override_type
            existing.description = request.description
        else:
            new_override = models.ManualOverride(employee_id=request.employee_id, work_date=current_date, override_type=request.override_type, description=request.description)
            db.add(new_override)
        count += 1
    db.commit()
    return {"status": "success", "message": f"{count} dia(s) de '{request.override_type}' foram aplicados com sucesso."}

@app.delete("/overrides", status_code=200)
def delete_override_range(request: ManualOverrideRequest, db: Session = Depends(get_db_app), current_user: models.AppUser = Depends(get_current_user)):
    if request.start_date > request.end_date:
        raise HTTPException(status_code=400, detail="A data de início não pode ser posterior à data de fim.")
    overrides_to_delete = db.query(models.ManualOverride).filter(
        models.ManualOverride.employee_id == request.employee_id,
        models.ManualOverride.work_date >= request.start_date,
        models.ManualOverride.work_date <= request.end_date
    ).all()
    if not overrides_to_delete:
        raise HTTPException(status_code=404, detail="Nenhum ajuste manual encontrado para este período.")
    count = len(overrides_to_delete)
    for override in overrides_to_delete:
        db.delete(override)
    db.commit()
    return {"status": "success", "message": f"{count} ajuste(s) manual(is) foram removidos com sucesso."}

@app.post("/schedules/upload")
async def upload_schedule_file(db: Session = Depends(get_db_app), file: UploadFile = File(...), current_user: models.AppUser = Depends(get_current_user)):
    if not file.filename.endswith(('.csv', '.xlsx')):
        raise HTTPException(status_code=400, detail="Formato de arquivo inválido. Por favor, envie um .csv ou .xlsx")
    try:
        if file.filename.endswith('.csv'):
            df = pd.read_csv(file.file, dtype={'employee_id': str, 'shift_code': str})
        else:
            df = pd.read_excel(file.file, dtype={'employee_id': str, 'shift_code': str})

        required_columns = ['employee_id', 'work_date', 'day_type', 'shift_code']
        if not all(col in df.columns for col in required_columns):
            raise HTTPException(status_code=400, detail=f"O arquivo deve conter as colunas: {required_columns}")

        success_count, error_count = 0, 0
        for _, row in df.iterrows():
            try:
                employee_id = str(row['employee_id']).strip().zfill(10)
                work_date = pd.to_datetime(row['work_date']).date()
                day_type = str(row['day_type']).upper()
                shift_code = str(row['shift_code']).strip().split('.')[0].zfill(3) if pd.notna(row['shift_code']) else None

                if day_type not in ['TRABALHO', 'FOLGA']:
                    error_count += 1
                    continue
                existing_schedule = db.query(models.EscalaDiaria).filter_by(employee_id=employee_id, work_date=work_date).first()
                if existing_schedule:
                    existing_schedule.day_type = day_type
                    existing_schedule.shift_code = shift_code
                else:
                    new_schedule = models.EscalaDiaria(employee_id=employee_id, work_date=work_date, day_type=day_type, shift_code=shift_code)
                    db.add(new_schedule)
                success_count += 1
            except Exception as e:
                logger.error(f"Erro ao processar linha da escala: {row}. Erro: {e}")
                error_count += 1
        db.commit()
        db.expire_all()
        return {"status": "success", "message": f"Arquivo processado. {success_count} escalas salvas, {error_count} linhas com erro."}
    except Exception as e:
        logger.error(f"Falha ao processar o arquivo de escala: {e}")
        raise HTTPException(status_code=500, detail=f"Não foi possível processar o arquivo. Erro: {e}")

