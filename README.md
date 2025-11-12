# Production Plan API (FastAPI)

A FastAPI service that computes how much power each plant should generate to meet a target **load**, following a cost-based merit order with feasibility rules and 0.1 MW rounding. The business logic and Pydantic models are in `models.py`; the API entrypoint is `main.py`. The service is designed to be run in **Amazon SageMaker JupyterLab** and to expose the API on **port 8888**.

---

## What the code does

### Overview
The service receives a JSON payload describing:
- the required **load** (total power demand),
- **fuel prices and wind availability**,
- a list of **power plants** with technical parameters (type, efficiency, pmin, pmax).

It returns a list of `{ name, p }` items, where `p` is the assigned production for each plant so that the total matches the requested load (subject to operational constraints).

### Models (`models.py`)
- **Powerplant**: `name`, `type` in {`gasfired`, `turbojet`, `windturbine`}, `efficiency`, `pmin`, `pmax`.
- **Fuels**: prices/percentages using Pydantic **aliases** (e.g. `"gas(euro/MWh)"`, `"wind(%)"`).
- **ProductionPlanRequest**: groups `load`, `fuels`, and `powerplants`.
- **ProductionItem**: output item `{ name: str, p: float }` (MW).

### Core criteria and algorithm
1. **Effective bounds**
   - For **wind**, production is inherently variable. The effective upper bound is `pmax * wind(%) / 100`. Its effective lower bound is `0`.
   - For **thermal** plants (gas and turbojet), the effective bounds remain the provided `pmin` and `pmax`.

2. **Marginal cost**
   - `windturbine`: cost = `0` (no fuel burn modeled).
   - `gasfired`: cost = `gas(euro/MWh) / efficiency`.
   - `turbojet`: cost = `kerosine(euro/MWh) / efficiency`.
   - (CO2 price is kept in the input for extensibility but not applied in the base cost here.)

3. **Merit order**
   - Plants are sorted by **ascending cost**, then by **higher efficiency**, then by **lower pmin**. This reflects dispatching cheaper units first while preferring more efficient ones when costs tie.

4. **Dispatch logic**
   - **Wind first** up to its effective `pmax`, because its modeled marginal cost is 0.
   - Then **thermal units**:
     - If the remaining demand is at least the unit’s `pmin`, the unit is dispatched between `pmin` and `pmax` (without exceeding the remaining demand).
     - If the remaining demand is **less than** the current unit’s `pmin`, the algorithm temporarily assigns `pmin` to that unit and performs a **backward reduction** on previously dispatched thermal units. This “back-adjustment” prioritizes reducing **more expensive** previously dispatched units first, down to their own `pmin`, to maintain feasibility.
   - If some demand remains after the first pass, a **fine fill** increases output on units that still have headroom up to `pmax`.

5. **Rounding and reconciliation**
   - Each assigned `p` is rounded to **0.1 MW**.
   - Any rounding difference from the target load is corrected in steps of `±0.1` by adjusting units in an order that **minimizes cost impact** (decrease higher-cost units first when over target, increase lower-cost units first when under target), without violating `pmin/pmax`.

6. **Validation and errors**
   - If the requested load exceeds the **sum of effective pmax**, a `422` error is raised (insufficient capacity).
   - If `pmin` constraints make dispatch **infeasible** even after back-adjustment, a `422` error is raised (“infeasible due to pmin”).
   - If it is not possible to reach the exact load after rounding within constraints, a `422` error is raised (rounding mismatch).

### API layer (`main.py`)
- Exposes `POST /productionplan` which accepts `ProductionPlanRequest` and returns a list of `ProductionItem`.
- Relies on the domain function `productionplan(...)` from `models.py`.
- Raises HTTP errors with clear messages when infeasibilities are detected.

---

## Example request and response

**Request body**
```json
{
  "load": 480,
  "fuels": {
    "gas(euro/MWh)": 13.4,
    "kerosine(euro/MWh)": 50.8,
    "co2(euro/ton)": 20,
    "wind(%)": 60
  },
  "powerplants": [
    { "name": "gas1", "type": "gasfired", "efficiency": 0.53, "pmin": 100, "pmax": 460 },
    { "name": "jet1", "type": "turbojet", "efficiency": 0.30, "pmin": 0,   "pmax": 100 },
    { "name": "wind1","type": "windturbine","efficiency": 1.00, "pmin": 0, "pmax": 100 }
  ]
}
```

**Response (example)**
```json
[
  { "name": "gas1",  "p": 380.0 },
  { "name": "jet1",  "p": 0.0 },
  { "name": "wind1", "p": 100.0 }
]
```

---

## How it is built and launched in SageMaker JupyterLab (Linux)

- The project typically resides in a SageMaker JupyterLab working directory with two files: `models.py` (domain logic and Pydantic models) and `main.py` (FastAPI app).
- Dependencies (FastAPI, Uvicorn, Pydantic) are commonly installed into a Python environment available to the JupyterLab terminal.
- The API is generally **launched with Uvicorn**, binding to `0.0.0.0` and **port 8888** (for example: `uvicorn main:app --host 0.0.0.0 --port 8888 --reload`). In this environment, the server logs show the listening address, and the service is reachable via the SageMaker JupyterLab proxy path for that port.
- When the process needs to be stopped, it is usually interrupted from the same terminal or terminated as a background process if it was started that way.

---

## Project layout
```
app/
├── main.py     # FastAPI entrypoint (endpoints)
└── models.py   # Pydantic models + planning logic and merit-order algorithm
```

---
