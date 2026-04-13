import logging
import os
import time
from multiprocessing import Value
from typing import Dict, List, Tuple

import requests
import rich
import rich_utils

from scan_exceptions import LLMAPIError

logger = logging.getLogger(__name__)
console = rich.get_console()

SYSTEM_MESSAGE = (
    "You are a smart contract auditor. You will be asked questions related to code "
    "properties. You can mimic answering them in the background five times and "
    "provide me with the most frequently appearing answer. Furthermore, please "
    "strictly adhere to the output format specified in the question; there is no "
    "need to explain your answer."
)
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_OPENROUTER_MODEL = "openrouter/auto"
PRIMARY_MODEL_ENV = "OPENROUTER_MODEL_PRIMARY"
SECONDARY_MODEL_ENV = "OPENROUTER_MODEL_SECONDARY"
API_URL_ENV = "LLM_API_URL"
MAX_RETRIES_ENV = "LLM_REQUEST_MAX_RETRIES"
RETRY_BACKOFF_ENV = "LLM_REQUEST_RETRY_BACKOFF_SECONDS"

try:
    import tiktoken
except ImportError:  # pragma: no cover - exercised only when dependency is absent
    tiktoken = None


def _encode_len(text: str) -> int:
    if tiktoken is None:
        return len(text.split())
    encoder = tiktoken.encoding_for_model("gpt-3.5-turbo")
    return len(encoder.encode(text))


tokens_sent = Value("d", 0)
tokens_received = Value("d", 0)
tokens_sent_gpt4 = Value("d", 0)
tokens_received_gpt4 = Value("d", 0)


def reset_token_counters() -> None:
    for counter in (
        tokens_sent,
        tokens_received,
        tokens_sent_gpt4,
        tokens_received_gpt4,
    ):
        counter.value = 0


def record_token_usage(prompt_tokens: float, completion_tokens: float, gpt4: bool = False) -> None:
    if gpt4:
        tokens_sent_gpt4.value += prompt_tokens
        tokens_received_gpt4.value += completion_tokens
    else:
        tokens_sent.value += prompt_tokens
        tokens_received.value += completion_tokens


def _validate_ascii_header_value(name: str, value: str) -> str:
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise LLMAPIError(
            f"Header {name} contains non-ASCII characters and cannot be sent safely."
        ) from exc
    return value


def build_openrouter_headers(api_key: str) -> Dict[str, str]:
    if not api_key:
        raise LLMAPIError("OPENAI_API_KEY is missing for completion API requests.")
    authorization = _validate_ascii_header_value("Authorization", f"Bearer {api_key.strip()}")
    return {
        "Authorization": authorization,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def get_completion_api_url() -> str:
    return os.environ.get(API_URL_ENV, "").strip() or OPENROUTER_API_URL


def get_max_request_retries() -> int:
    try:
        return max(1, int(os.environ.get(MAX_RETRIES_ENV, "3")))
    except ValueError:
        return 3


def get_retry_backoff_seconds() -> float:
    try:
        return max(0.0, float(os.environ.get(RETRY_BACKOFF_ENV, "2")))
    except ValueError:
        return 2.0


def resolve_model_name(use_secondary: bool = False) -> str:
    env_var = SECONDARY_MODEL_ENV if use_secondary else PRIMARY_MODEL_ENV
    return os.environ.get(env_var, "").strip() or DEFAULT_OPENROUTER_MODEL


def request_openrouter_completion(
    *,
    api_key: str | None,
    messages: List[Dict[str, str]],
    model_name: str,
    timeout: int = 90,
) -> Tuple[str, Dict[str, float]]:
    api_url = get_completion_api_url()
    headers = build_openrouter_headers(api_key or os.environ.get("OPENAI_API_KEY", ""))
    max_retries = get_max_request_retries()
    backoff_seconds = get_retry_backoff_seconds()
    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": 0,
        "top_p": 1.0,
    }

    response = None
    last_exception = None
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(
                api_url,
                headers=headers,
                json=payload,
                timeout=timeout,
            )
            break
        except requests.exceptions.RequestException as exc:
            last_exception = exc
            logger.warning(
                "Completion API request attempt %s/%s failed before receiving a response: %s",
                attempt,
                max_retries,
                exc,
            )
            if attempt >= max_retries:
                logger.error("Completion API request failed before receiving a response: %s", exc)
                raise LLMAPIError(f"Completion API request failed: {exc}") from exc
            if backoff_seconds > 0:
                time.sleep(backoff_seconds * attempt)

    if response is None:
        raise LLMAPIError(f"Completion API request failed: {last_exception}")

    logger.info("Completion API HTTP status: %s", response.status_code)
    if response.status_code >= 400:
        logger.error("Completion API response text: %s", response.text)
        raise LLMAPIError(
            f"Completion API request failed with status {response.status_code}",
            status_code=response.status_code,
            response_text=response.text,
        )

    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
    except Exception as exc:
        logger.error("Completion API returned invalid JSON payload: %s", response.text)
        raise LLMAPIError(
            "Completion API returned an invalid completion payload.",
            status_code=response.status_code,
            response_text=response.text,
        ) from exc

    logger.info("Completion API content: %s", content)
    usage = data.get("usage", {}) if isinstance(data, dict) else {}
    return content, {
        "prompt_tokens": float(usage.get("prompt_tokens", 0) or 0),
        "completion_tokens": float(usage.get("completion_tokens", 0) or 0),
    }


class Chat:
    def __init__(self) -> None:
        self.currentSession: List[Dict[str, str]] = []

    def newSession(self) -> None:
        self.currentSession = []

    def sendMessagesWithUsage(self, message: str, GPT4: bool = False) -> Dict[str, float | str | bool]:
        messages = [{"role": "system", "content": SYSTEM_MESSAGE}]
        messages.extend(self.currentSession)
        messages.append({"role": "user", "content": message})

        model_name = resolve_model_name(use_secondary=GPT4)
        content, usage = request_openrouter_completion(
            api_key=os.environ.get("OPENAI_API_KEY"),
            messages=messages,
            model_name=model_name,
        )

        self.currentSession.append({"role": "user", "content": message})
        self.currentSession.append({"role": "assistant", "content": content})
        console.print(rich_utils.make_response_panel(content, "Response"))
        return {
            "content": content,
            "prompt_tokens": usage["prompt_tokens"],
            "completion_tokens": usage["completion_tokens"],
            "gpt4": GPT4,
        }

    def sendMessages(self, message: str, GPT4: bool = False) -> str:
        payload = self.sendMessagesWithUsage(message, GPT4)
        prompt_tokens = float(payload.get("prompt_tokens", 0) or 0)
        completion_tokens = float(payload.get("completion_tokens", 0) or 0)
        if prompt_tokens == 0 and completion_tokens == 0:
            prompt_tokens = _encode_len(SYSTEM_MESSAGE) + _encode_len(message)
            completion_tokens = _encode_len(str(payload["content"]))
        record_token_usage(prompt_tokens, completion_tokens, GPT4)
        return str(payload["content"])

    def makeYesOrNoQuestion(self, question: str) -> str:
        return f"{question}. Please answer in one word, yes or no."

    def makeCodeQuestion(self, question: str, code: str):
        return f'Please analyze the following code, and answer the question "{question}"\n{code}'
