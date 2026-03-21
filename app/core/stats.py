"""统计追踪模块"""
import time
import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime, timedelta

import logging
logger = logging.getLogger("openfish.stats")


@dataclass
class RequestStats:
    """请求统计"""
    timestamp: float
    model: str
    backend: str
    tokens: int
    latency: float
    success: bool


class StatsCollector:
    """统计收集器"""

    def __init__(self, retention_minutes: int = 60):
        self.retention_minutes = retention_minutes
        self._requests: List[RequestStats] = []
        self._lock = asyncio.Lock()

        # 计数器
        self.total_requests: int = 0
        self.total_tokens: int = 0
        self.total_errors: int = 0

        # 按模型统计
        self.model_requests: Dict[str, int] = defaultdict(int)
        self.model_tokens: Dict[str, int] = defaultdict(int)

        # 按后端统计
        self.backend_requests: Dict[str, int] = defaultdict(int)
        self.backend_tokens: Dict[str, int] = defaultdict(int)

        # QPS计算
        self._qps_window: List[float] = []

    async def record(
        self,
        model: str,
        backend: str,
        tokens: int,
        latency: float,
        success: bool = True
    ) -> None:
        """记录请求"""
        async with self._lock:
            now = time.time()
            stats = RequestStats(
                timestamp=now,
                model=model,
                backend=backend,
                tokens=tokens,
                latency=latency,
                success=success
            )
            self._requests.append(stats)

            # 更新计数器
            self.total_requests += 1
            self.total_tokens += tokens
            if not success:
                self.total_errors += 1

            self.model_requests[model] += 1
            self.model_tokens[model] += tokens
            self.backend_requests[backend] += 1
            self.backend_tokens[backend] += tokens

            # 更新QPS窗口
            self._qps_window.append(now)
            self._qps_window = [t for t in self._qps_window if now - t < 60]

            # 清理旧数据
            self._cleanup(now)

    def _cleanup(self, now: float) -> None:
        """清理旧数据"""
        cutoff = now - (self.retention_minutes * 60)
        self._requests = [r for r in self._requests if r.timestamp > cutoff]

    def get_qps(self) -> float:
        """获取当前QPS"""
        if not self._qps_window:
            return 0.0
        now = time.time()
        self._qps_window = [t for t in self._qps_window if now - t < 60]
        return len(self._qps_window) / 60.0

    def get_recent_requests(self, minutes: int = 5) -> List[RequestStats]:
        """获取最近的请求"""
        cutoff = time.time() - (minutes * 60)
        return [r for r in self._requests if r.timestamp > cutoff]

    def get_summary(self) -> Dict:
        """获取统计摘要"""
        return {
            "total_requests": self.total_requests,
            "total_tokens": self.total_tokens,
            "total_errors": self.total_errors,
            "qps": round(self.get_qps(), 2),
            "model_stats": dict(self.model_requests),
            "backend_stats": dict(self.backend_requests)
        }

    def get_model_stats(self, model: str) -> Dict:
        """获取指定模型的统计"""
        recent = self.get_recent_requests(60)
        model_requests = [r for r in recent if r.model == model]

        if not model_requests:
            return {"requests": 0, "tokens": 0, "avg_latency": 0}

        total_latency = sum(r.latency for r in model_requests)
        return {
            "requests": self.model_requests[model],
            "tokens": self.model_tokens[model],
            "avg_latency": round(total_latency / len(model_requests), 3)
        }

    def get_backend_stats(self, backend: str) -> Dict:
        """获取指定后端的统计"""
        recent = self.get_recent_requests(60)
        backend_requests = [r for r in recent if r.backend == backend]

        if not backend_requests:
            return {"requests": 0, "tokens": 0, "avg_latency": 0}

        total_latency = sum(r.latency for r in backend_requests)
        return {
            "requests": self.backend_requests[backend],
            "tokens": self.backend_tokens[backend],
            "avg_latency": round(total_latency / len(backend_requests), 3)
        }

    def get_timeline(self, minutes: int = 30) -> List[Dict]:
        """获取时间线数据"""
        now = time.time()
        cutoff = now - (minutes * 60)
        recent = [r for r in self._requests if r.timestamp > cutoff]

        # 按分钟聚合
        buckets: Dict[int, Dict] = defaultdict(lambda: {"requests": 0, "tokens": 0, "errors": 0})

        for r in recent:
            minute = int(r.timestamp // 60)
            buckets[minute]["requests"] += 1
            buckets[minute]["tokens"] += r.tokens
            if not r.success:
                buckets[minute]["errors"] += 1

        timeline = []
        for minute in sorted(buckets.keys()):
            timeline.append({
                "time": datetime.fromtimestamp(minute * 60).isoformat(),
                **buckets[minute]
            })

        return timeline


# 全局统计实例
stats = StatsCollector()
