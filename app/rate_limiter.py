import os
import time
import logging
import redis

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_BROKER_URL", "redis://localhost:6379/0")
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)

# Atomic Lua script executed inside Redis single-threaded engine.
# Calculates token refill based on elapsed time and deducts requested tokens if available.
TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local requested = tonumber(ARGV[3])
local now = tonumber(ARGV[4])

local data = redis.call("HMGET", key, "tokens", "last_refill")
local tokens = tonumber(data[1])
local last_refill = tonumber(data[2])

if tokens == nil then
    tokens = capacity
    last_refill = now
else
    local elapsed = math.max(0, now - last_refill)
    tokens = math.min(capacity, tokens + (elapsed * refill_rate))
    last_refill = now
end

if tokens >= requested then
    tokens = tokens - requested
    redis.call("HMSET", key, "tokens", tokens, "last_refill", last_refill)
    redis.call("EXPIRE", key, 120)
    return {1, 0}
else
    local deficit = requested - tokens
    local wait_seconds = deficit / refill_rate
    redis.call("HMSET", key, "tokens", tokens, "last_refill", last_refill)
    redis.call("EXPIRE", key, 120)
    return {0, tostring(wait_seconds)}
end
"""

_consume_bucket = redis_client.register_script(TOKEN_BUCKET_LUA)


def acquire_rate_limit(
    provider: str,
    rpm_limit: int,
    tpm_limit: int,
    estimated_tokens: int = 1000,
    max_wait: float = 60.0,
) -> None:
    """
    Blocks the current worker until both 1 Request (RPM) and `estimated_tokens` (TPM)
    are available in the global Redis Token Bucket for `provider`.
    """
    rpm_key = f"rate_limit:{provider}:rpm"
    tpm_key = f"rate_limit:{provider}:tpm"

    rpm_refill_per_sec = rpm_limit / 60.0
    tpm_refill_per_sec = tpm_limit / 60.0

    # Cap requested tokens at bucket capacity so a single large batch never deadlocks
    requested_tokens = min(estimated_tokens, tpm_limit)
    start_time = time.monotonic()

    while True:
        now = time.time()
        rpm_ok, rpm_wait = _consume_bucket(
            keys=[rpm_key],
            args=[rpm_limit, rpm_refill_per_sec, 1, now],
        )
        tpm_ok, tpm_wait = _consume_bucket(
            keys=[tpm_key],
            args=[tpm_limit, tpm_refill_per_sec, requested_tokens, now],
        )

        if int(rpm_ok) == 1 and int(tpm_ok) == 1:
            return

        wait_time = max(float(rpm_wait), float(tpm_wait), 0.25)
        if (time.monotonic() - start_time) + wait_time > max_wait:
            raise TimeoutError(f"Global rate limiter timeout waiting for {provider} capacity.")

        logger.info(f"Rate limit throttling [{provider}]: sleeping {wait_time:.2f}s for global bucket refill...")
        time.sleep(wait_time)