-- Database as created by Habeny's init_db at v0-initial, with sample rows
BEGIN TRANSACTION;
CREATE TABLE agents (
                agent_name TEXT PRIMARY KEY,
                seq_id INTEGER UNIQUE NOT NULL,
                siem_type TEXT,
                siem_ip TEXT,
                siem_version TEXT,
                agent_group TEXT,
                os_type TEXT,
                config_template_id TEXT,
                lifecycle_status TEXT,
                state TEXT,
                init_pid INTEGER,
                ip_addresses TEXT,
                siem_agent_status TEXT,
                siem_agent_running INTEGER,
                siem_agent_last_check TEXT,
                manager_host TEXT,
                manager_port TEXT,
                manager_status TEXT,
                manager_reachable INTEGER,
                created_at TEXT,
                updated_at TEXT,
                deleted_at TEXT
            );
INSERT INTO "agents" VALUES('legacy-0001',1,'wazuh',NULL,NULL,NULL,NULL,NULL,'running',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'2025-01-01','2025-01-01',NULL);
CREATE TABLE benchmark_bottlenecks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                benchmark_id TEXT NOT NULL,
                phase INTEGER DEFAULT 0,
                severity TEXT NOT NULL,
                component TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                threshold REAL,
                actual_value REAL,
                recommendation TEXT,
                first_seen TEXT,
                occurrences INTEGER DEFAULT 1
            );
CREATE TABLE benchmark_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                benchmark_id TEXT NOT NULL,
                phase INTEGER DEFAULT 0,
                category TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                value REAL NOT NULL,
                tags TEXT,
                recorded_at TEXT NOT NULL
            );
CREATE TABLE benchmarks (
                benchmark_id TEXT PRIMARY KEY,
                scenario_id TEXT NOT NULL,
                name TEXT,
                siem_type TEXT DEFAULT 'none',
                status TEXT DEFAULT 'pending',
                config TEXT,
                phases TEXT,
                current_phase INTEGER DEFAULT 0,
                results TEXT,
                started_at TEXT,
                completed_at TEXT,
                created_at TEXT
            );
CREATE TABLE groups (
                name TEXT PRIMARY KEY,
                description TEXT,
                created_at TEXT,
                updated_at TEXT
            );
INSERT INTO "groups" VALUES('legacy-group',NULL,'2025-01-01','2025-01-01');
CREATE TABLE managers (
                manager_id TEXT PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                description TEXT,
                siem_type TEXT NOT NULL,
                siem_ip TEXT,
                siem_version TEXT,
                siem_auth_key TEXT,
                os_type TEXT DEFAULT 'ubuntu_22_04',
                agent_group TEXT DEFAULT 'default',
                memory_limit TEXT DEFAULT '512MB',
                cpu_shares INTEGER DEFAULT 1024,
                config_template_id TEXT,
                created_at TEXT,
                updated_at TEXT
            );
CREATE TABLE meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
CREATE TABLE metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                metric_type TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                value REAL NOT NULL,
                tags TEXT,
                recorded_at TEXT NOT NULL
            );
CREATE TABLE syslog_configs (
                config_id TEXT PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                description TEXT,
                manager_profile_id TEXT,
                target_ip TEXT NOT NULL,
                target_port INTEGER DEFAULT 514,
                protocol TEXT DEFAULT 'tcp',
                siem_type TEXT,
                enabled INTEGER DEFAULT 1,
                created_at TEXT,
                updated_at TEXT
            );
CREATE INDEX idx_bm_metrics_bid ON benchmark_metrics(benchmark_id);
CREATE INDEX idx_bm_metrics_time ON benchmark_metrics(recorded_at);
CREATE INDEX idx_bm_bottlenecks_bid ON benchmark_bottlenecks(benchmark_id);
CREATE INDEX idx_metrics_type ON metrics(metric_type);
CREATE INDEX idx_metrics_time ON metrics(recorded_at);
CREATE INDEX idx_agents_seq_id ON agents(seq_id);
CREATE INDEX idx_agents_siem_type ON agents(siem_type);
CREATE INDEX idx_agents_group ON agents(agent_group);
DELETE FROM "sqlite_sequence";
COMMIT;
