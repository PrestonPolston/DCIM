"""N-4: a pydantic ValidationError's str() contains `input_value=...` (which may be a submitted secret).
Nothing logs those today; this filter makes sure that if anything ever does, the values are redacted."""
import logging
import re

_INPUT = re.compile(r"input_value=(?:'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|\{.*?\}|\[.*?\]|[^,\]\s]+)", re.S)


def redact(text: str) -> str:
    return _INPUT.sub("input_value=<redacted>", text)


class RedactValidationInput(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        if "input_value=" in msg:
            record.msg, record.args = redact(msg), None
        if record.exc_info and record.exc_info[1] is not None and "input_value=" in str(record.exc_info[1]):
            record.msg = redact(f"{record.getMessage()} | {record.exc_info[1]!s}")
            record.args, record.exc_info, record.exc_text = None, None, None
        return True


_FILTER = RedactValidationInput()


def install_log_redaction() -> None:
    root = logging.getLogger()
    for logger in (root, *(logging.getLogger(n) for n in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi", "app"))):
        if _FILTER not in logger.filters:
            logger.addFilter(_FILTER)
    for h in root.handlers:
        if _FILTER not in h.filters:
            h.addFilter(_FILTER)
