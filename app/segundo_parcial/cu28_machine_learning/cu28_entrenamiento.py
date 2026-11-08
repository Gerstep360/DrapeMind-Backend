"""Train and persist demand models as data-only JSON; no pickle loading."""

from datetime import datetime, timedelta, timezone
from statistics import mean
import hashlib, json, math
from sqlalchemy import select
from app.models.saas import Tenant
from .cu28_modelos import DemandModel
from .cu28_forecast import forecast

RECIPE = "demand-rf-1"
FEATURES = [
    "dia_semana",
    "semana_seno",
    "semana_coseno",
    "tendencia",
    "ayer",
    "hace_7_dias",
    "media_7",
    "media_14",
]


def features(history, start):
    day = (start + timedelta(days=len(history))).weekday()
    return [
        day,
        math.sin(day * 2 * math.pi / 7),
        math.cos(day * 2 * math.pi / 7),
        len(history),
        history[-1],
        history[-7],
        mean(history[-7:]),
        mean(history[-14:]),
    ]


def forest_fit(series, start):
    from sklearn.ensemble import RandomForestRegressor

    model = RandomForestRegressor(
        n_estimators=96, max_depth=8, min_samples_leaf=2, random_state=42, n_jobs=1
    )
    x = [features(series[:i], start) for i in range(14, len(series))]
    model.fit(x, series[14:])
    return {
        "arboles": [
            {
                "izquierda": t.tree_.children_left.tolist(),
                "derecha": t.tree_.children_right.tolist(),
                "variable": t.tree_.feature.tolist(),
                "umbral": t.tree_.threshold.tolist(),
                "valor": t.tree_.value[:, 0, 0].tolist(),
            }
            for t in model.estimators_
        ],
        "importancia": dict(zip(FEATURES, model.feature_importances_.tolist())),
    }


def forest_predict(artifact, vector):
    values = []
    for tree in artifact["arboles"]:
        node = 0
        while tree["izquierda"][node] != -1:
            node = (
                tree["izquierda"][node]
                if vector[tree["variable"][node]] <= tree["umbral"][node]
                else tree["derecha"][node]
            )
        values.append(tree["valor"][node])
    return max(0.0, mean(values))


def predict_week(artifact, series, start):
    history = list(series)
    output = []
    for _ in range(7):
        y = forest_predict(artifact, features(history, start))
        output.append(y)
        history.append(y)
    return output


def train(series, start):
    baseline = forecast(series, start)
    if baseline["estado"] != "DISPONIBLE":
        return baseline, None
    # The holdout is never supplied as a feature or target to candidate training.
    candidate = forest_fit(series[:-7], start)
    estimated = predict_week(candidate, series[:-7], start)
    error = mean(abs(a - b) for a, b in zip(series[-7:], estimated))
    artifact = forest_fit(series, start)
    baseline["validacion"]["mae_random_forest"] = round(error, 3)
    baseline["validacion"]["tipo"] = (
        "Validación temporal: últimos siete días, predicción recursiva sin datos futuros"
    )
    baseline["modelos_evaluados"] = [
        "Regresión lineal",
        "Media móvil de siete días",
        "Random Forest",
    ]
    if error < min(
        baseline["validacion"]["mae_regresion"], baseline["validacion"]["mae_base"]
    ):
        baseline["modelo"] = "Random Forest"
        baseline["predicciones"] = [
            {
                "fecha": str(start + timedelta(days=len(series) + i)),
                "pedidos_estimados": round(value, 2),
            }
            for i, value in enumerate(predict_week(artifact, series, start))
        ]
    baseline["importancia_variables"] = artifact["importancia"]
    baseline["alcance"] = (
        "Estimación orientativa de pedidos pagados, sin garantizar ventas ni disponibilidad. Se comparan tres modelos con un periodo temporal separado; se utiliza el de menor MAE."
    )
    center = (len(series) - 1) / 2
    variance = sum((i - center) ** 2 for i in range(len(series)))
    average = mean(series)
    artifact.update(
        receta=RECIPE,
        variables=FEATURES,
        media_7=mean(series[-7:]),
        regresion={
            "centro": center,
            "media": average,
            "pendiente": sum((i - center) * (y - average) for i, y in enumerate(series))
            / variance
            if variance
            else 0,
        },
    )
    return baseline, artifact


def persisted_forecast(db, user, branch, series, start, *, force=False):
    if len(series) < 42 or sum(series) < 20:
        return forecast(series, start)
    scope = f"sucursal:{branch}" if branch else "empresa"
    fingerprint = hashlib.sha256(
        json.dumps([RECIPE, str(start), series], separators=(",", ":")).encode()
    ).hexdigest()
    # Serialize training for a company's scope; no model from another tenant is read.
    db.scalar(select(Tenant).where(Tenant.id == user.tenant_id).with_for_update())
    row = db.scalar(
        select(DemandModel).where(DemandModel.alcance == scope).with_for_update()
    )
    reused = bool(row and row.datos_hash == fingerprint and not force)
    if not reused:
        result, artifact = train(series, start)
        if not row:
            row = DemandModel(alcance=scope, sucursal_id=branch, entrenado_por=user.id)
            db.add(row)
        row.datos_hash = fingerprint
        row.modelo = result["modelo"]
        row.artefacto = artifact
        row.resultado = result
        row.entrenado_por = user.id
        row.entrenado_at = datetime.now(timezone.utc)
        db.commit()
    return {
        **row.resultado,
        "entrenamiento": {
            "id": row.id,
            "fecha": row.entrenado_at.isoformat(),
            "persistido": True,
            "reutilizado": reused,
            "receta": RECIPE,
            "huella_datos": fingerprint,
        },
    }
