import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { useAuth } from "../auth";
import { NavLink } from "react-router-dom";
import { Details } from "../components/Details";
import { Empty, PageHeader, Pill, Spinner } from "../components/UI";
import { formatDateTime, t } from "../i18n";

const PROMETHEUS = (origin) => `scrape_configs:
  - job_name: habeny
    scheme: ${origin.startsWith("https") ? "https" : "http"}
    tls_config: {insecure_skip_verify: true}   # only with Habeny's self-signed certificate
    authorization: {credentials_file: /etc/prometheus/habeny.token}
    static_configs: [{targets: ["${origin.replace(/^https?:\/\//, "")}"]}]`;

const RULES = `groups:
  - name: habeny
    rules:
      - alert: HabenyDown
        expr: up{job="habeny"} == 0
        for: 2m
      - alert: HabenyAlert        # anything Habeny itself raises (disk, LXC, backups, deploys)
        expr: habeny_alerts_active == 1
        labels: {severity: "{{ $labels.severity }}"}
        annotations: {summary: "Habeny: {{ $labels.alert }} {{ $labels.target }}"}
      - alert: HabenyDeploymentsFailing
        expr: increase(habeny_containers_deployed_total{result="failure"}[1h]) > 0
      - alert: HabenyNoRecentBackup
        expr: time() - habeny_backup_last_timestamp_seconds > 2 * 86400`;

export default function Monitoring() {
  const { user } = useAuth();
  const { toast } = useStore();
  const [alerts, setAlerts] = useState(null);

  const load = useCallback(async () => {
    try { setAlerts((await api.getAlerts()).data.alerts); }
    catch (err) { toast(err.message, "error"); setAlerts([]); }
  }, [toast]);
  useEffect(() => {
    load();
    const timer = setInterval(load, 30000);
    return () => clearInterval(timer);
  }, [load]);

  const origin = window.location.origin;
  return (
    <>
      <PageHeader title={t("Monitoring")} subtitle={t("Alerts, health checks and metrics for external monitoring")}>
        <button className="btn btn-secondary" onClick={load}>{t("Refresh")}</button>
      </PageHeader>

      <section className="section" aria-labelledby="alerts-title">
        <h2 className="section-title" id="alerts-title">{t("Active alerts")}</h2>
        <div className="card">
          {alerts === null ? <Spinner /> : !alerts.length ? <Empty message={t("No active alerts. Disk space, LXC, backups and deployments are fine.")} /> : (
            <ul className="alert-list">
              {alerts.map((a) => (
                <li key={`${a.name}:${a.target || ""}`} className={`alert-item alert-${a.severity}`}>
                  <div className="alert-head">
                    <Pill status={a.severity} />
                    <strong>{a.label}{a.target ? ` (${a.target})` : ""}</strong>
                    <span className="muted">{t("since")} {formatDateTime(a.since)}</span>
                  </div>
                  <p>{a.message}</p>
                  {Object.keys(a.details || {}).length > 0 && <Details data={a.details} />}
                </li>
              ))}
            </ul>
          )}
        </div>
        {user.is_admin && (
          <p className="account-help">
            {t("Alerts are also sent to")} <NavLink to="/notifications">{t("notification channels")}</NavLink> {t("when they start and clear.")}
          </p>
        )}
      </section>

      <section className="section" aria-labelledby="endpoints-title">
        <h2 className="section-title" id="endpoints-title">{t("Endpoints for monitoring systems")}</h2>
        <div className="card">
          <dl className="details">
            <div className="details-row"><dt><code>GET /api/healthz</code></dt><dd>{t("Liveness: 200 while the server answers. No sign-in.")}</dd></div>
            <div className="details-row"><dt><code>GET /api/readyz</code></dt><dd>{t("Readiness: 200 when the database, LXC and disk are fine, 503 otherwise. No sign-in.")}</dd></div>
            <div className="details-row"><dt><code>GET /api/metrics</code></dt><dd>{t("Prometheus metrics. Needs an API token (the viewer role is enough).")}</dd></div>
          </dl>
        </div>
      </section>

      <section className="section" aria-labelledby="prom-title">
        <h2 className="section-title" id="prom-title">Prometheus</h2>
        <div className="card">
          <p className="account-help">
            {t("Create a viewer")} <NavLink to="/account">{t("API token")}</NavLink>{t(", save it in")} <code>/etc/prometheus/habeny.token</code>{t(", then scrape:")}
          </p>
          <pre className="code-sample" tabIndex={0} aria-label={t("Prometheus scrape configuration")}>{PROMETHEUS(origin)}</pre>
          <p className="account-help">{t("Example alerting rules:")}</p>
          <pre className="code-sample" tabIndex={0} aria-label={t("Example alerting rules")}>{RULES}</pre>
        </div>
      </section>
    </>
  );
}
