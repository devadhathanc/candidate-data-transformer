from fastapi.testclient import TestClient
from app import app, _get_default_config

client = TestClient(app)

def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    assert "Candidate Data Transformer" in response.text

def test_default_config_endpoint():
    response = client.get("/api/config/default")
    assert response.status_code == 200
    data = response.json()
    assert "fields" in data

def test_process_samples_endpoint():
    response = client.get("/api/process-samples")
    assert response.status_code == 200
    data = response.json()
    assert "summary" in data
    assert data["summary"]["raw_records"] > 0
    assert data["summary"]["canonical_profiles"] > 0
    assert data["summary"]["projected_profiles"] > 0

def test_reproject_endpoint():
    sample_res = client.get("/api/process-samples").json()
    canonical = sample_res["canonical_profiles"]
    config = _get_default_config()

    response = client.post(
        "/api/project",
        json={"canonical_profiles": canonical, "config": config}
    )
    assert response.status_code == 200
    data = response.json()
    assert "projected_profiles" in data
    assert len(data["projected_profiles"]) == len(canonical)
