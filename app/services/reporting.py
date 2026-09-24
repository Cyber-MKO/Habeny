"""
Report generation — metrics/findings aggregation and CSV/PDF rendering.
"""
import csv
import json
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.config import DB_PATH
from app.db import get_metric_summary
from app.state import simulations_db


def normalize_dt(value: datetime) -> datetime:
    """Normalize datetimes to timezone-aware UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def generate_report_csv(report_data: dict[str, Any], report_file: Path) -> None:
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


def generate_report_pdf(report_data: dict[str, Any], agent_status_counts: dict[str, int], report_file: Path) -> None:
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


def build_report_metrics(since: str) -> dict:
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


def build_report_findings(agents_by_status: dict) -> list:
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
