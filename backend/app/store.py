"""Supabase persistence with an in-memory fallback for zero-setup demo runs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from supabase import Client, create_client

from . import engine
from .engine import BLOCKS


class DemoStore:
    def __init__(self) -> None:
        self.points = {block["id"]: block["starting_points"] for block in BLOCKS}
        self.adopted: set[tuple[str, str]] = set()
        self.logs: list[dict[str, Any]] = []

    def state(self) -> dict[str, Any]:
        return {
            "points": dict(self.points),
            "adopted": [{"block_id": block_id, "action_id": action_id} for block_id, action_id in sorted(self.adopted)],
            "logs": self.logs[:6],
        }

    def adopt(self, block_id: str, action_id: str, points: int) -> dict[str, Any]:
        key = (block_id, action_id)
        added = key not in self.adopted
        if added:
            self.adopted.add(key)
            self.points[block_id] += points
        return {"added": added, "points": self.points[block_id]}

    def remove(self, block_id: str, action_id: str, points: int) -> dict[str, Any]:
        key = (block_id, action_id)
        removed = key in self.adopted
        if removed:
            self.adopted.remove(key)
            self.points[block_id] = max(0, self.points[block_id] - points)
        return {"removed": removed, "points": self.points[block_id]}

    def log_waste(self, item: dict[str, Any]) -> dict[str, Any]:
        self.logs.insert(0, item)
        self.logs = self.logs[:100]
        self.points[item["block_id"]] += item["points"]
        return item

    def reset(self) -> None:
        self.__init__()

    def factor_values(self) -> dict[str, Any]:
        return {
            "grid_kg_co2e_per_kwh": engine.GRID_FACTOR,
            "pump_kwh_per_kl": engine.PUMP_KWH_PER_KL,
            "waste": {category: {"mixed": factor["mixed"], "segregated": factor["segregated"]} for category, factor in engine.FACTORS.items()},
        }

    def update_factor_values(self, grid: float, pump: float) -> dict[str, Any]:
        engine.configure_factors(grid, pump)
        return self.factor_values()


class SupabaseStore:
    def __init__(self, url: str, service_role_key: str) -> None:
        self.client: Client = create_client(url, service_role_key)

    def state(self) -> dict[str, Any]:
        block_rows = self.client.table("blocks").select("id,green_points").execute().data or []
        adopted_rows = self.client.table("adopted_actions").select("block_id,action_id").execute().data or []
        logs = self.client.table("waste_logs").select("id,item_label,category,weight_kg,block_id,block_name,co2e_saved_kg,points,created_at").order("created_at", desc=True).limit(6).execute().data or []
        return {
            "points": {row["id"]: row["green_points"] for row in block_rows},
            "adopted": adopted_rows,
            "logs": logs,
        }

    def factor_values(self) -> dict[str, Any]:
        rows = self.client.table("emission_factors").select("id,mixed_value,segregated_value").eq("active", True).execute().data or []
        factors = {row["id"]: row for row in rows}
        if "grid" not in factors or "pump" not in factors:
            raise RuntimeError("Grid and pump factors are missing from emission_factors.")
        waste = {}
        for category in engine.CATEGORIES:
            row = factors.get(category)
            if row is None or row["segregated_value"] is None:
                raise RuntimeError(f"Waste factors are incomplete for {category}.")
            waste[category] = {"mixed": float(row["mixed_value"]), "segregated": float(row["segregated_value"])}
        return {
            "grid_kg_co2e_per_kwh": float(factors["grid"]["mixed_value"]),
            "pump_kwh_per_kl": float(factors["pump"]["mixed_value"]),
            "waste": waste,
        }

    def update_factor_values(self, grid: float, pump: float) -> dict[str, Any]:
        self.client.table("emission_factors").update({"mixed_value": grid}).eq("id", "grid").execute()
        self.client.table("emission_factors").update({"mixed_value": pump}).eq("id", "pump").execute()
        return self.factor_values()

    def adopt(self, block_id: str, action_id: str, points: int) -> dict[str, Any]:
        result = self.client.rpc("greenloop_adopt_action", {
            "p_block_id": block_id, "p_action_id": action_id, "p_points": points,
        }).execute().data
        return result or {"added": False}

    def remove(self, block_id: str, action_id: str, points: int) -> dict[str, Any]:
        result = self.client.rpc("greenloop_remove_action", {
            "p_block_id": block_id, "p_action_id": action_id, "p_points": points,
        }).execute().data
        return result or {"removed": False}

    def log_waste(self, item: dict[str, Any]) -> dict[str, Any]:
        row = self.client.rpc("greenloop_log_waste", {
            "p_item_label": item["item_label"], "p_category": item["category"],
            "p_weight_kg": item["weight_kg"], "p_block_id": item["block_id"],
            "p_block_name": item["block_name"], "p_co2e_saved_kg": item["co2e_saved_kg"],
            "p_points": item["points"],
        }).execute().data
        return row or item

    def reset(self) -> None:
        raise RuntimeError("Reset is available only in in-memory demo mode.")


def make_store(url: str | None, service_role_key: str | None) -> tuple[DemoStore | SupabaseStore, str]:
    if url and service_role_key:
        return SupabaseStore(url, service_role_key), "supabase"
    return DemoStore(), "memory-demo"

