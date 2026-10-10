# Bronbestanden van het ontwerp

Elk scherm is één `.dc.html`-bestand. `canvas.json` beschrijft hoe ze op het ontwerpcanvas liggen en hoe
groot elk scherm is.

De bestanden zijn gemaakt voor het ontwerpcanvas van Claude en hebben de runtime daarvan nodig om te
tekenen. Die runtime (`support.js`) zit niet in deze repository. Los geopend in een browser tonen ze dus
niets. Ze zijn hier bewaard als naslag bij het bouwen: alle maten, kleuren en teksten staan er letterlijk
in, als inline stijlen, en de voorbeelddata staat onderaan elk bestand in het script.

De afbeeldingen in [`../../docs/schermen/`](../../docs/schermen/) zijn van deze bestanden gemaakt.

| Voorvoegsel | Wat |
|---|---|
| `C2-` | De uitgewerkte hoofdschermen, desktop en mobiel |
| `W-`, `P-`, `O-` | Wifi, poortmatrix, onderhoud en instellingen |
| `T-` | Inloggen, gebruikers en rollen |
| `S-` | Opslaan per pagina, eerste keer instellen, meldingencentrum, wijzigingslog, externe site |
| `I-` | De uitgewerkte ideeën: veilige modus, snelzoeken, ontdekken, wifi-inzicht, gasten, templates, push |
| `M-` | Mobiele schermen |
| `N-`, `N2-` tot `N6-` | Naam en pictogram, met de afgevallen kandidaten |
| `Main`, `A-`, `B-`, `C-` | De eerste verkenning van drie stijlen. Stijl C is gekozen; A en B zijn afgevallen |
