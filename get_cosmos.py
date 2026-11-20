"""Download ready-to-use CZML; no intermediate position files or build step."""
import argparse
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="1979-11-05", help="Kalenderdatum YYYY-MM-DD (plus je 1 Stunde Puffer)")
    parser.add_argument("--calendar", choices=["gregorian", "julian"], default="gregorian")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", default="cosmos.czml")
    parser.add_argument("--step", type=int, default=300)
    parser.add_argument("--zodiac-only", action="store_true")
    parser.add_argument("--pin-scope", choices=["bodies", "zodiac", "all"], default="bodies")
    parser.add_argument("--projection", choices=["sky", "ground", "both"], default="both")
    args = parser.parse_args()
    query = urlencode({"step_seconds": args.step, "zodiac_only": str(args.zodiac_only).lower(),
                       "pin_scope": args.pin_scope, "constellation_projection": args.projection})
    request = Request(f"{args.url.rstrip('/')}/api/{args.date}/{args.calendar}?{query}")
    with urlopen(request, timeout=600) as response:
        Path(args.output).write_bytes(response.read())
    print(f"CZML gespeichert: {args.output}")


if __name__ == "__main__":
    main()
