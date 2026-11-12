import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, Cable, Clock, Pause, Search, Wifi } from "lucide-react";
import { api } from "../api";
import { useApp } from "../App";
import { bandLabel, bps, Drawer, fmtBytes, fmtUptime, Loading, Seg, Signal, useAction, useLoad, useUi } from "../ui";

type Filter = "online" | "wifi" | "wired" | "offline";

export default function Clients() {
  const { site } = useApp();
  const list = useLoad<any[]>(() => api.get(`/api/sites/${site.id}/clients`), [site.id], 8000);
  const [filter, setFilter] = useState<Filter>("online");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (list.data ?? []).filter((c) =>
      (filter === "offline" ? !c.online : c.online && (filter === "online" || c.type === filter)) &&
      (!needle || [c.display, c.hostname, c.ip, c.mac, ...(c.ipv6 ?? []), c.wifi?.ssid, c.wifi?.ap, c.wired?.device].some((v) => v && String(v).toLowerCase().includes(needle))));
  }, [list.data, filter, q]);

  if (!list.data) return <Loading error={list.error} />;
  const all = list.data;
  const count = (f: Filter) => all.filter((c) => (f === "offline" ? !c.online : c.online && (f === "online" || c.type === f))).length;
  const current = all.find((c) => c.mac === open);

  return (
    <>
      <div className="page-head">
        <div><h1>Clients</h1><p>Elk apparaat staat er één keer in, op de plek waar het echt verbonden is: wifi-clients bij hun access point, bekabelde clients bij hun switchpoort.</p></div>
      </div>
      <div className="row wrap" style={{ marginBottom: 14, justifyContent: "space-between" }}>
        <Seg value={filter} onChange={setFilter} options={[["online", `Verbonden ${count("online")}`], ["wifi", `Wifi ${count("wifi")}`],
          ["wired", `Bedraad ${count("wired")}`], ["offline", `Offline ${count("offline")}`]]} />
        <label className="search"><Search size={15} /><input className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Zoek op naam, IP (v4/v6) of MAC" aria-label="Zoeken" /></label>
      </div>
      <div className="panel">
        {rows.length === 0 ? <div className="empty">{all.length === 0 ? "Nog geen clients gezien. Voeg je router toe, dan verschijnen ze hier." : "Geen clients die bij dit filter passen."}</div> : (
          <div className="table-wrap fit"><table className="t">
            <thead><tr><th>Naam</th><th className="hide-sm">IP-adres</th><th>Verbinding</th><th className="hide-sm">Signaal</th><th className="right hide-sm">Nu</th></tr></thead>
            <tbody>{rows.map((c) => (
              <tr key={c.mac} className={`click ${c.online ? "" : "off"}`} onClick={() => setOpen(c.mac)}>
                <td><div className="row" style={{ gap: 9 }}>
                  {c.type === "wifi" ? <Wifi size={16} className="muted" /> : <Cable size={16} className="muted" />}
                  <div style={{ minWidth: 0 }}><div className="strong">{c.display}</div>
                    {c.display !== c.mac && <div className="mono muted">{c.mac}</div>}</div>
                  {c.blocked && <span className="tag bad">Geblokkeerd</span>}
                  {c.paused && <span className="tag warn"><Pause size={12} />Gepauzeerd</span>}
                  {!c.paused && c.schedule && <span className="tag"><Clock size={12} />{c.schedule.from}–{c.schedule.to}</span>}
                </div></td>
                <td className="mono hide-sm">{c.ip ?? "–"}{c.static && <span className="tag" style={{ marginLeft: 8, fontFamily: "var(--sans)" }}>Vast</span>}
                  {c.ipv6?.length > 0 && <div className="muted small ellipsis" title={c.ipv6.join("\n")}>{c.ipv6[0]}{c.ipv6.length > 1 ? ` +${c.ipv6.length - 1}` : ""}</div>}</td>
                <td>{c.wifi ? <>{c.wifi.ssid}<div className="muted small">{c.wifi.ap}, {bandLabel(c.wifi.band)}</div></>
                  : c.wired ? <>{c.wired.device}<div className="muted small">poort {c.wired.port}{c.wired.shared ? `, gedeeld met ${c.wired.shared}` : ""}</div></>
                    : <span className="muted">{c.last_seen ? `laatst gezien ${c.last_seen} geleden` : "Niet verbonden"}</span>}</td>
                <td className="hide-sm">{c.wifi ? <Signal dbm={c.wifi.signal} /> : null}</td>
                <td className="num right hide-sm nowrap">{c.online && c.rate_down != null ? <>
                  <div><ArrowDown size={12} className="muted" /> {bps(c.rate_down)}</div><div className="muted"><ArrowUp size={12} /> {bps(c.rate_up)}</div></> : ""}</td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </div>
      {current && <ClientDrawer key={current.mac} siteId={site.id} c={current} onClose={() => setOpen(null)} reload={list.reload} />}
    </>
  );
}

function ClientDrawer({ siteId, c, onClose, reload }: { siteId: number; c: any; onClose: () => void; reload: () => void }) {
  const { busy, run } = useAction();
  const { confirm } = useUi();
  const [name, setName] = useState(c.name ?? "");
  const [ip, setIp] = useState(c.ip ?? "");
  const [from, setFrom] = useState(c.schedule?.from ?? "07:00");
  const [to, setTo] = useState(c.schedule?.to ?? "22:00");
  const base = `/api/sites/${siteId}/clients/${c.mac}`;
  const act = (key: string, path: string, body: any, done: string) => run(key, async () => { await api.post(base + path, body); await reload(); }, done);
  const block = async () => {
    if (c.blocked) return act("block", "/block", { blocked: false }, "Blokkade opgeheven");
    if (await confirm({ title: `${c.display} blokkeren?`, action: "Blokkeren", danger: true,
      text: "Het apparaat wordt van de wifi gehaald en kan op geen enkel wifi-netwerk van deze site meer verbinden. Een bekabelde verbinding blijft werken." }))
      act("block", "/block", { blocked: true }, "Geblokkeerd op wifi");
  };
  return (
    <Drawer title={c.display} sub={<span className="mono">{c.mac}</span>} onClose={onClose}>
      <dl className="kv">
        <dt>Status</dt><dd>{c.blocked ? <span className="tag bad">Geblokkeerd</span> : c.online ? <span className="tag ok">Verbonden</span> : <span className="tag">Offline</span>}</dd>
        <dt>IP-adres</dt><dd className="mono">{c.ip ?? "–"}</dd>
        {c.ipv6?.length > 0 && <><dt>IPv6</dt><dd className="mono small">{c.ipv6.map((a: string) => <div key={a}>{a}</div>)}</dd></>}
        {c.online && c.rate_down != null && <><dt>Nu</dt><dd>{bps(c.rate_down)} omlaag, {bps(c.rate_up)} omhoog</dd></>}
        {c.hostname && <><dt>Hostnaam</dt><dd>{c.hostname}</dd></>}
        {c.dhcp_server && <><dt>DHCP-server</dt><dd>{c.dhcp_server}{c.static ? " (vast adres)" : ""}</dd></>}
        {c.wifi && <>
          <dt>Netwerk</dt><dd>{c.wifi.ssid}</dd>
          <dt>Access point</dt><dd>{c.wifi.ap}, {bandLabel(c.wifi.band)}</dd>
          <dt>Signaal</dt><dd><Signal dbm={c.wifi.signal} /></dd>
          <dt>Snelheid</dt><dd className="small">{(c.wifi.rx_rate ?? "–").split("-")[0]} omhoog, {(c.wifi.tx_rate ?? "–").split("-")[0]} omlaag</dd>
          <dt>Verbonden sinds</dt><dd>{fmtUptime(c.wifi.uptime)}</dd>
          <dt>Verbruik</dt><dd>{fmtBytes(c.rx)} ontvangen, {fmtBytes(c.tx)} verzonden</dd>
        </>}
        {c.wifi?.stale && <><dt>Let op</dt><dd className="small">Het access point reageerde net niet; dit is de laatst bekende plek.</dd></>}
        {c.wired && <><dt>Switch</dt><dd>{c.wired.device}</dd><dt>Poort</dt><dd>{c.wired.port}{c.wired.shared ? ` (met ${c.wired.shared} andere apparaten, dus achter een eigen switch of access point)` : ""}</dd></>}
      </dl>

      <form className="form" onSubmit={(e) => { e.preventDefault(); act("name", "/name", { name }, "Naam opgeslagen"); }}>
        <label className="field"><span>Naam</span>
          <div className="row"><input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder={c.hostname ?? "Eigen naam"} />
            <button className="btn" disabled={!!busy || name === (c.name ?? "")}>Opslaan</button></div>
          <small>Alleen in MikroManager; op de router verandert niets.</small></label>
      </form>

      {c.lease_id && (
        <form className="form" onSubmit={(e) => { e.preventDefault(); act("static", "/static", { address: ip }, "Vast IP-adres ingesteld"); }}>
          <label className="field"><span>Vast IP-adres</span>
            <div className="row"><input className="input mono" value={ip} onChange={(e) => setIp(e.target.value)} />
              <button className="btn" disabled={!!busy || (c.static && ip === c.ip)}>{c.static ? "Wijzigen" : "Vastzetten"}</button></div>
            <small>{c.static ? "Deze client heeft een vaste lease op de router." : "Maakt van de huidige DHCP-lease een vaste lease."}</small></label>
        </form>
      )}

      <div className="field" style={{ marginBottom: 16 }}>
        <span>Internettoegang</span>
        <div className="row wrap" style={{ marginBottom: 10 }}>
          <button className={`btn ${c.paused ? "primary" : ""}`} disabled={!!busy}
            onClick={() => act("pause", "/pause", { paused: !c.paused }, c.paused ? "Internet hervat" : "Internet gepauzeerd")}>
            {c.paused ? "Internet hervatten" : "Internet pauzeren"}</button>
        </div>
        <form className="row wrap" onSubmit={(e) => { e.preventDefault(); act("sched", "/schedule", { from, to }, "Tijdschema opgeslagen"); }}>
          <span className="muted small">Alleen internet van</span>
          <input className="input mono" type="time" value={from} onChange={(e) => setFrom(e.target.value)} style={{ width: 110 }} aria-label="Van" />
          <span className="muted small">tot</span>
          <input className="input mono" type="time" value={to} onChange={(e) => setTo(e.target.value)} style={{ width: 110 }} aria-label="Tot" />
          <button className="btn" disabled={!!busy || (c.schedule?.from === from && c.schedule?.to === to)}>{c.schedule ? "Wijzigen" : "Instellen"}</button>
          {c.schedule && <button type="button" className="btn" disabled={!!busy} onClick={() => act("sched", "/schedule", {}, "Tijdschema verwijderd")}>Verwijderen</button>}
        </form>
        <small>Via Kid Control op de router, elke dag van de week. Pauzeren gaat voor het tijdschema; bij hervatten geldt het schema weer.</small>
      </div>

      <div className="row wrap">
        {!c.wifi && <button className="btn" disabled={!!busy} onClick={() => act("wol", "/wol", {}, "Wake-on-LAN verstuurd")}>Wake-on-LAN</button>}
        {c.wifi && <button className="btn" disabled={!!busy} onClick={() => act("kick", "/kick", {}, "Client verbindt opnieuw")}>Opnieuw laten verbinden</button>}
        <button className={`btn ${c.blocked ? "" : "danger"}`} disabled={!!busy} onClick={block}>{c.blocked ? "Blokkade opheffen" : "Blokkeren op wifi"}</button>
      </div>
    </Drawer>
  );
}
