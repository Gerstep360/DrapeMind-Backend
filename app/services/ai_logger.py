"""
Modulo centralizado de auditoria y logging enriquecido para el motor de IA de DrapeMind.

Genera salidas altamente legibles para humanos (banners visuales, diagnosticos claros de
rendimiento, consumo de tokens y enrutamiento) y lineas estructuradas [AI_AUDIT] en JSON
de facil parseo para agentes y herramientas de observabilidad de IA.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[2]
LOGS_DIR = BACKEND_DIR / "logs"

py_logger = logging.getLogger("drapemind.ai.audit")


class AILogger:
    """Registra eventos de inferencia y turnos conversacionales de Altair."""

    def __init__(self) -> None:
        self.logs_dir = LOGS_DIR
        self.gemma_log = self.logs_dir / "llama-server.log"
        self.scout_log = self.logs_dir / "llama-scout.log"
        self.audit_log = self.logs_dir / "ai-audit.log"

    def _ensure_dir(self) -> None:
        try:
            self.logs_dir.mkdir(exist_ok=True)
        except Exception:
            pass

    def _write_file(self, target: Path, text: str) -> None:
        """Escritura segura y no bloqueante en append."""
        try:
            self._ensure_dir()
            with target.open("a", encoding="utf-8", errors="replace") as f:
                f.write(text + "\n")
        except Exception:
            pass

    def _emit(self, human_text: str, json_event: dict[str, Any], targets: list[str] = ("gemma", "scout", "audit")) -> None:
        """Emite simultaneamente a archivos de log y logger de Python."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        formatted_human = f"\n{human_text}"
        json_line = f"[AI_AUDIT] {json.dumps(json_event, ensure_ascii=False, default=str)}"

        full_block = f"{formatted_human}\n{json_line}\n"

        # Logger Python para journalctl / Uvicorn
        py_logger.info("%s", json_line)

        # Archivos de llama-server para monitoreo en vivo (install.sh --logs-llama)
        if "gemma" in targets:
            self._write_file(self.gemma_log, full_block)
        if "scout" in targets:
            self._write_file(self.scout_log, full_block)
        if "audit" in targets:
            self._write_file(self.audit_log, full_block)

    def log_new_message(
        self,
        chat_id: int | str,
        user_id: int | str,
        user_name: str,
        message: str,
        scout_enabled: bool,
    ) -> None:
        """Registra el arribo de un nuevo mensaje de usuario al backend."""
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        clean_msg = " ".join(message.split())
        preview = clean_msg[:160] + ("..." if len(clean_msg) > 160 else "")
        mode_str = (
            "SCOUT (Qwen 0.6B en puerto 8089) -> GEMMA 4 (Bajo demanda en 8088)"
            if scout_enabled
            else "LEGACY DIRECTO (Gemma 4 en puerto 8088 sin Scout)"
        )

        banner = (
            "════════════════════════════════════════════════════════════════════════════════\n"
            f"✦ [NUEVO MENSAJE] Chat: #{chat_id} | Usuario: {user_name} (ID: {user_id}) | {now_str}\n"
            f"  Mensaje: \"{preview}\"\n"
            f"  Arquitectura IA: {mode_str}\n"
            "════════════════════════════════════════════════════════════════════════════════"
        )

        event = {
            "event": "new_message",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "chat_id": chat_id,
            "user_id": user_id,
            "user_name": user_name,
            "message_length": len(message),
            "message_preview": preview,
            "scout_enabled": scout_enabled,
            "architecture": "scout_gemma" if scout_enabled else "legacy_gemma",
        }
        self._emit(banner, event)

    def log_scout_decision(
        self,
        chat_id: int | str,
        step: int,
        decision_type: str,
        decision_detail: str,
        usage: dict[str, Any],
        timings: dict[str, Any],
        duration_ms: float,
    ) -> None:
        """Registra cada ciclo de razonamiento o llamada a tools del orquestador Scout."""
        prompt_tokens = usage.get("prompt_tokens", 0) or 0
        completion_tokens = usage.get("completion_tokens", 0) or 0
        total_tokens = prompt_tokens + completion_tokens
        cached_tokens = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0

        # Velocidad en tokens/seg
        pred_tps = timings.get("predicted_per_second")
        if not pred_tps and duration_ms > 0 and completion_tokens > 0:
            pred_tps = round((completion_tokens / (duration_ms / 1000.0)), 1)
        pred_tps_str = f"{pred_tps:.1f} T/s" if pred_tps else "N/D"

        prompt_ms = timings.get("prompt_ms", 0) or 0

        # Diagnostico de rendimiento de Scout
        perf_status = "OPTIMO"
        perf_alert = ""
        if duration_ms > 15000:
            perf_status = "LENTO"
            perf_alert = " ⚠️ [ALERTA RENDIMIENTO: Latencia de Scout elevada (>15s)]"
        elif pred_tps and pred_tps < 6.0:
            perf_status = "DEGRADADO"
            perf_alert = f" ⚠️ [ALERTA RENDIMIENTO: Velocidad de generación Scout baja ({pred_tps_str})]"

        # Clasificacion del enrutamiento
        if decision_type == "finish":
            route_badge = "[SCOUT ATENDIÓ DIRECTAMENTE]"
            route_desc = "Respuesta resuelta por Scout Qwen (Gemma 4 en reposo, 0 tokens Gemma)."
            delegated = False
        elif decision_type == "delegate":
            route_badge = "[DELEGACIÓN A GEMMA 4 SOLICITADA]"
            route_desc = "Scout delega al modelo grande para síntesis/razonamiento profundo."
            delegated = True
        elif decision_type == "tool":
            route_badge = "[CONSULTA A HERRAMIENTAS]"
            route_desc = f"Scout ejecuta lectura de datos: {decision_detail}"
            delegated = False
        else:
            route_badge = f"[{decision_type.upper()}]"
            route_desc = decision_detail
            delegated = False

        banner = (
            f"┌─── [SCOUT ORQUESTADOR - PASO {step}] {route_badge} ────────────────────\n"
            f"│ Chat: #{chat_id} | Acción: {route_desc}\n"
            f"│ Latencia Paso: {duration_ms:.0f}ms (Prefill prompt: {prompt_ms:.0f}ms)\n"
            f"│ Tokens Scout: Prompt={prompt_tokens} (Cacheados: {cached_tokens}) | Generados={completion_tokens} (~{pred_tps_str}) | Total={total_tokens}\n"
            f"│ Estado Rendimiento Scout: [{perf_status}]{perf_alert}\n"
            f"└──────────────────────────────────────────────────────────────────────────────"
        )

        event = {
            "event": "scout_step",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "chat_id": chat_id,
            "step": step,
            "route": decision_type,
            "delegated_to_gemma": delegated,
            "detail": decision_detail,
            "duration_ms": duration_ms,
            "tokens": {
                "prompt": prompt_tokens,
                "completion": completion_tokens,
                "total": total_tokens,
                "cached": cached_tokens,
            },
            "speed_tokens_per_sec": pred_tps,
            "prefill_ms": prompt_ms,
            "performance_status": perf_status,
        }
        self._emit(banner, event, targets=["scout", "gemma", "audit"])

    def log_tool_execution(
        self,
        chat_id: int | str,
        tool_name: str,
        args: dict[str, Any],
        results_count: int,
        duration_ms: float,
        is_error: bool = False,
    ) -> None:
        """Registra la ejecucion de una herramienta del atelier."""
        status_badge = "❌ ERROR" if is_error else "✔ OK"
        args_str = json.dumps(args, ensure_ascii=False)
        if len(args_str) > 100:
            args_str = args_str[:97] + "..."

        banner = (
            f"│ ⚡ [HERRAMIENTA EJECUTADA] {tool_name} [{status_badge}]\n"
            f"│    Args: {args_str}\n"
            f"│    Resultados: {results_count} item(s) | Tiempo: {duration_ms:.1f}ms"
        )
        event = {
            "event": "tool_execution",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "chat_id": chat_id,
            "tool": tool_name,
            "args": args,
            "results_count": results_count,
            "duration_ms": duration_ms,
            "success": not is_error,
        }
        self._emit(banner, event, targets=["scout", "audit"])

    def log_gemma_inference(
        self,
        chat_id: int | str,
        ttft_seconds: float | None,
        total_seconds: float,
        usage: dict[str, Any],
        timings: dict[str, Any],
        reasoning_chars: int,
        finish_reason: str,
        model_name: str = "google/gemma-4-E2B-it",
    ) -> None:
        """Registra la generacion y consumo de tokens del modelo grande Gemma 4."""
        prompt_tokens = usage.get("prompt_tokens", 0) or 0
        completion_tokens = usage.get("completion_tokens", 0) or 0
        total_tokens = prompt_tokens + completion_tokens

        pred_tps = timings.get("predicted_per_second")
        if not pred_tps and total_seconds > 0 and completion_tokens > 0:
            pred_tps = round(completion_tokens / total_seconds, 1)
        pred_tps_str = f"{pred_tps:.1f} T/s" if pred_tps else "N/D"

        ttft_str = f"{ttft_seconds:.2f}s" if ttft_seconds is not None else "N/D"

        # Evaluacion de rendimiento Gemma
        perf_status = "OPTIMO"
        perf_alert = ""
        if ttft_seconds and ttft_seconds > 8.0:
            perf_status = "LENTO (TTFT)"
            perf_alert = f" ⚠️ [ALERTA GEMMA: Primer token demoró {ttft_str}]"
        elif pred_tps and pred_tps < 4.0:
            perf_status = "DEGRADADO (TPS)"
            perf_alert = f" ⚠️ [ALERTA GEMMA: Velocidad de generación baja: {pred_tps_str}]"
        elif total_seconds > 60.0:
            perf_status = "TIEMPO EXCESIVO"
            perf_alert = f" ⚠️ [ALERTA GEMMA: Inferencia total superó 60s ({total_seconds:.1f}s)]"

        banner = (
            f"┌─── [GEMMA 4 - INFERENCIA MODELO GRANDE] ────────────────────────────────────\n"
            f"│ Chat: #{chat_id} | Modelo: {model_name}\n"
            f"│ Métricas de Generación:\n"
            f"│   • Tiempo al 1er Token (TTFT): {ttft_str}\n"
            f"│   • Tiempo Total Generación:   {total_seconds:.2f}s\n"
            f"│   • Velocidad de Generación:   {pred_tps_str}\n"
            f"│ Tokens Consumidos por Gemma 4:\n"
            f"│   • Prompt:     {prompt_tokens} tokens\n"
            f"│   • Generados:  {completion_tokens} tokens\n"
            f"│   • Total Gemma: {total_tokens} tokens (Razonamiento: {reasoning_chars} chars)\n"
            f"│   • Finalización: [{finish_reason}]\n"
            f"│ Estado Rendimiento Gemma: [{perf_status}]{perf_alert}\n"
            f"└──────────────────────────────────────────────────────────────────────────────"
        )

        event = {
            "event": "gemma_inference",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "chat_id": chat_id,
            "model": model_name,
            "ttft_seconds": ttft_seconds,
            "total_seconds": total_seconds,
            "tokens": {
                "prompt": prompt_tokens,
                "completion": completion_tokens,
                "total": total_tokens,
            },
            "reasoning_chars": reasoning_chars,
            "speed_tokens_per_sec": pred_tps,
            "finish_reason": finish_reason,
            "performance_status": perf_status,
        }
        self._emit(banner, event, targets=["gemma", "audit"])

    def log_turn_summary(
        self,
        chat_id: int | str,
        user_name: str,
        duration_ms: float,
        routing_mode: str,
        scout_calls: int,
        gemma_calls: int,
        tools_used: list[str],
        scout_tokens: dict[str, int],
        gemma_tokens: dict[str, int],
        notices: list[dict[str, Any]] | None = None,
    ) -> None:
        """Genera el resumen de cierre de turno con consumo consolidado de tokens y diagnostico."""
        duration_s = duration_ms / 1000.0

        scout_p = scout_tokens.get("prompt", 0)
        scout_c = scout_tokens.get("completion", 0)
        scout_t = scout_p + scout_c

        gemma_p = gemma_tokens.get("prompt", 0)
        gemma_c = gemma_tokens.get("completion", 0)
        gemma_t = gemma_p + gemma_c

        grand_total = scout_t + gemma_t

        # Etiqueta de ruta
        if gemma_calls > 0 and scout_calls > 0:
            route_label = "DELEGADO A GEMMA 4 (Scout consultó herramientas + Gemma redactó)"
            model_summary = "Qwen 0.6B + Gemma 4-E2B"
        elif scout_calls > 0 and gemma_calls == 0:
            route_label = "SCOUT DIRECTO (100% resuelto por Qwen 0.6B, Gemma 4 en reposo)"
            model_summary = "Qwen 0.6B (Ahorro de CPU)"
        else:
            route_label = "LEGACY GEMMA 4 (Sin orquestador Scout)"
            model_summary = "Gemma 4-E2B"

        tools_str = ", ".join(tools_used) if tools_used else "Ninguna (Charla / Directo)"

        # Diagnostico general de rendimiento del turno
        if duration_s < 5.0:
            perf_badge = "🟢 EXCELENTE (< 5s)"
            perf_verdict = "optimal"
        elif duration_s < 18.0:
            perf_badge = "🟢 BUENO (Respuesta fluida)"
            perf_verdict = "good"
        elif duration_s < 35.0:
            perf_badge = "🟡 MODERADO (Carga aceptable)"
            perf_verdict = "moderate"
        else:
            perf_badge = "🔴 LENTO (> 35s - Revisar concurrencia o recursos)"
            perf_verdict = "slow"

        banner = (
            "╔══════════════════════════════════════════════════════════════════════════════\n"
            f"║ ✔ [TURNO COMPLETADO] Chat: #{chat_id} | Usuario: {user_name}\n"
            f"║ Duración Total del Turno: {duration_s:.2f}s ({duration_ms:.0f}ms)\n"
            "║──────────────────────────────────────────────────────────────────────────────\n"
            "║ 📊 RESUMEN DE ENRUTAMIENTO Y CONSUMO DE TOKENS:\n"
            f"║   • Enrutamiento: {route_label}\n"
            f"║   • Modelos Usados: {model_summary}\n"
            f"║   • Llamadas: Scout={scout_calls} | Gemma 4={gemma_calls}\n"
            f"║   • Herramientas Ejecutadas ({len(tools_used)}): {tools_str}\n"
            "║   • Desglose de Tokens:\n"
            f"║       - Scout (Qwen 0.6B):   {scout_t:>5} tokens (Prompt: {scout_p}, Gen: {scout_c})\n"
            f"║       - Gemma 4 (2B):        {gemma_t:>5} tokens (Prompt: {gemma_p}, Gen: {gemma_c})\n"
            f"║       - TOTAL CONSUMIDO:     {grand_total:>5} tokens en este turno\n"
            f"║   • Evaluación Rendimiento: {perf_badge}\n"
            "╚══════════════════════════════════════════════════════════════════════════════"
        )

        event = {
            "event": "turn_summary",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "chat_id": chat_id,
            "user_name": user_name,
            "duration_ms": duration_ms,
            "duration_seconds": round(duration_s, 2),
            "routing": routing_mode,
            "route_label": route_label,
            "models_used": model_summary,
            "scout_calls": scout_calls,
            "gemma_calls": gemma_calls,
            "tools_used": tools_used,
            "tokens": {
                "scout": {"prompt": scout_p, "completion": scout_c, "total": scout_t},
                "gemma": {"prompt": gemma_p, "completion": gemma_c, "total": gemma_t},
                "grand_total": grand_total,
            },
            "performance_verdict": perf_verdict,
            "notices_count": len(notices or []),
        }
        self._emit(banner, event, targets=["gemma", "scout", "audit"])


ai_logger = AILogger()
