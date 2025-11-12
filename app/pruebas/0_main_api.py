from typing import List, Literal
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

#Endpoint principal /productionplan
"""
Versión inicial: valida el JSON y responde con p=0 para todas las plantas.
Más adelante añadiremos la lógica de cálculo real.
"""
@app.post("/productionplan", response_model=List[ProductionItem])
def productionplan(req: ProductionPlanRequest):
    #Comprobamos si la carga total puede cubrirse con las plantas disponibles. 
    #Queremos asegurarnos de que con las plantas disponibles se puede cubrir la demanda total (load).
    #Si la suma de todas las potencias máximas (pmax) es menor que el load, no hay forma de producir suficiente energía, la API debe lanzar un error 422.
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