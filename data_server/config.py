import os

def int_env(name: str, default: int, *, min_value: int | None = None, max_value: int | None = None) -> int:
    """
    Read an env var and convert to int, with optional range validation.
    Falls back to `default` if var is unset or its parsing fails.
    """
    raw = os.getenv(name, default)
    try:
        value = int(raw)
    except (ValueError, TypeError):
        value = int(default)

    if min_value is not None and value < min_value:
        value = min_value
    if max_value is not None and value > max_value:
        value = max_value
    return value

# Simulator settings
DATA_SWITCHES    = int_env("DATA_SWITCHES", 64, min_value=1)          # at least 1 switch
DATA_INTERVAL_SEC= int_env("DATA_INTERVAL_SEC", 10, min_value=1)      # enforce >= 1s

# Fault injection
FAULT_500_PCT    = int_env("FAULT_500_PCT", 0, min_value=0, max_value=100)  # clamp to [0,100]
FAULT_SLOW_MS    = int_env("FAULT_SLOW_MS", 0, min_value=0)                 # no negative delays

# Server bind & logging 
BIND_HOST = os.getenv("BIND_HOST", "0.0.0.0")
PORT      = int_env("PORT", 9001, min_value=1, max_value=65535)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
