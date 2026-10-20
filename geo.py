"""Distance helpers and the list of nearby towns used to place community reports."""
import math
import re

# Approximate town-center coordinates in the West Bloomfield area (and a few
# farther ones so reports from them are recognised and correctly rejected).
TOWNS = {
    "west bloomfield": (42.568, -83.383),
    "orchard lake": (42.583, -83.359),
    "keego harbor": (42.608, -83.344),
    "sylvan lake": (42.611, -83.328),
    "bloomfield hills": (42.584, -83.245),
    "bloomfield": (42.584, -83.245),
    "birmingham": (42.547, -83.211),
    "farmington hills": (42.485, -83.377),
    "farmington": (42.464, -83.376),
    "novi": (42.481, -83.476),
    "wixom": (42.525, -83.536),
    "walled lake": (42.538, -83.481),
    "commerce": (42.590, -83.488),
    "white lake": (42.651, -83.500),
    "waterford": (42.663, -83.383),
    "pontiac": (42.639, -83.291),
    "auburn hills": (42.688, -83.234),
    "troy": (42.606, -83.150),
    "southfield": (42.473, -83.222),
    "northville": (42.431, -83.483),
    "milford": (42.594, -83.599),
    "clarkston": (42.736, -83.419),
    "highland": (42.638, -83.617),
    "berkley": (42.503, -83.184),
    "beverly hills": (42.524, -83.223),
    "lathrup village": (42.496, -83.223),
    # Farther away - recognised so they get filtered out, not mis-matched
    "royal oak": (42.490, -83.145),
    "livonia": (42.368, -83.353),
    "rochester hills": (42.658, -83.150),
    "rochester": (42.680, -83.134),
    "madison heights": (42.486, -83.105),
    "mh": (42.486, -83.105),
    "lake orion": (42.784, -83.240),
    "south lyon": (42.460, -83.652),
    "canton": (42.309, -83.482),
    "dearborn": (42.322, -83.176),
    "detroit": (42.331, -83.046),
    "sterling heights": (42.580, -83.030),
    "sterling": (42.580, -83.030),
    "utica": (42.626, -83.034),
    "roseville": (42.497, -82.937),
    "warren": (42.493, -83.028),
    "southgate": (42.214, -83.194),
    "taylor": (42.241, -83.270),
    "woodhaven": (42.139, -83.242),
    "ann arbor": (42.281, -83.743),
    "brighton": (42.529, -83.780),
    "lansing": (42.733, -84.556),
    "flint": (43.013, -83.687),
}


def haversine_miles(a, b):
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def find_town(text, home):
    """Return (town, miles) for the first known town mentioned in text, preferring
    the longest name ("farmington hills" over "farmington"). None if no town."""
    low = text.lower()
    hits = []
    for name, coords in TOWNS.items():
        if re.search(r"\b" + re.escape(name) + r"\b", low):
            hits.append((len(name), name, coords))
    if not hits:
        return None
    hits.sort(reverse=True)
    _, name, coords = hits[0]
    return name, haversine_miles(home, coords)
