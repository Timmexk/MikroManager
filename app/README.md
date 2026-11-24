# MikroManager (proefversie v0.8)

Zelfgehoste beheerinterface voor MikroTik-netwerken, in de geest van UniFi Network: één plek voor
apparaten, clients, wifi-netwerken, VLAN's, updates en back-ups. Draait direct op Linux (systemd) of in Docker, geen cloud, geen account.

- **Apparaten**: status, CPU/geheugen, poortkaart met link, snelheid, PoE en verkeer per poort.
- **Clients**: DHCP-leases, wifi-registraties en switchpoorten samengevoegd per MAC. Naam geven, vast IP, opnieuw verbinden, blokkeren.
- **Wifi**: SSID's één keer instellen, uitrollen naar alle access points via CAPsMAN (`wifi`-menu, RouterOS 7.13+). AP's koppelen met één klik.
- **Netwerken**: VLAN + adres + DHCP-server (+ optioneel gastisolatie) in één stap, met terugdraaien als een stap mislukt.
- **Onderhoud**: RouterOS en RouterBOOT bijwerken (per apparaat of alles op volgorde), nachtelijke config-export met diff.
- **Meerdere sites**, donker/licht thema, werkt op telefoon.

> **Status: v0.8, getest tegen een simulator, nog niet tegen echte hardware.**
> Alle 282 end-to-end-controles slagen tegen de meegeleverde RouterOS-simulator. Die simulator is gebouwd
> op de MikroTik-documentatie, niet op een echte router. Lees [Eerst op echte hardware](#eerst-op-echte-hardware)
> voordat je dit op je productienetwerk loslaat.

Wat er per versie veranderde staat in [CHANGELOG.md](CHANGELOG.md). Nieuw in v0.8: één radiopaneel per access
point, kiezen op welke access points een netwerk uitzendt in het netwerkvenster zelf, en de controller-instellingen
onder Instellingen.

## Proberen zonder router

```bash
docker run --rm -p 8080:8080 -e MIKROMANAGER_DEMO=1 ghcr.io/timmexk/mikromanager:edge
```

Open http://localhost:8080, maak een account en klik rond. Demomodus start zes gesimuleerde apparaten
(hAP ax², CRS310, hEX PoE, twee cAP ax en een zelfstandige wAP ax) met clients. Alles wordt bij elke herstart gewist.

## Installeren met Docker (Unraid)

Het image wordt door GitHub Actions gebouwd en staat op `ghcr.io/timmexk/mikromanager` (amd64 en arm64):

| Tag | Wat |
|---|---|
| `edge` | De laatste stand van `main` |
| `sha-<commit>` | Een vaste build |
| `0.8.0`, `0.8`, `latest` | Uitgebrachte versies (zodra er een tag `v0.8.0` is) |

**Unraid.** Ga naar *Docker → Add Container*, kies bij *Template* niets en vul bij *Template URL* (onderaan,
of via *Docker → Template repositories*) dit adres in:

```
https://raw.githubusercontent.com/Timmexk/MikroManager/main/unraid/mikromanager.xml
```

Of vanaf de Unraid-terminal, zonder template:

```bash
docker run -d --name mikromanager --restart unless-stopped \
  -p 8090:8080 -v /mnt/user/appdata/mikromanager:/data \
  -e TZ=Europe/Amsterdam -e MIKROMANAGER_DEMO=1 \
  ghcr.io/timmexk/mikromanager:edge
```

Het template start in **demomodus** en op poort 8090 (8080 is op Unraid vaak bezet). Zet `MIKROMANAGER_DEMO` op `0`
als je je echte netwerk wilt beheren. Bijwerken: in Unraid *Check for updates*, of `docker pull` en de container
opnieuw maken.

**Docker Compose.** `docker compose up -d` in deze map gebruikt het image van ghcr.io; zelf bouwen kan met
`build: .` in `docker-compose.yml`. De data staat in `/mnt/user/appdata/mikromanager`: `mikromanager.db`,
`secret.key` en `backups/`. **Bewaar `secret.key` samen met de database**: zonder die sleutel zijn de
opgeslagen routerwachtwoorden niet meer te lezen. Kwam je van v0.7 met `/mnt/user/appdata/tikcontrol`, wijs
het volume dan naar die map of kopieer hem.

| Variabele | Standaard | Betekenis |
|---|---|---|
| `TZ` | UTC | Tijdzone voor het back-upschema en de update-wachtrij |
| `MIKROMANAGER_POLL` | `15` | Seconden tussen metingen |
| `MIKROMANAGER_SECURE_COOKIE` | uit | Zet op `1` als je MikroManager via HTTPS (reverse proxy) aanbiedt |
| `MIKROMANAGER_DEMO` | uit | Simulator in plaats van echte apparaten |

MikroManager bewaart beheerdersrechten voor je routers. Zet het niet open aan internet; bereik het via VPN
of een reverse proxy met eigen authenticatie.

## Installeren op Linux (aanbevolen)

Werkt op elke distro met systemd en Python 3.10 of nieuwer: Debian 12+, Ubuntu 22.04+, Fedora, Arch/CachyOS,
openSUSE. Vooraf nodig: Python met venv (Debian/Ubuntu: `sudo apt install python3-venv`) en `curl` of `wget`.
De frontend wordt kant-en-klaar gedownload (gebouwd door GitHub Actions), dus `npm` is op de server niet nodig.
Zelf bouwen kan met `sudo MM_FRONTEND=build bash linux/install.sh` (vraagt `nodejs` en `npm`).

```bash
git clone https://github.com/Timmexk/MikroManager.git
cd MikroManager/app
sudo bash linux/install.sh
```

Het script maakt een systeemgebruiker `mikromanager`, zet het programma in `/opt/mikromanager` en start de
systemd-service `mikromanager`. Bijwerken: `git pull` en het script opnieuw draaien. Je data en instellingen
blijven daarbij staan.

| Pad | Inhoud |
|---|---|
| `/etc/mikromanager/mikromanager.env` | Instellingen: poort, poll-interval, HTTPS-cookie, demomodus |
| `/var/lib/mikromanager/` | `mikromanager.db`, `secret.key` en `backups/`. **Bewaar `secret.key` samen met de database.** |
| `/opt/mikromanager/` | Programma en Python-omgeving, wordt bij elke update vervangen |

```bash
sudo systemctl restart mikromanager      # na het wijzigen van de instellingen
journalctl -u mikromanager -f            # logs
sudo bash linux/install.sh --uninstall      # verwijderen, data blijft staan
sudo bash linux/install.sh --purge          # alles verwijderen, ook de data
```

De service is afgeschermd: hij draait niet als root, mag alleen in `/var/lib/mikromanager` schrijven en ziet
de home-mappen niet. Het back-upschema gebruikt de tijdzone van het systeem (`timedatectl`).

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
| `/interface/wifi/security`, `datapath`, `channel`, `configuration` | naam begint met `mm-` | Wifi → wijzigingen toepassen |
| `/interface/wifi/provisioning` | comment `mm:2g:ax`, `mm:5g:ax` (en `:ac`) | idem |
| `/interface/wifi/capsman` | `enabled=yes interfaces=<bridge>` | eerste keer toepassen |
| `/interface/wifi/access-list` | comment `mm:blocked …` | client blokkeren (wifi) |
| `/ip/firewall/filter`, `/ipv6/firewall/filter` | drop op `src-mac-address`, comment `mm:blocked …`, bovenaan forward | client blokkeren |
| `/interface/wifi/configuration` en `channel` per radio | naam eindigt op `-r<mac>` | kanaal, breedte of zendvermogen per radio |
| `/interface/bridge/port`, `/interface/bridge/vlan`, `/ip/dhcp-server`, `configuration.manager` op de eigen radio's | alleen na een klik op Repareren in de wifi-controle | wifi-controle |
| `/interface/wifi` inline-eigenschappen en virtuele interfaces (comment `MikroManager`, of `mm:own:` na zelfstandig maken) | alleen op zelfstandige radio's | Wifi op dit apparaat |
| `/interface/wifi/provisioning` met `radio-mac` en `action=none` | comment `mm:radio:<mac>` | radio van een CAP uit of eigen SSID-keuze |
| `/interface/vlan`, `/ip/address`, `/ip/pool`, `/ip/dhcp-server`, `/ip/dhcp-server/network`, `/interface/bridge/vlan`, `/interface/list/member` | naam `mm-<naam>` of comment `mm:net:<naam>` | netwerk toevoegen |
| `/ip/firewall/filter` + address-list `mm-private` | comment `mm:net:<naam> isolatie` | netwerk met "afschermen" |
| Op een AP: `/interface/wifi/cap`, datapath `mm-cap`, `configuration.manager=capsman` op de radio's | | AP koppelen |
| Op de router: `/interface/wifi` wifi1/wifi2 `configuration=mm-…` en virtuele interfaces met comment `mm:local:…` | comment | Radio's overnemen |
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
firewallregels wijzigen, objecten zonder `mm-`-kenmerk aanpassen.

### Zo is wifi opgebouwd

```
WLAN "Thuis-IoT" (VLAN 30, 2,4 + 5 GHz)
  security       mm-thuis-iot        wpa2-psk, passphrase, ft
  datapath       mm-thuis-iot        bridge=bridge vlan-id=30
  configuration  mm-thuis-iot-2g     ssid, country, security, datapath, channel=mm-ch-2g
  configuration  mm-thuis-iot-5g     ... channel=mm-ch-5g
provisioning  supported-bands=2ghz-ax  master=mm-thuis-2g  slaves=mm-thuis-iot-2g
provisioning  supported-bands=5ghz-ax  master=mm-thuis-5g  slaves=mm-thuis-iot-5g,mm-thuis-gast-5g
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
MIKROMANAGER_DEMO=1 MIKROMANAGER_DATA=./data uvicorn app.main:app --port 8080 --reload

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
