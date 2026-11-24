import { FormEvent, useEffect, useState } from "react";
import qrcode from "qrcode-generator";
import { AlertTriangle, Check as CheckIcon, ChevronDown, ChevronRight, CircleCheck, CircleX, Eye, EyeOff, Lock, LockOpen, Minus, Pencil, Plus, QrCode, RefreshCw, Router as RouterIcon, Settings2, Sparkles, Stethoscope, Wifi as WifiIcon, Wrench, X } from "lucide-react";
import { api } from "../api";
import { useApp, useHash } from "../App";
import { bandLabel, Busy, Check, Drawer, Field, Loading, Modal, Seg, useAction, useLoad, useUi } from "../ui";
import { DeviceRadios, RadioInsight } from "./LocalWifi";

const SECURITY: Record<string, string> = { wpa2wpa3: "WPA2 + WPA3", wpa2: "WPA2", wpa3: "WPA3", open: "Open" };
const target = (n: any, siteBridge: string) => n.vlan_id ? `VLAN ${n.vlan_id}${n.bridge && n.bridge !== siteBridge ? ` op ${n.bridge}` : ""}`
  : n.bridge && n.bridge !== siteBridge ? n.bridge : "LAN (geen VLAN)";

/** A radio that carries the site's networks: an access point radio via CAPsMAN, or a router radio set to "site-netwerken". */
const siteRadio = (r: any) => !r.standalone && (!r.local || r.local_mode === "site");
const macOf = (r: any) => String(r.mac ?? "").toUpperCase();

/** Access points that can carry a network on the given bands, and the ones that do. */
function apsFor(aps: any[], bands: string[]) {
  return aps.filter((a) => a.radios.some((r: any) => siteRadio(r) && bands.includes(r.band)));
}
function placementOf(aps: any[], w: any) {
  const candidates = apsFor(aps, w.bands);
  const on = new Set<string>(w.radios ?? []);
  const carrying = candidates.filter((a) => a.radios.some((r: any) => on.has(macOf(r))));
  return { candidates, carrying };
}

/** What happened after a save: applied right away, rolled back, or only saved. */
export function useApplyToast() {
  const { toast } = useUi();
  return (res: any, saved = "Opgeslagen") => {
    const a = res?.apply;
    if (!a) { toast(`${saved}. Pas de wijzigingen toe om ze op de router te zetten.`); return true; }
    if (a.ok) { toast(`${saved} en toegepast`); return true; }
    if (a.rolled_back) { toast(`Niet gelukt en teruggedraaid: ${a.error}`, true); return false; }
    toast(a.error || `${saved}, maar niet toegepast`, true);
    return true;
  };
}

export default function Wifi() {
  const { site, reloadSites } = useApp();
  const parts = useHash();
  const w = useLoad(() => api.get(`/api/sites/${site.id}/wifi`), [site.id], 10000);
  const [edit, setEdit] = useState<any | "new" | null>(null);
  const [plan, setPlan] = useState(false);
  const [chanPlan, setChanPlan] = useState(false);
  const [apOpen, setApOpen] = useState<string | null>(null);
  const [qr, setQr] = useState<any | null>(null);
  const [showDefaults, setShowDefaults] = useState(false);
  const { busy, run } = useAction();
  const { confirm } = useUi();

  // #/wifi/ap/<device id> opens that access point (the link from the device page)
  const linked = parts[1] === "ap" ? decodeURIComponent(parts[2] ?? "") : null;
  useEffect(() => {
    if (!linked || !w.data) return;
    const ap = w.data.aps.find((a: any) => String(a.device_id) === linked || a.name === linked);
    if (ap) setApOpen(ap.name);
    history.replaceState(null, "", "#/wifi");
  }, [linked, !!w.data]);

  if (!w.data) return <Loading error={w.error} />;
  const d = w.data;

  if (!d.controller) {
    return (<><div className="page-head"><h1>Wifi</h1></div>
      <div className="panel"><div className="empty"><h3>Eerst een router nodig</h3>
        <p>De router van de site wordt de wifi-controller (CAPsMAN). Voeg hem toe, daarna stel je hier de netwerken in.</p>
        <a className="btn primary" href="#/devices">Router toevoegen</a></div></div></>);
  }
  const stuckLocal = d.aps.some((ap: any) => ap.local && ap.radios.some((r: any) => r.provisioned_local));
  const repair = () => run("local", async () => { await api.post(`/api/sites/${site.id}/wifi/local-radios`, { action: "take" }); w.reload(); }, "Radio's hersteld");
  const adopt = async (ap: any) => {
    if (await confirm({ title: `${ap.name} adopteren?`, action: "Adopteren",
      text: "De radio's worden voortaan door de controller ingesteld en zenden de netwerken van de site uit. De huidige wifi-instellingen op het apparaat zelf vervallen." }))
      run(`adopt${ap.device_id}`, async () => { await api.post(`/api/devices/${ap.device_id}/adopt`); w.reload(); }, "Access point geadopteerd");
  };
  const open = d.aps.find((a: any) => a.name === apOpen);
  const managedRadios = d.aps.reduce((n: number, a: any) => n + a.radios.filter(siteRadio).length, 0);
  const auto = d.settings.auto_apply !== false;
  const s = d.settings;

  return (
    <div className="stack">
      <div className="page-head" style={{ marginBottom: 0 }}>
        <div><h1>Wifi</h1><p>Eén set netwerken voor {site.name}, op de router en alle access points.{auto ? " Wijzigingen gaan direct naar de router." : ""}</p></div>
        <button className="btn primary" onClick={() => setEdit("new")}><Plus size={16} />Netwerk toevoegen</button>
      </div>

      {!d.controller.has_wifi_menu && d.controller.online && (
        <div className="banner bad">Op {d.controller.name} ontbreekt het wifi-menu. Installeer het pakket wifi-qcom (of wifi-qcom-ac) en RouterOS 7.13 of nieuwer.</div>
      )}
      {d.pending.error && <div className="banner bad">Controller niet te lezen: {d.pending.error}</div>}
      {d.pending.count > 0 && (
        <div className="banner warn">
          <span className="grow"><strong>{d.pending.count === 1 ? "1 wijziging staat" : `${d.pending.count} wijzigingen staan`} nog niet op de router.</strong>
            {auto ? " Bijvoorbeeld omdat er in WinBox iets is aangepast, of de router even onbereikbaar was." : " Bekijk eerst wat er verandert."}</span>
          <button className="btn primary" onClick={() => setPlan(true)}>Bekijken en toepassen</button>
        </div>
      )}
      {stuckLocal && (
        <div className="banner bad"><span className="grow"><strong>De eigen radio's van {d.controller.name} zijn geprovisioned door een eerdere versie van MikroManager.</strong> Dat werkt slecht; herstel ze.</span>
          <button className="btn sm primary" disabled={!!busy} onClick={repair}>Herstellen</button></div>
      )}

      <section className="panel">
        <header><h2>Netwerken</h2></header>
        {d.wlans.length === 0 ? (
          <div className="empty"><h3>Nog geen wifi-netwerken</h3><p>Maak je eerste netwerk: naam, wachtwoord en klaar.</p>
            <button className="btn primary" onClick={() => setEdit("new")}>Netwerk toevoegen</button></div>
        ) : (
          <div className="table-wrap fit"><table className="t">
            <thead><tr><th>Naam (SSID)</th><th>Netwerk</th><th className="hide-sm">Banden</th><th className="hide-sm">Access points</th><th className="hide-sm">Beveiliging</th><th /></tr></thead>
            <tbody>{d.wlans.map((n: any) => {
              const p = placementOf(d.aps, n);
              return (
                <tr key={n.id} className={`click ${n.enabled ? "" : "off"}`} onClick={() => setEdit(n)}>
                  <td className="strong"><span className="row" style={{ gap: 8 }}>{n.security === "open" ? <LockOpen size={15} className="muted" /> : <Lock size={15} className="muted" />}{n.ssid}
                    {!n.enabled && <span className="tag">Uit</span>}{n.hidden && <span className="tag">verborgen</span>}</span></td>
                  <td className="nowrap">{target(n, s.bridge)}</td>
                  <td className="nowrap hide-sm">{n.bands.map(bandLabel).join(" + ")}</td>
                  <td className="nowrap hide-sm">{p.candidates.length === 0 ? <span className="muted">–</span>
                    : p.carrying.length === p.candidates.length ? "Alle" : p.carrying.length === 0 ? <span className="tag warn">nergens</span>
                      : <span title={p.carrying.map((a) => a.name).join(", ")}>{p.carrying.length} van {p.candidates.length}</span>}</td>
                  <td className="small hide-sm">{SECURITY[n.security]}{n.ft && n.security !== "open" ? ", 802.11r" : ""}{n.isolation ? ", isolatie" : ""}</td>
                  <td className="right nowrap" onClick={(e) => e.stopPropagation()}>
                    <button className="btn sm icon" onClick={() => setQr(n)} title="QR-code om te verbinden" aria-label="QR-code"><QrCode size={16} /></button>
                    <button className="btn sm icon" onClick={() => setEdit(n)} title="Bewerken" aria-label="Bewerken"><Pencil size={15} /></button></td>
                </tr>);
            })}</tbody>
          </table></div>
        )}
      </section>

      <section className="panel">
        <header><h2>Access points</h2>
          <div className="row">
            <button className="btn sm" disabled={!managedRadios} onClick={() => setChanPlan(true)} title="Kanalen kiezen die elkaar niet storen"><Sparkles size={14} />Kanaalplan</button>
            <button className="btn sm icon" onClick={() => w.reload()} title="Vernieuwen" aria-label="Vernieuwen"><RefreshCw size={15} /></button>
          </div></header>
        {d.aps.length === 0 ? (
          <div className="empty"><p>Geen radio's gevonden. Voeg een access point toe onder Apparaten.</p><a className="btn" href="#/devices">Naar apparaten</a></div>
        ) : (
          <div className="ap-list">{d.aps.map((ap: any) => {
            const status = apStatus(ap);
            const clients = ap.radios.reduce((n: number, r: any) => n + (r.clients || 0), 0);
            const canOpen = ap.radios.length > 0 || ap.standalone;
            return (
              <div key={ap.name} className={`ap-row ${canOpen ? "" : "static"}`} role="button" tabIndex={0} onClick={() => canOpen && setApOpen(ap.name)}
                onKeyDown={(e) => e.key === "Enter" && canOpen && setApOpen(ap.name)}>
                <div className="ap-id">
                  <span className={`ap-ico ${ap.local ? "router" : ""}`}>{ap.local ? <RouterIcon size={18} /> : <WifiIcon size={18} />}</span>
                  <div style={{ minWidth: 0 }}>
                    <div className="strong ellipsis" style={{ maxWidth: "none" }}>{ap.name}</div>
                    <div className="muted small">{[ap.local ? "router + controller" : ap.board, ap.address].filter(Boolean).join(" · ")}</div>
                  </div>
                </div>
                <div className="ap-radios">{ap.radios.length ? ap.radios.map((r: any) => (
                  <span key={r.mac} className={`radio-chip ${r.tx?.off || r.off || (r.local && r.local_mode === "none") ? "off" : ""}`}>
                    <b>{bandLabel(r.band)}</b>{r.frequency ? ` kan. ${chanNo(r.frequency)}` : ""}{r.tx_power ? ` · ${r.tx_power} dBm` : ""}
                    {r.local && r.local_mode === "own" ? <span className="tag accent" style={{ marginLeft: 6 }}>zelfstandig</span> : null}
                    {r.drift?.length ? <span className="tag warn" style={{ marginLeft: 6 }}>wijkt af</span> : null}</span>))
                  : <span className="muted small">{ap.adoptable ? "nog niet geadopteerd" : "wacht op de controller"}</span>}</div>
                <div className="ap-clients num">{clients}<span className="muted small"> {clients === 1 ? "client" : "clients"}</span></div>
                <div className="ap-status">
                  {ap.adoptable && <button className="btn sm primary" disabled={!!busy} onClick={(e) => { e.stopPropagation(); adopt(ap); }}><Busy on={busy === `adopt${ap.device_id}`}>Adopteren</Busy></button>}
                  <span className={`tag ${status[1]}`}>{status[0]}</span>
                  {canOpen ? <ChevronRight size={16} className="muted" /> : <span style={{ width: 16 }} />}
                </div>
              </div>);
          })}</div>
        )}
      </section>

      {d.roaming?.some((x: any) => x.aps > 1 || x.issues.length) && <Roaming items={d.roaming} />}
      {d.wlans.length > 0 && <WifiCheck siteId={site.id} hints={d.hints ?? []} pending={d.pending.count > 0} onChanged={() => w.reload()} />}

      <section className="panel">
        <button className="panel-toggle" onClick={() => setShowDefaults(!showDefaults)} aria-expanded={showDefaults}>
          {showDefaults ? <ChevronDown size={16} /> : <ChevronRight size={16} />}<h2>Radio-standaarden</h2>
          <span className="muted small grow hide-sm">{[s.country, `2,4 GHz ${WIDTH[s.ch2_width] ?? s.ch2_width}`, `5 GHz ${WIDTH[s.ch5_width] ?? s.ch5_width}`,
            s.skip_dfs === "all" ? "geen DFS" : s.skip_dfs === "10min-cac" ? "DFS zonder 10 min CAC" : "DFS toegestaan", s.steering ? "802.11k/v aan" : null].filter(Boolean).join(" · ")}</span></button>
        {showDefaults && <RadioDefaults site={site} onSaved={() => { reloadSites(); w.reload(); }} />}
      </section>

      {edit && <WlanForm siteId={site.id} aps={d.aps} siteBridge={s.bridge} wlan={edit === "new" ? null : edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); w.reload(); }} />}
      {plan && <PlanModal siteId={site.id} prefix={d.settings.prefix ?? "tc"} onClose={() => { setPlan(false); w.reload(); }} />}
      {qr && <QrModal wlan={qr} site={site.name} onClose={() => setQr(null)} />}
      {open && <ApDrawer siteId={site.id} ap={open} wlans={d.wlans} onClose={() => setApOpen(null)} reload={() => w.reload()} onAdopt={() => adopt(open)} />}
      {chanPlan && <ChannelPlanModal siteId={site.id} onClose={() => { setChanPlan(false); w.reload(); }} />}
    </div>
  );
}

function apStatus(ap: any): [string, string] {
  if (ap.local) {
    if (ap.radios.some((r: any) => r.drift?.length)) return ["Wijkt af", "warn"];
    const modes = new Set(ap.radios.map((r: any) => r.local_mode));
    if (modes.size === 1 && modes.has("none")) return ["Niet beheerd", ""];
    return ["Online", "ok"];
  }
  if (ap.adoptable || ap.standalone) return ["Zelfstandig", "accent"];
  return ap.state === "Ok" ? ["Online", "ok"] : [ap.state ?? "?", "warn"];
}

function WlanForm({ siteId, wlan, aps, siteBridge, onClose, onSaved }: { siteId: number; wlan: any | null; aps: any[]; siteBridge: string; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({
    ssid: wlan?.ssid ?? "", passphrase: wlan?.passphrase ?? "", security: wlan?.security ?? "wpa2wpa3", vlan_id: wlan?.vlan_id ?? "",
    bands: wlan?.bands ?? ["2g", "5g"], hidden: wlan?.hidden ?? false, isolation: wlan?.isolation ?? false, ft: wlan?.ft ?? true, enabled: wlan?.enabled ?? true,
    bridge: wlan?.bridge ?? "",
  });
  const tg = useLoad(() => api.get(`/api/sites/${siteId}/wifi/targets`), [siteId]);
  const tBridge: string = tg.data?.site_bridge ?? siteBridge ?? "";
  const targets: any[] = tg.data?.targets ?? [];
  const keyOf = (bridge: string, vlan: any) => `${bridge || tBridge}|${vlan ?? ""}`;
  const current = keyOf(f.bridge, f.vlan_id === "" ? null : f.vlan_id);
  const [custom, setCustom] = useState(false);
  const [adv, setAdv] = useState(false);
  const known = targets.some((x) => keyOf(x.bridge, x.vlan_id) === current);
  const pick = (v: string) => {
    if (v === "custom") { setCustom(true); return; }
    setCustom(false);
    const [b, vl] = v.split("|");
    setF((o) => ({ ...o, bridge: b === tBridge ? "" : b, vlan_id: vl }));
  };
  const ownBridge = !!f.bridge && f.bridge !== tBridge;
  const set = (k: string, v: any) => setF((o) => ({ ...o, [k]: v }));

  // Where it is broadcast: every access point (also ones added later), or a choice of access points.
  const all = apsFor(aps, ["2g", "5g"]);
  const initial = wlan ? placementOf(aps, wlan) : null;
  const [everywhere, setEverywhere] = useState<boolean>(!initial || (wlan.scope === "all" && initial.carrying.length === initial.candidates.length));
  const [picked, setPicked] = useState<Set<string>>(new Set((initial ? initial.carrying : all).map((a: any) => a.name)));
  const choosable = apsFor(aps, f.bands);
  const chosen = choosable.filter((a) => picked.has(a.name));
  const capsChosen = everywhere ? choosable.some((a) => !a.local) : chosen.some((a) => !a.local);
  const bridgeProblem = ownBridge && !f.vlan_id && capsChosen;
  const togglePick = (name: string, on: boolean) => setPicked((p) => { const n = new Set(p); on ? n.add(name) : n.delete(name); return n; });
  const partial = (ap: any) => {
    if (!wlan) return null;
    const on = new Set<string>(wlan.radios ?? []);
    const rs = ap.radios.filter((r: any) => siteRadio(r) && f.bands.includes(r.band));
    const carried = rs.filter((r: any) => on.has(macOf(r)));
    return carried.length && carried.length < rs.length ? `nu alleen ${carried.map((r: any) => bandLabel(r.band)).join(", ")}` : null;
  };

  const [show, setShow] = useState(!wlan);
  const { busy, run } = useAction();
  const { confirm } = useUi();
  const done = useApplyToast();
  const band = (b: string, on: boolean) => set("bands", on ? [...f.bands, b] : f.bands.filter((x: string) => x !== b));
  const gen = () => {
    const words = ["zon", "maan", "fiets", "molen", "tulp", "kaas", "dijk", "wolk", "boom", "kade", "duin", "polder", "gracht", "brug"];
    const a = new Uint32Array(4); crypto.getRandomValues(a);
    set("passphrase", `${words[a[0] % words.length]}-${words[a[1] % words.length]}-${words[a[2] % words.length]}-${10 + (a[3] % 90)}`);
    setShow(true);
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    run("save", async () => {
      if (!everywhere && choosable.length && !chosen.length) throw new Error("Kies minstens één access point, of zet het netwerk uit onder Geavanceerd");
      const radios = everywhere ? null : chosen.flatMap((a) => a.radios.filter(siteRadio).map(macOf));
      const body = { ...f, bridge: f.bridge || null, radios };
      const res = wlan ? await api.patch(`/api/wlans/${wlan.id}`, body) : await api.post(`/api/sites/${siteId}/wifi/wlans`, body);
      if (done(res)) onSaved();
    });
  };
  const remove = async () => {
    if (await confirm({ title: `${wlan.ssid} verwijderen?`, action: "Verwijderen", danger: true,
      text: "Het netwerk verdwijnt van de router en alle access points. Clients erop vallen weg." }))
      run("del", async () => { const res = await api.del(`/api/wlans/${wlan.id}`); done(res, "Verwijderd"); onSaved(); });
  };
  return (
    <Modal title={wlan ? wlan.ssid : "Wifi-netwerk toevoegen"} onClose={onClose}
      footer={<>{wlan && <button className="btn danger" style={{ marginRight: "auto" }} onClick={remove} disabled={!!busy}>Verwijderen</button>}
        <button className="btn" onClick={onClose}>Annuleren</button>
        <button className="btn primary" form="wlanform" disabled={!!busy || bridgeProblem}><Busy on={busy === "save"}>{busy === "save" ? "Toepassen…" : "Opslaan"}</Busy></button></>}>
      <form id="wlanform" className="form" onSubmit={submit}>
        <Field label="Naam (SSID)"><input className="input" value={f.ssid} onChange={(e) => set("ssid", e.target.value)} maxLength={32} required autoFocus={!wlan} /></Field>
        {f.security !== "open" && (
          <Field label="Wachtwoord" hint="8 tot 63 tekens.">
            <div className="row"><input className="input mono" type={show ? "text" : "password"} value={f.passphrase} onChange={(e) => set("passphrase", e.target.value)} minLength={8} maxLength={63} required autoComplete="off" />
              <button type="button" className="btn icon" onClick={() => setShow(!show)} aria-label={show ? "Verberg wachtwoord" : "Toon wachtwoord"}>{show ? <EyeOff size={17} /> : <Eye size={17} />}</button>
              <button type="button" className="btn sm" onClick={gen} title="Een wachtwoord van vier woorden: sterk en makkelijk over te typen">Bedenk er een</button></div>
          </Field>)}
        <Field label="Netwerk" hint={custom ? undefined : "Waar clients van dit SSID uitkomen."}>
          {!tg.data ? <select className="input" disabled><option>Laden…</option></select> : (
            <select className="input" value={custom ? "custom" : current} onChange={(e) => pick(e.target.value)}>
              {!known && !custom && <option value={current}>{f.vlan_id ? `VLAN ${f.vlan_id}` : f.bridge || tBridge} (niet gevonden op de router)</option>}
              {targets.map((x) => (
                <option key={keyOf(x.bridge, x.vlan_id)} value={keyOf(x.bridge, x.vlan_id)}>
                  {x.vlan_id ? `${x.label} (VLAN ${x.vlan_id})` : x.bridge === tBridge ? `LAN (${x.bridge})` : `${x.bridge} (eigen bridge)`}{x.subnet ? `, ${x.subnet}` : ""}
                </option>
              ))}
              <option value="custom">Ander VLAN-ID…</option>
            </select>)}
          {custom && <input className="input" style={{ marginTop: 6 }} value={f.vlan_id} onChange={(e) => set("vlan_id", e.target.value)} inputMode="numeric" placeholder="VLAN-ID, 1 tot 4094" autoFocus />}
        </Field>
        <div className="field"><span>Frequentiebanden</span>
          <div className="row" style={{ gap: 22 }}>
            <Check checked={f.bands.includes("2g")} onChange={(v) => band("2g", v)} label="2,4 GHz" />
            <Check checked={f.bands.includes("5g")} onChange={(v) => band("5g", v)} label="5 GHz" />
          </div></div>
        {all.length > 0 && <div className="field"><span>Uitzenden op</span>
          <div className="seg" role="tablist" style={{ width: "fit-content" }}>
            <button type="button" role="tab" aria-selected={everywhere} className={everywhere ? "on" : ""} onClick={() => setEverywhere(true)}>Alle access points</button>
            <button type="button" role="tab" aria-selected={!everywhere} className={!everywhere ? "on" : ""} onClick={() => setEverywhere(false)}>Kiezen</button>
          </div>
          {everywhere ? <small>Ook op access points die je later adopteert.</small> : (
            <div className="ap-pick">{choosable.map((ap) => (
              <Check key={ap.name} checked={picked.has(ap.name)} onChange={(v) => togglePick(ap.name, v)}
                label={ap.local ? `${ap.name} (router)` : ap.name} hint={partial(ap) ?? undefined} />))}
              {choosable.length === 0 && <span className="muted small">Geen access points met {f.bands.map(bandLabel).join(" of ")}.</span>}
            </div>)}
          {bridgeProblem && <div className="banner warn small" style={{ marginTop: 6 }}>Een netwerk op een eigen bridge zonder VLAN kan niet naar de access points. Kies alleen de router, of gebruik een VLAN.</div>}
        </div>}
        <button type="button" className="disclosure" onClick={() => setAdv(!adv)} aria-expanded={adv}>{adv ? <ChevronDown size={15} /> : <ChevronRight size={15} />}Geavanceerd
          <span className="muted small">{[SECURITY[f.security], f.ft && f.security !== "open" ? "802.11r" : null, f.isolation ? "isolatie" : null, f.hidden ? "verborgen" : null,
            !f.enabled ? "uit" : null].filter(Boolean).join(", ")}</span></button>
        {adv && <div className="form adv">
          <Field label="Beveiliging" hint={f.security === "wpa3" ? "Oudere apparaten kunnen hier niet op verbinden." : f.security === "wpa2" ? "Voor IoT-apparaten die moeite hebben met WPA3." : undefined}>
            <select className="input" value={f.security} onChange={(e) => set("security", e.target.value)}>
              {Object.entries(SECURITY).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
          {f.security === "open" && <div className="banner warn small">Een open netwerk is voor iedereen binnen bereik toegankelijk en niet versleuteld.</div>}
          {f.security !== "open" && <Check checked={f.ft} onChange={(v) => set("ft", v)} label="Snelle roaming (802.11r)" hint="Clients stappen sneller over tussen router en access points. Zet uit als een oud apparaat niet wil verbinden." />}
          <Check checked={f.isolation} onChange={(v) => set("isolation", v)} label="Client-isolatie" hint="Apparaten op dit netwerk kunnen elkaar niet bereiken. Gebruikelijk voor gasten." />
          <Check checked={f.hidden} onChange={(v) => set("hidden", v)} label="SSID verbergen" />
          <Check checked={f.enabled} onChange={(v) => set("enabled", v)} label="SSID actief" />
        </div>}
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
  const [expanded, setExpanded] = useState(false);
  if (d && !d.errors && !d.warnings && !hints.some((h: any) => h.level === "warn") && !expanded)
    return (
      <div className="chk-mini"><CircleCheck size={16} color="var(--ok)" /><span className="grow"><strong>Wifi-controle:</strong> elk netwerk heeft een volledig pad van radio tot DHCP-server.</span>
        <button className="btn sm" onClick={() => setExpanded(true)}>Details</button></div>);
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
                    <span className="muted small grow">{s.target}{s.scope === "local" ? ", alleen de router" : s.scope === "caps" ? ", alleen de CAP's" : ""}</span>
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
  own: ["Zelfstandig", "Eigen SSID's en instellingen, hieronder per radio. Doet niet mee met de site-netwerken en het roamen."],
  none: ["Niet beheerd", "MikroManager laat deze radio met rust; hij zendt uit wat er in RouterOS staat."],
};

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

/** Defaults for every radio of the site: country, channel widths and channels per band, DFS, roaming help.
 * Per radio you can deviate from these in the access point panel. Controller settings live under Instellingen. */
function RadioDefaults({ site, onSaved }: { site: any; onSaved: () => void }) {
  const KEYS = ["country", "ch2_width", "ch2_freq", "ch5_width", "ch5_freq", "skip_dfs", "steering"];
  const pickKeys = (o: any) => Object.fromEntries(KEYS.map((k) => [k, o[k]]));
  const [s, setS] = useState<any>(pickKeys(site.settings));
  const set = (k: string, v: any) => setS((o: any) => ({ ...o, [k]: v }));
  const { busy, run } = useAction();
  const done = useApplyToast();
  const dirty = JSON.stringify(s) !== JSON.stringify(pickKeys(site.settings));
  const save = (e: FormEvent) => {
    e.preventDefault();
    run("save", async () => { const res = await api.patch(`/api/sites/${site.id}`, { settings: { ...site.settings, ...s } }); done(res); onSaved(); });
  };
  return (
    <form className="body form" onSubmit={save} style={{ borderTop: "1px solid var(--line-soft)" }}>
      <p className="muted small" style={{ margin: 0 }}>Gelden voor elke radio die de site-netwerken uitzendt. Per radio wijk je ervan af in het paneel van het access point.
        Bridge, CAPsMAN en direct toepassen staan onder <a href="#/settings">Instellingen → Wifi-controller</a>.</p>
      <div className="two">
        <Field label="Land" hint="Bepaalt toegestane kanalen en zendvermogen. Schrijf het zoals RouterOS het kent.">
          <input className="input" value={s.country} onChange={(e) => set("country", e.target.value)} required /></Field>
        <Field label="DFS-kanalen (5 GHz)" hint="Op DFS-kanalen doet een AP eerst een CAC (1 tot 10 minuten radardetectie) voordat hij uitzendt.">
          <select className="input" value={s.skip_dfs} onChange={(e) => set("skip_dfs", e.target.value)}>
            <option value="disabled">Alle kanalen gebruiken</option><option value="10min-cac">Kanalen met 10 minuten CAC overslaan</option><option value="all">Alle DFS-kanalen overslaan</option></select></Field>
      </div>
      <div className="two">
        <Field label="Kanaalbreedte 2,4 GHz">
          <select className="input" value={s.ch2_width} onChange={(e) => set("ch2_width", e.target.value)}><option value="20mhz">20 MHz</option><option value="20/40mhz">20/40 MHz</option></select></Field>
        <Field label="Kanalen 2,4 GHz" hint="Frequenties in MHz, bijvoorbeeld 2412,2437,2462. Leeg: automatisch.">
          <input className="input mono" value={s.ch2_freq ?? ""} onChange={(e) => set("ch2_freq", e.target.value)} placeholder="automatisch" pattern="[0-9,:\- ]*" /></Field>
      </div>
      <div className="two">
        <Field label="Kanaalbreedte 5 GHz">
          <select className="input" value={s.ch5_width} onChange={(e) => set("ch5_width", e.target.value)}>
            <option value="20mhz">20 MHz</option><option value="20/40mhz">20/40 MHz</option><option value="20/40/80mhz">20/40/80 MHz</option><option value="20/40/80/160mhz">20/40/80/160 MHz</option></select></Field>
        <Field label="Kanalen 5 GHz" hint="Bijvoorbeeld 5180,5260,5500. Leeg: automatisch.">
          <input className="input mono" value={s.ch5_freq ?? ""} onChange={(e) => set("ch5_freq", e.target.value)} placeholder="automatisch" pattern="[0-9,:\- ]*" /></Field>
      </div>
      <Check checked={!!s.steering} onChange={(v) => set("steering", v)} label="Roaming-hulp (802.11k/v)"
        hint="Een steering-profiel met rrm en wnm: AP's vertellen clients welke buren er zijn en kunnen een betere voorstellen. Nog niet getest op echte hardware." />
      <div><button className="btn primary" disabled={!dirty || !!busy}><Busy on={busy === "save"}>Opslaan</Busy></button></div>
    </form>
  );
}

const TX_LABEL: Record<string, string> = { manual: "Handmatig", low: "Laag", medium: "Midden", high: "Hoog" };
const WIDTH: Record<string, string> = { "20mhz": "20 MHz", "20/40mhz": "20/40 MHz", "20/40/80mhz": "20/40/80 MHz", "20/40/80/160mhz": "20/40/80/160 MHz" };
/** Channel number of a centre frequency: 2412 -> 1, 5180 -> 36, 5955 -> 1 (6 GHz). */
const chanNo = (f: number) => (f >= 5950 ? (f - 5950) / 5 : f >= 5000 ? (f - 5000) / 5 : f === 2484 ? 14 : (f - 2407) / 5);
const dfs = (f: number) => f >= 5260 && f <= 5720;

type RadioState = { mode: string; power: string; freq: string; width: string; off: boolean };
const radioState = (r: any): RadioState => ({ mode: r.tx?.mode ?? "high", power: r.tx?.mode === "manual" ? String(r.tx?.power ?? "") : "",
  freq: r.tx?.freq ?? "", width: r.tx?.width ?? "", off: !!r.tx?.off });
const sameRadio = (a: RadioState, b: RadioState) => a.mode === b.mode && a.freq === b.freq && a.width === b.width && a.off === b.off
  && (a.mode !== "manual" || a.power === b.power);

/** One radio in the access point panel. Site radios: on/off, channel, width, power (saved with the panel's button).
 * The router's own radios also get their management mode; a standalone one shows its own SSIDs. */
function RadioCard({ ap, r, st, set, wlans, busy, onMode }: { ap: any; r: any; st: RadioState; set: (v: RadioState) => void; wlans: any[]; busy: boolean; onMode: (m: string) => void }) {
  const known: number[] = r.channels ?? [];
  const custom = !!st.freq && !known.includes(Number(st.freq));
  const carried = wlans.filter((w) => (w.radios ?? []).includes(macOf(r)));
  const presets: Record<string, string> = { high: `maximum (${r.tx?.max} dBm)`, medium: `${r.tx?.presets?.medium} dBm`, low: `${r.tx?.presets?.low} dBm`, manual: "vaste waarde" };
  const managed = siteRadio(r);
  const up = (k: keyof RadioState, v: any) => set({ ...st, [k]: v });
  return (
    <div className={`radio-form ${managed && st.off ? "is-off" : ""}`}>
      <div className="spread">
        <div><span className="strong">{bandLabel(r.band)}</span> <span className="muted small mono">{r.interface}</span>
          <div className="muted small">Nu: {r.frequency ? `kanaal ${chanNo(r.frequency)} (${r.frequency} MHz)` : "kanaal onbekend"}{r.tx_power ? `, ${r.tx_power} dBm` : ""}, {r.clients} {r.clients === 1 ? "client" : "clients"}</div></div>
        {managed && <Check checked={!st.off} onChange={(v) => up("off", !v)} label="Aan" />}
      </div>
      {r.local && (
        <div className="rc-mode">
          <div className="seg" role="tablist" aria-label={`Beheer van ${r.interface}`}>{(["site", "own", "none"] as const).map((m) => (
            <button key={m} type="button" role="tab" aria-selected={r.local_mode === m} className={r.local_mode === m ? "on" : ""}
              disabled={busy || (m === "site" && !wlans.length)} onClick={() => onMode(m)}>{MODE[m][0]}</button>))}</div>
          <small className="muted">{MODE[r.local_mode ?? "none"][1]}</small>
        </div>)}
      {r.drift?.length > 0 && <div className="banner warn small">Wijkt af van de access points: {r.drift.map((k: string) => DRIFT[k] ?? k).join(", ")}. Opslaan of <em>Bekijken en toepassen</em> zet het recht.</div>}
      {managed ? (st.off ? <p className="muted small" style={{ margin: 0 }}>Deze radio zendt niets uit.</p> : <>
        <div className="two">
          <Field label="Kanaal">
            {known.length > 0 && !custom ? (
              <select className="input" value={st.freq} onChange={(e) => up("freq", e.target.value)}>
                <option value="">Automatisch</option>
                {known.map((f) => <option key={f} value={String(f)}>{chanNo(f)} ({f} MHz){dfs(f) ? " DFS" : ""}</option>)}
              </select>
            ) : <input className="input mono" value={st.freq} onChange={(e) => up("freq", e.target.value)} placeholder="automatisch, of bijv. 5180" />}
          </Field>
          <Field label="Breedte"><select className="input" value={st.width} onChange={(e) => up("width", e.target.value)}>
            <option value="">Site-standaard</option>{(r.widths ?? []).map((x: string) => <option key={x} value={x}>{WIDTH[x] ?? x}</option>)}</select></Field>
        </div>
        <div className="field"><span>Zendvermogen</span>
          <div className="row wrap">
            <div className="seg" role="tablist">{["low", "medium", "high", "manual"].map((m) => (
              <button key={m} type="button" role="tab" aria-selected={m === st.mode} className={m === st.mode ? "on" : ""} onClick={() => up("mode", m)}>{TX_LABEL[m]}</button>))}</div>
            {st.mode === "manual" ? <input className="input mono" inputMode="numeric" value={st.power} onChange={(e) => up("power", e.target.value)} style={{ width: 90 }} placeholder="dBm" aria-label="Zendvermogen in dBm" />
              : <span className="muted small">{presets[st.mode]}</span>}
          </div>
          {st.freq && dfs(Number(st.freq)) && <small>DFS: de radio luistert eerst 1 tot 10 minuten naar radar voordat hij uitzendt.</small>}
        </div>
        <div className="field"><span>Zendt uit</span>
          <div className="row wrap" style={{ gap: 6 }}>{carried.length ? carried.map((w) => <span key={w.id} className="tag">{w.ssid}</span>)
            : <span className="muted small">geen netwerken</span>}</div>
          <small>Welk netwerk op welk access point komt, kies je bij het netwerk zelf.</small>
        </div>
      </>) : r.local_mode === "own" && ap.device_id ? <DeviceRadios deviceId={ap.device_id} macs={[r.mac]} /> : null}
    </div>
  );
}

/** One access point (the router included): all of its radios in one place, its clients and surroundings, and management. */
function ApDrawer({ siteId, ap, wlans, onClose, reload, onAdopt }: { siteId: number; ap: any; wlans: any[]; onClose: () => void; reload: () => void; onAdopt: () => void }) {
  const [tab, setTab] = useState<"radios" | "clients" | "manage">("radios");
  const [radio, setRadio] = useState<string>(ap.radios[0]?.mac);
  const { busy, run } = useAction();
  const { confirm } = useUi();
  const done = useApplyToast();
  const managed = ap.radios.filter(siteRadio);
  const fresh = () => Object.fromEntries(ap.radios.map((x: any) => [x.mac, radioState(x)])) as Record<string, RadioState>;
  const [st, setSt] = useState<Record<string, RadioState>>(fresh);
  const sig = JSON.stringify(ap.radios.map((x: any) => [x.mac, x.tx, x.local_mode]));
  useEffect(() => setSt(fresh()), [sig]);
  const stOf = (x: any) => st[x.mac] ?? radioState(x);
  const dirty = managed.filter((x: any) => !sameRadio(stOf(x), radioState(x)));
  const invalid = dirty.some((x: any) => stOf(x).mode === "manual" && !stOf(x).power);
  const r = ap.radios.find((x: any) => x.mac === radio) ?? ap.radios[0];

  const save = () => run("save", async () => {
    const res = await api.post(`/api/sites/${siteId}/wifi/radios`, { radios: dirty.map((x: any) => {
      const s = stOf(x);
      return { mac: x.mac, mode: s.mode, power: s.mode === "manual" ? Number(s.power) : null, freq: s.freq, width: s.width, off: s.off };
    }) });
    done(res); reload();
  });
  const setMode = async (x: any, mode: string) => {
    if (mode === x.local_mode) return;
    const text: Record<string, any> = {
      site: <>De radio krijgt dezelfde netwerken en instellingen als de access points{x.local_mode === "own" ? "; wat je zelfstandig had ingesteld vervalt" : ""}. Clients verbinden kort opnieuw.</>,
      own: <>De radio houdt zijn huidige SSID's, maar je stelt ze voortaan los in, hier in dit paneel. Wijzigingen aan de site-netwerken gaan eraan voorbij.</>,
      none: <>MikroManager haalt zijn extra SSID's weg en laat de radio verder met rust; de hoofd-SSID blijft uitzenden zoals hij staat.</>,
    };
    if (await confirm({ title: `${x.interface}: ${MODE[mode][0].toLowerCase()}?`, action: MODE[mode][0], danger: mode !== "site", text: text[mode] }))
      run(`mode${x.mac}`, async () => { await api.post(`/api/sites/${siteId}/wifi/radios/${encodeURIComponent(x.mac)}/mode`, { mode }); reload(); }, `${x.interface}: ${MODE[mode][0].toLowerCase()}`);
  };
  const reprovision = () => run("prov", async () => { await api.post(`/api/sites/${siteId}/wifi/aps/reprovision`, { name: ap.name }); reload(); }, `${ap.name} opnieuw geprovisioned`);
  const release = async () => {
    if (await confirm({ title: `${ap.name} loskoppelen?`, action: "Loskoppelen", danger: true,
      text: "Het access point stopt met de netwerken van de site uit te zenden. Daarna stel je het zelfstandig in, of adopteer je het opnieuw." }))
      run("rel", async () => { await api.post(`/api/devices/${ap.device_id}/release`); reload(); onClose(); }, "Losgekoppeld");
  };
  const close = async () => {
    if (dirty.length && !(await confirm({ title: "Wijzigingen weggooien?", action: "Weggooien", danger: true,
      text: `${dirty.length === 1 ? "Eén radio heeft" : `${dirty.length} radio's hebben`} wijzigingen die nog niet zijn opgeslagen.` }))) return;
    onClose();
  };
  const footer = tab === "radios" && managed.length > 0 ? <>
    <span className="muted small grow">{dirty.length ? `${dirty.length} ${dirty.length === 1 ? "radio" : "radio's"} gewijzigd` : "Geen wijzigingen"}</span>
    <button className="btn" disabled={!dirty.length || !!busy} onClick={() => setSt(fresh())}>Herstellen</button>
    <button className="btn primary" disabled={!dirty.length || invalid || !!busy} onClick={save}><Busy on={busy === "save"}>{busy === "save" ? "Toepassen…" : "Opslaan"}</Busy></button>
  </> : undefined;

  return (
    <Drawer wide title={ap.name} onClose={close} footer={footer}
      sub={[ap.local ? "router + wifi-controller" : ap.board, ap.address, ap.version ? `RouterOS ${ap.version}` : null].filter(Boolean).join(" · ")}>
      <Seg value={tab} onChange={setTab} options={[["radios", "Radio's"], ["clients", "Clients en omgeving"], ["manage", "Beheer"]]} />
      {tab === "radios" && (ap.standalone ? <>
        <div className="banner info small"><span className="grow"><strong>Zelfstandig access point.</strong> De SSID's staan op het apparaat zelf, zonder controller. Adopteer het om de netwerken van de site uit te zenden.</span>
          {ap.adoptable && <button className="btn sm primary" disabled={!!busy} onClick={onAdopt}>Adopteren</button>}</div>
        {ap.device_id ? ap.radios.map((x: any) => (
          <div key={x.mac} className="radio-form"><div><span className="strong">{bandLabel(x.band)}</span> <span className="muted small mono">{x.interface}</span></div>
            <DeviceRadios deviceId={ap.device_id} macs={[x.mac]} /></div>)) : <p className="muted">Voeg dit access point toe onder Apparaten om het hier in te stellen.</p>}
      </> : ap.radios.map((x: any) => (
        <RadioCard key={x.mac} ap={ap} r={x} st={stOf(x)} set={(v) => setSt((o) => ({ ...o, [x.mac]: v }))} wlans={wlans} busy={!!busy} onMode={(m) => setMode(x, m)} />)))}
      {tab === "clients" && r && <>
        {ap.radios.length > 1 && <Seg value={r.mac} onChange={setRadio} options={ap.radios.map((x: any) => [x.mac, bandLabel(x.band)])} />}
        <RadioInsight key={r.mac} siteId={siteId} r={r} />
      </>}
      {tab === "manage" && <div className="form">
        <dl className="kv small"><dt>Status</dt><dd>{ap.local ? "router en wifi-controller" : ap.standalone ? "zelfstandig" : ap.state}</dd>
          {ap.address && <><dt>Adres</dt><dd className="mono">{ap.address}</dd></>}{ap.version && <><dt>RouterOS</dt><dd>{ap.version}</dd></>}</dl>
        {ap.local ? <p className="muted small">De router is ook de CAPsMAN-controller. CAPsMAN kan zijn eigen radio's niet beheren, dus MikroManager zet de instellingen er
          rechtstreeks op. Per radio kies je bij <em>Radio's</em> of hij de site-netwerken uitzendt, zelfstandig is of niet beheerd wordt.</p>
          : ap.standalone ? <p className="muted small">Adopteren zet CAPsMAN aan op het access point. De huidige SSID's op het apparaat vervallen; het zendt daarna de netwerken van de site uit.</p>
            : <p className="muted small">Opnieuw provisionen stuurt de configuratie opnieuw naar dit access point; clients verbinden kort opnieuw.</p>}
        <div className="row wrap">
          {!ap.local && !ap.standalone && <button className="btn" disabled={!!busy || !ap.radios.length} onClick={reprovision}><Busy on={busy === "prov"}>Opnieuw provisionen</Busy></button>}
          {ap.standalone && ap.adoptable && <button className="btn primary" disabled={!!busy} onClick={onAdopt}>Adopteren</button>}
          {ap.device_id && <a className="btn" href={`#/devices/${ap.device_id}`}><Settings2 size={15} />Apparaat openen</a>}
          {!ap.local && !ap.standalone && ap.device_id && <button className="btn danger" disabled={!!busy} onClick={release}>Loskoppelen</button>}
        </div>
      </div>}
    </Drawer>
  );
}

/** Measure, propose and apply a channel per radio. */
function ChannelPlanModal({ siteId, onClose }: { siteId: number; onClose: () => void }) {
  const [plan, setPlan] = useState<any | null>(null);
  const [pick, setPick] = useState<Set<string>>(new Set());
  const [power, setPower] = useState(true);
  const { busy, run } = useAction();
  const done = useApplyToast();
  const measure = (m: boolean) => run("measure", async () => {
    const p = await api.post(`/api/sites/${siteId}/wifi/channel-plan`, { measure: m });
    setPlan(p); setPick(new Set(p.radios.filter((x: any) => x.change || x.power_advice).map((x: any) => x.mac)));
  });
  const apply = () => run("apply", async () => {
    const res = await api.post(`/api/sites/${siteId}/wifi/channel-plan/apply`, { radios: plan.radios.filter((x: any) => pick.has(x.mac)), power });
    if (done(res, "Kanaalplan opgeslagen")) onClose();
  });
  const changes = plan?.radios.filter((x: any) => pick.has(x.mac)).length ?? 0;
  return (
    <Modal wide title="Kanaalplan" onClose={onClose}
      footer={!plan ? <><button className="btn" onClick={onClose}>Annuleren</button>
        <button className="btn" disabled={!!busy} onClick={() => measure(false)}>Zonder meten</button>
        <button className="btn primary" disabled={!!busy} onClick={() => measure(true)}><Busy on={busy === "measure"}>{busy === "measure" ? "Meten…" : "Meten en voorstellen"}</Busy></button></>
        : <><button className="btn" onClick={onClose}>Sluiten</button>
          <button className="btn primary" disabled={!!busy || !changes} onClick={apply}><Busy on={busy === "apply"}>{changes ? `${changes} ${changes === 1 ? "radio" : "radio's"} aanpassen` : "Niets te doen"}</Busy></button></>}>
      {!plan ? (
        <div className="form">
          <p>MikroManager kiest voor elke radio een kanaal dat de andere radio's en de buren zo min mogelijk stoort. Op 2,4 GHz alleen 1, 6 en 11; op 5 GHz
            houdt het rekening met de kanaalbreedte (bij 80 MHz is 36–48 één blok).</p>
          <p className="muted small"><strong>Meten:</strong> elke radio scant één keer de omgeving (/interface/wifi/scan). Clients op die radio zijn dan een paar seconden
            weg. Zonder meten kijkt MikroManager alleen naar je eigen access points.</p>
        </div>
      ) : (
        <>
          {plan.errors?.length > 0 && <div className="banner warn small" style={{ marginBottom: 10 }}>{plan.errors.join(" · ")}</div>}
          <div className="table-wrap fit"><table className="t">
            <thead><tr><th style={{ width: 34 }} /><th>Radio</th><th>Nu</th><th>Voorstel</th><th>Waarom</th></tr></thead>
            <tbody>{plan.radios.map((x: any) => (
              <tr key={x.mac} className={x.change || x.power_advice ? "" : "off"}>
                <td><input type="checkbox" className="cb" checked={pick.has(x.mac)} aria-label={`${x.ap} ${bandLabel(x.band)}`}
                  onChange={(e) => { const n = new Set(pick); e.target.checked ? n.add(x.mac) : n.delete(x.mac); setPick(n); }} /></td>
                <td><span className="strong">{x.ap}</span><div className="muted small">{bandLabel(x.band)}, {x.clients} {x.clients === 1 ? "client" : "clients"}</div></td>
                <td className="num">{x.current ? chanNo(x.current) : "–"}</td>
                <td className="num strong">{chanNo(x.proposed)}{x.dfs ? <span className="tag" style={{ marginLeft: 6 }}>DFS</span> : null}
                  {!x.change && <span className="muted small" style={{ fontWeight: 400 }}> (blijft)</span>}</td>
                <td className="small">{x.reason}{x.power_advice && <div className="muted">Zendvermogen naar midden: {x.power_reason}</div>}</td>
              </tr>))}</tbody>
          </table></div>
          {plan.radios.some((x: any) => x.power_advice) && <div style={{ marginTop: 10 }}><Check checked={power} onChange={setPower} label="Ook het zendvermogensadvies overnemen" /></div>}
          <p className="muted small" style={{ marginTop: 10 }}>Toepassen zet per radio een vast kanaal. Terug naar automatisch kan per radio bij het access point.</p>
        </>
      )}
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
