# Production Plan API (FastAPI)

Servicio FastAPI que calcula cuánta energía debe generar cada planta para cubrir un **load** objetivo, aplicando un despacho por **mérito económico** (coste), reglas de factibilidad y redondeo a 0.1 MW. La lógica y los modelos Pydantic están en `models.py`; el punto de entrada de la API está en `main.py`. El servicio está pensado para ejecutarse en **Amazon SageMaker JupyterLab** y exponer la API en el **puerto 8888**.

---

## Explicación del código

### Resumen
El servicio recibe un JSON con:
- el **load** (demanda total a cubrir),
- **precios de combustible y disponibilidad eólica**,
- una lista de **plantas** con parámetros técnicos (tipo, eficiencia, pmin, pmax).

Devuelve una lista de elementos `{ name, p }`, donde `p` es la generación asignada a cada planta, cumpliendo las restricciones operativas y sumando el load objetivo.

### Modelos (`models.py`)
- **Powerplant**: `name`, `type` en {`gasfired`, `turbojet`, `windturbine`}, `efficiency`, `pmin`, `pmax`.
- **Fuels**: precios/porcentajes con **alias** de Pydantic (por ejemplo, `"gas(euro/MWh)"`, `"wind(%)"`).
- **ProductionPlanRequest**: agrupa `load`, `fuels` y `powerplants`.
- **ProductionItem**: salida `{ name: str, p: float }` (MW).

### Criterios y algoritmo
1. **Límites efectivos**
   - **Eólica**: su cota superior efectiva es `pmax * wind(%) / 100` y su `pmin` efectivo es `0`.
   - **Térmicas** (gas y turbojet): se respetan `pmin` y `pmax` originales.

2. **Coste marginal**
   - `windturbine`: coste `0` (no se modela consumo).
   - `gasfired`: `gas(euro/MWh) / efficiency`.
   - `turbojet`: `kerosine(euro/MWh) / efficiency`.
   - (El precio de CO2 se mantiene para extensiones pero no se aplica al coste básico.)

3. **Merit order**
   - Orden por **menor coste**, a igualdad se prioriza **mayor eficiencia**, y después **menor pmin**.

4. **Lógica de despacho**
   - **Eólica primero** hasta su `pmax` efectivo (coste 0).
   - Luego **térmicas**:
     - Si la demanda restante es al menos `pmin` de la unidad, se despacha entre `pmin` y `pmax` sin exceder la demanda.
     - Si la demanda restante es **inferior** al `pmin` de la unidad actual, se asigna provisionalmente `pmin` y se realiza un **retroajuste** hacia atrás en unidades ya despachadas, reduciendo primero las **más caras** hasta su propio `pmin`, para mantener la factibilidad.
   - Si aún queda demanda, un **relleno fino** incrementa unidades con margen hasta `pmax`.

5. **Redondeo y ajuste final**
   - Cada `p` se redondea a **0.1 MW**.
   - La diferencia de redondeo frente al objetivo se corrige en pasos de `±0.1` priorizando cambios que **minimizan el impacto en coste** (bajar primero las más caras cuando sobra, subir primero las más baratas cuando falta), sin violar `pmin/pmax`.

6. **Validaciones y errores**
   - Si el load supera la **suma de pmax efectivos**, se lanza `422` (capacidad insuficiente).
   - Si los `pmin` hacen la solución **inviable** incluso con retroajuste, se lanza `422` (“inviable por pmin”).
   - Si no es posible alcanzar exactamente el load tras el redondeo manteniendo las restricciones, se lanza `422` (desajuste por redondeo).

### Capa API (`main.py`)
- Expone `POST /productionplan`, que recibe `ProductionPlanRequest` y devuelve una lista de `ProductionItem`.
- Usa la función de dominio `productionplan(...)` definida en `models.py`.
- Propaga errores HTTP con mensajes claros cuando se detecta inviabilidad.

---

## Ejemplo de entrada y salida

**Entrada**
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

**Salida (ejemplo)**
```json
[
  { "name": "gas1",  "p": 380.0 },
  { "name": "jet1",  "p": 0.0 },
  { "name": "wind1", "p": 100.0 }
]
```

---

## Cómo se construye y lanza en SageMaker JupyterLab (Linux)

- El proyecto reside en un directorio de trabajo de JupyterLab con dos archivos: `models.py` (lógica y modelos Pydantic) y `main.py` (aplicación FastAPI).
- Las dependencias (FastAPI, Uvicorn, Pydantic) se instalan en un entorno de Python accesible desde la terminal de JupyterLab.
- La API se lanza habitualmente con **Uvicorn**, enlazando a `0.0.0.0` y el **puerto 8888** (por ejemplo: `uvicorn main:app --host 0.0.0.0 --port 8888 --reload`). En este entorno, los logs indican la dirección de escucha y el servicio queda accesible mediante la ruta proxy de SageMaker JupyterLab para ese puerto.
- Para detener el proceso, se interrumpe desde la misma terminal o se finaliza si estaba en segundo plano.

---

## Estructura

```
app/
├── main.py     # Punto de entrada FastAPI (endpoints)
└── models.py   # Modelos Pydantic + lógica de mérito y planificación
```

---
