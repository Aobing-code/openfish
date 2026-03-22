# FishRouter

<div align="center">

**轻量级端侧AI总线 · 统一AI模型路由平台**

**Lightweight Edge AI Bus · Unified AI Model Routing Platform**

[![Docker](https://img.shields.io/badge/Docker-Ready-blue)](https://hub.docker.com)
[![Python](https://img.shields.io/badge/Python-3.11+-green)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

</div>

---

## 亮点特性 | Highlights

| Feature 特性 | Description 说明 |
|--------------|------------------|
| **全平台API统一** | 一个接口兼容 OpenAI、Claude、Gemini、Ollama |
| **Unified API** | One interface for OpenAI, Claude, Gemini, Ollama |
| **智能故障转移** | 速率限制预判、自动降级、多级回退 |
| **Smart Failover** | Rate limit prediction, auto degradation, multi-level fallback |
| **多Key轮询** | 每个提供商支持多个 API Key，自动负载均衡 |
| **Multi-Key Rotation** | Multiple API keys per provider with load balancing |
| **模型独立限速** | 每个模型可设置 RPM/TPM/并发数 |
| **Per-Model Rate Limit** | RPM/TPM/concurrent limits for each model |
| **多模态支持** | 图片、文本混合输入，Vision 全后端通用 |
| **Multimodal** | Image and text input, Vision across all backends |
| **工具调用** | Function Calling 跨平台统一 |
| **Tool Calling** | Unified Function Calling in OpenAI format |
| **零依赖部署** | 纯内存运行，无数据库，Docker 一键启动 |
| **Zero Dependencies** | In-memory, no database, Docker one-click deploy |
| **实时监控** | Web 面板查看 QPS、延迟、Token 统计 |
| **Real-time Monitor** | Web dashboard for QPS, latency, token stats |

---

## 快速开始 | Quick Start

### Docker 部署 | Docker Deploy

```bash
docker run -d -p 8080:8080 \
  -v ./config.json:/app/config.json \
  fishrouter
```

### 源码运行 | From Source

```bash
pip install -r requirements.txt
python -m app.main
```

访问 `http://localhost:8080` 查看监控面板。

Visit `http://localhost:8080` for the dashboard.

---

## 核心功能 | Core Features

### 1. 统一API入口 | Unified API

所有后端使用相同的 OpenAI 格式：  
All backends use the same OpenAI format:

```bash
# 调用 OpenAI | Call OpenAI
curl -X POST http://localhost:8080/v1/chat/completions \
  -d '{"model": "gpt-4", "messages": [...]}'

# 调用 Claude | Call Claude
curl -X POST http://localhost:8080/v1/chat/completions \
  -d '{"model": "claude-sonnet", "messages": [...]}'

# 调用 Gemini | Call Gemini
curl -X POST http://localhost:8080/v1/chat/completions \
  -d '{"model": "gemini-pro", "messages": [...]}'

# 调用本地 Ollama | Call local Ollama
curl -X POST http://localhost:8080/v1/chat/completions \
  -d '{"model": "llama3", "messages": [...]}'
```

### 2. 智能路由 | Smart Routing

```bash
# 直接指定模型（失败后自动回退）
# Direct model (auto fallback on failure)
curl -d '{"model": "gpt-4", ...}'

# 使用指定路由策略 | Use specific route
curl -d '{"model": "back-default", ...}'
curl -d '{"model": "back-cheap", ...}'
curl -d '{"model": "back-fast", ...}'
```

### 3. 工具调用 | Tool Calling

```json
{
  "model": "gpt-4",
  "messages": [{"role": "user", "content": "北京天气"}],
  "tools": [{
    "type": "function",
    "function": {
      "name": "get_weather",
      "description": "获取天气 | Get weather",
      "parameters": {
        "type": "object",
        "properties": {
          "city": {"type": "string"}
        }
      }
    }
  }],
  "tool_choice": "auto"
}
```

### 4. 多模态 Vision | Multimodal

```json
{
  "model": "gpt-4",
  "messages": [{
    "role": "user",
    "content": [
      {"type": "text", "text": "这是什么？| What's this?"},
      {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
    ]
  }]
}
```

---

## 配置说明 | Configuration

### 完整配置示例 | Full Config Example

```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 8080
  },
  "backends": [
    {
      "name": "ollama-local",
      "type": "ollama",
      "url": "http://localhost:11434",
      "api_keys": [],
      "weight": 10,
      "priority": 1,
      "timeout": 120,
      "verify_ssl": false,
      "models": [
        {
          "id": "llama3",
          "name": "llama3",
          "context_length": 8192,
          "rate_limit": {"rpm": 30, "tpm": 50000, "concurrent": 3}
        }
      ],
      "rate_limit": {"rpm": 0, "tpm": 0, "concurrent": 10}
    },
    {
      "name": "openai",
      "type": "openai",
      "url": "https://api.openai.com/v1",
      "api_keys": ["sk-key1", "sk-key2", "sk-key3"],
      "weight": 5,
      "priority": 2,
      "models": [
        {"id": "gpt-4", "name": "gpt-4-turbo", "context_length": 128000},
        {"id": "gpt-4-mini", "name": "gpt-4o-mini", "context_length": 16384}
      ],
      "rate_limit": {"rpm": 1000, "tpm": 1000000, "concurrent": 20}
    },
    {
      "name": "anthropic",
      "type": "anthropic",
      "url": "https://api.anthropic.com",
      "api_keys": ["sk-ant-key1", "sk-ant-key2"],
      "models": [
        {"id": "claude-sonnet", "name": "claude-3-5-sonnet-20241022", "context_length": 200000}
      ]
    },
    {
      "name": "google",
      "type": "google",
      "url": "https://generativelanguage.googleapis.com",
      "api_keys": ["gemini-key1"],
      "models": [
        {"id": "gemini-pro", "name": "gemini-1.5-pro", "context_length": 1000000}
      ]
    }
  ],
  "routes": [
    {
      "name": "default",
      "models": ["*"],
      "strategy": "latency",
      "failover": true,
      "fallback_order": ["ollama-local", "openai", "anthropic"],
      "fallback_rules": [
        {"name": "rate-limit", "condition": "rate_limit", "backends": ["openai", "anthropic"]},
        {"name": "error", "condition": "error", "threshold": 3, "backends": ["anthropic"]},
        {"name": "latency", "condition": "latency", "threshold": 10.0, "backends": ["anthropic"]}
      ]
    }
  ],
  "auth": {
    "enabled": false,
    "api_keys": ["sk-openfish"]
  }
}
```

---

## 路由策略 | Routing Strategy

| 策略 | 说明 | Description |
|------|------|-------------|
| `latency` | 选择延迟最低的后端（默认） | Select lowest latency (default) |
| `round_robin` | 轮询分发 | Round-robin distribution |
| `random` | 随机选择 | Random selection |
| `weighted` | 按权重分发 | Weighted distribution |
| `priority` | 按优先级选择 | Priority-based selection |
| `custom` | 自定义回退顺序 | Custom fallback order |

---

## 故障转移 | Failover

| 条件 | 说明 | Description |
|------|------|-------------|
| `rate_limit` | 触发速率限制时自动转移 | Auto transfer on rate limit |
| `error` | 错误次数超过阈值时转移 | Transfer on error threshold |
| `latency` | 延迟超过阈值时转移 | Transfer on latency threshold |
| `timeout` | 请求超时时转移 | Transfer on timeout |

---

## 支持的后端 | Supported Backends

| Backend 后端 | Type 类型 | Tool Calling 工具调用 | Multimodal 多模态 |
|--------------|-----------|----------------------|-------------------|
| OpenAI / Azure / Compatible | `openai` | ✅ | ✅ |
| Anthropic Claude | `anthropic` | ✅ | ✅ |
| Google Gemini | `google` | ✅ | ✅ |
| Ollama | `ollama` | ✅ | ✅ |

---

## Docker 部署 | Docker Deploy

```bash
# 构建镜像 | Build image
docker build -t fishrouter .

# 运行容器 | Run container
docker run -d \
  --name openfish \
  -p 8080:8080 \
  -v $(pwd)/config.json:/app/config.json \
  fishrouter

# 或使用 docker-compose | Or use docker-compose
docker-compose up -d
```

---

## Linux 服务化 | Linux Service

```bash
# 复制服务文件 | Copy service file
sudo cp fishrouter.service /etc/systemd/system/

# 启用并启动 | Enable and start
sudo systemctl enable fishrouter
sudo systemctl start fishrouter

# 查看日志 | View logs
sudo journalctl -u fishrouter -f
```

---

## 项目结构 | Project Structure

```
openfish/
├── app/
│   ├── main.py           # 主入口 | Main entry
│   ├── config.py         # 配置管理 | Config management
│   ├── api/
│   │   ├── chat.py       # Chat Completions
│   │   ├── embeddings.py # Embeddings
│   │   ├── models.py     # Models
│   │   ├── monitor.py    # 监控API | Monitor API
│   │   └── config.py     # 配置API | Config API
│   ├── backends/
│   │   ├── base.py       # 后端基类 | Backend base
│   │   ├── openai.py     # OpenAI 兼容
│   │   ├── anthropic.py  # Anthropic Claude
│   │   ├── google.py     # Google Gemini
│   │   └── ollama.py     # Ollama
│   ├── core/
│   │   ├── balancer.py   # 负载均衡 | Load balancer
│   │   ├── ratelimit.py  # 速率限制 | Rate limiter
│   │   ├── auth.py       # API Key 认证
│   │   └── stats.py      # 统计追踪 | Statistics
│   └── web/
│       └── dashboard.py  # 监控面板 | Dashboard
├── static/
│   └── index.html        # 前端界面 | Frontend
├── config.example.json   # 示例配置 | Example config
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## License

MIT
