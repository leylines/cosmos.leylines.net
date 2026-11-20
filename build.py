import json
import os
from datetime import datetime, timedelta

def load_astro_json(filename):
    with open(filename, 'r') as f:
        return json.load(f)

def generate_nadel_linie(object_id, name, availability, epoch, cartesian_waypoints, color_rgba, category):
    """Generiert die Stecknadeln exakt nach der funktionierenden Intervall-Spezifikation."""
    base_time = datetime.strptime(epoch, "%Y-%m-%dT%H:%M:%SZ")
    positions_intervals = []

    for i in range(0, len(cartesian_waypoints), 4):
        sekunden_seit_start = cartesian_waypoints[i]
        x = cartesian_waypoints[i+1]
        y = cartesian_waypoints[i+2]
        z = cartesian_waypoints[i+3]
        
        start_interval = base_time + timedelta(seconds=sekunden_seit_start)
        end_interval = start_interval + timedelta(seconds=60)
        
        positions_intervals.append({
            "interval": f"{start_interval.strftime('%Y-%m-%dT%H:%M:%SZ')}/{end_interval.strftime('%Y-%m-%dT%H:%M:%SZ')}",
            "cartesian": [x, y, z, 0.0, 0.0, 0.0] 
        })

    return {
        "id": f"{object_id}_nadel",
        "name": f"Stecknadel {name}",
        "availability": availability,
        "polyline": {
            "positions": positions_intervals,
            "width": 0.5,
            "material": { "solidColor": { "color": { "rgba": color_rgba } } },
            "followSurface": False
        }
    }

def build_universe_czml(config, output_file):
    """
    json_files_dict: Ein Dictionary mit Dateipfad und den Farb-RGBA-Werten.
    Beispiel: {"out_sun.json":, "out_venus.json":}
    """
    czml = []
    header_initialized = False

    for category, objects in config.items():
        for name, values in objects.items():
            filename = f"out_{name}.json"
            if not os.path.exists(filename):
                print(f"Warnung: {filename} nicht gefunden. Überspringe.")
                continue
            
            data = load_astro_json(filename)
            obj_name = data["object"].upper()
            epoch = data["epoch_iso_start"]
            end_time = data["epoch_iso_end"]
            availability = f"{epoch}/{end_time}"
            waypoints = data["waypoints"]
            color = data["star_color"] if len(data["star_color"]) > 0 else config[category][name]['color']

            # 1. Den globalen Zeit-Header NUR EINMAL beim ersten Element hinzufügen
            if not header_initialized:
                czml.append({
                    "id": "document",
                    "version": "1.0",
                    "clock": {
                        "interval": availability,
                        "currentTime": epoch, # Direkt zum Finsternis-Showdown springen
                        "multiplier": 30,
                        "range": "LOOP_STOP",
                        "step": "SYSTEM_CLOCK_MULTIPLIER"
                    }
                })
                header_initialized = True

            # 2. Den 3D-Körper (Ellipsoid) hinzufügen
            # Dynamische Radien-Größe basierend auf der Kuppelhöhe (Sterne kleiner, Sonne riesig)
            kuppel_hoehe = values['height']
            if data["star_radius"] > 0:
                radius = data["star_radius"]
            elif kuppel_hoehe >= 40000000.0:  # Sterne
                radius = 200000.0
            elif kuppel_hoehe >= 30000000.0: # Sonne
                radius = 800000.0
            elif kuppel_hoehe >= 25000000.0: # Planeten
                radius = 400000.0
            else:                            # Mond
                radius = 780000.0

            path_data = {
                # HIER KOMMT DAS NEUE ORBIT-FEATURE:
                "path": {
                    "show": True,
                    "width": 1,                     # Schön feine Linie, um die Karte nicht zu überladen
                    "material": {
                        "solidColor": {
                            "color": { 
                                # Wir nehmen die Objektfarbe, machen sie aber stark transparent (alpha=80)
                                "rgba": [color, color, color, 80]
                                #"rgba": [color[0], color[1], color[2], 80] 
                            }
                        }
                    },
                    #"leadTime": 86400,              # Zeigt die Bahn 24 Stunden in die Zukunft an
                    #"trailTime": 86400,             # Zeigt die Bahn 24 Stunden in die Vergangenheit an
                    "leadTime": 0,              # Zeigt die Bahn 24 Stunden in die Zukunft an
                    "trailTime": 86400,             # Zeigt die Bahn 24 Stunden in die Vergangenheit an
                    "resolution": 60                # Interpolation alle 60 Sekunden (pfeilschnell)
                }
            } if (category == "satellite" or category == "planet" or name == "Sun") else {}
            czml.append({
                "id": f"{obj_name.lower()}_3d",
                "name": f"{data['object'].capitalize()} (Simulation)",
                "availability": availability,
                "position": {
                    "epoch": epoch,
                    "cartesian": waypoints,
                    "interpolationAlgorithm": "HERMITE",
                    "interpolationDegree": 2
                },
                "ellipsoid": {
                    "radii": { "cartesian": [radius, radius, radius] },
                    "material": { "solidColor": { "color": { "rgba": color } } },
                    "fill": True
                },
                **path_data 
            })

            # 3. Die dazugehörige Stecknadel-Linie generieren (Teiltransparent, alpha=150)
            line_color = [color[0], color[1], color[2], 150]
            if data["show_pin"]:
                czml.append(generate_nadel_linie(obj_name.lower(), data['object'].capitalize(), availability, epoch, waypoints, line_color, category))

    # Alles wegschreiben
    with open(output_file, 'w') as f:
        json.dump(czml, f, indent=2)
    print(f"Megalomanisches Universum-CZML erfolgreich generiert: {output_file}")

# Konfiguration deiner Himmelskörper und deren Farben
if __name__ == "__main__":

   try:
      with open("config.json", "r") as file:
         config = json.load(file)

   except json.JSONDecodeError:
      print("Error: Invalid JSON format in the file.")

   build_universe_czml(config, "1979-11-5.czml")
