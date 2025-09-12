from sqlalchemy import Column, Integer, String, Date, Time, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class AppUser(Base):
    __tablename__ = 'app_users'
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)

class ExternalPunch(Base):
    __tablename__ = 'external_punches'
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(String, index=True)
    work_date = Column(Date)
    entry1 = Column(Time, nullable=True)
    exit1 = Column(Time, nullable=True)
    entry2 = Column(Time, nullable=True)
    exit2 = Column(Time, nullable=True)
    status = Column(String, default='pending')
    __table_args__ = (UniqueConstraint('employee_id', 'work_date', name='_employee_punch_date_uc'),)

class ManualOverride(Base):
    __tablename__ = 'manual_overrides'
    
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(String, index=True, nullable=False)
    work_date = Column(Date, index=True, nullable=False)
    override_type = Column(String, nullable=False) # Ex: 'FOLGA', 'FERIAS', 'ATESTADO'
    description = Column(String, nullable=True)
    
    __table_args__ = (UniqueConstraint('employee_id', 'work_date', name='_employee_override_date_uc'),)

class EscalaDiaria(Base):
    __tablename__ = 'escalas_diarias'
    
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(String, index=True, nullable=False)
    work_date = Column(Date, index=True, nullable=False)
    
    # 'TRABALHO' ou 'FOLGA'
    day_type = Column(String, nullable=False) 
    
    # O turno específico para aquele dia (pode ser nulo se for folga)
    shift_code = Column(String, nullable=True) 
    
    __table_args__ = (UniqueConstraint('employee_id', 'work_date', name='_employee_schedule_date_uc'),)