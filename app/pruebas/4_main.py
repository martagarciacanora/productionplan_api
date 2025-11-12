from typing import List, Literal, Dict, Tuple
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

PlantType = Literal["gasfired", "turbojet", "windturbine"]

class Powerplant(BaseModel):
    name: str
    type: PlantType
    efficiency: float
    pmin: float
    pmax: float

class Fuels(BaseModel):
    gas_eur_per_mwh: float = Field(alias="gas(euro/MWh)")
    kerosine_eur_per_mwh: float = Field(alias="kerosine(euro/MWh)")
    co2_eur_per_ton: float = Field(alias="co2(euro/ton)")
    wind_pct: float = Field(alias="wind(%)")

class ProductionPlanRequest(BaseModel):
    load: float
    fuels: Fuels
    powerplants: List[Powerplant]

class ProductionItem(BaseModel):
    name: str
    p: float

app = FastAPI(
    title="Production Plan API",
    version="0.1.0",
    description="Calcula cuánta energía debe generar cada planta para cubrir el load."
)

def round_0_1(x: float) -> float:
    return round(x * 10) / 10.0

def effective_bounds(p: Powerplant, fuels: Fuels) -> Tuple[float, float]:
    if p.type == "windturbine":
        return 0.0, p.pmax * (fuels.wind_pct / 100.0)
    return p.pmin, p.pmax

def marginal_cost(p: Powerplant, fuels: Fuels) -> float:
    if p.type == "windturbine":
        return 0.0
    if p.type == "gasfired":
        return fuels.gas_eur_per_mwh / p.efficiency
    if p.type == "turbojet":
        return fuels.kerosine_eur_per_mwh / p.efficiency
    return 1e9

def back_adjust(assignments: List[dict], indices_desc_cost: List[int], delta: float) -> float:
    reduced = 0.0
    for idx in indices_desc_cost:
        a = assignments[idx]
        room = a["p"] - a["pmin"]
        if room <= 1e-12:
            continue
        take = min(room, delta - reduced)
        if take > 0:
            a["p"] -= take
            reduced += take
            if abs(reduced - delta) <= 1e-12:
                break
    return reduced

def finalize_rounding(assignments: List[dict], target: float):
    for a in assignments:
        a["p"] = round_0_1(a["p"])

    total = sum(a["p"] for a in assignments)
    diff = round_0_1(target - total)
    if abs(diff) < 0.05:
        return
    step = 0.1 if diff > 0 else -0.1
    rem = abs(diff)
    
    key = (lambda a: a["cost"]) if step < 0 else (lambda a: -a["cost"])
    for a in sorted(assignments, key=key):
        while rem >= 0.0999:
            cand = a["p"] + step
            if step > 0 and cand <= a["pmax"] + 1e-12:
                a["p"] = round_0_1(cand)
                rem = round_0_1(rem - 0.1)
            elif step < 0 and cand >= a["pmin"] - 1e-12:
                a["p"] = round_0_1(cand)
                rem = round_0_1(rem - 0.1)
            else:
                break

    total2 = sum(a["p"] for a in assignments)
    if round_0_1(total2) != round_0_1(target):
        raise HTTPException(status_code=422, detail="No se pudo igualar el load tras el redondeo.")

def productionplan(req: ProductionPlanRequest) -> List[ProductionItem]:
    total_cap = 0.0
    for p in req.powerplants:
        _, pmax = effective_bounds(p, req.fuels)
        total_cap += pmax
    if req.load > total_cap + 1e-9:
        raise HTTPException(
            status_code=422,
            detail=f"La carga ({req.load}) supera la capacidad total ({total_cap:.1f})."
        )

    enriched: List[dict] = []
    for i, p in enumerate(req.powerplants):
        pmin, pmax = effective_bounds(p, req.fuels)
        cost = marginal_cost(p, req.fuels)
        enriched.append({
            "idx": i, "name": p.name, "type": p.type, "eff": p.efficiency,
            "pmin": max(0.0, float(pmin)),
            "pmax": max(0.0, float(pmax)),
            "cost": float(cost),
            "p": 0.0
        })

    enriched.sort(key=lambda x: (x["cost"], -x["eff"], x["pmin"]))

    remaining = req.load

    for a in enriched:
        if a["type"] == "windturbine" and remaining > 0:
            take = min(remaining, a["pmax"])
            a["p"] = take
            remaining -= take

    thermal_idx = [i for i, a in enumerate(enriched) if a["type"] != "windturbine"]
    for i in thermal_idx:
        if remaining <= 1e-9:
            break
        a = enriched[i]
        if remaining >= a["pmin"]:
            take = min(a["pmax"], remaining)
            a["p"] = max(a["pmin"], take)
            remaining -= a["p"]
        else:
            a["p"] = a["pmin"]
            over = a["p"] - remaining
            prev = [j for j in thermal_idx if j < i]
            prev.sort(key=lambda j: enriched[j]["cost"], reverse=True)
            reduced = back_adjust(enriched, prev, over)
            if reduced + 1e-12 < over:
                raise HTTPException(status_code=422, detail="Inviable por Pmin: no se puede retroceder más.")
            remaining = 0.0

    if remaining > 1e-9:
        for a in enriched:
            if a["p"] < a["pmax"] - 1e-12:
                add = min(a["pmax"] - a["p"], remaining)
                a["p"] += add
                remaining -= add
                if remaining <= 1e-9:
                    break

    if remaining > 1e-6:
        raise HTTPException(status_code=422, detail="Capacidad insuficiente.")

    finalize_rounding(enriched, req.load)

    by_name = {a["name"]: a["p"] for a in enriched}
    return [ProductionItem(name=p.name, p=round_0_1(by_name[p.name])) for p in req.powerplants]

@app.post("/productionplan", response_model=List[ProductionItem])
def productionplan_endpoint(req: ProductionPlanRequest):
    return productionplan(req)    