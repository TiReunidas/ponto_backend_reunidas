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
    """Combina batidas dando prioridade para as batidas do aplicativo."""
    return {
        key: app_punches.get(key) or main_punches.get(key) 
        for key in ["entry1", "exit1", "entry2", "exit2"]
    }

def _calculate_minutes_standard(punches: Dict[str, Optional[time]]) -> int:
    if not punches or not any(punches.values()): return 0
    total_minutos = 0
    dummy_date = date.today()
    if punches.get("entry1") and punches.get("exit1"):
        total_minutos += (datetime.combine(dummy_date, punches["exit1"]) - datetime.combine(dummy_date, punches["entry1"])).total_seconds() / 60
    if punches.get("entry2") and punches.get("exit2"):
        total_minutos += (datetime.combine(dummy_date, punches["exit2"]) - datetime.combine(dummy_date, punches["entry2"])).total_seconds() / 60
    return int(round(total_minutos))

def _calculate_minutes_overnight_by_day(punches_map: Dict[date, Dict[str, Optional[time]]]) -> Dict[date, int]:
    worked_minutes_map = {}
    all_punches = []
    # 1. Coleta e ordena todas as batidas em uma única linha do tempo
    for d in sorted(punches_map.keys()):
        day_punches = punches_map[d]
        for punch_type in ["entry1", "exit1", "entry2", "exit2"]:
            if day_punches.get(punch_type):
                all_punches.append(datetime.combine(d, day_punches[punch_type]))
    all_punches.sort()

    if not all_punches:
        return {}

    current_shift_start_date = None
    
    # 2. Processa as batidas em pares (entrada/saída)
    for i in range(0, len(all_punches) - 1, 2):
        start_dt = all_punches[i]
        end_dt = all_punches[i+1]
        
        # 3. Identifica o início de um novo turno
        # Se for o primeiro par de batidas, ou se houve uma pausa longa (ex: > 4 horas)
        if i == 0:
             current_shift_start_date = start_dt.date()
        else:
            previous_end_dt = all_punches[i-1]
            if (start_dt - previous_end_dt) > timedelta(hours=4):
                current_shift_start_date = start_dt.date()
        
        duration = (end_dt - start_dt).total_seconds() / 60
        
        # 4. Acumula a duração total na data de INÍCIO do turno
        worked_minutes_map[current_shift_start_date] = worked_minutes_map.get(current_shift_start_date, 0) + duration

    return {d: int(round(m)) for d, m in worked_minutes_map.items()}

def calculate_daily_balance(work_date: date, worked_minutes: int, planned_minutes: int, day_type: Optional[str]) -> Dict[str, int]:
    calculated = {"normal": 0, "overtime_50": 0, "overtime_100": 0, "undertime": 0}
    is_holiday_or_dsr = work_date in br_holidays or (day_type and day_type in ['D', 'C'])

    if is_holiday_or_dsr:
        if worked_minutes > 0:
            calculated["overtime_100"] = worked_minutes
        elif planned_minutes > 0:
            calculated["undertime"] = -planned_minutes
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
            calculated["normal"] = worked_minutes
            
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
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {"status": "success", "username": new_user.username}

@app.get("/employees/main")
def get_all_employees(db: Session = Depends(get_db_main), current_user: models.AppUser = Depends(get_current_user)):
    return {"status": "success", "employees": main_system_queries.get_all_employees_from_main_system(db)}

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

                # --- CORREÇÃO FINAL AQUI ---
                # Garante que o shift_code tenha 3 dígitos (ex: '2' vira '002')
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
        
        main_punches_map = {}
        app_punches_map = {}
        
        end_fetch_date = end_date + timedelta(days=1)
        current_date_fetch = start_date
        while current_date_fetch <= end_fetch_date:
            main_punches_map[current_date_fetch] = main_system_queries.get_main_system_punches_for_day(db_main, emp_id, current_date_fetch)
            app_punches_db = db_app.query(models.ExternalPunch).filter_by(employee_id=emp_id, work_date=current_date_fetch).first()
            app_punches_map[current_date_fetch] = {
                "entry1": app_punches_db.entry1 if app_punches_db else None, "exit1": app_punches_db.exit1 if app_punches_db else None, 
                "entry2": app_punches_db.entry2 if app_punches_db else None, "exit2": app_punches_db.exit2 if app_punches_db else None
            }
            current_date_fetch += timedelta(days=1)

        planned_start_time = default_shift_info.get("planned_start_time")
        is_overnight_shift = planned_start_time and planned_start_time.hour >= 18
        
        worked_minutes_per_day = {}
        display_main_punches = main_punches_map.copy()
        display_app_punches = app_punches_map.copy()

        if is_overnight_shift:
            logger.info(f"Funcionário {emp_id} detectado com turno NOTURNO. Usando lógica de cálculo e exibição avançada.")
            
            combined_punches_map = {d: _combine_punches(main_punches_map.get(d, {}), app_punches_map.get(d, {})) for d in main_punches_map}
            worked_minutes_per_day = _calculate_minutes_overnight_by_day(combined_punches_map)

            all_punches = []
            for d in sorted(main_punches_map.keys()):
                punches_of_the_day = []
                for punch_type, punch_time in main_punches_map[d].items():
                    if punch_time: punches_of_the_day.append({'source': 'main', 'datetime': datetime.combine(d, punch_time)})
                for punch_type, punch_time in app_punches_map[d].items():
                    if punch_time: punches_of_the_day.append({'source': 'app', 'datetime': datetime.combine(d, punch_time)})
                punches_of_the_day.sort(key=lambda x: x['datetime'])
                all_punches.extend(punches_of_the_day)
            
            for d in display_main_punches:
                display_main_punches[d] = {}
                display_app_punches[d] = {}
            
            if all_punches:
                shifts = []
                current_shift = [all_punches[0]]
                for i in range(1, len(all_punches)):
                    punch = all_punches[i]
                    previous_punch = all_punches[i-1]
                    # --- AJUSTE FINAL AQUI ---
                    # Aumentamos o tempo da pausa para 6 horas para não quebrar o turno no meio.
                    if (punch['datetime'] - previous_punch['datetime']) > timedelta(hours=6):
                        shifts.append(current_shift)
                        current_shift = []
                    current_shift.append(punch)
                shifts.append(current_shift)

                for shift in shifts:
                    if not shift: continue
                    start_date = shift[0]['datetime'].date()
                    entry_count = 0
                    exit_count = 0
                    for i in range(len(shift)):
                        punch = shift[i]
                        is_entry = (i % 2 == 0)

                        if is_entry:
                            entry_count += 1
                            display_punch_type = f"entry{entry_count}"
                        else:
                            exit_count += 1
                            display_punch_type = f"exit{exit_count}"
                        
                        target_map = display_main_punches if punch['source'] == 'main' else display_app_punches
                        target_map.setdefault(start_date, {})[display_punch_type] = punch['datetime'].time()
        else:
            logger.info(f"Funcionário {emp_id} detectado com turno DIURNO. Usando lógica de cálculo padrão.")
            for current_date in main_punches_map:
                if start_date <= current_date <= end_date:
                    combined = _combine_punches(main_punches_map.get(current_date, {}), app_punches_map.get(current_date, {}))
                    worked_minutes_per_day[current_date] = _calculate_minutes_standard(combined)
        
        # O restante da função continua exatamente igual...
        daily_breakdown_list = []
        totals_in_minutes = {"normal": 0, "overtime_50": 0, "overtime_100": 0, "undertime": 0}

        for day in range(1, num_days_in_month + 1):
            current_date = date(request.year, request.month, day)
            
            planned_minutes = 0; day_type = None; status = None
            
            manual_override = db_app.query(models.ManualOverride).filter_by(employee_id=emp_id, work_date=current_date).first()
            if manual_override:
                status = manual_override.override_type
                calculated_minutes = {"normal": 0, "overtime_50": 0, "overtime_100": 0, "undertime": 0}
            else:
                daily_schedule = db_app.query(models.EscalaDiaria).filter_by(employee_id=emp_id, work_date=current_date).first()
                if daily_schedule:
                    if daily_schedule.day_type == 'FOLGA':
                        status = 'D'; planned_minutes = 0; day_type = 'D'
                    else:
                        shift_code_for_the_day = daily_schedule.shift_code or default_shift_code
                        planned_minutes = main_system_queries.get_standard_shift_minutes(db_main, shift_code_for_the_day)
                        day_type = 'S'
                else:
                    filial = emp_id[:4]
                    day_of_week = (current_date.isoweekday() % 7) + 1
                    cycle_week = get_cycle_week(current_date, request.cycle_start_date, default_shift_info["weeks_in_cycle"])
                    schedule_info = main_system_queries.get_work_schedule_info_for_day(db_main, default_shift_code, filial, cycle_week, day_of_week)
                    planned_minutes = schedule_info.get('minutes', 0)
                    day_type = schedule_info.get('type')
                
                worked_minutes = worked_minutes_per_day.get(current_date, 0)
                calculated_minutes = calculate_daily_balance(current_date, worked_minutes, planned_minutes, day_type)
                if status is None and (current_date in br_holidays or (day_type and day_type in ['D', 'C'])):
                    status = day_type
            
            daily_breakdown_list.append(DailyBreakdown(
                date=current_date, 
                main_system_punches=display_main_punches.get(current_date, {}),
                app_punches=display_app_punches.get(current_date, {}),
                calculated_minutes=calculated_minutes, 
                status=status
            ))
            for key in totals_in_minutes:
                totals_in_minutes[key] += calculated_minutes.get(key, 0)
            
        report_data.append(DetailedReportData(
            employee_id=emp_id,
            employee_name=all_employees_map.get(emp_id, "Nome não encontrado"),
            shift_description=f"{default_shift_info['description']} ({'Noturno' if is_overnight_shift else 'Diurno'})",
            daily_breakdown=daily_breakdown_list,
            totals_in_minutes=totals_in_minutes
        ))
    return report_data