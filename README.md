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
von einem CDN; World Terrain benötigt einen eigenen Cesium-ion-Token mit
Zugriff auf das Terrain-Asset. Der Token bleibt im Browser.

Alternativ lokal:

```sh
python3 -m venv .venv
.venv/bin/pip install fastapi uvicorn skyfield convertdate pandas httpx
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

## CZML herunterladen

```sh
python3 get_cosmos.py --start 1979-11-04 --end 1979-11-06 --output cosmos.czml
```

Oder direkt:

```sh
curl --fail-with-body http://localhost:8000/api/v1/cosmos.czml \
  -H 'Content-Type: application/json' \
  -d '{"start_year":1979,"start_month":11,"start_day":5,"end_year":1979,"end_month":11,"end_day":5,"calendar_type":"gregorian"}' \
  -o cosmos.czml
```

### Direkter GET-Aufruf aus dem Globus (empfohlen)

```text
https://cosmos.leylines.net/api/1979-11-04/1979-11-06/gregorian
```

Die Route ist implementiert; DNS, HTTPS und Reverse Proxy für die Subdomain
müssen beim Deployment eingerichtet werden. CORS erlaubt Zugriffe von
`https://maps.leylines.net`. Download-CLI und Vorschau verwenden jetzt GET.
Die bisherigen POST-Routen bleiben für vorhandene Clients erhalten.

Beispiel für CesiumJS:

```js
const cosmos = await Cesium.CzmlDataSource.load(
  'https://cosmos.leylines.net/api/1979-11-04/1979-11-06/gregorian'
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

Terrainlinien referenzieren eigene, zeitabhängige Bodenprojektionen der
HIP-Sterne. `clampToGround: true` und `arcType: GEODESIC` legen die Linien
auf das Terrain des empfangenden Cesium-Viewers. Dafür sind weder ein
Terrain-Token in der API noch die spezielle Vorschauseite nötig. Ohne
Terrain-Provider liegen sie auf dem Ellipsoid. Die Figuren wandern mit
der Simulationszeit, nicht mit der Kamerabewegung. Es handelt sich um
geodätisch verbundene projizierte Sterne, nicht um exakte Projektionen
jedes Zwischenpunkts der geraden Himmelslinien. Dynamische Terrainlinien
können je nach Cesium-Version und Zahl der Figuren aufwendiger sein.

Der Endtag ist inklusive. Standardkalender der API ist aus Kompatibilitätsgründen
`julian`; Download-CLI und Vorschau verwenden ausdrücklich `gregorian`.
Maximal sieben Tage pro Anfrage; `step_seconds`: 60–3600, Standard 300.
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
