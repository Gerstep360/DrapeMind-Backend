import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from app.services import ai, ai_agent
from app.services.agent_stream import partial_answer


def test_partial_answer_never_exposes_tool_reason():
    assert partial_answer('{"type":"tool","reason":"buscar","arguments":{}}') == ""
    assert partial_answer('{"type":"finish","answer":"Primera línea') == "Primera línea"
    raw = json.dumps({"type": "finish", "answer": 'Una "camisa"\nAzul'}, ensure_ascii=False)
    assert partial_answer(raw) == 'Una "camisa"\nAzul'


def test_nested_protocol_recovery():
    decision = ai_agent._json_decision('JSON: {"type":"tool","tool":"example","arguments":{"nested":{"id":2}}}')
    assert decision["arguments"]["nested"]["id"] == 2


def test_stream_reads_real_deltas(monkeypatch):
    observed = []
    payloads = []
    real_client = httpx.AsyncClient
    def handler(request):
        payloads.append(json.loads(request.content))
        body = "".join(
            "data: " + json.dumps({"choices": [{"delta": {"content": part}}]}) + "\n\n"
            for part in ['{"type":"finish",', '"answer":"Listo"}']
        ) + "data: [DONE]\n\n"
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
    monkeypatch.setattr(ai.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler)))
    async def on_text(value):
        observed.append(value)
    result = asyncio.run(ai._completion([{"role": "user", "content": "Consulta independiente"}], on_text=on_text))
    assert len(observed) == 2
    assert payloads[0]["stream"] is True
    assert result["choices"][0]["message"]["content"] == observed[-1]


def test_dynamic_capabilities_and_suggestions(monkeypatch):
    monkeypatch.setattr(ai_agent, "tool_catalog", lambda: [
        {"name": "inspect_material", "description": "Consultar composición textil",
         "parameters": {"properties": {}, "required": []}}
    ])
    async def complete(messages, **kwargs):
        assert "inspect_material" in messages[1]["content"]
        return {"choices": [{"message": {"content": json.dumps({
            "type": "finish", "answer": "Puedo consultar la composición.",
            "suggested_actions": [{"label": "Composición", "prompt": "¿Qué materiales puedes consultar?"}]
        })}}]}
    result = asyncio.run(ai_agent.run_gemma_tool_agent(MagicMock(), SimpleNamespace(id=1), "¿Cómo me ayudas?", {}, complete))
    assert result["suggested_actions"][0]["label"] == "Composición"
    assert result["tool_args"]["steps"] == 0


def test_inference_failure_is_not_success():
    async def complete(*args, **kwargs):
        raise TimeoutError("inference timeout")
    with pytest.raises(TimeoutError):
        asyncio.run(ai_agent.run_gemma_tool_agent(MagicMock(), SimpleNamespace(id=1), "Consulta distinta", {}, complete))


def test_timeout_has_a_useful_message(monkeypatch):
    real_client = httpx.AsyncClient
    def handler(request):
        raise httpx.ReadTimeout("slow inference")
    monkeypatch.setattr(ai.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler)))
    async def on_text(value):
        pass
    with pytest.raises(ai.ModelRuntimeError, match="excedió el tiempo"):
        asyncio.run(ai._completion([{"role": "user", "content": "Prueba"}], on_text=on_text))


def test_valid_decision_does_not_wait_for_stream_end(monkeypatch):
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            answer = '{"type":"finish","answer":"Respuesta completa"}'
            yield ("data: " + json.dumps({"choices": [{"delta": {"content": answer}}]}) + "\n\n").encode()
            raise AssertionError("Should close immediately after a complete decision")
    real_client = httpx.AsyncClient
    monkeypatch.setattr(ai.httpx, "AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Stream()))))
    async def on_text(value):
        pass
    result = asyncio.run(ai._completion([{"role": "user", "content": "Prueba"}],
        response_format={"type": "json_object"}, on_text=on_text))
    assert result["choices"][0]["finish_reason"] == "stop"
