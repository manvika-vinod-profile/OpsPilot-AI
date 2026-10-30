import os
os.environ['DATABASE_URL'] = 'sqlite://'
from fastapi.testclient import TestClient
from app.main import app


def test_health():
    with TestClient(app) as client:
        assert client.get('/health').json()['status'] == 'ok'


def test_incident_lifecycle():
    with TestClient(app) as client:
        r = client.post('/api/logs', json={'service_name': 'test-db', 'level': 'ERROR', 'message': 'Database connection failed'})
        assert r.status_code == 201
        incidents = client.get('/api/incidents').json()
        created = next(x for x in incidents if x['service_name'] == 'test-db')
        assert created['status'] == 'open'
        assert 'database' in created['summary'].lower()
        updated = client.patch(f"/api/incidents/{created['id']}", json={'status': 'resolved'})
        assert updated.status_code == 200
        assert updated.json()['status'] == 'resolved'
        assert next(s for s in client.get('/api/services').json() if s['name'] == 'test-db')['status'] == 'healthy'


def test_reject_bad_log_level():
    with TestClient(app) as client:
        r = client.post('/api/logs', json={'service_name': 'test', 'level': 'SILLY', 'message': 'nope'})
        assert r.status_code == 422
