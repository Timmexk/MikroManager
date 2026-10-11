<p>
  <img src="docs/img/logo.svg" alt="" width="56" height="56">
</p>

# MikroManager

Zelf gehoste beheeromgeving voor MikroTik-netwerken. Eén webapp voor routers, switches en access points,
opgezet zoals UniFi Network en Omada, met de vaktermen die je uit RouterOS kent.

> **Stand van zaken: het ontwerp is klaar, de bouw is nog niet gestart.**
> De eerste versie richt zich op het beheren van je eigen MikroTik-netwerk op locatie. Externe sites
> koppelen is uitgewerkt in het ontwerp, maar blijft een functie voor later.
> Deze repository bevat het ontwerp, de ontwerpbesluiten, het bouwplan en een eerste proefversie (v0.1).
> Die proefversie draait alleen tegen een simulator en is nog nooit op echte hardware getest.

![Overzicht van de site Thuis](docs/schermen/overzicht.webp)

Alle schermen staan in [ontwerp/schermen.md](ontwerp/schermen.md). De schermen tonen voorbeelddata: de
apparaten, clients en adressen bestaan niet.

## Wat het wordt

| Onderdeel | Wat je ermee doet |
|---|---|
| **Overzicht** | WAN-verbindingen met failover, apparaten, clients en wat aandacht vraagt |
| **Topologie** | Backbone op basis van neighbors (LLDP en MNDP) en bridge-hosts |
| **Apparaten** | Poortkaart met link, PoE en VLAN's, reboot, PoE power-cycle, configuratie-versies |
| **Clients** | Naam geven, static lease, disconnect, blokkeren, signaal en historie per client |
| **Wifi** | SSID's via CAPsMAN, kanalen en radio's, inzicht in co-channel en roaming, gasten met vouchers |
| **Netwerken** | VLAN's met DHCP, WAN-overzicht, poortmatrix die je per cel bewerkt |
| **Onderhoud** | RouterOS en RouterBOOT updaten op volgorde, nachtelijke back-up met diff, wijzigingslog |
| **Gebruikers** | Per gebruiker een rol per site, tijdelijke toegang met einddatum, passkeys |
| **Sites** | Meerdere sites die de app zelf kan bereiken, apparaten ontdekken, templates voor een nieuwe site |
| **Externe sites** (later) | Een locatie elders koppelen via een management-tunnel |
| **Meldingen** | Pushmeldingen rechtstreeks vanuit de app, per gebeurtenis in te stellen |

De interface is er in het Nederlands en Engels, in een donker en een licht thema, en werkt op een telefoon
met een eigen navigatiebalk onderaan.

## Vaste uitgangspunten

Deze regels gelden voor elk scherm en elke functie. Ze staan uitgebreider in
[ontwerp/ontwerpbesluiten.md](ontwerp/ontwerpbesluiten.md).

1. **De app raakt alleen aan wat hij zelf heeft gemaakt.** Alles wat MikroManager op een router zet, heeft een
   naam die begint met `mm-` of een comment die begint met `mm:`. Objecten zonder dat kenmerk worden gelezen,
   nooit gewijzigd.
2. **Eerst zien, dan toepassen.** Bij elke wijziging zie je de stappen die op de router worden uitgevoerd
   voordat er iets gebeurt.
3. **Opslaan per pagina.** Je wijzigt op een pagina, slaat op en gaat dan pas verder. Wil je weg terwijl er
   nog iets klaarstaat, dan vraagt de app wat ermee moet gebeuren.
4. **Veilige modus bij alles wat je kan buitensluiten.** VLAN's, poorten, bridge, firewall, WAN, adressen en
   een back-up terugzetten: bevestig je niet binnen de time-out, dan volgt een rollback.
5. **Geen poort op slot.** Ook de poort waarover de app het apparaat bereikt mag je wijzigen. De app
   herkent die poort, waarschuwt, en de veilige modus vangt een vergissing op.
6. **WAN is alleen kijken.** De app toont failover en verbruik, maar past de WAN-configuratie niet aan.
7. **`vlan-filtering` blijft zoals het staat.** De app zet het op geen enkele bridge aan of uit.
8. **Externe sites komen later, en dan alleen voor management.** Een tunnel naar een andere locatie geeft
   geen route naar je LAN en er loopt geen internetverkeer doorheen.

## Rollen

Elke gebruiker krijgt per site één rol. Admin is geen rol per site: een admin mag alles op alle sites.

| | Gebruiker | Netwerkbeheerder | Admin |
|---|---|---|---|
| Wifi-netwerken aanmaken en wijzigen, ook de wachtwoorden | ja | ja | ja |
| Clients een naam geven, blokkeren of verbreken | ja | ja | ja |
| Kanalen en radio's, VLAN's, DHCP, adressen, poortmatrix, PoE, firewall | bekijken | ja | ja |
| Gastentoegang en vouchers | bekijken | ja | ja |
| Updates, reboot en back-up maken | bekijken | ja | ja |
| Apparaten toevoegen of verwijderen, site-instellingen | bekijken | bekijken | ja |
| Templates toepassen en een back-up terugzetten | nee | nee | ja |
| Sites en gebruikers beheren | nee | nee | ja |

Tijdelijke toegang is geen aparte rol. Het is een einddatum op een account, bij elke rol.

## Hoe de app met een router praat

MikroManager gebruikt de REST API van RouterOS 7 over https (service `www-ssl`) en pollt elk apparaat, standaard
elke 15 seconden. Er draait niets op de router zelf en er is geen cloud of extern account nodig. De app krijgt
een eigen gebruiker op elk apparaat, zodat je in de log van de router ziet wat de app deed en wat je zelf deed.

De eerste versie beheert de apparaten die de app rechtstreeks kan bereiken: het netwerk waar hij zelf in staat.
Een site op een andere locatie koppelen is een functie voor later. Het ontwerp daarvoor is een WireGuard-tunnel
die de externe router zelf opzet en die alleen de REST API doorlaat.

## Wat het niet is

- Geen vervanging van WinBox. Wat de app niet beheert, laat hij met rust en blijf je in WinBox doen.
- Geen cloudcontroller. De app draait in één container op je eigen server.
- Geen product van MikroTik en er niet aan verbonden.

## In deze repository

| Map | Inhoud |
|---|---|
| [`ontwerp/`](ontwerp/) | Ontwerpbesluiten, bouwplan, testlijst voor echte hardware, alle schermen en de bronbestanden van het ontwerp |
| [`docs/`](docs/) | De projectwebsite voor GitHub Pages, met de schermafbeeldingen |
| [`v0.1/`](v0.1/) | De eerste proefversie onder de oude werknaam TikControl: FastAPI, React en een RouterOS-simulator |

## Hoe verder

Er wordt pas gebouwd nadat de punten uit [ontwerp/hardware-testlijst.md](ontwerp/hardware-testlijst.md) op
echte apparaten zijn nagelopen. De volgorde daarna staat in [ontwerp/bouwplan.md](ontwerp/bouwplan.md).

## Licentie en merken

Er is nog geen licentie gekozen. Tot die er is, zijn alle rechten voorbehouden.

MikroTik en RouterOS zijn handelsmerken van SIA Mikrotīkls. UniFi is een handelsmerk van Ubiquiti en Omada
van TP-Link. Dit project is aan geen van deze bedrijven verbonden. De lettertypen IBM Plex Sans en IBM Plex
Mono in `docs/fonts/` vallen onder de SIL Open Font License 1.1.
