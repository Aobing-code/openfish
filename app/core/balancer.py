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

        # 自定义回退顺序
        if strategy == "custom" and fallback_order and backends_map:
            return self._custom_fallback(backends, fallback_order, backends_map)

        # 优先级策略
        if strategy == "priority":
            return self._priority(backends)

        if strategy == "round_robin":
            return self._round_robin(backends)
        elif strategy == "random":
            return self._random(backends)
        elif strategy == "weighted":
            return self._weighted(backends)
        else:  # latency (default)
            return self._lowest_latency(backends)

    def select_with_fallback(
        self,
        primary_backends: List[BaseBackend],
        strategy: str,
        fallback_rules: List[Dict],
        backends_map: Dict[str, BaseBackend]
    ) -> List[BaseBackend]:
        """选择后端并生成回退链"""
        result = []

        # 首先选择主后端
        primary = self.select(primary_backends, strategy)
        if primary:
            result.append(primary)

        # 根据回退规则添加备用后端
        for rule in fallback_rules:
            rule_backends = []
            for name in rule.get("backends", []):
                if name in backends_map and backends_map[name] not in result:
                    backend = backends_map[name]
                    if backend.status.healthy:
                        rule_backends.append(backend)

            # 添加到回退链
            for b in rule_backends:
                if b not in result:
                    result.append(b)

        return result

    def _custom_fallback(
        self,
        available_backends: List[BaseBackend],
        fallback_order: List[str],
        backends_map: Dict[str, BaseBackend]
    ) -> Optional[BaseBackend]:
        """自定义回退顺序"""
        available_names = {b.name for b in available_backends}

        # 按照fallback_order顺序选择第一个可用的后端
        for name in fallback_order:
            if name in available_names and name in backends_map:
                backend = backends_map[name]
                if backend.status.healthy:
                    return backend

        # 如果自定义顺序中没有可用的，返回第一个健康的
        for backend in available_backends:
            if backend.status.healthy:
                return backend

        # 如果没有健康的，返回第一个
        return available_backends[0] if available_backends else None

    def _priority(self, backends: List[BaseBackend]) -> BaseBackend:
        """优先级策略"""
        # 按优先级排序，选择优先级最高（数字最小）的健康后端
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

    async def _check_loop(self, backend: BaseBackend, interval: int) -> None:
        """检查循环"""
        while self._running:
            try:
                await backend.health_check()
                if backend.status.healthy:
                    logger.debug(f"Backend {backend.name} is healthy")
                else:
                    logger.warning(f"Backend {backend.name} is unhealthy")
            except Exception as e:
                logger.error(f"Health check error for {backend.name}: {e}")

            await asyncio.sleep(interval)

    async def check_once(self, backend: BaseBackend) -> bool:
        """单次检查"""
        return await backend.health_check()
