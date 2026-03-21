"""速率限制器"""
import asyncio
import time
from collections import deque
from typing import Dict, Optional
import logging

logger = logging.getLogger("openfish.ratelimit")


class TokenBucket:
    """令牌桶算法"""

    def __init__(self, rate: int, capacity: int):
        self.rate = rate  # 每秒生成令牌数
        self.capacity = capacity  # 桶容量
        self.tokens = capacity
        self.last_time = time.time()

    async def acquire(self) -> bool:
        """获取令牌"""
        now = time.time()
        elapsed = now - self.last_time
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_time = now

        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False

    def available(self) -> int:
        """可用令牌数"""
        now = time.time()
        elapsed = now - self.last_time
        return min(self.capacity, int(self.tokens + elapsed * self.rate))


class SlidingWindowCounter:
    """滑动窗口计数器"""

    def __init__(self, window_seconds: int = 60):
        self.window = window_seconds
        self.timestamps: deque = deque()
        self.values: deque = deque()
        self.total = 0

    def add(self, value: int = 1) -> None:
        """添加值"""
        now = time.time()
        self.timestamps.append(now)
        self.values.append(value)
        self.total += value
        self._cleanup(now)

    def get_count(self) -> int:
        """获取当前窗口内的计数"""
        self._cleanup(time.time())
        return self.total

    def _cleanup(self, now: float) -> None:
        """清理过期数据"""
        cutoff = now - self.window
        while self.timestamps and self.timestamps[0] < cutoff:
            self.timestamps.popleft()
            self.total -= self.values.popleft()


class RateLimiter:
    """速率限制器"""

    def __init__(self):
        # 每个后端的请求计数器
        self._request_counters: Dict[str, SlidingWindowCounter] = {}
        # 每个后端的token计数器
        self._token_counters: Dict[str, SlidingWindowCounter] = {}
        # 每个后端的并发控制
        self._concurrent: Dict[str, int] = {}
        # 每个后端的限制配置
        self._limits: Dict[str, Dict] = {}
        # 锁
        self._locks: Dict[str, asyncio.Lock] = {}

    def register_backend(self, backend_name: str, rpm: int = 0, tpm: int = 0, concurrent: int = 0) -> None:
        """注册后端速率限制"""
        self._request_counters[backend_name] = SlidingWindowCounter(60)
        self._token_counters[backend_name] = SlidingWindowCounter(60)
        self._concurrent[backend_name] = 0
        self._limits[backend_name] = {
            "rpm": rpm,
            "tpm": tpm,
            "concurrent": concurrent
        }
        self._locks[backend_name] = asyncio.Lock()

    def unregister_backend(self, backend_name: str) -> None:
        """注销后端"""
        self._request_counters.pop(backend_name, None)
        self._token_counters.pop(backend_name, None)
        self._concurrent.pop(backend_name, None)
        self._limits.pop(backend_name, None)
        self._locks.pop(backend_name, None)

    async def can_request(self, backend_name: str, estimated_tokens: int = 0) -> bool:
        """检查是否可以发送请求"""
        if backend_name not in self._limits:
            return True

        limits = self._limits[backend_name]

        # 检查并发限制
        if limits["concurrent"] > 0 and self._concurrent.get(backend_name, 0) >= limits["concurrent"]:
            logger.debug(f"Backend {backend_name} concurrent limit reached")
            return False

        # 检查RPM限制
        if limits["rpm"] > 0:
            current_rpm = self._request_counters[backend_name].get_count()
            if current_rpm >= limits["rpm"]:
                logger.debug(f"Backend {backend_name} RPM limit reached: {current_rpm}/{limits['rpm']}")
                return False

        # 检查TPM限制
        if limits["tpm"] > 0 and estimated_tokens > 0:
            current_tpm = self._token_counters[backend_name].get_count()
            if current_tpm + estimated_tokens > limits["tpm"]:
                logger.debug(f"Backend {backend_name} TPM limit would be exceeded")
                return False

        return True

    async def acquire(self, backend_name: str, tokens: int = 0) -> bool:
        """获取请求许可"""
        if backend_name not in self._limits:
            return True

        async with self._locks.get(backend_name, asyncio.Lock()):
            if not await self.can_request(backend_name, tokens):
                return False

            # 记录请求
            self._request_counters[backend_name].add(1)
            if tokens > 0:
                self._token_counters[backend_name].add(tokens)

            # 增加并发计数
            self._concurrent[backend_name] = self._concurrent.get(backend_name, 0) + 1

            return True

    def release(self, backend_name: str, tokens: int = 0) -> None:
        """释放请求许可"""
        if backend_name in self._concurrent:
            self._concurrent[backend_name] = max(0, self._concurrent[backend_name] - 1)

        # 记录实际使用的tokens（如果之前没有记录）
        if tokens > 0 and backend_name in self._token_counters:
            pass  # 已经在acquire时记录了

    def get_status(self, backend_name: str) -> Dict:
        """获取后端速率限制状态"""
        if backend_name not in self._limits:
            return {"limited": False}

        limits = self._limits[backend_name]
        return {
            "limited": True,
            "rpm_current": self._request_counters[backend_name].get_count() if backend_name in self._request_counters else 0,
            "rpm_limit": limits["rpm"],
            "tpm_current": self._token_counters[backend_name].get_count() if backend_name in self._token_counters else 0,
            "tpm_limit": limits["tpm"],
            "concurrent_current": self._concurrent.get(backend_name, 0),
            "concurrent_limit": limits["concurrent"]
        }

    def is_near_limit(self, backend_name: str, threshold: float = 0.8) -> bool:
        """检查是否接近限制（用于故障预判）"""
        if backend_name not in self._limits:
            return False

        limits = self._limits[backend_name]

        # 检查RPM
        if limits["rpm"] > 0:
            current = self._request_counters[backend_name].get_count()
            if current >= limits["rpm"] * threshold:
                return True

        # 检查TPM
        if limits["tpm"] > 0:
            current = self._token_counters[backend_name].get_count()
            if current >= limits["tpm"] * threshold:
                return True

        # 检查并发
        if limits["concurrent"] > 0:
            current = self._concurrent.get(backend_name, 0)
            if current >= limits["concurrent"] * threshold:
                return True

        return False


# 全局速率限制器实例
rate_limiter = RateLimiter()
