import pytest

from app.rate_limiter import BucketConfig, RateLimitBudgetExceeded, RedisTokenBucket


class FakeLuaRedis:
    """In-memory fake implementing register_script for deterministic token-bucket tests."""

    def __init__(self) -> None:
        self.buckets: dict[str, tuple[float, float]] = {}

    def register_script(self, _lua: str):
        parent = self

        def _call(keys: list[str], args: list[float | int]) -> list[int | str]:
            rpm_key, tpm_key = keys
            rpm_cap = float(args[0])
            rpm_rate = float(args[1])
            tpm_cap = float(args[2])
            tpm_rate = float(args[3])
            req_rpm = float(args[4])
            req_tpm = float(args[5])
            now = float(args[6])

            def read(k: str, cap: float, rate: float) -> float:
                if k not in parent.buckets:
                    return cap
                toks, ts = parent.buckets[k]
                return min(cap, toks + max(0.0, now - ts) * rate)

            rpm_tokens = read(rpm_key, rpm_cap, rpm_rate)
            tpm_tokens = read(tpm_key, tpm_cap, tpm_rate)

            if rpm_tokens >= req_rpm and tpm_tokens >= req_tpm:
                parent.buckets[rpm_key] = (rpm_tokens - req_rpm, now)
                parent.buckets[tpm_key] = (tpm_tokens - req_tpm, now)
                return [1, "0"]

            rpm_wait = (req_rpm - rpm_tokens) / rpm_rate if rpm_tokens < req_rpm else 0.0
            tpm_wait = (req_tpm - tpm_tokens) / tpm_rate if tpm_tokens < tpm_rpm_val(tpm_tokens, req_tpm) else 0.0
            return [0, str(max(rpm_wait, tpm_wait))]

        def tpm_rpm_val(_t: float, r: float) -> float:
            return r

        return _call


def test_token_bucket_enforces_rpm_and_tpm_and_refills() -> None:
    fake_redis = FakeLuaRedis()
    bucket = RedisTokenBucket(
        BucketConfig(namespace="llm", rpm_limit=2, tpm_limit=100),
        redis_client=fake_redis,  # type: ignore[arg-type]
    )

    allowed1, _ = bucket.try_acquire(tokens=40, requests=1, now=1000.0)
    allowed2, _ = bucket.try_acquire(tokens=40, requests=1, now=1000.0)
    allowed3, wait3 = bucket.try_acquire(tokens=10, requests=1, now=1000.0)

    assert allowed1 is True
    assert allowed2 is True
    assert allowed3 is False
    assert wait3 > 0.0

    # After 30 seconds, 1 RPM and 50 TPM refill -> next request allowed
    allowed4, _ = bucket.try_acquire(tokens=20, requests=1, now=1030.0)
    assert allowed4 is True


def test_token_bucket_raises_on_timeout_when_saturated() -> None:
    fake_redis = FakeLuaRedis()
    bucket = RedisTokenBucket(
        BucketConfig(namespace="embedding", rpm_limit=1, tpm_limit=100),
        redis_client=fake_redis,  # type: ignore[arg-type]
    )

    assert bucket.try_acquire(tokens=10, requests=1)[0] is True
    with pytest.raises(RateLimitBudgetExceeded):
        bucket.acquire(tokens=10, requests=1, timeout_seconds=0.05)
