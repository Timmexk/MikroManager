import { useState } from "react";
import { ArrowDown, ArrowUp, Radio } from "lucide-react";
import { api } from "../api";
import { useApp } from "../App";
import { Faceplate, LineChart } from "../components";
import { bps, fmtAgo, fmtBps, fmtBytes, Loading, Meter, Seg, Status, useLoad } from "../ui";

export default function Dashboard() {
  const { site } = useApp();
  const [hours, setHours] = useState<"1" | "6" | "24">("6");
  const o = useLoad(() => api.get(`/api/sites/${site.id}/overview?hours=${hours}`), [site.id, hours], 10000);
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

  const [rx, rxU] = fmtBps(d.wan.rx_bps), [tx, txU] = fmtBps(d.wan.tx_bps);
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
        <Seg value={hours} onChange={setHours} options={[["1", "1 uur"], ["6", "6 uur"], ["24", "24 uur"]]} />
      </div>

      {!allUp && <div className="banner bad"><strong>Offline:</strong> {d.devices.offline.join(", ")}</div>}
      {d.updates > 0 && (
        <div className="banner info">
          <span className="grow">{d.updates === 1 ? "Voor 1 apparaat is een RouterOS-update beschikbaar." : `Voor ${d.updates} apparaten is een RouterOS-update beschikbaar.`}</span>
          <a className="btn sm" href="#/maintenance">Updates bekijken</a>
        </div>
      )}

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
              <div className="hide-sm">{v.busy ? <Status online={v.online} busy={v.busy} /> : <Meter value={v.cpu} />}</div>
            </a>
          ))}
        </div>
      </section>

      <div className="cols">
        <section className="panel">
          <header>
            <h2>Internet{d.wan.interface ? <span className="muted small" style={{ fontFamily: "var(--sans)", fontWeight: 400 }}> via {d.wan.interface}</span> : null}</h2>
            <div className="row" style={{ gap: 18 }}>
              <span className="row" style={{ gap: 5 }}><ArrowDown size={16} color="var(--s1)" /><span className="figure" style={{ fontSize: 22 }}>{rx}<small>{rxU}</small></span></span>
              <span className="row" style={{ gap: 5 }}><ArrowUp size={16} color="var(--s2)" /><span className="figure" style={{ fontSize: 22 }}>{tx}<small>{txU}</small></span></span>
            </div>
          </header>
          <div className="body">
            {d.wan.interface
              ? <LineChart title="Internetverkeer" data={d.wan.history} fmt={bps}
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
              <header><h2>Meeste verkeer via wifi</h2><a className="btn sm" href="#/clients">Alle clients</a></header>
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
