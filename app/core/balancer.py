"""负载均衡器"""
import asyncio
import random
import time
from typing import List, Optional, Dict
from ..backends.base import BaseBackend

import logging
logger = logging.getLogger("openfish.balancer")


class LoadBalancer:
    """负载均衡器"""

    def __init__(self):
        self._counter = 0

    def select(
        self,
        backends: List[BaseBackend],
        strategy: str = "latency",
        fallback_order: List[str] = None,
        backends_map: Dict[str, BaseBackend] = None
    ) -> Optional[BaseBackend]:
        """根据策略选择后端"""
        if not backends:
            return None

        if strategy == "custom" and fallback_order and backends_map:
            return self._custom_fallback(backends, fallback_order, backends_map)

        if strategy == "priority":
            return self._priority(backends)

        if strategy == "round_robin":
            return self._round_robin(backends)
        elif strategy == "random":
            return self._random(backends)
        elif strategy == "weighted":
            return self._weighted(backends)
        else:
            return self._lowest_latency(backends)

    def _custom_fallback(
        self,
        available_backends: List[BaseBackend],
        fallback_order: List[str],
        backends_map: Dict[str, BaseBackend]
    ) -> Optional[BaseBackend]:
        """自定义回退顺序"""
        available_names = {b.name for b in available_backends}

        for name in fallback_order:
            if name in available_names and name in backends_map:
                backend = backends_map[name]
                if backend.status.healthy:
                    return backend

        for backend in available_backends:
            if backend.status.healthy:
                return backend

        return available_backends[0] if available_backends else None

    def _priority(self, backends: List[BaseBackend]) -> BaseBackend:
        """优先级策略"""
        sorted_backends = sorted(backends, key=lambda b: getattr(b, 'priority', 1))
        for backend in sorted_backends:
            if backend.status.healthy:
                return backend
        return sorted_backends[0] if sorted_backends else None

    def _round_robin(self, backends: List[BaseBackend]) -> BaseBackend:
        """轮询策略"""
        self._counter = (self._counter + 1) % len(backends)
        return backends[self._counter]

    def _random(self, backends: List[BaseBackend]) -> BaseBackend:
        """随机策略"""
        return random.choice(backends)

    def _weighted(self, backends: List[BaseBackend]) -> BaseBackend:
        """加权策略"""
        weights = [b.weight for b in backends]
        return random.choices(backends, weights=weights, k=1)[0]

    def _lowest_latency(self, backends: List[BaseBackend]) -> BaseBackend:
        """最低延迟策略"""
        return min(backends, key=lambda b: b.status.latency or float("inf"))


class HealthChecker:
    """健康检查器"""

    def __init__(self):
        self._tasks: dict = {}
        self._running = False
        # 速率限制临时禁用记录 {(backend_name, model_id): expire_time}
        self._rate_limited: Dict[str, float] = {}

    async def start(self, backends: List[BaseBackend], interval: int = 30) -> None:
        """启动健康检查"""
        self._running = True
        for backend in backends:
            task = asyncio.create_task(self._check_loop(backend, interval))
            self._tasks[backend.name] = task
        logger.info(f"Health checker started for {len(backends)} backends")

    async def stop(self) -> None:
        """停止健康检查"""
        self._running = False
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()
        logger.info("Health checker stopped")

    def mark_rate_limited(self, backend_name: str, model_id: str = "", cooldown: int = 60) -> None:
        """标记后端/模型被速率限制，暂时禁用"""
        key = f"{backend_name}/{model_id}" if model_id else backend_name
        self._rate_limited[key] = time.time() + cooldown
        logger.info(f"Marked {key} as rate limited for {cooldown}s")

    def is_rate_limited(self, backend_name: str, model_id: str = "") -> bool:
        """检查是否被速率限制"""
        key = f"{backend_name}/{model_id}" if model_id else backend_name
        expire_time = self._rate_limited.get(key, 0)
        
        # 检查后端级别限制
        backend_expire = self._rate_limited.get(backend_name, 0)
        
        if time.time() > expire_time and time.time() > backend_expire:
            # 过期，清除
            self._rate_limited.pop(key, None)
            return False
        
        return time.time() < expire_time or time.time() < backend_expire

    async def _check_loop(self, backend: BaseBackend, interval: int) -> None:
        """检查循环"""
        while self._running:
            try:
                healthy = await backend.health_check()
                if healthy:
                    logger.debug(f"Backend {backend.name} is healthy")
                    # 健康检查通过，清除速率限制标记
                    self._rate_limited.pop(backend.name, None)
                else:
                    logger.warning(f"Backend {backend.name} is unhealthy")
            except Exception as e:
                logger.error(f"Health check error for {backend.name}: {e}")
                # 健康检查异常，标记为不健康
                backend.update_status(False, 0)

            await asyncio.sleep(interval)

    async def check_once(self, backend: BaseBackend) -> bool:
        """单次检查"""
        return await backend.health_check()
