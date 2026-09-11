import json
import unittest
from unittest.mock import patch
from app.services.ai_logger import AILogger


class AILoggerTests(unittest.TestCase):
    def setUp(self):
        self.logger = AILogger()

    @patch.object(AILogger, "_write_file")
    def test_log_new_message(self, mock_write):
        self.logger.log_new_message(
            chat_id=10,
            user_id=1,
            user_name="Carlos",
            message="Hola Altair, recomiéndame una camisa blanca",
            scout_enabled=True,
        )
        self.assertTrue(mock_write.called)
        written_content = mock_write.call_args[0][1]
        self.assertIn("[NUEVO MENSAJE]", written_content)
        self.assertIn("Chat: #10", written_content)
        self.assertIn("[AI_AUDIT]", written_content)
        self.assertIn('"event": "new_message"', written_content)

    @patch.object(AILogger, "_write_file")
    def test_log_scout_decision(self, mock_write):
        usage = {"prompt_tokens": 120, "completion_tokens": 35}
        timings = {"predicted_per_second": 24.5, "prompt_ms": 150}
        self.logger.log_scout_decision(
            chat_id=10,
            step=1,
            decision_type="finish",
            decision_detail="Respuesta directa al cliente",
            usage=usage,
            timings=timings,
            duration_ms=850.0,
        )
        self.assertTrue(mock_write.called)
        written_content = mock_write.call_args[0][1]
        self.assertIn("[SCOUT ATENDIÓ DIRECTAMENTE]", written_content)
        self.assertIn("Prompt=120", written_content)
        self.assertIn("24.5 T/s", written_content)
        self.assertIn('"route": "finish"', written_content)

    @patch.object(AILogger, "_write_file")
    def test_log_gemma_inference(self, mock_write):
        usage = {"prompt_tokens": 450, "completion_tokens": 180}
        timings = {"predicted_per_second": 18.2}
        self.logger.log_gemma_inference(
            chat_id=10,
            ttft_seconds=0.75,
            total_seconds=9.8,
            usage=usage,
            timings=timings,
            reasoning_chars=60,
            finish_reason="stop",
            model_name="google/gemma-4-E2B-it",
        )
        self.assertTrue(mock_write.called)
        written_content = mock_write.call_args[0][1]
        self.assertIn("[GEMMA 4 - INFERENCIA MODELO GRANDE]", written_content)
        self.assertIn("TTFT", written_content)
        self.assertIn("18.2 T/s", written_content)
        self.assertIn("180 tokens", written_content)

    @patch.object(AILogger, "_write_file")
    def test_log_turn_summary(self, mock_write):
        scout_tokens = {"prompt": 200, "completion": 50}
        gemma_tokens = {"prompt": 500, "completion": 150}
        self.logger.log_turn_summary(
            chat_id=10,
            user_name="Carlos",
            duration_ms=11500.0,
            routing_mode="scout_delegated",
            scout_calls=2,
            gemma_calls=1,
            tools_used=["consultar_catalogo"],
            scout_tokens=scout_tokens,
            gemma_tokens=gemma_tokens,
        )
        self.assertTrue(mock_write.called)
        written_content = mock_write.call_args[0][1]
        self.assertIn("[TURNO COMPLETADO]", written_content)
        self.assertIn("TOTAL CONSUMIDO:       900 tokens", written_content)
        self.assertIn("consultar_catalogo", written_content)
        self.assertIn('"event": "turn_summary"', written_content)


if __name__ == "__main__":
    unittest.main()
