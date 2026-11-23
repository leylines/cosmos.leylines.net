# Leylines Astro-CZML API

Die API liefert direkt ein vollständiges CZML-Dokument. `out_*.json` und
`build.py` werden nicht mehr benötigt; vorhandene Dateien bleiben unverändert.
CZML selbst ist ein JSON-basiertes Format, aber es gibt keinen separaten
Zwischenschritt mit einem eigenen Positionsformat mehr.

## Start

```sh
docker build -t leylines-skyfield .
docker run --rm -p 8000:8000 leylines-skyfield
```

Unter <http://localhost:8000/> liegt die Cesium-Vorschau, unter
<http://localhost:8000/docs> die API-Dokumentation. Die Vorschau lädt Cesium
von einem CDN und verwendet die mit Cesium gelieferte Natural-Earth-II-Karte.
Über den Schalter **Re:Earth-Terrain** lässt sich das Terrain auch nach dem
Laden der CZML-Daten ein-/ausschalten, ohne diese neu abzurufen. Ein
Cesium-ion-Token ist nicht nötig. Ohne Terrain bleibt das WGS84-Ellipsoid aktiv.
Der Terrain-Provider wird von `https://terrain.reearth.land/cesium-mesh/ellipsoid`
mit Vertex-Normalen und Wassermaske geladen. Bei einem Ladefehler fällt die
Vorschau auf WGS84 zurück.

Alternativ lokal:

```sh
python3 -m venv .venv
.venv/bin/pip install fastapi uvicorn skyfield convertdate pandas httpx
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

## CZML herunterladen

```sh
python3 get_cosmos.py --date 1979-11-05 --output cosmos.czml
```

Oder direkt:

```sh
curl --fail-with-body http://localhost:8000/api/v1/cosmos.czml \
  -H 'Content-Type: application/json' \
  -d '{"year":1979,"month":11,"day":5,"calendar_type":"gregorian"}' \
  -o cosmos.czml
```

### Direkter GET-Aufruf aus dem Globus (empfohlen)

```text
https://cosmos.leylines.net/api/1979-11-05/gregorian
```

Die Route ist implementiert; DNS, HTTPS und Reverse Proxy für die Subdomain
müssen beim Deployment eingerichtet werden. CORS erlaubt Zugriffe von
`https://maps.leylines.net`. Download-CLI und Vorschau verwenden jetzt GET.
Die POST-Routen bleiben erhalten, erwarten jetzt aber ebenfalls nur
`year`, `month`, `day` statt der bisherigen Start-/Endfelder.
Die alte GET-Route mit zwei Datumsangaben entfällt.

Beispiel für CesiumJS:

```js
const cosmos = await Cesium.CzmlDataSource.load(
  'https://cosmos.leylines.net/api/1979-11-05/gregorian'
);
await viewer.dataSources.add(cosmos);
```

Standard: Pins nur für Sonne, Mond und konfigurierte Planeten; Sternbilder
sowohl am Himmel als auch als bewegliche Terrainlinien. Query-Parameter:

```text
?constellation_projection=ground
?constellation_projection=sky&pin_scope=zodiac
?constellation_projection=both&show_pins=false
?zodiac_only=true
?constellation_names=Ori&constellation_names=Tau
```

`constellation_projection`: `sky`, `ground` oder `both` (Standard).
`pin_scope`: `bodies` (Standard), `zodiac` (zusätzlich helle Sterne der
ausgewählten Tierkreisfiguren), `all` (zusätzlich alle hellen Sterne).
Die Helligkeitsgrenze für Stern-Pins gilt weiterhin.

### Himmelskulturen (Stellarium)

Mit `skyculture` wählst du die Sternbildfiguren; Standard bleibt `modern_st`:

```text
https://cosmos.leylines.net/api/0840-05-05/julian?skyculture=egyptian_dendera
```

```sh
python3 get_cosmos.py --date 0840-05-05 --calendar julian --skyculture egyptian_dendera
```

| `skyculture` | Figuren aus `constellations` | Hinweise |
|---|---:|---|
| `modern_st` | 88 | Zwölf klassische Tierkreisfiguren |
| `egyptian_dendera` | 34 | Zwölf Tierkreisfiguren nach den expliziten Kürzeln der Datei |
| `babylonian_mulapin` | 58 | Keine automatische Zuordnung zum modernen Tierkreis |
| `navajo` | 8 | Englische Namen als Rückfall |
| `chinese` | 309 von 312 | HIP-Teilmenge, siehe Einschränkungen unten |

Der Parameter gilt für GET und alle CZML-POST-Routen (JSON-Feld `skyculture`).
Auch die Vorschau bietet eine Auswahl. `constellation_names` sucht innerhalb
der gewählten Kultur nach einheimischen/englischen Namen, Aussprache, kompletter
Stellarium-ID oder letztem ID-Teil (z. B. `Ari` oder `001`). Für die Anzeige gilt:
einheimischer Name → englischer Name → ID. Unbekannte Kulturen werden mit HTTP 422
abgelehnt; Dateipfade können nicht als Kultur übergeben werden.

`zodiac_only=true` ist nur für `modern_st` und `egyptian_dendera` definiert;
bei den übrigen Kulturen antwortet die API mit HTTP 422, statt fremde Figuren
willkürlich den zwölf westlichen Zeichen zuzuordnen. Dort aktiviert auch
`pin_scope=zodiac` keine zusätzlichen Stern-Pins. Die konfigurierten Körper und
zusätzlichen Sterne aus `config.json` bleiben unabhängig von der Kultur erhalten.

**Chinesische Daten:** Die Datei enthält neben HIP-Nummern eine Gaia-ID
(`5350358584482202880`) und drei Deep-Sky-Objekte (`NGC2632`, `NGC6231`, `NGC6475`).
Diese können mit `hip_main.dat` nicht berechnet werden. Linien werden an solchen
Referenzen unterbrochen, niemals über die Lücke verbunden. Die drei ausschließlich
aus Deep-Sky-Referenzen bestehenden Figuren entfallen; die übrigen 309 bleiben
erhalten. Hinweise stehen im CZML-Dokument unter `properties.warnings` und werden
in der Vorschau angezeigt. Ein-Stern-Figuren werden als Sterne ohne degenerierte
Linien dargestellt. Die chinesische Kultur enthält wesentlich mehr Figuren und
kann größere Dateien und höhere Renderlast verursachen.

Es werden die HIP-Sterne und Linien aus `constellations` übernommen, nicht
Illustrationen, Sternbildgrenzen, das chinesische Mondstationssystem oder separate
Hilfslinien aus `asterisms`. Kulturelle Datierungsangaben begrenzen die gewählte
Berechnungszeit nicht automatisch. Die fünf Kulturdateien werden im Docker-Image
mitgeliefert; bestehende Mounts für Ephemeriden und Sternkatalog bleiben unverändert.

Terrainlinien referenzieren eigene, zeitabhängige Bodenprojektionen der
HIP-Sterne. `clampToGround: true` und `arcType: GEODESIC` legen die Linien
auf das Terrain des empfangenden Cesium-Viewers. Dafür sind weder ein
Terrain-Token in der API noch die spezielle Vorschauseite nötig. Ohne
Terrain-Provider liegen sie auf dem Ellipsoid. Die Figuren wandern mit
der Simulationszeit, nicht mit der Kamerabewegung. Es handelt sich um
geodätisch verbundene projizierte Sterne, nicht um exakte Projektionen
jedes Zwischenpunkts der geraden Himmelslinien. Dynamische Terrainlinien
können je nach Cesium-Version und Zahl der Figuren aufwendiger sein.

Jede Anfrage berechnet genau einen UTC-Kalendertag mit je einer Stunde
Puffer davor und danach (normalerweise 26 Stunden). Für `1979-11-05/gregorian`
reicht die Verfügbarkeit von `1979-11-04T23:00:00Z` bis
`1979-11-06T01:00:00Z`; die Cesium-Uhr startet am gewählten Tag um 00:00 UTC.
Bei `julian` wird zuerst das angegebene Kalenderdatum umgerechnet und dann
derselbe Puffer angewendet. Monats-/Jahreswechsel und Schaltsekunden werden
berücksichtigt. Die separate Aufgangsauswertung bleibt beim ungepufferten Tag.
Standardkalender der POST-API ist aus Kompatibilitätsgründen `julian`;
Download-CLI und Vorschau verwenden ausdrücklich `gregorian`.
`step_seconds`: 60–3600, Standard 300.
Kleinere Schritte verbessern die Interpolation, vergrößern aber die Datei.

Weitere Optionen (GET als Query-Parameter; POST als JSON):

- `include_bodies`: konfigurierte Körper einschließen (Standard `true`).
- `constellation_names`: `null` für alle 88, `[]` für keine oder eine Liste
  lateinischer/englischer Namen bzw. IAU-Kürzel, z. B. `["Orion", "Tau"]`.
- `zodiac_only`: nur die zwölf klassischen Tierkreis-Sternbilder.
- `show_pins`: Pins einschließen (Standard `true`).
- `pin_magnitude_limit`: bei aktiviertem Stern-Pin-Modus erhalten nur Sterne
  heller als dieser Wert Pins (Standard 3.0). Sonne, Mond und Planeten
  erhalten bei `show_pins: true` unabhängig davon Pins.

Tierkreislinien sind golden, andere Sternbildlinien blau. Schlangenträger
(Ophiuchus) bleibt ein normales Sternbild, gehört aber nicht zu den zwölf
klassischen Tierkreiszeichen. Es werden Sternbildfiguren dargestellt, keine
IAU-Grenzen oder astrologischen 30°-Sektoren. Die Verbindungen stammen aus
`modern_st.json`. Gemeinsame Sterne werden nur einmal ausgegeben.

Die bisherigen POST-Routen `/api/v1/astro-positions` und
`/api/v1/constellation-positions` akzeptieren weiterhin `object_type`/
`object_name` bzw. `constellation_name`, liefern nun aber ebenfalls CZML
statt des bisherigen Zwischenformats (**bewusste Änderung des Antwortformats**).
`/api/v1/observer-azimuth` bleibt eine separate JSON-Auswertung.

## Pins, Bezugssystem und Terrain

Alle Positionen sind erdfest (`FIXED`/ITRS). Pins referenzieren denselben
zeitabhängigen Körper wie die Darstellung und einen eigenen Bodenpunkt.
`arcType: NONE` verhindert bei Pins und Himmelslinien, dass Cesium aus der geraden 3D-Verbindung einen
Oberflächenbogen macht. Die Bodenpunkte sind die radialen Schnittpunkte mit
dem WGS84-Ellipsoid, nicht der Erdmittelpunkt. Ein Kameraschwenk verändert
die geografischen Koordinaten nicht. Die tägliche Bewegung bei laufender
Simulationszeit ist dagegen beabsichtigt.

**Ein CZML allein kennt das Terrain des Cesium-Viewers nicht.** Zwischen
Stützzeiten werden kartesische Positionen linear interpoliert; dabei kann
ein reiner CZML-Bodenpunkt geringfügig unter dem Ellipsoid liegen. Die
Vorschauseite projiziert deshalb auch ohne Terrain die interpolierten
Positionen bei jedem Frame wieder auf das Ellipsoid. Für
genaue Terrain-Endpunkte verwendet `viewer.html` die interpolierte Richtung
und fragt mit `sampleTerrainMostDetailed()` die Höhe beim aktiven Provider
zum aktuellen Zeitpunkt ab. Die endgültige Position wird wieder auf die
Terrainoberfläche projiziert. Solange die asynchrone Höhenabfrage läuft,
wird der betreffende Pin ausgeblendet. Für eine stabile, exakte Betrachtung
die Simulationszeit pausieren; schnelle Animation kann zu unterbrochenen
Pins führen. Das Terrain-Modell hat seinerseits eine endliche Auflösung.

Die Körperhöhen sind weiterhin die bewusst schematischen Kuppelhöhen aus
`config.json`, keine realen astronomischen Entfernungen. Sterne der
Sternbildfiguren liegen auf der gemeinsamen 40.000-km-Kuppel.

## Tests

```sh
.venv/bin/python -m unittest test_api -v
```

Die Tests prüfen unter anderem alle 88 Sternbilder, die zwölf Tierkreise,
Linienreferenzen, WGS84-Schnittpunkte, Zeitstempel und HTTP-Antworten.
Browserdarstellung und externe Terrain-Dienste sind nicht Teil dieser Tests.
