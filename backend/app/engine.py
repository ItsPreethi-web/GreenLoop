"""GreenLoop's deterministic software-only demo data and carbon calculations."""

from __future__ import annotations

import math
import random
from datetime import date, datetime, timezone
from typing import Any

GRID_FACTOR = 0.71  # kg CO2e / kWh; editable project baseline
PUMP_KWH_PER_KL = 0.45
CATEGORIES = ("organic", "paper", "plastic", "glass", "metal")

FACTORS: dict[str, dict[str, Any]] = {
    "organic": {"name": "Organic", "mixed": 0.58, "segregated": 0.10, "bin": "Wet waste, compost"},
    "paper": {"name": "Paper", "mixed": 0.45, "segregated": -0.70, "bin": "Dry waste, paper"},
    "plastic": {"name": "Plastic", "mixed": 1.00, "segregated": -0.60, "bin": "Dry waste, plastic"},
    "glass": {"name": "Glass", "mixed": 0.02, "segregated": -0.30, "bin": "Dry waste, glass"},
    "metal": {"name": "Metal", "mixed": 0.02, "segregated": -2.00, "bin": "Dry waste, metal"},
}


def configure_factors(grid: float, pump: float, waste: dict[str, dict[str, float]] | None = None) -> None:
    """Update process-wide factors from the project's editable database values."""
    global GRID_FACTOR, PUMP_KWH_PER_KL
    GRID_FACTOR = float(grid)
    PUMP_KWH_PER_KL = float(pump)
    if waste:
        for category in CATEGORIES:
            if category in waste:
                FACTORS[category]["mixed"] = float(waste[category]["mixed"])
                FACTORS[category]["segregated"] = float(waste[category]["segregated"])


def hourly_series(blocks: list[dict[str, Any]], now: datetime | None = None) -> list[dict[str, float | bool]]:
    now = now or datetime.now(timezone.utc)
    hour_now = now.hour + now.minute / 60 + now.second / 3600
    points = []
    for hour in range(now.hour):
        points.append({
            "hour": hour + .5,
            "grid_load_kw": sum(_load_kw(block, 0, hour) for block in blocks),
            "solar_generation_kw": sum(_solar_kw(block, 0, hour) for block in blocks),
            "now": False,
        })
    points.append({
        "hour": hour_now,
        "grid_load_kw": sum(simulated_load(block, now)["grid_load_kw"] for block in blocks),
        "solar_generation_kw": sum(simulated_load(block, now)["solar_generation_kw"] for block in blocks),
        "now": True,
    })
    return points

BLOCKS: list[dict[str, Any]] = [
    {"id": "ha", "name": "Hostel A", "kind": "hostel", "people": 380, "peak_kw": 95, "solar_kwp": 50, "water_l_person_day": 135, "waste_kg_person_day": .42, "segregation": .35, "seed": 11, "ranked": True, "starting_points": 1240},
    {"id": "hb", "name": "Hostel B", "kind": "hostel", "people": 360, "peak_kw": 88, "solar_kwp": 30, "water_l_person_day": 135, "waste_kg_person_day": .40, "segregation": .50, "seed": 23, "ranked": True, "starting_points": 1385},
    {"id": "hc", "name": "Hostel C", "kind": "hostel", "people": 300, "peak_kw": 80, "solar_kwp": 0, "water_l_person_day": 135, "waste_kg_person_day": .41, "segregation": .25, "seed": 37, "ranked": True, "starting_points": 910},
    {"id": "ap", "name": "Apartments D", "kind": "apartment", "people": 210, "peak_kw": 58, "solar_kwp": 20, "water_l_person_day": 150, "waste_kg_person_day": .50, "segregation": .40, "seed": 41, "ranked": True, "starting_points": 1090},
    {"id": "sq", "name": "Staff Quarters", "kind": "apartment", "people": 120, "peak_kw": 30, "solar_kwp": 10, "water_l_person_day": 150, "waste_kg_person_day": .45, "segregation": .30, "seed": 53, "ranked": True, "starting_points": 760},
    {"id": "ac", "name": "Academic Block", "kind": "academic", "people": 900, "peak_kw": 260, "solar_kwp": 150, "water_l_person_day": 25, "waste_kg_person_day": .20, "segregation": .45, "seed": 67, "ranked": False, "starting_points": 0},
]

MIX = {
    "residential": {"organic": .46, "paper": .20, "plastic": .20, "glass": .08, "metal": .06},
    "academic": {"organic": .30, "paper": .38, "plastic": .22, "glass": .05, "metal": .05},
}


def _rng(seed: int) -> random.Random:
    return random.Random(seed)


def _profile(kind: str, hour: float) -> float:
    def gaussian(center: float, width: float) -> float:
        return math.exp(-0.5 * ((hour - center) / width) ** 2)

    if kind == "hostel":
        return .30 + .28 * gaussian(7.5, 1.4) + .18 * gaussian(13, 2.5) + .70 * gaussian(20.5, 2.4)
    if kind == "apartment":
        return .28 + .35 * gaussian(7, 1.3) + .72 * gaussian(20, 2.3) + .12 * gaussian(13, 3)
    return .16 + .84 * gaussian(12.5, 3.4)


def _load_kw(block: dict[str, Any], day_index: int, hour: int) -> float:
    rng = _rng(block["seed"] * 7919 + day_index * 131 + hour * 17 + 3)
    noise = rng.uniform(-1, 1)
    daily_rng = _rng(block["seed"] * 7919 + day_index * 131 + 99 * 17 + 3)
    daily_noise = daily_rng.uniform(-1, 1)
    return block["peak_kw"] * _profile(block["kind"], hour + .5) * (1 + .05 * noise) * (1 + .04 * daily_noise)


def _solar_kw(block: dict[str, Any], day_index: int, hour: int) -> float:
    if not block["solar_kwp"]:
        return 0.0
    daylight = math.sin(math.pi * (hour + .5 - 6) / 12)
    if daylight <= 0:
        return 0.0
    cloud_rng = _rng(day_index * 53 + 5)
    cloud = .62 + .38 * cloud_rng.random()
    shade_rng = _rng(block["seed"] * 7919 + day_index * 131 + (hour + 40) * 17 + 3)
    return block["solar_kwp"] * .78 * daylight**1.2 * cloud * (1 + .04 * shade_rng.uniform(-1, 1))


def _daily_waste(block: dict[str, Any], day_index: int) -> dict[str, float]:
    noise = _rng(block["seed"] * 7919 + day_index * 131 + 88 * 17 + 3).uniform(-1, 1)
    total = block["people"] * block["waste_kg_person_day"] * (1 + .08 * noise)
    mix = MIX["academic" if block["kind"] == "academic" else "residential"]
    return {category: total * mix[category] for category in CATEGORIES}


def _water_kl(block: dict[str, Any], day_index: int) -> float:
    noise = _rng(block["seed"] * 7919 + day_index * 131 + 77 * 17 + 3).uniform(-1, 1)
    return block["people"] * block["water_l_person_day"] / 1000 * (1 + .06 * noise)


def block_day(block: dict[str, Any], day_index: int, up_to_hour: float = 24) -> dict[str, Any]:
    fraction = min(1.0, max(0.0, up_to_hour / 24))
    electricity = solar = 0.0
    for hour in range(24):
        weight = min(1.0, max(0.0, up_to_hour - hour))
        if weight <= 0:
            break
        electricity += _load_kw(block, day_index, hour) * weight
        solar += _solar_kw(block, day_index, hour) * weight
    categories = {category: kg * fraction for category, kg in _daily_waste(block, day_index).items()}
    waste_kg = sum(categories.values())
    waste_co2 = sum(
        categories[category]
        * (FACTORS[category]["mixed"] * (1 - block["segregation"]) + FACTORS[category]["segregated"] * block["segregation"])
        for category in CATEGORIES
    )
    water = _water_kl(block, day_index) * fraction
    kg_electricity = electricity * GRID_FACTOR
    kg_water = water * PUMP_KWH_PER_KL * GRID_FACTOR
    kg_solar = solar * GRID_FACTOR
    return {
        "electricity_kwh": electricity, "solar_kwh": solar, "water_kl": water,
        "waste_kg": waste_kg, "waste_categories_kg": categories,
        "kg_electricity": kg_electricity, "kg_waste": waste_co2, "kg_water": kg_water,
        "kg_solar_avoided": kg_solar,
        "kg_gross": kg_electricity + waste_co2 + kg_water,
        "kg_net": kg_electricity + waste_co2 + kg_water - kg_solar,
    }


def _avg_day(block: dict[str, Any]) -> dict[str, Any]:
    days = [block_day(block, day, 24) for day in range(1, 8)]
    avg = {"electricity_kwh": 0.0, "solar_kwh": 0.0, "water_kl": 0.0, "kg_net": 0.0}
    categories = {c: 0.0 for c in CATEGORIES}
    for item in days:
        for key in avg:
            avg[key] += item[key] / 7
        for category in CATEGORIES:
            categories[category] += item["waste_categories_kg"][category] / 7
    avg["waste_categories_kg"] = categories
    return avg


ACTIONS: list[dict[str, Any]] = [
    {"id": "lights", "name": "Put corridor and common-area lights on timers", "effort": "Easy", "why": "Occupancy sensors or timers cut lighting left on in empty corridors.", "kind": "lighting"},
    {"id": "ac", "name": "Raise AC setpoints from 24 to 26 °C", "effort": "Easy", "why": "A modest setpoint change can reduce cooling energy.", "kind": "cooling"},
    {"id": "idle", "name": "Switch off idle PCs and projectors after hours", "effort": "Easy", "why": "Lab machines and projectors draw power when left on standby.", "kind": "it"},
    {"id": "geyser", "name": "Put geysers and water heaters on timers", "effort": "Easy", "why": "Scheduling hot water production avoids heating it when it is not needed.", "kind": "heating"},
    {"id": "leaks", "name": "Fix leaks and fit tap aerators", "effort": "Easy", "why": "Reduces water use and the energy used to pump it.", "kind": "water"},
    {"id": "segregate", "name": "Run a waste segregation drive", "effort": "Medium", "why": "Composting wet waste and recycling dry waste reduce disposal emissions.", "kind": "waste"},
    {"id": "solar", "name": "Add 10 kWp of rooftop solar", "effort": "Capex", "why": "Additional rooftop solar reduces grid electricity demand.", "kind": "solar"},
]


def action_saving(action: dict[str, Any], block: dict[str, Any]) -> dict[str, float] | None:
    kind = action["kind"]
    if kind == "it" and block["kind"] != "academic":
        return None
    if kind == "heating" and block["kind"] == "academic":
        return None
    avg = _avg_day(block)
    weekly_electricity = avg["electricity_kwh"] * 7
    weekly_water = avg["water_kl"] * 7
    if kind == "lighting":
        share = {"hostel": .18, "apartment": .15, "academic": .20}[block["kind"]]
        kwh = weekly_electricity * share * .35
        kg = kwh * GRID_FACTOR
    elif kind == "cooling":
        share = {"hostel": .10, "apartment": .22, "academic": .38}[block["kind"]]
        kwh = weekly_electricity * share * .10
        kg = kwh * GRID_FACTOR
    elif kind == "it":
        kwh = weekly_electricity * .15 * .40
        kg = kwh * GRID_FACTOR
    elif kind == "heating":
        share = .18 if block["kind"] == "hostel" else .12
        kwh = weekly_electricity * share * .30
        kg = kwh * GRID_FACTOR
    elif kind == "water":
        kl = weekly_water * .12
        kwh = kl * PUMP_KWH_PER_KL
        kg = kwh * GRID_FACTOR
        return {"kg_co2e_week": kg, "kwh_week": kwh, "water_kl_week": kl}
    elif kind == "waste":
        delta = min(.30, .95 - block["segregation"])
        kg = sum(avg["waste_categories_kg"][c] * 7 * delta * (FACTORS[c]["mixed"] - FACTORS[c]["segregated"]) for c in CATEGORIES)
        kwh = 0.0
    else:  # additional 10 kWp solar option
        kwh = 10 * 4.3 * 7
        kg = kwh * GRID_FACTOR
    return {"kg_co2e_week": max(0.0, kg), "kwh_week": kwh, "water_kl_week": 0.0}


def simulated_load(block: dict[str, Any], now: datetime | None = None) -> dict[str, float]:
    now = now or datetime.now(timezone.utc)
    hour = now.hour
    stamp = now.strftime("%Y-%m-%d-%H")
    jitter = _rng(block["seed"] + sum(map(ord, stamp))).uniform(-.03, .03)
    return {
        "grid_load_kw": max(0.0, _load_kw(block, 0, hour) * (1 + jitter)),
        "solar_generation_kw": _solar_kw(block, 0, hour),
    }


def totals(blocks: list[dict[str, Any]], up_to_hour: float = 24) -> dict[str, Any]:
    result: dict[str, Any] = {
        "electricity_kwh": 0.0, "solar_kwh": 0.0, "water_kl": 0.0, "waste_kg": 0.0,
        "kg_electricity": 0.0, "kg_waste": 0.0, "kg_water": 0.0, "kg_solar_avoided": 0.0,
        "kg_gross": 0.0, "kg_net": 0.0,
    }
    for block in blocks:
        item = block_day(block, 0, up_to_hour)
        for key in result:
            result[key] += item[key]
    return result


def history(blocks: list[dict[str, Any]], now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    rows = []
    for offset in range(6, -1, -1):
        day = date.fromordinal(now.date().toordinal() - offset)
        index = -offset
        item = totals(blocks, (now.hour + now.minute / 60) if offset == 0 else 24)
        if offset:
            item = {key: sum(block_day(b, index, 24)[key] for b in blocks) for key in item}
        rows.append({"date": day.isoformat(), "label": "Today" if not offset else day.strftime("%a"), **item})
    return rows

