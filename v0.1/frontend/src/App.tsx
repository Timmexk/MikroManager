import { createContext, FormEvent, useContext, useEffect, useState } from "react";
import { LayoutDashboard, LogOut, MonitorSmartphone, Moon, Network, Server, Settings as Cog, Sun, SunMoon, Wifi as WifiIcon, Wrench } from "lucide-react";
import { api } from "./api";
import { Field, Loading, UiProvider, useAction, useLoad } from "./ui";
import Dashboard from "./pages/Dashboard";
import Devices from "./pages/Devices";
import Clients from "./pages/Clients";
import Wifi from "./pages/Wifi";
import Networks from "./pages/Networks";
import Maintenance from "./pages/Maintenance";
import Settings from "./pages/Settings";

export type Site = { id: number; name: string; settings: Record<string, any>; devices: number; online: number };
type AppCtx = { sites: Site[]; site: Site; reloadSites: () => Promise<void>; setSiteId: (id: number) => void; state: any };
const Ctx = createContext<AppCtx>(null as any);
export const useApp = () => useContext(Ctx);

// path, label, icon, short label for the phone tab bar
const NAV = [
  ["", "Overzicht", LayoutDashboard, "Overzicht"], ["devices", "Apparaten", Server, "Apparaten"],
  ["clients", "Clients", MonitorSmartphone, "Clients"], ["wifi", "Wifi", WifiIcon, "Wifi"],
  ["networks", "Netwerken", Network, "Netwerk"], ["maintenance", "Onderhoud", Wrench, "Beheer"],
  ["settings", "Instellingen", Cog, "Meer"],
] as const;

function useHash(): string[] {
  const read = () => window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  const [parts, setParts] = useState(read);
  useEffect(() => {
    const on = () => setParts(read());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return parts;
}

const stored = (k: string) => { try { return localStorage.getItem(k); } catch { return null; } };
const store = (k: string, v: string) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } };

function useTheme() {
  const [theme, setTheme] = useState(stored("tc-theme") || "auto");
  useEffect(() => {
    if (theme === "auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", theme);
    store("tc-theme", theme);
  }, [theme]);
  const next = () => setTheme(theme === "auto" ? "light" : theme === "light" ? "dark" : "auto");
  return { theme, next };
}

export default function App() {
  const state = useLoad(() => api.get("/api/state"), []);
  useEffect(() => {
    const on = () => state.reload();
    window.addEventListener("tc-unauthorized", on);
    return () => window.removeEventListener("tc-unauthorized", on);
  }, [state.reload]);
  return (
    <UiProvider>
      {!state.data ? <div className="auth"><Loading error={state.error} /></div>
        : state.data.setup_needed ? <Auth mode="setup" demo={state.data.demo} done={state.reload} />
          : !state.data.user ? <Auth mode="login" demo={state.data.demo} done={state.reload} />
            : <Shell state={state.data} onLogout={state.reload} />}
    </UiProvider>
  );
}

function Auth({ mode, done, demo }: { mode: "setup" | "login"; done: () => void; demo: boolean }) {
  const [username, setU] = useState(mode === "setup" ? "admin" : "");
  const [password, setP] = useState("");
  const { busy, run } = useAction();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    run("auth", async () => { await api.post(`/api/${mode}`, { username, password }); done(); });
  };
  return (
    <div className="auth">
      <form className="card" onSubmit={submit}>
        <div>
          <h1>{mode === "setup" ? "Welkom bij TikControl" : "Inloggen"}</h1>
          <p className="muted" style={{ marginTop: 6 }}>
            {mode === "setup" ? "Maak het beheerdersaccount aan. Dit is het enige account; het staat alleen op deze server." : "Beheer voor je MikroTik-netwerk."}
          </p>
        </div>
        {demo && <div className="banner info small">Demomodus: de apparaten zijn gesimuleerd en alles wordt bij een herstart gewist.</div>}
        <Field label="Gebruikersnaam"><input className="input" value={username} onChange={(e) => setU(e.target.value)} autoComplete="username" required /></Field>
        <Field label="Wachtwoord" hint={mode === "setup" ? "Minstens 8 tekens." : undefined}>
          <input className="input" type="password" value={password} onChange={(e) => setP(e.target.value)} autoFocus
            autoComplete={mode === "setup" ? "new-password" : "current-password"} minLength={mode === "setup" ? 8 : 1} required />
        </Field>
        <button className="btn primary" disabled={!!busy} style={{ justifyContent: "center" }}>{mode === "setup" ? "Account aanmaken" : "Inloggen"}</button>
      </form>
    </div>
  );
}

function Shell({ state, onLogout }: { state: any; onLogout: () => void }) {
  const sites = useLoad<Site[]>(() => api.get("/api/sites"), [], 30000);
  const [siteId, setSiteIdRaw] = useState<number | null>(Number(stored("tc-site")) || null);
  const parts = useHash();
  const { theme, next } = useTheme();
  const setSiteId = (id: number) => { setSiteIdRaw(id); store("tc-site", String(id)); };

  if (!sites.data) return <div className="auth"><Loading error={sites.error} /></div>;
  const site = sites.data.find((s) => s.id === siteId) ?? sites.data[0];
  const reloadSites = async () => { await sites.reload(); };
  const logout = async () => { await api.post("/api/logout"); onLogout(); };
  const page = parts[0] ?? "";
  const ThemeIcon = theme === "auto" ? SunMoon : theme === "light" ? Sun : Moon;

  if (!site) return <FirstSite done={async (id) => { await sites.reload(); setSiteId(id); }} />;

  return (
    <Ctx.Provider value={{ sites: sites.data, site, reloadSites, setSiteId, state }}>
      <div className="shell">
        <aside className="side">
          <div className="brand"><i><b /><b /><b /></i>TikControl</div>
          <select className="site-pick" value={site.id} onChange={(e) => setSiteId(Number(e.target.value))} aria-label="Site">
            {sites.data.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
          <nav className="nav">
            {NAV.map(([path, label, Icon]) => <a key={path} href={`#/${path}`} className={page === path ? "on" : ""}><Icon size={18} />{label}</a>)}
          </nav>
          <div className="side-foot">
            {state.demo && <span>Demomodus, gesimuleerde apparaten</span>}
            <button onClick={next}><ThemeIcon size={16} />Thema: {theme === "auto" ? "systeem" : theme === "light" ? "licht" : "donker"}</button>
            <button onClick={logout}><LogOut size={16} />Uitloggen ({state.user})</button>
            <span>v{state.version}</span>
          </div>
        </aside>
        <main className="main" key={site.id}>
          {page === "" && <Dashboard />}
          {page === "devices" && <Devices deviceId={parts[1] ? Number(parts[1]) : null} />}
          {page === "clients" && <Clients />}
          {page === "wifi" && <Wifi />}
          {page === "networks" && <Networks />}
          {page === "maintenance" && <Maintenance />}
          {page === "settings" && <Settings onLogout={logout} themeLabel={theme} nextTheme={next} />}
        </main>
        <nav className="tabbar">
          {NAV.map(([path, , Icon, short]) => <a key={path} href={`#/${path}`} className={page === path ? "on" : ""}><Icon size={20} />{short}</a>)}
        </nav>
      </div>
    </Ctx.Provider>
  );
}

function FirstSite({ done }: { done: (id: number) => void }) {
  const [name, setName] = useState("Thuis");
  const { busy, run } = useAction();
  return (
    <div className="auth">
      <form className="card" onSubmit={(e) => { e.preventDefault(); run("s", async () => done((await api.post("/api/sites", { name })).id)); }}>
        <div><h1>Je eerste site</h1>
          <p className="muted" style={{ marginTop: 6 }}>Een site is één locatie met een eigen router, access points en wifi-netwerken. Je kunt er later meer toevoegen.</p></div>
        <Field label="Naam"><input className="input" value={name} onChange={(e) => setName(e.target.value)} required autoFocus /></Field>
        <button className="btn primary" disabled={!!busy} style={{ justifyContent: "center" }}>Site aanmaken</button>
      </form>
    </div>
  );
}
