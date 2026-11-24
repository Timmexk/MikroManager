import { useMemo, useState } from "react";
import { Plus, ShieldCheck } from "lucide-react";
import { api } from "../api";
import { bps, Check, Drawer, Field, Loading, Modal, useAction, useUi } from "../ui";

const KIND: Record<string, string> = {
  ether: "Ethernet", sfp: "SFP", bridge: "Bridge", vlan: "VLAN", bonding: "Bonding", wifi: "Wifi",
  pppoe: "PPPoE", lte: "LTE", wireguard: "WireGuard", other: "Overig",
};
const FRAME: Record<string, string> = {
  "admit-all": "Alles (untagged en tagged)",
  "admit-only-untagged-and-priority-tagged": "Alleen untagged (access-poort)",
  "admit-only-vlan-tagged": "Alleen tagged (trunk)",
};
const POE: Record<string, string> = { "auto-on": "Auto-on", "forced-on": "Forced-on", off: "Uit (off)" };

type Result = { applied: boolean; reverting_in: number | null; lost?: string[]; steps: number; view: any };

/** Shows the outcome of a guarded change in plain words. */
function useApply(onDone: (view: any | null) => void) {
  const { toast } = useUi();
  const { busy, run } = useAction();
  const apply = (key: string, fn: () => Promise<Result>, ok: string) =>
    run(key, async () => {
      const r = await fn();
      if (r.applied) {
        toast(r.steps ? ok : "Niets gewijzigd");
        onDone(r.view);
      } else if (r.reverting_in) {
        toast(`${(r.lost ?? []).join(", ")} niet meer bereikbaar na deze wijziging. Het apparaat zet de oude instellingen over ${r.reverting_in} seconden zelf terug.`, true);
        onDone(null);
      } else {
        toast(`Teruggedraaid: ${(r.lost ?? []).join(", ")} was daarna niet meer bereikbaar.`, true);
        onDone(null);
      }
    });
  return { busy, apply };
}

export function InterfacesPanel({ deviceId, data, reload, open, setOpen, rates }: {
  deviceId: number; data: any | null; error?: string | null; reload: () => void; open: string | null; setOpen: (n: string | null) => void;
  /** Live rates per interface (updated every few seconds), overrides the slower numbers in `data`. */
  rates?: Record<string, { rx: number; tx: number }>;
}) {
  const [adding, setAdding] = useState(false);
  const [kind, setKind] = useState("all");
  if (!data) return <section className="panel"><header><h2>Interfaces</h2></header><div className="body"><Loading /></div></section>;
  const list: any[] = data.interfaces.map((i: any) => rates?.[i.name] ? { ...i, rx_bps: rates[i.name].rx, tx_bps: rates[i.name].tx } : i);
  const kinds = Array.from(new Set(list.map((i) => i.kind)));
  const rows = list.filter((i) => kind === "all" || i.kind === kind);
  const current = list.find((i) => i.name === open);
  return (
    <section className="panel">
      <header>
        <h2>Interfaces</h2>
        <div className="row wrap">
          <select className="input sm" value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Soort">
            <option value="all">Alle soorten ({list.length})</option>
            {kinds.map((k) => <option key={k} value={k}>{KIND[k] ?? k} ({list.filter((i) => i.kind === k).length})</option>)}
          </select>
          <button className="btn sm" onClick={() => setAdding(true)}><Plus size={14} />VLAN-interface</button>
        </div>
      </header>
      <div className="table-wrap fit"><table className="t">
        <thead><tr><th>Naam</th><th>Soort</th><th>Status</th><th className="hide-sm">Bridge / VLAN</th><th className="right hide-sm">MTU</th><th className="right">Verkeer</th></tr></thead>
        <tbody>{rows.map((i) => (
          <tr key={i.id} className={`click ${i.disabled ? "off" : ""}`} onClick={() => setOpen(i.name)}>
            <td><span className="strong mono">{i.name}</span>{i.comment && <div className="muted small">{i.comment}</div>}</td>
            <td>{KIND[i.kind] ?? i.type}{i.wan && <span className="tag accent" style={{ marginLeft: 6 }}>WAN</span>}</td>
            <td>{i.disabled ? <span className="tag">Uit</span> : i.running ? <span className="tag ok">{i.ether?.rate ?? "Actief"}</span> : <span className="tag">Geen link</span>}</td>
            <td className="hide-sm small">{i.bridge_port ? <>{i.bridge_port.bridge}, PVID {i.bridge_port.pvid}{i.bridge_port.tagged.length > 0 && <span className="muted"> + tagged {i.bridge_port.tagged.join(", ")}</span>}</>
              : i.vlan ? <>VLAN {i.vlan.vlan_id} op {i.vlan.parent}</> : i.bridge ? <>{i.bridge.ports.length} poorten{i.bridge.vlan_filtering ? ", VLAN-filtering" : ""}</> : <span className="muted">–</span>}</td>
            <td className="num right hide-sm">{i.mtu ?? "–"}</td>
            <td className="num right nowrap small">{i.running && i.rx_bps != null ? <>{bps(i.rx_bps)} / {bps(i.tx_bps)}</> : ""}</td>
          </tr>
        ))}</tbody>
      </table></div>
      {current && <InterfaceDrawer key={current.name} deviceId={deviceId} i={current} data={data} onClose={() => setOpen(null)} reload={reload} />}
      {adding && <VlanForm deviceId={deviceId} data={data} onClose={() => setAdding(false)} onSaved={() => { setAdding(false); reload(); }} />}
    </section>
  );
}

function SafeNote({ secs }: { secs: number }) {
  return (
    <div className="banner info small" style={{ alignItems: "flex-start", flexWrap: "nowrap" }}>
      <ShieldCheck size={16} style={{ flexShrink: 0, marginTop: 2 }} />
      <span>Veilige modus: deze wijziging kan een apparaat onbereikbaar maken. Het apparaat zet de oude instellingen na {secs} seconden
        zelf terug, tenzij MikroManager daarna alle apparaten van de site nog bereikt.</span>
    </div>
  );
}

function InterfaceDrawer({ deviceId, i, data, onClose, reload }: { deviceId: number; i: any; data: any; onClose: () => void; reload: () => void }) {
  const { confirm } = useUi();
  const bp = i.bridge_port;
  const [f, setF] = useState(() => ({
    enabled: !i.disabled, comment: i.comment ?? "", mtu: String(i.mtu ?? ""),
    an: i.ether?.auto_negotiation ?? true, speed: i.ether?.speed ?? (i.ether?.speeds?.[0] ?? ""),
    poe_out: i.poe?.out ?? "auto-on", poe_priority: String(i.poe?.priority ?? "10"),
    bridge: bp?.bridge ?? "", pvid: String(bp?.pvid ?? 1), frame_types: bp?.frame_types ?? "admit-all",
    tagged: (bp?.tagged ?? []).join(", "),
    vlan_id: String(i.vlan?.vlan_id ?? ""), parent: i.vlan?.parent ?? "",
  }));
  const set = (k: string, v: any) => setF((x) => ({ ...x, [k]: v }));
  const { busy, apply } = useApply((view) => { reload(); if (!view) onClose(); });

  const body = useMemo(() => {
    const b: any = {};
    if (f.enabled === i.disabled) b.disabled = !f.enabled;
    if (f.comment !== (i.comment ?? "")) b.comment = f.comment;
    if (f.mtu && f.mtu !== String(i.mtu ?? "") && i.kind !== "vlan") b.mtu = Number(f.mtu);
    if (i.ether) {
      if (f.an !== i.ether.auto_negotiation) b.auto_negotiation = f.an;
      if (!f.an && f.speed !== i.ether.speed) { b.auto_negotiation = false; b.speed = f.speed; }
    }
    if (i.poe) {
      if (f.poe_out !== i.poe.out) b.poe_out = f.poe_out;
      if (f.poe_priority !== String(i.poe.priority ?? "")) b.poe_priority = Number(f.poe_priority);
    }
    if ((i.ether || i.kind === "bonding" || i.kind === "wifi" || bp) && f.bridge !== (bp?.bridge ?? "")) b.bridge = f.bridge || null;
    if (f.bridge) {
      if (f.pvid !== String(bp?.pvid ?? 1)) b.pvid = Number(f.pvid);
      if (f.frame_types !== (bp?.frame_types ?? "admit-all")) b.frame_types = f.frame_types;
      const t = f.tagged.split(/[\s,]+/).filter(Boolean).map(Number);
      if (t.join(",") !== (bp?.tagged ?? []).join(",")) b.tagged = t;
    }
    return b;
  }, [f, i, bp]);
  const vlanBody = useMemo(() => {
    if (!i.vlan) return {};
    const b: any = {};
    if (f.vlan_id !== String(i.vlan.vlan_id)) b.vlan_id = Number(f.vlan_id);
    if (f.parent !== i.vlan.parent) b.interface = f.parent;
    if (f.comment !== (i.comment ?? "")) b.comment = f.comment;
    if (f.enabled === i.disabled) b.disabled = !f.enabled;
    if (f.mtu && f.mtu !== String(i.mtu ?? "")) b.mtu = Number(f.mtu);
    return b;
  }, [f, i]);
  const changes = i.vlan ? vlanBody : body;
  const dirty = Object.keys(changes).length > 0;
  const risky = Object.keys(changes).some((k) => k !== "comment" && !(k === "poe_priority"));

  const save = async () => {
    if (b_off(changes) && !(await confirm({ title: `${i.name} uitschakelen?`, action: "Uitschakelen", danger: true,
      text: i.wan ? "Dit is de internetpoort: het hele netwerk verliest internet." : "Alles achter deze interface verliest de verbinding. Raakt MikroManager daardoor een apparaat kwijt, dan wordt het automatisch teruggedraaid." }))) return;
    if (i.vlan) apply("save", () => api.patch(`/api/devices/${deviceId}/vlans/${encodeURIComponent(i.name)}`, changes), "Opgeslagen");
    else apply("save", () => api.post(`/api/devices/${deviceId}/interfaces/${encodeURIComponent(i.name)}`, changes), "Opgeslagen");
  };
  const remove = async () => {
    if (await confirm({ title: `${i.name} verwijderen?`, action: "Verwijderen", danger: true,
      text: "De VLAN-interface verdwijnt van het apparaat. Staat er nog een IP-adres of DHCP-server op, dan weigert RouterOS dit." }))
      apply("del", () => api.del(`/api/devices/${deviceId}/vlans/${encodeURIComponent(i.name)}`), "VLAN-interface verwijderd").then((ok) => ok && onClose());
  };

  const portLike = !!(i.ether || i.kind === "bonding" || bp);
  return (
    <Drawer title={<span className="mono">{i.name}</span>} sub={<>{KIND[i.kind] ?? i.type}{i.mac ? <> · <span className="mono">{i.mac}</span></> : null}</>} onClose={onClose}>
      <form className="form" onSubmit={(e) => { e.preventDefault(); save(); }}>
        <dl className="kv">
          <dt>Status</dt><dd>{i.disabled ? "Uitgeschakeld" : i.running ? `Actief${i.ether?.rate ? `, ${i.ether.rate}` : ""}` : "Geen link"}</dd>
          {i.running && i.rx_bps != null && <><dt>Verkeer</dt><dd>RX {bps(i.rx_bps)}, TX {bps(i.tx_bps)}</dd></>}
          {i.poe?.status && <><dt>PoE</dt><dd>{i.poe.status === "powered-on" ? `Actief, ${i.poe.power ?? "?"} W` : i.poe.status === "waiting-for-load" ? "Geen PoE-apparaat aangesloten" : i.poe.status}</dd></>}
        </dl>

        <Check checked={f.enabled} onChange={(v) => set("enabled", v)} label="Ingeschakeld" />
        <Field label="Label"><input className="input" value={f.comment} onChange={(e) => set("comment", e.target.value)} placeholder="Bijvoorbeeld: uplink zolder" /></Field>
        {i.kind !== "wifi" && <Field label="MTU"><input className="input mono" inputMode="numeric" value={f.mtu} onChange={(e) => set("mtu", e.target.value)} /></Field>}
        {i.kind === "wifi" && <p className="muted small">SSID's, kanalen en wachtwoorden beheer je onder Wifi.</p>}

        {i.ether && <>
          <h3 className="small-h">Snelheid</h3>
          <Check checked={f.an} onChange={(v) => set("an", v)} label="Auto-negotiation" hint="Uit: vaste snelheid en duplex" />
          {!f.an && <Field label="Vaste snelheid">
            <select className="input" value={f.speed} onChange={(e) => set("speed", e.target.value)}>
              {i.ether.speeds.map((s: string) => <option key={s} value={s}>{s}</option>)}
            </select></Field>}
        </>}

        {i.poe && <>
          <h3 className="small-h">PoE-out</h3>
          <div className="row">
            <Field label="Modus"><select className="input" value={f.poe_out} onChange={(e) => set("poe_out", e.target.value)}>
              {data.poe_out.map((p: string) => <option key={p} value={p}>{POE[p] ?? p}</option>)}</select></Field>
            <Field label="Prioriteit" hint="0 = hoogst"><input className="input mono" inputMode="numeric" value={f.poe_priority} onChange={(e) => set("poe_priority", e.target.value)} style={{ width: 90 }} /></Field>
          </div>
        </>}

        {portLike && <>
          <h3 className="small-h">Bridge en VLAN's</h3>
          <Field label="Bridge"><select className="input" value={f.bridge} onChange={(e) => set("bridge", e.target.value)}>
            <option value="">Niet in een bridge</option>
            {data.bridges.map((b: string) => <option key={b} value={b}>{b}</option>)}</select></Field>
          {f.bridge && <>
            {bp && !bp.vlan_filtering && <p className="muted small">VLAN-filtering staat uit op {bp.bridge}. PVID en tagged VLAN's worden opgeslagen, maar werken pas als je het aanzet; dat doet MikroManager bewust niet.</p>}
            <div className="row">
              <Field label="PVID" hint="Untagged VLAN"><input className="input mono" inputMode="numeric" value={f.pvid} onChange={(e) => set("pvid", e.target.value)} style={{ width: 90 }} /></Field>
              <Field label="Frame-types"><select className="input" value={f.frame_types} onChange={(e) => set("frame_types", e.target.value)}>
                {data.frame_types.map((t: string) => <option key={t} value={t}>{FRAME[t] ?? t}</option>)}</select></Field>
            </div>
            <Field label="Tagged VLAN's" hint="Komma-gescheiden, bijvoorbeeld 10, 20, 30"><input className="input mono" value={f.tagged} onChange={(e) => set("tagged", e.target.value)} placeholder="geen" /></Field>
          </>}
        </>}

        {i.vlan && <>
          <h3 className="small-h">VLAN</h3>
          <div className="row">
            <Field label="VLAN-ID"><input className="input mono" inputMode="numeric" value={f.vlan_id} onChange={(e) => set("vlan_id", e.target.value)} style={{ width: 100 }} /></Field>
            <Field label="Op interface"><select className="input" value={f.parent} onChange={(e) => set("parent", e.target.value)}>
              {data.interfaces.filter((x: any) => ["bridge", "ether", "sfp", "bonding"].includes(x.kind)).map((x: any) => <option key={x.name} value={x.name}>{x.name}</option>)}</select></Field>
          </div>
        </>}

        {i.bridge && <p className="muted small">Poorten in deze bridge: {i.bridge.ports.join(", ") || "geen"}. VLAN-filtering {i.bridge.vlan_filtering ? "staat aan" : "staat uit"}.</p>}

        {dirty && risky && <SafeNote secs={data.safe_secs} />}
        <div className="row wrap">
          <button className="btn primary" disabled={!dirty || !!busy}>{busy === "save" ? "Bezig…" : "Opslaan"}</button>
          {i.vlan && <button type="button" className="btn danger" disabled={!!busy} onClick={remove}>Verwijderen</button>}
        </div>
      </form>
    </Drawer>
  );
}

const b_off = (c: any) => c.disabled === true || c.poe_out === "off";

function VlanForm({ deviceId, data, onClose, onSaved }: { deviceId: number; data: any; onClose: () => void; onSaved: () => void }) {
  const parents = data.interfaces.filter((x: any) => ["bridge", "ether", "sfp", "bonding"].includes(x.kind));
  const [f, setF] = useState({ name: "", vlan_id: "", interface: parents.find((p: any) => p.kind === "bridge")?.name ?? parents[0]?.name ?? "", comment: "" });
  const { busy, apply } = useApply(() => onSaved());
  const auto = f.vlan_id && !f.name ? `vlan${f.vlan_id}` : f.name;
  return (
    <Modal title="VLAN-interface toevoegen" onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Annuleren</button>
        <button className="btn primary" disabled={!!busy || !f.vlan_id} onClick={() => apply("add", () => api.post(`/api/devices/${deviceId}/vlans`, { ...f, name: auto, vlan_id: Number(f.vlan_id) }), "VLAN-interface toegevoegd")}>Toevoegen</button></>}>
      <div className="form">
        <div className="row">
          <Field label="VLAN-ID"><input className="input mono" inputMode="numeric" value={f.vlan_id} onChange={(e) => setF({ ...f, vlan_id: e.target.value })} style={{ width: 100 }} autoFocus /></Field>
          <Field label="Op interface"><select className="input" value={f.interface} onChange={(e) => setF({ ...f, interface: e.target.value })}>
            {parents.map((p: any) => <option key={p.name} value={p.name}>{p.name}</option>)}</select></Field>
        </div>
        <Field label="Naam" hint={!f.name && f.vlan_id ? `Leeg laten wordt ${auto}` : undefined}><input className="input mono" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="vlan30" /></Field>
        <Field label="Label"><input className="input" value={f.comment} onChange={(e) => setF({ ...f, comment: e.target.value })} placeholder="Bijvoorbeeld: IoT" /></Field>
        <p className="muted small">Alleen de VLAN-interface. Wil je er ook een IP-adres en DHCP bij, gebruik dan Netwerken.</p>
      </div>
    </Modal>
  );
}
