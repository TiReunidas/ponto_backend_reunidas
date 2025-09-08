from sqlalchemy import Column, Integer, String, Boolean, BigInteger
from database import Base

class Punch(Base):
    __tablename__ = "punches"
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(String, index=True)
    timestamp = Column(BigInteger)
    type = Column(String)
    photo_path = Column(String)
    verified = Column(Boolean)

class Employee(Base):
    __tablename__ = "employees"
    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(String, unique=True, index=True)
    name = Column(String)
    

