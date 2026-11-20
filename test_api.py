import unittest

import numpy as np
from fastapi.testclient import TestClient

from main import app, CosmosRequest, generate_czml


class CosmosTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = dict(start_year=1979, start_month=11, start_day=5,
                           end_year=1979, end_month=11, end_day=5,
                           calendar_type="gregorian", step_seconds=3600)
        cls.packets = generate_czml(CosmosRequest(**cls.payload))
        cls.by_id = {p["id"]: p for p in cls.packets}
        cls.client = TestClient(app)

    def test_all_constellations_and_zodiac(self):
        groups = [p for p in self.packets if "zodiac" in p.get("properties", {})]
        self.assertEqual(len(groups), 88)
        self.assertEqual(sum(p["properties"]["zodiac"] for p in groups), 12)
        self.assertEqual(len(self.by_id), len(self.packets))
        self.assertIn("hip_55203", self.by_id)

    def test_references_and_straight_lines(self):
        for packet in self.packets:
            if "polyline" not in packet:
                continue
            line = packet["polyline"]
            self.assertEqual(line["arcType"], "GEODESIC" if line["clampToGround"] else "NONE")
            for reference in line["positions"]["references"]:
                self.assertIn("position", self.by_id[reference.split("#")[0]])

    def test_pin_samples_intersect_wgs84(self):
        axes = np.array([6378137., 6378137., 6356752.314245])
        for packet in self.packets:
            if "surfaceBody" not in packet.get("properties", {}):
                continue
            ground = np.array(packet["position"]["cartesian"]).reshape(-1, 4)[:, 1:]
            body_id = packet["properties"]["surfaceBody"]
            body = np.array(self.by_id[body_id]["position"]["cartesian"]).reshape(-1, 4)[:, 1:]
            np.testing.assert_allclose(np.sum((ground / axes) ** 2, axis=1), 1, atol=1e-12)
            np.testing.assert_allclose(ground / np.linalg.norm(ground, axis=1)[:, None],
                                       body / np.linalg.norm(body, axis=1)[:, None], atol=1e-12)

    def test_sample_times_include_actual_end(self):
        for packet in self.packets:
            if "position" not in packet:
                continue
            position = packet["position"]
            values = np.array(position["cartesian"]).reshape(-1, 4)
            self.assertEqual(position["referenceFrame"], "FIXED")
            self.assertEqual(values[0, 0], 0)
            self.assertEqual(values[-1, 0], 86400)
            self.assertTrue(np.isfinite(values).all())

    def test_api_returns_czml_and_errors(self):
        response = self.client.post("/api/v1/cosmos.czml", json=self.payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/vnd.cesium.czml+json", response.headers["content-type"])
        self.assertEqual(response.json()[0]["id"], "document")
        for update in [{"start_month": 13}, {"end_day": 4}, {"end_day": 20},
                       {"calendar_type": "unknown"}, {"step_seconds": 0}]:
            with self.subTest(update=update):
                self.assertEqual(self.client.post("/api/v1/cosmos.czml",
                                                   json=self.payload | update).status_code, 422)
        self.assertEqual(self.client.post("/api/v1/cosmos.czml", json=self.payload |
                                         {"constellation_names": ["missing"]}).status_code, 404)

    def test_legacy_routes_now_return_czml(self):
        for route, fields in [("astro-positions", {"object_type": "star", "object_name": "Sun"}),
                              ("constellation-positions", {"constellation_name": "Orion"})]:
            response = self.client.post("/api/v1/" + route, json=self.payload | fields)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()[0]["id"], "document")

    def test_calendar_conversion(self):
        req = CosmosRequest(**(self.payload | {"calendar_type": "julian", "include_bodies": False,
                                               "constellation_names": []}))
        self.assertEqual(generate_czml(req)[0]["clock"]["currentTime"], "1979-11-18T00:00:00Z")

    def test_zodiac_filter(self):
        packets = generate_czml(CosmosRequest(**(self.payload | {"zodiac_only": True})))
        groups = [p for p in packets if "zodiac" in p.get("properties", {})]
        self.assertEqual(len(groups), 12)
        self.assertTrue(all(p["properties"]["zodiac"] for p in groups))

    def test_observer_endpoint(self):
        response = self.client.post("/api/v1/observer-azimuth", json={
            "object_name": "Sun", "year": 1979, "month": 11, "day": 5,
            "calendar_type": "gregorian", "observer_lat": 47.126, "observer_lon": 8.751})
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.json()["aufgang_azimut_kompass"])

    def test_default_pins_are_only_solar_system(self):
        pins = {p["id"] for p in self.packets if p["id"].endswith("_pin")}
        self.assertEqual(pins, {"sun_pin", "moon_pin", "venus_pin", "mars_pin"})

    def test_zodiac_pins_exclude_other_stars(self):
        from main import constellations, ZODIAC
        zodiac_hips = {hip for c in constellations if c["id"].split()[-1] in ZODIAC
                       for path in c["lines"] for hip in path}
        packets = generate_czml(CosmosRequest(**self.payload, pin_scope="zodiac"))
        star_pins = [p for p in packets if p["id"].startswith("hip_") and p["id"].endswith("_pin")]
        self.assertTrue(star_pins)
        self.assertTrue(all(int(p["id"].split("_")[1]) in zodiac_hips for p in star_pins))

    def test_projection_modes(self):
        for mode in ["sky", "ground", "both"]:
            packets = generate_czml(CosmosRequest(**self.payload, constellation_names=["Ori"],
                                                 constellation_projection=mode))
            lines = [p["polyline"] for p in packets if p.get("parent") == "constellation_Ori"]
            self.assertTrue(lines)
            self.assertEqual(any(p["clampToGround"] for p in lines), mode != "sky")
            self.assertEqual(any(not p["clampToGround"] for p in lines), mode != "ground")

    def test_get_route_cors_and_validation(self):
        url = "/api/1979-11-05/1979-11-05/gregorian?step_seconds=3600"
        response = self.client.get(url, headers={"Origin": "https://maps.leylines.net"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "https://maps.leylines.net")
        self.assertEqual(response.json(), self.packets)
        for path in ["/api/1979-13-05/1979-11-05/gregorian",
                     "/api/invalid/1979-11-05/gregorian", url + "&step_seconds=0",
                     url + "&pin_scope=unknown", url + "&constellation_projection=unknown",
                     "/api/1979-11-05/1979-11-05/unknown"]:
            self.assertEqual(self.client.get(path).status_code, 422, path)
        # A Julian leap date must not be validated as a Gregorian date.
        response = self.client.get("/api/1900-02-29/1900-02-29/julian?constellation_names=Ori")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["clock"]["currentTime"], "1900-03-13T00:00:00Z")

    def test_no_pins_keeps_terrain_projections(self):
        packets = generate_czml(CosmosRequest(**self.payload, show_pins=False))
        self.assertFalse(any(p["id"].endswith("_pin") for p in packets))
        self.assertTrue(any(p.get("polyline", {}).get("clampToGround") for p in packets))


if __name__ == "__main__":
    unittest.main()
