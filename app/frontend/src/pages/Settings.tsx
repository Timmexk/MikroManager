import { FormEvent, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { api } from "../api";
import { useApp } from "../App";
import { Busy, Check, Field, fmtAgo, useAction, useLoad, useUi } from "../ui";
import { useApplyToast } from "./Wifi";

export default function Settings({ onLogout, themeLabel, nextTheme }: { onLogout: () => void; themeLabel: string; nextTheme: () => void }) {
  const { site, sites, reloadSites, setSiteId, state } = useApp();
  const devs = useLoad<any[]>(() => api.get(`/api/sites/${site.id}/devices`), [site.id]);
  const { busy, run } = useAction();
  const { confirm } = useUi();
  const [name, setName] = useState(site.name);
  const [newSite, setNewSite] = useState("");
  const [pw, setPw] = useState({ current: "", new: "" });
  const controller = devs.data?.find((d) => d.is_controller)?.id ?? "";
  const routers = devs.data?.filter((d) => d.role === "router") ?? [];

  const removeSite = async () => {
    if (await confirm({ title: `Site ${site.name} verwijderen?`, action: "Site verwijderen", danger: true,
      text: `De site verdwijnt uit MikroManager met ${site.devices} apparaten, de wifi-netwerken en alle back-ups. Op de apparaten zelf verandert niets.` }))
      run("delsite", async () => { await api.del(`/api/sites/${site.id}`); await reloadSites(); }, "Site verwijderd");
  };

  return (
    <div className="stack" style={{ maxWidth: 760 }}>
      <div className="page-head" style={{ marginBottom: 0 }}><h1>Instellingen</h1></div>

      <section className="panel">
        <header><h2>Deze site</h2></header>
        <div className="body form">
          <form className="row" onSubmit={(e) => { e.preventDefault(); run("name", async () => { await api.patch(`/api/sites/${site.id}`, { name }); await reloadSites(); }, "Naam opgeslagen"); }}>
            <div className="grow"><Field label="Naam"><input className="input" value={name} onChange={(e) => setName(e.target.value)} required /></Field></div>
            <button className="btn" style={{ alignSelf: "end" }} disabled={!!busy || name === site.name}>Opslaan</button>
          </form>
          <div><button className="btn danger" onClick={removeSite} disabled={!!busy || sites.length < 2} title={sites.length < 2 ? "De laatste site kun je niet verwijderen" : undefined}><Trash2 size={15} />Site verwijderen</button></div>
        </div>
      </section>

      <WifiController routers={routers} controller={controller} onController={(v) => run("ctrl", async () => {
        await api.patch(`/api/sites/${site.id}`, { controller_id: v }); devs.reload(); }, "Controller gewijzigd")} />

      <section className="panel">
        <header><h2>Sites</h2></header>
        <table className="t"><tbody>{sites.map((s) => (
          <tr key={s.id}><td className="strong">{s.name}{s.id === site.id && <span className="tag accent" style={{ marginLeft: 8 }}>Geopend</span>}</td>
            <td className="muted">{s.devices === 0 ? "geen apparaten" : `${s.online} van ${s.devices} apparaten online`}</td>
            <td className="right">{s.id !== site.id && <button className="btn sm" onClick={() => { setSiteId(s.id); location.hash = "#/"; }}>Openen</button>}</td></tr>
        ))}</tbody></table>
        <form className="body row" style={{ borderTop: "1px solid var(--line-soft)" }}
          onSubmit={(e: FormEvent) => { e.preventDefault(); run("add", async () => { const s = await api.post("/api/sites", { name: newSite }); setNewSite(""); await reloadSites(); setSiteId(s.id); location.hash = "#/devices"; }, "Site aangemaakt"); }}>
          <input className="input grow" value={newSite} onChange={(e) => setNewSite(e.target.value)} placeholder="Naam van de nieuwe site" aria-label="Naam van de nieuwe site" required />
          <button className="btn" disabled={!!busy}><Plus size={15} />Site toevoegen</button>
        </form>
      </section>

      <section className="panel">
        <header><h2>Account</h2><span className="muted small">ingelogd als {state.user}</span></header>
        <form className="body form" onSubmit={(e) => { e.preventDefault(); run("pw", async () => { await api.post("/api/password", pw); onLogout(); }, "Wachtwoord gewijzigd. Log opnieuw in."); }}>
          <div className="two">
            <Field label="Huidig wachtwoord"><input className="input" type="password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} autoComplete="current-password" required /></Field>
            <Field label="Nieuw wachtwoord" hint="Minstens 8 tekens."><input className="input" type="password" value={pw.new} onChange={(e) => setPw({ ...pw, new: e.target.value })} autoComplete="new-password" minLength={8} required /></Field>
          </div>
          <div className="row wrap">
            <button className="btn" disabled={!!busy}>Wachtwoord wijzigen</button>
            <button type="button" className="btn" onClick={nextTheme}>Thema: {themeLabel === "auto" ? "systeem" : themeLabel === "light" ? "licht" : "donker"}</button>
            <button type="button" className="btn" onClick={onLogout}>Uitloggen</button>
          </div>
        </form>
      </section>
      <Vendors />
      <section className="panel">
        <header><h2>Diagnose</h2></header>
        <div className="body" style={{ display: "grid", gap: 10 }}>
          <p className="muted" style={{ maxWidth: "70ch" }}>Klopt er iets niet op je echte apparaten? Dit bestand bevat wat de routers van <b>{site.name}</b> letterlijk
            antwoorden op de menu's die MikroManager leest, naast wat MikroManager ervan maakt. Wachtwoorden en sleutels zitten er nooit in.</p>
          <div className="row wrap">
            <a className="btn" href={`/api/sites/${site.id}/diagnostics?anonymous=true`}>Download anoniem (om te delen)</a>
            <a className="btn" href={`/api/sites/${site.id}/diagnostics?anonymous=false`}>Download volledig</a>
          </div>
          <small className="muted">Anoniem: namen, MAC-adressen, serienummers en publieke IP-adressen zijn vervangen. Volledig bevat die wel.</small>
        </div>
      </section>
      <p className="muted small">MikroManager {state.version}{state.demo ? ", demomodus" : ""}. Wachtwoorden van apparaten staan versleuteld in de database; de sleutel staat in <span className="mono">secret.key</span> in de data-map.</p>
    </div>
  );
}

function Vendors() {
  const v = useLoad<any>(() => api.get("/api/vendors"), []);
  const { busy, run } = useAction();
  if (!v.data) return null;
  return (
    <section className="panel">
      <header><h2>Fabrikantenlijst</h2>
        <span className="muted small">{v.data.count ? `${v.data.count.toLocaleString("nl-NL")} prefixen${v.data.updated ? `, bijgewerkt ${fmtAgo(v.data.updated)}` : ""}` : "nog niet opgehaald"}</span></header>
      <div className="body spread" style={{ flexWrap: "wrap" }}>
        <p className="muted" style={{ maxWidth: "62ch" }}>Bij clients toont MikroManager de fabrikant op basis van het MAC-adres. Daarvoor wordt de openbare lijst van de IEEE
          gedownload{v.data.auto ? " en elke twee maanden ververst" : " (automatisch verversen staat uit)"}. Er wordt niets over je netwerk verstuurd.</p>
        <button className="btn" disabled={!!busy} onClick={() => run("oui", async () => { await api.post("/api/vendors/update"); v.reload(); }, "Fabrikantenlijst bijgewerkt")}>
          {busy ? "Bezig…" : "Nu bijwerken"}</button>
      </div>
    </section>
  );
}

/** How MikroManager drives the wifi controller: which router, which bridge, CAPsMAN, and whether changes go out right away.
 * The radio defaults (country, widths, channels) are on the Wifi page. */
function WifiController({ routers, controller, onController }: { routers: any[]; controller: number | ""; onController: (id: number) => void }) {
  const { site, reloadSites } = useApp();
  const w = useLoad<any>(() => api.get(`/api/sites/${site.id}/wifi`), [site.id]);
  const pickKeys = (o: any) => ({ auto_apply: o.auto_apply !== false, bridge: o.bridge, capsman: o.capsman ?? "auto", ac_caps: !!o.ac_caps });
  const [s, setS] = useState<any>(pickKeys(site.settings));
  const set = (k: string, v: any) => setS((o: any) => ({ ...o, [k]: v }));
  const { busy, run } = useAction();
  const done = useApplyToast();
  const dirty = JSON.stringify(s) !== JSON.stringify(pickKeys(site.settings));
  const bridges: string[] = w.data?.controller?.bridges ?? [];
  const save = (e: FormEvent) => {
    e.preventDefault();
    run("wctl", async () => { const res = await api.patch(`/api/sites/${site.id}`, { settings: { ...site.settings, ...s } }); done(res); await reloadSites(); });
  };
  return (
    <section className="panel">
      <header><h2>Wifi-controller</h2><span className="muted small">{w.data?.controller ? w.data.controller.name : "nog geen router"}</span></header>
      <form className="body form" onSubmit={save}>
        {routers.length > 1 && (
          <Field label="Router" hint="De router waarop CAPsMAN draait en waar de wifi-netwerken worden aangemaakt.">
            <select className="input" value={controller} onChange={(e) => onController(Number(e.target.value))}>
              {routers.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select></Field>
        )}
        <Check checked={s.auto_apply} onChange={(v) => set("auto_apply", v)} label="Wijzigingen direct toepassen"
          hint="Opslaan zet wifi-wijzigingen meteen op de router en de access points. Mislukt een stap, dan draait MikroManager de wijziging terug. Uit: eerst bekijken en dan zelf toepassen." />
        <div className="two">
          <Field label="Bridge op de controller" hint="Hierin komen de wifi-interfaces en de VLAN's.">
            {bridges.length ? <select className="input" value={s.bridge} onChange={(e) => set("bridge", e.target.value)}>
              {!bridges.includes(s.bridge) && <option value={s.bridge}>{s.bridge} (bestaat niet)</option>}
              {bridges.map((b) => <option key={b}>{b}</option>)}</select>
              : <input className="input" value={s.bridge} onChange={(e) => set("bridge", e.target.value)} required />}
          </Field>
          <Field label="CAPsMAN" hint={s.capsman === "off" ? "MikroManager schrijft geen provisioning-regels. CAPsMAN zelf blijft zoals hij op de router staat."
            : s.capsman === "on" ? "Provisioning-regels staan er altijd, ook zonder access points."
              : "Provisioning-regels pas zodra er een access point is. De eigen radio's van de router hebben CAPsMAN nooit nodig."}>
            <select className="input" value={s.capsman} onChange={(e) => set("capsman", e.target.value)}>
              <option value="auto">Automatisch (alleen met access points)</option><option value="on">Altijd</option><option value="off">Uit</option></select></Field>
        </div>
        <Check checked={s.ac_caps} onChange={(v) => set("ac_caps", v)} label="Ook wifi 5 access points (wifi-qcom-ac)"
          hint="Maakt extra regels zonder VLAN in het datapath; het VLAN stel je op die AP's per interface in met een bridge-PVID." />
        <div><button className="btn primary" disabled={!dirty || !!busy}><Busy on={busy === "wctl"}>Opslaan</Busy></button></div>
      </form>
    </section>
  );
}
