import logging
import sys

from app.core.request_id import current_request_id


class RequestIDFilter(logging.Filter):
    """Adds the active request id to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = current_request_id()
        return True


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIDFilter())

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | request_id=%(request_id)s | %(name)s | %(message)s",
        handlers=[handler],
        force=True,
    )

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
