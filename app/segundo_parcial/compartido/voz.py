"""CU-25/CU-29 microphone input; audio is validated in memory, never persisted."""

import base64, binascii, io, wave
from threading import BoundedSemaphore
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import User, Role
from app.core.config import settings
from app.services.saas import require_active_subscription

router = APIRouter(prefix="/voice", tags=["CU-25 / CU-29 · Entrada de voz"])
capacity = BoundedSemaphore(2)


class VoiceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audio_wav: str = Field(min_length=60, max_length=2_600_000)
    proposito: Literal["ALTAIR", "REPORTE"] = "ALTAIR"


def audio_samples(encoded):
    try:
        content = base64.b64decode(encoded, validate=True)
        with wave.open(io.BytesIO(content), "rb") as audio:
            if (
                audio.getnchannels() != 1
                or audio.getsampwidth() != 2
                or audio.getframerate() != 16000
                or audio.getcomptype() != "NONE"
            ):
                raise ValueError("format")
            if not 3200 <= audio.getnframes() <= 960000:
                raise ValueError("duration")
            samples = audio.readframes(audio.getnframes())
            if len(samples) != audio.getnframes() * 2:
                raise ValueError("truncated")
        if not any(samples):
            raise ValueError("silence")
        return samples
    except (ValueError, binascii.Error, wave.Error, EOFError) as exc:
        raise HTTPException(
            422,
            "Graba entre 0,2 y 60 segundos de voz. Se requiere audio WAV mono a 16 kHz.",
        ) from exc


def recognize(samples):
    import riva.client
    from riva.client.asr import streaming_request_generator

    auth = riva.client.Auth(
        uri=settings.NVIDIA_ASR_SERVER,
        use_ssl=True,
        metadata_args=[
            ["authorization", "Bearer " + settings.NVIDIA_API_KEY],
            ["function-id", settings.NVIDIA_ASR_FUNCTION_ID],
        ],
    )
    try:
        config = riva.client.RecognitionConfig(
            encoding=riva.client.AudioEncoding.LINEAR_PCM,
            sample_rate_hertz=16000,
            language_code=settings.NVIDIA_ASR_LANGUAGE,
            max_alternatives=1,
            enable_automatic_punctuation=True,
            audio_channel_count=1,
        )
        stream = riva.client.StreamingRecognitionConfig(
            config=config, interim_results=False
        )
        requests = streaming_request_generator(
            (samples[i : i + 3200] for i in range(0, len(samples), 3200)), stream
        )
        results = riva.client.ASRService(auth).stub.StreamingRecognize(
            requests, metadata=auth.get_auth_metadata(), timeout=30
        )
        return " ".join(
            r.alternatives[0].transcript.strip()
            for result in results
            for r in result.results
            if r.is_final and r.alternatives
        ).strip()
    except Exception as exc:
        raise HTTPException(
            503,
            "No pudimos transcribir la voz con NVIDIA. Conserva tu consulta y vuelve a intentarlo.",
        ) from exc
    finally:
        auth.channel.close()


@router.post("/transcribe")
def transcribe(
    payload: VoiceInput,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    if payload.proposito == "REPORTE":
        if user.rol != Role.ADMIN or "reports.ai" not in user.permisos:
            raise HTTPException(
                403, "Tu cuenta no tiene habilitados los reportes con IA"
            )
        require_active_subscription(db, user.tenant_id, "ai_reports")
    elif "catalog.read" not in user.permisos:
        raise HTTPException(403, "Tu cuenta no tiene acceso a Altair")
    samples = audio_samples(payload.audio_wav)
    if not settings.NVIDIA_API_KEY:
        raise HTTPException(503, "Configura NVIDIA antes de utilizar la entrada de voz")
    if not capacity.acquire(blocking=False):
        raise HTTPException(
            429, "Hay otras consultas de voz en curso. Reintenta en unos segundos."
        )
    try:
        text = recognize(samples)
    finally:
        capacity.release()
    if not text:
        raise HTTPException(
            422,
            "No distinguimos palabras. Acércate al micrófono y vuelve a intentarlo.",
        )
    return {
        "texto": text[:2000],
        "proveedor": "NVIDIA",
        "idioma": "auto",
        "requiere_revision": True,
    }
