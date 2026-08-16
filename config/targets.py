"""Modular geographic target configuration — Greater Hyderabad & ORR."""
from __future__ import annotations
from typing import Any

REGIONS: dict[str, dict[str, Any]] = {
    "TELANGANA_CORE_ORR": {
        "display_name": "Greater Hyderabad & ORR",
        "bounding_box": {
            "lat_min": 17.1500,
            "lat_max": 17.6500,
            "lon_min": 78.1500,
            "lon_max": 78.7000,
            "step": 0.025,
        },
        "named_localities": {
            # Core & Central
            "Abids": (17.3924, 78.4731),
            "Nampally": (17.3926, 78.4679),
            "Himayatnagar": (17.4015, 78.4862),
            "Somajiguda": (17.4239, 78.4738),
            "Panjagutta": (17.4286, 78.4574),
            "Ameerpet": (17.4375, 78.4482),
            "Begumpet": (17.4399, 78.4663),
            "Secunderabad": (17.4399, 78.4983),
            "Mehdipatnam": (17.3851, 78.4419),
            "Tolichowki": (17.3984, 78.4185),
            "Lakdikapul": (17.4014, 78.4614),
            "Khairatabad": (17.4128, 78.4653),
            "Chikkadpally": (17.4086, 78.4986),
            "Nallakunta": (17.4014, 78.5114),
            "Kachiguda": (17.3897, 78.4914),
            "Koti": (17.3847, 78.4814),

            # West & IT Corridor
            "Banjara Hills": (17.4156, 78.4347),
            "Jubilee Hills": (17.4226, 78.4071),
            "Film Nagar": (17.4186, 78.4014),
            "Madhapur": (17.4483, 78.3915),
            "Hitec City": (17.4435, 78.3772),
            "Kondapur": (17.4702, 78.3534),
            "Gachibowli": (17.4401, 78.3489),
            "Financial District": (17.4194, 78.3427),
            "Nanakramguda": (17.4167, 78.3486),
            "Manikonda": (17.4062, 78.3762),
            "Shaikpet": (17.4069, 78.4072),
            "Raidurg": (17.4347, 78.3814),
            "Kokapet": (17.3814, 78.3314),
            "Gandipet": (17.3514, 78.4014),
            "Tellapur": (17.4686, 78.2814),
            "Narsingi": (17.3850, 78.3580),

            # North & North-West
            "Kukatpally": (17.4948, 78.3996),
            "KPHB Colony": (17.4932, 78.3912),
            "Miyapur": (17.4967, 78.3574),
            "Nizampet": (17.5186, 78.3836),
            "Bachupally": (17.5447, 78.3897),
            "Chanda Nagar": (17.4944, 78.3178),
            "Lingampally": (17.4942, 78.3169),
            "Patancheru": (17.5289, 78.2652),
            "Suchitra": (17.5514, 78.4814),
            "Kompally": (17.5425, 78.4819),
            "Medchal": (17.6314, 78.4814),
            "Alwal": (17.5047, 78.5086),
            "Sainikpuri": (17.4883, 78.5489),
            "Trimulgherry": (17.4814, 78.5114),
            "ECIL": (17.4736, 78.5714),

            # East & South-East
            "Tarnaka": (17.4269, 78.5286),
            "Habsiguda": (17.4125, 78.5431),
            "Uppal": (17.4014, 78.5582),
            "Boduppal": (17.4817, 78.5803),
            "Ghatkesar": (17.4525, 78.6833),
            "Pocharam": (17.4714, 78.7014),
            "Dilsukhnagar": (17.3687, 78.5247),
            "Kothapet": (17.3703, 78.5414),
            "LB Nagar": (17.3457, 78.5522),
            "Vanasthalipuram": (17.3286, 78.5486),
            "Hayathnagar": (17.3214, 78.5814),

            # South & Airport Corridor
            "Charminar": (17.3616, 78.4747),
            "Old City": (17.3700, 78.4800),
            "Falaknuma": (17.3325, 78.4683),
            "Attapur": (17.3528, 78.4289),
            "Rajendranagar": (17.3214, 78.4114),
            "Aramghar": (17.3235, 78.4419),
            "Shamshabad": (17.2403, 78.4294),
        },
    },
    "TELANGANA_WARANGAL": {
        "display_name": "Warangal",
        "bounding_box": {
            "lat_min": 17.8500,
            "lat_max": 18.1500,
            "lon_min": 79.4000,
            "lon_max": 79.7000,
            "step": 0.030,
        },
        "named_localities": {
            "Warangal Fort Area": (18.0000, 79.5833),
            "Hanamkonda": (18.0167, 79.5500),
            "Kazipet": (17.9667, 79.5167),
            "Subedari": (18.0100, 79.5600),
        },
    },
}

ACTIVE_REGION = "TELANGANA_CORE_ORR"
MIN_RATING = 4.0
MIN_REVIEWS = 1000

def get_active_region() -> dict[str, Any]:
    if ACTIVE_REGION not in REGIONS:
        raise ValueError(f"Unknown ACTIVE_REGION: {ACTIVE_REGION}")
    return REGIONS[ACTIVE_REGION]

def get_bounding_box() -> dict[str, float]:
    return get_active_region()["bounding_box"]

def get_named_localities() -> dict[str, tuple[float, float]]:
    return get_active_region()["named_localities"]
