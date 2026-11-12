# MikroManager (proefversie v0.2)

> **Tweede proefversie.** Alles uit v0.1, plus interfacebeheer per apparaat met een veilige modus.
> Net als v0.1 alleen getest tegen de meegeleverde simulator, nog niet tegen echte hardware. Technische namen
> uit de werknaam (`TIKCONTROL_*`, `tikcontrol.db`, het kenmerk `tc-` op de router) blijven staan, zodat een
> bestaande v0.1-installatie gewoon doorwerkt: v0.2 gebruikt dezelfde data en instellingen.

## Nieuw in v0.2: interfaces per apparaat

Onder **Apparaten → (apparaat) → Interfaces** staan alle interfaces: ethernet, SFP, bridge, VLAN, bonding, wifi,
PPPoE, LTE en WireGuard, met status, MTU en verkeer. Klik op een interface (of op een poort in de poortkaart):

| Soort | Wat je instelt |
|---|---|
| Alle | aan/uit, label, MTU |
| Ethernet en SFP | automatisch onderhandelen of een vaste snelheid en duplex |
| PoE-poorten | PoE-uitgang (automatisch, altijd aan, uit) en prioriteit |
| Poorten | bridge-lidmaatschap, PVID, welke frames worden toegelaten, tagged VLAN's |
| VLAN | toevoegen, VLAN-ID, op welke interface, verwijderen |
| Wifi | aan/uit en label; SSID's en kanalen blijven onder Wifi |

**Live grafieken.** Het overzicht en de apparaatpagina openen op **Live**: zolang je kijkt, leest MikroManager
elke 2 seconden de interfacetellers en de CPU van de apparaten op die pagina, en pingt elke 6 seconden naar
1.1.1.1. De laatste 10 minuten schuiven mee; bij openen worden ze aangevuld met de opgeslagen metingen. Kijkt
er een minuut niemand, dan stopt het snelle meten vanzelf. Instelbaar met `TIKCONTROL_LIVE_INTERVAL` (seconden)
en `TIKCONTROL_LIVE_WINDOW` (seconden). Voor langere periodes kies je 1, 6 of 24 uur.

**Veilige modus.** De REST API van RouterOS heeft geen safe mode, dus MikroManager bouwt die zelf: voor een
wijziging die iets kan afsluiten (uitzetten, snelheid, MTU, PoE, bridge, PVID, VLAN's) zet de app eerst een
scheduler `mm-terugdraai-…` op het apparaat. Die draait na 90 seconden de omgekeerde commando's en verwijdert
zichzelf. Daarna voert de app de wijziging uit en controleert of **alle** apparaten van de site nog antwoorden.

- Alles bereikbaar: de scheduler wordt weggehaald, de wijziging blijft.
- Het apparaat zelf is onbereikbaar: het apparaat zet de oude instellingen na 90 seconden zelf terug.
- Een ander apparaat valt weg (bijvoorbeeld een AP achter een poort of PoE die je uitzet): de app draait de
  wijziging meteen terug.

Een label wijzigen of een VLAN-interface toevoegen gebeurt zonder veilige modus. VLAN-filtering op een bridge
zet MikroManager bewust niet aan of uit.

Zelfgehoste beheerinterface voor MikroTik-netwerken, in de geest van UniFi Network: één plek voor
apparaten, clients, wifi-netwerken, VLAN's, updates en back-ups. Draait direct op Linux (systemd) of in Docker, geen cloud, geen account.

- **Apparaten**: status, CPU/geheugen, poortkaart met link, snelheid, PoE en verkeer per poort.
- **Clients**: DHCP-leases, wifi-registraties en switchpoorten samengevoegd per MAC. Naam geven, vast IP, opnieuw verbinden, blokkeren.
- **Wifi**: SSID's één keer instellen, uitrollen naar alle access points via CAPsMAN (`wifi`-menu, RouterOS 7.13+). AP's koppelen met één klik.
- **Netwerken**: VLAN + adres + DHCP-server (+ optioneel gastisolatie) in één stap, met terugdraaien als een stap mislukt.
- **Onderhoud**: RouterOS en RouterBOOT bijwerken (per apparaat of alles op volgorde), nachtelijke config-export met diff.
- **Meerdere sites**, donker/licht thema, werkt op telefoon.

> **Status: v0.2, getest tegen een simulator, nog niet tegen echte hardware.**
> Alle 125 end-to-end-controles slagen tegen de meegeleverde RouterOS-simulator. Die simulator is gebouwd
> op de MikroTik-documentatie, niet op een echte router. Lees [Eerst op echte hardware](#eerst-op-echte-hardware)
> voordat je dit op je productienetwerk loslaat.

## Proberen zonder router

```bash
docker compose build
docker run --rm -p 8080:8080 -e TIKCONTROL_DEMO=1 tikcontrol:0.2.0
```

Open http://localhost:8080, maak een account en klik rond. Demomodus start vijf gesimuleerde apparaten
(hAP ax², CRS310, hEX PoE, twee cAP ax) met clients. Alles wordt bij elke herstart gewist.

## Installeren op Linux (aanbevolen)

Werkt op elke distro met systemd en Python 3.10 of nieuwer: Debian 12+, Ubuntu 22.04+, Fedora, Arch/CachyOS,
openSUSE. Vooraf nodig: Python met venv (Debian/Ubuntu: `sudo apt install python3-venv`) en `curl` of `wget`.
De frontend wordt kant-en-klaar gedownload (gebouwd door GitHub Actions), dus `npm` is op de server niet nodig.
Zelf bouwen kan met `sudo MM_FRONTEND=build bash linux/install.sh` (vraagt `nodejs` en `npm`).

```bash
git clone https://github.com/Timmexk/MikroManager.git
cd MikroManager/v0.2
sudo bash linux/install.sh
```

Het script maakt een systeemgebruiker `mikromanager`, zet het programma in `/opt/mikromanager` en start de
systemd-service `mikromanager`. Bijwerken: `git pull` en het script opnieuw draaien. Je data en instellingen
blijven daarbij staan.

| Pad | Inhoud |
|---|---|
| `/etc/mikromanager/mikromanager.env` | Instellingen: poort, poll-interval, HTTPS-cookie, demomodus |
| `/var/lib/mikromanager/` | `tikcontrol.db`, `secret.key` en `backups/`. **Bewaar `secret.key` samen met de database.** |
| `/opt/mikromanager/` | Programma en Python-omgeving, wordt bij elke update vervangen |

```bash
sudo systemctl restart mikromanager      # na het wijzigen van de instellingen
journalctl -u mikromanager -f            # logs
sudo bash linux/install.sh --uninstall      # verwijderen, data blijft staan
sudo bash linux/install.sh --purge          # alles verwijderen, ook de data
```

De service is afgeschermd: hij draait niet als root, mag alleen in `/var/lib/mikromanager` schrijven en ziet
de home-mappen niet. Het back-upschema gebruikt de tijdzone van het systeem (`timedatectl`).

## Installeren met Docker (Unraid)

Op Unraid of als je liever een container gebruikt. Start vanuit deze map:

```bash
docker compose up -d --build
```

`docker-compose.yml` zet de data in `/mnt/user/appdata/tikcontrol`. Daarin staan `tikcontrol.db`,
`secret.key` en `backups/`. **Bewaar `secret.key` samen met de database**: zonder die sleutel zijn de
opgeslagen routerwachtwoorden niet meer te lezen.

| Variabele | Standaard | Betekenis |
|---|---|---|
| `TZ` | UTC | Tijdzone voor het back-upschema |
| `TIKCONTROL_POLL` | `15` | Seconden tussen metingen |
| `TIKCONTROL_SECURE_COOKIE` | uit | Zet op `1` als je MikroManager via HTTPS (reverse proxy) aanbiedt |
| `TIKCONTROL_DEMO` | uit | Simulator in plaats van echte apparaten |

MikroManager bewaart beheerdersrechten voor je routers. Zet het niet open aan internet; bereik het via VPN
of een reverse proxy met eigen authenticatie.

## Router voorbereiden

MikroManager gebruikt de REST API van RouterOS 7 (`https://router/rest`). Per apparaat:

```routeros
# eigen gebruiker met alleen wat nodig is
/user group add name=mikromanager policy=read,write,policy,test,sensitive,reboot,rest-api,api
/user add name=mikromanager group=mikromanager password="kies-een-lang-wachtwoord" address=192.168.88.50/32

# HTTPS aanzetten met een zelfondertekend certificaat, alleen bereikbaar voor de MikroManager-host
/certificate add name=mikromanager-web common-name=router.lan days-valid=3650 key-usage=tls-server
/certificate sign mikromanager-web
/ip service set www-ssl certificate=mikromanager-web address=192.168.88.50/32 disabled=no
```

Vervang `192.168.88.50` door het adres van de machine waarop MikroManager draait. `address=` op `www-ssl` beperkt ook WebFig tot
dat adres. Krijg je bij toevoegen "Inloggen geweigerd", voeg dan `web` toe aan de policy van de groep.
HTTP (`www`) werkt ook, maar dan gaat het wachtwoord onversleuteld over het netwerk.

Daarna in MikroManager: **Apparaten → Apparaat toevoegen**. De eerste router van een site wordt de wifi-controller.

## Wat MikroManager op je router schrijft

Alles wat MikroManager aanmaakt is herkenbaar en verder blijft het van je configuratie af:

| Waar | Herkenbaar aan | Wanneer |
|---|---|---|
| `/interface/wifi/security`, `datapath`, `channel`, `configuration` | naam begint met `tc-` | Wifi → wijzigingen toepassen |
| `/interface/wifi/provisioning` | comment `tc:2g:ax`, `tc:5g:ax` (en `:ac`) | idem |
| `/interface/wifi/capsman` | `enabled=yes interfaces=<bridge>` | eerste keer toepassen |
| `/interface/wifi/access-list` | comment `tc:blocked …` | client blokkeren |
| `/interface/vlan`, `/ip/address`, `/ip/pool`, `/ip/dhcp-server`, `/ip/dhcp-server/network`, `/interface/bridge/vlan`, `/interface/list/member` | naam `tc-<naam>` of comment `tc:net:<naam>` | netwerk toevoegen |
| `/ip/firewall/filter` + address-list `tc-private` | comment `tc:net:<naam> isolatie` | netwerk met "afschermen" |
| Op een AP: `/interface/wifi/cap`, datapath `tc-cap`, `configuration.manager=capsman` op de radio's | | AP koppelen |
| `/system/scheduler` `mm-terugdraai-…` | naam | tijdens een wijziging met veilige modus, verdwijnt daarna weer |
| `/interface`, `/interface/ethernet`, `/interface/ethernet/poe`, `/interface/bridge/port`, `/interface/bridge/vlan`, `/interface/vlan` | | alleen wat je onder Interfaces zelf wijzigt |
| `/ip/kid-control` profielen `mm-pauze` en `mm-tijd-<van>-<tot>`, `/ip/kid-control/device` naam `mm-<mac>` | naam begint met `mm-` | client pauzeren of een tijdschema geven |

Verder leest MikroManager op de router: IPv6-adressen per client uit `/ipv6/neighbor` (alleen globale adressen
worden getoond), live verbruik per client uit `/ip/kid-control/device`, en elke poll een korte ping
(4 pakketten) naar 1.1.1.1 via de actieve WAN en naar de gateway van elke WAN voor de WAN-kwaliteit.
Wake-on-LAN gaat via `/tool/wol`.

Wifi-wijzigingen worden nooit direct doorgevoerd: je ziet eerst de lijst met stappen (met de exacte
eigenschappen) en past ze dan toe. Dezelfde stappen twee keer toepassen verandert niets.

Wat MikroManager bewust **niet** doet: `vlan-filtering` op een bridge aan- of uitzetten, bestaande
firewallregels wijzigen, objecten zonder `tc-`-kenmerk aanpassen.

### Zo is wifi opgebouwd

```
WLAN "Thuis-IoT" (VLAN 30, 2,4 + 5 GHz)
  security       tc-thuis-iot        wpa2-psk, passphrase, ft
  datapath       tc-thuis-iot        bridge=bridge vlan-id=30
  configuration  tc-thuis-iot-2g     ssid, country, security, datapath, channel=tc-ch-2g
  configuration  tc-thuis-iot-5g     ... channel=tc-ch-5g
provisioning  supported-bands=2ghz-ax  master=tc-thuis-2g  slaves=tc-thuis-iot-2g
provisioning  supported-bands=5ghz-ax  master=tc-thuis-5g  slaves=tc-thuis-iot-5g,tc-thuis-gast-5g
```

Het eerste netwerk in de lijst is per band de master-configuratie; de rest wordt een virtuele interface.

## Eerst op echte hardware

Ik heb dit tegen de simulator getest, niet tegen een echte router. Dit zijn de punten waar de echte
RouterOS zich anders kan gedragen dan de documentatie doet vermoeden. Loop ze één keer na op een
testapparaat of buiten kantooruren:

1. **Wifi-plan blijft "N wijzigingen" tonen na toepassen.** Dan geeft RouterOS een eigenschap anders terug
   dan MikroManager hem zet (bijvoorbeeld een standaardwaarde die wordt weggelaten). De vergelijking staat in
   `backend/app/wifi.py` (`_norm`, `DEFAULTS`); de plan-weergave laat zien om welke eigenschap het gaat.
2. **Back-up.** Eerst wordt `:execute "/export" as-string` geprobeerd, anders export naar bestand en uitlezen
   via `/file`. Op oudere 7.x is `contents` beperkt in grootte; dan meldt MikroManager dat de export te groot is.
3. **Kanaal en zendvermogen per radio** komen uit `/interface/wifi/monitor … once` met meerdere interfaces
   tegelijk. Blijft de kolom leeg, dan accepteert jouw versie dat niet.
4. **Gastisolatie** verplaatst de drop-regel met `/ip/firewall/filter/move` tot direct na de
   established/related-accept in `forward`. Controleer de positie in WinBox; heeft je firewall geen zo'n
   regel, dan staat de drop onderaan.
5. **Radio's van de controller overnemen** gebruikt `/interface/wifi/radio/provision`. Volgens MikroTik kan
   de interface-naam daarbij veranderen, waardoor statische bridge-poorten naar `wifi1`/`wifi2` ongeldig
   worden (de datapath voegt ze dynamisch toe). Doe dit bekabeld.
6. **wifi-qcom-ac AP's** (wifi 5) kunnen geen VLAN uit de datapath krijgen. Zet "Ook wifi 5 access points"
   aan en stel het VLAN op die AP's per interface in met een bridge-PVID (zie de WiFi-handleiding van MikroTik).
7. **Client "bedraad" op een gedeelde poort.** Clients achter een niet-beheerde switch of AP (zoals een
   UniFi-AP) verschijnen op de switchpoort waar die aan hangt, met "gedeeld met N".

Nog niet aanwezig: kanaal per radio vastzetten, firewall- en NAT-beheer, IPv6, WireGuard, meerdere
gebruikers, meldingen. Legacy `wireless` (RouterOS 6 / MIPS-AP's) wordt niet ondersteund.

## Ontwikkelen

```bash
# backend + simulator
cd backend && pip install -r requirements.txt
TIKCONTROL_DEMO=1 TIKCONTROL_DATA=./data uvicorn app.main:app --port 8080 --reload

# frontend met hot reload (proxyt /api naar :8080)
cd frontend && npm install && npm run dev

# end-to-end-test tegen de simulator
cd backend && python tests/test_e2e.py
```

```
backend/app/
  main.py       API-routes en uitlevering van de frontend
  ros.py        REST-client voor RouterOS
  poller.py     achtergrondmetingen, momentopname per apparaat, 24 uur historie
  wifi.py       gewenste staat -> CAPsMAN-plan, AP koppelen
  networks.py   VLAN/DHCP-netwerken met terugdraaien
  clients.py    clients samenvoegen uit leases, registraties en bridge-hosts
  maint.py      updates, firmware, back-ups en diff
  security.py   wachtwoord-hash (scrypt), sessies, versleuteling van routerwachtwoorden (Fernet)
backend/mock/mock_ros.py   RouterOS-simulator (ook los te starten: python -m mock.mock_ros)
frontend/src/   React + TypeScript, geen UI-framework
```

MikroTik en RouterOS zijn handelsmerken van SIA Mikrotīkls. Dit project is daar niet aan verbonden.
