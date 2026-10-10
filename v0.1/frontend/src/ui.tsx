import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import { Loader2, X } from "lucide-react";

/* ---------- formatting ---------- */

export function fmtBps(v?: number | null): [string, string] {
  if (v == null || isNaN(v)) return ["–", ""];
  if (v >= 1e9) return [(v / 1e9).toFixed(2), "Gbps"];
  if (v >= 1e6) return [(v / 1e6).toFixed(v >= 1e7 ? 0 : 1), "Mbps"];
  if (v >= 1e3) return [(v / 1e3).toFixed(0), "kbps"];
  return [v.toFixed(0), "bps"];
}
export const bps = (v?: number | null) => fmtBps(v).join(" ").trim();

export function fmtBytes(v?: number | null): string {
  if (!v) return "–";
  const units = ["B", "kB", "MB", "GB", "TB"];
  let i = 0;
  while (v >= 1000 && i < units.length - 1) {
    v /= 1000;
    i++;
  }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${units[i]}`;
}

export function fmtUptime(sec?: number | null): string {
  if (!sec) return "–";
  const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60);
  if (d) return `${d} d ${h} u`;
  if (h) return `${h} u ${m} min`;
  return `${Math.max(1, m)} min`;
}

export function fmtAgo(ts?: number | null): string {
  if (!ts) return "nooit";
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "zojuist";
  if (s < 3600) return `${Math.floor(s / 60)} min geleden`;
  if (s < 86400) return `${Math.floor(s / 3600)} uur geleden`;
  return new Date(ts * 1000).toLocaleDateString("nl-NL", { day: "numeric", month: "short" });
}

export const fmtDateTime = (ts: number) =>
  new Date(ts * 1000).toLocaleString("nl-NL", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
export const fmtTime = (ts: number) => new Date(ts * 1000).toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit" });

export const ROLE: Record<string, string> = { router: "Router", switch: "Switch", ap: "Access point" };
export const bandLabel = (b?: string | null) => (!b ? "" : b.startsWith("2") ? "2,4 GHz" : b.startsWith("6") ? "6 GHz" : "5 GHz");

/* ---------- data loading ---------- */

export function useLoad<T = any>(fn: () => Promise<T>, deps: unknown[], intervalMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const gen = useRef(0);

  const reload = useCallback(async () => {
    const mine = ++gen.current;
    try {
      const d = await fnRef.current();
      if (mine === gen.current) {
        setData(d);
        setError(null);
      }
    } catch (e: any) {
      if (mine === gen.current) setError(e.message || "Laden mislukt");
    } finally {
      if (mine === gen.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    setData(null);
    setLoading(true);
    reload();
    if (!intervalMs) return;
    const t = setInterval(() => document.visibilityState === "visible" && reload(), intervalMs);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading, reload };
}

/* ---------- toasts & confirm ---------- */

type Toast = { id: number; text: string; bad?: boolean };
type Confirm = { title: string; text: ReactNode; action: string; danger?: boolean; resolve: (ok: boolean) => void };
const Ctx = createContext<{ toast: (text: string, bad?: boolean) => void; confirm: (c: Omit<Confirm, "resolve">) => Promise<boolean> }>(null as any);
export const useUi = () => useContext(Ctx);

export function UiProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [conf, setConf] = useState<Confirm | null>(null);
  const toast = useCallback((text: string, bad = false) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-2), { id, text, bad }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), bad ? 8000 : 4000);
  }, []);
  const confirm = useCallback((c: Omit<Confirm, "resolve">) => new Promise<boolean>((resolve) => setConf({ ...c, resolve })), []);
  const answer = (ok: boolean) => {
    conf?.resolve(ok);
    setConf(null);
  };
  return (
    <Ctx.Provider value={{ toast, confirm }}>
      {children}
      {conf && (
        <Modal title={conf.title} onClose={() => answer(false)}
          footer={<><button className="btn" onClick={() => answer(false)}>Annuleren</button>
            <button className={`btn ${conf.danger ? "danger" : "primary"}`} autoFocus onClick={() => answer(true)}>{conf.action}</button></>}>
          <div style={{ lineHeight: 1.55 }}>{conf.text}</div>
        </Modal>
      )}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => <div key={t.id} className={`toast ${t.bad ? "bad" : ""}`}>{t.text}</div>)}
      </div>
    </Ctx.Provider>
  );
}

/** Run an async action with a busy flag and error toast. */
export function useAction() {
  const { toast } = useUi();
  const [busy, setBusy] = useState<string | null>(null);
  const run = async (key: string, fn: () => Promise<unknown>, done?: string) => {
    setBusy(key);
    try {
      await fn();
      if (done) toast(done);
      return true;
    } catch (e: any) {
      toast(e.message || "Mislukt", true);
      return false;
    } finally {
      setBusy(null);
    }
  };
  return { busy, run };
}

/* ---------- components ---------- */

export function Modal({ title, children, footer, onClose, wide }: { title: string; children: ReactNode; footer?: ReactNode; onClose: () => void; wide?: boolean }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? "wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <header><h2>{title}</h2><button className="btn icon" onClick={onClose} aria-label="Sluiten"><X size={18} /></button></header>
        <div className="body">{children}</div>
        {footer && <footer>{footer}</footer>}
      </div>
    </div>
  );
}

export function Drawer({ title, sub, children, onClose }: { title: ReactNode; sub?: ReactNode; children: ReactNode; onClose: () => void }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <aside className="drawer" role="dialog" aria-label="Details">
      <header><div className="grow"><h2>{title}</h2>{sub && <div className="muted small" style={{ marginTop: 4 }}>{sub}</div>}</div>
        <button className="btn icon" onClick={onClose} aria-label="Sluiten"><X size={18} /></button></header>
      <div className="body">{children}</div>
    </aside>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return <label className="field"><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>;
}

export function Check({ checked, onChange, label, hint }: { checked: boolean; onChange: (v: boolean) => void; label: string; hint?: string }) {
  return (
    <label className="check">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span>{label}{hint && <small>{hint}</small>}</span>
    </label>
  );
}

export function Seg<T extends string>({ value, onChange, options }: { value: T; onChange: (v: T) => void; options: [T, string][] }) {
  return (
    <div className="seg" role="tablist">
      {options.map(([v, label]) => (
        <button key={v} role="tab" aria-selected={v === value} className={v === value ? "on" : ""} onClick={() => onChange(v)}>{label}</button>
      ))}
    </div>
  );
}

export function Busy({ on, children }: { on: boolean; children: ReactNode }) {
  return <>{on ? <Loader2 size={15} className="spin" /> : null}{children}</>;
}

export function Status({ online, busy }: { online: boolean | null | undefined; busy?: string | null }) {
  if (busy) return <span className="tag warn"><Loader2 size={12} className="spin" />{busy}</span>;
  if (online == null) return <span className="tag">Wordt gecontroleerd</span>;
  return online ? <span className="tag ok">Online</span> : <span className="tag bad">Offline</span>;
}

export function Signal({ dbm }: { dbm?: number | null }) {
  if (dbm == null) return null;
  const level = dbm >= -55 ? 4 : dbm >= -65 ? 3 : dbm >= -72 ? 2 : 1;
  return (
    <span className="row" style={{ gap: 6 }} title={`${dbm} dBm`}>
      <span className="bars" aria-hidden>{[5, 8, 11, 14].map((h, i) => <i key={i} className={i < level ? "on" : ""} style={{ height: h }} />)}</span>
      <span className="num small muted">{dbm} dBm</span>
    </span>
  );
}

export function Meter({ value }: { value?: number | null }) {
  if (value == null) return <span className="muted">–</span>;
  return (
    <span className="row" style={{ gap: 8 }}>
      <span className={`meter ${value > 85 ? "hot" : ""}`}><i style={{ width: `${Math.min(100, Math.max(2, value))}%` }} /></span>
      <span className="num small">{Math.round(value)}%</span>
    </span>
  );
}

export function Loading({ error }: { error?: string | null }) {
  if (error) return <div className="banner bad">{error}</div>;
  return <div className="empty"><Loader2 className="spin" /></div>;
}
