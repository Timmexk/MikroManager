# Bouwplan

De volgorde waarin MikroManager gebouwd wordt, en wat er per stap af moet zijn. Er wordt nog niet gebouwd:
eerst moet [hardware-testlijst.md](hardware-testlijst.md) zijn afgewerkt en moeten de open besluiten
hieronder zijn genomen.

## Waar we staan

| | Stand |
|---|---|
| Proefversie v0.1 (werknaam TikControl) | Werkt tegen een simulator, 77 end-to-end-controles slagen. Nooit op echte hardware gedraaid. |
| Ontwerp | Klaar: 40 schermen voor desktop en mobiel, zie [schermen.md](schermen.md). |
| Ontwerpbesluiten | Vastgelegd in [ontwerpbesluiten.md](ontwerpbesluiten.md). |
| Hardwareproef | Nog te doen. |
| Bouw | Nog niet gestart. |

## Wat uit v0.1 bruikbaar blijft

De proefversie in [`../v0.1/`](../v0.1/) is één container met FastAPI, SQLite en een React-frontend. Die opzet blijft.

| Onderdeel | Bestand | Oordeel |
|---|---|---|
| REST-client voor RouterOS | `backend/app/ros.py` | Houden |
| Poller met 24 uur historie | `backend/app/poller.py` | Houden, uitbreiden met WAN-status en optellen van verbruik |
| Wifi: gewenste staat naar CAPsMAN-plan | `backend/app/wifi.py` | Houden, ombouwen naar instellingen per SSID en kanaal per radio |
| Netwerken met terugdraaien | `backend/app/networks.py` | Houden, aansluiten op de veilige modus |
| Clients samenvoegen | `backend/app/clients.py` | Houden |
| Updates, back-ups en diff | `backend/app/maint.py` | Houden, aanvullen met de wijzigingslog |
| Wachtwoord-hash, sessies, versleuteling | `backend/app/security.py` | Houden, uitbreiden met gebruikers, rollen en passkeys |
| RouterOS-simulator | `backend/mock/mock_ros.py` | Houden als testbasis, bijwerken met wat de hardwareproef oplevert |
| Frontend | `frontend/src/` | Opnieuw opzetten in de nieuwe stijl; de API-laag kan mee |

Wat in elk geval verandert: de naam, het kenmerk op de router (`tc-` wordt `mm-`), en van één beheerder
naar gebruikers met een rol per site.

## Open besluiten

Deze vragen zijn tijdens het ontwerp naar boven gekomen en nog niet beantwoord. De eerste twee hangen af van
de hardwareproef.

1. **Hoe werkt de rollback van de veilige modus?** Omgekeerde commando's die de app genereert, of een
   back-up laden. Zie deel A van de testlijst.
2. **Wat doet de poortmatrix op een bridge waar `vlan-filtering` uit staat?** De app zet het niet aan. De
   keuze is: de matrix daar alleen-lezen tonen met uitleg, of het aanzetten als aparte, bewuste handeling
   van een admin toestaan.
3. **Firewall.** In de rollen en de veilige modus komt firewall voor, maar er is geen eigen scherm. Blijft het
   bij isolatie per netwerk, of komt er een scherm bij?
4. **Vouchers of alleen een wachtwoord met QR-code** voor gasten. Vouchers vragen de hotspot van RouterOS.
5. **Hostnaam van de app.** Push en passkeys vragen een vaste hostnaam met een geldig certificaat. Via een
   reverse proxy zoals Pangolin, of anders? Daarbij hoort een veld "externe URL" in Instellingen.
6. **Licentie**, als de code later openbaar wordt.

Niet nu aan de orde: waar het endpoint van de management-tunnel komt te liggen (thuis of een hub op een VPS).
Dat hoort bij externe sites en staat onder [Later](#later).

## Volgorde

Eerst alles wat alleen leest, dan schrijven waar weinig mis kan gaan, dan schrijven waar je buitengesloten
kunt raken. Elke fase eindigt met een versie die op het eigen netwerk draait.

### Fase 0. Hardwareproef

Geen code voor de app, wel losse testscripts.

- De testlijst afwerken op een router, een switch en een access point.
- De simulator bijwerken met elk verschil dat gevonden is.
- De open besluiten 1 en 2 nemen.

**Klaar als** elk blokkerend punt een antwoord heeft en dat antwoord in de ontwerpbesluiten staat.

### Fase 1. Fundament

- Hernoemen naar MikroManager, kenmerk `mm-`.
- Gebruikers, rol per site, admin-schakelaar, tijdelijke toegang met einddatum.
- Inloggen met wachtwoord, sessies, open sessies afmelden. Passkeys zodra de hostnaam vastligt.
- De schil in de nieuwe stijl: zijbalk, site-wisselaar, donker en licht, Nederlands en Engels, mobiele balk.
- Opslaan per pagina: de balk, de vraag bij het verlaten, en de vaste vorm van een plan (stappen vooraf tonen).
- Wijzigingslog als basisvoorziening: elke schrijfactie komt erin.
- Eerste keer instellen, tot en met "router toevoegen" en "configuratie inlezen".

**Klaar als** je kunt inloggen, een site en een router kunt toevoegen en elke rol ziet wat hij mag zien.

### Fase 2. Lezen

- Overzicht, Apparaten met poortkaart, Clients met detail en historie, Topologie.
- Netwerken: WAN-verbindingen met failover-geschiedenis, lokale netwerken, poortmatrix alleen-lezen.
- Wifi-overzicht en Kanalen en radio's, alleen-lezen.
- Snelzoeken.

**Klaar als** alle cijfers op deze schermen kloppen met WinBox op het eigen netwerk, een week lang.

### Fase 3. Wifi en clients schrijven

Weinig risico op buitensluiten, en het is wat de rol Gebruiker mag.

- SSID aanmaken en wijzigen, per access point en per band, met alle instellingen per SSID.
- Kanaal, kanaalbreedte en zendvermogen per radio.
- Clients: naam, static lease, disconnect, blokkeren.
- Gasten: wachtwoord en QR-code. Vouchers afhankelijk van besluit 4.
- Access point toevoegen aan CAPsMAN.

**Klaar als** een wijziging twee keer toepassen niets verandert en het plan na toepassen leeg is.

### Fase 4. Veilige modus en netwerken schrijven

- De veilige modus volgens besluit 1, eerst los getest met een wijziging die bewust buitensluit.
- Netwerk toevoegen en verwijderen: VLAN, adres, DHCP, isolatie.
- Poortmatrix bewerken, met herkenning van de management-poort en de pre-check.
- Eenmalige acties op een apparaat: reboot, PoE power-cycle, poort uitschakelen.

**Klaar als** een bewust foute wijziging op elk type apparaat vanzelf wordt teruggedraaid.

### Fase 5. Onderhoud

- Nachtelijke back-up met versies en diff, downloaden, terugzetten via de veilige modus.
- Updates op volgorde, met RouterBOOT, nu of gepland.
- Wijzigingen buiten de app herkennen.
- Wie deed wat, met open sessies.

**Klaar als** een update van alle apparaten zonder ingrijpen doorloopt en stopt als een apparaat niet terugkomt.

### Fase 6. Meldingen

- Web Push met instellingen per gebeurtenis en stille uren.
- Meldingencentrum achter de bel.
- De app als app op het beginscherm van een telefoon.

**Klaar als** een failover binnen een minuut op de telefoon staat.

### Fase 7. Meerdere sites

Alleen sites die de app zelf kan bereiken, rechtstreeks of via een verbinding die er al is.

- Een tweede site toevoegen met eigen apparaten, instellingen en rollen.
- Apparaten ontdekken.
- Templates maken en toepassen.

**Klaar als** twee sites naast elkaar te beheren zijn en een gebruiker alleen de sites ziet waar hij een rol heeft.

### Fase 8. Afronden

- Mobiele schermen nalopen op een echte telefoon.
- Engelse vertaling compleet.
- Installatie-instructie voor Unraid en Docker.
- Besluit over openbaar maken en de licentie.

## Later

Uitgewerkt in het ontwerp, maar bewust niet in de eerste versie. De prioriteit is het eigen netwerk op
locatie beheren.

- **Externe sites via een management-tunnel.** Het scherm en de regels staan in
  [ontwerpbesluiten.md](ontwerpbesluiten.md#13-meerdere-sites-en-later-externe-sites). Vooraf te kiezen: het
  endpoint thuis, of een WireGuard-hub op een VPS zodat op geen enkele locatie een poort open hoeft.
- Deel H van de testlijst hoort hierbij en hoeft voor de eerste versie niet te worden afgewerkt.

## Buiten het plan

WAN, NAT en routing beheren, IPv6, legacy `wireless` (RouterOS 6), SSO en TOTP.
