import unittest

import numpy as np
from fastapi.testclient import TestClient

from main import app, CosmosRequest, generate_czml, time_grid


class CosmosTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = dict(year=1979, month=11, day=5,
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
            self.assertEqual(values[-1, 0], 26 * 3600)
            self.assertTrue(np.isfinite(values).all())

    def test_api_returns_czml_and_errors(self):
        response = self.client.post("/api/v1/cosmos.czml", json=self.payload)
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/vnd.cesium.czml+json", response.headers["content-type"])
        self.assertEqual(response.json()[0]["id"], "document")
        for update in [{"month": 13}, {"month": 2, "day": 30}, {"day": 0},
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
        url = "/api/1979-11-05/gregorian?step_seconds=3600"
        response = self.client.get(url, headers={"Origin": "https://maps.leylines.net"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "https://maps.leylines.net")
        self.assertEqual(response.json(), self.packets)
        for path in ["/api/1979-13-05/gregorian", "/api/1979-02-29/gregorian",
                     "/api/invalid/gregorian", url + "&step_seconds=0",
                     url + "&pin_scope=unknown", url + "&constellation_projection=unknown",
                     "/api/1979-11-05/unknown"]:
            self.assertEqual(self.client.get(path).status_code, 422, path)
        # A Julian leap date must not be validated as a Gregorian date.
        response = self.client.get("/api/1900-02-29/julian?constellation_names=Ori")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["clock"]["currentTime"], "1900-03-13T00:00:00Z")

    def test_padded_day_and_clock(self):
        clock = self.packets[0]["clock"]
        self.assertEqual(clock["interval"], "1979-11-04T23:00:00Z/1979-11-06T01:00:00Z")
        self.assertEqual(clock["currentTime"], "1979-11-05T00:00:00Z")
        for packet in self.packets:
            if "availability" in packet:
                self.assertEqual(packet["availability"], clock["interval"])
            if "position" in packet:
                self.assertEqual(packet["position"]["epoch"], "1979-11-04T23:00:00Z")

    def test_padding_across_calendar_boundaries(self):
        cases = [((2026, 1, 1), "2025-12-31T23:00:00Z", "2026-01-02T01:00:00Z"),
                 ((2024, 2, 29), "2024-02-28T23:00:00Z", "2024-03-01T01:00:00Z"),
                 ((2026, 12, 31), "2026-12-30T23:00:00Z", "2027-01-01T01:00:00Z")]
        for (year, month, day), expected_start, expected_end in cases:
            with self.subTest(date=(year, month, day)):
                req = CosmosRequest(year=year, month=month, day=day, calendar_type="gregorian")
                start, end, offsets, _ = time_grid(req)
                self.assertEqual((start, end), (expected_start, expected_end))
                self.assertEqual(offsets[-1], 93600)

    def test_leap_second_and_non_dividing_step(self):
        req = CosmosRequest(year=2016, month=12, day=31, calendar_type="gregorian", step_seconds=3599)
        start, end, offsets, times = time_grid(req)
        self.assertEqual(start, "2016-12-30T23:00:00Z")
        self.assertEqual(end, "2017-01-01T01:00:00Z")
        self.assertEqual(offsets[-1], 93601)
        self.assertTrue(np.all(np.diff(offsets) > 0))
        self.assertEqual(times[-1].utc_iso(), end)

    def test_no_pins_keeps_terrain_projections(self):
        packets = generate_czml(CosmosRequest(**self.payload, show_pins=False))
        self.assertFalse(any(p["id"].endswith("_pin") for p in packets))
        self.assertTrue(any(p.get("polyline", {}).get("clampToGround") for p in packets))

    def test_all_skycultures(self):
        expected = {"modern_st": 88, "egyptian_dendera": 34, "babylonian_mulapin": 58,
                    "navajo": 8, "chinese": 309}
        for culture, count in expected.items():
            with self.subTest(culture=culture):
                response = self.client.get(f"/api/0840-05-05/julian?skyculture={culture}&step_seconds=3600")
                self.assertEqual(response.status_code, 200)
                packets = response.json()
                by_id = {p["id"]: p for p in packets}
                self.assertEqual(len(by_id), len(packets))
                self.assertEqual(packets[0]["properties"]["skyculture"], culture)
                groups = [p for p in packets if "zodiac" in p.get("properties", {})]
                self.assertEqual(len(groups), count)
                self.assertTrue(all(p["name"] for p in groups))
                self.assertEqual(sum(p["properties"]["zodiac"] for p in groups),
                                 12 if culture in ("modern_st", "egyptian_dendera") else 0)
                for packet in packets:
                    if "position" in packet:
                        self.assertTrue(np.isfinite(packet["position"]["cartesian"]).all())
                    if "polyline" in packet:
                        references = packet["polyline"]["positions"]["references"]
                        self.assertGreaterEqual(len(references), 2)
                        self.assertTrue(all(a != b for a, b in zip(references, references[1:])))
                        for reference in references:
                            self.assertIn("position", by_id[reference.split("#")[0]])

    def test_chinese_unsupported_references_break_lines(self):
        from main import culture_constellations
        figures, warnings = culture_constellations("chinese")
        self.assertEqual(len(warnings), 4)
        figure = next(c for c in figures if c["id"] == "CON chinese 090")
        self.assertIn([51232], figure["lines"])
        self.assertIn([56606, 56561, 57363], figure["lines"])
        self.assertFalse(any(51232 in path and 56606 in path for path in figure["lines"]))
        self.assertTrue(all(type(hip) is int for c in figures for path in c["lines"] for hip in path))
        self.assertTrue(any("DSO:NGC2632" in warning for warning in warnings))

    def test_culture_validation_and_name_fallbacks(self):
        url = "/api/0840-05-05/julian"
        for culture in ["missing", "../config", "config.json"]:
            self.assertEqual(self.client.get(url, params={"skyculture": culture}).status_code, 422)
        response = self.client.post("/api/v1/cosmos.czml", json=self.payload | {"skyculture": "missing"})
        self.assertEqual(response.status_code, 422)
        for culture, name in [("egyptian_dendera", "Thigh of Bull"), ("navajo", "Revolving Male")]:
            response = self.client.get(url, params={"skyculture": culture, "constellation_names": name})
            self.assertEqual(response.status_code, 200)
            groups = [p for p in response.json() if "zodiac" in p.get("properties", {})]
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]["name"], name)
        response = self.client.get(url, params={"skyculture": "egyptian_dendera", "zodiac_only": "true"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(sum("zodiac" in p.get("properties", {}) for p in response.json()), 12)
        response = self.client.get(url, params={"skyculture": "chinese", "zodiac_only": "true"})
        self.assertEqual(response.status_code, 422)

    def test_post_culture_selection(self):
        response = self.client.post("/api/v1/constellation-positions", json=self.payload | {
            "skyculture": "egyptian_dendera", "constellation_name": "Ari"})
        self.assertEqual(response.status_code, 200)
        groups = [p for p in response.json() if "zodiac" in p.get("properties", {})]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["name"], "Aries")


if __name__ == "__main__":
    unittest.main()
