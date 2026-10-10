import { FormEvent, useState } from "react";
import { Check as CheckIcon, Download, Loader2, RefreshCw, X } from "lucide-react";
import { api } from "../api";
import { useApp } from "../App";
import { Busy, Check, Field, fmtAgo, fmtBytes, fmtDateTime, Loading, Modal, ROLE, Seg, Status, useAction, useLoad, useUi } from "../ui";

export default function Maintenance() {
  const [tab, setTab] = useState<"updates" | "backups">("updates");
  return (
    <div className="stack">
      <div className="page-head" style={{ marginBottom: 0 }}>
        <div><h1>Onderhoud</h1><p>RouterOS bijwerken en configuraties bewaren.</p></div>
        <Seg value={tab} onChange={setTab} options={[["updates", "Updates"], ["backups", "Back-ups"]]} />
      </div>
      {tab === "updates" ? <Updates /> : <Backups />}
    </div>
  );
}

function Updates() {
  const { site } = useApp();
  const u = useLoad(() => api.get(`/api/sites/${site.id}/updates`), [site.id], 5000);
  const { busy, run } = useAction();
  const { confirm } = useUi();
  if (!u.data) return <Loading error={u.error} />;
  const devs: any[] = u.data.devices, job = u.data.job;
  const avail = devs.filter((d) => d.available && d.online);
  const hasRouter = avail.some((d) => d.role === "router");

  const check = () => run("check", async () => { await api.post(`/api/sites/${site.id}/updates/check`); u.reload(); }, "Gecontroleerd op updates");
  const all = async () => {
    if (await confirm({ title: `${avail.length} ${avail.length === 1 ? "apparaat" : "apparaten"} bijwerken?`, action: "Alles bijwerken", danger: true,
      text: <>De apparaten worden één voor één bijgewerkt en herstart: eerst access points, dan switches, als laatste de router. Mislukt er één, dan stopt de ronde.
        {hasRouter && <strong> Tijdens de herstart van de router is er een paar minuten geen internet.</strong>} Maak eerst een back-up als je die nog niet hebt.</> }))
      run("all", async () => { await api.post(`/api/sites/${site.id}/updates/all`); u.reload(); });
  };
  const one = async (d: any) => {
    if (await confirm({ title: `${d.name} bijwerken naar ${d.latest}?`, action: "Bijwerken", danger: true,
      text: d.role === "router" ? "De router downloadt de update en herstart. Het netwerk is een paar minuten zonder internet." : "Het apparaat downloadt de update en herstart. Alles wat erop is aangesloten valt kort weg." }))
      run(`up${d.id}`, async () => { await api.post(`/api/devices/${d.id}/upgrade`); u.reload(); }, "Update gestart");
  };
  const fw = async (d: any) => {
    if (await confirm({ title: `Firmware van ${d.name} bijwerken?`, action: "Bijwerken en herstarten", danger: true,
      text: `RouterBOOT gaat van ${d.firmware} naar ${d.firmware_target}. Daarvoor herstart het apparaat één keer.` }))
      run(`fw${d.id}`, async () => { await api.post(`/api/devices/${d.id}/firmware`); u.reload(); }, "Firmware-update gestart");
  };

  return (
    <>
      {job && (
        <section className="panel">
          <header><h2>{job.running ? "Update-ronde bezig" : job.error ? "Update-ronde gestopt" : "Update-ronde klaar"}</h2>
            <span className="muted small">{job.steps.filter((s: any) => s.status === "klaar").length} van {job.total} klaar</span></header>
          <div className="body">
            {job.error && <div className="banner bad" style={{ marginBottom: 10 }}>{job.error}. De overige apparaten zijn niet aangeraakt.</div>}
            <ul className="steps">{job.steps.map((s: any, i: number) => (
              <li key={i}>{s.status === "bezig" ? <Loader2 size={16} className="spin" /> : s.status === "klaar" ? <CheckIcon size={16} color="var(--ok)" /> : <X size={16} color="var(--bad)" />}
                <div><span className="strong">{s.device}</span> <span className="muted">{s.from} naar {s.to}</span>{s.error && <code>{s.error}</code>}</div></li>
            ))}</ul>
          </div>
        </section>
      )}
      <section className="panel">
        <header><h2>RouterOS</h2>
          <div className="row">
            <button className="btn sm" onClick={check} disabled={!!busy}><Busy on={busy === "check"}><RefreshCw size={14} />Controleren op updates</Busy></button>
            <button className="btn sm primary" onClick={all} disabled={!!busy || !avail.length || job?.running}>Alles bijwerken</button>
          </div></header>
        <div className="table-wrap"><table className="t">
          <thead><tr><th>Apparaat</th><th>Kanaal</th><th>Geïnstalleerd</th><th>Nieuwste</th><th>Firmware</th><th>Gecontroleerd</th><th /></tr></thead>
          <tbody>{devs.map((d) => (
            <tr key={d.id} className={d.online === false ? "off" : ""}>
              <td><span className="strong">{d.name}</span><div className="muted small">{[d.board, ROLE[d.role]].filter(Boolean).join(", ")}</div></td>
              <td>{d.channel ?? "–"}</td>
              <td className="num">{d.installed ?? "–"}</td>
              <td className="num">{d.latest ? (d.available ? <span className="tag accent">{d.latest}</span> : <span className="muted">actueel</span>) : <span className="muted">onbekend</span>}</td>
              <td className="num">{d.firmware ?? "–"}{d.firmware_pending && <div><button className="btn sm" style={{ marginTop: 4 }} disabled={!!busy || !!d.busy || !d.online} onClick={() => fw(d)}>Naar {d.firmware_target}</button></div>}</td>
              <td className="small muted nowrap">{d.checked ? fmtAgo(d.checked) : "nog niet"}</td>
              <td className="right">{d.busy || d.online === false ? <Status online={d.online} busy={d.busy} />
                : d.available ? <button className="btn sm" disabled={!!busy || job?.running} onClick={() => one(d)}>Bijwerken</button> : null}</td>
            </tr>
          ))}</tbody>
        </table></div>
      </section>
      <p className="muted small">De router haalt updates zelf op bij MikroTik, uit het kanaal dat op het apparaat is ingesteld. Na een RouterOS-update staat er meestal ook nieuwe RouterBOOT-firmware klaar.</p>
    </>
  );
}

function Backups() {
  const { site, reloadSites } = useApp();
  const b = useLoad<any[]>(() => api.get(`/api/sites/${site.id}/backups`), [site.id], 30000);
  const [view, setView] = useState<{ dev: any; backup: any; prev: any | null } | null>(null);
  const { busy, run } = useAction();
  const [s, setS] = useState({ backup_enabled: site.settings.backup_enabled, backup_hour: site.settings.backup_hour, backup_keep: site.settings.backup_keep, backup_sensitive: site.settings.backup_sensitive });
  const set = (k: string, v: any) => setS((o) => ({ ...o, [k]: v }));
  if (!b.data) return <Loading error={b.error} />;

  const now = () => run("now", async () => {
    const res: any[] = await api.post(`/api/sites/${site.id}/backups`);
    const failed = res.filter((r) => r.error);
    b.reload();
    if (failed.length) throw new Error(`Mislukt voor ${failed.map((f) => f.name).join(", ")}: ${failed[0].error}`);
  }, "Back-up gemaakt. Ongewijzigde configuraties worden niet dubbel bewaard.");
  const save = (e: FormEvent) => { e.preventDefault(); run("save", async () => { await api.patch(`/api/sites/${site.id}`, { settings: s }); reloadSites(); }, "Schema opgeslagen"); };

  return (
    <>
      <section className="panel">
        <header><h2>Configuraties</h2><button className="btn sm primary" onClick={now} disabled={!!busy}><Busy on={busy === "now"}>Nu een back-up maken</Busy></button></header>
        {b.data.length === 0 ? <div className="empty">Nog geen apparaten.</div> : b.data.map((dev) => (
          <div key={dev.device_id} style={{ borderBottom: "1px solid var(--line-soft)" }}>
            <div className="spread" style={{ padding: "12px 16px 4px" }}><h3>{dev.name}</h3><span className="muted small">{dev.backups.length} {dev.backups.length === 1 ? "versie" : "versies"}</span></div>
            {dev.backups.length === 0 ? <div className="muted small" style={{ padding: "0 16px 12px" }}>Nog geen back-up.</div> : (
              <div className="table-wrap fit"><table className="t"><tbody>{dev.backups.slice(0, 6).map((bk: any, i: number) => (
                <tr key={bk.id} className="click" onClick={() => setView({ dev, backup: bk, prev: dev.backups[i + 1] ?? null })}>
                  <td className="nowrap">{fmtDateTime(bk.ts)}</td>
                  <td className="muted small">{bk.trigger === "schedule" ? "gepland" : "handmatig"}</td>
                  <td className="muted small num">RouterOS {bk.ros_version || "?"}</td>
                  <td className="muted small num right">{fmtBytes(bk.size)}</td>
                  <td className="right"><a className="btn icon" href={`/api/backups/${bk.id}?download=true`} onClick={(e) => e.stopPropagation()} aria-label="Download"><Download size={16} /></a></td>
                </tr>
              ))}</tbody></table></div>
            )}
          </div>
        ))}
      </section>

      <section className="panel">
        <header><h2>Schema</h2></header>
        <form className="body form" onSubmit={save}>
          <Check checked={s.backup_enabled} onChange={(v) => set("backup_enabled", v)} label="Elke nacht een back-up maken"
            hint="Een export (.rsc) per apparaat. Er komt alleen een nieuwe versie bij als de configuratie is veranderd." />
          <div className="two">
            <Field label="Tijdstip (uur)"><input className="input" type="number" min={0} max={23} value={s.backup_hour} onChange={(e) => set("backup_hour", Number(e.target.value))} /></Field>
            <Field label="Versies bewaren per apparaat"><input className="input" type="number" min={1} max={365} value={s.backup_keep} onChange={(e) => set("backup_keep", Number(e.target.value))} /></Field>
          </div>
          <Check checked={s.backup_sensitive} onChange={(v) => set("backup_sensitive", v)} label="Wachtwoorden en sleutels meenemen (show-sensitive)"
            hint="Nodig om een router volledig te herstellen. De bestanden staan dan onversleuteld in de data-map van TikControl." />
          <div><button className="btn primary" disabled={!!busy}>Schema opslaan</button></div>
        </form>
      </section>
      {view && <BackupView {...view} onClose={() => setView(null)} onDeleted={() => { setView(null); b.reload(); }} />}
    </>
  );
}

function BackupView({ dev, backup, prev, onClose, onDeleted }: { dev: any; backup: any; prev: any | null; onClose: () => void; onDeleted: () => void }) {
  const [mode, setMode] = useState<"diff" | "full">(prev ? "diff" : "full");
  const diff = useLoad(() => (prev ? api.get(`/api/backups/${backup.id}/diff/${prev.id}`) : Promise.resolve(null)), [backup.id]);
  const full = useLoad(() => api.get(`/api/backups/${backup.id}`), [backup.id]);
  const { busy, run } = useAction();
  return (
    <Modal wide title={`${dev.name}, ${fmtDateTime(backup.ts)}`} onClose={onClose}
      footer={<><button className="btn danger" style={{ marginRight: "auto" }} disabled={!!busy} onClick={() => run("del", async () => { await api.del(`/api/backups/${backup.id}`); onDeleted(); }, "Versie verwijderd")}>Verwijderen</button>
        <a className="btn" href={`/api/backups/${backup.id}?download=true`}><Download size={15} />Download .rsc</a>
        <button className="btn primary" onClick={onClose}>Sluiten</button></>}>
      <div className="spread" style={{ marginBottom: 12, flexWrap: "wrap" }}>
        {prev ? <Seg value={mode} onChange={setMode} options={[["diff", "Wijzigingen"], ["full", "Volledig"]]} /> : <span className="muted">Eerste versie, dus nog niets om mee te vergelijken.</span>}
        {mode === "diff" && diff.data && <span className="muted small">{diff.data.added} regels erbij, {diff.data.removed} eraf sinds {fmtDateTime(prev.ts)}</span>}
      </div>
      {mode === "diff" ? (!diff.data ? <Loading error={diff.error} /> : diff.data.lines.length === 0 ? <p className="muted">Geen verschillen.</p> : (
        <div className="diff">{diff.data.lines.map((l: any, i: number) => <div key={i} className={l.kind}>{l.kind === "add" ? "+ " : l.kind === "del" ? "- " : l.kind === "hunk" ? "" : "  "}{l.text}</div>)}</div>
      )) : (!full.data ? <Loading error={full.error} /> : <div className="diff">{full.data.text.split("\n").map((l: string, i: number) => <div key={i}>{l || " "}</div>)}</div>)}
    </Modal>
  );
}
