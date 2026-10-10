import { FormEvent, useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { api } from "../api";
import { useApp } from "../App";
import { Field, useAction, useLoad, useUi } from "../ui";

export default function Settings({ onLogout, themeLabel, nextTheme }: { onLogout: () => void; themeLabel: string; nextTheme: () => void }) {
  const { site, sites, reloadSites, setSiteId, state } = useApp();
  const devs = useLoad<any[]>(() => api.get(`/api/sites/${site.id}/devices`), [site.id]);
  const { busy, run } = useAction();
  const { confirm } = useUi();
  const [name, setName] = useState(site.name);
  const [newSite, setNewSite] = useState("");
  const [pw, setPw] = useState({ current: "", new: "" });
  const controller = devs.data?.find((d) => d.is_controller)?.id ?? "";
  const routers = devs.data?.filter((d) => d.role === "router") ?? [];

  const removeSite = async () => {
    if (await confirm({ title: `Site ${site.name} verwijderen?`, action: "Site verwijderen", danger: true,
      text: `De site verdwijnt uit TikControl met ${site.devices} apparaten, de wifi-netwerken en alle back-ups. Op de apparaten zelf verandert niets.` }))
      run("delsite", async () => { await api.del(`/api/sites/${site.id}`); await reloadSites(); }, "Site verwijderd");
  };

  return (
    <div className="stack" style={{ maxWidth: 760 }}>
      <div className="page-head" style={{ marginBottom: 0 }}><h1>Instellingen</h1></div>

      <section className="panel">
        <header><h2>Deze site</h2></header>
        <div className="body form">
          <form className="row" onSubmit={(e) => { e.preventDefault(); run("name", async () => { await api.patch(`/api/sites/${site.id}`, { name }); await reloadSites(); }, "Naam opgeslagen"); }}>
            <div className="grow"><Field label="Naam"><input className="input" value={name} onChange={(e) => setName(e.target.value)} required /></Field></div>
            <button className="btn" style={{ alignSelf: "end" }} disabled={!!busy || name === site.name}>Opslaan</button>
          </form>
          {routers.length > 1 && (
            <Field label="Wifi-controller" hint="De router waarop CAPsMAN draait en waar netwerken worden aangemaakt.">
              <select className="input" value={controller} onChange={(e) => run("ctrl", async () => { await api.patch(`/api/sites/${site.id}`, { controller_id: Number(e.target.value) }); devs.reload(); }, "Controller gewijzigd")}>
                {routers.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select></Field>
          )}
          <div><button className="btn danger" onClick={removeSite} disabled={!!busy || sites.length < 2} title={sites.length < 2 ? "De laatste site kun je niet verwijderen" : undefined}><Trash2 size={15} />Site verwijderen</button></div>
        </div>
      </section>

      <section className="panel">
        <header><h2>Sites</h2></header>
        <table className="t"><tbody>{sites.map((s) => (
          <tr key={s.id}><td className="strong">{s.name}{s.id === site.id && <span className="tag accent" style={{ marginLeft: 8 }}>Geopend</span>}</td>
            <td className="muted">{s.devices === 0 ? "geen apparaten" : `${s.online} van ${s.devices} apparaten online`}</td>
            <td className="right">{s.id !== site.id && <button className="btn sm" onClick={() => { setSiteId(s.id); location.hash = "#/"; }}>Openen</button>}</td></tr>
        ))}</tbody></table>
        <form className="body row" style={{ borderTop: "1px solid var(--line-soft)" }}
          onSubmit={(e: FormEvent) => { e.preventDefault(); run("add", async () => { const s = await api.post("/api/sites", { name: newSite }); setNewSite(""); await reloadSites(); setSiteId(s.id); location.hash = "#/devices"; }, "Site aangemaakt"); }}>
          <input className="input grow" value={newSite} onChange={(e) => setNewSite(e.target.value)} placeholder="Naam van de nieuwe site" aria-label="Naam van de nieuwe site" required />
          <button className="btn" disabled={!!busy}><Plus size={15} />Site toevoegen</button>
        </form>
      </section>

      <section className="panel">
        <header><h2>Account</h2><span className="muted small">ingelogd als {state.user}</span></header>
        <form className="body form" onSubmit={(e) => { e.preventDefault(); run("pw", async () => { await api.post("/api/password", pw); onLogout(); }, "Wachtwoord gewijzigd. Log opnieuw in."); }}>
          <div className="two">
            <Field label="Huidig wachtwoord"><input className="input" type="password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} autoComplete="current-password" required /></Field>
            <Field label="Nieuw wachtwoord" hint="Minstens 8 tekens."><input className="input" type="password" value={pw.new} onChange={(e) => setPw({ ...pw, new: e.target.value })} autoComplete="new-password" minLength={8} required /></Field>
          </div>
          <div className="row wrap">
            <button className="btn" disabled={!!busy}>Wachtwoord wijzigen</button>
            <button type="button" className="btn" onClick={nextTheme}>Thema: {themeLabel === "auto" ? "systeem" : themeLabel === "light" ? "licht" : "donker"}</button>
            <button type="button" className="btn" onClick={onLogout}>Uitloggen</button>
          </div>
        </form>
      </section>
      <p className="muted small">TikControl {state.version}{state.demo ? ", demomodus" : ""}. Wachtwoorden van apparaten staan versleuteld in de database; de sleutel staat in <span className="mono">secret.key</span> in de data-map.</p>
    </div>
  );
}
