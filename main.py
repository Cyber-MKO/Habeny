from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.encoders import jsonable_encoder
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
import lxc
import os
import time
import uuid
import json
import asyncio
import socket
import random
import subprocess
import pty
import fcntl
import termios
import struct
import csv
from io import BytesIO

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count
from pathlib import Path

from models import *
from utils import *
from db import (
    init_db,
    get_or_create_agent_seq_id,
    get_agent_by_name,
    upsert_agent,
    mark_agent_deleted,
    create_group,
    list_groups,
    group_exists,
    get_agents_in_group,
    assign_agents_to_group,
    remove_agents_from_group,
    rename_group,
    delete_group,
    create_manager,
    list_managers,
    get_manager,
    get_manager_by_name,
    update_manager,
    delete_manager,
    create_syslog_config,
    list_syslog_configs,
    get_syslog_config,
    update_syslog_config,
    delete_syslog_config,
    record_metric,
    record_metrics_batch,
    query_metrics,
    get_metric_summary,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Multi-SIEM Container Emulation Platform",
    description="LXC-based platform for deploying containers that run SIEM agents at scale",
    version="2.0.0"
)

MAX_WORKERS = cpu_count() * 2

logger.info(f"Initialized with {MAX_WORKERS} max thread workers and {cpu_count()} CPU cores")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API latency tracking middleware
@app.middleware("http")
async def track_request_latency(request, call_next):
    start = time.time()
    response = await call_next(request)
    latency_ms = (time.time() - start) * 1000
    path = request.url.path
    # Record latency for API endpoints (skip static files)
    if not path.startswith("/assets") and path != "/favicon.ico":
        try:
            record_metric(DB_PATH, "api_latency", path, latency_ms, request.method)
        except Exception:
            pass
    response.headers["X-Response-Time-Ms"] = f"{latency_ms:.1f}"
    return response

# In-memory storage
simulations_db = {}
reports_db = {}
report_files = {}
activity_logs = []
config_templates = {}
scheduled_log_tasks = {}

# Data directories
DATA_DIR = Path("/var/lib/lxc-siem-platform")
CONFIGS_DIR = DATA_DIR / "configs"
REPORTS_DIR = DATA_DIR / "reports"
LOGS_DIR = DATA_DIR / "logs"
AGENTS_DIR = DATA_DIR / "agents"
DB_PATH = DATA_DIR / "platform.db"

# Ensure directories exist
for dir_path in [DATA_DIR, CONFIGS_DIR, REPORTS_DIR, LOGS_DIR, AGENTS_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)

# Initialize database
init_db(DB_PATH)

# Clean up benchmarks left in "running" state from a previous crash/restart
try:
    from benchmarks import cleanup_stale_benchmarks
    cleaned = cleanup_stale_benchmarks()
    if cleaned:
        logger.info(f"Recovered {cleaned} stale benchmark(s) from previous session")
except Exception as e:
    logger.warning(f"Benchmark cleanup failed: {e}")

# Dependency for checking root privileges
def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def check_root():
    if os.geteuid() != 0:
        raise HTTPException(
            status_code=403,
            detail="This operation requires root privileges. Run with sudo."
        )
    return True


def get_lxc_version() -> str:
    """Return LXC version, guarding for API differences."""
    version_attr = getattr(lxc, "version", None)
    if callable(version_attr):
        return version_attr()
    if version_attr is None:
        return "unknown"
    return str(version_attr)


def get_lxc_default_config_path() -> str:
    """Return LXC default config path if available."""
    path_attr = getattr(lxc, "default_config_path", None)
    if callable(path_attr):
        return path_attr()
    if path_attr is None:
        return "unknown"
    return str(path_attr)


def resize_pty(fd: int, cols: int, rows: int) -> None:
    """Resize a pseudo-terminal for interactive console sessions."""
    if cols <= 0 or rows <= 0:
        return
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _detach_and_claim_tty() -> None:
    """Run in the child before exec: start a new session and make the
    inherited pty slave (stdin) its controlling terminal, instead of
    inheriting the API server's own controlling terminal."""
    os.setsid()
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


def read_agent_metadata(agent_name: str) -> Dict[str, Any]:
    """Load persisted container metadata from the database if available."""
    data = get_agent_by_name(DB_PATH, agent_name)
    if not data:
        return {}
    if "seq_id" in data and "agent_seq_id" not in data:
        data["agent_seq_id"] = data.get("seq_id")
    return data


def write_agent_metadata(agent_name: str, metadata: Dict[str, Any]) -> None:
    """Persist container metadata to the database for later lookup."""
    payload = {**read_agent_metadata(agent_name), **metadata}
    if "agent_seq_id" in payload and "seq_id" not in payload:
        payload["seq_id"] = payload.get("agent_seq_id")
    if "seq_id" not in payload or payload.get("seq_id") is None:
        payload["seq_id"] = get_or_create_agent_seq_id(DB_PATH, agent_name)
    payload["agent_seq_id"] = payload.get("seq_id")

    allowed_keys = {
        "seq_id",
        "siem_type",
        "siem_ip",
        "siem_version",
        "agent_group",
        "os_type",
        "config_template_id",
        "lifecycle_status",
        "state",
        "init_pid",
        "ip_addresses",
        "siem_agent_status",
        "siem_agent_running",
        "siem_agent_last_check",
        "manager_host",
        "manager_port",
        "manager_status",
        "manager_reachable",
        "created_at",
        "updated_at",
        "deleted_at"
    }
    db_payload = {key: payload.get(key) for key in allowed_keys if key in payload}
    upsert_agent(DB_PATH, agent_name, db_payload)


def delete_agent_metadata(agent_name: str) -> None:
    """Mark persisted metadata for a container as deleted."""
    try:
        mark_agent_deleted(DB_PATH, agent_name)
    except Exception as e:
        logger.warning(f"Failed to mark metadata deleted for {agent_name}: {e}")


# Migrate legacy container metadata JSON files into the database
for legacy_file in AGENTS_DIR.glob("*.json"):
    try:
        with open(legacy_file, "r") as f:
            legacy_data = json.load(f)
        agent_name = legacy_data.get("agent_name") or legacy_data.get("agent_id") or legacy_file.stem
        write_agent_metadata(agent_name, legacy_data)
    except Exception as e:
        logger.warning(f"Failed to migrate {legacy_file}: {e}")


def normalize_dt(value: datetime) -> datetime:
    """Normalize datetimes to timezone-aware UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def generate_report_csv(report_data: Dict[str, Any], report_file: Path) -> None:
    """Generate a CSV report file."""
    rows = [["section", "key", "value"]]
    rows.append(["report", "report_id", report_data.get("report_id")])
    rows.append(["report", "generated_at", report_data.get("generated_at")])
    time_range = report_data.get("time_range", {})
    rows.append(["report", "start_time", time_range.get("start")])
    rows.append(["report", "end_time", time_range.get("end")])

    summary = report_data.get("summary", {})
    for key, value in summary.items():
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                rows.append(["summary", f"{key}.{sub_key}", sub_value])
        else:
            rows.append(["summary", key, value])

    metrics = report_data.get("metrics", {})
    for key, value in metrics.items():
        rows.append(["metrics", key, json.dumps(value)])

    findings = report_data.get("findings", [])
    for idx, finding in enumerate(findings, start=1):
        rows.append(["finding", f"{idx}.severity", finding.get("severity")])
        rows.append(["finding", f"{idx}.title", finding.get("title")])
        rows.append(["finding", f"{idx}.description", finding.get("description")])

    with open(report_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)


def generate_report_pdf(report_data: Dict[str, Any], agent_status_counts: Dict[str, int], report_file: Path) -> None:
    """Generate a PDF report with visualizations."""
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("Habeny Report", styles["Title"]))
    story.append(Paragraph("Multi-SIEM Container Emulation Platform", styles["Heading3"]))
    story.append(Spacer(1, 12))

    summary = report_data.get("summary", {})
    time_range = report_data.get("time_range", {})
    summary_table_data = [
        ["Report ID", report_data.get("report_id")],
        ["Generated At", report_data.get("generated_at")],
        ["Start Time", time_range.get("start")],
        ["End Time", time_range.get("end")],
        ["Total Containers", summary.get("total_agents")],
        ["Total Simulations", summary.get("total_simulations")]
    ]
    table = Table(summary_table_data, colWidths=[150, 350])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5f5")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(table)
    story.append(Spacer(1, 18))

    agents_by_siem = summary.get("agents_by_siem", {})
    if agents_by_siem:
        fig, ax = plt.subplots(figsize=(5, 3))
        labels = list(agents_by_siem.keys())
        values = list(agents_by_siem.values())
        ax.bar(labels, values, color="#2563eb")
        ax.set_title("Containers by SIEM Type")
        ax.set_ylabel("Containers")
        fig.tight_layout()
        img_buf = BytesIO()
        fig.savefig(img_buf, format="png")
        plt.close(fig)
        img_buf.seek(0)
        story.append(Paragraph("Containers by SIEM Type", styles["Heading3"]))
        story.append(Image(img_buf, width=400, height=240))
        story.append(Spacer(1, 12))

    if agent_status_counts:
        fig, ax = plt.subplots(figsize=(5, 3))
        labels = list(agent_status_counts.keys())
        values = list(agent_status_counts.values())
        ax.pie(values, labels=labels, autopct="%1.0f%%", startangle=90)
        ax.axis("equal")
        ax.set_title("Containers by Status")
        fig.tight_layout()
        img_buf = BytesIO()
        fig.savefig(img_buf, format="png")
        plt.close(fig)
        img_buf.seek(0)
        story.append(Paragraph("Containers by Status", styles["Heading3"]))
        story.append(Image(img_buf, width=400, height=240))
        story.append(Spacer(1, 12))

    if summary.get("simulations_in_range"):
        story.append(Paragraph("Simulations in Range", styles["Heading3"]))
        sims_table_data = [["Simulation ID"]] + [[sid] for sid in summary["simulations_in_range"]]
        sims_table = Table(sims_table_data, colWidths=[500])
        sims_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5f5")),
        ]))
        story.append(sims_table)

    if summary.get("simulations_by_type"):
        story.append(Spacer(1, 12))
        story.append(Paragraph("Simulations by Type", styles["Heading3"]))
        type_rows = [["Type", "Count"]]
        for key, value in summary.get("simulations_by_type", {}).items():
            type_rows.append([str(key), str(value)])
        type_table = Table(type_rows, colWidths=[250, 250])
        type_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5f5")),
        ]))
        story.append(type_table)

    if summary.get("syslog_targets"):
        story.append(Spacer(1, 12))
        story.append(Paragraph("Syslog Targets", styles["Heading3"]))
        target_rows = [["Target", "Count"]]
        for key, value in summary.get("syslog_targets", {}).items():
            target_rows.append([str(key), str(value)])
        target_table = Table(target_rows, colWidths=[350, 150])
        target_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5f5")),
        ]))
        story.append(target_table)

    doc = SimpleDocTemplate(str(report_file), pagesize=letter)
    doc.build(story)

def log_activity(action: str, details: Dict[str, Any], status: str = "success"):
    """Log activity to in-memory store and file"""
    activity = {
        "timestamp": utc_now().isoformat(),
        "action": action,
        "status": status,
        "details": details
    }
    activity_logs.append(activity)
    
    # Also log to file
    log_file = LOGS_DIR / f"activity_{utc_now().strftime('%Y%m%d')}.json"
    with open(log_file, 'a') as f:
        f.write(json.dumps(activity) + "\n")
    
    logger.info(f"Activity logged: {action} - {status}")


def read_activity_logs_from_files(action: Optional[str] = None) -> List[Dict[str, Any]]:
    """Read activity logs from JSONL files."""
    logs = []
    for log_file in sorted(LOGS_DIR.glob("activity_*.json"), reverse=True):
        try:
            with open(log_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if action and entry.get("action") != action:
                        continue
                    logs.append(entry)
        except Exception:
            continue
    logs.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return logs

# ===== ROOT & SYSTEM INFO =====

@app.get("/", response_model=APIResponse)
async def root():
    """Root endpoint with comprehensive API information"""
    return APIResponse(
        success=True,
        message="Multi-SIEM Container Emulation Platform API",
        data={
            "version": "2.0.0",
            "description": "LXC-based platform for deploying containers that run SIEM agents at scale",
            "supported_siem_types": ["wazuh", "ossec", "ossim", "utmstack", "elastic"],
            "default_os": "ubuntu_22_04",
            "max_workers": MAX_WORKERS,
            "cpu_count": cpu_count(),
            "endpoint_groups": {
                "system": ["/system/info", "/system/health"],
                "containers": ["/agents", "/agents/deploy", "/agents/{id}", "/agents/stats"],
                "simulations": ["/simulations", "/simulations/start", "/simulations/load", "/simulations/syslog/start", "/simulations/stop"],
                "configs": ["/configs", "/configs/import", "/configs/export/{id}"],
                "reports": ["/reports", "/reports/generate", "/reports/{id}"],
                "activity": ["/activity/logs"],
                "siem": ["/siem/{siem_type}/stats"],
                "groups": ["/groups", "/groups/{group_name}/assign", "/groups/{group_name}/remove"]
            }
        }
    )

@app.get("/system/info", response_model=APIResponse)
async def system_info():
    """Get comprehensive system and LXC information"""
    try:
        info = {
            "platform": {
                "name": "Multi-SIEM Container Emulation Platform",
                "version": "2.0.0",
                "lxc_version": get_lxc_version(),
                "default_config_path": get_lxc_default_config_path(),
            },
            "system": {
                "arch": get_system_arch(),
                "is_root": os.geteuid() == 0,
                "cpu_count": cpu_count(),
                "worker_config": {
                    "thread_workers": MAX_WORKERS,
                    "process_workers": cpu_count()
                }
            },
            "containers": {
                "total": len(lxc.list_containers()),
                "by_state": get_containers_by_state()
            },
            "supported_features": {
                "siem_types": ["wazuh", "ossec", "ossim", "utmstack", "elastic"],
                "os_types": ["ubuntu_22_04", "ubuntu_20_04", "debian_11"],
                "simulation_profiles": list_simulation_profiles(),
                "parallel_modes": ["multiprocessing", "threading", "sequential"]
            },
            "templates": run_command(["ls", "/usr/share/lxc/templates"])["stdout"].split()
        }
        return APIResponse(success=True, message="System info retrieved", data=info)
    except Exception as e:
        logger.error(f"Failed to get system info: {e}")
        return APIResponse(success=False, message="Failed to get system info", error=str(e))

@app.get("/system/health", response_model=HealthCheckResponse)
async def health_check():
    """Comprehensive health check endpoint"""
    try:
        containers = lxc.list_containers()
        running_containers = sum(1 for name in containers if lxc.Container(name).running)
        
        # Calculate uptime (simplified - use actual process start time in production)
        uptime = time.time()  # Placeholder
        
        return HealthCheckResponse(
            status="healthy",
            version="2.0.0",
            uptime_seconds=uptime,
            containers_count=len(containers),
            system_info={
                "cpu_count": cpu_count(),
                "running_containers": running_containers,
                "active_simulations": len([s for s in simulations_db.values() if s.get("status") == "running"])
            }
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail=f"Service unhealthy: {str(e)}")

def get_containers_by_state() -> Dict[str, int]:
    """Get container counts by state"""
    state_counts = {"RUNNING": 0, "STOPPED": 0, "FROZEN": 0, "OTHER": 0}
    for name in lxc.list_containers():
        container = lxc.Container(name)
        state = container.state
        if state in state_counts:
            state_counts[state] += 1
        else:
            state_counts["OTHER"] += 1
    return state_counts

# ===== LIVE METRICS WEBSOCKET =====

@app.websocket("/ws/metrics")
async def metrics_stream(websocket: WebSocket):
    """Push live platform metrics to connected React dashboards."""
    await websocket.accept()
    try:
        while True:
            try:
                containers = lxc.list_containers()
                running = sum(1 for n in containers if lxc.Container(n).running)
                by_status = {"running": running, "stopped": len(containers) - running}

                by_siem = {}
                for name in containers:
                    meta = read_agent_metadata(name)
                    stype = meta.get("siem_type") or "unknown"
                    by_siem[stype] = by_siem.get(stype, 0) + 1

                active_sims = len([s for s in simulations_db.values() if s.get("status") == "running"])
                total_events = sum(s.get("events_generated", 0) for s in simulations_db.values())
                running_sims_eps = sum(s.get("eps_target", 0) for s in simulations_db.values() if s.get("status") == "running")

                # System resources
                sys_res = get_system_resources()

                # Recent API latency (last 60s)
                try:
                    since = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
                    latency_summary = get_metric_summary(DB_PATH, "api_latency", "/agents/deploy", since)
                except Exception:
                    latency_summary = {}

                payload = {
                    "total_agents": len(containers),
                    "by_status": by_status,
                    "by_siem_type": by_siem,
                    "active_simulations": active_sims,
                    "total_events_generated": total_events,
                    "current_eps_target": running_sims_eps,
                    "system": {
                        "cpu_count": sys_res.get("cpu_count"),
                        "memory_used_percent": round(sys_res.get("memory_used_percent", 0), 1),
                        "memory_available_mb": sys_res.get("memory_available_mb"),
                        "disk_used_percent": round(sys_res.get("disk_used_percent", 0), 1),
                        "load_average": sys_res.get("load_average", []),
                    },
                    "deploy_latency": latency_summary,
                    "timestamp": utc_now().isoformat(),
                }

                # Persist system metrics snapshot for historical trending
                try:
                    record_metrics_batch(DB_PATH, [
                        ("system", "memory_used_percent", sys_res.get("memory_used_percent", 0), None),
                        ("system", "cpu_load_1m", sys_res.get("load_average", [0])[0] if sys_res.get("load_average") else 0, None),
                        ("system", "disk_used_percent", sys_res.get("disk_used_percent", 0), None),
                        ("system", "containers_running", running, None),
                    ])
                except Exception:
                    pass

                await websocket.send_json(payload)
            except Exception as e:
                logger.debug(f"Metrics collection error: {e}")

            await asyncio.sleep(5)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass

# ===== CONSOLE ACCESS =====

@app.websocket("/ws/console/{container_name}")
async def console_session(websocket: WebSocket, container_name: str):
    """WebSocket console session into a running container."""
    await websocket.accept()

    if os.geteuid() != 0:
        await websocket.send_text("WARNING: API is not running as root. Console access may fail.\n")

    if not validate_container_name(container_name):
        await websocket.send_text("ERROR: Invalid container name.\n")
        await websocket.close(code=1008)
        return

    if container_name not in lxc.list_containers():
        await websocket.send_text("ERROR: Container not found.\n")
        await websocket.close(code=1008)
        return

    container = lxc.Container(container_name)
    if not container.running:
        await websocket.send_text("ERROR: Container is not running.\n")
        await websocket.close(code=1008)
        return

    master_fd, slave_fd = pty.openpty()
    env = os.environ.copy()
    env["TERM"] = "xterm-256color"

    try:
        process = subprocess.Popen(
            ["lxc-attach", "-n", container_name, "--", "/bin/bash", "-l"],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
            close_fds=True,
            preexec_fn=_detach_and_claim_tty,
        )
        os.close(slave_fd)
    except Exception as e:
        try:
            os.close(slave_fd)
        except Exception:
            pass
        await websocket.send_text(f"ERROR: Failed to start console: {e}\n")
        await websocket.close(code=1011)
        return

    resize_pty(master_fd, 80, 24)

    async def read_pty():
        try:
            while True:
                data = await asyncio.to_thread(os.read, master_fd, 1024)
                if not data:
                    break
                await websocket.send_text(data.decode(errors="ignore"))
        except Exception:
            pass

    async def write_pty():
        try:
            while True:
                message = await websocket.receive_text()
                if not message:
                    continue
                if message.startswith("{"):
                    try:
                        payload = json.loads(message)
                    except json.JSONDecodeError:
                        payload = None
                    if payload and payload.get("type") == "resize":
                        cols = int(payload.get("cols", 0))
                        rows = int(payload.get("rows", 0))
                        resize_pty(master_fd, cols, rows)
                        continue
                os.write(master_fd, message.encode())
        except WebSocketDisconnect:
            pass
        except Exception:
            pass

    reader = asyncio.create_task(read_pty())
    writer = asyncio.create_task(write_pty())
    done, pending = await asyncio.wait({reader, writer}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()

    try:
        process.terminate()
        process.wait(timeout=2)
    except Exception:
        process.kill()

    try:
        os.close(master_fd)
    except Exception:
        pass

# ===== CONTAINER DEPLOYMENT =====

@app.post("/agents/deploy", response_model=APIResponse)
async def deploy_agents(
    deployment: AgentDeploymentRequest,
    background_tasks: BackgroundTasks,
    root: bool = Depends(check_root)
):
    """
    Deploy multiple containers with SIEM agents

    Supports Wazuh, OSSEC, OSSIM, and UTMstack with configurable parameters
    """
    try:
        start_time = time.time()

        # If a manager profile is specified, load it and fill in any fields
        # the request didn't explicitly set
        if deployment.manager_profile_id:
            mgr = get_manager(DB_PATH, deployment.manager_profile_id)
            if not mgr:
                raise HTTPException(status_code=404, detail=f"Manager profile '{deployment.manager_profile_id}' not found")
            profile_fields = ["siem_type", "siem_ip", "siem_version", "siem_auth_key",
                            "os_type", "agent_group", "memory_limit", "cpu_shares", "config_template_id"]
            for field in profile_fields:
                req_val = getattr(deployment, field, None)
                mgr_val = mgr.get(field)
                # Use profile value when the request field is at its default/empty
                if mgr_val and (req_val is None or req_val == "" or
                    (field == "siem_type" and req_val == "wazuh") or
                    (field == "agent_group" and req_val == "default") or
                    (field == "os_type" and req_val == "ubuntu_22_04")):
                    setattr(deployment, field, mgr_val)

        # Validate: siem_ip required unless deploying bare containers
        if deployment.siem_type != "none" and not deployment.siem_ip:
            raise HTTPException(status_code=400, detail="siem_ip is required when deploying a SIEM agent")
        
        if deployment.agent_group:
            if not group_exists(DB_PATH, deployment.agent_group):
                if deployment.auto_create_group:
                    create_group(DB_PATH, deployment.agent_group, "Auto-created during deployment")
                    log_activity("group_auto_created", {"group": deployment.agent_group})
                else:
                    raise HTTPException(status_code=400, detail="Container group not found")

        # Log deployment request
        log_activity(
            "container_deployment_started",
            {
                "count": deployment.count,
                "siem_type": deployment.siem_type,
                "siem_ip": deployment.siem_ip,
                "os_type": deployment.os_type
            }
        )
        
        logger.info(f"Starting deployment of {deployment.count} {deployment.siem_type} containers")

        # Convert to dict for multiprocessing
        deployment_dict = {
            "siem_type": deployment.siem_type,
            "siem_ip": deployment.siem_ip,
            "siem_version": deployment.siem_version,
            "os_type": deployment.os_type,
            "agent_group": deployment.agent_group,
            "agent_base_name": deployment.agent_base_name,
            "memory_limit": deployment.memory_limit,
            "cpu_shares": deployment.cpu_shares,
            "config_template_id": deployment.config_template_id,
            "siem_auth_key": deployment.siem_auth_key
        }
        
        # Create container names
        agent_names = [f"{deployment.agent_base_name}-{i:04d}" for i in range(1, deployment.count + 1)]

        agent_seq_ids = {}
        for name in agent_names:
            seq_id = get_or_create_agent_seq_id(DB_PATH, name)
            agent_seq_ids[name] = seq_id
            write_agent_metadata(
                name,
                {
                    "agent_seq_id": seq_id,
                    "siem_type": deployment.siem_type,
                    "siem_ip": deployment.siem_ip,
                    "siem_version": deployment.siem_version,
                    "agent_group": deployment.agent_group,
                    "os_type": deployment.os_type,
                    "config_template_id": deployment.config_template_id,
                    "lifecycle_status": "starting"
                }
            )
        
        # Deploy in parallel using multiprocessing
        results = []
        warnings = []
        
        with ProcessPoolExecutor(max_workers=cpu_count()) as executor:
            future_to_name = {
                executor.submit(deploy_single_siem_agent, name, deployment_dict, agent_seq_ids[name]): name
                for name in agent_names
            }
            
            for future in as_completed(future_to_name):
                try:
                    result = future.result(timeout=600)
                    results.append(result)
                    if not result["success"]:
                        warnings.append(f"Failed to deploy container {result['agent_name']}: {result.get('error')}")
                except Exception as e:
                    agent_name = future_to_name[future]
                    logger.error(f"Exception deploying {agent_name}: {e}")
                    results.append({
                        "agent_name": agent_name,
                        "success": False,
                        "error": str(e)
                    })
                    warnings.append(f"Exception deploying {agent_name}: {str(e)}")
        
        elapsed_time = time.time() - start_time
        successful = [r for r in results if r["success"]]
        failed = [r for r in results if not r["success"]]
        
        # Log completion
        log_activity(
            "container_deployment_completed",
            {
                "total_requested": deployment.count,
                "successful": len(successful),
                "failed": len(failed),
                "elapsed_time": elapsed_time
            },
            status="success" if len(failed) == 0 else "partial"
        )
        
        return APIResponse(
            success=len(failed) == 0,
            message=f"Deployed {len(successful)}/{deployment.count} containers in {elapsed_time:.2f}s",
            data={
                "total_requested": deployment.count,
                "successful": len(successful),
                "failed": len(failed),
                "elapsed_time_seconds": round(elapsed_time, 2),
                "agents_per_second": round(len(successful) / elapsed_time, 2) if elapsed_time > 0 else 0,
                "deployed_agents": [r for r in results if r["success"]],
                "failed_agents": [r for r in results if not r["success"]],
                "warnings": warnings,
                "siem_mapping": {
                    "siem_type": deployment.siem_type,
                    "siem_ip": deployment.siem_ip,
                    "siem_version": deployment.siem_version,
                    "agent_group": deployment.agent_group
                }
            },
            error=f"{len(failed)} containers failed" if failed else None
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Container deployment failed: {e}")
        log_activity("container_deployment_failed", {"error": str(e)}, status="error")
        return APIResponse(success=False, message="Container deployment failed", error=str(e))

def deploy_single_siem_agent(agent_name: str, deployment_config: dict, agent_seq_id: Optional[int] = None) -> dict:
    """Deploy a single container with a SIEM agent"""
    deploy_start = time.time()
    try:
        logger.info(f"[{os.getpid()}] Deploying container: {agent_name}")
        
        # Check if container exists
        if agent_name in lxc.list_containers():
            write_agent_metadata(
                agent_name,
                {
                    "agent_seq_id": agent_seq_id,
                    "lifecycle_status": "error",
                    "state": "EXISTS"
                }
            )
            return {
                "agent_name": agent_name,
                "agent_seq_id": agent_seq_id,
                "success": False,
                "error": "Container already exists"
            }
        
        # Create container
        container = lxc.Container(agent_name)
        
        # Map OS type to LXC parameters
        os_config = get_os_config(deployment_config["os_type"])
        
        success = container.create(
            "download",
            0,
            {
                "dist": os_config["distro"],
                "release": os_config["release"],
                "arch": os_config["arch"]
            }
        )
        
        if not success:
            write_agent_metadata(
                agent_name,
                {
                    "agent_seq_id": agent_seq_id,
                    "lifecycle_status": "error",
                    "state": "CREATE_FAILED"
                }
            )
            return {
                "agent_name": agent_name,
                "agent_seq_id": agent_seq_id,
                "success": False,
                "error": "Container creation failed"
            }
        
        # Apply resource limits
        if deployment_config.get("memory_limit"):
            container.set_cgroup_item("memory.max", parse_memory_limit(deployment_config["memory_limit"]))
        
        if deployment_config.get("cpu_shares"):
            container.set_cgroup_item("cpu.shares", str(deployment_config["cpu_shares"]))
        
        # OSSEC requires agent IPs to match what the manager sees. With the
        # default lxcbr0 (NAT), all containers share the host IP and OSSEC
        # rejects duplicates. Macvlan gives each container its own IP on the
        # host's physical network, solving the mismatch.
        siem_type = deployment_config.get("siem_type")
        if siem_type == "ossec":
            host_iface = get_host_interface()
            if host_iface:
                configure_container_macvlan(container, host_iface)
            else:
                logger.warning(
                    f"[{agent_name}] No wired interface for macvlan (WiFi-only host). "
                    f"Containers will use NAT. OSSEC manager needs <use_source_ip>no</use_source_ip> "
                    f"in its auth config, or agents must be manually keyed."
                )

        container.save_config()
        
        # Start container
        if not container.start():
            container.destroy()
            write_agent_metadata(
                agent_name,
                {
                    "agent_seq_id": agent_seq_id,
                    "lifecycle_status": "error",
                    "state": "START_FAILED"
                }
            )
            return {
                "agent_name": agent_name,
                "agent_seq_id": agent_seq_id,
                "success": False,
                "error": "Container start failed"
            }
        
        container.wait("RUNNING", 10)
        time.sleep(2)  # Wait for network

        # Install SIEM agent based on type
        install_result = None

        if siem_type == "none":
            install_result = {"success": True, "stdout": "Bare container (no SIEM agent)"}
        elif siem_type == "wazuh":
            install_result = install_wazuh_agent(
                agent_name,
                deployment_config["siem_ip"],
                deployment_config["agent_group"],
                deployment_config.get("siem_version") or "4.14.2",
                deployment_config.get("config_template_id")
            )
        elif siem_type == "ossec":
            install_result = install_ossec_agent(
                agent_name,
                deployment_config["siem_ip"],
                deployment_config.get("config_template_id")
            )
        elif siem_type == "ossim":
            install_result = install_ossim_agent(
                agent_name,
                deployment_config["siem_ip"],
                deployment_config.get("config_template_id")
            )
        elif siem_type == "utmstack":
            install_result = install_utmstack_agent(
                agent_name,
                deployment_config["siem_ip"],
                deployment_config.get("siem_auth_key", ""),
                deployment_config.get("config_template_id")
            )
        elif siem_type == "elastic":
            install_result = install_elastic_agent(
                agent_name,
                deployment_config["siem_ip"],
                deployment_config.get("siem_auth_key", ""),
                deployment_config.get("siem_version") or "9.0.2",
                deployment_config.get("config_template_id")
            )
        else:
            container.stop()
            container.destroy()
            write_agent_metadata(
                agent_name,
                {
                    "agent_seq_id": agent_seq_id,
                    "lifecycle_status": "error",
                    "state": "UNSUPPORTED"
                }
            )
            return {
                "agent_name": agent_name,
                "agent_seq_id": agent_seq_id,
                "success": False,
                "error": f"Unsupported SIEM type: {siem_type}"
            }
        
        # Get container IP
        ips = container.get_ips() if container.running else []

        install_success = install_result.get("success", False)
        write_agent_metadata(
            agent_name,
            {
                "agent_seq_id": agent_seq_id,
                "siem_type": siem_type,
                "siem_ip": deployment_config.get("siem_ip"),
                "siem_version": deployment_config.get("siem_version"),
                "agent_group": deployment_config.get("agent_group"),
                "os_type": deployment_config.get("os_type"),
                "config_template_id": deployment_config.get("config_template_id"),
                "installation_success": install_success,
                "lifecycle_status": "running" if container.running else "stopped",
                "state": container.state,
                "init_pid": container.init_pid,
                "ip_addresses": ips
            }
        )
        try:
            health_setup = setup_agent_health_check(agent_name)
            if not health_setup.get("success", False):
                logger.warning(f"Health check setup failed for {agent_name}: {health_setup.get('stderr')}")
        except Exception as e:
            logger.warning(f"Health check setup error for {agent_name}: {e}")
        
        return {
            "agent_name": agent_name,
            "agent_seq_id": agent_seq_id,
            "container_id": agent_name,
            "success": install_success,
            "siem_type": siem_type,
            "siem_ip": deployment_config.get("siem_ip"),
            "agent_group": deployment_config.get("agent_group"),
            "os_type": deployment_config.get("os_type"),
            "ip_address": ips[0] if ips else None,
            "agent_installation": {
                "success": install_result["success"],
                "message": install_result.get("stdout", "")[:200] if install_result["success"] else install_result.get("stderr", "")
            },
            "deploy_time_seconds": round(time.time() - deploy_start, 2),
        }

        # Record per-container deployment timing
        try:
            record_metric(DB_PATH, "deployment", "container_deploy_time",
                         time.time() - deploy_start, siem_type)
            if install_success:
                record_metric(DB_PATH, "deployment", "container_success", 1, siem_type)
            else:
                record_metric(DB_PATH, "deployment", "container_failure", 1, siem_type)
        except Exception:
            pass
        
    except Exception as e:
        logger.error(f"Failed to deploy {agent_name}: {e}")
        return {
            "agent_name": agent_name,
            "success": False,
            "error": str(e)
        }

def get_os_config(os_type: str) -> dict:
    """Map OS type to LXC configuration"""
    os_configs = {
        "ubuntu_22_04": {"distro": "ubuntu", "release": "jammy", "arch": "amd64"},
        "ubuntu_20_04": {"distro": "ubuntu", "release": "focal", "arch": "amd64"},
        "debian_11": {"distro": "debian", "release": "bullseye", "arch": "amd64"},
    }
    return os_configs.get(os_type, os_configs["ubuntu_22_04"])

# ===== CONTAINER MANAGEMENT =====

@app.get("/agents", response_model=APIResponse)
async def list_agents(
    siem_type: Optional[str] = Query(None, description="Filter by SIEM type"),
    status: Optional[str] = Query(None, description="Filter by status"),
    agent_group: Optional[str] = Query(None, description="Filter by container group"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """List all containers with filtering and pagination"""
    try:
        all_agents = []
        
        for name in lxc.list_containers():
            container = lxc.Container(name)
            agent_info = get_agent_info(container)
            
            # Apply filters
            if siem_type and agent_info.get("siem_type") != siem_type:
                continue
            if status and agent_info.get("lifecycle_status") != status:
                continue
            if agent_group and agent_info.get("agent_group") != agent_group:
                continue
            
            all_agents.append(agent_info)
        
        # Pagination
        total = len(all_agents)
        paginated_agents = all_agents[offset:offset + limit]
        
        return APIResponse(
            success=True,
            message=f"Retrieved {len(paginated_agents)} containers",
            data={
                "agents": paginated_agents,
                "total": total,
                "limit": limit,
                "offset": offset,
                "has_more": offset + limit < total
            }
        )
        
    except Exception as e:
        logger.error(f"Failed to list containers: {e}")
        return APIResponse(success=False, message="Failed to list containers", error=str(e))

def _build_log_upload_script(log_upload: LogUploadRequest) -> str:
    operator = ">>" if log_upload.append else ">"
    return f"""
mkdir -p $(dirname {log_upload.destination_path})
cat {operator} {log_upload.destination_path} << 'EOFLOG'
{log_upload.content}
EOFLOG
chmod 644 {log_upload.destination_path}
"""


def _escape_json_string(value: str) -> str:
    return (
        value
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def _escape_bash_single_quotes(value: str) -> str:
    return value.replace("'", "'\"'\"'")


def _build_custom_log_script(config: CustomLogSimulationRequest, simulation_id: str) -> str:
    extra_fields = jsonable_encoder(config.extra_fields or {})
    extra_fragment = ""
    if extra_fields:
        extra_json = json.dumps(extra_fields)
        if extra_json and extra_json != "{}":
            extra_fragment = f",{extra_json[1:-1]}"

    message_escaped = _escape_json_string(config.message)
    script = f"""
FILE_PATH='{_escape_bash_single_quotes(config.file_path)}'
MESSAGE_ESCAPED='{_escape_bash_single_quotes(message_escaped)}'
SRC_IP='{_escape_bash_single_quotes(config.src_ip)}'
DEST_IP='{_escape_bash_single_quotes(config.dest_ip)}'
EXTRA_FRAGMENT='{_escape_bash_single_quotes(extra_fragment)}'
SIM_ID='{_escape_bash_single_quotes(simulation_id)}'
START_TIME='{_escape_bash_single_quotes(config.start_time.isoformat() if config.start_time else "")}'
EPS={config.eps}
DURATION={config.duration}
SEQ_START={config.seq_start}
TOTAL=$((EPS * DURATION))

mkdir -p "$(dirname "$FILE_PATH")"

if [ -n "$START_TIME" ]; then
  START_EPOCH=$(date -u -d "$START_TIME" +%s 2>/dev/null || date +%s)
else
  START_EPOCH=$(date +%s)
fi

SEQ=$((SEQ_START - 1))
COUNT=0

for s in $(seq 1 "$DURATION"); do
  TS=$(date -u -d "@$((START_EPOCH + s - 1))" +%Y-%m-%dT%H:%M:%SZ)
  for i in $(seq 1 "$EPS"); do
    COUNT=$((COUNT + 1))
    SEQ=$((SEQ + 1))
    printf '{{"timestamp":"%s","date":"%s","eps":%s,"duration_seconds":%s,"src_ip":"%s","dest_ip":"%s","file_path":"%s","message":"%s","count":%s,"seq":%s,"simulation_id":"%s","total_count":%s%s}}\\n' \\
      "$TS" "$TS" "$EPS" "$DURATION" "$SRC_IP" "$DEST_IP" "$FILE_PATH" "$MESSAGE_ESCAPED" "$COUNT" "$SEQ" "$SIM_ID" "$TOTAL" "$EXTRA_FRAGMENT" >> "$FILE_PATH"
  done
  sleep 1
done

echo "Generated $COUNT custom events"
"""
    return script


def _build_utmstack_filebeat_script(log_path: str) -> str:
    """Generate a script that adds a log path to UTMstack's filebeat config and restarts the collector.

    The default system.yml has ``#var.paths:`` (commented, no space).
    Three cases:
      1. Path already present → skip
      2. ``#var.paths:`` (default/commented) → uncomment and add path below
      3. ``var.paths:`` exists (already uncommented) → append path to list
    """
    yml = "/opt/utmstack-linux-agent/beats/filebeat/modules.d/system.yml"
    return f"""
if [ ! -f {yml} ]; then exit 0; fi

if grep -qF '{log_path}' {yml} 2>/dev/null; then
  echo "Path {log_path} already in filebeat config"
  exit 0
fi

# Case: default commented "#var.paths:" — uncomment and add path.
# Matches the first occurrence only (syslog section, not auth section).
if grep -q '^ *#var\\.paths:' {yml} 2>/dev/null; then
  sed -i '0,/^ *#var\\.paths:/{{
    s|^ *#var\\.paths:.*|    var.paths:\\n      - {log_path}|
  }}' {yml}
# Case: already uncommented "var.paths:" — append path to the list.
elif grep -q '^ *var\\.paths:' {yml} 2>/dev/null; then
  sed -i '0,/^ *var\\.paths:/{{
    /^ *var\\.paths:/a\\      - {log_path}
  }}' {yml}
# Case: neither found — insert after "enabled: true" in syslog section.
else
  sed -i '0,/enabled: true/{{
    /enabled: true/a\\\\n    var.paths:\\n      - {log_path}
  }}' {yml}
fi

systemctl restart UTMStackModulesLogsCollector 2>/dev/null || true
echo "UTMstack filebeat config updated for {log_path}"
"""


async def _perform_log_upload(agent_id: str, log_upload: LogUploadRequest) -> Dict[str, Any]:
    script = _build_log_upload_script(log_upload)
    result = execute_in_container(agent_id, script, timeout=30)

    if result.get("success"):
        # If this is a UTMstack container, update filebeat config to monitor the destination path
        metadata = read_agent_metadata(agent_id)
        siem_type = metadata.get("siem_type")
        if not siem_type:
            siem_type = detect_siem_type(agent_id)
        if siem_type == "utmstack":
            fb_script = _build_utmstack_filebeat_script(log_upload.destination_path)
            fb_result = execute_in_container(agent_id, fb_script, timeout=30)
            if fb_result.get("success"):
                logger.info(f"[{agent_id}] UTMstack filebeat configured for {log_upload.destination_path}")
            else:
                logger.warning(f"[{agent_id}] UTMstack filebeat config update failed: {fb_result.get('stderr', '')}")

    return result


async def _run_log_schedule(schedule_id: str, agent_id: str, log_upload: LogUploadRequest,
                            interval_seconds: int, duration_seconds: Optional[int], indefinite: bool) -> None:
    start_time = time.time()
    scheduled_log_tasks[schedule_id]["status"] = "running"
    scheduled_log_tasks[schedule_id]["last_run"] = None
    scheduled_log_tasks[schedule_id]["runs"] = 0

    try:
        while True:
            if agent_id not in lxc.list_containers():
                scheduled_log_tasks[schedule_id]["status"] = "stopped"
                scheduled_log_tasks[schedule_id]["error"] = "Container not found"
                log_activity("log_schedule_stopped", {"schedule_id": schedule_id, "container_id": agent_id}, status="error")
                break

            result = await _perform_log_upload(agent_id, log_upload)
            scheduled_log_tasks[schedule_id]["last_run"] = utc_now().isoformat()
            scheduled_log_tasks[schedule_id]["runs"] += 1
            if not result.get("success"):
                scheduled_log_tasks[schedule_id]["last_error"] = result.get("stderr") or result.get("error")

            if not indefinite and duration_seconds is not None:
                if time.time() - start_time >= duration_seconds:
                    scheduled_log_tasks[schedule_id]["status"] = "completed"
                    break

            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        scheduled_log_tasks[schedule_id]["status"] = "stopped"
    except Exception as e:
        scheduled_log_tasks[schedule_id]["status"] = "error"
        scheduled_log_tasks[schedule_id]["error"] = str(e)
        log_activity("log_schedule_failed", {"schedule_id": schedule_id, "container_id": agent_id, "error": str(e)}, status="error")


def _schedule_public(schedule: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in schedule.items() if k != "task"}


@app.post("/agents/{agent_id}/logs/schedule", response_model=APIResponse)
async def schedule_log_upload(agent_id: str, schedule: LogScheduleRequest):
    """Schedule periodic log uploads to a container."""
    try:
        if agent_id not in lxc.list_containers():
            raise HTTPException(status_code=404, detail=f"Container {agent_id} not found")

        if schedule.interval_seconds < 5:
            raise HTTPException(status_code=400, detail="interval_seconds must be at least 5 seconds")

        if not schedule.indefinite and not schedule.duration_seconds:
            raise HTTPException(status_code=400, detail="duration_seconds is required unless indefinite is true")

        schedule_id = str(uuid.uuid4())
        log_upload = LogUploadRequest(
            content=schedule.content,
            destination_path=schedule.destination_path,
            log_type=schedule.log_type,
            append=schedule.append
        )

        scheduled_log_tasks[schedule_id] = {
            "schedule_id": schedule_id,
            "agent_id": agent_id,
            "interval_seconds": schedule.interval_seconds,
            "duration_seconds": schedule.duration_seconds,
            "indefinite": schedule.indefinite,
            "status": "starting",
            "created_at": utc_now().isoformat(),
        }

        task = asyncio.create_task(
            _run_log_schedule(
                schedule_id,
                agent_id,
                log_upload,
                schedule.interval_seconds,
                schedule.duration_seconds,
                schedule.indefinite
            )
        )
        scheduled_log_tasks[schedule_id]["task"] = task
        log_activity("log_schedule_started", {"schedule_id": schedule_id, "container_id": agent_id})

        return APIResponse(
            success=True,
            message="Log schedule created",
            data=_schedule_public(scheduled_log_tasks[schedule_id])
        )
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to schedule log upload", error=str(e))


@app.post("/agents/logs/schedules/{schedule_id}/stop", response_model=APIResponse)
async def stop_log_schedule(schedule_id: str):
    """Stop a scheduled log upload."""
    try:
        schedule = scheduled_log_tasks.get(schedule_id)
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")
        task = schedule.get("task")
        if task and not task.done():
            task.cancel()
        schedule["status"] = "stopped"
        log_activity("log_schedule_stopped", {"schedule_id": schedule_id, "container_id": schedule.get("agent_id")})
        return APIResponse(success=True, message="Schedule stopped", data=_schedule_public(schedule))
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to stop schedule", error=str(e))


@app.get("/agents/logs/schedules", response_model=APIResponse)
async def list_log_schedules():
    """List all log upload schedules."""
    data = []
    for schedule in scheduled_log_tasks.values():
        data.append(_schedule_public(schedule))
    return APIResponse(success=True, message="Log schedules retrieved", data={"schedules": data})


# ===== GROUP MANAGEMENT =====

@app.get("/groups", response_model=APIResponse)
async def list_agent_groups():
    """List all container groups with counts."""
    try:
        data = list_groups(DB_PATH)
        return APIResponse(success=True, message="Groups retrieved", data=data)
    except Exception as e:
        logger.error(f"Failed to list groups: {e}")
        return APIResponse(success=False, message="Failed to list groups", error=str(e))


@app.post("/groups", response_model=APIResponse)
async def create_agent_group(request: GroupCreateRequest):
    """Create a new container group."""
    try:
        if group_exists(DB_PATH, request.name):
            raise HTTPException(status_code=400, detail="Group already exists")
        group = create_group(DB_PATH, request.name, request.description)
        log_activity("group_created", {"group": request.name})
        return APIResponse(success=True, message="Group created", data=group)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create group: {e}")
        return APIResponse(success=False, message="Failed to create group", error=str(e))


@app.post("/groups/{group_name}/rename", response_model=APIResponse)
async def rename_agent_group(group_name: str, request: GroupRenameRequest):
    """Rename a container group."""
    try:
        if not group_exists(DB_PATH, group_name):
            raise HTTPException(status_code=404, detail="Group not found")
        result = rename_group(DB_PATH, group_name, request.new_name, request.description)
        log_activity("group_renamed", {"group": group_name, "new_name": request.new_name})
        return APIResponse(success=True, message="Group renamed", data=result)
    except HTTPException:
        raise
    except ValueError as e:
        return APIResponse(success=False, message="Failed to rename group", error=str(e))
    except Exception as e:
        logger.error(f"Failed to rename group: {e}")
        return APIResponse(success=False, message="Failed to rename group", error=str(e))


@app.delete("/groups/{group_name}", response_model=APIResponse)
async def delete_agent_group(group_name: str):
    """Delete a container group and unassign containers."""
    try:
        if not group_exists(DB_PATH, group_name):
            raise HTTPException(status_code=404, detail="Group not found")
        removed = delete_group(DB_PATH, group_name)
        log_activity("group_deleted", {"group": group_name, "removed_containers": removed})
        return APIResponse(success=True, message="Group deleted", data={"group": group_name, "removed_containers": removed})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete group: {e}")
        return APIResponse(success=False, message="Failed to delete group", error=str(e))


@app.post("/groups/{group_name}/assign", response_model=APIResponse)
async def assign_group_agents(group_name: str, request: GroupAgentRequest):
    """Assign containers to a group."""
    try:
        if not group_exists(DB_PATH, group_name):
            raise HTTPException(status_code=404, detail="Group not found")
        existing = set(lxc.list_containers())
        valid_agent_ids = [agent_id for agent_id in request.agent_ids if agent_id in existing]
        invalid_agent_ids = [agent_id for agent_id in request.agent_ids if agent_id not in existing]

        for agent_id in valid_agent_ids:
            get_or_create_agent_seq_id(DB_PATH, agent_id)

        updated = assign_agents_to_group(DB_PATH, group_name, valid_agent_ids)
        log_activity("group_assign", {"group": group_name, "containers": request.agent_ids})
        return APIResponse(
            success=True,
            message=f"Assigned {updated} containers to {group_name}",
            data={
                "group": group_name,
                "assigned": updated,
                "invalid_containers": invalid_agent_ids
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to assign group: {e}")
        return APIResponse(success=False, message="Failed to assign group", error=str(e))


@app.post("/groups/{group_name}/remove", response_model=APIResponse)
async def remove_group_agents(group_name: str, request: GroupAgentRequest):
    """Remove containers from a group."""
    try:
        if not group_exists(DB_PATH, group_name):
            raise HTTPException(status_code=404, detail="Group not found")
        updated = remove_agents_from_group(DB_PATH, request.agent_ids)
        log_activity("group_remove", {"group": group_name, "containers": request.agent_ids})
        return APIResponse(
            success=True,
            message=f"Removed {updated} containers from {group_name}",
            data={"group": group_name, "removed": updated}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to remove from group: {e}")
        return APIResponse(success=False, message="Failed to remove group", error=str(e))


@app.post("/groups/{group_name}/bulk/{operation}", response_model=APIResponse)
async def bulk_group_operation(group_name: str, operation: str):
    """Perform bulk operations on all containers in a group."""
    try:
        if operation not in ['start', 'stop', 'delete']:
            raise HTTPException(status_code=400, detail=f"Invalid operation: {operation}")
        if not group_exists(DB_PATH, group_name):
            raise HTTPException(status_code=404, detail="Group not found")

        agent_ids = get_agents_in_group(DB_PATH, group_name)
        if not agent_ids:
            return APIResponse(success=False, message="No containers in group", error="empty_group")

        request = BulkOperationRequest(container_names=agent_ids, operation=operation)
        return await bulk_agent_operation(operation, request)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed group bulk operation: {e}")
        return APIResponse(success=False, message="Failed group bulk operation", error=str(e))


@app.post("/groups/{group_name}/logs/upload", response_model=APIResponse)
async def upload_logs_to_group(group_name: str, log_upload: LogUploadRequest):
    """Upload log content to all containers in a group."""
    try:
        if not group_exists(DB_PATH, group_name):
            raise HTTPException(status_code=404, detail="Group not found")
        agent_ids = get_agents_in_group(DB_PATH, group_name)
        if not agent_ids:
            return APIResponse(success=False, message="No containers in group", error="empty_group")

        results = []
        for agent_id in agent_ids:
            if agent_id not in lxc.list_containers():
                results.append({"agent_id": agent_id, "success": False, "error": "Not found"})
                continue
            result = await _perform_log_upload(agent_id, log_upload)
            results.append({"agent_id": agent_id, "success": result.get("success"), "error": result.get("stderr")})

        log_activity("group_logs_uploaded", {"group": group_name, "count": len(agent_ids)})
        return APIResponse(success=True, message="Logs uploaded to group", data={"results": results})
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to upload logs to group", error=str(e))


@app.post("/groups/{group_name}/logs/schedule", response_model=APIResponse)
async def schedule_logs_to_group(group_name: str, schedule: LogScheduleRequest):
    """Schedule periodic log uploads to all containers in a group."""
    try:
        if not group_exists(DB_PATH, group_name):
            raise HTTPException(status_code=404, detail="Group not found")
        agent_ids = get_agents_in_group(DB_PATH, group_name)
        if not agent_ids:
            return APIResponse(success=False, message="No containers in group", error="empty_group")

        schedules = []
        for agent_id in agent_ids:
            result = await schedule_log_upload(agent_id, schedule)
            if result.success and result.data:
                schedules.append(result.data)
        log_activity("group_log_schedule_started", {"group": group_name, "count": len(schedules)})
        return APIResponse(success=True, message="Log schedules created", data={"schedules": schedules})
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to schedule logs to group", error=str(e))

@app.get("/agents/stats", response_model=APIResponse)
async def get_agents_stats():
    """Get aggregated container statistics"""
    try:
        containers = lxc.list_containers()
        total_agents = len(containers)
        
        stats_by_siem = {}
        stats_by_status = {"running": 0, "stopped": 0, "error": 0}
        
        for name in containers:
            container = lxc.Container(name)
            agent_info = get_agent_info(container)
            
            # Count by SIEM type
            siem_type = agent_info.get("siem_type", "unknown")
            stats_by_siem[siem_type] = stats_by_siem.get(siem_type, 0) + 1
            
            # Count by status
            lifecycle = agent_info.get("lifecycle_status", "error")
            if lifecycle in stats_by_status:
                stats_by_status[lifecycle] += 1
            else:
                stats_by_status["error"] += 1
        
        return APIResponse(
            success=True,
            message="Container statistics retrieved",
            data={
                "total_agents": total_agents,
                "by_siem_type": stats_by_siem,
                "by_status": stats_by_status,
                "timestamp": utc_now().isoformat()
            }
        )
        
    except Exception as e:
        logger.error(f"Failed to get container stats: {e}")
        return APIResponse(success=False, message="Failed to get container statistics", error=str(e))

@app.get("/agents/{agent_id}", response_model=APIResponse)
async def get_agent(agent_id: str):
    """Get detailed information about a specific container"""
    try:
        if agent_id not in lxc.list_containers():
            raise HTTPException(status_code=404, detail=f"Container '{agent_id}' not found")
        
        container = lxc.Container(agent_id)
        agent_info = get_agent_info(container, detailed=True)
        
        return APIResponse(
            success=True,
            message=f"Container '{agent_id}' details retrieved",
            data=agent_info
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get container {agent_id}: {e}")
        return APIResponse(success=False, message="Failed to get container details", error=str(e))

def get_agent_info(container, detailed: bool = False) -> dict:
    """Extract comprehensive container information from container"""
    info = {
        "agent_id": container.name,
        "agent_name": container.name,
        "lifecycle_status": "running" if container.running else "stopped",
        "state": container.state,
        "init_pid": container.init_pid,
        "ip_addresses": container.get_ips() if container.running else [],
    }

    metadata = read_agent_metadata(container.name)
    if metadata:
        for key in [
            "agent_seq_id",
            "siem_type",
            "siem_ip",
            "siem_version",
            "agent_group",
            "os_type",
            "created_at",
            "tags",
            "siem_agent_status",
            "siem_agent_running",
            "siem_agent_last_check",
            "manager_host",
            "manager_port",
            "manager_status",
            "manager_reachable"
        ]:
            value = metadata.get(key)
            if value is not None:
                info[key] = value

    # Try to extract SIEM metadata from container config
    # In production, store this in database
    try:
        config_file = container.config_file_name
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                config_content = f.read().lower()
                if "wazuh" in config_content:
                    info["siem_type"] = "wazuh"
                elif "ossec" in config_content:
                    info["siem_type"] = "ossec"
                elif "ossim" in config_content:
                    info["siem_type"] = "ossim"
                elif "utmstack" in config_content:
                    info["siem_type"] = "utmstack"
                elif "elastic" in config_content:
                    info["siem_type"] = "elastic"
    except Exception:
        pass
    
    if container.running:
        status_result = execute_in_container(
            container.name,
            "cat /var/lib/siem-agent-status.json 2>/dev/null",
            timeout=5
        )
        if status_result.get("success") and status_result.get("stdout"):
            try:
                status_payload = json.loads(status_result["stdout"])
                info["siem_agent_status"] = status_payload.get("status")
                info["siem_agent_running"] = status_payload.get("running")
                info["siem_agent_last_check"] = status_payload.get("last_check")
                info["manager_host"] = status_payload.get("manager_host")
                info["manager_port"] = status_payload.get("manager_port")
                info["manager_status"] = status_payload.get("manager_status")
                info["manager_reachable"] = status_payload.get("manager_reachable")
                if status_payload.get("siem_type") and not info.get("siem_type"):
                    info["siem_type"] = status_payload.get("siem_type")
                write_agent_metadata(
                    container.name,
                    {
                        "siem_type": info.get("siem_type"),
                        "siem_agent_status": info.get("siem_agent_status"),
                        "siem_agent_running": info.get("siem_agent_running"),
                        "siem_agent_last_check": info.get("siem_agent_last_check"),
                        "manager_host": info.get("manager_host"),
                        "manager_port": info.get("manager_port"),
                        "manager_status": info.get("manager_status"),
                        "manager_reachable": info.get("manager_reachable"),
                    }
                )
            except json.JSONDecodeError:
                pass

    if detailed:
        info["stats"] = get_container_stats(container.name)
        info["siem_connectivity"] = check_siem_connectivity(container.name)
    
    write_agent_metadata(
        container.name,
        {
            "agent_seq_id": info.get("agent_seq_id"),
            "lifecycle_status": info.get("lifecycle_status"),
            "state": info.get("state"),
            "init_pid": info.get("init_pid"),
            "ip_addresses": info.get("ip_addresses")
        }
    )

    return info


def detect_siem_type(container_name: str) -> Optional[str]:
    """Detect SIEM type by checking installed agent artifacts."""
    try:
        container = lxc.Container(container_name)
        if not container.running:
            return None
        script = (
            "if [ -f /var/ossec/bin/wazuh-control ] || [ -f /var/ossec/bin/wazuh-agentd ]; then "
            "echo wazuh; "
            "elif [ -f /var/ossec/bin/ossec-control ] || [ -f /var/ossec/bin/ossec-agentd ]; then "
            "echo ossec; "
            "elif [ -f /usr/share/ossim/agent/agent.py ]; then "
            "echo ossim; "
            "elif [ -f /opt/utmstack-linux-agent/utmstack_agent_service ]; then "
            "echo utmstack; "
            "elif command -v elastic-agent >/dev/null 2>&1; then "
            "echo elastic; "
            "else echo unknown; fi"
        )
        result = execute_in_container(container_name, script, timeout=10)
        if result.get("success") and result.get("stdout"):
            return result["stdout"].strip().splitlines()[-1]
    except Exception:
        return None
    return None

def check_siem_connectivity(container_name: str) -> dict:
    """Check SIEM agent connectivity status"""
    try:
        container = lxc.Container(container_name)
        if not container.running:
            return {
                "status": "disconnected",
                "reason": "Container not running",
                "last_check": utc_now().isoformat()
            }
        
        # Check if Wazuh agent is running
        check_result = execute_in_container(
            container_name,
            "systemctl is-active wazuh-agent 2>/dev/null || service wazuh-agent status 2>/dev/null || echo 'unknown'",
            timeout=10
        )
        
        if "active" in check_result.get("stdout", "").lower():
            status = "connected"
        elif "inactive" in check_result.get("stdout", "").lower():
            status = "pending"
        else:
            status = "disconnected"
        
        return {
            "status": status,
            "last_check": utc_now().isoformat(),
            "agent_status": check_result.get("stdout", "").strip()
        }
        
    except Exception as e:
        return {
            "status": "error",
            "reason": str(e),
            "last_check": utc_now().isoformat()
        }

@app.delete("/agents/{agent_id}", response_model=APIResponse)
async def delete_agent(agent_id: str, root: bool = Depends(check_root)):
    """Delete a container and optionally unregister from SIEM"""
    try:
        if agent_id not in lxc.list_containers():
            raise HTTPException(status_code=404, detail=f"Container '{agent_id}' not found")
        
        container = lxc.Container(agent_id)
        
        # Stop container if running
        if container.running:
            if not container.shutdown(10):
                container.stop()
            container.wait("STOPPED", 10)
        
        # Destroy container
        success = container.destroy()
        
        if success:
            log_activity("container_deleted", {"container_id": agent_id})
            delete_agent_metadata(agent_id)
            return APIResponse(
                success=True,
                message=f"Container '{agent_id}' deleted successfully"
            )
        else:
            return APIResponse(
                success=False,
                message=f"Failed to delete container '{agent_id}'",
                error="Destroy operation failed"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete container {agent_id}: {e}")
        return APIResponse(success=False, message="Failed to delete container", error=str(e))

@app.post("/agents/bulk/{operation}", response_model=APIResponse)
async def bulk_agent_operation(
    operation: str,
    request: BulkOperationRequest,
    root: bool = Depends(check_root)
):
    """Perform bulk operations on multiple containers"""
    try:
        if operation not in ['start', 'stop', 'delete']:
            raise HTTPException(status_code=400, detail=f"Invalid operation: {operation}")
        
        results = []
        
        for agent_id in request.container_names:
            try:
                if agent_id not in lxc.list_containers():
                    results.append({"agent_id": agent_id, "success": False, "error": "Not found"})
                    continue
                
                container = lxc.Container(agent_id)
                
                if operation == "start":
                    success = container.start() if not container.running else False
                elif operation == "stop":
                    success = container.shutdown(10) if container.running else False
                elif operation == "delete":
                    if container.running:
                        container.stop()
                        container.wait("STOPPED", 10)
                    success = container.destroy()
                    if success:
                        delete_agent_metadata(agent_id)
                
                results.append({"agent_id": agent_id, "success": success})
                
            except Exception as e:
                results.append({"agent_id": agent_id, "success": False, "error": str(e)})
        
        successful = sum(1 for r in results if r["success"])
        log_activity(f"bulk_{operation}", {
            "total": len(request.container_names),
            "successful": successful
        })
        
        return APIResponse(
            success=successful == len(request.container_names),
            message=f"Bulk {operation}: {successful}/{len(request.container_names)} successful",
            data={"results": results}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bulk operation failed: {e}")
        return APIResponse(success=False, message="Bulk operation failed", error=str(e))

@app.post("/agents/{agent_id}/start", response_model=APIResponse)
async def start_agent(agent_id: str, root: bool = Depends(check_root)):
    """Start a container"""
    try:
        if agent_id not in lxc.list_containers():
            raise HTTPException(status_code=404, detail=f"Container '{agent_id}' not found")
        
        container = lxc.Container(agent_id)
        
        if container.running:
            return APIResponse(
                success=False,
                message=f"Container '{agent_id}' is already running"
            )
        
        success = container.start()
        if success:
            container.wait("RUNNING", 10)
            log_activity("container_started", {"container_id": agent_id})
            return APIResponse(
                success=True,
                message=f"Container '{agent_id}' started successfully"
            )
        else:
            return APIResponse(
                success=False,
                message=f"Failed to start container '{agent_id}'",
                error="Start operation failed"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start container {agent_id}: {e}")
        return APIResponse(success=False, message="Failed to start container", error=str(e))

@app.post("/agents/{agent_id}/stop", response_model=APIResponse)
async def stop_agent(agent_id: str, root: bool = Depends(check_root)):
    """Stop a container"""
    try:
        if agent_id not in lxc.list_containers():
            raise HTTPException(status_code=404, detail=f"Container '{agent_id}' not found")
        
        container = lxc.Container(agent_id)
        
        if not container.running:
            return APIResponse(
                success=False,
                message=f"Container '{agent_id}' is not running"
            )
        
        if not container.shutdown(10):
            container.stop()
        
        container.wait("STOPPED", 10)
        log_activity("container_stopped", {"container_id": agent_id})
        
        return APIResponse(
            success=True,
            message=f"Container '{agent_id}' stopped successfully"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to stop container {agent_id}: {e}")
        return APIResponse(success=False, message="Failed to stop container", error=str(e))

# ===== ATTACK SIMULATIONS =====

def list_simulation_profiles() -> List[str]:
    """List available simulation profiles"""
    return [
        "auth_bruteforce",
        "web_attacks",
        "malware_beacon",
        "lateral_movement",
        "data_exfiltration",
        "privilege_escalation"
    ]

@app.get("/simulations", response_model=APIResponse)
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


@app.post("/simulations/load", response_model=APIResponse)
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


@app.post("/simulations/syslog/start", response_model=APIResponse)
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

@app.post("/simulations/start", response_model=APIResponse)
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

def select_agents_for_simulation(selector: AgentSelector) -> List[str]:
    """Select containers based on selector criteria"""
    all_containers = lxc.list_containers()
    selected = []
    
    # Filter by labels/tags (simplified - use metadata in production)
    for name in all_containers:
        container = lxc.Container(name)
        if not container.running:
            continue
        
        # Add filtering logic based on selector
        selected.append(name)
    
    if selector.count:
        selected = random.sample(selected, min(selector.count, len(selected)))
    
    return selected

async def run_simulation(simulation_id: str, profile_id: str, agents: List[str], 
                        duration: int, eps_target: int):
    """Run simulation on selected containers"""
    try:
        logger.info(f"Starting simulation {simulation_id} on {len(agents)} containers")
        
        start_time = time.time()
        end_time = start_time + duration
        events_generated = 0
        
        while time.time() < end_time:
            # Generate events on containers
            for agent in agents:
                try:
                    result = generate_simulation_events(agent, profile_id, eps_target)
                    events_generated += result.get("events", 0)
                except Exception as e:
                    logger.error(f"Error generating events on {agent}: {e}")
            
            await asyncio.sleep(1)
            
            # Update simulation status
            if simulation_id in simulations_db:
                simulations_db[simulation_id]["events_generated"] = events_generated
        
        # Mark as completed
        if simulation_id in simulations_db:
            simulations_db[simulation_id]["status"] = "completed"
            simulations_db[simulation_id]["completed_at"] = utc_now().isoformat()
            simulations_db[simulation_id]["events_generated"] = events_generated
        
        log_activity("simulation_completed", {
            "simulation_id": simulation_id,
            "events_generated": events_generated
        })
        
        logger.info(f"Simulation {simulation_id} completed with {events_generated} events")
        
    except Exception as e:
        logger.error(f"Simulation {simulation_id} failed: {e}")
        if simulation_id in simulations_db:
            simulations_db[simulation_id]["status"] = "failed"
            simulations_db[simulation_id]["error"] = str(e)


async def run_custom_log_simulation(
    simulation_id: str,
    containers: List[str],
    config: CustomLogSimulationRequest
) -> None:
    try:
        timeout = config.duration + 60
        tasks = []
        for container_name in containers:
            script = _build_custom_log_script(config, simulation_id)
            tasks.append(asyncio.to_thread(
                execute_in_container_shell,
                container_name,
                script,
                None,
                timeout
            ))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        errors = []
        success_count = 0
        for container_name, result in zip(containers, results):
            if isinstance(result, Exception):
                errors.append({"container": container_name, "error": str(result)})
                continue
            if not result.get("success"):
                errors.append({"container": container_name, "error": result.get("stderr")})
                continue
            success_count += 1

        total_events = config.eps * config.duration * success_count

        if simulation_id in simulations_db:
            simulations_db[simulation_id]["events_generated"] = total_events
            simulations_db[simulation_id]["completed_at"] = utc_now().isoformat()
            simulations_db[simulation_id]["status"] = "completed" if success_count == len(containers) else "failed"
            if errors:
                simulations_db[simulation_id]["errors"] = errors

        log_activity("custom_log_simulation_completed", {
            "simulation_id": simulation_id,
            "successful_containers": success_count,
            "failed_containers": len(containers) - success_count,
            "events_generated": total_events
        })
    except Exception as e:
        logger.error(f"Custom log simulation {simulation_id} failed: {e}")
        if simulation_id in simulations_db:
            simulations_db[simulation_id]["status"] = "failed"
            simulations_db[simulation_id]["error"] = str(e)
        log_activity("custom_log_simulation_failed", {"simulation_id": simulation_id, "error": str(e)}, status="error")


SYSLOG_TEMPLATES = {
    "router": [
        "%LINK-5-CHANGED: Interface GigabitEthernet0/{iface} changed state to administratively down",
        "%LINEPROTO-5-UPDOWN: Line protocol on Interface GigabitEthernet0/{iface}, changed state to down",
        "%SYS-5-CONFIG_I: Configured from console by admin on vty0 ({device_ip})",
        "%OSPF-5-ADJCHG: Process 1, Nbr {peer_ip} on GigabitEthernet0/{iface} from FULL to DOWN, Neighbor Down: Dead timer expired",
        "%SEC_LOGIN-5-LOGIN_SUCCESS: Login successful [user: admin] [Source: {src_ip}] [localport: 22] at {timestamp}"
    ],
    "switch": [
        "%LINK-3-UPDOWN: Interface FastEthernet0/{iface}, changed state to up",
        "%SPANTREE-6-PORTBLK: Port Fa0/{iface} blocked by spanning tree.",
        "%MACFLAP_NOTIF: Host {mac} in vlan {vlan} is flapping between port Fa0/{iface} and port Fa0/{iface_alt}",
        "%DHCP_SNOOPING-5-DHCP_SNOOPING_NONZERO_GIADDR: DHCP_SNOOPING drop message with non-zero giaddr from interface Fa0/{iface}",
        "%AUTHPRIV-6-SYSTEM_MSG: AAA authorization succeeded for user admin - shell"
    ],
    "firewall": [
        "%ASA-6-302013: Built inbound TCP connection {conn} for inside:{src_ip}/{src_port} ({src_ip}/{src_port}) to outside:{dst_ip}/80",
        "%ASA-6-302014: Teardown TCP connection {conn} for inside:{src_ip}/{src_port} to outside:{dst_ip}/80 duration 0:{min}:{sec} bytes {bytes}",
        "%ASA-4-106023: Deny tcp src outside:{dst_ip}/{dst_port} dst inside:{src_ip}/22 by access-group \"OUTSIDE_IN\" [0x0, 0x0]",
        "%ASA-5-111008: User 'admin' executed the 'enable' command.",
        "%ASA-6-305011: Built dynamic UDP translation from inside:{src_ip}/{src_port} to outside:{dst_ip}/{dst_port}"
    ],
    "ids": [
        "%ET NETBIOS DCERPC ISystemActivator SMB named pipe access attempt {sig}",
        "%ET TROJAN Possible Metasploit Payload common.ports.dstport {sig}",
        "%GPL ATTACK_RESPONSE id check returned root {sig}",
        "%ET SCAN Potential SSH Scan {sig}",
        "%ET WEB_CLIENT Microsoft Internet Explorer invalid MIME type attempt {sig}"
    ]
}


def _select_syslog_template(device_type: str) -> str:
    return random.choice(SYSLOG_TEMPLATES.get(device_type, SYSLOG_TEMPLATES["router"]))


def _build_syslog_message(device_name: str, device_ip: str, device_type: str, facility: int) -> str:
    timestamp = datetime.now().strftime("%b %d %H:%M:%S")
    severity = random.choices(
        [0, 1, 2, 3, 4, 5, 6, 7],
        weights=[0.1, 0.5, 1, 2, 5, 10, 70, 11.4]
    )[0]
    pri = f"<{facility * 8 + severity}>"
    template = _select_syslog_template(device_type)
    payload = template.format(
        iface=random.randint(1, 24),
        iface_alt=random.randint(1, 24),
        device_ip=device_ip,
        peer_ip=f"{random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}",
        src_ip=f"{random.randint(10,250)}.{random.randint(10,250)}.{random.randint(10,250)}.{random.randint(10,250)}",
        dst_ip=f"{random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}.{random.randint(1,254)}",
        src_port=random.randint(1024, 65535),
        dst_port=random.randint(1024, 65535),
        conn=random.randint(1000, 9999),
        min=random.randint(0, 59),
        sec=random.randint(0, 59),
        bytes=random.randint(100, 99999),
        vlan=random.randint(1, 100),
        mac=":".join(f"{random.randint(0,255):02x}" for _ in range(6)),
        sig=random.randint(1000, 9999),
        timestamp=timestamp
    )
    header = f"{timestamp} {device_name}"
    return f"{pri}{header}: {payload}"


def _send_syslog_message(target_ip: str, target_port: int, protocol: str, message: str) -> bool:
    try:
        if protocol == "tcp":
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect((target_ip, target_port))
            sock.sendall(message.encode("utf-8") + b"\n")
            sock.close()
        else:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.sendto(message.encode("utf-8"), (target_ip, target_port))
            sock.close()
        return True
    except Exception:
        return False


def run_syslog_simulation(simulation_id: str, request: SyslogSimulationRequest) -> None:
    try:
        device_types = ["router", "switch", "firewall", "ids"]
        device_type_value = request.device_type.value if hasattr(request.device_type, "value") else request.device_type
        if device_type_value != "mixed":
            device_types = [device_type_value]

        devices = []
        for idx in range(request.device_count):
            device_type = device_types[idx % len(device_types)]
            device_name = f"{request.device_name_prefix}-{idx + 1:02d}"
            device_ip = f"10.0.{(idx % 254) + 1}.{(idx % 250) + 1}"
            devices.append((device_name, device_ip, device_type))

        total_sent = 0
        total_failed = 0
        protocol = request.protocol.value if hasattr(request.protocol, "value") else request.protocol
        per_device_base = request.eps // request.device_count
        remainder = request.eps % request.device_count

        for second in range(request.duration):
            status = simulations_db.get(simulation_id, {}).get("status")
            if status != "running":
                break
            for index, (device_name, device_ip, device_type) in enumerate(devices):
                count = per_device_base + (1 if index < remainder else 0)
                for _ in range(count):
                    message = _build_syslog_message(device_name, device_ip, device_type, request.facility)
                    if _send_syslog_message(request.target_ip, request.target_port, protocol, message):
                        total_sent += 1
                    else:
                        total_failed += 1
            time.sleep(1)

        simulation = simulations_db.get(simulation_id)
        if simulation:
            simulation["events_generated"] = total_sent
            simulation["completed_at"] = utc_now().isoformat()
            if simulation.get("status") == "running":
                simulation["status"] = "completed" if total_sent > 0 else "failed"
            simulation["messages_failed"] = total_failed

        log_activity("syslog_simulation_completed", {
            "simulation_id": simulation_id,
            "messages_sent": total_sent,
            "messages_failed": total_failed
        })
    except Exception as e:
        logger.error(f"Syslog simulation {simulation_id} failed: {e}")
        if simulation_id in simulations_db:
            simulations_db[simulation_id]["status"] = "failed"
            simulations_db[simulation_id]["error"] = str(e)
        log_activity("syslog_simulation_failed", {"simulation_id": simulation_id, "error": str(e)}, status="error")

def generate_simulation_events(agent_name: str, profile_id: str, eps_target: int) -> dict:
    """Generate simulation events on a container"""
    try:
        script = get_simulation_script(profile_id, eps_target)
        result = execute_in_container(agent_name, script, timeout=10)
        
        return {
            "success": result["success"],
            "events": eps_target  # Simplified
        }
    except Exception as e:
        logger.error(f"Failed to generate events on {agent_name}: {e}")
        return {"success": False, "events": 0}

def get_simulation_script(profile_id: str, eps_target: int) -> str:
    """Get simulation script for a profile"""
    scripts = {
        "auth_bruteforce": f"""
            for i in {{1..{eps_target}}}; do
                echo "$(date) sshd[$$]: Failed password for invalid user admin from 192.168.1.100 port 22 ssh2" >> /var/log/auth.log
            done
        """,
        "web_attacks": f"""
            for i in {{1..{eps_target}}}; do
                echo '$(date) 192.168.1.100 - - [$(date)] "GET /admin/../../../etc/passwd HTTP/1.1" 404 -' >> /var/log/apache2/access.log
            done
        """,
        "malware_beacon": f"""
            for i in {{1..{eps_target}}}; do
                echo "$(date) MALWARE: Beacon to C2 server 185.220.100.240:443" >> /var/log/syslog
            done
        """
    }
    
    return scripts.get(profile_id, "echo 'Unknown profile'")

@app.post("/simulations/{simulation_id}/stop", response_model=APIResponse)
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

# ===== CONFIGURATION MANAGEMENT =====

@app.get("/configs", response_model=APIResponse)
async def list_configs():
    """List all configuration templates"""
    try:
        return APIResponse(
            success=True,
            message="Configuration templates retrieved",
            data={
                "templates": list(config_templates.values()),
                "total": len(config_templates)
            }
        )
    except Exception as e:
        return APIResponse(success=False, message="Failed to list configs", error=str(e))

@app.post("/configs/import", response_model=APIResponse)
async def import_config(config: ConfigImportRequest):
    """Import a configuration template"""
    try:
        template_id = str(uuid.uuid4())
        
        template = {
            "template_id": template_id,
            "name": config.name,
            "siem_type": config.siem_type,
            "content": config.content,
            "description": config.description,
            "created_at": utc_now().isoformat()
        }
        
        config_templates[template_id] = template
        
        # Save to file
        config_file = CONFIGS_DIR / f"{template_id}.json"
        with open(config_file, 'w') as f:
            json.dump(template, f, indent=2)
        
        log_activity("config_imported", {"template_id": template_id, "name": config.name})
        
        return APIResponse(
            success=True,
            message="Configuration template imported",
            data=template
        )
        
    except Exception as e:
        return APIResponse(success=False, message="Failed to import config", error=str(e))

@app.get("/configs/export/{template_id}", response_model=APIResponse)
async def export_config(template_id: str):
    """Export a configuration template"""
    try:
        if template_id not in config_templates:
            raise HTTPException(status_code=404, detail=f"Template {template_id} not found")
        
        template = config_templates[template_id]
        
        return APIResponse(
            success=True,
            message="Configuration template retrieved",
            data=template
        )
        
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to export config", error=str(e))

@app.post("/agents/{agent_id}/logs/upload", response_model=APIResponse)
async def upload_logs_to_agent(agent_id: str, log_upload: LogUploadRequest):
    """Upload log content to a container"""
    try:
        if agent_id not in lxc.list_containers():
            raise HTTPException(status_code=404, detail=f"Container {agent_id} not found")
        
        # Write log content to container
        result = await _perform_log_upload(agent_id, log_upload)
        
        if result["success"]:
            log_activity("logs_uploaded", {
                "agent_id": agent_id,
                "path": log_upload.destination_path
            })
            
            return APIResponse(
                success=True,
                message=f"Logs uploaded to {log_upload.destination_path}",
                data={
                    "agent_id": agent_id,
                    "destination_path": log_upload.destination_path,
                    "bytes_written": len(log_upload.content)
                }
            )
        else:
            return APIResponse(
                success=False,
                message="Failed to upload logs",
                error=result.get("stderr")
            )
        
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to upload logs", error=str(e))

# ===== REPORTING =====

def _build_report_metrics(since: str) -> dict:
    """Compute actual performance metrics for reports."""
    try:
        deploy = get_metric_summary(DB_PATH, "deployment", "container_deploy_time", since)
        mem = get_metric_summary(DB_PATH, "system", "memory_used_percent", since)
        cpu = get_metric_summary(DB_PATH, "system", "cpu_load_1m", since)
        return {
            "deployment_time": {
                "avg_seconds": round(deploy.get("avg") or 0, 2),
                "p50_seconds": round(deploy.get("p50") or 0, 2),
                "p90_seconds": round(deploy.get("p90") or 0, 2),
                "p99_seconds": round(deploy.get("p99") or 0, 2),
                "total_deployments": deploy.get("cnt") or 0,
            },
            "system_resources": {
                "memory_avg_percent": round(mem.get("avg") or 0, 1),
                "memory_max_percent": round(mem.get("max") or 0, 1),
                "cpu_load_avg": round(cpu.get("avg") or 0, 2),
                "cpu_load_max": round(cpu.get("max") or 0, 2),
            },
            "simulation_throughput": {
                "total_events": sum(s.get("events_generated", 0) for s in simulations_db.values()),
                "completed_simulations": len([s for s in simulations_db.values() if s.get("status") == "completed"]),
            },
        }
    except Exception:
        return {}


def _build_report_findings(agents_by_status: dict) -> list:
    """Generate automated findings based on current state."""
    findings = []
    stopped = agents_by_status.get("stopped", 0)
    error = agents_by_status.get("error", 0)
    total = sum(agents_by_status.values())

    if error > 0:
        findings.append({
            "finding_id": "ERR_AGENTS",
            "severity": "critical",
            "title": f"{error} containers in error state",
            "description": f"{error} out of {total} containers are in an error state.",
            "recommendation": "Check container logs and redeploy failed containers.",
        })

    if total > 0 and stopped / total > 0.5:
        findings.append({
            "finding_id": "HIGH_STOPPED",
            "severity": "warning",
            "title": f"{stopped}/{total} containers stopped",
            "description": f"{round(stopped/total*100)}% of containers are stopped.",
            "recommendation": "Start stopped containers or remove unused ones.",
        })

    try:
        deploy_summary = get_metric_summary(DB_PATH, "deployment", "container_deploy_time")
        if (deploy_summary.get("p90") or 0) > 300:
            findings.append({
                "finding_id": "SLOW_DEPLOY",
                "severity": "warning",
                "title": "Slow deployment times detected",
                "description": f"P90 deployment time is {round(deploy_summary['p90'])}s (>5 min).",
                "recommendation": "Check network connectivity and use agent package caching.",
            })
    except Exception:
        pass

    if not findings:
        findings.append({
            "finding_id": "ALL_OK",
            "severity": "info",
            "title": "No issues detected",
            "description": "All monitored metrics are within normal ranges.",
        })

    return findings


@app.post("/reports/generate", response_model=APIResponse)
async def generate_report(report_request: ReportGenerateRequest):
    """Generate a performance/benchmark report"""
    try:
        report_id = str(uuid.uuid4())
        
        # Collect data
        containers = lxc.list_containers()
        agent_stats = []
        
        for name in containers:
            container = lxc.Container(name)
            agent_info = get_agent_info(container, detailed=True)
            agent_stats.append(agent_info)
        
        # Aggregate stats
        agents_by_siem = {}
        agents_by_os = {}
        agents_by_status = {}
        for agent in agent_stats:
            siem = agent.get("siem_type") or "unknown"
            agents_by_siem[siem] = agents_by_siem.get(siem, 0) + 1
            os_type = agent.get("os_type") or "unknown"
            agents_by_os[os_type] = agents_by_os.get(os_type, 0) + 1
            status = agent.get("lifecycle_status") or "unknown"
            agents_by_status[status] = agents_by_status.get(status, 0) + 1

        start_time = normalize_dt(report_request.start_time)
        end_time = normalize_dt(report_request.end_time)
        simulations_in_range = []
        simulations_by_type = {}
        syslog_targets = {}
        for sim in simulations_db.values():
            started_at = sim.get("started_at")
            if not started_at:
                continue
            try:
                sim_time = normalize_dt(datetime.fromisoformat(started_at))
            except Exception:
                continue
            if start_time <= sim_time <= end_time:
                simulations_in_range.append(sim.get("simulation_id"))

            sim_type = sim.get("simulation_type") or sim.get("profile_id") or "unknown"
            simulations_by_type[sim_type] = simulations_by_type.get(sim_type, 0) + 1

            if sim_type == "syslog":
                params = sim.get("custom_parameters") or {}
                target_key = f"{params.get('target_ip', 'unknown')}:{params.get('target_port', 'unknown')}/{params.get('protocol', 'unknown')}"
                syslog_targets[target_key] = syslog_targets.get(target_key, 0) + 1

        # Generate report
        report = {
            "report_id": report_id,
            "generated_at": utc_now().isoformat(),
            "time_range": {
                "start": start_time.isoformat(),
                "end": end_time.isoformat()
            },
            "summary": {
                "total_agents": len(containers),
                "agents_by_siem": agents_by_siem,
                "agents_by_os": agents_by_os,
                "total_simulations": len(simulations_db),
                "simulations_in_range": [s for s in simulations_in_range if s],
                "simulations_by_type": simulations_by_type,
                "syslog_targets": syslog_targets
            },
            "metrics": _build_report_metrics(start_time.isoformat()),
            "findings": _build_report_findings(agents_by_status)
        }
        
        # Convert datetimes to JSON-safe values
        report_data = jsonable_encoder(report)

        # Save JSON report
        reports_db[report_id] = report_data
        report_file = REPORTS_DIR / f"{report_id}.json"
        with open(report_file, 'w') as f:
            json.dump(report_data, f, indent=2)
        report_files[report_id] = {"json": str(report_file)}

        requested_format = (report_request.format or "json").lower()
        download_path = report_file
        download_format = "json"

        if requested_format == "csv":
            csv_file = REPORTS_DIR / f"{report_id}.csv"
            generate_report_csv(report_data, csv_file)
            report_files[report_id]["csv"] = str(csv_file)
            download_path = csv_file
            download_format = "csv"
        elif requested_format == "pdf":
            pdf_file = REPORTS_DIR / f"{report_id}.pdf"
            generate_report_pdf(report_data, agents_by_status, pdf_file)
            report_files[report_id]["pdf"] = str(pdf_file)
            download_path = pdf_file
            download_format = "pdf"
        
        log_activity("report_generated", {"report_id": report_id})
        
        return APIResponse(
            success=True,
            message="Report generated successfully",
            data={
                "report_id": report_id,
                "report": report_data,
                "format": requested_format,
                "download_url": f"/reports/{report_id}/download?format={download_format}"
            }
        )
        
    except Exception as e:
        logger.error(f"Failed to generate report: {e}")
        return APIResponse(success=False, message="Failed to generate report", error=str(e))

@app.get("/reports/{report_id}", response_model=APIResponse)
async def get_report(report_id: str):
    """Retrieve a generated report"""
    try:
        if report_id not in reports_db:
            raise HTTPException(status_code=404, detail=f"Report {report_id} not found")
        
        return APIResponse(
            success=True,
            message="Report retrieved",
            data=reports_db[report_id]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to retrieve report", error=str(e))

@app.get("/reports/{report_id}/download")
async def download_report(report_id: str, format: Optional[str] = Query(None)):
    """Download report in the requested format (json, csv, pdf)."""
    try:
        requested = (format or "json").lower()
        available = report_files.get(report_id, {})
        report_path = available.get(requested)
        if not report_path:
            report_path = available.get("json") or str(REPORTS_DIR / f"{report_id}.json")
            requested = "json"

        report_file = Path(report_path)
        if not report_file.exists():
            raise HTTPException(status_code=404, detail="Report file not found")

        media_type = {
            "json": "application/json",
            "csv": "text/csv",
            "pdf": "application/pdf"
        }.get(requested, "application/octet-stream")

        return FileResponse(
            report_file,
            media_type=media_type,
            filename=f"report_{report_id}.{requested}"
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to download report: {str(e)}")

# ===== ACTIVITY LOGS =====

@app.get("/activity/logs", response_model=APIResponse)
async def get_activity_logs(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    action: Optional[str] = Query(None, description="Filter by action type")
):
    """Retrieve activity logs with filtering"""
    try:
        filtered_logs = read_activity_logs_from_files(action)
        total = len(filtered_logs)
        paginated_logs = filtered_logs[offset:offset + limit]
        
        return APIResponse(
            success=True,
            message=f"Retrieved {len(paginated_logs)} activity logs",
            data={
                "logs": paginated_logs,
                "total": total,
                "limit": limit,
                "offset": offset,
                "has_more": offset + limit < total
            }
        )
        
    except Exception as e:
        return APIResponse(success=False, message="Failed to retrieve activity logs", error=str(e))

# ===== MANAGER PROFILES =====

@app.get("/managers", response_model=APIResponse)
async def list_manager_profiles():
    """List all manager profiles"""
    try:
        managers = list_managers(DB_PATH)
        return APIResponse(success=True, message=f"Retrieved {len(managers)} manager profiles", data={"managers": managers, "total": len(managers)})
    except Exception as e:
        return APIResponse(success=False, message="Failed to list managers", error=str(e))


@app.get("/managers/{manager_id}", response_model=APIResponse)
async def get_manager_profile(manager_id: str):
    """Get a single manager profile"""
    try:
        mgr = get_manager(DB_PATH, manager_id)
        if not mgr:
            raise HTTPException(status_code=404, detail="Manager profile not found")
        return APIResponse(success=True, message="Manager profile retrieved", data=mgr)
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to get manager", error=str(e))


@app.post("/managers", response_model=APIResponse)
async def create_manager_profile(profile: ManagerProfileCreate):
    """Create a manager profile"""
    try:
        if get_manager_by_name(DB_PATH, profile.name):
            raise HTTPException(status_code=400, detail=f"Manager profile '{profile.name}' already exists")
        manager_id = str(uuid.uuid4())
        data = profile.dict()
        mgr = create_manager(DB_PATH, manager_id, data)
        log_activity("manager_created", {"manager_id": manager_id, "name": profile.name})
        return APIResponse(success=True, message="Manager profile created", data=mgr)
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to create manager", error=str(e))


@app.put("/managers/{manager_id}", response_model=APIResponse)
async def update_manager_profile(manager_id: str, profile: ManagerProfileUpdate):
    """Update a manager profile"""
    try:
        data = {k: v for k, v in profile.dict().items() if v is not None}
        mgr = update_manager(DB_PATH, manager_id, data)
        if not mgr:
            raise HTTPException(status_code=404, detail="Manager profile not found")
        log_activity("manager_updated", {"manager_id": manager_id})
        return APIResponse(success=True, message="Manager profile updated", data=mgr)
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to update manager", error=str(e))


@app.delete("/managers/{manager_id}", response_model=APIResponse)
async def delete_manager_profile(manager_id: str):
    """Delete a manager profile"""
    try:
        if not delete_manager(DB_PATH, manager_id):
            raise HTTPException(status_code=404, detail="Manager profile not found")
        log_activity("manager_deleted", {"manager_id": manager_id})
        return APIResponse(success=True, message="Manager profile deleted")
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to delete manager", error=str(e))

# ===== PERFORMANCE METRICS & BENCHMARKS =====

@app.get("/metrics/benchmarks", response_model=APIResponse)
async def get_benchmarks(since: Optional[str] = Query(None, description="ISO timestamp to filter from")):
    """Get deployment and simulation performance benchmarks with percentiles"""
    try:
        deploy_time = get_metric_summary(DB_PATH, "deployment", "container_deploy_time", since)
        successes = get_metric_summary(DB_PATH, "deployment", "container_success", since)
        failures = get_metric_summary(DB_PATH, "deployment", "container_failure", since)

        total_deploys = (successes.get("cnt") or 0) + (failures.get("cnt") or 0)
        success_rate = round(((successes.get("cnt") or 0) / total_deploys * 100), 1) if total_deploys > 0 else 0

        api_latency = get_metric_summary(DB_PATH, "api_latency", "/agents/deploy", since)

        return APIResponse(success=True, message="Benchmarks retrieved", data={
            "deployment": {
                "total_deploys": total_deploys,
                "success_rate_percent": success_rate,
                "deploy_time_seconds": {
                    "avg": round(deploy_time.get("avg") or 0, 2),
                    "min": round(deploy_time.get("min") or 0, 2),
                    "max": round(deploy_time.get("max") or 0, 2),
                    "p50": round(deploy_time.get("p50") or 0, 2),
                    "p90": round(deploy_time.get("p90") or 0, 2),
                    "p99": round(deploy_time.get("p99") or 0, 2),
                },
            },
            "api_latency_ms": {
                "deploy_endpoint": {
                    "avg": round(api_latency.get("avg") or 0, 1),
                    "p50": round(api_latency.get("p50") or 0, 1),
                    "p90": round(api_latency.get("p90") or 0, 1),
                    "p99": round(api_latency.get("p99") or 0, 1),
                },
            },
            "simulations": {
                "total_events_generated": sum(s.get("events_generated", 0) for s in simulations_db.values()),
                "completed": len([s for s in simulations_db.values() if s.get("status") == "completed"]),
                "failed": len([s for s in simulations_db.values() if s.get("status") == "failed"]),
            },
        })
    except Exception as e:
        return APIResponse(success=False, message="Failed to get benchmarks", error=str(e))


@app.get("/metrics/history", response_model=APIResponse)
async def get_metrics_history(
    metric_type: str = Query(..., description="e.g. system, deployment, api_latency"),
    metric_name: Optional[str] = Query(None),
    since: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
):
    """Get raw metrics history for charting"""
    try:
        rows = query_metrics(DB_PATH, metric_type, metric_name, since, limit)
        return APIResponse(success=True, message=f"Retrieved {len(rows)} data points", data={"metrics": rows})
    except Exception as e:
        return APIResponse(success=False, message="Failed to query metrics", error=str(e))


@app.get("/metrics/system", response_model=APIResponse)
async def get_system_metrics():
    """Get current system resource metrics"""
    try:
        res = get_system_resources()
        return APIResponse(success=True, message="System metrics retrieved", data=res)
    except Exception as e:
        return APIResponse(success=False, message="Failed to get system metrics", error=str(e))


# ===== BENCHMARK ENDPOINTS =====

import benchmarks as bm_engine

@app.get("/benchmarks/scenarios", response_model=APIResponse)
async def list_benchmark_scenarios():
    """List available benchmark scenarios"""
    scenarios = [{"id": s["id"], "name": s["name"], "description": s["description"],
                  "phases": len(s["phases"]), "total_agents": sum(p.get("agents", 0) for p in s["phases"])}
                 for s in bm_engine.SCENARIOS.values()]
    return APIResponse(success=True, message="Scenarios retrieved", data={"scenarios": scenarios})


class BenchmarkStartRequest(BaseModel):
    scenario_id: str = "linear_scale"
    name: Optional[str] = None
    siem_type: Optional[str] = "none"
    siem_ip: Optional[str] = None
    siem_version: Optional[str] = None
    siem_auth_key: Optional[str] = None
    base_name: Optional[str] = None
    memory_limit: Optional[str] = "256MB"
    os_type: Optional[str] = "ubuntu_22_04"
    agent_group: Optional[str] = "benchmark"
    metric_interval: Optional[int] = None
    failure_threshold: Optional[float] = None

@app.post("/benchmarks/start", response_model=APIResponse)
async def start_benchmark(request: BenchmarkStartRequest,
                          background_tasks: BackgroundTasks):
    """Start a benchmark execution"""
    try:
        scenario_id = request.scenario_id
        if scenario_id not in bm_engine.SCENARIOS:
            raise HTTPException(status_code=400, detail=f"Unknown scenario: {scenario_id}")
        benchmark_id = str(uuid.uuid4())
        cfg = {k: v for k, v in request.dict().items() if v is not None}
        if request.name:
            cfg["name"] = request.name

        background_tasks.add_task(bm_engine.run_benchmark, benchmark_id, scenario_id, cfg)
        log_activity("benchmark_started", {"benchmark_id": benchmark_id, "scenario": scenario_id})

        return APIResponse(success=True, message=f"Benchmark {benchmark_id[:8]} started",
                          data={"benchmark_id": benchmark_id, "scenario_id": scenario_id})
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to start benchmark", error=str(e))


@app.post("/benchmarks/{benchmark_id}/stop", response_model=APIResponse)
async def stop_benchmark(benchmark_id: str):
    """Stop a running benchmark"""
    if benchmark_id in bm_engine.active_benchmarks:
        bm_engine.active_benchmarks[benchmark_id]["status"] = "stopped"
        return APIResponse(success=True, message="Benchmark stop requested")
    # If not in memory but still marked running in DB, it's stale — abort it
    bm = bm_engine.get_benchmark(benchmark_id)
    if bm and bm["status"] == "running":
        bm_engine._save_benchmark({**bm, "status": "aborted", "completed_at": bm_engine._now()})
        return APIResponse(success=True, message="Stale benchmark marked as aborted")
    return APIResponse(success=False, message="Benchmark not found or not running")


@app.post("/benchmarks/cleanup", response_model=APIResponse)
async def cleanup_benchmarks():
    """Mark all stale 'running' benchmarks as aborted"""
    cleaned = bm_engine.cleanup_stale_benchmarks()
    return APIResponse(success=True, message=f"Cleaned up {cleaned} stale benchmark(s)",
                      data={"cleaned": cleaned})


@app.get("/benchmarks", response_model=APIResponse)
async def list_benchmarks_endpoint():
    """List all benchmarks"""
    benchmarks = bm_engine.list_benchmarks()
    return APIResponse(success=True, message=f"Retrieved {len(benchmarks)} benchmarks",
                      data={"benchmarks": benchmarks, "total": len(benchmarks)})


@app.get("/benchmarks/{benchmark_id}", response_model=APIResponse)
async def get_benchmark_detail(benchmark_id: str):
    """Get detailed benchmark results"""
    bm = bm_engine.get_benchmark(benchmark_id)
    if not bm:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    # Merge live data if running
    if benchmark_id in bm_engine.active_benchmarks:
        bm["live"] = bm_engine.active_benchmarks[benchmark_id].get("results", {}).get("live")
    return APIResponse(success=True, message="Benchmark retrieved", data=bm)


@app.get("/benchmarks/{benchmark_id}/metrics", response_model=APIResponse)
async def get_benchmark_metrics_endpoint(benchmark_id: str,
                                         category: Optional[str] = None,
                                         limit: int = Query(1000, ge=1, le=10000)):
    """Get time-series metrics for a benchmark"""
    metrics = bm_engine.get_benchmark_metrics(benchmark_id, category, limit)
    return APIResponse(success=True, message=f"Retrieved {len(metrics)} data points",
                      data={"metrics": metrics})


@app.get("/benchmarks/{benchmark_id}/bottlenecks", response_model=APIResponse)
async def get_benchmark_bottlenecks_endpoint(benchmark_id: str):
    """Get detected bottlenecks for a benchmark"""
    bottlenecks = bm_engine.get_benchmark_bottlenecks(benchmark_id)
    return APIResponse(success=True, message=f"Retrieved {len(bottlenecks)} bottlenecks",
                      data={"bottlenecks": bottlenecks})


class BenchmarkCompareRequest(BaseModel):
    benchmark_ids: List[str]

@app.post("/benchmarks/compare", response_model=APIResponse)
async def compare_benchmarks_endpoint(request: BenchmarkCompareRequest):
    """Compare multiple benchmarks side-by-side"""
    result = bm_engine.compare_benchmarks(request.benchmark_ids)
    if "error" in result:
        return APIResponse(success=False, message=result["error"])
    return APIResponse(success=True, message="Comparison complete", data=result)


# ===== SYSLOG CONFIG PROFILES =====

@app.get("/syslog-configs", response_model=APIResponse)
async def list_syslog_config_profiles():
    """List all syslog config profiles"""
    try:
        configs = list_syslog_configs(DB_PATH)
        return APIResponse(success=True, message=f"Retrieved {len(configs)} syslog configs", data={"configs": configs, "total": len(configs)})
    except Exception as e:
        return APIResponse(success=False, message="Failed to list syslog configs", error=str(e))


@app.post("/syslog-configs", response_model=APIResponse)
async def create_syslog_config_profile(config: SyslogConfigCreate):
    """Create a syslog config profile"""
    try:
        config_id = str(uuid.uuid4())
        result = create_syslog_config(DB_PATH, config_id, config.dict())
        log_activity("syslog_config_created", {"config_id": config_id, "name": config.name})
        return APIResponse(success=True, message="Syslog config created", data=result)
    except Exception as e:
        return APIResponse(success=False, message="Failed to create syslog config", error=str(e))


@app.get("/syslog-configs/{config_id}", response_model=APIResponse)
async def get_syslog_config_profile(config_id: str):
    """Get a syslog config profile"""
    try:
        cfg = get_syslog_config(DB_PATH, config_id)
        if not cfg:
            raise HTTPException(status_code=404, detail="Syslog config not found")
        return APIResponse(success=True, message="Syslog config retrieved", data=cfg)
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to get syslog config", error=str(e))


@app.put("/syslog-configs/{config_id}", response_model=APIResponse)
async def update_syslog_config_profile(config_id: str, config: SyslogConfigUpdate):
    """Update a syslog config profile"""
    try:
        data = {k: v for k, v in config.dict().items() if v is not None}
        result = update_syslog_config(DB_PATH, config_id, data)
        if not result:
            raise HTTPException(status_code=404, detail="Syslog config not found")
        log_activity("syslog_config_updated", {"config_id": config_id})
        return APIResponse(success=True, message="Syslog config updated", data=result)
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to update syslog config", error=str(e))


@app.delete("/syslog-configs/{config_id}", response_model=APIResponse)
async def delete_syslog_config_profile(config_id: str):
    """Delete a syslog config profile"""
    try:
        if not delete_syslog_config(DB_PATH, config_id):
            raise HTTPException(status_code=404, detail="Syslog config not found")
        log_activity("syslog_config_deleted", {"config_id": config_id})
        return APIResponse(success=True, message="Syslog config deleted")
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to delete syslog config", error=str(e))


@app.post("/syslog-configs/test-connectivity", response_model=APIResponse)
async def test_syslog_connectivity(target_ip: str = Query(...), target_port: int = Query(514), protocol: str = Query("tcp")):
    """Test TCP/UDP connectivity to a syslog target"""
    try:
        if protocol.lower() == "tcp":
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            sock.connect((target_ip, target_port))
            sock.close()
            status = "connected"
        else:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(5)
            sock.sendto(b"<14>test connectivity check\n", (target_ip, target_port))
            sock.close()
            status = "sent"  # UDP is fire-and-forget

        return APIResponse(success=True, message=f"Connectivity test: {status}", data={
            "target_ip": target_ip, "target_port": target_port, "protocol": protocol, "status": status
        })
    except socket.timeout:
        return APIResponse(success=False, message="Connection timed out", data={
            "target_ip": target_ip, "target_port": target_port, "protocol": protocol, "status": "timeout"
        })
    except Exception as e:
        return APIResponse(success=False, message=f"Connection failed: {e}", data={
            "target_ip": target_ip, "target_port": target_port, "protocol": protocol, "status": "error", "error": str(e)
        })


@app.post("/agents/{agent_id}/enable-syslog", response_model=APIResponse)
async def enable_utmstack_syslog(agent_id: str, protocol: str = Query("tcp")):
    """Enable syslog on a UTMstack container (port 7014) and create a syslog config profile"""
    try:
        if agent_id not in lxc.list_containers():
            raise HTTPException(status_code=404, detail=f"Container {agent_id} not found")

        proto = protocol.lower()
        if proto not in ("tcp", "udp"):
            raise HTTPException(status_code=400, detail="Protocol must be tcp or udp")

        cmd = f"/opt/utmstack-linux-agent/utmstack_agent_service enable-integration syslog {proto}"
        result = execute_in_container(agent_id, cmd, timeout=30)

        if not result.get("success"):
            return APIResponse(success=False, message="Failed to enable syslog", error=result.get("stderr", ""))

        # Get the container's IP for the syslog config profile
        container = lxc.Container(agent_id)
        ips = container.get_ips() if container.running else []
        agent_ip = ips[0] if ips else agent_id

        # Auto-create a syslog config profile for this listener
        profile_name = f"{agent_id}-syslog-{proto}"
        config_id = str(uuid.uuid4())
        try:
            create_syslog_config(DB_PATH, config_id, {
                "name": profile_name,
                "description": f"Auto-created: syslog {proto.upper()} on {agent_id} port 7014",
                "target_ip": agent_ip,
                "target_port": 7014,
                "protocol": proto,
                "siem_type": "utmstack",
            })
        except Exception:
            pass  # profile may already exist from a previous enable

        log_activity("utmstack_syslog_enabled", {"agent_id": agent_id, "protocol": proto})
        return APIResponse(success=True, message=f"Syslog {proto.upper()} enabled on {agent_id} (port 7014)", data={
            "agent_id": agent_id, "protocol": proto, "port": 7014,
            "syslog_config_profile": profile_name,
            "target_ip": agent_ip,
            "output": result.get("stdout", ""),
        })
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to enable syslog", error=str(e))


@app.post("/agents/{agent_id}/disable-syslog", response_model=APIResponse)
async def disable_utmstack_syslog(agent_id: str, protocol: str = Query("tcp")):
    """Disable syslog on a UTMstack container"""
    try:
        if agent_id not in lxc.list_containers():
            raise HTTPException(status_code=404, detail=f"Container {agent_id} not found")

        proto = protocol.lower()
        if proto not in ("tcp", "udp"):
            raise HTTPException(status_code=400, detail="Protocol must be tcp or udp")

        cmd = f"/opt/utmstack-linux-agent/utmstack_agent_service disable-integration syslog {proto}"
        result = execute_in_container(agent_id, cmd, timeout=30)

        if not result.get("success"):
            return APIResponse(success=False, message="Failed to disable syslog", error=result.get("stderr", ""))

        log_activity("utmstack_syslog_disabled", {"agent_id": agent_id, "protocol": proto})
        return APIResponse(success=True, message=f"Syslog {proto.upper()} disabled on {agent_id}", data={
            "agent_id": agent_id, "protocol": proto, "output": result.get("stdout", ""),
        })
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to disable syslog", error=str(e))


# ===== SIEM-SPECIFIC ENDPOINTS =====

@app.get("/siem/{siem_type}/stats", response_model=APIResponse)
async def get_siem_stats(siem_type: str):
    """Get statistics for a specific SIEM type"""
    try:
        if siem_type not in ["wazuh", "ossec", "ossim", "utmstack", "elastic"]:
            raise HTTPException(status_code=400, detail=f"Invalid SIEM type: {siem_type}")
        requested_type = siem_type
        
        # Count agents for this SIEM
        agent_count = 0
        connected_count = 0
        
        for name in lxc.list_containers():
            try:
                container = lxc.Container(name)
                agent_info = get_agent_info(container)
                agent_siem = agent_info.get("siem_type")

                if not agent_siem:
                    detected = detect_siem_type(name)
                    if detected and detected != "unknown":
                        agent_siem = detected
                        write_agent_metadata(name, {"siem_type": detected})

                if agent_siem == requested_type:
                    agent_count += 1
                    connectivity = check_siem_connectivity(name)
                    if connectivity.get("status") == "connected":
                        connected_count += 1
            except Exception as e:
                logger.warning(f"Failed to inspect container {name}: {e}")
                continue
        
        return APIResponse(
            success=True,
            message=f"Stats for {requested_type} retrieved",
            data={
                "siem_type": requested_type,
                "total_agents": agent_count,
                "connected_agents": connected_count,
                "disconnected_agents": agent_count - connected_count,
                "connection_rate": round(connected_count / agent_count * 100, 2) if agent_count > 0 else 0
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        return APIResponse(success=False, message="Failed to get SIEM stats", error=str(e))

# ===== STATIC FILE SERVING (React frontend) =====

STATIC_DIR = Path(__file__).parent / "static"

if STATIC_DIR.is_dir():
    from fastapi.staticfiles import StaticFiles
    from starlette.responses import FileResponse as StarletteFileResponse

    # Serve built assets (JS, CSS, images)
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")

    @app.get("/{path:path}")
    async def serve_spa(path: str):
        """Serve the React SPA; fall back to index.html for client-side routing."""
        file = STATIC_DIR / path
        if file.is_file():
            return StarletteFileResponse(str(file))
        return StarletteFileResponse(str(STATIC_DIR / "index.html"))

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutdown complete")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9000)