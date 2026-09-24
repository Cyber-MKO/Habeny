import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { useConfirm } from "../components/Confirm";
import { DataTable, Modal, PageHeader, Spinner } from "../components/UI";

const limitValue = (text) => (text === "" ? null : Math.max(0, Number(text)));

function TeamModal({ team, onClose, onSaved }) {
  const { toast } = useStore();
  const [form, setForm] = useState({
    name: team?.name || "", description: team?.description || "",
    max_containers: team?.max_containers ?? "",
  });
  const [error, setError] = useState(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const submit = async (e) => {
    e.preventDefault();
    const body = { name: form.name.trim(), description: form.description.trim() || null, max_containers: limitValue(form.max_containers) };
    try {
      const res = team ? await api.updateTeam(team.id, body) : await api.createTeam(body);
      toast(res.message, "success");
      onSaved();
      onClose();
    } catch (err) { setError(err.message); }
  };
  return (
    <Modal title={team ? `Edit ${team.name}` : "New team"} onClose={onClose}>
      <form className="account-modal-form" onSubmit={submit} noValidate>
        {error && <div className="auth-error" role="alert">{error}</div>}
        <div className="field">
          <label htmlFor="team-name">Name</label>
          <input id="team-name" className="input" value={form.name} onChange={set("name")} maxLength={64} />
        </div>
        <div className="field">
          <label htmlFor="team-desc">Description</label>
          <input id="team-desc" className="input" value={form.description} onChange={set("description")} maxLength={300} />
        </div>
        <div className="field">
          <label htmlFor="team-limit">Container limit</label>
          <input id="team-limit" className="input" type="number" min={0} value={form.max_containers} onChange={set("max_containers")} placeholder="No limit" />
          <span className="auth-hint">The most containers the team's members can have in total. Empty: no limit.</span>
        </div>
        <div className="btn-group">
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={!form.name.trim()}>Save</button>
        </div>
      </form>
    </Modal>
  );
}

function MemberRow({ user, teams, used, onSaved }) {
  const { toast } = useStore();
  const [teamId, setTeamId] = useState(user.team ? String(user.team.id) : "");
  const [limit, setLimit] = useState(user.max_containers ?? "");
  const changed = teamId !== (user.team ? String(user.team.id) : "") || String(limit) !== String(user.max_containers ?? "");
  const save = async () => {
    try {
      toast((await api.setUserTeam(user.id, { team_id: teamId ? Number(teamId) : null, max_containers: limitValue(limit) })).message, "success");
      onSaved();
    } catch (err) { toast(err.message, "error"); }
  };
  return (
    <tr>
      <th scope="row">{user.username} <span className="muted">({user.role})</span></th>
      <td>
        <select className="select" aria-label={`Team of ${user.username}`} value={teamId} onChange={(e) => setTeamId(e.target.value)}>
          <option value="">No team</option>
          {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
      </td>
      <td>
        <input className="input input-narrow" type="number" min={0} aria-label={`Container limit for ${user.username}`}
          value={limit} onChange={(e) => setLimit(e.target.value)} placeholder="No limit" />
      </td>
      <td>{used || 0}</td>
      <td><button className="btn btn-sm btn-primary" onClick={save} disabled={!changed}>Save</button></td>
    </tr>
  );
}

function MoveContainers({ teams, onMoved }) {
  const { toast } = useStore();
  const [agents, setAgents] = useState(null);
  const [selected, setSelected] = useState(new Set());
  const [target, setTarget] = useState("");
  const [filter, setFilter] = useState("");

  const load = useCallback(async () => {
    try { setAgents((await api.getAgents({ limit: 1000 })).data.agents); }
    catch (err) { toast(err.message, "error"); setAgents([]); }
  }, [toast]);
  useEffect(() => { load(); }, [load]);

  const teamName = (id) => teams.find((t) => t.id === id)?.name || "No team";
  const shown = (agents || []).filter((a) => a.agent_name.includes(filter.trim()));
  const toggle = (name) => setSelected((prev) => { const s = new Set(prev); if (s.has(name)) s.delete(name); else s.add(name); return s; });
  const move = async () => {
    try {
      const res = await api.assignToTeam({ team_id: target ? Number(target) : null, containers: [...selected] });
      toast(res.message, "success");
      setSelected(new Set());
      load();
      onMoved();
    } catch (err) { toast(err.message, "error"); }
  };

  return (
    <div className="card">
      <p className="account-help">
        Containers deployed from now on belong to the deploying user's team. Move existing ones (for example, those
        created before teams existed) here.
      </p>
      <div className="filters">
        <div className="field">
          <label htmlFor="move-filter">Filter by name</label>
          <input id="move-filter" className="input" type="search" value={filter} onChange={(e) => setFilter(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="move-target">Move to</label>
          <select id="move-target" className="select" value={target} onChange={(e) => setTarget(e.target.value)}>
            <option value="">No team</option>
            {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        </div>
        <div className="field filters-actions">
          <button className="btn btn-primary" onClick={move} disabled={!selected.size}>Move {selected.size || ""} selected</button>
        </div>
      </div>
      {agents === null ? <Spinner /> : (
        <div className="table-wrap table-scroll">
          <table>
            <caption className="sr-only">Containers and their team</caption>
            <thead><tr><th scope="col"><span className="sr-only">Select</span></th><th scope="col">Container</th><th scope="col">Team</th><th scope="col">Status</th></tr></thead>
            <tbody>
              {shown.map((a) => (
                <tr key={a.agent_name}>
                  <td><input type="checkbox" aria-label={`Select ${a.agent_name}`} checked={selected.has(a.agent_name)} onChange={() => toggle(a.agent_name)} /></td>
                  <td>{a.agent_name}</td>
                  <td>{teamName(a.team_id)}</td>
                  <td>{a.lifecycle_status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function Teams() {
  const { toast } = useStore();
  const confirm = useConfirm();
  const [data, setData] = useState(null);
  const [users, setUsers] = useState([]);
  const [editing, setEditing] = useState(null);

  const load = useCallback(async () => {
    try {
      const [t, u] = await Promise.all([api.getTeams(), api.getUsers()]);
      setData(t.data);
      setUsers(u.data.users);
    } catch (err) { toast(err.message, "error"); setData({ teams: [], user_usage: {} }); }
  }, [toast]);
  useEffect(() => { load(); }, [load]);

  const remove = async (t) => {
    if (!(await confirm({
      title: `Delete team ${t.name}?`,
      message: `Its ${t.members} member(s) and ${t.containers} container(s) will have no team. Nothing is deleted.`,
      confirmLabel: "Delete team", danger: true,
    }))) return;
    try { toast((await api.deleteTeam(t.id)).message, "success"); load(); }
    catch (err) { toast(err.message, "error"); }
  };

  const teams = useMemo(() => data?.teams || [], [data]);
  const columns = [
    { key: "name", label: "Team", render: (t) => <><strong>{t.name}</strong>{t.description && <div className="muted">{t.description}</div>}</> },
    { key: "members", label: "Members" },
    { key: "containers", label: "Containers", render: (t) => `${t.containers}${t.max_containers !== null ? ` of ${t.max_containers}` : ""}` },
    { key: "actions", label: <span className="sr-only">Actions</span>, render: (t) => (
      <div className="btn-group">
        <button className="btn btn-sm btn-secondary" onClick={() => setEditing(t)} aria-label={`Edit ${t.name}`}>Edit</button>
        <button className="btn btn-sm btn-danger" onClick={() => remove(t)} aria-label={`Delete ${t.name}`}>Delete</button>
      </div>
    ) },
  ];

  return (
    <>
      <PageHeader title="Teams" subtitle="Separate teams or customers, and cap how many containers they run">
        <button className="btn btn-primary" onClick={() => setEditing("new")}>New team</button>
      </PageHeader>
      <p className="account-help">
        Members of a team see and manage only their team's containers, simulations and reports; people without a team
        see containers that belong to no team. Admins see everything. Profiles, groups and templates are shared.
      </p>
      <section className="section" aria-labelledby="teams-list">
        <h2 className="section-title" id="teams-list">Teams</h2>
        <div className="card">{data === null ? <Spinner /> : <DataTable columns={columns} rows={teams} emptyMsg="No teams yet: everyone shares all containers." />}</div>
      </section>
      <section className="section" aria-labelledby="teams-members">
        <h2 className="section-title" id="teams-members">Members and personal limits</h2>
        <div className="card table-wrap">
          <table>
            <thead><tr><th scope="col">User</th><th scope="col">Team</th><th scope="col">Personal limit</th><th scope="col">Containers</th><th scope="col"><span className="sr-only">Save</span></th></tr></thead>
            <tbody>
              {users.map((u) => (
                <MemberRow key={`${u.id}-${u.team?.id}-${u.max_containers}`} user={u} teams={teams} used={data?.user_usage?.[u.id]} onSaved={load} />
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="section" aria-labelledby="teams-move">
        <h2 className="section-title" id="teams-move">Move containers between teams</h2>
        {data && <MoveContainers teams={teams} onMoved={load} />}
      </section>
      {editing && <TeamModal team={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={load} />}
    </>
  );
}
