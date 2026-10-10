import { useEffect, useMemo, useRef, useState } from "react";
import { fmtTime } from "./ui";

/* ---------- faceplate ---------- */

export type Port = {
  name: string; running: boolean; disabled: boolean; speed: string | null; sfp: boolean; wan: boolean;
  poe: { status?: string; power?: string } | null; rx_bps: number; tx_bps: number; comment?: string | null;
  bridge?: string | null; pvid?: string | null; mac?: string | null;
};

export const portShort = (name: string) => {
  const n = name.match(/(\d+)$/)?.[1] ?? "";
  return name.startsWith("sfp") ? `S${n}` : name.startsWith("ether") ? n : name.slice(0, 4);
};

const portTitle = (p: Port) =>
  `${p.name}${p.comment ? ` (${p.comment})` : ""}: ${p.disabled ? "uitgeschakeld" : p.running ? `link ${p.speed ?? ""}` : "geen link"}` +
  (p.wan ? ", internet" : "") + (p.poe?.power ? `, PoE ${p.poe.power} W` : "");

/** The device's ports drawn as its faceplate: link LED, PoE LED, WAN outline. */
export function Faceplate({ ports, mini, selected, onSelect }: { ports: Port[]; mini?: boolean; selected?: string | null; onSelect?: (name: string) => void }) {
  const copper = ports.filter((p) => !p.sfp), sfp = ports.filter((p) => p.sfp);
  const render = (p: Port) => {
    const cls = ["port", p.sfp && "sfp", p.running && !p.disabled && "up", p.disabled && "disabled", p.wan && "wan",
      p.poe?.power && "poe", selected === p.name && "sel"].filter(Boolean).join(" ");
    const inner = (<><span className="leds"><span className="led link" />{p.poe && <span className={`led poe ${p.poe.power ? "on" : ""}`} />}</span>
      <span className="jack" /><span className="n">{portShort(p.name)}</span></>);
    return mini
      ? <span key={p.name} className={cls} title={portTitle(p)}>{inner}</span>
      : <button key={p.name} className={cls} title={portTitle(p)} aria-pressed={selected === p.name} onClick={() => onSelect?.(p.name)}>{inner}</button>;
  };
  if (!ports.length) return null;
  return (
    <div className={`plate ${mini ? "mini" : ""}`} role={mini ? "img" : "group"} aria-label={`Poorten: ${ports.filter((p) => p.running).length} van ${ports.length} met link`}>
      {copper.length > 0 && <div className="group">{copper.map(render)}</div>}
      {sfp.length > 0 && <div className="group">{sfp.map(render)}</div>}
    </div>
  );
}

/* ---------- line chart ---------- */

export type Series = { key: string; label: string; color: string; area?: boolean };

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const exp = Math.pow(10, Math.floor(Math.log10(v)));
  const f = v / exp;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 4 ? 4 : f <= 5 ? 5 : f <= 8 ? 8 : 10) * exp;
}

/** Time series on one shared axis. Crosshair tooltip lists every series; a table view is one click away. */
export function LineChart({ data, series, height = 220, fmt, max, title }: {
  data: Record<string, number>[]; series: Series[]; height?: number; fmt: (v: number) => string; max?: number; title: string;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(600);
  const [hover, setHover] = useState<number | null>(null);
  const [table, setTable] = useState(false);
  useEffect(() => {
    if (!box.current) return;
    const ro = new ResizeObserver((e) => setW(Math.max(260, e[0].contentRect.width)));
    ro.observe(box.current);
    return () => ro.disconnect();
  }, []);

  const pts = useMemo(() => data.filter((d) => series.some((s) => d[s.key] != null)), [data, series]);
  const m = { l: 52, r: 10, t: 8, b: 22 };
  const iw = w - m.l - m.r, ih = height - m.t - m.b;
  const t0 = pts[0]?.ts ?? 0, t1 = pts[pts.length - 1]?.ts ?? 1;
  const top = max ?? niceMax(Math.max(1, ...pts.flatMap((d) => series.map((s) => d[s.key] ?? 0))));
  const x = (ts: number) => m.l + (t1 === t0 ? iw : ((ts - t0) / (t1 - t0)) * iw);
  const y = (v: number) => m.t + ih - (Math.min(v, top) / top) * ih;
  const path = (key: string) => pts.filter((d) => d[key] != null).map((d, i) => `${i ? "L" : "M"}${x(d.ts).toFixed(1)},${y(d[key]).toFixed(1)}`).join("");
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * top);
  const nx = Math.max(1, Math.min(6, Math.floor(iw / 90)));
  const xt: number[] = pts.length > 1 ? Array.from({ length: nx + 1 }, (_, i) => t0 + ((t1 - t0) * i) / nx) : [];
  const h = hover != null ? pts[hover] : null;

  const onMove = (e: React.PointerEvent) => {
    if (!pts.length || !box.current) return;
    const px = e.clientX - box.current.getBoundingClientRect().left;
    let best = 0;
    for (let i = 1; i < pts.length; i++) if (Math.abs(x(pts[i].ts) - px) < Math.abs(x(pts[best].ts) - px)) best = i;
    setHover(best);
  };

  if (pts.length < 2) return <div className="empty" style={{ height }}>Nog te weinig metingen. De grafiek vult zich vanzelf.</div>;

  return (
    <div>
      {table ? (
        <div className="table-wrap" style={{ maxHeight: height, overflowY: "auto" }}>
          <table className="t"><thead><tr><th>Tijd</th>{series.map((s) => <th key={s.key} className="right">{s.label}</th>)}</tr></thead>
            <tbody>{pts.slice().reverse().map((d) => (
              <tr key={d.ts}><td className="num">{fmtTime(d.ts)}</td>{series.map((s) => <td key={s.key} className="num right">{d[s.key] != null ? fmt(d[s.key]) : "–"}</td>)}</tr>
            ))}</tbody></table>
        </div>
      ) : (
        <div className="chart" ref={box} onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
          <svg height={height} role="img" aria-label={title}>
            <g className="grid">{ticks.map((t: number) => <line key={t} x1={m.l} x2={w - m.r} y1={y(t)} y2={y(t)} />)}</g>
            <g className="axis">
              {ticks.map((t) => <text key={t} x={m.l - 8} y={y(t) + 4} textAnchor="end">{fmt(t)}</text>)}
              {xt.map((t, i) => <text key={i} x={x(t)} y={height - 5} textAnchor={i === 0 ? "start" : i === xt.length - 1 ? "end" : "middle"}>{fmtTime(t)}</text>)}
            </g>
            {series.map((s) => s.area && (
              <path key={s.key + "a"} d={`${path(s.key)}L${x(t1)},${y(0)}L${x(t0)},${y(0)}Z`} fill={s.color} opacity={0.1} />
            ))}
            {series.map((s) => <path key={s.key} d={path(s.key)} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />)}
            {h && <line className="cross" x1={x(h.ts)} x2={x(h.ts)} y1={m.t} y2={m.t + ih} />}
            {h && series.map((s) => h[s.key] != null && <circle key={s.key} cx={x(h.ts)} cy={y(h[s.key])} r={4} fill={s.color} stroke="var(--panel)" strokeWidth={2} />)}
          </svg>
          {h && (
            <div className="tip" style={{ left: Math.min(w - 80, Math.max(80, x(h.ts))), top: m.t + 2 }}>
              <div style={{ opacity: 0.75, marginBottom: 2 }}>{fmtTime(h.ts)}</div>
              {series.map((s) => <div key={s.key}><span className="k" style={{ background: s.color }} /><b>{h[s.key] != null ? fmt(h[s.key]) : "–"}</b> {s.label}</div>)}
            </div>
          )}
        </div>
      )}
      <div className="spread" style={{ marginTop: 8 }}>
        {series.length > 1
          ? <div className="legend">{series.map((s) => <span key={s.key}><span className="k" style={{ background: s.color }} />{s.label}</span>)}</div>
          : <span />}
        <button className="btn sm" onClick={() => setTable(!table)}>{table ? "Grafiek" : "Tabel"}</button>
      </div>
    </div>
  );
}
