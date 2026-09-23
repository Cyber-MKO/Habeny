"""
Report generation, retrieval and download.
"""
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import lxc
from fastapi import APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse

from app.config import REPORTS_DIR
from app.models import APIResponse, ReportGenerateRequest, utc_now
from app.services.activity import log_activity
from app.services.agent_info import get_agent_info
from app.services.reporting import (
    build_report_findings,
    build_report_metrics,
    generate_report_csv,
    generate_report_pdf,
    normalize_dt,
)
from app.state import report_files, reports_db, simulations_db

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/reports/generate", response_model=APIResponse)
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
            "metrics": build_report_metrics(start_time.isoformat()),
            "findings": build_report_findings(agents_by_status)
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


@router.get("/reports/{report_id}", response_model=APIResponse)
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


@router.get("/reports/{report_id}/download")
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
