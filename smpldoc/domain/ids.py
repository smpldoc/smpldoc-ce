import os
import time


def new_id() -> str:
    """Time-ordered id: 12 hex chars of milliseconds, then 20 hex chars of randomness."""
    return f"{int(time.time() * 1000):012x}{os.urandom(10).hex()}"
