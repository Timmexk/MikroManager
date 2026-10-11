# Schermen

Alle schermen van het ontwerp, in het donkere thema tenzij anders vermeld. De data is verzonnen en op elk
scherm dezelfde, zie [ontwerpbesluiten.md](ontwerpbesluiten.md#15-voorbeelddata-in-de-schermen).
De bronbestanden staan in [`bron/`](bron/).

Inhoud: [Dagelijks beheer](#dagelijks-beheer) · [Wifi](#wifi) · [Netwerken en veilige modus](#netwerken-en-veilige-modus) · [Onderhoud](#onderhoud) · [Toegang](#toegang) · [Sites](#sites) · [Mobiel](#mobiel) · [Naam en pictogram](#naam-en-pictogram)

## Dagelijks beheer

### Overzicht

WAN, apparaten, clients en wat aandacht vraagt op één pagina.

![Overzicht](../docs/schermen/overzicht.webp)

### Overzicht, licht thema

Hetzelfde scherm in het lichte thema.

![Overzicht, licht thema](../docs/schermen/overzicht-licht.webp)

### Topologie

Backbone op basis van neighbors (LLDP en MNDP) en bridge-hosts.

![Topologie](../docs/schermen/topologie.webp)

### Apparaat

Poortkaart met link, PoE, VLAN’s en configuratie-versies.

![Apparaat](../docs/schermen/apparaat.webp)

### Clients

Lijst met detail, signaal over 24 uur en historie.

![Clients](../docs/schermen/clients.webp)

### Snelzoeken

Ctrl K zoekt op naam, IP, MAC en vendor en biedt acties aan.

![Snelzoeken](../docs/schermen/snelzoeken.webp)

### Meldingencentrum

Opent vanuit de bel in de zijbalk.

![Meldingencentrum](../docs/schermen/meldingencentrum.webp)

## Wifi

### Wifi: overzicht

SSID’s, access points en signaalsterkte van de clients.

![Wifi: overzicht](../docs/schermen/wifi-overzicht.webp)

### Wifi: netwerk bewerken

Alle instellingen gelden voor één SSID. Rechts staat wat er op de router verandert.

![Wifi: netwerk bewerken](../docs/schermen/wifi-bewerken.webp)

### Wifi: kanalen en radio’s

Kanaalplan per band met naburige netwerken, kanaalbreedte en zendvermogen.

![Wifi: kanalen en radio’s](../docs/schermen/wifi-kanalen.webp)

### Wifi: inzicht

Co-channel, sticky clients en roaming van vandaag.

![Wifi: inzicht](../docs/schermen/wifi-inzicht.webp)

### Wifi: gasten

QR-code, wachtwoord en vouchers voor het gastnetwerk.

![Wifi: gasten](../docs/schermen/wifi-gasten.webp)

## Netwerken en veilige modus

### Netwerken

WAN-verbindingen met failover-geschiedenis, lokale netwerken en de poortmatrix.

![Netwerken](../docs/schermen/netwerken.webp)

### Poortmatrix bewerken

Klik op een cel: leeg, tagged, untagged. Geen poort staat op slot.

![Poortmatrix bewerken](../docs/schermen/poortmatrix.webp)

### Veilige modus

Bevestig je niet, dan volgt een rollback, ook als de verbinding weg is.

![Veilige modus](../docs/schermen/veilige-modus.webp)

### Opslaan per pagina

De balk onderaan en de vraag bij het verlaten van een pagina.

![Opslaan per pagina](../docs/schermen/opslaan-per-pagina.webp)

## Onderhoud

### Onderhoud

Updates op volgorde en back-ups met diff.

![Onderhoud](../docs/schermen/onderhoud.webp)

### Wijzigingslog

Elke wijziging met diff, ook wat buiten de app is gedaan.

![Wijzigingslog](../docs/schermen/wijzigingslog.webp)

### Wijzigingslog: wie deed wat

Per gebruiker en per site, met de open sessies.

![Wijzigingslog: wie deed wat](../docs/schermen/wie-deed-wat.webp)

### Instellingen

Wat bij de site hoort en wat voor de hele app geldt, staat apart.

![Instellingen](../docs/schermen/instellingen.webp)

### Pushmeldingen

Per gebeurtenis aan of uit, met stille uren.

![Pushmeldingen](../docs/schermen/pushmeldingen.webp)

## Toegang

### Inloggen

Wachtwoord of passkey.

![Inloggen](../docs/schermen/inloggen.webp)

### Gebruikers

Per gebruiker een rol per site, met tijdelijke toegang.

![Gebruikers](../docs/schermen/gebruikers.webp)

### Gebruiker toevoegen

Rechts staat wat de gebruiker straks mag.

![Gebruiker toevoegen](../docs/schermen/gebruiker-toevoegen.webp)

### Rollen

Gebruiker, Netwerkbeheerder en Admin naast elkaar.

![Rollen](../docs/schermen/rollen.webp)

## Sites

### Eerste keer instellen

Vijf stappen. Er verandert niets op de router tot je daarvoor kiest.

![Eerste keer instellen](../docs/schermen/eerste-keer-instellen.webp)

### Externe site toevoegen

Functie voor later, niet in de eerste versie. Een WireGuard-tunnel die alleen management doorlaat.

![Externe site toevoegen](../docs/schermen/externe-site.webp)

### Apparaten ontdekken

Via neighbor discovery en een scan van het subnet.

![Apparaten ontdekken](../docs/schermen/apparaten-ontdekken.webp)

### Templates

Een vaste set netwerken en instellingen voor een nieuwe locatie.

![Templates](../docs/schermen/templates.webp)

## Mobiel

<table>
<tr>
<td align="center" valign="top"><img src="../docs/schermen/mobiel-overzicht.webp" alt="Mobiel: overzicht" width="170"><br><sub>Overzicht</sub></td>
<td align="center" valign="top"><img src="../docs/schermen/mobiel-client.webp" alt="Mobiel: client" width="170"><br><sub>Client</sub></td>
<td align="center" valign="top"><img src="../docs/schermen/mobiel-apparaat.webp" alt="Mobiel: apparaat" width="170"><br><sub>Apparaat</sub></td>
<td align="center" valign="top"><img src="../docs/schermen/mobiel-wifi.webp" alt="Mobiel: wifi" width="170"><br><sub>Wifi</sub></td>
<td align="center" valign="top"><img src="../docs/schermen/mobiel-wifi-bewerken.webp" alt="Mobiel: wifi-netwerk bewerken" width="170"><br><sub>Wifi-netwerk bewerken</sub></td>
</tr>
<tr>
<td align="center" valign="top"><img src="../docs/schermen/mobiel-poorten.webp" alt="Mobiel: poorten en VLAN’s" width="170"><br><sub>Poorten en VLAN’s</sub></td>
<td align="center" valign="top"><img src="../docs/schermen/mobiel-meldingen.webp" alt="Mobiel: meldingen" width="170"><br><sub>Meldingen</sub></td>
<td align="center" valign="top"><img src="../docs/schermen/mobiel-onderhoud.webp" alt="Mobiel: onderhoud" width="170"><br><sub>Onderhoud</sub></td>
<td align="center" valign="top"><img src="../docs/schermen/mobiel-meer.webp" alt="Mobiel: meer" width="170"><br><sub>Meer</sub></td>
<td align="center" valign="top"><img src="../docs/schermen/mobiel-inloggen.webp" alt="Mobiel: inloggen" width="170"><br><sub>Inloggen</sub></td>
</tr>
</table>

## Naam en pictogram

### Pictogram

De drie kandidaten; gekozen is switch 1.

![Pictogram](../docs/schermen/pictogram.webp)
