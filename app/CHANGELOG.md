# Wijzigingen

Wat er per proefversie bij kwam. De mappen v0.1 t/m v0.7 staan sinds v0.8 niet meer los in de repository;
ze zijn bewaard in de branch [`archief/proefversies-v0.1-v0.7`](https://github.com/Timmexk/MikroManager/tree/archief/proefversies-v0.1-v0.7).

## v0.8

Opgeruimde wifi en één app-map.

- **Eén radiopaneel per access point.** Klik onder Wifi op een access point: alle radio's staan onder elkaar met
  aan/uit, kanaal, breedte en zendvermogen, en één *Opslaan* onderaan voor het hele paneel. Bij de router staat per
  radio ook de keuze *Site-netwerken / Zelfstandig / Niet beheerd*; een zelfstandige radio toont zijn eigen SSID's
  in hetzelfde paneel. Een zelfstandig access point stel je ook daar in (en adopteer je daar). Het blok *Wifi op dit
  apparaat* op de apparaatpagina is vervangen door een knop *Radio's instellen*.
- **Waar een netwerk uitzendt, kies je bij het netwerk.** In het netwerkvenster staat *Uitzenden op: Alle access
  points / Kiezen*, met per access point een vinkje. *Alle* geldt ook voor access points die je later adopteert. De
  oude keuze *Uitzenden op: alle / alleen de router / alleen de CAP's* en de vinkjes per radio zijn daarin opgegaan.
  In de lijst met netwerken zie je per netwerk op hoeveel access points het staat.
- **Wifi-instellingen gesplitst.** Onder Wifi staan alleen nog de *Radio-standaarden* (land, kanaalbreedtes,
  kanalen, DFS, 802.11k/v). Wifi-controller, bridge, CAPsMAN, wifi-qcom-ac en *direct toepassen* staan onder
  *Instellingen → Wifi-controller*.
- **API.** `POST /api/sites/{id}/wifi/radios` slaat meerdere radio's in één keer op en past ze in één keer toe.
  `PATCH /api/wlans/{id}` en `POST /api/sites/{id}/wifi/wlans` nemen `radios` (lijst van radio-MAC's, `null` = alle).
  `POST /api/sites/{id}/wifi/radios/{mac}` laat de netwerken op de radio met rust als `ssids` ontbreekt.
- **Repository.** De code staat in `app/`; de losse mappen v0.1 t/m v0.7 zijn weg (zie de branch hierboven). Een
  Docker-image staat op `ghcr.io/timmexk/mikromanager`, met een Unraid-template in `unraid/`.

## v0.7

**Direct toepassen.** Opslaan in het netwerkvenster, bij een radio of in de wifi-instellingen zet de wijziging meteen
op de router en de access points. Mislukt een stap, dan zet MikroManager de wijziging in zijn eigen database terug en
past de oude toestand opnieuw toe, zodat er niets half blijft staan; je ziet welke stap misging. De oude werkwijze
(eerst bekijken, dan toepassen) staat onder *Wifi-instellingen → Wijzigingen direct toepassen*. De melding "staat nog
niet op de router" verschijnt nu alleen nog als er iets afwijkt, bijvoorbeeld na een aanpassing in WinBox.

**Eenvoudig netwerkvenster.** Naam, wachtwoord (met *Bedenk er een*: vier woorden), netwerk en banden. Beveiliging,
op welke AP's, 802.11r, isolatie, verbergen en aan/uit staan onder *Geavanceerd*.

**Eén lijst met access points.** De router staat er gewoon tussen, met per radio het kanaal en zendvermogen. Klik
op een AP voor een paneel met:

- *Radio's*: per radio aan/uit, welke netwerken, kanaal, breedte en zendvermogen (Laag/Midden/Hoog/Handmatig);
- *Clients en omgeving*: clients met signaal en snelheid, netwerkscan en kanaalbezetting;
- *Beheer*: bij de router per radio *site-netwerken*, *zelfstandig* of *niet beheerd*; bij een CAP opnieuw provisionen of
  loskoppelen; bij een los AP adopteren of zelf instellen.

**Automatisch kanaalplan** (knop *Kanaalplan* bij Access points). Elke radio scant één keer (`/interface/wifi/scan`;
clients zijn dan een paar seconden weg). MikroManager kiest per radio het kanaal met de minste overlap met de buren
(gewogen naar signaal) en met je eigen AP's (zwaar als ze elkaar horen), rekening houdend met de kanaalbreedte en met
een kleine voorkeur voor niet-DFS en voor het huidige kanaal. AP's die elkaar sterker dan −55 dBm horen krijgen het
advies *zendvermogen midden*. Je ziet per radio nu/voorstel/waarom en kiest wat je overneemt.

**Update-wachtrij** (Onderhoud → Updates). Kies apparaten, *nu*, *vannacht 03:00* of een tijdstip, en of de
RouterBOOT-firmware ook mee moet. Volgorde: access points, switches (diepste in het netwerk eerst), de router als
laatste. Elk apparaat moet terug zijn op de nieuwe versie voordat het volgende begint; mislukt er één, dan worden de
rest overgeslagen. De wachtrij staat in de database en gaat verder na een herstart van MikroManager. Annuleren kan
zolang er nog apparaten wachten. *Wat is er nieuw* opent de changelogs van MikroTik.

**Bijwerken**

```bash
cd ~/MikroManager && git pull
cd v0.7 && sudo bash linux/install.sh
```

Bestaande sites houden hun instellingen; *direct toepassen* staat standaard aan. Nieuwe sites laten de radio's van de
router meteen de site-netwerken uitzenden.

## v0.6: router-radio's en naadloos roamen

**Waarom.** CAPsMAN kan de radio's van het apparaat waarop hij draait niet beheren. De handleiding zegt: zet zelf
dezelfde configuratie op de lokale interfaces. Tot v0.5 deed MikroManager dat alleen met een verwijzing naar het
profiel. Maar op een hAP ax² staan vanuit de standaardconfiguratie *inline* instellingen op wifi1/wifi2
(`configuration.ssid`, `security.passphrase` …), en die gaan altijd vóór een profiel. Het weghalen daarvan kon op
echte hardware stil mislukken, waardoor instellingen niet aankwamen.

**Hoe nu.** Onder Wifi staat een eigen blok **Radio's van de router**, met per radio:

| Keuze | Wat er gebeurt |
|---|---|
| **Site-netwerken** | De radio krijgt het profiel én dezelfde waarden als inline-eigenschappen: SSID, beveiliging, wachtwoord, 802.11r, bridge, VLAN, client-isolatie, land, kanaalbreedte (en kanaal/zendvermogen als je die per radio vastzet). Inline gaat altijd voor, dus een oude instelling kan niet meer in de weg zitten. Extra SSID's worden virtuele interfaces met dezelfde waarden. |
| **Zelfstandig** | De radio houdt zijn huidige SSID's, maar de instellingen staan op de interface zelf; je stelt hem in bij het apparaat. |
| **Niet beheerd** | MikroManager haalt zijn extra SSID's weg en laat de radio verder met rust. |

- **Teruglezen na toepassen.** Na *Toepassen* leest MikroManager de radio's van de router terug. Wijkt er iets af,
  dan staat dat als foutregel in het resultaat ("RouterOS heeft deze instellingen niet overgenomen").
- **Afwijking zien.** Wordt een router-radio in WinBox aangepast, dan krijgt hij het label *wijkt af* met wát er
  afwijkt (SSID, 802.11r, VLAN …); *Bekijken en toepassen* zet het recht.
- **Naadloos roamen.** Een nieuw blok laat per SSID zien waar het wordt uitgezonden (router en AP's), of 802.11r aan
  staat en of iets het roamen kan verstoren: een zelfstandige radio met dezelfde naam, of een router-radio die afwijkt.
- **Roaming-hulp (802.11k/v)**, onder Radio-instellingen: een steering-profiel `mm-steering` met `rrm=yes` en
  `wnm=yes` op alle configuraties. Standaard uit, omdat het nog niet op echte hardware is getest.
- **Wachtwoord wijzigen** past nu ook direct de radio's van de router aan (in het plan gemaskeerd).

De oude knoppen *Radio's overnemen* en *Teruggeven* zijn vervangen door de keuze per radio. Bestaande installaties:
stond *Radio's overnemen* aan, dan staan beide radio's op *Site-netwerken*; anders op *Niet beheerd*.

## v0.5: lokale wifi-radio's

**Per radio de SSID's kiezen en aan/uit.** Klik onder Wifi → Access points op het kanaal of het zendvermogen van een
radio. Onder *Instellingen* kies je welke wifi-netwerken van de site die radio uitzendt (bijvoorbeeld gast alleen op
de 5 GHz van de router) en zet je de radio aan of uit.

- Eigen radio van de router: het eerste gekozen netwerk wordt het profiel op wifi1/wifi2, de rest virtuele
  interfaces. Uit = de interface op `disabled`.
- Radio van een CAP: een provisioning-regel op `radio-mac` met alleen de gekozen configuraties. Uit (of geen
  netwerk gekozen) = `action=none`, dan maakt CAPsMAN voor die radio geen interface.
- Staan alle netwerken aan, dan komt een nieuw netwerk er vanzelf bij; met een eigen keuze niet.

**Zelfstandig instellen.** Onder Apparaten → (apparaat) staat het blok *Wifi op dit apparaat*:

- **Losse access points** (een MikroTik met wifi die geen CAP is, bijvoorbeeld een hAP of wAP elders) stel je daar
  helemaal zelf in: SSID, beveiliging en wachtwoord, verbergen, client-isolatie, snelle roaming, bridge en VLAN per
  SSID, en per radio kanaal, kanaalbreedte, zendvermogen en land. Extra SSID's voeg je toe als virtuele interface
  (`master-interface`). Het wordt direct op het apparaat gezet, als inline-eigenschappen zoals in de MikroTik-handleiding
  (`configuration.ssid`, `security.passphrase`, `channel.frequency`, `datapath.vlan-id` …); er is geen 'toepassen'.
  Ze staan onder Wifi → Access points als *Zelfstandig*, met *Adopteren* als je ze toch aan CAPsMAN wilt hangen.
- **Een radio van de router** kun je *zelfstandig maken*. Hij blijft dan dezelfde SSID's uitzenden, maar de instellingen
  uit de profielen worden inline-eigenschappen op de interface en de site-netwerken laten hem verder met rust.
  *Terug naar de site* zet de profielen weer terug en haalt de overgenomen extra SSID's weg.

**Radio-inzicht.** Onder *Clients en omgeving* bij elke radio (router, CAP of los access point):

- de status, het kanaal en het zendvermogen volgens `/interface/wifi/monitor`, en de clients met signaal, snelheid
  en verbindingsduur;
- **Netwerken scannen** (`/interface/wifi/scan`): access points in de buurt met kanaal, signaal en aantal clients;
- **Kanaalbezetting meten** (`/interface/wifi/frequency-scan`): per kanaal de belasting, het aantal netwerken en de
  ruisvloer, met het kanaal van de radio gemarkeerd.

Beide scans halen de radio een paar seconden van zijn kanaal: clients op die radio verliezen even de verbinding.
MikroManager vraagt daarom eerst om bevestiging. Bij een CAP draait de scan op het access point zelf, dus dat moet als
apparaat zijn toegevoegd.

## v0.4

**Eigen radio's van de router los van CAPsMAN.** CAPsMAN kan de radio's van het apparaat waarop hij draait niet
beheren (`configuration.manager=capsman` werkt daar niet). MikroManager zet de profielen daarom rechtstreeks op de
eigen radio's en gebruikt CAPsMAN alleen voor de access points:

- **CAPsMAN automatisch:** provisioning-regels en CAPsMAN pas zodra er een access point is (er is er een
  geadopteerd, er hangt een CAP aan de controller of de regels bestaan al). Instelbaar onder Radio-instellingen:
  automatisch, altijd of uit.
- **Adopteren zet de AP meteen aan het werk:** regels, CAPsMAN en profielen worden direct geschreven, zonder
  aparte "toepassen".
- **Toepassen in groepen:** profielen, eigen radio's (direct), access points (CAPsMAN) en opruimen. Een fout stopt
  alleen de rest van zijn eigen groep. Een probleem met de eigen radio's blokkeert dus niet langer alle andere
  wifi-wijzigingen. Het weghalen van een inline-instelling op een eigen radio mag mislukken zonder dat het plan stopt.
- **`configuration.manager` terug naar local** als een eigen radio op `capsman` of `capsman-or-local` staat.

**Wifi-controle (geen IP-adres?).** Bovenaan de Wifi-pagina loopt MikroManager per SSID het pad na: bestaat de
bridge, staat vlan-filtering aan, is er een VLAN-interface, staat de bridge zelf tagged in de bridge-VLAN-tabel,
is er een adres en een DHCP-server, en zit elke eigen radio-interface in de juiste bridge met de juiste PVID. Ook
bridge-poorten die naar een verdwenen interface wijzen (overblijfsel van provisionen) worden gevonden. Wat veilig
kan, repareer je met één klik: wees-poort verwijderen, bridge tagged toevoegen, PVID of bridge van een vaste poort
goed zetten, poort toevoegen, DHCP-server aanzetten, manager op local. Vlan-filtering aanzetten doet de controle
bewust niet: dat kan je buitensluiten en hoort bij Interfaces met veilige modus.

**Netwerk per SSID uit de router.** In plaats van een kaal VLAN-nummer kies je het netwerk uit wat er op de router
staat: het LAN, een VLAN op de bridge, of een eigen bridge zonder VLAN (voor wie IoT of gasten op een aparte bridge
heeft). Per SSID kies je ook waar het wordt uitgezonden: alle access points, alleen de router of alleen de CAP's.

**Uitstraling.** Nieuw overzicht met statuskaarten (apparaten, clients, internet, wifi, updates) en een
topologie: de router bovenaan, daaronder elk apparaat aan de poort waar het hangt, met het aantal clients. De
topologie wordt afgeleid uit de bridge-tabellen. Verder een rustigere zijbalk met groepen, tabellen met vaste
koppen, en overal dezelfde knoppen, kaarten en meldingen, licht en donker.

## v0.3

**Clients**

- **Fabrikant** bij elke client, afgeleid van het MAC-adres (IEEE-lijst, wekelijks opgehaald; bijwerken of
  uitzetten onder Instellingen). Een willekeurig privé-MAC-adres van een telefoon wordt als "privé-adres" getoond.
- **Historie per client**: eerst en laatst gezien, online/offline en roamen tussen access points, 30 dagen
  bewaard. Offline clients blijven in de lijst staan met "laatst gezien"; met **Vergeten** haal je ze weg.
- **Bedrade clients blokkeren.** Blokkeren werkt nu voor elke client: een drop-regel op het MAC-adres bovenaan
  de forward-chain (IPv4 en IPv6), en voor wifi daarnaast de access-list. Let op: verkeer binnen hetzelfde VLAN
  gaat niet door de firewall en blijft dus mogelijk; de client komt alleen niet meer naar andere netwerken en
  internet.
- **Actuele snelheid voor wifi-clients** komt uit de registration-table (`tx-bits-per-second`), niet meer
  alleen uit Kid Control. Hostnaam en IP vallen terug op `dhcp-hostname`/`dhcp-address` van de AP.

**Wifi**

- **Kanaal en kanaalbreedte per radio.** Klik bij een radio op het kanaal of het zendvermogen. De keuzelijst
  komt uit wat de radio zelf opgeeft (`5g-channels`/`2g-channels`), DFS-kanalen zijn gemarkeerd.
- **Aandachtspunten**: meldingen over twee radio's op hetzelfde kanaal, clients met een zwak signaal
  (−75 dBm of slechter), 40 MHz op 2,4 GHz en access points die niet goed geprovisioned zijn.
- **Opnieuw provisionen** per access point, voor als een CAP zijn configuratie niet oppakt.
- **QR-code per SSID** om gasten te laten verbinden, ook af te drukken.
- Op een telefoon staan de access points als kaarten onder elkaar in plaats van in een brede tabel.

**Onder de motorkap**

- **Diagnosebestand** (Instellingen → Diagnose): de ruwe uitvoer van de RouterOS-menu's die MikroManager leest,
  als JSON. Wachtwoorden en sleutels zitten er nooit in; de anonieme variant vervangt ook MAC-adressen, namen
  en publieke IP-adressen. Bedoeld om problemen op echte hardware te kunnen uitzoeken.
- **Minder verkeer naar de router**: de clientlijst, interfaces en openstaande wifi-wijzigingen worden kort
  gecachet; een wijziging gooit de cache leeg.
- **Fouten** komen in het logboek (`journalctl -u mikromanager`) en geven in de app een nette melding in
  plaats van een kale 500. `/api/health` voor bewaking.
- **Namen**: instellingen heten nu `MIKROMANAGER_*` (de oude `MIKROMANAGER_*` werken nog), de database
  `mikromanager.db`, en nieuwe sites gebruiken het kenmerk `mm-` op de router.
- Opgeruimd: een aanroep van een Kid Control-commando dat volgens de handleiding niet bestaat.

## Bijwerken vanaf v0.1 of v0.2 (naamgeving, uit v0.3)

```bash
cd ~/MikroManager && git pull
cd v0.7 && sudo bash linux/install.sh
```

- De database wordt bij de eerste start gekopieerd van `mikromanager.db` naar `mikromanager.db`. Het oude
  bestand blijft staan, zodat je terug kunt naar v0.2.
- Je bestaande `/etc/mikromanager/mikromanager.env` blijft staan en de oude namen daarin blijven werken.
- **Bestaande sites houden het kenmerk `tc-` op de router**, zodat er niets hernoemd of dubbel aangemaakt
  wordt. Alleen een site die je vanaf v0.3 nieuw aanmaakt krijgt `mm-`. Waar hieronder `mm-` staat, lees je voor
  een oudere site `tc-`.
- Docker: `docker-compose.yml` wijst nog naar `/mnt/user/appdata/tikcontrol`, zodat je data gevonden wordt.

## v0.2: interfaces per apparaat

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

**Zendvermogen per radio.** Onder **Wifi → Access points** stel je per radio het zendvermogen in: Handmatig
(dBm), Laag, Midden of Hoog. Hoog stelt niets in: RouterOS gebruikt dan het maximum dat het land op dat kanaal
toestaat (`current-max-reg-power` van de radio; in Nederland 20 dBm op 2,4 GHz, 23 dBm op 5 GHz kanaal 36–64 en
30 dBm op kanaal 100–140, allemaal EIRP). Midden is 6 dB en Laag 12 dB onder dat maximum. Voor een access point
zet MikroManager per radio een provisioning-regel op `radio-mac` met een eigen kopie van de master-configuratie
met `tx-power`; voor de eigen radio's van de router alleen die kopie. Toepassen via **Bekijken en toepassen**.

**Eigen radio's van de router.** CAPsMAN kan de radio's van het apparaat waarop het draait niet beheren en
MikroTik raadt af ze te provisionen: de interfaces worden dan verwijderd en opnieuw aangemaakt. **Radio's overnemen**
zet daarom de wifi-profielen rechtstreeks op wifi1/wifi2, met statische virtuele interfaces (comment `mm:local:…`)
voor extra SSID's. **Teruggeven** haalt dat weer weg. Heeft v0.1 of een eerdere v0.2 de radio's wel geprovisioned,
dan herstelt MikroManager dat eerst op de manier uit de handleiding: provisioning-regels even uit, radio opnieuw
provisionen, regels weer aan.

**Live grafieken.** Het overzicht en de apparaatpagina openen op **Live**: zolang je kijkt, leest MikroManager
elke 2 seconden de interfacetellers en de CPU van de apparaten op die pagina, en pingt elke 6 seconden naar
1.1.1.1. De laatste 10 minuten schuiven mee; bij openen worden ze aangevuld met de opgeslagen metingen. Kijkt
er een minuut niemand, dan stopt het snelle meten vanzelf. Instelbaar met `MIKROMANAGER_LIVE_INTERVAL` (seconden)
en `MIKROMANAGER_LIVE_WINDOW` (seconden). Voor langere periodes kies je 1, 6 of 24 uur.

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
