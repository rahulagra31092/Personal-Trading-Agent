"""
Timeout decorator for API calls — prevents hanging requests.

Wraps external API calls (yfinance, Polygon, etc.) with timeout enforcement.
If call exceeds time limit, returns None or default value instead of hanging.
"""
import logging
import time
from functools import wraps
from typing import Any, Callable, Optional, TypeVar
from threading import Thread

logger = logging.getLogger(__name__)

T = TypeVar('T')


class TimeoutError(Exception):
    """Raised when a function call exceeds its timeout."""
    pass


def timeout(seconds: int = 15, default: Any = None):
    """
    Decorator to enforce timeout on function calls (thread-based, Windows-compatible).

    Args:
        seconds: Timeout in seconds (default 15)
        default: Default value to return if timeout (default None)

    Usage:
        @timeout(15, default=0.5)
        def compute_signal():
            ...

    Note: Uses threading rather than signals for cross-platform compatibility.
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            result_container = {"result": default, "finished": False}
            exception_container = {"exception": None}

            def target():
                try:
                    result_container["result"] = func(*args, **kwargs)
                    result_container["finished"] = True
                except Exception as e:
                    exception_container["exception"] = e
                    result_container["finished"] = True

            thread = Thread(target=target, daemon=True)
            thread.start()
            thread.join(timeout=seconds)

            if result_container["finished"]:
                if exception_container["exception"]:
                    logger.error(f"Exception in {func.__name__}: {exception_container['exception']}")
                    return default
                return result_container["result"]
            else:
                logger.error(f"Timeout on {func.__name__} (exceeded {seconds}s)")
                return default

        return wrapper
    return decorator


def timeout_with_retry(
    seconds: int = 15,
    max_retries: int = 2,
    backoff_factor: float = 1.5,
    default: Any = None
):
    """
    Decorator with exponential backoff retry.

    Args:
        seconds: Initial timeout in seconds
        max_retries: Number of retries (exponential backoff)
        backoff_factor: Multiply timeout by this each retry
        default: Default value if all retries fail

    Usage:
        @timeout_with_retry(15, max_retries=2, backoff_factor=1.5)
        def fetch_data():
            ...
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            current_timeout = seconds
            last_error = None

            for attempt in range(max_retries + 1):
                try:
                    def timeout_handler(signum, frame):
                        raise TimeoutError(f"{func.__name__} exceeded {current_timeout}s timeout (attempt {attempt + 1})")

                    old_handler = signal.signal(signal.SIGALRM, timeout_handler)
                    signal.alarm(current_timeout)

                    try:
                        result = func(*args, **kwargs)
                        signal.alarm(0)
                        return result
                    except TimeoutError as e:
                        last_error = e
                        if attempt < max_retries:
                            logger.warning(f"{func.__name__} timed out, retrying with {current_timeout * backoff_factor:.0f}s timeout")
                            current_timeout = int(current_timeout * backoff_factor)
                            time.sleep(0.5)  # Brief pause before retry
                        else:
                            raise
                    finally:
                        signal.alarm(0)
                        signal.signal(signal.SIGALRM, old_handler)
                except TimeoutError as e:
                    last_error = e
                    if attempt == max_retries:
                        logger.error(f"{func.__name__} failed after {max_retries + 1} attempts: {e}")
                        return default

            return default

        return wrapper
    return decorator


# Common timeout presets
TIMEOUT_YFINANCE = 15  # yfinance data fetch
TIMEOUT_API = 10       # Generic API calls
TIMEOUT_WEB = 5        # Web scraping


def with_yfinance_timeout(func: Callable[..., T]) -> Callable[..., T]:
    """Apply yfinance timeout (15s)."""
    return timeout(TIMEOUT_YFINANCE, default=None)(func)


def with_api_timeout(func: Callable[..., T]) -> Callable[..., T]:
    """Apply API timeout (10s)."""
    return timeout(TIMEOUT_API, default=None)(func)
