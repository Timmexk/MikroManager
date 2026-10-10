import { FormEvent, useState } from "react";
import { ArrowLeft, Pencil, Plus, Power, Trash2 } from "lucide-react";
import { api } from "../api";
import { useApp } from "../App";
import { Faceplate, LineChart, Port } from "../components";
import { bps, Busy, Check, Field, fmtAgo, fmtUptime, Loading, Meter, Modal, ROLE, Status, useAction, useLoad, useUi } from "../ui";

export default function Devices({ deviceId }: { deviceId: number | null }) {
  return deviceId ? <Detail id={deviceId} /> : <List />;
}

function List() {
  const { site, reloadSites } = useApp();
  const list = useLoad<any[]>(() => api.get(`/api/sites/${site.id}/devices`), [site.id], 10000);
  const [adding, setAdding] = useState(false);
  if (!list.data) return <Loading error={list.error} />;
  return (
    <>
      <div className="page-head">
        <div><h1>Apparaten</h1><p>Routers, switches en access points op {site.name}.</p></div>
        <button className="btn primary" onClick={() => setAdding(true)}><Plus size={16} />Apparaat toevoegen</button>
      </div>
      <div className="panel">
        {list.data.length === 0 ? (
          <div className="empty"><h3>Voeg eerst je router toe</h3>
            <p>TikControl praat met RouterOS 7 via de REST API. Zet op de router de service <span className="mono">www-ssl</span> aan en maak een gebruiker voor TikControl.</p>
            <button className="btn primary" onClick={() => setAdding(true)}>Router toevoegen</button></div>
        ) : (
          <div className="table-wrap"><table className="t">
            <thead><tr><th>Naam</th><th>Model</th><th>Adres</th><th>RouterOS</th><th>Uptime</th><th>CPU</th><th>Geheugen</th><th>Status</th></tr></thead>
            <tbody>{list.data.map((d) => (
              <tr key={d.id} className={`click ${d.online === false ? "off" : ""}`} onClick={() => (location.hash = `#/devices/${d.id}`)}>
                <td><a className="strong" href={`#/devices/${d.id}`} style={{ color: "inherit" }}>{d.name}</a>
                  <div className="muted small">{ROLE[d.role]}{d.is_controller ? ", wifi-controller" : ""}</div></td>
                <td>{d.board ?? "–"}</td>
                <td className="mono">{d.host}{[80, 443].includes(d.port) ? "" : `:${d.port}`}</td>
                <td className="num">{d.version ?? "–"}{d.update_available && <span className="tag accent" style={{ marginLeft: 8 }}>Update</span>}</td>
                <td className="nowrap">{fmtUptime(d.uptime)}</td>
                <td><Meter value={d.cpu} /></td>
                <td><Meter value={d.mem} /></td>
                <td><Status online={d.online} busy={d.busy} />{d.online === false && d.error && <div className="small muted" style={{ marginTop: 3 }}>{d.error}</div>}</td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </div>
      {adding && <DeviceForm siteId={site.id} hasRouter={list.data.some((d) => d.role === "router")} onClose={() => setAdding(false)}
        onSaved={() => { setAdding(false); list.reload(); reloadSites(); }} />}
    </>
  );
}

export function DeviceForm({ siteId, device, hasRouter, onClose, onSaved }: { siteId: number; device?: any; hasRouter?: boolean; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({
    host: device?.host ?? "", scheme: device?.scheme ?? "https", port: device?.port ?? "", username: device?.username ?? "tikcontrol",
    password: "", role: device?.role ?? (hasRouter ? "ap" : "router"), name: device?.name ?? "", verify_tls: device?.verify_tls ?? false,
  });
  const set = (k: string, v: any) => setF((o) => ({ ...o, [k]: v }));
  const { busy, run } = useAction();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const body = { ...f, port: f.port ? Number(f.port) : undefined };
    run("save", async () => {
      if (device) await api.patch(`/api/devices/${device.id}`, body);
      else await api.post(`/api/sites/${siteId}/devices`, body);
      onSaved();
    }, device ? "Apparaat opgeslagen" : "Apparaat toegevoegd");
  };
  return (
    <Modal title={device ? `${device.name} bewerken` : "Apparaat toevoegen"} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Annuleren</button>
        <button className="btn primary" form="devform" disabled={!!busy}><Busy on={!!busy}>{device ? "Opslaan" : "Verbinden en toevoegen"}</Busy></button></>}>
      <form id="devform" className="form" onSubmit={submit}>
        <div className="two">
          <Field label="IP-adres of hostnaam"><input className="input" value={f.host} onChange={(e) => set("host", e.target.value)} placeholder="192.168.88.1" required autoFocus /></Field>
          <Field label="Rol">
            <select className="input" value={f.role} onChange={(e) => set("role", e.target.value)}>
              <option value="router">Router</option><option value="switch">Switch</option><option value="ap">Access point</option>
            </select>
          </Field>
        </div>
        <div className="two">
          <Field label="Verbinding" hint={f.scheme === "http" ? "Zonder versleuteling is het wachtwoord op het netwerk te onderscheppen." : "REST API via de service www-ssl."}>
            <select className="input" value={f.scheme} onChange={(e) => set("scheme", e.target.value)}>
              <option value="https">HTTPS (www-ssl)</option><option value="http">HTTP (www)</option>
            </select>
          </Field>
          <Field label="Poort"><input className="input" value={f.port} onChange={(e) => set("port", e.target.value)} placeholder={f.scheme === "https" ? "443" : "80"} inputMode="numeric" /></Field>
        </div>
        <div className="two">
          <Field label="Gebruikersnaam"><input className="input" value={f.username} onChange={(e) => set("username", e.target.value)} required autoComplete="off" /></Field>
          <Field label="Wachtwoord" hint={device ? "Leeg laten om het huidige te houden." : "Wordt versleuteld opgeslagen."}>
            <input className="input" type="password" value={f.password} onChange={(e) => set("password", e.target.value)} autoComplete="new-password" /></Field>
        </div>
        <Field label="Naam in TikControl" hint="Leeg laten om de identity van het apparaat over te nemen.">
          <input className="input" value={f.name} onChange={(e) => set("name", e.target.value)} /></Field>
        {f.scheme === "https" && <Check checked={f.verify_tls} onChange={(v) => set("verify_tls", v)} label="Certificaat controleren"
          hint="Laat uit bij het zelfondertekende certificaat van de router." />}
      </form>
    </Modal>
  );
}

function Detail({ id }: { id: number }) {
  const { site } = useApp();
  const { confirm } = useUi();
  const d = useLoad(() => api.get(`/api/devices/${id}`), [id], 8000);
  const [sel, setSel] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const { busy, run } = useAction();
  if (!d.data) return <><a href="#/devices" className="row small"><ArrowLeft size={15} />Apparaten</a><Loading error={d.error} /></>;
  const v = d.data;
  const port: Port | undefined = v.ports.find((p: Port) => p.name === sel);

  const reboot = async () => {
    if (await confirm({ title: `${v.name} herstarten?`, action: "Herstarten", danger: true,
      text: v.role === "router" ? "Het hele netwerk is ongeveer een minuut zonder internet." : "Alles wat op dit apparaat is aangesloten valt ongeveer een minuut weg." }))
      run("reboot", () => api.post(`/api/devices/${id}/reboot`), "Herstart gestart");
  };
  const remove = async () => {
    if (await confirm({ title: `${v.name} verwijderen?`, action: "Verwijderen", danger: true,
      text: "Het apparaat verdwijnt uit TikControl, samen met de bewaarde back-ups. Aan de configuratie op het apparaat zelf verandert niets." }))
      run("del", async () => { await api.del(`/api/devices/${id}`); location.hash = "#/devices"; }, "Apparaat verwijderd");
  };
  const adopt = async () => {
    if (await confirm({ title: `${v.name} koppelen aan de controller?`, action: "Koppelen",
      text: "De radio's van dit apparaat worden voortaan door de controller ingesteld (CAPsMAN). De huidige wifi-instellingen op het apparaat zelf vervallen; clients verbinden opnieuw." }))
      run("adopt", async () => { await api.post(`/api/devices/${id}/adopt`); d.reload(); }, "Gekoppeld. De radio's verschijnen zo onder Wifi.");
  };
  const release = async () => {
    if (await confirm({ title: `${v.name} loskoppelen?`, action: "Loskoppelen", danger: true,
      text: "De radio's worden weer lokaal beheerd en zenden niets uit totdat je ze op het apparaat zelf instelt." }))
      run("release", async () => { await api.post(`/api/devices/${id}/release`); d.reload(); }, "Losgekoppeld");
  };

  return (
    <div className="stack">
      <a href="#/devices" className="row small" style={{ width: "fit-content" }}><ArrowLeft size={15} />Apparaten</a>
      <div className="page-head" style={{ marginBottom: 0 }}>
        <div>
          <div className="row"><h1>{v.name}</h1><Status online={v.online} busy={v.busy} /></div>
          <p>{[v.board, ROLE[v.role] + (v.is_controller ? " en wifi-controller" : ""), v.host].filter(Boolean).join(", ")}</p>
        </div>
        <div className="row wrap">
          <button className="btn" onClick={() => setEditing(true)}><Pencil size={15} />Bewerken</button>
          <button className="btn" onClick={reboot} disabled={!v.online || !!busy}><Power size={15} />Herstarten</button>
          <button className="btn danger" onClick={remove} disabled={!!busy}><Trash2 size={15} />Verwijderen</button>
        </div>
      </div>
      {v.online === false && <div className="banner bad"><strong>Niet bereikbaar.</strong> {v.error} Laatst gezien: {fmtAgo(v.last_seen)}.</div>}

      {v.ports.length > 0 && (
        <section className="panel">
          <header><h2>Poorten</h2>
            <span className="muted small">{v.ports.filter((p: Port) => p.running).length} van {v.ports.length} met link{v.poe_total != null ? `, ${v.poe_total} W PoE` : ""}</span></header>
          <div className="body" style={{ display: "grid", gap: 16 }}>
            <Faceplate ports={v.ports} selected={sel} onSelect={(n) => setSel(sel === n ? null : n)} />
            {port ? <PortPanel deviceId={id} port={port} onChange={d.reload} /> : <span className="muted small">Kies een poort voor snelheid, verkeer en instellingen.</span>}
          </div>
        </section>
      )}

      <div className="cols">
        <section className="panel">
          <header><h2>Belasting</h2><span className="muted small">laatste 6 uur</span></header>
          <div className="body">
            <LineChart title="CPU en geheugen" data={v.history} max={100} height={190} fmt={(n) => `${Math.round(n)}%`}
              series={[{ key: "cpu", label: "CPU", color: "var(--s1)", area: true }, { key: "mem", label: "Geheugen", color: "var(--s2)" }]} />
          </div>
        </section>
        <section className="panel">
          <header><h2>Gegevens</h2></header>
          <div className="body">
            <dl className="kv">
              <dt>Identity</dt><dd>{v.identity ?? "–"}</dd>
              <dt>Model</dt><dd>{v.model ?? v.board ?? "–"}</dd>
              <dt>Serienummer</dt><dd className="mono">{v.serial ?? "–"}</dd>
              <dt>RouterOS</dt><dd>{v.version ?? "–"}{v.update?.available && <> <a href="#/maintenance" className="tag accent">{v.update.latest} beschikbaar</a></>}</dd>
              <dt>Firmware</dt><dd>{v.update?.firmware ?? "–"}{v.update?.firmware_pending && <> <a href="#/maintenance" className="tag warn">{v.update.firmware_target} klaar om te installeren</a></>}</dd>
              <dt>Uptime</dt><dd>{fmtUptime(v.uptime)}</dd>
              {v.temperature && <><dt>Temperatuur</dt><dd>{v.temperature} °C</dd></>}
              {v.voltage && <><dt>Voeding</dt><dd>{v.voltage} V</dd></>}
              <dt>Verbinding</dt><dd className="mono">{v.scheme}://{v.host}:{v.port}</dd>
            </dl>
          </div>
        </section>
      </div>

      {v.has_wifi && !v.is_controller && (
        <section className="panel">
          <header><h2>Wifi-beheer</h2>{v.cap_enabled ? <span className="tag ok">Gekoppeld aan controller</span> : <span className="tag">Zelfstandig</span>}</header>
          <div className="body spread" style={{ flexWrap: "wrap" }}>
            <p className="muted" style={{ maxWidth: "62ch" }}>
              {v.cap_enabled
                ? "De radio's krijgen hun wifi-netwerken, kanalen en wachtwoorden van de controller. Je beheert ze onder Wifi."
                : "Koppel dit apparaat aan de controller om de wifi-netwerken van deze site erop uit te zenden. TikControl zet CAP-modus aan en draagt de radio's over."}
            </p>
            {v.cap_enabled
              ? <button className="btn" onClick={release} disabled={!!busy || !v.online}>Loskoppelen</button>
              : <button className="btn primary" onClick={adopt} disabled={!!busy || !v.online}><Busy on={busy === "adopt"}>Koppelen aan controller</Busy></button>}
          </div>
        </section>
      )}
      {editing && <DeviceForm siteId={site.id} device={v} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); d.reload(); }} />}
    </div>
  );
}

function PortPanel({ deviceId, port, onChange }: { deviceId: number; port: Port; onChange: () => void }) {
  const { busy, run } = useAction();
  const { confirm } = useUi();
  const [comment, setComment] = useState(port.comment ?? "");
  const [forPort, setForPort] = useState(port.name);
  if (forPort !== port.name) { setForPort(port.name); setComment(port.comment ?? ""); }
  const toggle = async () => {
    if (!port.disabled && !(await confirm({ title: `${port.name} uitschakelen?`, action: "Uitschakelen", danger: true,
      text: port.wan ? "Dit is de internetpoort. Het hele netwerk verliest de verbinding met internet." : "Alles achter deze poort verliest de verbinding. Zit TikControl zelf achter deze poort, dan kun je hem alleen via de router weer aanzetten." }))) return;
    run("toggle", async () => { await api.post(`/api/devices/${deviceId}/ports/${encodeURIComponent(port.name)}`, { disabled: !port.disabled }); onChange(); });
  };
  return (
    <div className="panel" style={{ background: "var(--panel-2)" }}>
      <div className="body" style={{ display: "grid", gap: 14 }}>
        <div className="spread" style={{ flexWrap: "wrap" }}>
          <div className="row"><h3>{port.name}</h3>
            {port.disabled ? <span className="tag">Uitgeschakeld</span> : port.running ? <span className="tag ok">Link {port.speed ?? ""}</span> : <span className="tag">Geen link</span>}
            {port.wan && <span className="tag accent">Internet</span>}
            {port.poe?.power && <span className="tag warn">PoE {port.poe.power} W</span>}
          </div>
          <button className={`btn sm ${port.disabled ? "" : "danger"}`} onClick={toggle} disabled={!!busy}>{port.disabled ? "Inschakelen" : "Uitschakelen"}</button>
        </div>
        <dl className="kv">
          <dt>Ontvangen</dt><dd className="num">{bps(port.rx_bps)}</dd>
          <dt>Verzonden</dt><dd className="num">{bps(port.tx_bps)}</dd>
          {port.bridge && <><dt>Bridge</dt><dd>{port.bridge}{port.pvid ? `, PVID ${port.pvid}` : ""}</dd></>}
          {port.poe && <><dt>PoE</dt><dd>{port.poe.status === "powered-on" ? "Levert stroom" : port.poe.status === "waiting-for-load" ? "Geen afnemer" : port.poe.status ?? "–"}</dd></>}
          <dt>MAC</dt><dd className="mono">{port.mac ?? "–"}</dd>
        </dl>
        <form className="row" onSubmit={(e) => { e.preventDefault(); run("c", async () => { await api.post(`/api/devices/${deviceId}/ports/${encodeURIComponent(port.name)}`, { comment }); onChange(); }, "Label opgeslagen"); }}>
          <input className="input" value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Label, bijvoorbeeld: uplink zolder" aria-label="Label" />
          <button className="btn" disabled={!!busy || comment === (port.comment ?? "")}>Opslaan</button>
        </form>
      </div>
    </div>
  );
}
