import time
from dataclasses import dataclass

import redis

from app.config import get_settings


class RateLimitBudgetExceeded(Exception):
    """Raised when the Redis token bucket cannot grant budget within the wait window."""


# Atomic dual-bucket (RPM + TPM) refill & consume Lua script.
# KEYS[1] = rpm_key, KEYS[2] = tpm_key
# ARGV[1] = rpm_capacity, ARGV[2] = rpm_refill_per_sec
# ARGV[3] = tpm_capacity, ARGV[4] = tpm_refill_per_sec
# ARGV[5] = requested_rpm (1), ARGV[6] = requested_tpm
# ARGV[7] = current_unix_timestamp (float)
_TOKEN_BUCKET_LUA = """
local rpm_key = KEYS[1]
local tpm_key = KEYS[2]

local rpm_cap = tonumber(ARGV[1])
local rpm_rate = tonumber(ARGV[2])
local tpm_cap = tonumber(ARGV[3])
local tpm_rate = tonumber(ARGV[4])
local req_rpm = tonumber(ARGV[5])
local req_tpm = tonumber(ARGV[6])
local now = tonumber(ARGV[7])

local function read_bucket(key, cap, rate)
  local data = redis.call("HMGET", key, "tokens", "ts")
  local tokens = tonumber(data[1])
  local ts = tonumber(data[2])
  if tokens == nil or ts == nil then
    return cap, now
  end
  local elapsed = math.max(0, now - ts)
  local refilled = math.min(cap, tokens + elapsed * rate)
  return refilled, now
end

local rpm_tokens, _ = read_bucket(rpm_key, rpm_cap, rpm_rate)
local tpm_tokens, _ = read_bucket(tpm_key, tpm_cap, tpm_rate)

if rpm_tokens >= req_rpm and tpm_tokens >= req_tpm then
  rpm_tokens = rpm_tokens - req_rpm
  tpm_tokens = tpm_tokens - req_tpm
  redis.call("HSET", rpm_key, "tokens", rpm_tokens, "ts", now)
  redis.call("HSET", tpm_key, "tokens", tpm_tokens, "ts", now)
  redis.call("EXPIRE", rpm_key, 120)
  redis.call("EXPIRE", tpm_key, 120)
  return {1, 0}
end

local rpm_wait = 0
if rpm_tokens < req_rpm then
  rpm_wait = (req_rpm - rpm_tokens) / rpm_rate
end

local tpm_wait = 0
if tpm_tokens < req_tpm then
  tpm_wait = (req_tpm - tpm_tokens) / tpm_rate
end

local wait_sec = math.max(rpm_wait, tpm_wait)
return {0, tostring(wait_sec)}
"""


@dataclass(frozen=True)
class BucketConfig:
    namespace: str
    rpm_limit: int
    tpm_limit: int


class RedisTokenBucket:
    """Global distributed RPM + TPM Token Bucket backed by Redis Lua atomicity."""

    def __init__(
        self,
        config: BucketConfig,
        redis_client: redis.Redis | None = None,
    ) -> None:
        self.config = config
        if redis_client is not None:
            self.redis = redis_client
        else:
            settings = get_settings()
            self.redis = redis.Redis.from_url(settings.redis_rate_limit_url, decode_responses=True)
        self._script = self.redis.register_script(_TOKEN_BUCKET_LUA)

    @property
    def rpm_key(self) -> str:
        return f"ratelimit:{self.config.namespace}:rpm"

    @property
    def tpm_key(self) -> str:
        return f"ratelimit:{self.config.namespace}:tpm"

    def try_acquire(self, tokens: int = 1, requests: int = 1, now: float | None = None) -> tuple[bool, float]:
        """Attempt one non-blocking atomic acquire. Returns (allowed, wait_seconds)."""
        req_tokens = max(1, min(tokens, self.config.tpm_limit))
        req_requests = max(1, min(requests, self.config.rpm_limit))
        rpm_rate = self.config.rpm_limit / 60.0
        tpm_rate = self.config.tpm_limit / 60.0
        timestamp = now if now is not None else time.time()

        allowed, wait_raw = self._script(
            keys=[self.rpm_key, self.tpm_key],
            args=[
                self.config.rpm_limit,
                rpm_rate,
                self.config.tpm_limit,
                tpm_rate,
                req_requests,
                req_tokens,
                timestamp,
            ],
        )
        return bool(int(allowed)), float(wait_raw)

    def acquire(self, tokens: int = 1, requests: int = 1, timeout_seconds: float = 30.0) -> None:
        """Block up to timeout_seconds until global RPM & TPM budget is available."""
        deadline = time.monotonic() + timeout_seconds
        while True:
            allowed, wait_sec = self.try_acquire(tokens=tokens, requests=requests)
            if allowed:
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RateLimitBudgetExceeded(
                    f"Global rate-limit budget exhausted for {self.config.namespace} "
                    f"(needed ~{wait_sec:.2f}s)."
                )
            time.sleep(min(max(wait_sec, 0.05), remaining, 2.0))


def get_llm_rate_limiter(redis_client: redis.Redis | None = None) -> RedisTokenBucket:
    settings = get_settings()
    return RedisTokenBucket(
        BucketConfig(
            namespace="llm",
            rpm_limit=settings.llm_rpm_limit,
            tpm_limit=settings.llm_tpm_limit,
        ),
        redis_client=redis_client,
    )


def get_embedding_rate_limiter(redis_client: redis.Redis | None = None) -> RedisTokenBucket:
    settings = get_settings()
    return RedisTokenBucket(
        BucketConfig(
            namespace="embedding",
            rpm_limit=settings.embedding_rpm_limit,
            tpm_limit=settings.embedding_tpm_limit,
        ),
        redis_client=redis_client,
    )
