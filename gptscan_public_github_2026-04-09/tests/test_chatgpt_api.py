import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from chatgpt_api import (
    DEFAULT_OPENROUTER_MODEL,
    LLMAPIError,
    build_openrouter_headers,
    get_completion_api_url,
    record_token_usage,
    request_openrouter_completion,
    resolve_model_name,
    reset_token_counters,
    tokens_received,
    tokens_sent,
)


class ChatApiTests(unittest.TestCase):
    def test_headers_are_ascii_safe(self) -> None:
        headers = build_openrouter_headers("sk-test-key")
        for key, value in headers.items():
            self.assertTrue(key.isascii(), key)
            self.assertTrue(value.isascii(), value)

    def test_default_model_is_openrouter_auto(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            self.assertEqual(DEFAULT_OPENROUTER_MODEL, resolve_model_name())
            self.assertEqual(DEFAULT_OPENROUTER_MODEL, resolve_model_name(use_secondary=True))

    def test_completion_api_url_can_be_overridden(self) -> None:
        with patch.dict("os.environ", {"LLM_API_URL": "https://example.com/v1/chat/completions"}, clear=False):
            self.assertEqual("https://example.com/v1/chat/completions", get_completion_api_url())

    def test_model_name_can_be_overridden_per_slot(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "OPENROUTER_MODEL_PRIMARY": "anthropic/claude-3.5-haiku",
                "OPENROUTER_MODEL_SECONDARY": "google/gemini-2.0-flash-001",
            },
            clear=False,
        ):
            self.assertEqual("anthropic/claude-3.5-haiku", resolve_model_name())
            self.assertEqual("google/gemini-2.0-flash-001", resolve_model_name(use_secondary=True))

    def test_record_token_usage_updates_counters(self) -> None:
        reset_token_counters()
        record_token_usage(12, 7, False)
        self.assertEqual(12, tokens_sent.value)
        self.assertEqual(7, tokens_received.value)

    @patch("chatgpt_api.requests.post")
    def test_request_openrouter_completion_returns_content(self, mock_post: Mock) -> None:
        response = Mock()
        response.status_code = 200
        response.text = '{"choices":[{"message":{"content":"yes"}}]}'
        response.json.return_value = {"choices": [{"message": {"content": "yes"}}]}
        mock_post.return_value = response

        with patch.dict("os.environ", {"LLM_API_URL": "https://example.com/v1/chat/completions"}, clear=False):
            content, usage = request_openrouter_completion(
                api_key="sk-test-key",
                messages=[{"role": "user", "content": "hello"}],
                model_name="openrouter/auto",
            )

        self.assertEqual("yes", content)
        self.assertEqual({"prompt_tokens": 0.0, "completion_tokens": 0.0}, usage)
        self.assertEqual(1, mock_post.call_count)
        self.assertEqual("https://example.com/v1/chat/completions", mock_post.call_args.args[0])

    @patch("chatgpt_api.requests.post")
    def test_request_openrouter_completion_raises_llm_api_failed(self, mock_post: Mock) -> None:
        response = Mock()
        response.status_code = 500
        response.text = "upstream failure"
        response.json.return_value = {"error": {"message": "upstream failure"}}
        mock_post.return_value = response

        with self.assertRaises(LLMAPIError) as ctx:
            request_openrouter_completion(
                api_key="sk-test-key",
                messages=[{"role": "user", "content": "hello"}],
                model_name="openrouter/auto",
            )

        self.assertEqual("llm_api_failed", ctx.exception.error_code)
        self.assertIn("500", str(ctx.exception))

    @patch("chatgpt_api.time.sleep")
    @patch("chatgpt_api.requests.post")
    def test_request_openrouter_completion_retries_transient_request_errors(
        self, mock_post: Mock, mock_sleep: Mock
    ) -> None:
        response = Mock()
        response.status_code = 200
        response.text = '{"choices":[{"message":{"content":"yes"}}]}'
        response.json.return_value = {"choices": [{"message": {"content": "yes"}}]}
        mock_post.side_effect = [
            requests.exceptions.SSLError("EOF occurred in violation of protocol"),
            response,
        ]

        with patch.dict("os.environ", {"LLM_REQUEST_MAX_RETRIES": "2", "LLM_REQUEST_RETRY_BACKOFF_SECONDS": "0"}, clear=False):
            content, usage = request_openrouter_completion(
                api_key="sk-test-key",
                messages=[{"role": "user", "content": "hello"}],
                model_name="openrouter/auto",
            )

        self.assertEqual("yes", content)
        self.assertEqual({"prompt_tokens": 0.0, "completion_tokens": 0.0}, usage)
        self.assertEqual(2, mock_post.call_count)
        self.assertEqual(0, mock_sleep.call_count)

    @patch("chatgpt_api.time.sleep")
    @patch("chatgpt_api.requests.post")
    def test_request_openrouter_completion_raises_after_retry_exhaustion(
        self, mock_post: Mock, mock_sleep: Mock
    ) -> None:
        mock_post.side_effect = requests.exceptions.SSLError("EOF occurred in violation of protocol")

        with patch.dict("os.environ", {"LLM_REQUEST_MAX_RETRIES": "2", "LLM_REQUEST_RETRY_BACKOFF_SECONDS": "0"}, clear=False):
            with self.assertRaises(LLMAPIError) as ctx:
                request_openrouter_completion(
                    api_key="sk-test-key",
                    messages=[{"role": "user", "content": "hello"}],
                    model_name="openrouter/auto",
                )

        self.assertEqual("llm_api_failed", ctx.exception.error_code)
        self.assertIn("Completion API request failed", str(ctx.exception))
        self.assertEqual(2, mock_post.call_count)
        self.assertEqual(0, mock_sleep.call_count)


if __name__ == "__main__":
    unittest.main()
