import { FormEvent, useState } from "react";
import qrcode from "qrcode-generator";
import { AlertTriangle, Check as CheckIcon, ChevronDown, ChevronRight, CircleCheck, CircleX, Eye, EyeOff, Lock, LockOpen, Minus, Pencil, Plus, QrCode, RefreshCw, Stethoscope, Wrench, X } from "lucide-react";
import { api } from "../api";
import { useApp } from "../App";
import { bandLabel, Busy, Check, Field, Loading, Modal, Seg, useAction, useLoad, useUi } from "../ui";
import { RadioInsight } from "./LocalWifi";

const SECURITY: Record<string, string> = { wpa2wpa3: "WPA2 + WPA3", wpa2: "WPA2", wpa3: "WPA3", open: "Open" };
const SCOPE: Record<string, string> = { all: "Alle access points", local: "Alleen de router", caps: "Alleen de CAP's" };
const target = (n: any, siteBridge: string) => n.vlan_id ? `VLAN ${n.vlan_id}${n.bridge && n.bridge !== siteBridge ? ` op ${n.bridge}` : ""}`
  : n.bridge && n.bridge !== siteBridge ? n.bridge : "LAN (geen VLAN)";

export default function Wifi() {
  const { site, reloadSites } = useApp();
  const w = useLoad(() => api.get(`/api/sites/${site.id}/wifi`), [site.id], 10000);
  const [edit, setEdit] = useState<any | "new" | null>(null);
  const [plan, setPlan] = useState(false);
  const [txRadio, setTxRadio] = useState<{ ap: string; r: any; deviceId?: number } | null>(null);
  const [qr, setQr] = useState<any | null>(null);
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
      run("local", async () => { await api.post(`/api/sites/${site.id}/wifi/local-radios`, { action: "take" }); w.reload(); }, "Radio's overgenomen");
  };
  const giveBack = async () => {
    if (await confirm({ title: "Radio's van de router teruggeven?", action: "Teruggeven", danger: true,
      text: <>MikroManager haalt zijn profielen en virtuele interfaces van de eigen radio's van {d.controller.name}. De radio's staan daarna
        onbeheerd en zenden niets uit, tot je ze zelf instelt (bijvoorbeeld met je oude instellingen uit Onderhoud, Back-ups).
        Radio's die nog op de oude manier geprovisioned zijn, worden eerst hersteld. De access points merken hier niets van.</> }))
      run("local", async () => { await api.post(`/api/sites/${site.id}/wifi/local-radios`, { action: "release" }); w.reload(); }, "Radio's teruggegeven");
  };
  const stuckLocal = d.aps.some((ap: any) => ap.local && ap.radios.some((r: any) => r.provisioned_local));
  const adopt = async (ap: any) => {
    if (await confirm({ title: `${ap.name} adopteren?`, action: "Adopteren",
      text: "De radio's worden voortaan door de controller ingesteld. De huidige wifi-instellingen op het apparaat zelf vervallen." }))
      run(`adopt${ap.device_id}`, async () => { await api.post(`/api/devices/${ap.device_id}/adopt`); w.reload(); }, "Access point geadopteerd");
  };

  return (
    <div className="stack">
      <div className="page-head" style={{ marginBottom: 0 }}>
        <div><h1>Wifi</h1><p>Eén set netwerken voor {site.name}. {d.controller.name} zendt ze zelf uit met zijn eigen radio's
          {d.aps.some((a: any) => !a.local) ? "; de access points krijgen ze via CAPsMAN." : ". CAPsMAN gaat pas aan zodra je een access point adopteert."}</p></div>
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

      {d.wlans.length > 0 && <WifiCheck siteId={site.id} hints={d.hints ?? []} pending={d.pending.count > 0} onChanged={() => w.reload()} />}

      <section className="panel">
        <header><h2>Netwerken</h2></header>
        {d.wlans.length === 0 ? (
          <div className="empty"><h3>Nog geen wifi-netwerken</h3><p>Maak je eerste netwerk. Er verandert niets op de router totdat je de wijzigingen toepast.</p>
            <button className="btn primary" onClick={() => setEdit("new")}>Netwerk toevoegen</button></div>
        ) : (
          <div className="table-wrap"><table className="t">
            <thead><tr><th>Naam (SSID)</th><th>Beveiliging</th><th>Netwerk</th><th>Banden</th><th>Uitzenden op</th><th>Opties</th><th /></tr></thead>
            <tbody>{d.wlans.map((n: any) => (
              <tr key={n.id} className={n.enabled ? "" : "off"}>
                <td className="strong"><span className="row" style={{ gap: 8 }}>{n.security === "open" ? <LockOpen size={15} className="muted" /> : <Lock size={15} className="muted" />}{n.ssid}
                  {!n.enabled && <span className="tag">Uit</span>}</span></td>
                <td>{SECURITY[n.security]}</td>
                <td className="nowrap">{target(n, d.settings.bridge)}</td>
                <td>{n.bands.map(bandLabel).join(" en ")}</td>
                <td className="small">{SCOPE[n.scope ?? "all"]}</td>
                <td className="small muted">{[n.hidden && "verborgen SSID", n.isolation && "client-isolatie", n.ft && n.security !== "open" && "snelle roaming"].filter(Boolean).join(", ") || "–"}</td>
                <td className="right nowrap"><button className="btn sm" onClick={() => setQr(n)} title="QR-code om te verbinden"><QrCode size={14} />QR</button>{" "}
                  <button className="btn sm" onClick={() => setEdit(n)}><Pencil size={14} />Bewerken</button></td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </section>

      {d.aps.some((a: any) => a.local) && <RouterRadios ap={d.aps.find((a: any) => a.local)} siteId={site.id} wlans={d.wlans} busy={busy} run={run}
        pending={d.pending.count > 0} onPlan={() => setPlan(true)} onOpen={(r: any) => setTxRadio({ ap: d.controller.name, r, deviceId: d.controller.id })}
        reload={() => w.reload()} />}
      {d.roaming?.length > 0 && <Roaming items={d.roaming} />}

      <section className="panel">
        {stuckLocal && (
          <div className="banner bad" style={{ margin: 12 }}>
            <span className="grow"><strong>De eigen radio's van {d.controller.name} zijn geprovisioned door een eerdere versie van MikroManager.</strong> MikroTik
              raadt dat af: de interfaces worden verwijderd en opnieuw aangemaakt, waardoor ze slecht of niet werken. Herstel ze hier.</span>
            <button className="btn sm primary" disabled={!!busy} onClick={takeLocal}>Herstellen en netwerken uitzenden</button>
            <button className="btn sm" disabled={!!busy} onClick={giveBack}>Herstellen en teruggeven</button>
          </div>
        )}
        <header><h2>Access points</h2><button className="btn sm" onClick={() => w.reload()}><RefreshCw size={14} />Vernieuwen</button></header>
        {d.aps.filter((a: any) => !a.local).length === 0 ? (
          <div className="empty"><p>Geen radio's gevonden. Voeg een access point toe onder Apparaten en koppel het aan de controller.</p>
            <a className="btn" href="#/devices">Naar apparaten</a></div>
        ) : (
          <><div className="only-sm ap-cards">{d.aps.filter((a: any) => !a.local).map((ap: any) => (
            <div key={ap.name} className="ap-card">
              <div className="spread"><div style={{ minWidth: 0 }}>
                {ap.device_id ? <a className="strong" href={`#/devices/${ap.device_id}`} style={{ color: "inherit" }}>{ap.name}</a> : <span className="strong">{ap.name}</span>}
                <div className="muted small">{[ap.board, ap.address].filter(Boolean).join(", ")}{ap.local ? " (controller)" : ""}</div></div>
                {ap.adoptable ? <button className="btn sm primary" disabled={!!busy} onClick={() => adopt(ap)}>Adopteren</button>
                  : ap.local && ap.radios.some((r: any) => !r.managed) ? <button className="btn sm" disabled={!!busy || d.wlans.length === 0} onClick={takeLocal}>Overnemen</button>
                    : <span className={`tag ${ap.local || ap.state === "Ok" ? "ok" : "warn"}`}>{ap.local ? "Beheerd" : ap.state === "Ok" ? "Verbonden" : ap.state}</span>}
              </div>
              {ap.radios.map((r: any) => (
                <button key={r.mac} className="radio-row" onClick={() => setTxRadio({ ap: ap.name, r, deviceId: ap.device_id })}>
                  <span className="strong">{bandLabel(r.band)}</span>
                  <span className="num">{r.frequency ? `kan. ${chanNo(r.frequency)}` : "–"}</span>
                  <span className="num">{r.tx_power ? `${r.tx_power} dBm` : "–"}</span>
                  <span className="muted">{r.clients} {r.clients === 1 ? "client" : "clients"}</span>
                </button>
              ))}
              {!ap.radios.length && <div className="muted small">{ap.adoptable ? "Nog niet geadopteerd" : "Wacht op de controller"}</div>}
            </div>
          ))}</div>
          <div className="table-wrap hide-sm"><table className="t">
            <thead><tr><th>Access point</th><th>Radio</th><th>Kanaal</th><th>Zendvermogen</th><th>SSID's</th><th className="right">Clients</th><th>Status</th></tr></thead>
            <tbody>{d.aps.filter((a: any) => !a.local).flatMap((ap: any) => {
              const unmanagedLocal = ap.local && ap.radios.some((r: any) => !r.managed);
              const head = (
                <td rowSpan={Math.max(1, ap.radios.length)} style={{ verticalAlign: "top" }}>
                  {ap.device_id ? <a className="strong" href={`#/devices/${ap.device_id}`} style={{ color: "inherit" }}>{ap.name}</a> : <span className="strong">{ap.name}</span>}
                  <div className="muted small">{[ap.board, ap.address].filter(Boolean).join(", ")}{ap.local ? " (de controller zelf)" : ""}</div>
                  {!ap.device_id && <div className="small muted">Niet toegevoegd als apparaat</div>}
                </td>);
              const status = (
                <td rowSpan={Math.max(1, ap.radios.length)} style={{ verticalAlign: "top" }}>
                  {ap.adoptable ? <div style={{ display: "grid", gap: 6, justifyItems: "start" }}>
                      {ap.standalone && <span className="tag accent">Zelfstandig</span>}
                      <button className="btn sm primary" disabled={!!busy} onClick={() => adopt(ap)}><Busy on={busy === `adopt${ap.device_id}`}>Adopteren</Busy></button>
                      {ap.standalone && <a className="btn sm" href={`#/devices/${ap.device_id}`}>Zelf instellen</a>}</div>
                    : ap.local && unmanagedLocal ? <button className="btn sm" disabled={!!busy || d.wlans.length === 0} onClick={takeLocal} title="Laat ook de radio's van de router deze netwerken uitzenden">Radio's overnemen</button>
                      : ap.local ? <div style={{ display: "grid", gap: 6, justifyItems: "start" }}><span className="tag ok">Beheerd</span>
                          <button className="btn sm" disabled={!!busy} onClick={giveBack}>Teruggeven</button></div>
                        : <div style={{ display: "grid", gap: 6, justifyItems: "start" }}>
                            <span className={`tag ${ap.state === "Ok" ? "ok" : "warn"}`}>{ap.state === "Ok" ? "Verbonden" : ap.state}</span>
                            {ap.radios.length > 0 && <button className="btn sm" disabled={!!busy} title="Stuurt de configuratie opnieuw naar dit access point; clients verbinden kort opnieuw"
                              onClick={() => run(`prov${ap.name}`, async () => { await api.post(`/api/sites/${site.id}/wifi/aps/reprovision`, { name: ap.name }); w.reload(); }, `${ap.name} opnieuw geprovisioned`)}>
                              <Busy on={busy === `prov${ap.name}`}>Opnieuw provisionen</Busy></button>}
                          </div>}
                </td>);
              if (!ap.radios.length) return [<tr key={ap.name}>{head}<td colSpan={5} className="muted">{ap.adoptable ? "Nog niet geadopteerd door de controller" : "Wacht tot de controller het apparaat ziet"}</td>{status}</tr>];
              return ap.radios.map((r: any, i: number) => (
                <tr key={ap.name + r.mac}>
                  {i === 0 && head}
                  <td>{bandLabel(r.band)}<div className="mono muted">{r.mac}</div></td>
                  <td><button className="btn sm" onClick={() => setTxRadio({ ap: ap.name, r, deviceId: ap.device_id })} title="Kanaal en kanaalbreedte instellen">
                    {r.frequency ? <><span className="num">{chanNo(r.frequency)}</span><span className="muted num" style={{ marginLeft: 6 }}>{r.frequency} MHz</span></> : "–"}
                    {r.tx?.freq ? <span className="tag accent" style={{ marginLeft: 6 }}>vast</span> : null}</button></td>
                  <td><button className="btn sm" onClick={() => setTxRadio({ ap: ap.name, r, deviceId: ap.device_id })} title="Zendvermogen instellen">
                      {r.standalone ? "Op het apparaat" : r.tx?.own ? "Zelfstandig" : r.tx?.off ? "Uit" : TX_LABEL[r.tx?.mode ?? "high"]}{r.tx_power ? <span className="muted num" style={{ marginLeft: 6 }}>{r.tx_power} dBm</span> : null}</button></td>
                  <td>{r.ssids.length ? r.ssids.join(", ") : <span className="muted">{r.managed ? "geen" : "eigen instelling"}</span>}</td>
                  <td className="num right">{r.clients}</td>
                  {i === 0 && status}
                </tr>
              ));
            })}</tbody>
          </table></div></>
        )}
      </section>

      <RadioSettings site={site} bridges={d.controller.bridges} onSaved={() => { reloadSites(); w.reload(); }} />

      {edit && <WlanForm siteId={site.id} hasCaps={d.aps.some((a: any) => !a.local)} wlan={edit === "new" ? null : edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); w.reload(); }} />}
      {plan && <PlanModal siteId={site.id} prefix={d.settings.prefix ?? "tc"} onClose={() => { setPlan(false); w.reload(); }} />}
      {qr && <QrModal wlan={qr} site={site.name} onClose={() => setQr(null)} />}
      {txRadio && <TxModal siteId={site.id} ap={txRadio.ap} r={txRadio.r} deviceId={txRadio.deviceId} wlans={d.wlans}
        onClose={() => setTxRadio(null)} onSaved={() => { setTxRadio(null); w.reload(); }} />}
    </div>
  );
}

function WlanForm({ siteId, wlan, hasCaps, onClose, onSaved }: { siteId: number; wlan: any | null; hasCaps: boolean; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({
    ssid: wlan?.ssid ?? "", passphrase: wlan?.passphrase ?? "", security: wlan?.security ?? "wpa2wpa3", vlan_id: wlan?.vlan_id ?? "",
    bands: wlan?.bands ?? ["2g", "5g"], hidden: wlan?.hidden ?? false, isolation: wlan?.isolation ?? false, ft: wlan?.ft ?? true, enabled: wlan?.enabled ?? true,
    bridge: wlan?.bridge ?? "", scope: wlan?.scope ?? "all",
  });
  const tg = useLoad(() => api.get(`/api/sites/${siteId}/wifi/targets`), [siteId]);
  const siteBridge: string = tg.data?.site_bridge ?? "";
  const targets: any[] = tg.data?.targets ?? [];
  const keyOf = (bridge: string, vlan: any) => `${bridge || siteBridge}|${vlan ?? ""}`;
  const current = keyOf(f.bridge, f.vlan_id === "" ? null : f.vlan_id);
  const [custom, setCustom] = useState(false);
  const known = targets.some((x) => keyOf(x.bridge, x.vlan_id) === current);
  const pick = (v: string) => {
    if (v === "custom") { setCustom(true); return; }
    setCustom(false);
    const [b, vl] = v.split("|");
    setF((o) => ({ ...o, bridge: b === siteBridge ? "" : b, vlan_id: vl }));
  };
  const ownBridge = !!f.bridge && f.bridge !== siteBridge;
  const set = (k: string, v: any) => setF((o) => ({ ...o, [k]: v }));
  const [show, setShow] = useState(false);
  const { busy, run } = useAction();
  const { confirm } = useUi();
  const band = (b: string, on: boolean) => set("bands", on ? [...f.bands, b] : f.bands.filter((x: string) => x !== b));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    run("save", async () => {
      const body = { ...f, bridge: f.bridge || null };
      if (wlan) await api.patch(`/api/wlans/${wlan.id}`, body); else await api.post(`/api/sites/${siteId}/wifi/wlans`, body);
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
          <Field label="Netwerk" hint={custom ? undefined : "Waar de clients van dit SSID uitkomen. Uit de netwerken op de router."}>
            {!tg.data ? <select className="input" disabled><option>Laden…</option></select> : (
              <select className="input" value={custom ? "custom" : current} onChange={(e) => pick(e.target.value)}>
                {!known && !custom && <option value={current}>{f.vlan_id ? `VLAN ${f.vlan_id}` : f.bridge || siteBridge} (niet gevonden op de router)</option>}
                {targets.map((x) => (
                  <option key={keyOf(x.bridge, x.vlan_id)} value={keyOf(x.bridge, x.vlan_id)}>
                    {x.vlan_id ? `VLAN ${x.vlan_id}, ${x.label}` : x.bridge === siteBridge ? `LAN, ${x.bridge} zonder VLAN` : `${x.bridge}, eigen bridge zonder VLAN`}
                    {x.subnet ? ` (${x.subnet})` : ""}{x.vlan_id && x.bridge !== siteBridge ? ` op ${x.bridge}` : ""}
                  </option>
                ))}
                <option value="custom">Ander VLAN-ID…</option>
              </select>)}
            {custom && <input className="input" style={{ marginTop: 6 }} value={f.vlan_id} onChange={(e) => set("vlan_id", e.target.value)}
              inputMode="numeric" placeholder="VLAN-ID, 1 tot 4094" autoFocus />}
          </Field>
        </div>
        <Field label="Uitzenden op" hint={f.scope === "local" ? "Alleen de eigen radio's van de router, direct ingesteld, zonder CAPsMAN."
          : f.scope === "caps" ? "Alleen de access points die CAPsMAN beheert; de router zelf zendt dit netwerk niet uit."
            : ownBridge && hasCaps ? "Let op: een netwerk op een eigen bridge zonder VLAN kan niet naar de access points. Kies 'Alleen de router' of gebruik een VLAN."
              : "De router en alle access points."}>
          <select className="input" value={f.scope} onChange={(e) => set("scope", e.target.value)}>
            {Object.entries(SCOPE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </Field>
        {f.security !== "open" ? (
          <Field label="Wachtwoord" hint="8 tot 63 tekens.">
            <div className="row"><input className="input mono" type={show ? "text" : "password"} value={f.passphrase} onChange={(e) => set("passphrase", e.target.value)} minLength={8} maxLength={63} required autoComplete="off" />
              <button type="button" className="btn icon" onClick={() => setShow(!show)} aria-label={show ? "Verberg wachtwoord" : "Toon wachtwoord"}>{show ? <EyeOff size={17} /> : <Eye size={17} />}</button></div>
          </Field>
        ) : <div className="banner warn small">Een open netwerk is voor iedereen binnen bereik toegankelijk en niet versleuteld.</div>}
        <div className="field"><span>Frequentiebanden</span>
          <div className="row" style={{ gap: 22 }}>
            <Check checked={f.bands.includes("2g")} onChange={(v) => band("2g", v)} label="2,4 GHz" />
            <Check checked={f.bands.includes("5g")} onChange={(v) => band("5g", v)} label="5 GHz" />
          </div></div>
        <Check checked={f.isolation} onChange={(v) => set("isolation", v)} label="Client-isolatie" hint="Apparaten op dit netwerk kunnen elkaar niet bereiken. Gebruikelijk voor gasten." />
        {f.security !== "open" && <Check checked={f.ft} onChange={(v) => set("ft", v)} label="Snelle roaming (802.11r)" hint="Clients roamen sneller tussen access points. Zet uit als een oud apparaat niet wil verbinden." />}
        <Check checked={f.hidden} onChange={(v) => set("hidden", v)} label="SSID verbergen" />
        <Check checked={f.enabled} onChange={(v) => set("enabled", v)} label="SSID actief" />
      </form>
    </Modal>
  );
}

function PlanModal({ siteId, prefix, onClose }: { siteId: number; prefix: string; onClose: () => void }) {
  const plan = useLoad(() => api.get(`/api/sites/${siteId}/wifi/plan`), [siteId]);
  const [result, setResult] = useState<any | null>(null);
  const { busy, run } = useAction();
  const apply = () => run("apply", async () => setResult(await api.post(`/api/sites/${siteId}/wifi/apply`)));
  const icon = (op: string) => op === "add" ? <Plus size={16} color="var(--ok)" /> : op === "remove" ? <Minus size={16} color="var(--bad)" /> : <RefreshCw size={15} className="muted" />;
  const groups = (items: any[]) => GROUP_ORDER.map((g) => [g, items.filter((o) => (o.group ?? "profiles") === g)] as [string, any[]]).filter(([, l]) => l.length);
  return (
    <Modal wide title={result ? "Resultaat" : `Wijzigingen voor ${plan.data?.controller ?? "de controller"}`} onClose={onClose}
      footer={result ? <button className="btn primary" onClick={onClose}>Sluiten</button>
        : <><button className="btn" onClick={onClose}>Annuleren</button>
          <button className="btn primary" disabled={!!busy || !plan.data?.ops.length} onClick={apply}><Busy on={!!busy}>Toepassen op de router</Busy></button></>}>
      {!plan.data ? <Loading error={plan.error} /> : result ? (
        <>
          <div className={`banner ${result.ok ? "ok" : "bad"}`} style={{ marginBottom: 12 }}>
            {result.ok ? "Alle stappen zijn uitgevoerd." : <>Niet alles is gelukt. Een fout stopt alleen de rest van zijn eigen groep: de andere groepen zijn wel uitgevoerd.
              {result.remaining > 0 && ` ${result.remaining} ${result.remaining === 1 ? "stap is" : "stappen zijn"} overgeslagen.`} De wifi-controle hieronder laat zien waar het pad nog breekt.</>}
          </div>
          {groups(result.results).map(([g, list]) => (
            <div key={g} className="plan-group">
              <h3 className="small-h">{GROUP_LABEL[g]}</h3>
              <ul className="steps">{list.map((r: any, i: number) => (
                <li key={i}>{r.skipped ? <Minus size={16} className="muted" /> : r.ok ? (r.warning ? <AlertTriangle size={15} color="var(--warn)" /> : <CheckIcon size={16} color="var(--ok)" />) : <X size={16} color="var(--bad)" />}
                  <div className={r.skipped ? "muted" : ""}>{r.text}{r.skipped && " (overgeslagen)"}
                    {r.error && <code style={{ color: "var(--bad)" }}>{r.error}</code>}{r.warning && <code style={{ color: "var(--warn)" }}>{r.warning} (geen probleem, het profiel geldt)</code>}</div></li>
              ))}</ul>
            </div>
          ))}
        </>
      ) : plan.data.ops.length === 0 ? <p className="muted">De router is al gelijk aan wat hier is ingesteld.</p> : (
        <>
          <p className="muted" style={{ marginBottom: 10 }}>
            MikroManager raakt alleen objecten aan waarvan de naam met <span className="mono">{prefix}-</span> begint. Wat je zelf in WinBox hebt gemaakt blijft staan.
          </p>
          {groups(plan.data.ops).map(([g, list]) => (
            <div key={g} className="plan-group">
              <h3 className="small-h">{GROUP_LABEL[g]}</h3>
              <ul className="steps">{list.map((o: any, i: number) => (
                <li key={i}>{icon(o.op)}<div>{o.text}{o.show && <code>{Object.entries(o.show).map(([k, v]) => `${k}=${v === "" ? '""' : v}`).join("  ")}</code>}</div></li>
              ))}</ul>
            </div>
          ))}
        </>
      )}
    </Modal>
  );
}

const GROUP_ORDER = ["profiles", "local", "capsman", "cleanup"];
const GROUP_LABEL: Record<string, string> = {
  profiles: "Profielen (gedeeld)", local: "Eigen radio's van de router, direct (zonder CAPsMAN)",
  capsman: "Access points via CAPsMAN", cleanup: "Opruimen",
};

/** Follows every SSID from radio to DHCP server and offers the safe repairs. */
function WifiCheck({ siteId, hints, pending, onChanged }: { siteId: number; hints: any[]; pending: boolean; onChanged: () => void }) {
  const c = useLoad(() => api.get(`/api/sites/${siteId}/wifi/check`), [siteId]);
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const { busy, run } = useAction();
  const fix = (key: string, body: any) => run(key, async () => {
    const r = await api.post(`/api/sites/${siteId}/wifi/check/fix`, body);
    await c.reload(); onChanged();
    if (r.failed.length) throw new Error(`Niet gelukt: ${r.failed.join("; ")}`);
  }, "Gerepareerd");
  const d = c.data;
  const Icon = ({ ok }: { ok: boolean | null }) => ok === true ? <CircleCheck size={16} color="var(--ok)" /> : ok === false ? <CircleX size={16} color="var(--bad)" /> : <AlertTriangle size={15} color="var(--warn)" />;
  const Item = ({ i }: { i: any }) => (
    <li className="chk-item">
      <Icon ok={i.ok} />
      <div className="grow"><div className={i.ok ? "" : "strong"}>{i.text}</div>{i.detail && <div className="muted small">{i.detail}</div>}</div>
      {i.fixable && <button className="btn sm" disabled={!!busy} onClick={() => fix(i.id, { ids: [i.id] })}><Busy on={busy === i.id}><Wrench size={13} />{i.fix_label}</Busy></button>}
    </li>);
  const bad = (s: any) => s.items.filter((i: any) => i.ok === false).length;
  const warn = (s: any) => s.items.filter((i: any) => i.ok === null).length;
  const general = d?.general.filter((i: any) => i.ok !== true) ?? [];
  return (
    <section className="panel">
      <header>
        <div className="row" style={{ gap: 10 }}><Stethoscope size={18} className="muted" /><div><h2>Wifi-controle</h2>
          <div className="muted small">Van radio tot DHCP-server: bridge-poort, PVID, bridge-VLAN-tabel, VLAN-interface, DHCP</div></div></div>
        <div className="row">
          {d?.fixable > 0 && <button className="btn sm primary" disabled={!!busy} onClick={() => fix("all", { all: true })}><Busy on={busy === "all"}><Wrench size={13} />Alles repareren ({d.fixable})</Busy></button>}
          <button className="btn sm" disabled={!!busy} onClick={() => c.reload()}><RefreshCw size={14} />Opnieuw</button>
        </div>
      </header>
      {!d ? <Loading error={c.error} /> : (
        <>
          <div className={`chk-summary ${d.errors ? "bad" : d.warnings ? "warn" : "ok"}`}>
            <Icon ok={d.errors ? false : d.warnings ? null : true} />
            <span>{d.errors ? `${d.errors} ${d.errors === 1 ? "onderbreking" : "onderbrekingen"} gevonden: clients op die netwerken krijgen waarschijnlijk geen IP-adres.`
              : d.warnings ? "Elk netwerk heeft een pad, met een paar aandachtspunten." : "Elk netwerk heeft een volledig pad van radio tot DHCP-server."}
              {pending && " Er staan nog wifi-wijzigingen open; pas die eerst toe."}</span>
          </div>
          {general.length > 0 && <ul className="chk-list">{general.map((i: any) => <Item key={i.id} i={i} />)}</ul>}
          <div className="chk-ssids">
            {d.ssids.map((s: any) => {
              const isOpen = open[s.ssid] ?? bad(s) > 0;
              return (
                <div key={s.ssid} className="chk-ssid">
                  <button className="chk-head" onClick={() => setOpen((o) => ({ ...o, [s.ssid]: !isOpen }))} aria-expanded={isOpen}>
                    {isOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                    <Icon ok={bad(s) ? false : warn(s) ? null : true} />
                    <span className="strong">{s.ssid}</span>
                    <span className="muted small grow">{s.target}{s.scope !== "all" ? `, ${SCOPE[s.scope].toLowerCase()}` : ""}</span>
                    <span className={`tag ${bad(s) ? "bad" : warn(s) ? "warn" : "ok"}`}>{bad(s) ? `${bad(s)} ${bad(s) === 1 ? "probleem" : "problemen"}` : warn(s) ? "let op" : "in orde"}</span>
                  </button>
                  {isOpen && <ul className="chk-list inner">{s.items.map((i: any) => <Item key={i.id} i={i} />)}</ul>}
                </div>);
            })}
          </div>
          {hints.length > 0 && (
            <div className="chk-hints">
              <h3 className="small-h">Radio's en clients</h3>
              <ul className="chk-list">{hints.map((h: any, i: number) => (
                <li key={i} className="chk-item"><Icon ok={h.level === "warn" ? null : true} /><div className="grow">{h.text}</div></li>))}</ul>
            </div>
          )}
        </>
      )}
    </section>
  );
}

const DRIFT: Record<string, string> = {
  "configuration.ssid": "SSID", "security.ft": "802.11r", "security.ft-over-ds": "802.11r over DS", "security.passphrase": "wachtwoord",
  "security.authentication-types": "beveiliging", "datapath.vlan-id": "VLAN", "datapath.bridge": "bridge", "datapath.client-isolation": "client-isolatie",
  "channel.frequency": "kanaal", "channel.width": "kanaalbreedte", "channel.skip-dfs-channels": "DFS", "configuration.tx-power": "zendvermogen",
  "configuration.country": "land", "configuration.hide-ssid": "verborgen SSID", "configuration.mode": "modus", "configuration.manager": "manager",
  "extra SSID ontbreekt": "extra SSID ontbreekt", "overbodige extra SSID": "overbodige extra SSID",
};
const MODE: Record<string, [string, string]> = {
  site: ["Site-netwerken", "Dezelfde netwerken en instellingen als de access points: clients roamen naadloos tussen router en AP's."],
  own: ["Zelfstandig", "Eigen SSID's en instellingen, ingesteld bij het apparaat. Doet niet mee met de site-netwerken."],
  none: ["Niet beheerd", "MikroManager laat deze radio met rust; hij zendt uit wat er in RouterOS staat."],
};

/** The router's own radios: per radio site networks (like the CAPs), standalone, or left alone. */
function RouterRadios({ ap, siteId, wlans, busy, run, pending, onPlan, onOpen, reload }: any) {
  const { confirm } = useUi();
  const setMode = async (r: any, mode: string) => {
    if (mode === r.local_mode) return;
    const text: Record<string, any> = {
      site: <>De radio krijgt dezelfde SSID's, wachtwoorden, 802.11r en VLAN's als de access points{r.local_mode === "own" ? "; wat je zelfstandig had ingesteld vervalt" : ""}.
        Clients op deze radio verbinden kort opnieuw. <strong>Ben je zelf via deze radio verbonden, doe dit dan bekabeld.</strong></>,
      own: <>De radio blijft dezelfde SSID's uitzenden, maar de instellingen komen op de interface zelf te staan. Daarna stel je hem los in bij het apparaat;
        wijzigingen aan de site-netwerken gaan aan deze radio voorbij.</>,
      none: <>MikroManager haalt zijn extra SSID's van deze radio en laat hem verder met rust. De hoofd-SSID blijft uitzenden zoals hij nu staat.</>,
    };
    if (await confirm({ title: `${r.interface}: ${MODE[mode][0].toLowerCase()}?`, action: MODE[mode][0], danger: mode !== "site", text: text[mode] }))
      run(`mode${r.mac}`, async () => { await api.post(`/api/sites/${siteId}/wifi/radios/${encodeURIComponent(r.mac)}/mode`, { mode }); reload(); },
        `${r.interface}: ${MODE[mode][0].toLowerCase()}`);
  };
  return (
    <section className="panel">
      <header><div><h2>Radio's van de router</h2><div className="muted small">{ap.name} is ook de CAPsMAN-controller. Zijn eigen radio's stel je hier per radio in;
        CAPsMAN kan ze niet zelf beheren.</div></div></header>
      <div className="rr-list">
        {ap.radios.map((r: any) => (
          <div key={r.mac} className="rr">
            <div className="rr-head">
              <div className="grow">
                <div className="row" style={{ gap: 8 }}><span className="strong nowrap">{bandLabel(r.band)}</span><span className="mono muted small">{r.interface}</span>
                  {r.local_mode === "site" && (r.drift?.length ? <span className="tag warn">wijkt af</span> : <span className="tag ok">gelijk aan de AP's</span>)}</div>
                <div className="muted small">{r.ssids.length ? r.ssids.join(", ") : "geen SSID"} · {r.frequency ? `kanaal ${chanNo(r.frequency)}` : "kanaal onbekend"}
                  {r.tx_power ? ` · ${r.tx_power} dBm` : ""} · {r.clients} {r.clients === 1 ? "client" : "clients"}</div>
              </div>
              <div className="seg" role="tablist" aria-label={`Beheer van ${r.interface}`}>
                {(["site", "own", "none"] as const).map((m) => (
                  <button key={m} role="tab" aria-selected={r.local_mode === m} className={r.local_mode === m ? "on" : ""} disabled={!!busy || (m === "site" && !wlans.length)}
                    title={MODE[m][1]} onClick={() => setMode(r, m)}>{MODE[m][0]}</button>))}
              </div>
            </div>
            <p className="muted small rr-note">{MODE[r.local_mode ?? "none"][1]}</p>
            {r.local_mode === "site" && r.drift?.length > 0 && (
              <div className="banner warn small rr-banner"><span className="grow">Wijkt af van de access points: <strong>{r.drift.map((k: string) => DRIFT[k] ?? k).join(", ")}</strong>.
                {pending ? " Pas de wijzigingen toe om het recht te zetten." : " Waarschijnlijk in WinBox aangepast."}</span>
                {pending && <button className="btn sm primary" onClick={onPlan}>Bekijken en toepassen</button>}</div>)}
            <div className="row rr-actions">
              {r.local_mode === "site" && <button className="btn sm" onClick={() => onOpen(r)}>SSID's, kanaal en vermogen</button>}
              {r.local_mode === "own" && <a className="btn sm" href={`#/devices/${ap.device_id}`}>Instellen bij het apparaat</a>}
              <button className="btn sm" onClick={() => onOpen({ ...r, insightOnly: true })}>Clients en omgeving</button>
              {busy === `mode${r.mac}` && <Busy on>Bezig…</Busy>}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

/** Per SSID: on which access points, and whether clients can roam between them. */
function Roaming({ items }: { items: any[] }) {
  return (
    <section className="panel">
      <header><div><h2>Naadloos roamen</h2><div className="muted small">Zelfde SSID, wachtwoord, VLAN en 802.11r op de router en alle access points</div></div></header>
      <div className="table-wrap"><table className="t">
        <thead><tr><th>SSID</th><th>Uitgezonden door</th><th>802.11r</th><th>802.11k/v</th><th>Status</th></tr></thead>
        <tbody>{items.map((x) => (
          <tr key={x.ssid}>
            <td className="strong">{x.ssid}</td>
            <td className="small">{x.aps === 0 ? <span className="muted">nergens</span> : [...new Set(x.radios.map((r: any) => r.ap))].join(", ")}</td>
            <td>{x.ft ? <span className="tag ok">aan</span> : <span className="tag">uit</span>}</td>
            <td>{x.steering ? <span className="tag ok">aan</span> : <span className="tag">uit</span>}</td>
            <td className="small">{x.issues.length ? <span className="roam-issues">{x.issues.map((i: string) => <span key={i} className="row" style={{ gap: 6, alignItems: "flex-start" }}>
              <AlertTriangle size={14} color="var(--warn)" style={{ flex: "none", marginTop: 2 }} />{i}</span>)}</span>
              : x.aps > 1 ? <span className="row" style={{ gap: 6 }}><CircleCheck size={15} color="var(--ok)" />roamen op {x.aps} plekken</span>
                : <span className="muted">op één plek, roamen niet van toepassing</span>}</td>
          </tr>))}</tbody>
      </table></div>
    </section>
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
          <Field label="CAPsMAN" hint={s.capsman === "off" ? "MikroManager schrijft geen provisioning-regels. CAPsMAN zelf blijft zoals hij op de router staat."
            : s.capsman === "on" ? "Provisioning-regels staan er altijd, ook zonder access points."
              : "Provisioning-regels en CAPsMAN pas zodra er een access point is. De eigen radio's van de router hebben CAPsMAN nooit nodig."}>
            <select className="input" value={s.capsman ?? "auto"} onChange={(e) => set("capsman", e.target.value)}>
              <option value="auto">Automatisch (alleen met access points)</option><option value="on">Altijd</option><option value="off">Uit</option></select></Field>
          <div className="field" style={{ alignContent: "end" }}>
            <Check checked={!!s.steering} onChange={(v) => set("steering", v)} label="Roaming-hulp (802.11k/v)"
              hint="Een steering-profiel met rrm en wnm: AP's vertellen clients welke buren er zijn en kunnen een betere voorstellen." />
          </div>
        </div>
        <div className="two">
          <Field label="DFS-kanalen (5 GHz)" hint="Op DFS-kanalen doet een AP eerst een CAC (1 tot 10 minuten radardetectie) voordat hij uitzendt.">
            <select className="input" value={s.skip_dfs} onChange={(e) => set("skip_dfs", e.target.value)}>
              <option value="disabled">Alle kanalen gebruiken</option><option value="10min-cac">Kanalen met 10 minuten CAC overslaan</option><option value="all">Alle DFS-kanalen overslaan</option></select></Field>
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

const TX_LABEL: Record<string, string> = { manual: "Handmatig", low: "Laag", medium: "Midden", high: "Hoog" };
const WIDTH: Record<string, string> = { "20mhz": "20 MHz", "20/40mhz": "20/40 MHz", "20/40/80mhz": "20/40/80 MHz", "20/40/80/160mhz": "20/40/80/160 MHz" };
/** Channel number of a centre frequency: 2412 -> 1, 5180 -> 36, 5955 -> 1 (6 GHz). */
const chanNo = (f: number) => (f >= 5950 ? (f - 5950) / 5 : f >= 5000 ? (f - 5000) / 5 : f === 2484 ? 14 : (f - 2407) / 5);
const dfs = (f: number) => f >= 5260 && f <= 5720;

function TxModal({ siteId, ap, r, deviceId, wlans, onClose, onSaved }: { siteId: number; ap: string; r: any; deviceId?: number; wlans: any[]; onClose: () => void; onSaved: () => void }) {
  const [tab, setTab] = useState<"set" | "insight">(r.standalone || r.tx?.own || r.insightOnly || r.local_mode === "own" || r.local_mode === "none" ? "insight" : "set");
  const [mode, setMode] = useState<string>(r.tx?.mode ?? "high");
  const [power, setPower] = useState(String(r.tx?.power ?? r.tx_power ?? ""));
  const [freq, setFreq] = useState<string>(r.tx?.freq ?? "");
  const [width, setWidth] = useState<string>(r.tx?.width ?? "");
  const [off, setOff] = useState<boolean>(!!r.tx?.off);
  const onBand = wlans.filter((w) => w.enabled && w.bands.includes(r.band) && (r.local ? w.scope !== "caps" : w.scope !== "local"));
  const [ssids, setSsids] = useState<number[] | null>(r.tx?.ssids ?? null);
  const { busy, run } = useAction();
  const max = r.tx?.max;
  const hint: Record<string, string> = {
    high: `Geen limiet: RouterOS gebruikt het maximum dat in het land op dit kanaal mag (${max} dBm). Standaard.`,
    medium: `${r.tx?.presets?.medium} dBm: 6 dB onder het maximum (een kwart van het vermogen). Goed voor meerdere AP's dicht bij elkaar.`,
    low: `${r.tx?.presets?.low} dBm: 12 dB onder het maximum. Kleine cel, bijvoorbeeld een AP per kamer.`,
    manual: `Vaste waarde in dBm, 1 tot ${max}. Hoger dan het maximum kan niet; RouterOS begrenst het dan zelf.`,
  };
  const known: number[] = r.channels ?? [];
  const custom = !!freq && !known.includes(Number(freq));
  const toggle = (id: number, on: boolean) => {
    const cur = ssids ?? onBand.map((w) => w.id);
    const next = on ? [...cur, id] : cur.filter((x) => x !== id);
    setSsids(next.length === onBand.length && onBand.every((w) => next.includes(w.id)) ? null : next);
  };
  const save = () => run("tx", async () => {
    await api.post(`/api/sites/${siteId}/wifi/radios/${encodeURIComponent(r.mac)}`, { mode, power: mode === "manual" ? Number(power) : null, freq, width, ssids, off });
    onSaved();
  }, "Opgeslagen. Pas de wijzigingen toe om ze op de radio te zetten.");
  const standalone = r.standalone || r.tx?.own || r.local_mode === "own" || r.local_mode === "none";
  return (
    <Modal wide title={`Radio ${ap}, ${bandLabel(r.band)}`} onClose={onClose}
      footer={tab === "set" && !standalone ? <><button className="btn" onClick={onClose}>Annuleren</button>
        <button className="btn primary" disabled={!!busy || (mode === "manual" && !power)} onClick={save}>Opslaan</button></>
        : <button className="btn" onClick={onClose}>Sluiten</button>}>
      <div style={{ marginBottom: 14 }}><Seg value={tab} onChange={setTab} options={[["set", "Instellingen"], ["insight", "Clients en omgeving"]]} /></div>
      {tab === "insight" ? <RadioInsight siteId={siteId} r={r} /> : standalone ? (
        <div className="form">
          {r.local_mode === "none"
            ? <p>MikroManager <strong>beheert deze radio niet</strong>. Kies bij Radio's van de router 'Site-netwerken' of 'Zelfstandig' om hem in te stellen.</p>
            : <p>Deze radio is <strong>zelfstandig</strong>: SSID's, wachtwoorden, kanaal en zendvermogen staan op het apparaat zelf, los van de wifi-netwerken van de site.</p>}
          {deviceId && r.local_mode !== "none" && <a className="btn primary" style={{ width: "fit-content" }} href={`#/devices/${deviceId}`}>Instellen bij het apparaat</a>}
        </div>
      ) : (
      <div className="form">
        <div className="spread">
          <h3 className="small-h" style={{ marginTop: 0 }}>Netwerken op deze radio</h3>
          <Check checked={!off} onChange={(v) => setOff(!v)} label="Radio aan" />
        </div>
        {!off && (onBand.length === 0 ? <p className="muted small">Geen wifi-netwerken op {bandLabel(r.band)}{r.local ? " voor de router" : " voor de access points"}.</p> : (
          <div className="ssid-pick">
            {onBand.map((w) => <Check key={w.id} checked={ssids === null || ssids.includes(w.id)} onChange={(v) => toggle(w.id, v)}
              label={w.ssid} hint={w.vlan_id ? `VLAN ${w.vlan_id}` : "LAN"} />)}
          </div>))}
        <p className="muted small">{off ? "De radio zendt niets uit." : ssids === null ? "Alle netwerken van de site op deze band. Nieuwe netwerken komen er vanzelf bij."
          : ssids.length === 0 ? "Geen netwerk gekozen: de radio gaat uit." : "Alleen de gekozen netwerken. Nieuwe netwerken komen er niet vanzelf bij."}</p>

        <h3 className="small-h">Kanaal</h3>
        <div className="row" style={{ alignItems: "flex-start" }}>
          <Field label="Kanaal" hint={freq ? (dfs(Number(freq)) ? "DFS-kanaal: de radio doet eerst een CAC en wijkt uit bij radar." : "Vast kanaal voor deze radio.") : "Volgt de radio-instellingen van de site."}>
            {known.length > 0 && !custom ? (
              <select className="input" value={freq} onChange={(e) => setFreq(e.target.value)}>
                <option value="">Automatisch (site-instelling)</option>
                {known.map((f) => <option key={f} value={String(f)}>{chanNo(f)} ({f} MHz){dfs(f) ? " DFS" : ""}</option>)}
              </select>
            ) : <input className="input mono" value={freq} onChange={(e) => setFreq(e.target.value)} placeholder="automatisch, of bijv. 5180" />}
          </Field>
          <Field label="Kanaalbreedte"><select className="input" value={width} onChange={(e) => setWidth(e.target.value)}>
            <option value="">Site-instelling</option>
            {(r.widths ?? []).map((x: string) => <option key={x} value={x}>{WIDTH[x] ?? x}</option>)}</select></Field>
        </div>
        <p className="muted small">Nu: {r.frequency ? `kanaal ${chanNo(r.frequency)} (${r.frequency} MHz)` : "onbekend"}. Geef access points die elkaar kunnen horen elk een eigen kanaal:
          op 2,4 GHz alleen 1, 6 of 11. Onder <b>Clients en omgeving</b> meet je welke kanalen druk zijn.</p>

        <h3 className="small-h">Zendvermogen</h3>
        <div className="seg" role="tablist" style={{ width: "fit-content" }}>
          {["manual", "low", "medium", "high"].map((m) => (
            <button key={m} type="button" role="tab" aria-selected={m === mode} className={m === mode ? "on" : ""} onClick={() => setMode(m)}>{TX_LABEL[m]}</button>
          ))}
        </div>
        {mode === "manual" && <Field label="Zendvermogen (dBm)"><input className="input mono" inputMode="numeric" value={power} onChange={(e) => setPower(e.target.value)} style={{ width: 110 }} /></Field>}
        <p className="muted small">{hint[mode]}</p>
        <dl className="kv small">
          <dt>Maximum op dit kanaal</dt><dd>{max} dBm{r.tx?.max_reported ? " (current-max-reg-power van de radio)" : " (EU-grens, de radio gaf geen waarde)"}</dd>
          <dt>Nu volgens de radio</dt><dd>{r.tx_power ? `${r.tx_power} dBm` : "onbekend"}</dd>
        </dl>
        {r.managed || r.tx?.off
          ? <p className="muted small">Wordt per radio ingesteld met een eigen profiel of provisioning-regel. Clients op deze radio verbinden bij het toepassen kort opnieuw.
            {r.local && deviceId && <> Wil je deze radio helemaal los instellen? Kies dan <a href={`#/devices/${deviceId}`}>Zelfstandig maken</a> bij het apparaat.</>}</p>
          : <div className="banner info small">Deze radio zendt nog niet de wifi-netwerken van MikroManager uit. De instelling wordt bewaard en
            gaat in zodra de radio beheerd wordt: adopteer het access point (of kies bij de router <b>Radio's overnemen</b>) en pas de wijzigingen toe.</div>}
      </div>)}
    </Modal>
  );
}

/** QR code that phones understand as "join this wifi network". The picture is made in the browser; nothing is sent anywhere. */
function QrModal({ wlan, site, onClose }: { wlan: any; site: string; onClose: () => void }) {
  const esc = (v: string) => v.replace(/([\\;,:"])/g, "\\$1");
  const text = `WIFI:T:${wlan.security === "open" ? "nopass" : "WPA"};S:${esc(wlan.ssid)};${wlan.security === "open" ? "" : `P:${esc(wlan.passphrase)};`}${wlan.hidden ? "H:true;" : ""};`;
  const q = qrcode(0, "M");
  q.addData(text);
  q.make();
  const n = q.getModuleCount(), quiet = 4, size = n + quiet * 2;
  const cells: string[] = [];
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) if (q.isDark(y, x)) cells.push(`M${x + quiet},${y + quiet}h1v1h-1z`);
  const print = () => { document.body.classList.add("print-qr"); window.print(); setTimeout(() => document.body.classList.remove("print-qr"), 500); };
  return (
    <Modal title={`Verbinden met ${wlan.ssid}`} onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Sluiten</button><button className="btn primary" onClick={print}>Afdrukken</button></>}>
      <div className="qr-card">
        <svg viewBox={`0 0 ${size} ${size}`} width="240" height="240" role="img" aria-label={`QR-code voor wifi-netwerk ${wlan.ssid}`} shapeRendering="crispEdges">
          <rect width={size} height={size} fill="#fff" /><path d={cells.join("")} fill="#000" />
        </svg>
        <div>
          <div className="muted small">{site}</div>
          <h3 style={{ margin: "2px 0 10px" }}>{wlan.ssid}</h3>
          {wlan.security !== "open" && <><div className="muted small">Wachtwoord</div><div className="mono" style={{ fontSize: 16, overflowWrap: "anywhere" }}>{wlan.passphrase}</div></>}
          <p className="muted small" style={{ marginTop: 12 }}>Scan met de camera van je telefoon om te verbinden.</p>
        </div>
      </div>
      {wlan.security === "wpa3" && <p className="muted small" style={{ marginTop: 10 }}>Dit netwerk is alleen WPA3. Oudere telefoons kunnen de QR-code wel scannen maar niet verbinden.</p>}
    </Modal>
  );
}
