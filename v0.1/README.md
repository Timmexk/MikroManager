# TikControl (proefversie v0.1)

> **Dit is de eerste proefversie, onder de oude werknaam TikControl.**
> Hij is alleen getest tegen de meegeleverde simulator en nooit tegen echte hardware. Het nieuwe ontwerp heet
> MikroManager en staat in [`../ontwerp/`](../ontwerp/). Wat uit deze versie blijft, staat in
> [`../ontwerp/bouwplan.md`](../ontwerp/bouwplan.md). De tekst hieronder is die van de proefversie zelf en
> is niet aangepast aan het nieuwe ontwerp.

Zelfgehoste beheerinterface voor MikroTik-netwerken, in de geest van UniFi Network: één plek voor
apparaten, clients, wifi-netwerken, VLAN's, updates en back-ups. Eén Docker-container, geen cloud, geen account.

- **Apparaten**: status, CPU/geheugen, poortkaart met link, snelheid, PoE en verkeer per poort.
- **Clients**: DHCP-leases, wifi-registraties en switchpoorten samengevoegd per MAC. Naam geven, vast IP, opnieuw verbinden, blokkeren.
- **Wifi**: SSID's één keer instellen, uitrollen naar alle access points via CAPsMAN (`wifi`-menu, RouterOS 7.13+). AP's koppelen met één klik.
- **Netwerken**: VLAN + adres + DHCP-server (+ optioneel gastisolatie) in één stap, met terugdraaien als een stap mislukt.
- **Onderhoud**: RouterOS en RouterBOOT bijwerken (per apparaat of alles op volgorde), nachtelijke config-export met diff.
- **Meerdere sites**, donker/licht thema, werkt op telefoon.

> **Status: v0.1, getest tegen een simulator, nog niet tegen echte hardware.**
> Alle 77 end-to-end-controles slagen tegen de meegeleverde RouterOS-simulator. Die simulator is gebouwd
> op de MikroTik-documentatie, niet op een echte router. Lees [Eerst op echte hardware](#eerst-op-echte-hardware)
> voordat je dit op je productienetwerk loslaat.

## Proberen zonder router

```bash
docker compose build
docker run --rm -p 8080:8080 -e TIKCONTROL_DEMO=1 tikcontrol:0.1.0
```

Open http://localhost:8080, maak een account en klik rond. Demomodus start vijf gesimuleerde apparaten
(hAP ax², CRS310, hEX PoE, twee cAP ax) met clients. Alles wordt bij elke herstart gewist.

## Installeren (Unraid / Docker)

Start vanuit deze map:

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
| `TIKCONTROL_SECURE_COOKIE` | uit | Zet op `1` als je TikControl via HTTPS (reverse proxy) aanbiedt |
| `TIKCONTROL_DEMO` | uit | Simulator in plaats van echte apparaten |

TikControl bewaart beheerdersrechten voor je routers. Zet het niet open aan internet; bereik het via VPN
of een reverse proxy met eigen authenticatie.

## Router voorbereiden

TikControl gebruikt de REST API van RouterOS 7 (`https://router/rest`). Per apparaat:

```routeros
# eigen gebruiker met alleen wat nodig is
/user group add name=tikcontrol policy=read,write,policy,test,sensitive,reboot,rest-api,api
/user add name=tikcontrol group=tikcontrol password="kies-een-lang-wachtwoord" address=192.168.88.50/32

# HTTPS aanzetten met een zelfondertekend certificaat, alleen bereikbaar voor de TikControl-host
/certificate add name=tikcontrol-web common-name=router.lan days-valid=3650 key-usage=tls-server
/certificate sign tikcontrol-web
/ip service set www-ssl certificate=tikcontrol-web address=192.168.88.50/32 disabled=no
```

Vervang `192.168.88.50` door het adres van je Docker-host. `address=` op `www-ssl` beperkt ook WebFig tot
dat adres. Krijg je bij toevoegen "Inloggen geweigerd", voeg dan `web` toe aan de policy van de groep.
HTTP (`www`) werkt ook, maar dan gaat het wachtwoord onversleuteld over het netwerk.

Daarna in TikControl: **Apparaten → Apparaat toevoegen**. De eerste router van een site wordt de wifi-controller.

## Wat TikControl op je router schrijft

Alles wat TikControl aanmaakt is herkenbaar en verder blijft het van je configuratie af:

| Waar | Herkenbaar aan | Wanneer |
|---|---|---|
| `/interface/wifi/security`, `datapath`, `channel`, `configuration` | naam begint met `tc-` | Wifi → wijzigingen toepassen |
| `/interface/wifi/provisioning` | comment `tc:2g:ax`, `tc:5g:ax` (en `:ac`) | idem |
| `/interface/wifi/capsman` | `enabled=yes interfaces=<bridge>` | eerste keer toepassen |
| `/interface/wifi/access-list` | comment `tc:blocked …` | client blokkeren |
| `/interface/vlan`, `/ip/address`, `/ip/pool`, `/ip/dhcp-server`, `/ip/dhcp-server/network`, `/interface/bridge/vlan`, `/interface/list/member` | naam `tc-<naam>` of comment `tc:net:<naam>` | netwerk toevoegen |
| `/ip/firewall/filter` + address-list `tc-private` | comment `tc:net:<naam> isolatie` | netwerk met "afschermen" |
| Op een AP: `/interface/wifi/cap`, datapath `tc-cap`, `configuration.manager=capsman` op de radio's | | AP koppelen |

Wifi-wijzigingen worden nooit direct doorgevoerd: je ziet eerst de lijst met stappen (met de exacte
eigenschappen) en past ze dan toe. Dezelfde stappen twee keer toepassen verandert niets.

Wat TikControl bewust **niet** doet: `vlan-filtering` op een bridge aan- of uitzetten, bestaande
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
   dan TikControl hem zet (bijvoorbeeld een standaardwaarde die wordt weggelaten). De vergelijking staat in
   `backend/app/wifi.py` (`_norm`, `DEFAULTS`); de plan-weergave laat zien om welke eigenschap het gaat.
2. **Back-up.** Eerst wordt `:execute "/export" as-string` geprobeerd, anders export naar bestand en uitlezen
   via `/file`. Op oudere 7.x is `contents` beperkt in grootte; dan meldt TikControl dat de export te groot is.
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
