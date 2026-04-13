class GPTScanError(Exception):
    def __init__(self, message: str, *, error_code: str):
        super().__init__(message)
        self.error_code = error_code


class CompileFailure(GPTScanError):
    def __init__(self, message: str):
        super().__init__(message, error_code="compile_failed")


class ParseFailure(GPTScanError):
    def __init__(self, message: str):
        super().__init__(message, error_code="parse_failed")


class LLMAPIError(GPTScanError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_text: str | None = None,
    ):
        super().__init__(message, error_code="llm_api_failed")
        self.status_code = status_code
        self.response_text = response_text
