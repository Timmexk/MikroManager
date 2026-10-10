import { FormEvent, useState } from "react";
import { Check as CheckIcon, Eye, EyeOff, Lock, LockOpen, Minus, Pencil, Plus, RefreshCw, X } from "lucide-react";
import { api } from "../api";
import { useApp } from "../App";
import { bandLabel, Busy, Check, Field, Loading, Modal, useAction, useLoad, useUi } from "../ui";

const SECURITY: Record<string, string> = { wpa2wpa3: "WPA2 + WPA3", wpa2: "WPA2", wpa3: "WPA3", open: "Open" };

export default function Wifi() {
  const { site, reloadSites } = useApp();
  const w = useLoad(() => api.get(`/api/sites/${site.id}/wifi`), [site.id], 10000);
  const [edit, setEdit] = useState<any | "new" | null>(null);
  const [plan, setPlan] = useState(false);
  const { busy, run } = useAction();
  const { confirm } = useUi();
  if (!w.data) return <Loading error={w.error} />;
  const d = w.data;

  if (!d.controller) {
    return (<><div className="page-head"><h1>Wifi</h1></div>
      <div className="panel"><div className="empty"><h3>Eerst een router nodig</h3>
        <p>De router van de site wordt de wifi-controller (CAPsMAN). Voeg hem toe, daarna stel je hier de netwerken in.</p>
        <a className="btn primary" href="#/devices">Router toevoegen</a></div></div></>);
  }

  const takeLocal = async () => {
    if (await confirm({ title: "Radio's van de router overnemen?", action: "Overnemen", danger: true,
      text: <>De eigen radio's van {d.controller.name} gaan de wifi-netwerken van deze site uitzenden. De huidige wifi-instellingen op die radio's
        (SSID, wachtwoord) vervallen en clients moeten opnieuw verbinden. <strong>Ben je nu zelf via die wifi verbonden, doe dit dan bekabeld.</strong></> }))
      run("local", async () => { await api.post(`/api/sites/${site.id}/wifi/local-radios`); w.reload(); }, "Radio's overgenomen");
  };
  const adopt = async (ap: any) => {
    if (await confirm({ title: `${ap.name} koppelen?`, action: "Koppelen",
      text: "De radio's worden voortaan door de controller ingesteld. De huidige wifi-instellingen op het apparaat zelf vervallen." }))
      run(`adopt${ap.device_id}`, async () => { await api.post(`/api/devices/${ap.device_id}/adopt`); w.reload(); }, "Access point gekoppeld");
  };

  return (
    <div className="stack">
      <div className="page-head" style={{ marginBottom: 0 }}>
        <div><h1>Wifi</h1><p>Eén set netwerken voor alle access points van {site.name}. {d.controller.name} verdeelt ze via CAPsMAN.</p></div>
        <button className="btn primary" onClick={() => setEdit("new")}><Plus size={16} />Netwerk toevoegen</button>
      </div>

      {!d.controller.has_wifi_menu && d.controller.online && (
        <div className="banner bad">Op {d.controller.name} ontbreekt het wifi-menu. Installeer het pakket wifi-qcom (of wifi-qcom-ac) en RouterOS 7.13 of nieuwer.</div>
      )}
      {d.pending.error && <div className="banner bad">Controller niet te lezen: {d.pending.error}</div>}
      {d.pending.count > 0 && (
        <div className="banner warn">
          <span className="grow"><strong>{d.pending.count === 1 ? "1 wijziging staat" : `${d.pending.count} wijzigingen staan`} nog niet op de router.</strong> Bekijk eerst wat er verandert.</span>
          <button className="btn primary" onClick={() => setPlan(true)}>Bekijken en toepassen</button>
        </div>
      )}

      <section className="panel">
        <header><h2>Netwerken</h2></header>
        {d.wlans.length === 0 ? (
          <div className="empty"><h3>Nog geen wifi-netwerken</h3><p>Maak je eerste netwerk. Er verandert niets op de router totdat je de wijzigingen toepast.</p>
            <button className="btn primary" onClick={() => setEdit("new")}>Netwerk toevoegen</button></div>
        ) : (
          <div className="table-wrap"><table className="t">
            <thead><tr><th>Naam (SSID)</th><th>Beveiliging</th><th>VLAN</th><th>Banden</th><th>Opties</th><th /></tr></thead>
            <tbody>{d.wlans.map((n: any) => (
              <tr key={n.id} className={n.enabled ? "" : "off"}>
                <td className="strong"><span className="row" style={{ gap: 8 }}>{n.security === "open" ? <LockOpen size={15} className="muted" /> : <Lock size={15} className="muted" />}{n.ssid}
                  {!n.enabled && <span className="tag">Uit</span>}</span></td>
                <td>{SECURITY[n.security]}</td>
                <td className="num">{n.vlan_id ?? <span className="muted">geen</span>}</td>
                <td>{n.bands.map(bandLabel).join(" en ")}</td>
                <td className="small muted">{[n.hidden && "verborgen", n.isolation && "clients geïsoleerd", n.ft && n.security !== "open" && "snel roamen"].filter(Boolean).join(", ") || "–"}</td>
                <td className="right"><button className="btn sm" onClick={() => setEdit(n)}><Pencil size={14} />Bewerken</button></td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </section>

      <section className="panel">
        <header><h2>Access points</h2><button className="btn sm" onClick={() => w.reload()}><RefreshCw size={14} />Vernieuwen</button></header>
        {d.aps.length === 0 ? (
          <div className="empty"><p>Geen radio's gevonden. Voeg een access point toe onder Apparaten en koppel het aan de controller.</p>
            <a className="btn" href="#/devices">Naar apparaten</a></div>
        ) : (
          <div className="table-wrap"><table className="t">
            <thead><tr><th>Access point</th><th>Radio</th><th>Kanaal</th><th>Netwerken</th><th className="right">Clients</th><th>Status</th></tr></thead>
            <tbody>{d.aps.flatMap((ap: any) => {
              const unmanagedLocal = ap.local && ap.radios.some((r: any) => !r.managed);
              const head = (
                <td rowSpan={Math.max(1, ap.radios.length)} style={{ verticalAlign: "top" }}>
                  {ap.device_id ? <a className="strong" href={`#/devices/${ap.device_id}`} style={{ color: "inherit" }}>{ap.name}</a> : <span className="strong">{ap.name}</span>}
                  <div className="muted small">{[ap.board, ap.address].filter(Boolean).join(", ")}{ap.local ? " (de controller zelf)" : ""}</div>
                  {!ap.device_id && <div className="small muted">Niet toegevoegd als apparaat</div>}
                </td>);
              const status = (
                <td rowSpan={Math.max(1, ap.radios.length)} style={{ verticalAlign: "top" }}>
                  {ap.adoptable ? <button className="btn sm primary" disabled={!!busy} onClick={() => adopt(ap)}><Busy on={busy === `adopt${ap.device_id}`}>Koppelen</Busy></button>
                    : unmanagedLocal ? <button className="btn sm" disabled={!!busy || d.wlans.length === 0} onClick={takeLocal} title="Laat ook de radio's van de router deze netwerken uitzenden">Radio's overnemen</button>
                      : <span className={`tag ${ap.state === "Ok" || ap.local ? "ok" : "warn"}`}>{ap.local ? "Beheerd" : ap.state === "Ok" ? "Verbonden" : ap.state}</span>}
                </td>);
              if (!ap.radios.length) return [<tr key={ap.name}>{head}<td colSpan={4} className="muted">{ap.adoptable ? "Nog niet gekoppeld aan de controller" : "Wacht tot de controller het apparaat ziet"}</td>{status}</tr>];
              return ap.radios.map((r: any, i: number) => (
                <tr key={ap.name + r.mac}>
                  {i === 0 && head}
                  <td>{bandLabel(r.band)}<div className="mono muted">{r.mac}</div></td>
                  <td className="num">{r.channel ? <>{r.channel.split("/")[0]} MHz{r.tx_power && <div className="muted small">{r.tx_power} dBm</div>}</> : <span className="muted">–</span>}</td>
                  <td>{r.ssids.length ? r.ssids.join(", ") : <span className="muted">{r.managed ? "geen" : "eigen instelling"}</span>}</td>
                  <td className="num right">{r.clients}</td>
                  {i === 0 && status}
                </tr>
              ));
            })}</tbody>
          </table></div>
        )}
      </section>

      <RadioSettings site={site} bridges={d.controller.bridges} onSaved={() => { reloadSites(); w.reload(); }} />

      {edit && <WlanForm siteId={site.id} wlan={edit === "new" ? null : edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); w.reload(); }} />}
      {plan && <PlanModal siteId={site.id} onClose={() => { setPlan(false); w.reload(); }} />}
    </div>
  );
}

function WlanForm({ siteId, wlan, onClose, onSaved }: { siteId: number; wlan: any | null; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({
    ssid: wlan?.ssid ?? "", passphrase: wlan?.passphrase ?? "", security: wlan?.security ?? "wpa2wpa3", vlan_id: wlan?.vlan_id ?? "",
    bands: wlan?.bands ?? ["2g", "5g"], hidden: wlan?.hidden ?? false, isolation: wlan?.isolation ?? false, ft: wlan?.ft ?? true, enabled: wlan?.enabled ?? true,
  });
  const set = (k: string, v: any) => setF((o) => ({ ...o, [k]: v }));
  const [show, setShow] = useState(false);
  const { busy, run } = useAction();
  const { confirm } = useUi();
  const band = (b: string, on: boolean) => set("bands", on ? [...f.bands, b] : f.bands.filter((x: string) => x !== b));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    run("save", async () => {
      if (wlan) await api.patch(`/api/wlans/${wlan.id}`, f); else await api.post(`/api/sites/${siteId}/wifi/wlans`, f);
      onSaved();
    }, "Opgeslagen. Pas de wijzigingen toe om ze op de router te zetten.");
  };
  const remove = async () => {
    if (await confirm({ title: `${wlan.ssid} verwijderen?`, action: "Verwijderen", danger: true,
      text: "Het netwerk verdwijnt van alle access points zodra je de wijzigingen toepast." }))
      run("del", async () => { await api.del(`/api/wlans/${wlan.id}`); onSaved(); });
  };
  return (
    <Modal title={wlan ? `${wlan.ssid} bewerken` : "Wifi-netwerk toevoegen"} onClose={onClose}
      footer={<>{wlan && <button className="btn danger" style={{ marginRight: "auto" }} onClick={remove} disabled={!!busy}>Verwijderen</button>}
        <button className="btn" onClick={onClose}>Annuleren</button>
        <button className="btn primary" form="wlanform" disabled={!!busy}>Opslaan</button></>}>
      <form id="wlanform" className="form" onSubmit={submit}>
        <Field label="Naam (SSID)"><input className="input" value={f.ssid} onChange={(e) => set("ssid", e.target.value)} maxLength={32} required autoFocus /></Field>
        <div className="two">
          <Field label="Beveiliging" hint={f.security === "wpa3" ? "Oudere apparaten kunnen hier niet op verbinden." : f.security === "wpa2" ? "Kies dit voor IoT-apparaten die moeite hebben met WPA3." : undefined}>
            <select className="input" value={f.security} onChange={(e) => set("security", e.target.value)}>
              {Object.entries(SECURITY).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </Field>
          <Field label="VLAN" hint="Leeg: het netwerk van de bridge zelf.">
            <input className="input" value={f.vlan_id} onChange={(e) => set("vlan_id", e.target.value)} inputMode="numeric" placeholder="geen" /></Field>
        </div>
        {f.security !== "open" ? (
          <Field label="Wachtwoord" hint="8 tot 63 tekens.">
            <div className="row"><input className="input mono" type={show ? "text" : "password"} value={f.passphrase} onChange={(e) => set("passphrase", e.target.value)} minLength={8} maxLength={63} required autoComplete="off" />
              <button type="button" className="btn icon" onClick={() => setShow(!show)} aria-label={show ? "Verberg wachtwoord" : "Toon wachtwoord"}>{show ? <EyeOff size={17} /> : <Eye size={17} />}</button></div>
          </Field>
        ) : <div className="banner warn small">Een open netwerk is voor iedereen binnen bereik toegankelijk en niet versleuteld.</div>}
        <div className="field"><span>Banden</span>
          <div className="row" style={{ gap: 22 }}>
            <Check checked={f.bands.includes("2g")} onChange={(v) => band("2g", v)} label="2,4 GHz" />
            <Check checked={f.bands.includes("5g")} onChange={(v) => band("5g", v)} label="5 GHz" />
          </div></div>
        <Check checked={f.isolation} onChange={(v) => set("isolation", v)} label="Clients van elkaar isoleren" hint="Apparaten op dit netwerk kunnen elkaar niet bereiken. Gebruikelijk voor gasten." />
        {f.security !== "open" && <Check checked={f.ft} onChange={(v) => set("ft", v)} label="Snel roamen (802.11r)" hint="Vlottere overdracht tussen access points. Zet uit als een oud apparaat niet wil verbinden." />}
        <Check checked={f.hidden} onChange={(v) => set("hidden", v)} label="Naam verbergen" />
        <Check checked={f.enabled} onChange={(v) => set("enabled", v)} label="Netwerk uitzenden" />
      </form>
    </Modal>
  );
}

function PlanModal({ siteId, onClose }: { siteId: number; onClose: () => void }) {
  const plan = useLoad(() => api.get(`/api/sites/${siteId}/wifi/plan`), [siteId]);
  const [result, setResult] = useState<any | null>(null);
  const { busy, run } = useAction();
  const apply = () => run("apply", async () => setResult(await api.post(`/api/sites/${siteId}/wifi/apply`)));
  const icon = (op: string) => op === "add" ? <Plus size={16} color="var(--ok)" /> : op === "remove" ? <Minus size={16} color="var(--bad)" /> : <RefreshCw size={15} className="muted" />;
  return (
    <Modal wide title={result ? "Resultaat" : `Wijzigingen voor ${plan.data?.controller ?? "de controller"}`} onClose={onClose}
      footer={result ? <button className="btn primary" onClick={onClose}>Sluiten</button>
        : <><button className="btn" onClick={onClose}>Annuleren</button>
          <button className="btn primary" disabled={!!busy || !plan.data?.ops.length} onClick={apply}><Busy on={!!busy}>Toepassen op de router</Busy></button></>}>
      {!plan.data ? <Loading error={plan.error} /> : result ? (
        <>
          <div className={`banner ${result.ok ? "ok" : "bad"}`} style={{ marginBottom: 12 }}>
            {result.ok ? "Alle stappen zijn uitgevoerd." : `Gestopt bij een fout. ${result.remaining} ${result.remaining === 1 ? "stap is" : "stappen zijn"} niet uitgevoerd; wat al gelukt is blijft staan.`}
          </div>
          <ul className="steps">{result.results.map((r: any, i: number) => (
            <li key={i}>{r.ok ? <CheckIcon size={16} color="var(--ok)" /> : <X size={16} color="var(--bad)" />}<div>{r.text}{r.error && <code style={{ color: "var(--bad)" }}>{r.error}</code>}</div></li>
          ))}</ul>
        </>
      ) : plan.data.ops.length === 0 ? <p className="muted">De router is al gelijk aan wat hier is ingesteld.</p> : (
        <>
          <p className="muted" style={{ marginBottom: 10 }}>
            TikControl raakt alleen objecten aan waarvan de naam met <span className="mono">tc-</span> begint. Wat je zelf in WinBox hebt gemaakt blijft staan.
          </p>
          <ul className="steps">{plan.data.ops.map((o: any, i: number) => (
            <li key={i}>{icon(o.op)}<div>{o.text}{o.show && <code>{Object.entries(o.show).map(([k, v]) => `${k}=${v === "" ? '""' : v}`).join("  ")}</code>}</div></li>
          ))}</ul>
        </>
      )}
    </Modal>
  );
}

function RadioSettings({ site, bridges, onSaved }: { site: any; bridges: string[]; onSaved: () => void }) {
  const [s, setS] = useState({ ...site.settings });
  const set = (k: string, v: any) => setS((o: any) => ({ ...o, [k]: v }));
  const { busy, run } = useAction();
  const dirty = JSON.stringify(s) !== JSON.stringify(site.settings);
  const save = (e: FormEvent) => {
    e.preventDefault();
    run("save", async () => { await api.patch(`/api/sites/${site.id}`, { settings: s }); onSaved(); }, "Opgeslagen. Pas de wijzigingen toe om ze op de router te zetten.");
  };
  return (
    <section className="panel">
      <header><h2>Radio-instellingen</h2><span className="muted small">gelden voor alle access points</span></header>
      <form className="body form" onSubmit={save}>
        <div className="two">
          <Field label="Land" hint="Bepaalt toegestane kanalen en zendvermogen. Schrijf het zoals RouterOS het kent.">
            <input className="input" value={s.country} onChange={(e) => set("country", e.target.value)} required /></Field>
          <Field label="Bridge op de controller" hint="Hierin komen de wifi-interfaces en de VLAN's.">
            {bridges.length ? <select className="input" value={s.bridge} onChange={(e) => set("bridge", e.target.value)}>
              {!bridges.includes(s.bridge) && <option value={s.bridge}>{s.bridge} (bestaat niet)</option>}
              {bridges.map((b) => <option key={b}>{b}</option>)}</select>
              : <input className="input" value={s.bridge} onChange={(e) => set("bridge", e.target.value)} required />}
          </Field>
        </div>
        <div className="two">
          <Field label="Kanaalbreedte 2,4 GHz">
            <select className="input" value={s.ch2_width} onChange={(e) => set("ch2_width", e.target.value)}><option value="20mhz">20 MHz</option><option value="20/40mhz">20/40 MHz</option></select></Field>
          <Field label="Kanalen 2,4 GHz" hint="Frequenties in MHz, bijvoorbeeld 2412,2437,2462. Leeg: automatisch.">
            <input className="input mono" value={s.ch2_freq} onChange={(e) => set("ch2_freq", e.target.value)} placeholder="automatisch" pattern="[0-9,:\- ]*" /></Field>
        </div>
        <div className="two">
          <Field label="Kanaalbreedte 5 GHz">
            <select className="input" value={s.ch5_width} onChange={(e) => set("ch5_width", e.target.value)}>
              <option value="20mhz">20 MHz</option><option value="20/40mhz">20/40 MHz</option><option value="20/40/80mhz">20/40/80 MHz</option><option value="20/40/80/160mhz">20/40/80/160 MHz</option></select></Field>
          <Field label="Kanalen 5 GHz" hint="Bijvoorbeeld 5180,5260,5500. Leeg: automatisch.">
            <input className="input mono" value={s.ch5_freq} onChange={(e) => set("ch5_freq", e.target.value)} placeholder="automatisch" pattern="[0-9,:\- ]*" /></Field>
        </div>
        <div className="two">
          <Field label="DFS-kanalen (5 GHz)" hint="Op DFS-kanalen luistert een AP eerst 1 tot 10 minuten naar radar voordat hij uitzendt.">
            <select className="input" value={s.skip_dfs} onChange={(e) => set("skip_dfs", e.target.value)}>
              <option value="disabled">Alle kanalen gebruiken</option><option value="10min-cac">Kanalen met 10 minuten wachttijd overslaan</option><option value="all">Alle DFS-kanalen overslaan</option></select></Field>
          <div className="field" style={{ alignContent: "end" }}>
            <Check checked={!!s.ac_caps} onChange={(v) => set("ac_caps", v)} label="Ook wifi 5 access points (wifi-qcom-ac)"
              hint="Maakt extra regels zonder VLAN in het datapath; het VLAN stel je op die AP's per interface in met een bridge-PVID." />
          </div>
        </div>
        <div><button className="btn primary" disabled={!dirty || !!busy}>Instellingen opslaan</button></div>
      </form>
    </section>
  );
}
