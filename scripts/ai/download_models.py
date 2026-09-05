#!/usr/bin/env python3
"""
DRAPEMIND ATELIER - FAST & NON-BLOCKING AI MODEL DOWNLOADER
Descargador de alto rendimiento para modelos GGUF oficiales de Google Gemma 4.
- Máxima saturación de ancho de banda del router (Mbps).
- Descarga en hilo secundario no bloqueante (cero congelamiento de GUI).
- Reanudación inteligente HTTP Range (con auto-recuperación ante 416).
- Telemetría fluida: Porcentaje, MB/s, Mbps, Tamaño y ETA.
"""

import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Callable, Optional

# Directorio base del backend
BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_MODELS_DIR = BACKEND_DIR / "ai_models" / "gemma-4-e2b"

# URLs oficiales de Google Gemma 4 en HuggingFace CDN
DEFAULT_MODELS = [
    {
        "filename": "gemma-4-E2B-it-mmproj.gguf",
        "url": "https://huggingface.co/google/gemma-4-E2B-it-qat-q4_0-gguf/resolve/main/gemma-4-E2B-it-mmproj.gguf?download=true",
        "description": "Proyector multimodal / visión Atelier",
        "approx_size_mb": 941,
    },
    {
        "filename": "gemma-4-E2B_q4_0-it.gguf",
        "url": "https://huggingface.co/google/gemma-4-E2B-it-qat-q4_0-gguf/resolve/main/gemma-4-E2B_q4_0-it.gguf?download=true",
        "description": "Modelo cuantizado Gemma 4-E2B Q4_0",
        "approx_size_mb": 3194,
    },
]

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"


def format_bytes(size: float) -> str:
    """Convierte bytes a formato legible (KB, MB, GB)."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0 or unit == "TB":
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} GB"


def format_speed(bytes_per_sec: float) -> str:
    """Retorna la velocidad tanto en MB/s como en Mbps."""
    mb_s = bytes_per_sec / (1024 * 1024)
    mbps = (bytes_per_sec * 8) / (1000 * 1000)
    return f"{mb_s:.2f} MB/s ({mbps:.1f} Mbps)"


def format_eta(seconds: float) -> str:
    """Formatea el tiempo estimado restante."""
    if seconds < 0 or seconds > 86400:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def download_file_fast(
    url: str,
    destination: Path,
    chunk_size: int = 1024 * 1024,  # 1MB por chunk (óptimo para velocidad y respuesta de GUI)
    progress_callback: Optional[Callable[[dict], None]] = None,
    stop_check: Optional[Callable[[], bool]] = None,
) -> bool:
    """
    Descarga un archivo con máxima velocidad de red, reanudación y emisión segura de eventos.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_file = destination.with_suffix(destination.suffix + ".part")

    # Si el archivo final ya existe y tiene peso completo
    if destination.exists() and destination.stat().st_size > 10 * 1024 * 1024:
        sz = destination.stat().st_size
        if progress_callback:
            progress_callback({
                "status": "completed",
                "filename": destination.name,
                "downloaded": sz,
                "total": sz,
                "percent": 100.0,
                "message": f"{destination.name} ya se encuentra presente ({format_bytes(sz)}).",
            })
        return True

    def _open_stream(resume_from: int):
        headers = {"User-Agent": BROWSER_UA}
        if resume_from > 0:
            headers["Range"] = f"bytes={resume_from}-"
        req = urllib.request.Request(url, headers=headers)
        return urllib.request.urlopen(req, timeout=30)

    existing_bytes = temp_file.stat().st_size if temp_file.exists() else 0
    response = None
    mode = "wb"
    downloaded_bytes = 0
    total_bytes = 0

    try:
        try:
            response = _open_stream(existing_bytes)
        except urllib.error.HTTPError as http_err:
            if http_err.code == 416:  # Range Not Satisfiable (archivo parcial dañado o ya completo)
                if temp_file.exists():
                    temp_file.unlink()
                existing_bytes = 0
                response = _open_stream(0)
            else:
                raise

        status = getattr(response, "status", 200)
        content_range = response.headers.get("Content-Range")
        content_length = response.headers.get("Content-Length")

        if status == 206 and content_range:
            # Servidor aceptó reanudar
            total_bytes = int(content_range.split("/")[-1])
            mode = "ab"
            downloaded_bytes = existing_bytes
        else:
            # Descarga completa desde inicio
            total_bytes = int(content_length) if content_length else 0
            mode = "wb"
            downloaded_bytes = 0

        start_time = time.perf_counter()
        last_calc_time = start_time
        last_calc_bytes = downloaded_bytes
        current_speed = 0.0

        with open(temp_file, mode, buffering=chunk_size) as f:
            while True:
                if stop_check and stop_check():
                    if progress_callback:
                        progress_callback({
                            "status": "cancelled",
                            "filename": destination.name,
                            "message": "Descarga pausada por el usuario.",
                        })
                    return False

                chunk = response.read(chunk_size)
                if not chunk:
                    break

                f.write(chunk)
                downloaded_bytes += len(chunk)

                now = time.perf_counter()
                dt = now - last_calc_time
                if dt >= 0.25:  # Emitir telemetría cada 250ms (4 actualizaciones/seg, suave y ligero)
                    current_speed = (downloaded_bytes - last_calc_bytes) / dt
                    last_calc_time = now
                    last_calc_bytes = downloaded_bytes

                    percent = (downloaded_bytes / total_bytes * 100) if total_bytes > 0 else 0.0
                    eta = ((total_bytes - downloaded_bytes) / current_speed) if current_speed > 0 and total_bytes > 0 else 0.0

                    if progress_callback:
                        progress_callback({
                            "status": "downloading",
                            "filename": destination.name,
                            "downloaded": downloaded_bytes,
                            "total": total_bytes,
                            "percent": percent,
                            "speed_bps": current_speed,
                            "speed_str": format_speed(current_speed),
                            "eta_str": format_eta(eta),
                            "progress_str": f"{format_bytes(downloaded_bytes)} / {format_bytes(total_bytes)} ({percent:.1f}%)",
                        })

                # Ceder brevemente el CPU al hilo principal de la interfaz
                time.sleep(0.0005)

        # Finalización exitosa
        if temp_file.exists():
            if destination.exists():
                destination.unlink()
            temp_file.rename(destination)

        if progress_callback:
            progress_callback({
                "status": "completed",
                "filename": destination.name,
                "downloaded": downloaded_bytes,
                "total": total_bytes,
                "percent": 100.0,
                "message": f"✓ {destination.name} descargado ({format_bytes(downloaded_bytes)}).",
            })
        return True

    except Exception as e:
        if progress_callback:
            progress_callback({
                "status": "error",
                "error": str(e),
                "filename": destination.name,
            })
        return False
    finally:
        if response:
            try:
                response.close()
            except Exception:
                pass


def check_models_status(target_dir: Optional[Path] = None) -> list[dict]:
    """Verifica el estado y peso actual de los modelos en el directorio de destino."""
    dest_dir = target_dir or DEFAULT_MODELS_DIR
    results = []

    for item in DEFAULT_MODELS:
        filename = item["filename"]
        path = dest_dir / filename
        part_path = dest_dir / (filename + ".part")

        # Comprobar si existe el archivo final o variantes de prueba (como .gguf000)
        exists = path.exists() and path.stat().st_size > 10 * 1024 * 1024
        size_bytes = path.stat().st_size if path.exists() else 0

        # Comprobar archivo parcial
        part_exists = part_path.exists()
        part_size = part_path.stat().st_size if part_exists else 0

        if not exists:
            # Comprobar si existe con extensión renombrada de prueba
            alt_path = dest_dir / (filename + "000")
            if alt_path.exists() and alt_path.stat().st_size > 10 * 1024 * 1024:
                exists = True
                size_bytes = alt_path.stat().st_size
                path = alt_path

        results.append({
            "filename": filename,
            "path": str(path),
            "description": item["description"],
            "exists": exists,
            "size_bytes": size_bytes,
            "size_str": format_bytes(size_bytes) if exists else ("Parcial: " + format_bytes(part_size) if part_exists else "No descargado"),
            "part_exists": part_exists,
            "part_size": part_size,
            "url": item["url"],
        })

    return results


if __name__ == "__main__":
    print("=" * 60)
    print("  DRAPEMIND ATELIER - VERIFICADOR Y DESCARGADOR DE IA")
    print("=" * 60)

    target_directory = DEFAULT_MODELS_DIR
    print(f"Directorio de destino: {target_directory}\n")

    status_list = check_models_status(target_directory)
    for m in status_list:
        state = "[PRESENTE]" if m["exists"] else "[FALTA]"
        print(f"{state} {m['filename']} - {m['size_str']} ({m['description']})")

    missing = [m for m in status_list if not m["exists"]]

    if "--check" in sys.argv:
        if missing:
            print(f"\nFaltan {len(missing)} archivo(s) de modelo.")
            sys.exit(1)
        else:
            print("\nTodos los modelos de IA se encuentran presentes y listos.")
            sys.exit(0)

    if not missing:
        print("\nTodos los modelos de IA se encuentran presentes y listos.")
    else:
        print(f"\nFaltan {len(missing)} archivo(s) de modelo.")
        auto_yes = "-y" in sys.argv or "--yes" in sys.argv
        if not auto_yes:
            ans = input("¿Deseas iniciar la descarga rápida ahora? (s/n): ").strip().lower()
        else:
            ans = "s"

        if ans == "s":
            for m in missing:
                print(f"\nDescargando {m['filename']}...")
                dest = target_directory / m["filename"]

                def _cli_progress(info):
                    if info.get("status") == "downloading":
                        sys.stdout.write(
                            f"\r[{info['percent']:5.1f}%] {info['progress_str']} | Vel: {info['speed_str']} | ETA: {info['eta_str']}    "
                        )
                        sys.stdout.flush()
                    elif info.get("status") == "completed":
                        print(f"\n{info['message']}")
                    elif info.get("status") == "error":
                        print(f"\n✗ Error: {info.get('error')}")

                download_file_fast(m["url"], dest, progress_callback=_cli_progress)
