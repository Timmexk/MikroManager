import { FormEvent, useState } from "react";
import { Eye, EyeOff, Lock, LockOpen, Pencil, Plus, Radio as RadioIcon, Trash2 } from "lucide-react";
import { api } from "../api";
import { bandLabel, Busy, Check, Field, Loading, Modal, useAction, useLoad, useUi } from "../ui";

const SECURITY: Record<string, string> = { wpa2wpa3: "WPA2 + WPA3", wpa2: "WPA2", wpa3: "WPA3", open: "Open", other: "Anders" };
const WIDTH: Record<string, string> = { "20mhz": "20 MHz", "20/40mhz": "20/40 MHz", "20/40/80mhz": "20/40/80 MHz", "20/40/80/160mhz": "20/40/80/160 MHz" };
export const chanNo = (f: number) => (f >= 5950 ? (f - 5950) / 5 : f >= 5000 ? (f - 5000) / 5 : f === 2484 ? 14 : (f - 2407) / 5);
export const isDfs = (f: number) => f >= 5260 && f <= 5720;

/** Wifi on one device, set up on the device itself: a standalone access point, or a standalone radio of the router. */
export function LocalWifiPanel({ deviceId, siteId }: { deviceId: number; siteId: number }) {
  const w = useLoad(() => api.get(`/api/devices/${deviceId}/wifi`), [deviceId], 15000);
  const [edit, setEdit] = useState<{ radio: any; iface: any | null } | null>(null);
  const { busy, run } = useAction();
  const { confirm } = useUi();
  if (!w.data) return w.error ? <div className="banner bad">{w.error}</div> : null;
  const d = w.data;
  if (d.kind === "none" || d.kind === "cap" || !d.radios.length) return null;

  const MODES: Record<string, string> = { site: "Site-netwerken", own: "Zelfstandig", none: "Niet beheerd" };
  const setMode = async (r: any, mode: string) => {
    if (mode === r.mode) return;
    const text: Record<string, any> = {
      site: <>De radio krijgt dezelfde SSID's en instellingen als de access points, zodat clients naadloos roamen. Wat je hier zelf had ingesteld vervalt;
        extra SSID's die bij het zelfstandig maken zijn overgenomen worden verwijderd. Clients verbinden opnieuw.</>,
      own: <>De radio blijft dezelfde SSID's uitzenden, maar de instellingen komen op de interface zelf te staan. Daarna stel je hem hier los in;
        wijzigingen aan de site-netwerken gaan aan deze radio voorbij.</>,
      none: <>MikroManager laat deze radio verder met rust. Hij blijft uitzenden wat er nu op staat.</>,
    };
    if (await confirm({ title: `${r.interface}: ${MODES[mode].toLowerCase()}?`, action: MODES[mode], danger: mode !== "own", text: text[mode] }))
      run(`own${r.mac}`, async () => { await api.post(`/api/sites/${siteId}/wifi/radios/${encodeURIComponent(r.mac)}/mode`, { mode }); w.reload(); },
        `${r.interface}: ${MODES[mode].toLowerCase()}`);
  };
  const remove = async (r: any, i: any) => {
    if (await confirm({ title: `${i.ssid ?? i.name} verwijderen?`, action: "Verwijderen", danger: true, text: `De extra SSID op ${r.interface} verdwijnt meteen; clients erop vallen weg.` }))
      run(`del${i.id}`, async () => { await api.del(`/api/devices/${deviceId}/wifi/${encodeURIComponent(i.id)}`); w.reload(); }, "Verwijderd");
  };

  return (
    <section className="panel">
      <header>
        <div className="row" style={{ gap: 10 }}><RadioIcon size={18} className="muted" /><div><h2>Wifi op dit apparaat</h2>
          <div className="muted small">{d.kind === "standalone" ? "Zelfstandig access point: de radio's worden op het apparaat zelf ingesteld, zonder CAPsMAN."
            : "Eigen radio's van de router. Zendt een radio de netwerken van de site uit, dan stel je hem in onder Wifi."}</div></div></div>
      </header>
      <div className="lw-radios">
        {d.radios.map((r: any) => (
          <div key={r.mac} className="lw-radio">
            <div className="lw-head">
              <div className="grow">
                <div className="row" style={{ gap: 8 }}><span className="strong nowrap">{bandLabel(r.band)}</span><span className="mono muted small">{r.interface}</span>
                  {d.kind === "standalone" && <span className="tag accent">Zelfstandig</span>}</div>
                <div className="muted small">{r.frequency ? `kanaal ${chanNo(r.frequency)} (${r.frequency} MHz)` : r.monitor?.state === "disabled" ? "uit" : "kanaal onbekend"}
                  {r.monitor?.["tx-power"] ? `, ${r.monitor["tx-power"]} dBm` : ""}, {r.clients} {r.clients === 1 ? "client" : "clients"}</div>
              </div>
              {d.kind === "controller" && <div className="seg" role="tablist" aria-label={`Beheer van ${r.interface}`}>
                {["site", "own", "none"].map((m) => <button key={m} role="tab" aria-selected={r.mode === m} className={r.mode === m ? "on" : ""}
                  disabled={!!busy} onClick={() => setMode(r, m)}>{MODES[m]}</button>)}</div>}
              {r.editable && <button className="btn sm" onClick={() => setEdit({ radio: r, iface: null })}><Plus size={14} />SSID toevoegen</button>}
            </div>
            {r.reason && !r.editable && <p className="muted small" style={{ padding: "0 16px 12px" }}>{r.reason}</p>}
            <table className="t lw-table"><colgroup><col style={{ width: "42%" }} /><col style={{ width: "16%" }} /><col /><col style={{ width: 170 }} /></colgroup><tbody>
              {r.interfaces.map((i: any) => (
                <tr key={i.id} className={i.disabled ? "off" : ""}>
                  <td className="strong"><span className="row" style={{ gap: 8 }}>{i.security === "open" ? <LockOpen size={14} className="muted" /> : <Lock size={14} className="muted" />}
                    {i.ssid ?? <span className="muted">geen SSID</span>}{i.hidden && <span className="tag">verborgen</span>}{i.disabled && <span className="tag">uit</span>}</span>
                    <div className="muted small" style={{ fontWeight: 400 }}>{i.master ? "hoofdinterface" : "extra SSID"} · <span className="mono">{i.name}</span>{i.profile ? ` · profiel ${i.profile}` : ""}</div>
                    <div className="muted small lw-sm" style={{ fontWeight: 400 }}>{SECURITY[i.security] ?? i.auth_raw} · {i.vlan_id ? `VLAN ${i.vlan_id}` : "geen VLAN"}</div></td>
                  <td className="small">{SECURITY[i.security] ?? i.auth_raw}</td>
                  <td className="small">{i.vlan_id ? `VLAN ${i.vlan_id}` : "geen VLAN"}{i.bridge ? ` · ${i.bridge}` : i.port_bridge ? ` · ${i.port_bridge} (vaste poort${i.port_pvid && i.port_pvid !== "1" ? `, PVID ${i.port_pvid}` : ""})` : ""}</td>
                  <td className="right nowrap">{r.editable && <>
                    <button className="btn sm" onClick={() => setEdit({ radio: r, iface: i })}><Pencil size={13} />Bewerken</button>
                    {!i.master && <>{" "}<button className="btn sm icon" aria-label="Verwijderen" title="Verwijderen" disabled={!!busy} onClick={() => remove(r, i)}><Trash2 size={14} /></button></>}</>}</td>
                </tr>
              ))}
            </tbody></table>
          </div>
        ))}
      </div>
      {edit && <IfaceForm deviceId={deviceId} radio={edit.radio} iface={edit.iface} bridges={d.bridges}
        onClose={() => setEdit(null)} onSaved={() => { setEdit(null); w.reload(); }} />}
    </section>
  );
}

function IfaceForm({ deviceId, radio, iface, bridges, onClose, onSaved }: { deviceId: number; radio: any; iface: any | null; bridges: string[]; onClose: () => void; onSaved: () => void }) {
  const master = iface ? iface.master : false;
  const m = radio.interfaces[0];
  const [f, setF] = useState({
    ssid: iface?.ssid ?? "", security: iface?.security && iface.security !== "other" ? iface.security : "wpa2wpa3", passphrase: iface?.passphrase ?? "",
    hidden: iface?.hidden ?? false, ft: iface?.ft ?? false, isolation: iface?.isolation ?? false, disabled: iface?.disabled ?? false,
    bridge: iface?.bridge ?? (m?.bridge || ""), vlan_id: iface?.vlan_id ?? "",
    country: iface?.country ?? "", frequency: iface?.frequency ?? "", width: iface?.width ?? "", tx_power: iface?.tx_power ?? "",
  });
  const set = (k: string, v: any) => setF((o) => ({ ...o, [k]: v }));
  const [show, setShow] = useState(false);
  const { busy, run } = useAction();
  const known: number[] = radio.channels ?? [];
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const body: any = { ssid: f.ssid, security: f.security, hidden: f.hidden, isolation: f.isolation, bridge: f.bridge, vlan_id: f.vlan_id === "" ? null : f.vlan_id };
    if (f.security !== "open") { body.passphrase = f.passphrase; body.ft = f.ft; }
    if (iface) body.disabled = f.disabled;
    if (master) Object.assign(body, { country: f.country, frequency: f.frequency, width: f.width, tx_power: f.tx_power === "" ? null : f.tx_power });
    run("save", async () => {
      if (iface) await api.patch(`/api/devices/${deviceId}/wifi/${encodeURIComponent(iface.id)}`, body);
      else await api.post(`/api/devices/${deviceId}/wifi/${encodeURIComponent(m.id)}/virtual`, body);
      onSaved();
    }, "Opgeslagen op het apparaat");
  };
  return (
    <Modal title={iface ? `${iface.name} bewerken` : `Extra SSID op ${radio.interface}`} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Annuleren</button><button className="btn primary" form="ifaceform" disabled={!!busy}><Busy on={!!busy}>Opslaan</Busy></button></>}>
      <form id="ifaceform" className="form" onSubmit={submit}>
        <div className="banner info small">Wordt direct op het apparaat gezet; er is geen 'toepassen' nodig. Clients op {iface ? "deze SSID" : "deze radio"} kunnen kort opnieuw verbinden.</div>
        <Field label="Naam (SSID)"><input className="input" value={f.ssid} onChange={(e) => set("ssid", e.target.value)} maxLength={32} required autoFocus /></Field>
        <div className="two">
          <Field label="Beveiliging"><select className="input" value={f.security} onChange={(e) => set("security", e.target.value)}>
            {Object.entries(SECURITY).filter(([k]) => k !== "other").map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
          {f.security !== "open" ? (
            <Field label="Wachtwoord" hint="8 tot 63 tekens.">
              <div className="row"><input className="input mono" type={show ? "text" : "password"} value={f.passphrase} onChange={(e) => set("passphrase", e.target.value)} minLength={8} maxLength={63} required autoComplete="off" />
                <button type="button" className="btn icon" onClick={() => setShow(!show)} aria-label={show ? "Verberg wachtwoord" : "Toon wachtwoord"}>{show ? <EyeOff size={17} /> : <Eye size={17} />}</button></div>
            </Field>) : <div />}
        </div>
        <div className="two">
          <Field label="Bridge (datapath)" hint={iface?.port_bridge && !f.bridge ? `Zit nu als vaste bridge-poort in ${iface.port_bridge}; die gaat voor het datapath.`
            : iface && !iface.master && !f.bridge ? "Leeg: dezelfde bridge als de hoofdinterface." : undefined}>
            <select className="input" value={f.bridge} onChange={(e) => set("bridge", e.target.value)}>
              <option value="">{master ? (iface?.port_bridge ? `Niet via het datapath (vaste poort in ${iface.port_bridge})` : "Geen (niet in een bridge)") : "Zelfde als de hoofdinterface"}</option>
              {bridges.map((b) => <option key={b}>{b}</option>)}</select></Field>
          <Field label="VLAN" hint="Leeg: zonder VLAN. Met VLAN moet vlan-filtering aan staan op de bridge.">
            <input className="input" value={f.vlan_id} onChange={(e) => set("vlan_id", e.target.value)} inputMode="numeric" placeholder="geen" /></Field>
        </div>
        {master && <>
          <h3 className="small-h">Radio</h3>
          <div className="two">
            <Field label="Kanaal"><select className="input" value={f.frequency} onChange={(e) => set("frequency", e.target.value)}>
              <option value="">Automatisch</option>
              {f.frequency && !known.includes(Number(f.frequency)) && <option value={f.frequency}>{f.frequency}</option>}
              {known.map((x) => <option key={x} value={String(x)}>{chanNo(x)} ({x} MHz){isDfs(x) ? " DFS" : ""}</option>)}</select></Field>
            <Field label="Kanaalbreedte"><select className="input" value={f.width} onChange={(e) => set("width", e.target.value)}>
              <option value="">Standaard</option>{(radio.widths ?? []).map((x: string) => <option key={x} value={x}>{WIDTH[x] ?? x}</option>)}</select></Field>
          </div>
          <div className="two">
            <Field label="Zendvermogen (dBm)" hint={`Leeg: het maximum dat mag (${radio.max} dBm).`}>
              <input className="input mono" value={f.tx_power} onChange={(e) => set("tx_power", e.target.value)} inputMode="numeric" placeholder="maximum" /></Field>
            <Field label="Land" hint="Zoals RouterOS het kent, bijvoorbeeld Netherlands.">
              <input className="input" value={f.country} onChange={(e) => set("country", e.target.value)} placeholder="Netherlands" /></Field>
          </div>
        </>}
        <Check checked={f.isolation} onChange={(v) => set("isolation", v)} label="Client-isolatie" hint="Apparaten op deze SSID kunnen elkaar niet bereiken." />
        {f.security !== "open" && <Check checked={f.ft} onChange={(v) => set("ft", v)} label="Snelle roaming (802.11r)" />}
        <Check checked={f.hidden} onChange={(v) => set("hidden", v)} label="SSID verbergen" />
        {iface && <Check checked={f.disabled} onChange={(v) => set("disabled", v)} label={master ? "Radio uit" : "SSID uit"} />}
      </form>
    </Modal>
  );
}

/** Clients, monitor and scans of one radio. Works for every radio the site knows (router, CAP, standalone). */
export function RadioInsight({ siteId, r }: { siteId: number; r: any }) {
  const cl = useLoad(() => api.get(`/api/sites/${siteId}/wifi/radios/${encodeURIComponent(r.mac)}/clients`), [r.mac], 8000);
  const [scan, setScan] = useState<any | null>(null);
  const { busy, run } = useAction();
  const { confirm } = useUi();
  const start = async (kind: "networks" | "channels") => {
    if (await confirm({ title: kind === "networks" ? "Netwerken in de buurt scannen?" : "Kanaalbezetting meten?", action: "Scannen", danger: true,
      text: <>De radio verlaat zijn kanaal tijdens de scan (een paar seconden per ronde). <strong>Clients op deze radio verliezen even de verbinding.</strong>
        {r.clients > 0 && ` Er zijn nu ${r.clients} verbonden.`}</> }))
      run(kind, async () => setScan(await api.post(`/api/sites/${siteId}/wifi/radios/${encodeURIComponent(r.mac)}/scan`, { kind })));
  };
  const d = cl.data;
  const maxLoad = Math.max(1, ...(scan?.kind === "channels" ? scan.rows.map((x: any) => x.load ?? 0) : [1]));
  return (
    <div className="form">
      <h3 className="small-h" style={{ marginTop: 0 }}>Nu</h3>
      {!d ? <Loading error={cl.error} /> : <>
        <dl className="kv small">
          <dt>Status</dt><dd>{d.monitor.state ?? "onbekend"}</dd>
          <dt>Kanaal</dt><dd className="mono">{d.monitor.channel ?? "–"}</dd>
          <dt>Zendvermogen</dt><dd>{d.monitor["tx-power"] ? `${d.monitor["tx-power"]} dBm` : "–"}</dd>
          <dt>Clients</dt><dd>{d.clients.length}</dd>
        </dl>
        {d.clients.length > 0 && <div className="table-wrap fit"><table className="t">
          <thead><tr><th>Client</th><th>Signaal</th><th className="right">Snelheid</th><th>Verbonden</th></tr></thead>
          <tbody>{d.clients.map((c: any) => (
            <tr key={c.mac}><td className="strong">{c.name ?? c.mac}<div className="muted small" style={{ fontWeight: 400 }}>{c.ssid}{c.ip ? ` · ${c.ip}` : ""}</div></td>
              <td><SignalBar dbm={c.signal} /></td>
              <td className="num right small">{rate(c.tx_rate)} / {rate(c.rx_rate)}</td>
              <td className="small muted">{c.uptime}</td></tr>))}</tbody></table></div>}
      </>}

      <h3 className="small-h">Omgeving</h3>
      {d && !d.can_scan ? <p className="muted small">Scannen kan alleen als het access point ook als apparaat is toegevoegd.</p> : (
        <div className="row wrap">
          <button className="btn sm" disabled={!!busy} onClick={() => start("networks")}><Busy on={busy === "networks"}>Netwerken scannen</Busy></button>
          <button className="btn sm" disabled={!!busy} onClick={() => start("channels")}><Busy on={busy === "channels"}>Kanaalbezetting meten</Busy></button>
          <span className="muted small">Gebruikt /interface/wifi scan en frequency-scan op {d?.device ?? "het apparaat"}.</span>
        </div>)}
      {scan?.kind === "networks" && (
        <div className="table-wrap fit"><table className="t">
          <thead><tr><th>SSID</th><th>Kanaal</th><th>Signaal</th><th className="right">Clients</th></tr></thead>
          <tbody>{scan.rows.map((x: any) => (
            <tr key={x.address}><td className="strong">{x.ssid || <span className="muted">verborgen</span>}<div className="mono muted small" style={{ fontWeight: 400 }}>{x.address}</div></td>
              <td className="small">{chanText(x.channel)}</td><td><SignalBar dbm={x.signal} /></td><td className="num right">{x["sta-count"] ?? "–"}</td></tr>))}</tbody>
        </table></div>)}
      {scan?.kind === "channels" && (
        <div className="chan-bars">
          {scan.rows.map((x: any) => {
            const f = parseInt(String(x.channel));
            return (
              <div key={x.channel} className={`chan ${f === r.frequency ? "cur" : ""}`} title={`${f} MHz: ${x.networks} netwerken, belasting ${x.load}%, ruisvloer ${x.nf} dBm`}>
                <span className="chan-n">{x.networks}</span>
                <span className="chan-bar"><i style={{ height: `${Math.max(3, ((x.load ?? 0) / maxLoad) * 100)}%` }} className={(x.load ?? 0) > 50 ? "hot" : ""} /></span>
                <span className="chan-no">{chanNo(f)}{isDfs(f) ? "*" : ""}</span>
              </div>);
          })}
          <p className="muted small" style={{ gridColumn: "1 / -1" }}>Balk: kanaalbelasting (load). Getal: aantal netwerken. Blauw omlijnd: het kanaal van deze radio. * DFS.</p>
        </div>)}
    </div>
  );
}

const rate = (v: any) => {
  const n = Number(v);
  if (!v) return "–";
  if (!isNaN(n)) return n >= 1e9 ? `${(n / 1e9).toFixed(1)} Gb/s` : `${Math.round(n / 1e6)} Mb/s`;
  return String(v).split("-")[0].replace("Mbps", " Mb/s");
};
const chanText = (c: any) => { const f = parseInt(String(c)); return isNaN(f) ? String(c ?? "–") : `${chanNo(f)} (${f})`; };

function SignalBar({ dbm }: { dbm?: number | null }) {
  if (dbm == null) return <span className="muted">–</span>;
  const pct = Math.max(4, Math.min(100, ((dbm + 95) / 55) * 100));
  return (
    <span className="row" style={{ gap: 8 }}>
      <span className="meter" style={{ width: 64 }}><i style={{ width: `${pct}%`, background: dbm >= -60 ? "var(--ok)" : dbm >= -72 ? "var(--warn)" : "var(--bad)" }} /></span>
      <span className="num small">{Math.round(dbm)} dBm</span>
    </span>
  );
}
