import logging
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, date, time, timedelta
from typing import Dict, Optional, List, Any

logger = logging.getLogger(__name__)

def get_all_employees_from_main_system(db: Session) -> List[Dict[str, str]]:
    logger.info("Buscando lista de todos os funcionários ativos do sistema principal com descrição de turno.")
    sql_query = text("""
        SELECT
            sra.RA_FILIAL AS filial,
            sra.RA_MAT AS matricula,
            TRIM(sra.RA_NOME) AS nome,
            MAX(TRIM(sr6.R6_DESC)) AS turno_descricao
        FROM
            SRA010 AS sra
        LEFT JOIN
            SR6010 AS sr6 ON sra.RA_TNOTRAB = sr6.R6_TURNO
            AND (sr6.R6_FILIAL = sra.RA_FILIAL OR sr6.R6_FILIAL = '')
            AND sr6.D_E_L_E_T_ <> '*'
        WHERE
            sra.RA_SITFOLH <> 'D'
            AND (sra.D_E_L_E_T_ IS NULL OR sra.D_E_L_E_T_ <> '*')
        GROUP BY
            sra.RA_FILIAL, sra.RA_MAT, sra.RA_NOME
        ORDER BY
            sra.RA_NOME;
    """)
    employees = []
    try:
        results = db.execute(sql_query).fetchall()
        for row in results:
            employees.append({
                "employee_id": f"{row.filial}{row.matricula}",
                "name": row.nome,
                "shift_description": row.turno_descricao or "Turno não especificado"
            })
        logger.info(f"Encontrados {len(employees)} funcionários ativos.")
        return employees
    except Exception as e:
        logger.error(f"Erro ao buscar lista de funcionários do sistema principal: {e}")
        raise e

def get_shift_info(db: Session, shift_code: str) -> Dict:
    shift_info = {
        "description": f"Turno {shift_code}",
        "weeks_in_cycle": 1,
        "planned_start_time": None
    }

    desc_query = text("SELECT TOP 1 TRIM(R6_DESC) FROM SR6010 WHERE R6_TURNO = :shift_code AND D_E_L_E_T_ <> '*'")
    description = db.execute(desc_query, {"shift_code": shift_code}).scalar_one_or_none()
    if description:
        shift_info["description"] = description

    cycle_query = text("SELECT MAX(CAST(PJ_SEMANA AS INT)) FROM SPJ010 WHERE PJ_TURNO = :shift_code AND D_E_L_E_T_ <> '*'")
    weeks = db.execute(cycle_query, {"shift_code": shift_code}).scalar_one_or_none()
    if weeks and weeks > 0:
        shift_info["weeks_in_cycle"] = weeks

    start_time_query = text("""
        SELECT TOP 1 PJ_ENTRA1 FROM SPJ010 WHERE PJ_TURNO = :shift_code AND PJ_ENTRA1 > 0 AND D_E_L_E_T_ <> '*' ORDER BY PJ_SEMANA, PJ_DIA
    """)
    start_time_float = db.execute(start_time_query, {"shift_code": shift_code}).scalar_one_or_none()
    if start_time_float is not None:
        hour = int(start_time_float)
        minute = int(round((start_time_float - hour) * 100))
        if 0 <= minute <= 59:
             shift_info["planned_start_time"] = time(hour, minute)

    return shift_info

def get_work_schedule_info_for_day(db: Session, shift_code: str, filial: str, cycle_week: int, day_of_week: int) -> Dict[str, Any]:
    filial_curta = filial[:2]
    semana_formatada = str(cycle_week).zfill(2)
    dia_formatado = str(day_of_week)
    logger.info(f"VERIFICANDO BANCO: PJ_TURNO='{shift_code}', PJ_FILIAL='{filial_curta}', PJ_SEMANA='{semana_formatada}', PJ_DIA='{dia_formatado}'")
    default_result = {"minutes": 0, "type": "F"}
    sql_query = text("""
        SELECT TOP 1
            (ISNULL(PJ_HRSTRAB, 0) + ISNULL(PJ_HRSTRA2, 0)) AS horas_trabalhadas,
            PJ_TPDIA
        FROM SPJ010
        WHERE TRIM(PJ_TURNO) = :shift_code
          AND (TRIM(PJ_FILIAL) = :filial OR TRIM(PJ_FILIAL) = '')
          AND TRIM(PJ_SEMANA) = :cycle_week
          AND TRIM(PJ_DIA) = :day_of_week
          AND D_E_L_E_T_ <> '*'
        ORDER BY PJ_FILIAL DESC;
    """)
    try:
        result = db.execute(sql_query, {"shift_code": shift_code, "filial": filial_curta, "cycle_week": semana_formatada, "day_of_week": dia_formatado}).fetchone()
        if result:
            hours = float(result.horas_trabalhadas or 0)
            parte_horas = int(hours)
            parte_minutos = int(round((hours - parte_horas) * 100))
            total_minutes = (parte_horas * 60) + parte_minutos
            day_type = result.PJ_TPDIA.strip() if result.PJ_TPDIA else "S"
            logger.info(f"SUCESSO! Jornada encontrada para o turno {shift_code}: {total_minutes} minutos, Tipo: {day_type}.")
            return {"minutes": total_minutes, "type": day_type}
        else:
            logger.warning(f"Jornada não encontrada para o turno {shift_code} na filial {filial_curta}. Assumindo folga.")
            return default_result
    except Exception as e:
        logger.error(f"Erro ao buscar jornada de trabalho para o turno {shift_code}: {e}")
        return default_result

def get_employee_shift_code(db: Session, employee_id: str) -> Optional[str]:
    logger.info(f"Buscando código do turno para o funcionário: {employee_id}")
    filial = employee_id[:4]
    matricula = employee_id[4:]
    sql_query = text("""
        SELECT TOP 1 TRIM(RA_TNOTRAB) AS shift_code FROM SRA010
        WHERE RA_FILIAL = :filial AND RA_MAT = :matricula AND (D_E_L_E_T_ IS NULL OR D_E_L_E_T_ <> '*')
    """)
    try:
        result = db.execute(sql_query, {"filial": filial, "matricula": matricula}).scalar_one_or_none()
        if result:
            logger.info(f"Turno encontrado para {employee_id}: {result}")
            return result
        else:
            logger.warning(f"Nenhum turno encontrado para o funcionário {employee_id}")
            return None
    except Exception as e:
        logger.error(f"Erro ao buscar turno para o funcionário {employee_id}: {e}")
        return None

def get_standard_shift_minutes(db: Session, shift_code: str) -> int:
    logger.info(f"Buscando jornada padrão para o turno: {shift_code}")
    sql_query = text("""
        SELECT TOP 1
            (ISNULL(PJ_HRSTRAB, 0) + ISNULL(PJ_HRSTRA2, 0)) AS horas_trabalhadas
        FROM SPJ010
        WHERE TRIM(PJ_TURNO) = :shift_code
          AND (ISNULL(PJ_HRSTRAB, 0) + ISNULL(PJ_HRSTRA2, 0)) > 0
          AND D_E_L_E_T_ <> '*'
        GROUP BY (ISNULL(PJ_HRSTRAB, 0) + ISNULL(PJ_HRSTRA2, 0))
        ORDER BY COUNT(*) DESC;
    """)
    try:
        result = db.execute(sql_query, {"shift_code": shift_code}).scalar_one_or_none()
        if result:
            hours = float(result or 0)
            parte_horas = int(hours)
            parte_minutos = int(round((hours - parte_horas) * 100))
            total_minutes = (parte_horas * 60) + parte_minutos
            logger.info(f"SUCESSO! Jornada padrão encontrada para o turno {shift_code}: {total_minutes} minutos.")
            return total_minutes
        else:
            logger.warning(f"Nenhuma jornada padrão encontrada para o turno {shift_code}. Retornando 0.")
            return 0
    except Exception as e:
        logger.error(f"Erro ao buscar jornada padrão para o turno {shift_code}: {e}")
        return 0

# --- FUNÇÕES CORRIGIDAS ---

def _convert_float_to_time(hour_float: Optional[float]) -> Optional[time]:
    """Converte um horário em formato float (ex: 22.40) para um objeto time."""
    if hour_float is None or hour_float == 0:
        return None
    try:
        hour = int(hour_float)
        minute = int(round((hour_float - hour) * 100))
        return time(hour, minute) if 0 <= hour <= 23 and 0 <= minute <= 59 else None
    except (ValueError, TypeError):
        return None

def get_schedule_times_for_day(db: Session, shift_code: str, filial: str, cycle_week: int, day_of_week: int) -> Dict[str, Optional[time]]:
    """Busca os horários de início e fim da escala para um dia específico."""
    filial_curta = filial[:2]
    semana_formatada = str(cycle_week).zfill(2)
    dia_formatado = str(day_of_week)

    # --- CORREÇÃO APLICADA AQUI ---
    sql_query = text("""
        SELECT TOP 1
            PJ_ENTRA1, PJ_SAIDA1, PJ_ENTRA2, PJ_SAIDA2
        FROM SPJ010
        WHERE TRIM(PJ_TURNO) = :shift_code
          AND (TRIM(PJ_FILIAL) = :filial OR TRIM(PJ_FILIAL) = '')
          AND TRIM(PJ_SEMANA) = :cycle_week
          AND TRIM(PJ_DIA) = :day_of_week
          AND D_E_L_E_T_ <> '*'
        ORDER BY PJ_FILIAL DESC;
    """)
    try:
        result = db.execute(sql_query, {
            "shift_code": shift_code, "filial": filial_curta,
            "cycle_week": semana_formatada, "day_of_week": dia_formatado
        }).fetchone()
        if result:
            start_time = _convert_float_to_time(result.PJ_ENTRA1)
            # A saída final do turno é a última batida registrada (SAIDA2 ou, se não houver, SAIDA1)
            end_time = _convert_float_to_time(result.PJ_SAIDA2) or _convert_float_to_time(result.PJ_SAIDA1)
            return {"start": start_time, "end": end_time}
    except Exception as e:
        logger.error(f"Erro ao buscar horários da escala para o turno {shift_code}: {e}")

    return {"start": None, "end": None}

def get_raw_punches_for_period(db: Session, employee_id: str, start_date: date, end_date: date) -> List[datetime]:
    """Busca todas as batidas de um funcionário em um período, retornando uma lista de datetimes."""
    logger.info(f"Buscando todas as batidas brutas para {employee_id} de {start_date} a {end_date}")
    filial_completa = employee_id[:4]
    matricula = employee_id[4:]
    start_str = start_date.strftime('%Y%m%d')
    end_str = end_date.strftime('%Y%m%d')

    all_punches = []

    def fetch_from_table(table_name: str, date_col: str, hour_col: str, mat_col: str, filial_col: str):
        sql = text(f"""
            SELECT {date_col} AS data, {hour_col} AS hora
            FROM {table_name}
            WHERE TRIM({filial_col}) = :filial
              AND TRIM({mat_col}) = :matricula
              AND {date_col} BETWEEN :start_date AND :end_date
              AND (D_E_L_E_T_ IS NULL OR D_E_L_E_T_ <> '*')
        """)
        try:
            results = db.execute(sql, {
                "filial": filial_completa, "matricula": matricula,
                "start_date": start_str, "end_date": end_str
            }).fetchall()

            for row in results:
                punch_time = _convert_float_to_time(row.hora)
                if punch_time:
                    try:
                        punch_date = datetime.strptime(row.data.strip(), '%Y%m%d').date()
                        all_punches.append(datetime.combine(punch_date, punch_time))
                    except (ValueError, AttributeError):
                        continue # Ignora datas mal formatadas
        except Exception as e:
            logger.error(f"Erro ao buscar batidas da tabela {table_name}: {e}")

    # Busca nas duas tabelas
    fetch_from_table('SP8010', 'P8_DATA', 'P8_HORA', 'P8_MAT', 'P8_FILIAL')
    fetch_from_table('SPG010', 'PG_DATA', 'PG_HORA', 'PG_MAT', 'PG_FILIAL')

    # Remove duplicatas e ordena
    unique_punches = sorted(list(set(all_punches)))
    logger.info(f"Encontradas {len(unique_punches)} batidas brutas para {employee_id}.")
    return unique_punches

    