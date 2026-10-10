# Testlijst voor echte hardware

Het ontwerp en de proefversie zijn gemaakt op basis van de MikroTik-documentatie en een simulator. Geen van
de punten hieronder is op een echte router gecontroleerd. Deze lijst moet zijn afgewerkt voordat de bouw
begint, omdat een aantal antwoorden het ontwerp kan veranderen.

**Werkwijze**

- Test op een apparaat dat even weg mag vallen, of buiten de uren dat het netwerk nodig is.
- Maak vooraf een back-up (`/system/backup/save`) en een export, en houd een tweede weg naar het apparaat
  open, bijvoorbeeld WinBox via MAC-adres.
- Noteer per punt het apparaat en de RouterOS-versie. Gedrag verschilt per versie en per chipset.

| Apparaat | Model | RouterOS | RouterBOOT | Getest op |
|---|---|---|---|---|
| | | | | |

De punten zijn gemerkt met wat het antwoord raakt: **[blokkerend]** betekent dat het ontwerp zonder dit
antwoord niet gebouwd kan worden, **[gedrag]** dat alleen de uitwerking verandert.

---

## A. Veilige modus

De REST API heeft geen safe mode. Het ontwerp gaat ervan uit dat de app vóór een riskante wijziging een
scheduler met een rollback-script op het apparaat zet en die na bevestigen weer weghaalt.

- [ ] **[blokkerend] Rollback zonder verbinding.** Zet een scheduler `mm-rollback` met `interval=2m` en een
  script dat een bekende wijziging ongedaan maakt en zichzelf verwijdert. Pas een wijziging toe die de
  REST-verbinding verbreekt (bijvoorbeeld de PVID van de management-poort). Komt het apparaat na 2 minuten
  vanzelf terug?
- [ ] **[blokkerend] Wat is het rollback-script?** Vergelijk drie vormen: (1) de omgekeerde commando's die de
  app zelf genereert, (2) `/system/backup/load` van een back-up van vlak ervoor, (3) `/import` van een export.
  Let op: een back-up laden herstart het apparaat en zet ook terug wat iemand anders in die 2 minuten deed.
- [ ] **[gedrag] Reboot binnen de time-out.** Herstart het apparaat terwijl de scheduler loopt. Loopt de
  scheduler daarna nog, of is een tweede scheduler met `start-time=startup` nodig?
- [ ] **[gedrag] Klok.** Werkt het ook op een apparaat waarvan de klok niet goed staat? `interval` zou
  onafhankelijk van de klok moeten zijn.
- [ ] **[gedrag] Bevestigen.** Het weghalen van de scheduler is zelf een REST-aanroep. Wat ziet de gebruiker
  als die aanroep net niet aankomt?

## B. Verbinding en rechten

- [ ] **[blokkerend] Kleinste policy.** Werkt alles met een groep met
  `policy=read,write,policy,test,sensitive,reboot,rest-api`? Haal er één voor één een policy af en noteer wat
  dan stuk gaat. Is `web` nodig om via `www-ssl` in te loggen?
- [ ] **[gedrag] Self-signed certificaat.** De app onthoudt de fingerprint van het certificaat. Wat gebeurt er
  na een reset of als RouterOS het certificaat vernieuwt?
- [ ] **[gedrag] Time-out van 60 seconden.** Een REST-aanroep die langer duurt, breekt af. Geldt dat voor de
  omgevingsscan, `monitor … once` op meerdere interfaces en een grote export?
- [ ] **[gedrag] Belasting.** Wat doet pollen om de 15 seconden met de CPU van een hEX of een cAP? Welke
  aanroepen zijn duur?
- [ ] **[gedrag] `address=` op `www-ssl`.** Dit beperkt de REST API tot de host van de app, maar ook WebFig.
  Is dat gewenst op elk apparaat?

## C. Wifi via CAPsMAN

Overgenomen uit de proefversie, aangevuld met wat het nieuwe ontwerp nodig heeft.

- [ ] **[blokkerend] Plan blijft wijzigingen tonen na toepassen.** Dan geeft RouterOS een eigenschap anders
  terug dan de app hem zet, bijvoorbeeld een standaardwaarde die wordt weggelaten. De vergelijking staat in
  `v0.1/backend/app/wifi.py` (`_norm`, `DEFAULTS`).
- [ ] **[blokkerend] Radio's van de controller overnemen** gebruikt `/interface/wifi/radio/provision`. Volgens
  de documentatie kan de interfacenaam daarbij veranderen, waardoor statische bridge-poorten naar `wifi1` en
  `wifi2` ongeldig worden. Doe dit bekabeld.
- [ ] **[blokkerend] Per SSID.** Zet `ft` aan op het security-profiel van één SSID en `client-isolation` op de
  datapath van een ander. Geldt het echt alleen voor dat SSID, ook als beide op dezelfde radio uitzenden?
- [ ] **[gedrag] Steering.** Hoe hangen `rrm` en `wnm` aan een SSID: via een steering-profiel met een
  neighbor-group per SSID, of gedeeld? Het ontwerp toont steering als schakelaar per SSID.
- [ ] **[gedrag] Kanaal, kanaalbreedte en zendvermogen per radio** komen uit `/interface/wifi/monitor … once`
  met meerdere interfaces tegelijk. Blijft de kolom leeg, dan accepteert de versie dat niet.
- [ ] **[gedrag] Kanaal vastzetten per radio.** De provisioning deelt één kanaalprofiel per band uit. Hoe geef
  je één access point een eigen kanaal zonder de provisioning te breken?
- [ ] **[gedrag] Omgevingsscan.** Onderbreekt `/interface/wifi/scan` de clients op die radio? Werkt het op een
  radio die door CAPsMAN wordt beheerd? Hoe lang duurt een scan van alle 5 GHz-kanalen?
- [ ] **[gedrag] DFS.** Hoe lang is een radio weg bij een wissel naar een DFS-kanaal (CAC), en hoe meldt
  RouterOS een radardetectie?
- [ ] **[gedrag] Signaal, retries en linkrate per client.** Welke velden geeft de registration-table, en
  welke alleen op de access point zelf en niet op de controller?
- [ ] **[gedrag] Roaming.** Is uit de log of de registration-table af te leiden of een client via fast
  transition is overgestapt of opnieuw moest associëren?
- [ ] **[gedrag] wifi-qcom-ac.** Access points met dit pakket kunnen geen VLAN uit de datapath krijgen. Het
  VLAN moet daar per interface met een bridge-PVID. Hoe toont de app dat verschil?
- [ ] **[gedrag] Blokkeren en disconnect.** Werkt een access-list-regel op de controller direct voor een
  client die al verbonden is?

## D. Netwerken en poortmatrix

- [ ] **[blokkerend] Waar staan de VLAN's?** Op een CRS3xx in de bridge VLAN-tabel met hardware offload. Op
  apparaten met een oudere switch-chip (zoals de hEX PoE) mogelijk in `/interface/ethernet/switch`. Leest en
  schrijft de matrix op elk type de juiste plek?
- [ ] **[blokkerend] `vlan-filtering` staat uit.** De app zet het niet aan. Regels in de bridge VLAN-tabel doen
  dan niets. Zie het open besluit hierover in [bouwplan.md](bouwplan.md).
- [ ] **[blokkerend] Management-poort herkennen.** De app zoekt zijn eigen MAC-adres op via `/ip/arp` en
  `/interface/bridge/host`. Klopt de poort op een switch die de app via de router bereikt? En via de
  management-tunnel, waar het verkeer van de router zelf komt?
- [ ] **[gedrag] Hardware offload.** Blijft `hw=yes` staan na een wijziging in de VLAN-tabel, of valt verkeer
  terug op de CPU?
- [ ] **[gedrag] PVID wijzigen** op een poort met een actieve client: hoe lang is de client weg?
- [ ] **[gedrag] Gastisolatie.** De drop-regel wordt met `/ip/firewall/filter/move` direct na de
  established/related-accept in `forward` gezet. Controleer de positie. Zonder zo'n regel komt de drop onderaan.
- [ ] **[gedrag] Volgorde bij een nieuw netwerk.** VLAN-interface, adres, pool, DHCP-server, bridge VLAN,
  interface-list. Wat blijft achter als stap 4 mislukt en de app terugdraait?

## E. Clients en verbruik

- [ ] **[gedrag] Bedraad op een gedeelde poort.** Clients achter een onbeheerde switch of een access point
  van een ander merk verschijnen op de switchpoort waar die aan hangt.
- [ ] **[gedrag] Verbruik per client.** Voor wifi-clients komen de tellers uit de registration-table en
  beginnen ze opnieuw bij elke associatie. Voor bedrade clients is er geen teller per MAC-adres. Het ontwerp
  laat verbruik bij bedrade clients daarom leeg; klopt dat met wat RouterOS kan?
- [ ] **[gedrag] Verbruik per WAN-verbinding.** Interfacetellers beginnen opnieuw bij een reboot. De app moet
  zelf optellen.
- [ ] **[gedrag] Static lease maken** van een dynamische lease: verandert het `.id`, en blijft de client online?

## F. WAN en failover

De app past WAN niet aan, maar moet het wel goed lezen.

- [ ] **[gedrag] Status lezen.** Zijn `/tool/netwatch` en de `active`-vlag van de routes genoeg om te zien
  welke verbinding actief is, ook bij een opzet met recursive routes of scripts?
- [ ] **[gedrag] Geschiedenis.** Een failover die korter duurt dan één poll mist de app. Staat hij dan wel in
  de log van de router, en is die via REST te lezen?
- [ ] **[gedrag] Publiek IP achter CGNAT.** Hoe herkent de app CGNAT: aan het adresbereik 100.64.0.0/10, of
  door het adres te vergelijken met IP Cloud?

## G. Onderhoud

- [ ] **[blokkerend] Export via REST.** Eerst `:execute "/export" as-string`, anders export naar een bestand
  en uitlezen via `/file`. Op oudere 7.x is `contents` beperkt in grootte.
- [ ] **[gedrag] Wachtwoorden in de export.** Wat staat erin met en zonder `show-sensitive`? De opslag van
  back-ups is versleuteld; de diff in de wijzigingslog mag geen wachtwoorden tonen.
- [ ] **[gedrag] Update starten.** `check-for-updates`, downloaden en installeren via REST. Hoe lang is elk
  type apparaat weg? Wat ziet de app als de download mislukt?
- [ ] **[gedrag] RouterBOOT.** `/system/routerboard/upgrade` en daarna een tweede reboot. Is te zien dat de
  upgrade klaarstaat?
- [ ] **[gedrag] Volgorde.** Als de switch waar de access points aan hangen herstart, zijn de access points
  ook even weg. Wacht de app daar goed op?
- [ ] **[gedrag] Wijziging buiten de app.** Nu gevonden via de diff van de nachtelijke export. Staat er ook
  een regel in de log van de router met de gebruiker, zodat het sneller en met naam kan?
- [ ] **[gedrag] Terugzetten.** Een export importeren is niet hetzelfde als een back-up laden. Welke van de
  twee gebruikt Terugzetten, en wat gebeurt er met objecten die sindsdien zijn toegevoegd?

## H. Externe sites en de management-tunnel

- [ ] **[blokkerend] Script op de externe router.** Plak het script uit het scherm
  [Externe site toevoegen](schermen.md#sites) op een router met de standaard-firewall en op een router zonder
  firewallregels. Werkt `place-before=0` in een geplakt script in beide gevallen?
- [ ] **[blokkerend] Alleen management.** Controleer vanaf beide kanten: geen ping naar elkaars LAN, geen
  route naar elkaars subnet, op de tunnel alleen tcp 443 naar de router open.
- [ ] **[blokkerend] Achter CGNAT.** Komt de handshake tot stand als de externe site achter CGNAT zit, en
  blijft de tunnel staan met `persistent-keepalive=25s`?
- [ ] **[blokkerend] Endpoint op hostnaam.** Het endpoint is de IP Cloud-naam van de thuislocatie. Als het
  publieke IP daar verandert, komt de tunnel dan vanzelf terug, of moet een script de peer opnieuw laten resolven?
- [ ] **[gedrag] Failover thuis.** Trek de hoofdverbinding eruit. Wat doet IP Cloud als de thuislocatie op
  4G achter CGNAT zit, en hoe lang duurt het na failback voordat de tunnel terug is?
- [ ] **[gedrag] Switches en access points op de externe site** via een port forward op het tunneladres.
  Werkt dat als `www-ssl` op die apparaten met `address=` is beperkt? Welk bronadres zien ze?
- [ ] **[gedrag] Dezelfde subnetten op twee sites.** Beide 192.168.88.0/24. Blijft alles werken?
- [ ] **[gedrag] Meerdere externe sites.** Verkeer van de ene tunnel naar de andere moet op de thuislocatie
  worden gedropt.

## I. Inloggen en meldingen

- [ ] **[blokkerend] Passkeys vragen een hostnaam.** WebAuthn werkt niet op een IP-adres en alleen over
  https. Leg de hostnaam vast voordat er passkeys worden gemaakt; een andere hostnaam maakt ze onbruikbaar.
- [ ] **[blokkerend] Web Push** op Chrome en Firefox (desktop), Android en iPhone. Op iPhone en iPad alleen
  als de app op het beginscherm staat.
- [ ] **[gedrag] Achter een reverse proxy** (bijvoorbeeld Pangolin): komen push, passkeys en de veilige cookie
  goed door?
- [ ] **[gedrag] Melding als alles down is.** Zonder internet kan de app geen push versturen. De melding moet
  binnenkomen zodra er weer verbinding is.

## J. Sites, ontdekken en gasten

- [ ] **[gedrag] Ontdekken.** Geeft `/ip/neighbor` op de router genoeg (identity, adres, model, versie) om
  nieuwe apparaten te vinden zonder dat de app zelf in dat netwerk zit?
- [ ] **[gedrag] Template toepassen** op een router met een bestaande configuratie. Wat botst er?
- [ ] **[gedrag] Vouchers.** De hotspot van RouterOS op het gast-VLAN, terwijl het wifi-verkeer via CAPsMAN
  lokaal wordt doorgezet. Werken geldigheid en rate limit per voucher?
- [ ] **[gedrag] QR-code.** Een wifi-QR-code werkt met een WPA-wachtwoord. Gaat dat samen met de hotspot, of
  is het een van de twee?

---

## Wat hier niet in staat

Legacy `wireless` (RouterOS 6 en oudere MIPS-access points), IPv6 en het beheren van WAN, NAT en routing
vallen buiten het ontwerp en hoeven niet getest te worden.
