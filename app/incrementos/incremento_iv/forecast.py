"""Small supervised demand model, fitted per tenant; no invented observations."""
from statistics import mean
from datetime import timedelta


def fit(values):
    center = (len(values) - 1) / 2
    average = mean(values)
    variance = sum((i - center) ** 2 for i in range(len(values)))
    slope = sum((i - center) * (y - average) for i, y in enumerate(values)) / variance if variance else 0
    return lambda x: max(0.0, average + slope * (x - center))


def forecast(series, start):
    """Chronological seven-day holdout selects regression or moving-average baseline."""
    if len(series) < 42 or sum(series) < 20:
        return {'estado': 'DATOS_INSUFICIENTES', 'motivo': 'Se necesitan al menos 42 días de historial y 20 pedidos pagados.', 'predicciones': [], 'observaciones': len(series), 'pedidos_observados': sum(series)}
    train, test = series[:-7], series[-7:]
    linear = fit(train)
    baseline = mean(train[-7:])
    linear_mae = mean(abs(y - linear(len(train) + i)) for i, y in enumerate(test))
    baseline_mae = mean(abs(y - baseline) for y in test)
    use_linear = linear_mae < baseline_mae
    model = fit(series) if use_linear else lambda _: mean(series[-7:])
    days = [sum(series[i] for i in range(len(series)) if (start + timedelta(days=i)).weekday() == weekday) for weekday in range(7)]
    return {'estado': 'DISPONIBLE', 'modelo': 'Regresión lineal' if use_linear else 'Media móvil de siete días',
            'objetivo': 'Pedidos pagados por día; no ingresos ni stock garantizado',
            'validacion': {'tipo': 'Últimos siete días fuera del entrenamiento', 'mae_regresion': round(linear_mae, 3), 'mae_base': round(baseline_mae, 3)},
            'observaciones': len(series), 'pedidos_observados': sum(series),
            'patron_semanal': [{'dia': day, 'pedidos': count} for day, count in zip(['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'], days)],
            'predicciones': [{'fecha': str(start + timedelta(days=len(series) + i)), 'pedidos_estimados': round(model(len(series) + i), 2)} for i in range(7)],
            'alcance': 'Estimación estadística orientativa. La validación compara regresión con una base simple; la empresa puede no tener suficiente historial o un patrón estable.'}
