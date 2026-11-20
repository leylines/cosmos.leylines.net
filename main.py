"""Skyfield positions on a geocentric display dome, served directly as CZML."""
import json
import re
from datetime import date
from pathlib import Path
from typing import Literal

import convertdate
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from skyfield.api import Star, load, wgs84
from skyfield.data import hipparcos
from skyfield.framelib import itrs

BASE = Path(__file__).resolve().parent
config = json.loads((BASE / "config.json").read_text())
constellations = json.loads((BASE / "modern_st.json").read_text())["constellations"]
eph = load(str(BASE / "de422.bsp"))
with (BASE / "hip_main.dat").open("rb") as catalog:
    stars = hipparcos.load_dataframe(catalog)
colors = pd.read_csv(BASE / "hip_main.dat", sep="|", names=hipparcos._COLUMN_NAMES,
                     usecols=["HIP", "B-V", "RAhms", "DEdms"], index_col="HIP")
stars["B-V"] = pd.to_numeric(colors["B-V"], errors="coerce")
# A few multiple systems (notably HIP 55203, Xi UMa) have no decimal
# astrometric solution, but do include a sexagesimal catalogue position.
for hip in stars.index[stars.ra_degrees.isna() | stars.dec_degrees.isna()]:
    raw = colors.loc[hip]
    try:
        h, m, s = map(float, str(raw["RAhms"]).split())
        dec = str(raw["DEdms"]).strip()
        d, dm, ds = map(float, dec.split())
        stars.loc[hip, "ra_hours"] = h + m / 60 + s / 3600
        stars.loc[hip, "ra_degrees"] = stars.loc[hip, "ra_hours"] * 15
        stars.loc[hip, "dec_degrees"] = (-1 if dec.startswith("-") else 1) * (abs(d) + dm / 60 + ds / 3600)
        stars.loc[hip, ["parallax_mas", "ra_mas_per_year", "dec_mas_per_year"]] = 0.0
    except (ValueError, TypeError):
        pass  # An actually unusable catalogue entry is reported when requested.
ts = load.timescale()
earth = eph["earth"]
ZODIAC = {"Ari", "Tau", "Gem", "Cnc", "Leo", "Vir", "Lib", "Sco", "Sgr", "Cap", "Aqr", "Psc"}
app = FastAPI(title="Leylines Astro-CZML API")
app.add_middleware(CORSMiddleware, allow_origins=["https://maps.leylines.net"],
                   allow_methods=["GET", "POST"], allow_headers=["Content-Type"])


class CosmosRequest(BaseModel):
    year: int
    month: int
    day: int
    calendar_type: Literal["julian", "gregorian"] = "julian"
    step_seconds: int = Field(default=300, ge=60, le=3600)
    include_bodies: bool = True
    constellation_names: list[str] | None = None  # None: all; []: none
    zodiac_only: bool = False
    show_pins: bool = True
    pin_magnitude_limit: float = 3.0
    pin_scope: Literal["bodies", "zodiac", "all"] = "bodies"
    constellation_projection: Literal["sky", "ground", "both"] = "both"


class AstroRequest(CosmosRequest):
    object_type: Literal["star", "planet", "satellite"]
    object_name: str


class ConstellationRequest(CosmosRequest):
    constellation_name: str


def calendar_date(req):
    year, month, day = req.year, req.month, req.day
    calendar = convertdate.julian if req.calendar_type == "julian" else convertdate.gregorian
    if not 1 <= month <= 12 or not 1 <= day <= calendar.month_length(year, month):
        raise HTTPException(422, "Ungültiges Kalenderdatum")
    if req.calendar_type == "julian":
        year, month, day = convertdate.gregorian.from_jd(calendar.to_jd(year, month, day))
    try:
        date(year, month, day)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return year, month, day


def time_grid(req, padding_hours=1):
    year, month, day = calendar_date(req)
    # Skyfield normalises hours and days across month/year boundaries and
    # accounts for leap seconds between these UTC endpoints.
    start = ts.utc(year, month, day, -padding_hours)
    end = ts.utc(year, month, day + 1, padding_hours)
    duration = round(float(end.tai - start.tai) * 86400)
    offsets = np.unique(np.append(np.arange(0, duration, req.step_seconds), duration))
    times = ts.tai_jd(start.tai + offsets / 86400)
    return start.utc_iso(), end.utc_iso(), offsets, times


def color_for_star(row):
    bv = row.get("B-V", 0.0)
    if not np.isfinite(bv):
        bv = 0.0
    for limit, rgb in [(-0.4, [155, 176, 255]), (0, [170, 191, 255]),
                       (0.4, [202, 215, 255]), (0.8, [248, 247, 255]),
                       (1.2, [255, 244, 234]), (1.6, [255, 210, 161])]:
        if bv < limit:
            return rgb + [255]
    return [255, 100, 100, 255]


def sampled_position(epoch, offsets, xyz):
    return {"epoch": epoch, "referenceFrame": "FIXED",
            "interpolationAlgorithm": "LINEAR", "interpolationDegree": 1,
            "cartesian": np.column_stack((offsets, xyz.T)).ravel().tolist()}


def line_packet(entity_id, name, references, color, availability, width=1):
    return {"id": entity_id, "name": name, "availability": availability,
            "polyline": {"positions": {"references": references}, "arcType": "NONE",
                         "clampToGround": False, "width": width,
                         "material": {"solidColor": {"color": {"rgba": color}}}}}


def generate_czml(req, only_object=None):
    epoch, end, offsets, times = time_grid(req)
    availability = f"{epoch}/{end}"
    packets = [{"id": "document", "version": "1.0", "name": "Leylines Cosmos",
                "clock": {"interval": availability, "currentTime": ts.utc(*calendar_date(req)).utc_iso(),
                          "multiplier": 30, "range": "LOOP_STOP",
                          "step": "SYSTEM_CLOCK_MULTIPLIER"}}]
    observer = earth.at(times)
    added = set()
    selected = constellations
    if req.constellation_names is not None:
        selected = []
        for requested in req.constellation_names:
            found = [c for c in constellations if requested.casefold() in
                     {c["common_name"]["native"].casefold(), c["common_name"]["english"].casefold(),
                      c["id"].split()[-1].casefold()}]
            if not found:
                raise HTTPException(404, f"Sternbild nicht gefunden: {requested}")
            selected.extend(c for c in found if c not in selected)
    if req.zodiac_only:
        selected = [c for c in selected if c["id"].split()[-1] in ZODIAC]
    zodiac_hips = {hip for c in selected if c["id"].split()[-1] in ZODIAC
                   for path in c["lines"] for hip in path}
    projected_hips = {hip for c in selected for path in c["lines"] for hip in path}

    def add_body(entity_id, name, target, height, color, radius, pin, moving=False, project=False):
        if entity_id in added:
            return
        added.add(entity_id)
        try:
            xyz = observer.observe(target).frame_xyz(itrs).m
        except Exception as exc:
            raise HTTPException(422, f"Ephemeride/Zeitraum nicht verfügbar: {exc}") from exc
        unit = xyz / np.linalg.norm(xyz, axis=0)
        xyz = unit * (6371000.0 + height)
        if not np.isfinite(xyz).all():
            raise HTTPException(422, f"Keine gültige Position für {name}")
        packet = {"id": entity_id, "name": name, "availability": availability,
                  "position": sampled_position(epoch, offsets, xyz),
                  "ellipsoid": {"radii": {"cartesian": [radius] * 3},
                                "material": {"solidColor": {"color": {"rgba": color}}}}}
        if moving:
            packet["path"] = {"width": 1, "leadTime": 0, "trailTime": 86400,
                              "resolution": req.step_seconds,
                              "material": {"solidColor": {"color": {"rgba": color[:3] + [80]}}}}
        packets.append(packet)
        if (req.show_pins and pin) or project:
            # Intersection of the geocentric ray with the WGS84 ellipsoid.
            axes = np.array([6378137.0, 6378137.0, 6356752.314245])[:, None]
            ground = unit / np.sqrt(np.sum((unit / axes) ** 2, axis=0))
            ground_id = entity_id + "_ground"
            packets.append({"id": ground_id, "availability": availability,
                            "properties": {"surfaceBody": entity_id, **({"pinBody": entity_id} if req.show_pins and pin else {})},
                            "position": sampled_position(epoch, offsets, ground)})
        if req.show_pins and pin:
            packets.append(line_packet(entity_id + "_pin", f"Pin {name}",
                                       [entity_id + "#position", ground_id + "#position"],
                                       color[:3] + [150], availability))

    aliases = {v["hip"]: name for name, v in config["star"].items() if "hip" in v}

    def add_star(hip):
        if hip not in stars.index:
            raise HTTPException(422, f"HIP {hip} fehlt im Katalog")
        row = stars.loc[hip]
        mag = float(row["magnitude"])
        add_body(f"hip_{hip}", aliases.get(hip, f"HIP {hip}"), Star.from_dataframe(row),
                 40000000, color_for_star(row), max(80000, 250000 - mag * 50000),
                 mag < req.pin_magnitude_limit and (req.pin_scope == "all" or
                     (req.pin_scope == "zodiac" and hip in zodiac_hips)),
                 project=hip in projected_hips and req.constellation_projection != "sky")

    if req.include_bodies or only_object:
        matched = False
        for category, objects in config.items():
            for name, settings in objects.items():
                if only_object and (category, name.casefold()) != (only_object[0], only_object[1].casefold()):
                    continue
                matched = True
                if "hip" in settings:
                    add_star(settings["hip"])
                else:
                    key = name.lower() + (" barycenter" if category == "planet" else "")
                    radius = 800000 if key == "sun" else 780000 if key == "moon" else 400000
                    add_body(name.lower(), name, eph[key], settings["height"],
                             settings["color"], radius, True, True)
        if only_object and not matched:
            raise HTTPException(404, "Körper nicht in config.json gefunden")

    for constellation in selected:
        abbreviation = constellation["id"].split()[-1]
        zodiac = abbreviation in ZODIAC
        if req.zodiac_only and not zodiac:
            continue
        name = constellation["common_name"]["native"]
        parent = "constellation_" + abbreviation
        packets.append({"id": parent, "name": name,
                        "properties": {"zodiac": zodiac, "abbreviation": abbreviation}})
        for index, path in enumerate(constellation["lines"]):
            for hip in path:
                add_star(hip)
            color = [255, 200, 80, 210] if zodiac else [130, 170, 255, 150]
            if req.constellation_projection in ("sky", "both"):
                packet = line_packet(f"{parent}_{index}", name,
                                     [f"hip_{hip}#position" for hip in path],
                                     color, availability, 2 if zodiac else 1)
                packet["parent"] = parent
                packets.append(packet)
            if req.constellation_projection in ("ground", "both"):
                packet = line_packet(f"{parent}_{index}_ground", f"{name} (Terrain)",
                                     [f"hip_{hip}_ground#position" for hip in path],
                                     color, availability, 3 if zodiac else 2)
                packet["parent"] = parent
                packet["polyline"].update(clampToGround=True, arcType="GEODESIC")
                packets.append(packet)
    return packets


def czml_response(packets):
    return Response(json.dumps(packets, allow_nan=False, separators=(",", ":")),
                    media_type="application/vnd.cesium.czml+json",
                    headers={"Content-Disposition": 'inline; filename="cosmos.czml"'})


@app.post("/api/v1/cosmos.czml")
def cosmos(req: CosmosRequest):
    return czml_response(generate_czml(req))


@app.get("/api/{date}/{calendar_type}")
def cosmos_get(date: str, calendar_type: Literal["julian", "gregorian"],
               step_seconds: int = Query(default=300, ge=60, le=3600),
               include_bodies: bool = True, zodiac_only: bool = False, show_pins: bool = True,
               pin_scope: Literal["bodies", "zodiac", "all"] = "bodies",
               pin_magnitude_limit: float = 3.0,
               constellation_projection: Literal["sky", "ground", "both"] = "both",
               constellation_names: list[str] | None = Query(default=None)):
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", date)
    if not match:
        raise HTTPException(422, "Datum muss das Format YYYY-MM-DD haben")
    values = dict(zip(["year", "month", "day"], map(int, match.groups())))
    req = CosmosRequest(**values, calendar_type=calendar_type, step_seconds=step_seconds,
                        include_bodies=include_bodies, zodiac_only=zodiac_only, show_pins=show_pins,
                        pin_scope=pin_scope, pin_magnitude_limit=pin_magnitude_limit,
                        constellation_projection=constellation_projection,
                        constellation_names=constellation_names)
    return czml_response(generate_czml(req))


@app.post("/api/v1/astro-positions")
def astro(req: AstroRequest):
    return czml_response(generate_czml(req.model_copy(update={"constellation_names": []}),
                                       (req.object_type, req.object_name)))


@app.post("/api/v1/constellation-positions")
def constellation(req: ConstellationRequest):
    return czml_response(generate_czml(req.model_copy(update={
        "include_bodies": False, "constellation_names": [req.constellation_name]})))


@app.get("/")
def viewer():
    return FileResponse(BASE / "viewer.html")


class AzimuthRequest(BaseModel):
    object_name: str
    year: int
    month: int
    day: int
    observer_lat: float = Field(ge=-90, le=90)
    observer_lon: float = Field(ge=-180, le=180)
    calendar_type: Literal["julian", "gregorian"] = "julian"


@app.post("/api/v1/observer-azimuth")
def observer_azimuth(req: AzimuthRequest):
    """Retain the observer endpoint (geometric centre crossing, no refraction)."""
    grid_request = CosmosRequest(year=req.year, month=req.month, day=req.day,
                                calendar_type=req.calendar_type, step_seconds=60)
    epoch, _, offsets, times = time_grid(grid_request, padding_hours=0)
    target = None
    for category, objects in config.items():
        for name, settings in objects.items():
            if name.casefold() == req.object_name.casefold():
                target = (Star.from_dataframe(stars.loc[settings["hip"]]) if "hip" in settings else
                          eph[name.lower() + (" barycenter" if category == "planet" else "")])
    if target is None:
        raise HTTPException(400, "Objekt unbekannt")
    observer = earth + wgs84.latlon(req.observer_lat, req.observer_lon)
    altitude, azimuth, _ = observer.at(times).observe(target).apparent().altaz()
    rises = np.flatnonzero((altitude.degrees[:-1] < 0) & (altitude.degrees[1:] >= 0)) + 1
    index = int(rises[0]) if len(rises) else None
    return {"object": req.object_name, "observer_coordinates": [req.observer_lon, req.observer_lat],
            "gregorian_date": epoch[:10],
            "aufgang_azimut_kompass": float(azimuth.degrees[index]) if index is not None else None,
            "aufgang_uhrzeit_sekunden_seit_mitternacht": int(offsets[index]) if index is not None else None}
