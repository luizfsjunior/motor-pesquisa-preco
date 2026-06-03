import asyncio
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from loguru import logger

T = TypeVar("T")


def async_retry(
    max_attempts: int = 3,
    delay_seconds: float = 2.0,
    backoff: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception | None = None
            wait = delay_seconds
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        break
                    logger.warning(
                        "Retry {}/{} for {}: {}",
                        attempt,
                        max_attempts,
                        func.__name__,
                        exc,
                    )
                    await asyncio.sleep(wait)
                    wait *= backoff
            raise last_exc  # type: ignore[misc]

        return wrapper

    return decorator
