# OpenFish

<div align="center">

**轻量级端侧AI总线 · 统一AI模型路由平台**

[![Docker](https://img.shields.io/badge/Docker-Ready-blue)](https://hub.docker.com)
[![Python](https://img.shields.io/badge/Python-3.11+-green)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

</div>

---

## 亮点特性

| 特性 | 说明 |
|------|------|
| **全平台API统一** | 一个接口兼容 OpenAI、Claude、Gemini、Ollama，无需修改代码 |
| **智能故障转移** | 速率限制预判、自动降级、多级回退，服务永不断线 |
| **多Key轮询** | 每个提供商支持多个 API Key，自动负载均衡，突破单Key限速 |
| **模型独立限速** | 每个模型可设置 RPM/TPM/并发数，精细控制成本 |
| **多模态支持** | 图片、文本混合输入，Vision 全后端通用 |
| **工具调用** | Function Calling 跨平台统一，OpenAI格式一调到底 |
| **零依赖部署** | 纯内存运行，无数据库，Docker 一键启动 |
| **实时监控** | Web 面板查看 QPS、延迟、Token 统计，一目了然 |

---

## 为什么选择 OpenFish？

```diff
+ 一套代码，调用所有AI模型
+ 一个Key用完？自动切换下一个
+ 请求太多？自动转移到其他后端
+ 想用哪个模型？model字段直接指定
+ 想按策略路由？back-xxx一键切换
```

---

## 快速开始

### Docker 部署（推荐）

```bash
docker run -d -p 8080:8080 \
  -v ./config.json:/app/config.json \
  openfish
```

### 源码运行

```bash
pip install -r requirements.txt
python -m app.main
```

访问 `http://localhost:8080` 查看监控面板。

---

## 核心功能

### 1. 统一API入口

所有后端使用相同的 OpenAI 格式：

```bash
# 调用 OpenAI
curl -X POST http://localhost:8080/v1/chat/completions \
  -d '{"model": "gpt-4", "messages": [...]}'

# 调用 Claude（同一接口）
curl -X POST http://localhost:8080/v1/chat/completions \
  -d '{"model": "claude-sonnet", "messages": [...]}'

# 调用 Gemini（同一接口）
curl -X POST http://localhost:8080/v1/chat/completions \
  -d '{"model": "gemini-pro", "messages": [...]}'

# 调用本地 Ollama（同一接口）
curl -X POST http://localhost:8080/v1/chat/completions \
  -d '{"model": "llama3", "messages": [...]}'
```

### 2. 智能路由与故障转移

```bash
# 直接指定模型（失败后自动回退）
curl -d '{"model": "gpt-4", ...}'

# 使用指定路由策略
curl -d '{"model": "back-default", ...}'
curl -d '{"model": "back-cheap", ...}'
curl -d '{"model": "back-fast", ...}'
```

### 3. 工具调用（Function Calling）

```json
{
  "model": "gpt-4",
  "messages": [{"role": "user", "content": "北京天气"}],
  "tools": [{
    "type": "function",
    "function": {
      "name": "get_weather",
      "description": "获取天气",
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

### 4. 多模态 Vision

```json
{
  "model": "gpt-4",
  "messages": [{
    "role": "user",
    "content": [
      {"type": "text", "text": "这是什么？"},
      {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
    ]
  }]
}
```

### 5. 多Key轮询

```json
{
  "name": "openai",
  "type": "openai",
  "api_keys": ["sk-key1", "sk-key2", "sk-key3"],
  "models": [...]
}
```

多个 Key 自动轮询，单个 Key 限速自动切换下一个。

### 6. 模型独立限速

```json
{
  "models": [{
    "id": "gpt-4",
    "name": "gpt-4-turbo",
    "rate_limit": {
      "rpm": 100,      // 每分钟最多100次请求
      "tpm": 200000,   // 每分钟最多20万Token
      "concurrent": 5  // 最多5个并发
    }
  }]
}
```

---

## 配置说明

### 完整配置示例

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
        {"id": "claude-sonnet", "name": "claude-3-5-sonnet-20241022"},
        {"id": "claude-haiku", "name": "claude-3-5-haiku-20241022"}
      ]
    },
    {
      "name": "google",
      "type": "google",
      "url": "https://generativelanguage.googleapis.com",
      "api_keys": ["gemini-key1"],
      "models": [
        {"id": "gemini-pro", "name": "gemini-1.5-pro"},
        {"id": "gemini-flash", "name": "gemini-1.5-flash"}
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

## 路由策略

| 策略 | 说明 |
|------|------|
| `latency` | 选择延迟最低的后端（默认） |
| `round_robin` | 轮询分发 |
| `random` | 随机选择 |
| `weighted` | 按权重分发 |
| `priority` | 按优先级选择 |
| `custom` | 自定义回退顺序 |

---

## 故障转移规则

| 条件 | 说明 |
|------|------|
| `rate_limit` | 触发速率限制时自动转移 |
| `error` | 错误次数超过阈值时转移 |
| `latency` | 延迟超过阈值时转移 |
| `timeout` | 请求超时时转移 |

---

## 支持的后端

| 后端 | 类型 | 工具调用 | 多模态 |
|------|------|---------|--------|
| OpenAI / Azure / 兼容接口 | `openai` | ✅ | ✅ |
| Anthropic Claude | `anthropic` | ✅ | ✅ |
| Google Gemini | `google` | ✅ | ✅ |
| Ollama | `ollama` | ✅ | ✅ |

---

## Docker 部署

```bash
# 构建镜像
docker build -t openfish .

# 运行容器
docker run -d \
  --name openfish \
  -p 8080:8080 \
  -v $(pwd)/config.json:/app/config.json \
  openfish

# 或使用 docker-compose
docker-compose up -d
```

---

## Linux 服务化部署

```bash
# 复制服务文件
sudo cp openfish.service /etc/systemd/system/

# 启用并启动
sudo systemctl enable openfish
sudo systemctl start openfish

# 查看日志
sudo journalctl -u openfish -f
```

---

## 项目结构

```
openfish/
├── app/
│   ├── main.py           # 主入口
│   ├── config.py         # 配置管理（热更新）
│   ├── api/
│   │   ├── chat.py       # Chat Completions（工具调用/多模态）
│   │   ├── embeddings.py # Embeddings
│   │   ├── models.py     # Models
│   │   ├── monitor.py    # 监控API
│   │   └── config.py     # 配置管理API
│   ├── backends/
│   │   ├── base.py       # 后端基类
│   │   ├── openai.py     # OpenAI 兼容
│   │   ├── anthropic.py  # Anthropic Claude
│   │   ├── google.py     # Google Gemini
│   │   └── ollama.py     # Ollama
│   ├── core/
│   │   ├── balancer.py   # 负载均衡
│   │   ├── ratelimit.py  # 速率限制
│   │   ├── auth.py       # API Key 认证
│   │   └── stats.py      # 统计追踪
│   └── web/
│       └── dashboard.py  # 监控面板
├── static/
│   └── index.html        # 前端界面
├── config.example.json   # 示例配置
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## License

MIT

