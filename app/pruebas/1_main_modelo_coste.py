from typing import List, Literal, Dict, Tuple
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

#Definimos los tipos de planta posibles
PlantType = Literal["gasfired", "turbojet", "windturbine"]

#Modelo de una planta de energía
class Powerplant(BaseModel):
    name: str
    type: PlantType
    efficiency: float
    pmin: float
    pmax: float

#Modelo de combustibles y mapeamos los nombres del JSON a nombres Python
class Fuels(BaseModel):
    gas_eur_per_mwh: float = Field(alias="gas(euro/MWh)")
    kerosine_eur_per_mwh: float = Field(alias="kerosine(euro/MWh)")
    co2_eur_per_ton: float = Field(alias="co2(euro/ton)")
    wind_pct: float = Field(alias="wind(%)")

#Modelo del POST
class ProductionPlanRequest(BaseModel):
    load: float
    fuels: Fuels
    powerplants: List[Powerplant]

#Modelo respuesta
class ProductionItem(BaseModel):
    name: str
    p: float

#Creamos FastAPI
app = FastAPI(
    title="Production Plan API",
    version="0.1.0",
    description="Calcula cuánta energía debe generar cada planta para cubrir el load."
)

##Funciones
def round_0_1(x: float) -> float:
    return round(x * 10) / 10.0

#Para eólica: pmin=0 y pmax efectivo = pmax * %Wind
def effective_bounds(p: Powerplant, fuels: Fuels) -> Tuple[float, float]:
    if p.type == "windturbine":
        return 0.0, p.pmax * (fuels.wind_pct / 100.0)
    return p.pmin, p.pmax

#Coste marginal: wind = 0   gasfired = gas_price / efficiency   turbojet = kerosine_price / efficiency
def marginal_cost(p: Powerplant, fuels: Fuels) -> float:
    if p.type == "windturbine":
        return 0.0
    if p.type == "gasfired":
        return fuels.gas_eur_per_mwh / p.efficiency
    if p.type == "turbojet":
        return fuels.kerosine_eur_per_mwh / p.efficiency
    return 1e9

#Recibe cuántos MW sobran (delta). Recorre plantas encendidas de más cara a más barata. Resta producción sin bajar de su pmin. Se detiene cuando logra compensar todo el exceso. Devuelve cuánto pudo reducir (reduced)
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

#Redondea las potencias asignadas a múltiplos de 0.1 MW, y luego ajusta los pequeños desfases que ese redondeo puede generar
#Cuando se redondea, se pierden o se ganan pequeñas fracciones (por ejemplo, 479.95 → 480.0, pero quizás sumando todas ya no da igual al load)
# finalize_rounding() corrige eso
def finalize_rounding(assignments: List[dict], target: float):
    for a in assignments:
        a["p"] = round_0_1(a["p"])

    total = sum(a["p"] for a in assignments)
    diff = round_0_1(target - total)
    if abs(diff) < 0.05:
        return
    #Decidir dirección del ajuste
    step = 0.1 if diff > 0 else -0.1
    rem = abs(diff)

    #Si hay que subir (diff > 0), se empieza por las más baratas (wind o gas antes que turbojet).
    #Si hay que bajar (diff < 0), se empieza por las más caras (para reducir coste).
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

    #Verificación final
    total2 = sum(a["p"] for a in assignments)
    if round_0_1(total2) != round_0_1(target):
        raise HTTPException(status_code=422, detail="No se pudo igualar el load tras el redondeo.")


##Endpoint principal /productionplan
@app.post("/productionplan", response_model=List[ProductionItem])
def productionplan(req: ProductionPlanRequest):
    total_capacidad = 0.0
    for p in req.powerplants:
        if p.type == "windturbine":
            total_capacidad += p.pmax * (req.fuels.wind_pct / 100)
        else:
            total_capacidad += p.pmax

    if req.load > total_capacidad:
        raise HTTPException(
            status_code=422,
            detail=f"La carga ({req.load}) es mayor que la capacidad total ({total_capacidad:.1f})"
        )

    # Respuesta provisional: devolvemos p=0 para todas las plantas
    return [{"name": p.name, "p": 0.0} for p in req.powerplants]