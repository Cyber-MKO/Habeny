"""
Attack, custom-log and syslog simulation endpoints.
"""
import json
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.encoders import jsonable_encoder

from app.models import (
    APIResponse,
    CustomLogSimulationRequest,
    SimulationStartRequest,
    SyslogSimulationRequest,
    utc_now,
)
from app.services.activity import log_activity
from app.services.simulation import (
    list_simulation_profiles,
    run_custom_log_simulation,
    run_simulation,
    run_syslog_simulation,
    select_agents_for_simulation,
)
from app.state import simulations_db

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/simulations", response_model=APIResponse)
async def list_simulations():
    """List all simulations (running and completed)"""
    try:
        return APIResponse(
            success=True,
            message="Simulations retrieved",
            data={
                "simulations": list(simulations_db.values()),
                "total": len(simulations_db),
                "running": len([s for s in simulations_db.values() if s["status"] == "running"]),
                "available_profiles": list_simulation_profiles()
            }
        )
    except Exception as e:
        return APIResponse(success=False, message="Failed to list simulations", error=str(e))


@router.post("/simulations/load", response_model=APIResponse)
async def load_simulation(
    request: CustomLogSimulationRequest,
    background_tasks: BackgroundTasks
):
    """Load custom EPS simulations using JSON log templates."""
    try:
        simulation_id = str(uuid.uuid4())

        target_agents = select_agents_for_simulation(request.agent_selector)
        if not target_agents:
            raise HTTPException(status_code=400, detail="No containers match the selector")

        try:
            json.dumps(jsonable_encoder(request.extra_fields or {}))
        except TypeError:
            raise HTTPException(status_code=400, detail="Extra fields must be JSON serializable")

        config_payload = jsonable_encoder(request.dict())
        config_payload.pop("agent_selector", None)

        simulation = {
            "simulation_id": simulation_id,
            "profile_id": "custom_eps",
            "status": "running",
            "target_agents": target_agents,
            "duration": request.duration,
            "eps_target": request.eps,
            "started_at": utc_now().isoformat(),
            "events_generated": 0,
            "custom_parameters": config_payload,
            "simulation_type": "custom_logs"
        }

        simulations_db[simulation_id] = simulation

        background_tasks.add_task(
            run_custom_log_simulation,
            simulation_id,
            target_agents,
            request
        )

        log_activity("custom_log_simulation_started", {
            "simulation_id": simulation_id,
            "containers": len(target_agents),
            "eps": request.eps,
            "duration": request.duration
        })

        return APIResponse(
            success=True,
            message=f"Custom log simulation {simulation_id} started",
            data=simulation
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start custom log simulation: {e}")
        return APIResponse(success=False, message="Failed to start custom log simulation", error=str(e))


@router.post("/simulations/syslog/start", response_model=APIResponse)
async def start_syslog_simulation(request: SyslogSimulationRequest, background_tasks: BackgroundTasks):
    """Start a syslog simulation to a target IP/port."""
    try:
        simulation_id = str(uuid.uuid4())
        protocol = request.protocol.value if hasattr(request.protocol, "value") else request.protocol
        device_type = request.device_type.value if hasattr(request.device_type, "value") else request.device_type

        device_names = [
            f"{request.device_name_prefix}-{idx + 1:02d}"
            for idx in range(request.device_count)
        ]

        simulation = {
            "simulation_id": simulation_id,
            "profile_id": "syslog_simulation",
            "status": "running",
            "target_agents": device_names,
            "duration": request.duration,
            "eps_target": request.eps,
            "started_at": utc_now().isoformat(),
            "events_generated": 0,
            "simulation_type": "syslog",
            "custom_parameters": {
                "target_ip": request.target_ip,
                "target_port": request.target_port,
                "protocol": protocol,
                "device_count": request.device_count,
                "device_type": device_type,
                "device_name_prefix": request.device_name_prefix,
                "facility": request.facility
            }
        }

        simulations_db[simulation_id] = simulation
        background_tasks.add_task(run_syslog_simulation, simulation_id, request)

        log_activity("syslog_simulation_started", {
            "simulation_id": simulation_id,
            "target_ip": request.target_ip,
            "target_port": request.target_port,
            "protocol": protocol,
            "eps": request.eps,
            "duration": request.duration
        })

        return APIResponse(
            success=True,
            message=f"Syslog simulation {simulation_id} started",
            data=simulation
        )
    except Exception as e:
        logger.error(f"Failed to start syslog simulation: {e}")
        return APIResponse(success=False, message="Failed to start syslog simulation", error=str(e))


@router.post("/simulations/start", response_model=APIResponse)
async def start_simulation(
    simulation_request: SimulationStartRequest,
    background_tasks: BackgroundTasks
):
    """Start an attack simulation on selected containers"""
    try:
        simulation_id = str(uuid.uuid4())

        # Validate profile
        if simulation_request.profile_id not in list_simulation_profiles():
            raise HTTPException(status_code=400, detail=f"Invalid profile: {simulation_request.profile_id}")

        # Select target containers
        target_agents = select_agents_for_simulation(simulation_request.agent_selector)

        if not target_agents:
            raise HTTPException(status_code=400, detail="No containers match the selector")

        simulation = {
            "simulation_id": simulation_id,
            "profile_id": simulation_request.profile_id,
            "status": "running",
            "target_agents": target_agents,
            "duration": simulation_request.duration,
            "eps_target": simulation_request.eps_target,
            "started_at": utc_now().isoformat(),
            "events_generated": 0
        }

        simulations_db[simulation_id] = simulation

        # Start simulation in background
        background_tasks.add_task(
            run_simulation,
            simulation_id,
            simulation_request.profile_id,
            target_agents,
            simulation_request.duration,
            simulation_request.eps_target
        )

        log_activity("simulation_started", {
            "simulation_id": simulation_id,
            "profile": simulation_request.profile_id,
            "containers": len(target_agents)
        })

        return APIResponse(
            success=True,
            message=f"Simulation {simulation_id} started",
            data=simulation
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start simulation: {e}")
        return APIResponse(success=False, message="Failed to start simulation", error=str(e))


@router.post("/simulations/{simulation_id}/stop", response_model=APIResponse)
async def stop_simulation(simulation_id: str):
    """Stop a running simulation"""
    try:
        if simulation_id not in simulations_db:
            raise HTTPException(status_code=404, detail=f"Simulation {simulation_id} not found")

        simulation = simulations_db[simulation_id]

        if simulation["status"] != "running":
            return APIResponse(
                success=False,
                message=f"Simulation is not running (status: {simulation['status']})"
            )

        simulation["status"] = "stopped"
        simulation["stopped_at"] = utc_now().isoformat()

        log_activity("simulation_stopped", {"simulation_id": simulation_id})

        return APIResponse(
            success=True,
            message=f"Simulation {simulation_id} stopped",
            data=simulation
        )

    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to stop simulation", error=str(e))
