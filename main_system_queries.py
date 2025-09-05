import logging
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, date
from typing import Dict
from collections import defaultdict

logger = logging.getLogger(__name__)

def get_overtime_from_main_system(db: Session, employee_id: str, year: int, month: int) -> Dict[date, float]:
    """
    Conecta-se ao banco de dados do sistema principal (SQL Server) e retorna um
    dicionário mapeando cada dia do mês ao seu total de horas extras.
    """
    logger.info(f"Buscando horas do sistema principal para Matrícula: {employee_id}, Mês/Ano: {month}/{year}")

    filial = employee_id[:4]
    matricula = employee_id[4:]

    # Consulta SQL que busca as horas extras PARA CADA DIA
    sql_query = text("""
        WITH BatidasDiarias AS (
            SELECT
                P8_DATA,
                MAX(CASE WHEN P8_TPMARCA = '1E' THEN FLOOR(P8_HORA) * 60 + (P8_HORA - FLOOR(P8_HORA)) * 100 ELSE NULL END) AS min_1e,
                MAX(CASE WHEN P8_TPMARCA = '1S' THEN FLOOR(P8_HORA) * 60 + (P8_HORA - FLOOR(P8_HORA)) * 100 ELSE NULL END) AS min_1s,
                MAX(CASE WHEN P8_TPMARCA = '2E' THEN FLOOR(P8_HORA) * 60 + (P8_HORA - FLOOR(P8_HORA)) * 100 ELSE NULL END) AS min_2e,
                MAX(CASE WHEN P8_TPMARCA = '2S' THEN FLOOR(P8_HORA) * 60 + (P8_HORA - FLOOR(P8_HORA)) * 100 ELSE NULL END) AS min_2s
            FROM
                SP8010
            WHERE
                P8_FILIAL = :filial
                AND P8_MAT = :matricula
                AND SUBSTRING(P8_DATA, 1, 4) = :p_year
                AND SUBSTRING(P8_DATA, 5, 2) = :p_month
                AND P8_APONTA = 'S' -- Garante que a batida é válida para apontamento
                AND (D_E_L_E_T_ IS NULL OR D_E_L_E_T_ <> '*') -- Garante que o registro não foi deletado
            GROUP BY
                P8_DATA
        ),
        JornadaCalculada AS (
            SELECT
                P8_DATA,
                (ISNULL(min_1s, 0) - ISNULL(min_1e, 0)) + (ISNULL(min_2s, 0) - ISNULL(min_2e, 0)) AS total_minutos_jornada
            FROM
                BatidasDiarias
        )
        SELECT 
            P8_DATA as dia,
            -- Retorna as horas extras calculadas para este dia
            CAST(
                CASE 
                    WHEN total_minutos_jornada > 528
                    THEN (total_minutos_jornada - 528) / 60.0
                    ELSE 0 
                END 
            AS DECIMAL(10,2)) AS HorasExtras
        FROM JornadaCalculada
        WHERE total_minutos_jornada > 0;
    """)

    main_system_overtime_per_day: Dict[date, float] = defaultdict(float)
    try:
        results = db.execute(
            sql_query,
            {"filial": filial, "matricula": matricula, "p_year": str(year), "p_month": str(month).zfill(2)}
        ).fetchall()

        # Constrói o dicionário que o main.py espera
        for row in results:
            dia_str, horas_extras = row
            if horas_extras and float(horas_extras) > 0:
                dia_date = datetime.strptime(dia_str, '%Y%m%d').date()
                main_system_overtime_per_day[dia_date] = float(horas_extras)
            
        return main_system_overtime_per_day
        
    except Exception as e:
        logger.error(f"Erro ao consultar o banco de dados principal: {e}")
        raise e

