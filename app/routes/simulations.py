"""
Simulation endpoints: start, stop, list, custom log load, syslog.

Will receive from main.py (Phase 4):
  - GET  /simulations
  - POST /simulations/start
  - POST /simulations/load
  - POST /simulations/syslog/start
  - POST /simulations/{simulation_id}/stop
"""
from fastapi import APIRouter

router = APIRouter(prefix="/simulations", tags=["simulations"])

# Phase 4: move simulation endpoints here
