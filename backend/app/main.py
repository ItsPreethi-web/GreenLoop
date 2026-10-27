from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from . import engine
from .engine import ACTIONS, BLOCKS, FACTORS, action_saving, block_day, history, hourly_series, simulated_load, totals
from .store import DemoStore, make_store


class Settings(BaseSettings):
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    cors_origins: str = "http://localhost:5500,http://127.0.0.1:5500,http://localhost:8000"
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
store, storage_mode = make_store(settings.supabase_url, settings.supabase_service_role_key)

app = FastAPI(title="GreenLoop API", version="1.0.0", description="Campus carbon dashboard API using software-generated demo readings by default.")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

BLOCK_BY_ID = {block["id"]: block for block in BLOCKS}
ACTION_BY_ID = {action["id"]: action for action in ACTIONS}
ITEMS = {
    "bottle": {"label": "Water bottle", "category": "plastic", "probabilities": {"plastic": .93, "glass": .04, "metal": .01, "paper": .01, "organic": .01}},
    "paper": {"label": "Newspaper", "category": "paper", "probabilities": {"paper": .96, "plastic": .02, "organic": .01, "glass": .005, "metal": .005}},
    "jar": {"label": "Glass jar", "category": "glass", "probabilities": {"glass": .88, "plastic": .09, "metal": .01, "paper": .01, "organic": .01}},
    "can": {"label": "Tin can", "category": "metal", "probabilities": {"metal": .90, "plastic": .06, "glass": .02, "paper": .01, "organic": .01}},
    "peel": {"label": "Banana peel", "category": "organic", "probabilities": {"organic": .94, "paper": .03, "plastic": .02, "glass": .005, "metal": .005}},
}


class ActionRequest(BaseModel):
    scope: str = "all"


class WasteClassificationRequest(BaseModel):
    sample_item: str = Field(min_length=1, max_length=32)
    weight_kg: float = Field(default=.5, gt=0, le=50)


class WasteLogRequest(BaseModel):
    sample_item: str = Field(min_length=1, max_length=32)
    block_id: str
    weight_kg: float = Field(gt=0, le=50)


class FactorUpdateRequest(BaseModel):
    grid_kg_co2e_per_kwh: float = Field(gt=0.1, le=1.5)
    pump_kwh_per_kl: float = Field(gt=0.05, le=3)


def scoped_blocks(scope: str) -> list[dict[str, Any]]:
    if scope == "all":
        return BLOCKS
    if scope not in BLOCK_BY_ID:
        raise HTTPException(status_code=404, detail="Unknown campus block.")
    return [BLOCK_BY_ID[scope]]


def current_state() -> dict[str, Any]:
    try:
        return store.state()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Could not read GreenLoop data from {storage_mode}: {exc}") from exc


def current_factors() -> dict[str, Any]:
    try:
        values = store.factor_values()
        engine.configure_factors(values["grid_kg_co2e_per_kwh"], values["pump_kwh_per_kl"], values["waste"])
        return values
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Could not read emission factors from {storage_mode}: {exc}") from exc


def saved_for_block(block_id: str, state: dict[str, Any]) -> float:
    saved = 0.0
    adopted = {(row["block_id"], row["action_id"]) for row in state["adopted"]}
    for action in ACTIONS:
        if (block_id, action["id"]) in adopted:
            calc = action_saving(action, BLOCK_BY_ID[block_id])
            if calc:
                saved += calc["kg_co2e_week"] / 7
    return saved


@app.get("/", include_in_schema=False)
def frontend() -> FileResponse:
    path = Path(__file__).resolve().parents[2] / "greenloop.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Frontend file was not found.")
    return FileResponse(path)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "storage": storage_mode, "readings": "software-simulated"}


@app.get("/api/blocks")
def get_blocks() -> list[dict[str, Any]]:
    return [{key: value for key, value in block.items() if key not in {"seed", "starting_points"}} for block in BLOCKS]


@app.get("/api/state")
def get_state() -> dict[str, Any]:
    return current_state()


@app.get("/api/dashboard")
def dashboard(scope: str = "all", utc_offset_minutes: int = 0) -> dict[str, Any]:
    current_factors()
    blocks = scoped_blocks(scope)
    state = current_state()
    now = datetime.now(timezone.utc).astimezone(timezone(timedelta(minutes=-utc_offset_minutes)))
    elapsed = now.hour + now.minute / 60 + now.second / 3600
    previous = {key: sum(block_day(block, 1, elapsed)[key] for block in blocks) for key in totals(blocks, elapsed)}
    today = {key: sum(block_day(block, 0, elapsed)[key] for block in blocks) for key in previous}
    today["comparison_kg_net"] = previous["kg_net"]
    return {
        "scope": scope,
        "generated_at": now.isoformat(),
        "reading_mode": "software-simulated",
        "totals": today,
        "blocks": [{"id": block["id"], "name": block["name"], "people": block["people"], **simulated_load(block, now)} for block in BLOCKS],
        "hourly": hourly_series(blocks, now),
        "history": history(blocks, now),
        "factors": {"grid_kg_co2e_per_kwh": engine.GRID_FACTOR, "pump_kwh_per_kl": engine.PUMP_KWH_PER_KL},
        "adopted_savings_kg_per_day": sum(saved_for_block(block["id"], state) for block in blocks),
    }


@app.get("/api/actions")
def get_actions(scope: str = "all") -> list[dict[str, Any]]:
    current_factors()
    blocks = scoped_blocks(scope)
    state = current_state()
    adopted = {(row["block_id"], row["action_id"]) for row in state["adopted"]}
    result = []
    for action in ACTIONS:
        per_block = []
        for block in blocks:
            saving = action_saving(action, block)
            if saving:
                per_block.append({"block_id": block["id"], **saving, "adopted": (block["id"], action["id"]) in adopted})
        if per_block:
            result.append({**action, "kg_co2e_week": sum(row["kg_co2e_week"] for row in per_block), "kwh_week": sum(row["kwh_week"] for row in per_block), "water_kl_week": sum(row["water_kl_week"] for row in per_block), "adopted": all(row["adopted"] for row in per_block), "blocks": per_block})
    return sorted(result, key=lambda row: row["kg_co2e_week"], reverse=True)


@app.post("/api/actions/{action_id}/adopt")
def adopt_action(action_id: str, request: ActionRequest) -> dict[str, Any]:
    current_factors()
    action = ACTION_BY_ID.get(action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Unknown recommended action.")
    outcomes = []
    for block in scoped_blocks(request.scope):
        saving = action_saving(action, block)
        if not saving:
            continue
        try:
            outcome = store.adopt(block["id"], action_id, round(saving["kg_co2e_week"] * 2))
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Could not save action to {storage_mode}: {exc}") from exc
        outcomes.append({"block_id": block["id"], **outcome})
    return {"action_id": action_id, "results": outcomes, "state": current_state()}


@app.delete("/api/actions/{action_id}/adopt")
def remove_action(action_id: str, scope: str = Query(default="all")) -> dict[str, Any]:
    current_factors()
    action = ACTION_BY_ID.get(action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Unknown recommended action.")
    outcomes = []
    for block in scoped_blocks(scope):
        saving = action_saving(action, block)
        if not saving:
            continue
        try:
            outcome = store.remove(block["id"], action_id, round(saving["kg_co2e_week"] * 2))
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Could not remove action from {storage_mode}: {exc}") from exc
        outcomes.append({"block_id": block["id"], **outcome})
    return {"action_id": action_id, "results": outcomes, "state": current_state()}


def classification(sample_item: str, weight_kg: float) -> dict[str, Any]:
    current_factors()
    item = ITEMS.get(sample_item)
    if not item:
        raise HTTPException(status_code=422, detail="Choose one of the supported software demo samples.")
    category = item["category"]
    factor = FACTORS[category]
    saved = weight_kg * (factor["mixed"] - factor["segregated"])
    return {
        "sample_item": sample_item, "item_label": item["label"], "category": category,
        "bin": factor["bin"], "probabilities": item["probabilities"], "weight_kg": weight_kg,
        "co2e_saved_kg": saved, "points": round(saved * 10),
        "model_mode": "fixed-software-demo-output",
    }


@app.post("/api/waste/classify")
def classify_waste(request: WasteClassificationRequest) -> dict[str, Any]:
    return classification(request.sample_item, request.weight_kg)


@app.post("/api/waste/log")
def log_waste(request: WasteLogRequest) -> dict[str, Any]:
    block = BLOCK_BY_ID.get(request.block_id)
    if not block:
        raise HTTPException(status_code=404, detail="Unknown campus block.")
    if not block["ranked"]:
        raise HTTPException(status_code=422, detail="Waste points are not enabled for this block in the demo.")
    item = classification(request.sample_item, request.weight_kg)
    record = {
        "item_label": item["item_label"], "category": item["category"], "weight_kg": request.weight_kg,
        "block_id": block["id"], "block_name": block["name"], "co2e_saved_kg": item["co2e_saved_kg"],
        "points": item["points"], "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        saved = store.log_waste(record)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Could not save waste log to {storage_mode}: {exc}") from exc
    return {**item, "log": saved, "state": current_state()}


@app.get("/api/leaderboard")
def leaderboard() -> list[dict[str, Any]]:
    current_factors()
    state = current_state()
    rows = []
    for block in BLOCKS:
        if not block["ranked"]:
            continue
        measured = _seven_day_average_net(block) / block["people"]
        adopted_count = sum(1 for row in state["adopted"] if row["block_id"] == block["id"])
        rows.append({"block_id": block["id"], "block_name": block["name"], "people": block["people"], "measured_kg_co2e_person_day": measured, "effective_kg_co2e_person_day": measured - saved_for_block(block["id"], state) / block["people"], "green_points": state["points"].get(block["id"], block["starting_points"]), "adopted_actions": adopted_count})
    return sorted(rows, key=lambda row: row["effective_kg_co2e_person_day"])


def _seven_day_average_net(block: dict[str, Any]) -> float:
    return sum(block_day(block, day, 24)["kg_net"] / 7 for day in range(1, 8))


@app.get("/api/method")
def method() -> dict[str, Any]:
    factors = current_factors()
    return {
        "factors": {"grid_kg_co2e_per_kwh": factors["grid_kg_co2e_per_kwh"], "pump_kwh_per_kl": factors["pump_kwh_per_kl"]},
        "waste_factors": FACTORS,
        "calculations": {
            "electricity": "electricity_kwh * grid factor",
            "solar_avoided": "solar_generation_kwh * grid factor",
            "water_pumping": "water_kl * pump_kwh_per_kl * grid factor",
            "net": "electricity + waste + water pumping - solar avoided",
            "action_points": "round(kg CO2e saved per week * 2)",
            "waste_points": "round(kg CO2e saved * 10)",
        },
        "reading_mode": "software-simulated",
    }


@app.patch("/api/factors")
def update_factors(request: FactorUpdateRequest) -> dict[str, Any]:
    try:
        factors = store.update_factor_values(request.grid_kg_co2e_per_kwh, request.pump_kwh_per_kl)
        engine.configure_factors(factors["grid_kg_co2e_per_kwh"], factors["pump_kwh_per_kl"], factors["waste"])
        return {"factors": {"grid_kg_co2e_per_kwh": engine.GRID_FACTOR, "pump_kwh_per_kl": engine.PUMP_KWH_PER_KL}}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Could not update emission factors in {storage_mode}: {exc}") from exc


@app.post("/api/demo/reset")
def reset_demo() -> dict[str, str]:
    if not isinstance(store, DemoStore):
        raise HTTPException(status_code=409, detail="Demo reset is disabled when Supabase persistence is active.")
    store.reset()
    return {"status": "reset", "storage": storage_mode}

