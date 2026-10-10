# Ontwerpbesluiten

Wat er is besloten en waarom. Elk besluit hoort bij een of meer schermen in [schermen.md](schermen.md).
Wat hier staat is ontwerp. Of RouterOS zich overal gedraagt zoals het ontwerp aanneemt, staat in
[hardware-testlijst.md](hardware-testlijst.md).

## 1. Naam en pictogram

- **Naam: MikroManager.** In het woordmerk is "Mikro" vet en "Manager" licht.
- **Pictogram: een switch met vier poorten, waarvan één blauw.** Het blijft op 16 pixels herkenbaar en sluit
  aan op de poortblokjes die overal in de app terugkomen.
- De SVG staat in [`docs/img/logo.svg`](../docs/img/logo.svg). Neutrale kleur `#c4cbd4` op donker en
  `#333b45` op licht, accent `#3d8bfd` op donker en `#1a66d9` op licht.

Afgevallen: drie rondes met andere namen (onder meer TikControl, Tikro, Mikora, Pontix) en de pictogrammen
met knooppunten, twee apparaten in een rack en een router met wifi.

## 2. Stijl

- **Donker en zakelijk**, met een volwaardig licht thema. Lettertypen IBM Plex Sans en IBM Plex Mono.
- **Blauw is het enige accent** en staat alleen op wat je kunt aanklikken of wat is gewijzigd.
- **Status is een vierkant blokje** in groen, oranje, rood of grijs. Dezelfde blokjes vormen de poortkaart.
- Mono voor alles wat je letterlijk zo in RouterOS terugvindt: IP-adressen, MAC-adressen, interfacenamen, commando's.
- Een veld of cel die is gewijzigd en nog niet is opgeslagen, heeft een blauwe rand.

Kleuren, donker thema: ondergrond `#0e1114`, zijbalk `#0a0c0f`, paneel `#15191e`, tabelkop `#111519`, rand
`#242a32`, tekst `#e6e9ed`, gedempt `#98a2af`, accent `#3d8bfd`, goed `#3fb97a`, let op `#e0a52e`, fout `#f0655d`.
Licht thema: ondergrond `#f3f4f6`, paneel `#ffffff`, rand `#dfe3e8`, tekst `#14181d`, gedempt `#5c6672`, accent `#1a66d9`.

## 3. Navigatie

- **Zijbalk met pictogrammen, in te klappen.** Bovenaan de site-wisselaar, daaronder zoeken (Ctrl K), dan de
  pagina's. Onderaan de bel met meldingen en het account.
- Pagina's: Overzicht, Topologie, Apparaten, Clients, Wifi, Netwerken, Onderhoud, Instellingen.
- **Gasten is een tabblad onder Wifi.** De wijzigingslog is een tabblad onder Onderhoud.
- **Zoeken, meldingen en account staan alleen in de zijbalk**, niet ook nog in de kop van een pagina.
- **Mobiel**: een zwevende balk onderaan met Overzicht, Apparaten, Clients, Wifi en Meer.
- Instellingen scheidt wat bij de site hoort, wat voor de hele app geldt en wat alleen voor jou is.

## 4. Taal

- De interface is er in het **Nederlands en Engels**.
- **Vakjargon, geen letterlijke vertaling.** De app gebruikt de woorden die een netwerkbeheerder zelf gebruikt.

| Zo wel | Zo niet |
|---|---|
| snelle roaming (802.11r), fast transition | snel overstappen |
| client-isolatie, geïsoleerd | afschermen |
| failover, failback | overschakelen, terugschakelen |
| tagged, untagged, PVID | gelabeld, ongelabeld |
| static lease, DHCP-pool, gateway | vast IP, adresbereik |
| rollback, time-out | terugdraaien, wachttijd |
| reboot, updaten, disconnect | herstarten, bijwerken, opnieuw verbinden |
| neighbors, co-channel | buren, zelfde kanaal |
| template, diff, vendor, comment | sjabloon, verschil, fabrikant, opmerking |
| self-signed, fingerprint | zelfondertekend, vingerafdruk |

Bewust Nederlands gebleven: veilige modus, wijzigingslog, poortmatrix, zendvermogen, terugzetten, apparaten,
gastentoegang, kanaalbreedte, kanaalbezetting.

## 5. Rollen en toegang

- **Geen groepen.** Elke gebruiker krijgt per site één rol: Geen, Gebruiker of Netwerkbeheerder.
- **Admin is een aparte schakelaar** en geldt altijd voor alle sites.
- **Gebruiker**: wifi-netwerken aanmaken en beheren, ook de wachtwoorden, en clients beheren. De rest alleen bekijken.
- **Netwerkbeheerder**: alles wat met het beheer van de netwerken van de site te maken heeft, ook updates en
  een back-up maken. Niet de opzet van de site: geen apparaten toevoegen of verwijderen, geen
  site-instellingen, geen templates, geen back-up terugzetten, geen gebruikers.
- **Admin**: alles.
- **Tijdelijke toegang is een einddatum op een account**, bij elke rol. Na die datum kan het account niet meer
  inloggen en worden open sessies afgemeld. Het account blijft uitgeschakeld bewaard.
- Een site waarvoor een gebruiker de rol Geen heeft, is voor die gebruiker onzichtbaar.
- Een nieuwe site geeft niemand toegang tot een admin er een rol voor kiest.

Afgevallen: gebruikersgroepen met een rol per site, een rol met alleen lezen, een aparte rol voor tijdelijke gebruikers.

## 6. Inloggen

- **Wachtwoord en passkeys.** Geen TOTP en geen SSO.
- Ingelogd blijven op een apparaat duurt 30 dagen.
- Na te veel verkeerde pogingen wacht je een minuut. De wijzigingslog toont mislukte pogingen en open sessies,
  en een admin kan een sessie afmelden.
- Een nieuwe gebruiker krijgt een eerste wachtwoord dat één keer zichtbaar is en kiest bij de eerste keer
  inloggen een eigen wachtwoord.
- Passkeys hangen aan de hostnaam waarop de app bereikbaar is. Die hostnaam moet dus vastliggen voordat
  iemand een passkey aanmaakt.

## 7. Opslaan per pagina

Zoals bij UniFi en Omada.

- Wijzigingen op een pagina gaan pas naar de router bij **Opslaan**. Tot dan staat er onderaan een balk met
  het aantal wijzigingen, Verwerpen en Opslaan.
- Raakt de wijziging iets waardoor je buitengesloten kunt raken, dan heet de knop **Bekijken en opslaan**
  en loopt het via de veilige modus.
- Wil je naar een andere pagina, een andere site of uitloggen terwijl er iets klaarstaat, dan vraagt de app:
  Opslaan en doorgaan, Hier blijven, of Verwerpen en doorgaan.
- De router is nooit half aangepast. Er gaat pas iets heen bij opslaan, en dan in vaste stappen.
- Eenmalige acties zoals reboot, PoE power-cycle en disconnect gaan direct, zonder balk.

## 8. Veilige modus

- Geldt **alleen voor wijzigingen die je kunnen buitensluiten**: VLAN's, poorten, bridge, firewall, WAN,
  adressen en een back-up terugzetten. Voor die onderdelen is hij niet uit te zetten.
- Na toepassen loopt een time-out, standaard 2 minuten en per site in te stellen op 1, 2 of 5 minuten.
  Bevestig je dat alles werkt, dan blijft de wijziging staan.
- **Bevestig je niet, dan doet het apparaat zelf een rollback**, ook als de verbinding met de app weg is.
- Een wifi-wachtwoord wijzigen of een SSID op een band uitzetten raakt de management-toegang niet en gaat
  zonder veilige modus.

RouterOS kent safe mode alleen binnen een terminal- of WinBox-sessie, niet via de REST API. De app moet dit
dus zelf regelen: vóór het toepassen zet hij een scheduler met een rollback-script op het apparaat, en na
bevestigen haalt hij die weer weg. Dit mechanisme is het grootste open punt en staat bovenaan de testlijst.

## 9. Poortmatrix

- Rijen zijn de netwerken, kolommen de poorten. **Klik op een cel** om te wisselen tussen leeg, tagged en untagged.
- Een poort heeft één PVID. Zet je een poort untagged in een netwerk, dan vervalt untagged in het vorige.
- **Geen poort staat op slot, ook niet voor een admin.** De uplink zit niet bij iedereen op poort 1.
- De app zoekt op via welke poort zijn eigen verkeer het apparaat bereikt en zet daar `mgmt` bij. Dat is
  informatie, geen blokkade. Wijzig je die poort, dan waarschuwt de pre-check en vangt de veilige modus een
  vergissing op.
- Onder de matrix staan de wijzigingen in gewone taal ("Poort 8: PVID van LAN naar Camera's") en een pre-check.

## 10. Wifi

- Wifi loopt via CAPsMAN in het `wifi`-menu (wifi-qcom, RouterOS 7.13 en nieuwer).
- **Elke instelling geldt voor één SSID.** Snelle roaming (802.11r), steering (802.11k/v), client-isolatie en
  SSID verbergen stel je per wifi-netwerk in. Er is geen knop die iets op alle netwerken tegelijk zet.
- Dat volgt uit de opbouw op de router: elk SSID heeft een eigen security-profiel, datapath en configuratie.
  `ft` staat in het security-profiel, `client-isolation` in de datapath, `hide-ssid` in de configuratie.
- Per SSID kies je op welke access points en op welke band het uitzendt.
- Kanalen en radio's: kanaal, kanaalbreedte en zendvermogen per radio, met de naburige netwerken per kanaal
  en een melding bij DFS-kanalen.
- Inzicht: co-channel met naburige netwerken, sticky clients, roaming van vandaag.
- Gasten: QR-code, wachtwoord vernieuwen, vouchers met geldigheid en rate limit.

## 11. Onderhoud

- **Updates op volgorde**: eerst de access points, dan de switches, de router als laatste. De volgende start
  pas als het vorige apparaat weer online is. Standaard eerst een back-up, RouterBOOT mee, en stoppen als een
  apparaat niet terugkomt.
- **Back-ups elke nacht**, met een nieuwe versie alleen als er iets is veranderd. Per versie een diff.
  Terugzetten gaat via de veilige modus en mag alleen een admin.
- **Wijzigingslog**: wie, wanneer, op welke site, wat, en de afloop (toegepast, rollback). Wijzigingen buiten
  de app, via WinBox of de terminal, vindt de app in de nachtelijke back-up en zet ze er zonder naam bij.
- Wachtwoorden staan nooit leesbaar in de log.

## 12. Meldingen

- **Echte pushmeldingen vanuit de app zelf** (Web Push), zonder account bij een derde partij. De melding gaat
  versleuteld via de pushdienst van de browser naar het apparaat.
- Per gebeurtenis aan of uit: WAN-failover, alle WAN-verbindingen down, apparaat offline, apparaat weer online,
  onbekende client, rollback door veilige modus, wijziging buiten de app, back-up mislukt, update beschikbaar.
- **Stille uren**: alleen gebeurtenissen die zijn gemarkeerd als "komt door" geven dan een melding.
- De bel in de zijbalk opent het meldingencentrum met dezelfde gebeurtenissen, per site of voor alle sites.
- Push vraagt een geldige hostnaam met https. Op iPhone en iPad moet de app eerst op het beginscherm staan.

## 13. Meerdere sites en externe sites

- Elke site heeft eigen apparaten, netwerken, instellingen en rollen.
- **Eerste keer instellen** in vijf stappen. Er verandert niets op de router tot je daar zelf voor kiest.
- **Apparaten ontdekken** via neighbor discovery (MNDP) en een scan van het subnet.
- **Templates**: een vaste set netwerken en instellingen voor een nieuwe locatie. Wachtwoorden en subnetten
  vul je per site in bij het toepassen, en je ziet eerst alle stappen.

### De management-tunnel

Voor een site op een andere locatie zet de app een WireGuard-tunnel op. De externe router belt naar de
thuislocatie, dus het werkt met een publiek IP en achter CGNAT.

Wat vastligt:

- **Geen routes naar elkaars LAN.** Allowed-address is aan beide kanten alleen het tunneladres, een /32.
- **Geen internet door de tunnel.** Er komt geen default route bij; elke site houdt zijn eigen WAN.
- **Alleen de REST API.** De firewall op de externe router laat op de tunnel alleen de app toe op tcp 443.
- **Sites zien elkaar niet.** Verkeer van de ene tunnel naar de andere wordt op de thuislocatie gedropt.
- Switches en access points op de externe site bereikt de app via een port forward op het tunneladres. Daardoor
  mogen sites dezelfde subnetten gebruiken.
- De kant van de thuislocatie zet de app zelf. Voor de externe router geeft de app een script dat je één keer
  in de terminal plakt.

Valt de thuislocatie terug op een verbinding achter CGNAT, dan is het endpoint onbereikbaar en heeft de app
tijdelijk geen controle over de externe sites. De tunnel komt terug bij failback. Dat is geaccepteerd; een
melding is genoeg.

Wie al een eigen VPN naar een site heeft, kiest "Bestaande verbinding" en vult alleen het adres in.

### De app zelf van buiten bereiken

Voor de webinterface kan een reverse proxy met een geldig certificaat ervoor, bijvoorbeeld Pangolin op een
VPS. Dat geeft de vaste hostnaam die push en passkeys nodig hebben. Pangolin is niet bedoeld als route naar
de REST API van de routers: een TCP-resource heeft daar geen eigen authenticatie en zet een poort open op de VPS.

## 14. Wat de app op een router zet

- Elk object dat de app aanmaakt heeft een naam met `mm-` of een comment met `mm:`.
- Objecten zonder dat kenmerk leest de app, maar wijzigt hij niet.
- Dezelfde stappen twee keer toepassen verandert niets.
- De app zet `vlan-filtering` op een bridge niet aan of uit, wijzigt geen bestaande firewallregels en past de
  WAN-configuratie niet aan.
- Per apparaat een eigen gebruiker met een eigen groep, met alleen de policy's die nodig zijn.

Voorbeeld voor één SSID:

```
security       mm-thuis-iot       wpa2-psk, passphrase, ft
datapath       mm-thuis-iot       bridge=bridge vlan-id=30
configuration  mm-thuis-iot-2g    ssid, country, security, datapath, channel
configuration  mm-thuis-iot-5g    ssid, country, security, datapath, channel
```

## 15. Voorbeelddata in de schermen

Alle schermen gebruiken dezelfde verzonnen site, zodat cijfers op elk scherm kloppen met de andere.

- Site Thuis: hAP-ax2-meterkast (router en CAPsMAN), CRS310-kantoor, hEX-PoE-zolder, cAP-ax-woonkamer, cAP-ax-overloop.
- WAN: Kabel op ether1 (actief) en 4G back-up op lte1 (stand-by, achter CGNAT).
- Netwerken: LAN, IoT (VLAN 30), Gasten (VLAN 40), Camera's (VLAN 50).
- 19 clients: 13 op wifi en 6 bedraad. SSID's Thuis, Thuis-IoT en Thuis-Gast.
- Publieke adressen komen uit het documentatiebereik 203.0.113.0/24.
