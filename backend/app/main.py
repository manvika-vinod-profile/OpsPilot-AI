import os
import random
from datetime import datetime, timezone, timedelta
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Text, select, func
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.pool import StaticPool

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./opspilot.db')
engine_kwargs = {'connect_args': {'check_same_thread': False}} if DATABASE_URL.startswith('sqlite') else {}
if DATABASE_URL == 'sqlite://':
    engine_kwargs['poolclass'] = StaticPool
engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
Base = declarative_base()


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Service(Base):
    __tablename__ = 'services'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)
    status = Column(String(20), default='healthy', nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class EventLog(Base):
    __tablename__ = 'logs'
    id = Column(Integer, primary_key=True)
    service_id = Column(Integer, ForeignKey('services.id'), nullable=False)
    level = Column(String(10), nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class Incident(Base):
    __tablename__ = 'incidents'
    id = Column(Integer, primary_key=True)
    service_id = Column(Integer, ForeignKey('services.id'), nullable=False)
    title = Column(String(255), nullable=False)
    severity = Column(String(20), nullable=False)
    status = Column(String(20), default='open', nullable=False)
    summary = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    resolved_at = Column(DateTime, nullable=True)


class LogIn(BaseModel):
    service_name: str = Field(min_length=1, max_length=100)
    level: str
    message: str = Field(min_length=1, max_length=2000)


class IncidentUpdate(BaseModel):
    status: str


class ServiceIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


def get_db():
    with SessionLocal() as db:
        yield db


def as_iso(value):
    return value.isoformat(timespec='seconds') + 'Z' if value else None


def serialize_service(s):
    return {'id': s.id, 'name': s.name, 'status': s.status}


def serialize_log(log, service_name):
    return {'id': log.id, 'service_id': log.service_id, 'service_name': service_name,
            'level': log.level, 'message': log.message, 'created_at': as_iso(log.created_at)}


def serialize_incident(incident, service_name):
    return {'id': incident.id, 'service_id': incident.service_id, 'service_name': service_name,
            'title': incident.title, 'severity': incident.severity, 'status': incident.status,
            'summary': incident.summary, 'created_at': as_iso(incident.created_at),
            'resolved_at': as_iso(incident.resolved_at)}


def explanation(level, message):
    # Explainable rule-based starter, NOT an LLM diagnosis.
    m = message.lower()
    if 'timeout' in m or 'latency' in m:
        return 'Possible upstream dependency timeout or network saturation. Check latency percentiles, retry rates, and dependency health.'
    if 'database' in m or 'connection' in m or 'pool' in m:
        return 'Possible database connectivity or connection-pool issue. Check pool utilization, query latency, and database availability.'
    if 'memory' in m or 'oom' in m:
        return 'Possible memory pressure. Inspect memory consumption, container limits, and recent deployments.'
    if '500' in m or 'exception' in m:
        return 'Application error detected. Review the stack trace, error frequency, recent changes, and dependent services.'
    return f'{level.title()} log detected. Correlate nearby logs, recent deployments, service metrics, and upstream dependencies.'


def ingest(db: Session, payload: LogIn):
    level = payload.level.upper()
    if level not in ('DEBUG', 'INFO', 'WARN', 'ERROR', 'CRITICAL'):
        raise HTTPException(422, 'level must be DEBUG, INFO, WARN, ERROR, or CRITICAL')
    name = payload.service_name.strip()
    if not name:
        raise HTTPException(422, 'service name must not be blank')
    service = db.scalar(select(Service).where(Service.name == name))
    if not service:
        service = Service(name=name)
        db.add(service)
        db.flush()
    log = EventLog(service_id=service.id, level=level, message=payload.message)
    db.add(log)
    if level in ('ERROR', 'CRITICAL'):
        sev = 'critical' if level == 'CRITICAL' else 'high'
        # One open incident per service: a deliberate simplification for starter use.
        existing = db.scalar(select(Incident).where(Incident.service_id == service.id, Incident.status == 'open').order_by(Incident.id.desc()))
        if existing:
            existing.summary = explanation(level, payload.message)
            if level == 'CRITICAL':
                existing.severity = 'critical'
        else:
            db.add(Incident(service_id=service.id, title=payload.message[:100], severity=sev,
                            summary=explanation(level, payload.message)))
        service.status = 'degraded'
    db.commit()
    db.refresh(log)
    return serialize_log(log, service.name)


def seed(db):
    if db.scalar(select(func.count(Service.id))) != 0:
        return
    for name in ('api-gateway', 'payment-service', 'auth-service', 'notifications'):
        db.add(Service(name=name))
    db.commit()
    for name, level, message in (
        ('api-gateway', 'INFO', 'Request completed in 84ms'),
        ('auth-service', 'INFO', 'JWT signature validated'),
        ('notifications', 'INFO', 'Email queued successfully'),
        ('payment-service', 'ERROR', 'Database connection pool exhausted'),
        ('api-gateway', 'WARN', 'Request latency exceeded 400ms'),
    ):
        ingest(db, LogIn(service_name=name, level=level, message=message))


@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
    yield


app = FastAPI(title='OpsPilot AI API', version='0.1.0', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173', 'http://127.0.0.1:5173'],
                   allow_credentials=False, allow_methods=['GET', 'POST', 'PATCH'], allow_headers=['Content-Type'])


@app.get('/health')
def health():
    return {'status': 'ok', 'timestamp': as_iso(utcnow())}


@app.get('/api/services')
def list_services(db: Session = Depends(get_db)):
    return [serialize_service(s) for s in db.scalars(select(Service).order_by(Service.name)).all()]


@app.post('/api/services', status_code=201)
def create_service(payload: ServiceIn, db: Session = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(422, 'Service name cannot be blank')
    existing = db.scalar(select(Service).where(Service.name == name))
    if existing:
        raise HTTPException(409, 'Service already exists')
    s = Service(name=name)
    db.add(s); db.commit(); db.refresh(s)
    return serialize_service(s)


@app.get('/api/logs')
def list_logs(limit: int = 50, service: Optional[str] = None, db: Session = Depends(get_db)):
    limit = min(max(limit, 1), 200)
    q = select(EventLog, Service.name).join(Service).order_by(EventLog.id.desc()).limit(limit)
    if service:
        q = q.where(Service.name == service)
    return [serialize_log(log, name) for log, name in db.execute(q).all()]


@app.post('/api/logs', status_code=201)
def create_log(payload: LogIn, db: Session = Depends(get_db)):
    return ingest(db, payload)


@app.get('/api/incidents')
def list_incidents(db: Session = Depends(get_db)):
    q = select(Incident, Service.name).join(Service).order_by(Incident.id.desc())
    return [serialize_incident(inc, name) for inc, name in db.execute(q).all()]


@app.patch('/api/incidents/{incident_id}')
def patch_incident(incident_id: int, payload: IncidentUpdate, db: Session = Depends(get_db)):
    if payload.status not in ('open', 'resolved'):
        raise HTTPException(422, 'status must be open or resolved')
    inc = db.get(Incident, incident_id)
    if inc is None:
        raise HTTPException(404, 'Incident not found')
    inc.status = payload.status
    inc.resolved_at = utcnow() if payload.status == 'resolved' else None
    service = db.get(Service, inc.service_id)
    if payload.status == 'resolved':
        outstanding = db.scalar(select(func.count(Incident.id)).where(
            Incident.service_id == inc.service_id, Incident.status == 'open'))
        # Flush first so the just-resolved incident is excluded.
        db.flush()
        outstanding = db.scalar(select(func.count(Incident.id)).where(
            Incident.service_id == inc.service_id, Incident.status == 'open'))
        if outstanding == 0:
            service.status = 'healthy'
    else:
        service.status = 'degraded'
    db.commit(); db.refresh(inc)
    return serialize_incident(inc, service.name)


@app.get('/api/summary')
def summary(db: Session = Depends(get_db)):
    total_services = db.scalar(select(func.count(Service.id))) or 0
    degraded = db.scalar(select(func.count(Service.id)).where(Service.status == 'degraded')) or 0
    open_incidents = db.scalar(select(func.count(Incident.id)).where(Incident.status == 'open')) or 0
    logs_last_hour = db.scalar(select(func.count(EventLog.id)).where(EventLog.created_at >= utcnow() - timedelta(hours=1))) or 0
    return {'services': total_services, 'healthy_services': total_services - degraded,
            'degraded_services': degraded, 'open_incidents': open_incidents, 'logs_last_hour': logs_last_hour}


SIMULATED = [
    ('api-gateway','INFO','Request completed in 81ms'),
    ('payment-service','ERROR','Database connection pool exhausted'),
    ('auth-service','INFO','Token validated successfully'),
    ('notifications','WARN','Email delivery latency elevated'),
    ('api-gateway','CRITICAL','Upstream timeout after 5000ms'),
    ('payment-service','INFO','Payment intent accepted'),
    ('auth-service','ERROR','Unexpected authentication exception'),
]


@app.post('/api/simulate')
def simulate(db: Session = Depends(get_db)):
    name, level, message = random.choice(SIMULATED)
    return ingest(db, LogIn(service_name=name, level=level, message=message))
