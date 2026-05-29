"""
Smoke tests for system endpoints.

These will work once Phase 4 is complete and create_app() returns a
fully wired application.  For now they serve as a target spec.
"""
# Phase 6: uncomment when routes are migrated
#
# from fastapi.testclient import TestClient
# from app import create_app
#
#
# def test_root_returns_200():
#     client = TestClient(create_app())
#     resp = client.get("/")
#     assert resp.status_code == 200
#     assert resp.json()["success"] is True
#
#
# def test_health_returns_200():
#     client = TestClient(create_app())
#     resp = client.get("/system/health")
#     assert resp.status_code == 200
