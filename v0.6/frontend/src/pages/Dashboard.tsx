import { useState } from "react";
import { ArrowDown, ArrowUp, CircleCheck, Download, Globe, MonitorSmartphone, Network, Radio, Router, Server, Wifi as WifiIcon } from "lucide-react";
import { api } from "../api";
import { useApp } from "../App";
import { Faceplate, LineChart } from "../components";
import { bps, fmtAgo, fmtBps, fmtBytes, Loading, Meter, Seg, Status, useLive, useLoad } from "../ui";

export default function Dashboard() {
  const { site } = useApp();
  const [hours, setHours] = useState<"live" | "1" | "6" | "24">("live");
  const isLive = hours === "live";
  const o = useLoad(() => api.get(`/api/sites/${site.id}/overview?hours=${isLive ? 1 : hours}`), [site.id, hours], 10000);
  const lv = useLive<any>(isLive ? `/api/sites/${site.id}/live` : null, ["traffic", "latency"]);
  if (!o.data) return <Loading error={o.error} />;
  const d = o.data;

  if (!d.devices.total) {
    return (
      <>
        <div className="page-head"><h1>{site.name}</h1></div>
        <div className="panel"><div className="empty">
          <h3>Nog geen apparaten op deze site</h3>
          <p>Begin met je router. Daarna voeg je switches en access points toe.</p>
          <a className="btn primary" href="#/devices">Router toevoegen</a>
        </div></div>
      </>
    );
  }

  const now = lv?.traffic?.[lv.traffic.length - 1];
  const [rx, rxU] = fmtBps(isLive && now ? now.rx : d.wan.rx_bps), [tx, txU] = fmtBps(isLive && now ? now.tx : d.wan.tx_bps);
  const range: [number, number] | undefined = isLive && lv ? [lv.now - lv.window, lv.now] : undefined;
  const allUp = d.devices.online === d.devices.total;
  return (
    <div className="stack">
      <div className="page-head" style={{ marginBottom: 0 }}>
        <div>
          <h1>{site.name}</h1>
          <p>
            {allUp ? `Alle ${d.devices.total} apparaten zijn online` : `${d.devices.online} van ${d.devices.total} apparaten online`}
            {`, ${d.clients.online} clients verbonden (${d.clients.wifi} via wifi, ${d.clients.wired} bedraad).`}
          </p>
        </div>
        <Seg value={hours} onChange={setHours} options={[["live", "Live"], ["1", "1 uur"], ["6", "6 uur"], ["24", "24 uur"]]} />
      </div>

      {!allUp && <div className="banner bad"><strong>Offline:</strong> {d.devices.offline.join(", ")}</div>}

      <div className="stats">
        <a className="stat" href="#/devices">
          <span className="stat-label"><Server size={15} />Apparaten</span>
          <span className="stat-row"><Ring value={d.devices.online} total={d.devices.total} />
            <span><span className="stat-value">{d.devices.online}<small>/{d.devices.total}</small></span>
              <span className={`stat-sub ${allUp ? "ok" : "bad"}`}>{allUp ? "Alles online" : `${d.devices.total - d.devices.online} offline`}</span></span></span>
        </a>
        <a className="stat" href="#/clients">
          <span className="stat-label"><MonitorSmartphone size={15} />Clients</span>
          <span className="stat-value">{d.clients.online}</span>
          <span className="split" aria-label={`${d.clients.wifi} wifi, ${d.clients.wired} bedraad`}>
            <i style={{ flex: d.clients.wifi || 0.0001, background: "var(--s1)" }} /><i style={{ flex: d.clients.wired || 0.0001, background: "var(--s2)" }} /></span>
          <span className="stat-sub"><span className="key" style={{ background: "var(--s1)" }} />{d.clients.wifi} wifi <span className="key" style={{ background: "var(--s2)", marginLeft: 8 }} />{d.clients.wired} bedraad</span>
        </a>
        <div className="stat wide-sm">
          <span className="stat-label"><Globe size={15} />Internet{d.wan.interface ? <span className="muted iface">via {d.wan.interface}</span> : null}{isLive && <span className="live-dot">Live</span>}</span>
          <span className="stat-row" style={{ gap: 16 }}>
            <span><span className="stat-value sm"><ArrowDown size={15} color="var(--s1)" />{rx}<small>{rxU}</small></span></span>
            <span><span className="stat-value sm"><ArrowUp size={15} color="var(--s2)" />{tx}<small>{txU}</small></span></span>
          </span>
          <span className="stat-sub">{latency(d, isLive ? lv : null)}</span>
        </div>
        <a className="stat" href="#/wifi">
          <span className="stat-label"><WifiIcon size={15} />Wifi</span>
          <span className="stat-value">{d.ssids.length}<small>{d.ssids.length === 1 ? " SSID" : " SSID's"} actief</small></span>
          <span className="stat-sub">{d.topology.filter((n: any) => n.role === "ap" || n.wifi > 0).length} access points, {d.clients.wifi} clients</span>
        </a>
        <a className="stat" href="#/maintenance">
          <span className="stat-label"><Download size={15} />Updates</span>
          {d.updates > 0 ? <><span className="stat-value">{d.updates}</span><span className="stat-sub warn">{d.updates === 1 ? "update beschikbaar" : "updates beschikbaar"}</span></>
            : <><span className="stat-value ok-ico"><CircleCheck size={26} /></span><span className="stat-sub ok">Alles up-to-date</span></>}
        </a>
      </div>

      <Topology nodes={d.topology} />

      <section className="panel">
        <header><h2>Apparaten</h2><a className="btn sm" href="#/devices">Beheren</a></header>
        <div className="rack">
          {d.device_list.map((v: any) => (
            <a key={v.id} className="rack-row" href={`#/devices/${v.id}`}>
              <div style={{ minWidth: 0 }}>
                <div className="name"><span className={`dot ${v.online ? "ok" : v.online === false ? "bad" : ""}`} /><span>{v.name}</span></div>
                <div className="sub">{v.board ?? v.host}{v.version ? `, RouterOS ${v.version}` : ""}</div>
              </div>
              <Faceplate ports={v.ports} mini />
              <div className="sub hide-sm">
                {v.online === false ? (v.error ?? "Niet bereikbaar")
                  : v.clients > 0 ? <span className="row" style={{ gap: 6 }}><Radio size={14} />{v.clients} {v.clients === 1 ? "wifi-client" : "wifi-clients"}</span>
                    : v.role === "ap" ? "Geen wifi-clients" : ""}
              </div>
              <div className="hide-sm">{v.busy ? <Status online={v.online} busy={v.busy} /> : <Meter value={lv?.cpu?.[v.id] ?? v.cpu} />}</div>
            </a>
          ))}
        </div>
      </section>

      <div className="cols">
        <section className="panel">
          <header>
            <h2>Internetverkeer{d.wan.interface ? <span className="muted small" style={{ fontFamily: "var(--sans)", fontWeight: 400 }}> via {d.wan.interface}</span> : null}
              {isLive && <span className="live-dot" title="Werkt elke paar seconden bij">Live</span>}</h2>
          </header>
          <div className="body">
            {d.wan.interface
              ? <LineChart title="Internetverkeer" data={isLive ? (lv?.traffic ?? []) : d.wan.history} fmt={bps} xRange={range}
                series={[{ key: "rx", label: "Download", color: "var(--s1)", area: true }, { key: "tx", label: "Upload", color: "var(--s2)" }]} />
              : <div className="empty">Geen standaardroute gevonden op de router, dus de internetpoort is onbekend.</div>}
          </div>
        </section>

        <div className="stack">
          <section className="panel">
            <header><h2>Wifi-netwerken</h2><a className="btn sm" href="#/wifi">Beheren</a></header>
            <div className="body" style={{ display: "grid", gap: 10 }}>
              {d.ssids.length === 0 && <span className="muted">Geen wifi-clients verbonden.</span>}
              {d.ssids.map(([ssid, n]: [string, number]) => (
                <div key={ssid} className="spread">
                  <span className="strong">{ssid}</span>
                  <span className="row" style={{ gap: 10 }}>
                    <span className="meter" style={{ width: 90 }}><i style={{ width: `${(n / Math.max(...d.ssids.map((s: any) => s[1]))) * 100}%` }} /></span>
                    <span className="num" style={{ minWidth: 68, textAlign: "right" }}>{n} {n === 1 ? "client" : "clients"}</span>
                  </span>
                </div>
              ))}
            </div>
          </section>
          {d.top_clients.length > 0 && (
            <section className="panel">
              <header><h2>Top wifi-clients (data)</h2><a className="btn sm" href="#/clients">Alle clients</a></header>
              <table className="t"><tbody>
                {d.top_clients.map((c: any) => (
                  <tr key={c.mac}><td className="strong">{c.display}<div className="muted small" style={{ fontWeight: 400 }}>{c.ssid}</div></td>
                    <td className="num right nowrap">{fmtBytes(c.rx + c.tx)}</td></tr>
                ))}
              </tbody></table>
            </section>
          )}
        </div>
      </div>

      {d.wan_quality?.wans?.length > 0 && <WanQuality q={d.wan_quality} live={isLive ? lv : null} />}

      <section className="panel">
        <header><h2>Logboek</h2></header>
        <div className="log">
          {d.activity.length === 0 && <div><span /><span className="muted">Nog niets gebeurd.</span><span /></div>}
          {d.activity.map((a: any, i: number) => (
            <div key={i}><span className={`dot ${a.level === "error" ? "bad" : a.level === "warn" ? "warn" : a.level === "ok" ? "ok" : ""}`} />
              <span>{a.message}</span><time>{fmtAgo(a.ts)}</time></div>
          ))}
        </div>
      </section>
    </div>
  );
}

const ms = (v?: number | null) => (v == null ? "–" : v < 10 ? `${v.toFixed(1)} ms` : `${Math.round(v)} ms`);
const pct = (v?: number | null) => (v == null ? "–" : `${v < 1 && v > 0 ? v.toFixed(1) : Math.round(v)}%`);

function WanQuality({ q, live }: { q: any; live: any | null }) {
  const active = q.wans.find((w: any) => w.active) ?? q.wans[0];
  const inet = live ? (live.latency ?? []) : (q.history as any[]).filter((h) => h.kind === "internet" && h.wan === active.interface);
  const series = live ? inet.map((h: any) => ({ ts: h.ts, rtt: h.rtt })) : inet.map((h: any) => ({ ts: h.ts, rtt: h.rtt, peak: h.rtt_max }));
  const lossAvg = inet.length ? inet.reduce((a: number, h: any) => a + (h.loss ?? 0), 0) / inet.length : null;
  const lastLive = live?.latency?.[live.latency.length - 1];
  const tone = (p?: any) => !p || p.avg == null ? "" : p.loss >= 5 || p.avg > 100 ? "bad" : p.loss > 0 || p.avg > 40 ? "warn" : "ok";
  const Ping = ({ p }: { p?: any }) => p ? <span className={`tag ${tone(p)}`}>{ms(p.avg)}</span> : <span className="muted">–</span>;
  return (
    <section className="panel">
      <header>
        <h2>WAN-kwaliteit<span className="muted small" style={{ fontFamily: "var(--sans)", fontWeight: 400 }}> ping naar {q.target} en naar de gateway</span></h2>
        <span className="muted small">gem. pakketverlies {pct(lossAvg)}</span>
      </header>
      <div className="table-wrap fit"><table className="t">
        <thead><tr><th>WAN</th><th>Status</th><th className="right">Internet</th><th className="right">Gateway</th><th className="right">Verlies</th></tr></thead>
        <tbody>{q.wans.map((w: any) => (
          <tr key={w.interface}>
            <td><span className="strong mono">{w.interface}</span>{w.gateway && <div className="muted small mono">{w.gateway}</div>}</td>
            <td>{w.active ? <span className="tag ok">Actief</span> : <span className="tag">Standby</span>}</td>
            <td className="num right"><Ping p={w.active && lastLive ? { avg: lastLive.rtt, loss: lastLive.loss } : w.ping?.internet} /></td>
            <td className="num right"><Ping p={w.ping?.gateway} /></td>
            <td className="num right">{pct((w.ping?.internet ?? w.ping?.gateway)?.loss)}</td>
          </tr>
        ))}</tbody>
      </table></div>
      <div className="body">
        {series.length > 0
          ? <LineChart title={`Latency naar internet via ${active.interface}`} data={series} fmt={(v) => ms(v)}
            xRange={live ? [live.now - live.window, live.now] : undefined}
            series={live ? [{ key: "rtt", label: "Latency", color: "var(--s1)", area: true }]
              : [{ key: "rtt", label: "Gemiddeld", color: "var(--s1)", area: true }, { key: "peak", label: "Piek", color: "var(--s2)" }]} />
          : <div className="empty">Nog geen metingen. De eerste verschijnen na een halve minuut.</div>}
      </div>
    </section>
  );
}

function latency(d: any, live: any | null) {
  const last = live?.latency?.[live.latency.length - 1];
  const active = d.wan_quality?.wans?.find((w: any) => w.active) ?? d.wan_quality?.wans?.[0];
  const avg = last?.rtt ?? active?.ping?.internet?.avg;
  return avg == null ? "Latency nog onbekend" : `Latency ${ms(avg)} naar ${d.wan_quality.target}`;
}

/** Devices online as a ring, like the health widget of a controller. */
function Ring({ value, total }: { value: number; total: number }) {
  const r = 17, c = 2 * Math.PI * r, f = total ? value / total : 0;
  return (
    <svg width="44" height="44" viewBox="0 0 44 44" className="ring" aria-hidden>
      <circle cx="22" cy="22" r={r} fill="none" stroke="var(--line-soft)" strokeWidth="5" />
      <circle cx="22" cy="22" r={r} fill="none" stroke={f === 1 ? "var(--ok)" : "var(--bad)"} strokeWidth="5" strokeLinecap="round"
        strokeDasharray={`${c * f} ${c}`} transform="rotate(-90 22 22)" />
    </svg>
  );
}

const ROLE_ICON: Record<string, any> = { router: Router, switch: Network, ap: WifiIcon };

/** Topology: controller on top, every managed device below the device and port where it was learned. */
function Topology({ nodes }: { nodes: any[] }) {
  const root = nodes.find((n) => n.parent == null);
  if (!root || nodes.length < 2) return null;
  const kids = (id: number) => nodes.filter((n) => n.parent === id);
  const Node = ({ n }: { n: any }) => {
    const Icon = ROLE_ICON[n.role] ?? Server;
    const ch = kids(n.id);
    return (
      <li>
        {n.port && <span className="topo-port">{n.port}</span>}
        <a className={`topo-node ${n.online === false ? "off" : ""}`} href={`#/devices/${n.id}`}>
          <span className={`topo-ico ${n.role}`}><Icon size={18} /></span>
          <span className="topo-text"><span className="topo-name">{n.name}</span>
            <span className="topo-sub">{n.board ?? ""}{n.online === false ? " · offline" : ""}</span></span>
          {(n.wifi > 0 || n.wired > 0) && <span className="topo-count" title={`${n.wifi} wifi, ${n.wired} bedraad`}>
            {n.wifi > 0 && <span><WifiIcon size={12} />{n.wifi}</span>}{n.wired > 0 && <span><MonitorSmartphone size={12} />{n.wired}</span>}</span>}
        </a>
        {ch.length > 0 && <ul>{ch.map((c) => <Node key={c.id} n={c} />)}</ul>}
      </li>
    );
  };
  return (
    <section className="panel">
      <header><h2>Topologie</h2><span className="muted small hide-sm-sub">afgeleid uit de bridge-tabellen; onbeheerde switches ertussen zie je niet</span></header>
      <div className="topo-wrap"><ul className="topo"><Node n={root} /></ul></div>
    </section>
  );
}
