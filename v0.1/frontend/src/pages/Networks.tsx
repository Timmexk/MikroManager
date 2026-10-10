import { FormEvent, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { api } from "../api";
import { useApp } from "../App";
import { Busy, Check, Field, Loading, Modal, useAction, useLoad, useUi } from "../ui";

export default function Networks() {
  const { site } = useApp();
  const n = useLoad(() => api.get(`/api/sites/${site.id}/networks`), [site.id], 20000);
  const [adding, setAdding] = useState(false);
  const [dns, setDns] = useState({ name: "", address: "" });
  const { busy, run } = useAction();
  const { confirm } = useUi();

  if (!n.data) {
    return (<><div className="page-head"><h1>Netwerken</h1></div>
      {n.error?.includes("geen router") ? <div className="panel"><div className="empty"><h3>Eerst een router nodig</h3><a className="btn primary" href="#/devices">Router toevoegen</a></div></div> : <Loading error={n.error} />}</>);
  }
  const d = n.data;
  const remove = async (net: any) => {
    if (await confirm({ title: `Netwerk ${net.label ?? net.name} verwijderen?`, action: "Verwijderen", danger: true,
      text: <>Het VLAN, het adres, de DHCP-server en de bijbehorende firewallregel worden van de router gehaald. Apparaten op dit netwerk verliezen hun verbinding.
        {net.dhcp?.leases ? <strong> Er zijn nu {net.dhcp.leases} apparaten met een adres uit dit netwerk.</strong> : null}</> }))
      run("del", async () => { await api.del(`/api/sites/${site.id}/networks/${net.slug}`); n.reload(); }, "Netwerk verwijderd");
  };

  return (
    <div className="stack">
      <div className="page-head" style={{ marginBottom: 0 }}>
        <div><h1>Netwerken</h1><p>Elk netwerk is een VLAN met een eigen adresreeks en DHCP-server op de router.</p></div>
        <button className="btn primary" onClick={() => setAdding(true)} disabled={!d.bridge.exists}><Plus size={16} />Netwerk toevoegen</button>
      </div>

      {!d.bridge.exists && <div className="banner bad">Bridge <span className="mono">{d.bridge.name}</span> bestaat niet op de router. Kies de juiste bridge onder Wifi, Radio-instellingen.</div>}
      {d.bridge.exists && !d.bridge.vlan_filtering && (
        <div className="banner warn">
          <span className="grow"><strong>VLAN-filtering staat uit op {d.bridge.name}.</strong> Nieuwe VLAN's werken pas op de switchpoorten als je dat aanzet.
            TikControl doet dat niet zelf: een verkeerde volgorde sluit je buiten. Zet het aan in WinBox nadat je de bridge-VLAN-tabel hebt gecontroleerd.</span>
        </div>
      )}

      <section className="panel">
        <div className="table-wrap"><table className="t">
          <thead><tr><th>Netwerk</th><th>VLAN</th><th>Subnet</th><th>Adres router</th><th>DHCP-bereik</th><th className="right">In gebruik</th><th /></tr></thead>
          <tbody>{d.networks.map((net: any) => (
            <tr key={net.name + net.subnet} className={net.disabled ? "off" : ""}>
              <td><span className="strong">{net.label ?? net.name}</span>
                <div className="muted small">{net.wan ? "Internet (WAN)" : net.managed ? `interface ${net.name}` : "Zelf ingesteld"}</div></td>
              <td className="num">{net.vlan_id ?? <span className="muted">–</span>}</td>
              <td className="mono">{net.subnet}</td>
              <td className="mono">{net.gateway}</td>
              <td className="mono">{net.dhcp?.pool ?? <span className="muted" style={{ fontFamily: "var(--sans)" }}>geen DHCP</span>}</td>
              <td className="num right">{net.dhcp ? net.dhcp.leases : ""}</td>
              <td className="right">{net.managed
                ? <button className="btn icon danger" onClick={() => remove(net)} disabled={!!busy} aria-label={`Verwijder ${net.label ?? net.name}`}><Trash2 size={16} /></button>
                : null}</td>
            </tr>
          ))}</tbody>
        </table></div>
      </section>
      <p className="muted small">Netwerken die je zelf op de router hebt gemaakt staan er ter informatie tussen; TikControl wijzigt of verwijdert ze niet.</p>

      <section className="panel">
        <header><h2>Lokale DNS-namen</h2></header>
        {d.dns.length > 0 && (
          <div className="table-wrap"><table className="t"><tbody>{d.dns.map((r: any) => (
            <tr key={r[".id"]}><td className="mono">{r.name ?? r.regexp}</td><td className="mono">{r.address ?? r.cname ?? r.type}</td><td className="muted small">{r.comment}</td>
              <td className="right"><button className="btn icon danger" disabled={!!busy} aria-label={`Verwijder ${r.name}`}
                onClick={() => run("dns", async () => { await api.del(`/api/sites/${site.id}/dns/${encodeURIComponent(r[".id"])}`); n.reload(); })}><Trash2 size={16} /></button></td></tr>
          ))}</tbody></table></div>
        )}
        <form className="body row wrap" style={{ borderTop: d.dns.length ? "1px solid var(--line-soft)" : 0 }}
          onSubmit={(e) => { e.preventDefault(); run("dns", async () => { await api.post(`/api/sites/${site.id}/dns`, dns); setDns({ name: "", address: "" }); n.reload(); }, "DNS-naam toegevoegd"); }}>
          <input className="input grow mono" style={{ flex: "1 1 180px" }} value={dns.name} onChange={(e) => setDns({ ...dns, name: e.target.value })} placeholder="nas.lan" aria-label="Naam" required />
          <input className="input mono" style={{ flex: "1 1 150px" }} value={dns.address} onChange={(e) => setDns({ ...dns, address: e.target.value })} placeholder="192.168.88.20" aria-label="IP-adres" required />
          <button className="btn" disabled={!!busy}>Toevoegen</button>
        </form>
      </section>

      {adding && <NetworkForm siteId={site.id} info={d} onClose={() => setAdding(false)} onSaved={() => { setAdding(false); n.reload(); }} />}
    </div>
  );
}

function NetworkForm({ siteId, info, onClose, onSaved }: { siteId: number; info: any; onClose: () => void; onSaved: () => void }) {
  const used = info.networks.map((x: any) => x.vlan_id).filter(Boolean);
  const nextVlan = [10, 20, 30, 40, 50, 60, 70, 80, 90].find((v) => !used.includes(v)) ?? 100;
  const [f, setF] = useState({ name: "", vlan_id: String(nextVlan), subnet: `192.168.${nextVlan}.0/24`, dns: "", isolate: false,
    interface_list: info.interface_lists.includes("LAN") ? "LAN" : "", tagged_ports: [] as string[] });
  const set = (k: string, v: any) => setF((o) => ({ ...o, [k]: v }));
  const { busy, run } = useAction();
  const [steps, setSteps] = useState<string[] | null>(null);
  const setVlan = (v: string) => setF((o) => ({ ...o, vlan_id: v, subnet: /^192\.168\.\d+\.0\/24$/.test(o.subnet) && /^\d+$/.test(v) && Number(v) < 255 ? `192.168.${v}.0/24` : o.subnet }));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    run("save", async () => setSteps((await api.post(`/api/sites/${siteId}/networks`, { ...f, vlan_id: Number(f.vlan_id) })).steps));
  };
  const ports: string[] = info.bridge.ports.filter((p: string) => !/^(wifi|cap|wlan)/.test(p));
  if (steps) {
    return (
      <Modal title="Netwerk aangemaakt" onClose={onSaved} footer={<button className="btn primary" onClick={onSaved}>Sluiten</button>}>
        <ul className="steps">{steps.map((s, i) => <li key={i}><span className="dot ok" style={{ marginTop: 7 }} /><div>{s}</div></li>)}</ul>
        <p className="muted small" style={{ marginTop: 12 }}>Koppel het netwerk aan een wifi-netwerk door bij Wifi dit VLAN-nummer in te vullen.</p>
      </Modal>
    );
  }
  return (
    <Modal title="Netwerk toevoegen" onClose={onClose}
      footer={<><button className="btn" onClick={onClose}>Annuleren</button>
        <button className="btn primary" form="netform" disabled={!!busy}><Busy on={!!busy}>Aanmaken op de router</Busy></button></>}>
      <form id="netform" className="form" onSubmit={submit}>
        <div className="two">
          <Field label="Naam"><input className="input" value={f.name} onChange={(e) => set("name", e.target.value)} placeholder="Gasten" required autoFocus /></Field>
          <Field label="VLAN-ID"><input className="input" value={f.vlan_id} onChange={(e) => setVlan(e.target.value)} inputMode="numeric" required /></Field>
        </div>
        <div className="two">
          <Field label="Subnet" hint="De router krijgt het eerste adres; DHCP deelt uit vanaf .10.">
            <input className="input mono" value={f.subnet} onChange={(e) => set("subnet", e.target.value)} required /></Field>
          <Field label="DNS-server" hint="Leeg: de router zelf.">
            <input className="input mono" value={f.dns} onChange={(e) => set("dns", e.target.value)} placeholder="router" /></Field>
        </div>
        {ports.length > 0 && (
          <div className="field"><span>Doorgeven op poorten (tagged)</span>
            <div className="row wrap" style={{ gap: "8px 18px" }}>
              {ports.map((p) => <Check key={p} checked={f.tagged_ports.includes(p)} label={p}
                onChange={(v) => set("tagged_ports", v ? [...f.tagged_ports, p] : f.tagged_ports.filter((x) => x !== p))} />)}
            </div>
            <small>Kies de poorten waar een switch of access point aan hangt die dit VLAN moet krijgen.</small></div>
        )}
        {info.interface_lists.length > 0 && (
          <Field label="Interface-lijst" hint="Je firewall laat meestal alleen verkeer toe van interfaces in de lijst LAN. Zonder lijst heeft dit netwerk mogelijk geen DNS of internet.">
            <select className="input" value={f.interface_list} onChange={(e) => set("interface_list", e.target.value)}>
              <option value="">Geen</option>{info.interface_lists.map((l: string) => <option key={l}>{l}</option>)}</select></Field>
        )}
        <Check checked={f.isolate} onChange={(v) => set("isolate", v)} label="Afschermen van andere lokale netwerken"
          hint="Voegt een firewallregel toe die verkeer van dit netwerk naar 10.0.0.0/8, 172.16.0.0/12 en 192.168.0.0/16 weigert. Internet blijft werken." />
      </form>
    </Modal>
  );
}
