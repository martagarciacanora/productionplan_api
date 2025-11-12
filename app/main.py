from typing import List
from fastapi import FastAPI
from models import (
    ProductionPlanRequest,
    ProductionItem,
    productionplan,
)

app = FastAPI(
    title="Production Plan API",
    version="0.1.0",
    description="Calcula cuánta energía debe generar cada planta para cubrir el load."
)

@app.post("/productionplan", response_model=List[ProductionItem])
def productionplan_endpoint(req: ProductionPlanRequest):
    return productionplan(req)
