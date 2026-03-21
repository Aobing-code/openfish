# OpenFish

轻量级端侧AI总线 · 统一AI模型路由平台

## 特性

- **全平台兼容**: 支持 Ollama、OpenAI、Anthropic Claude、Google Gemini
- **OpenAI格式统一**: 完全兼容 OpenAI API，所有后端统一输入输出
- **多Key轮询**: 每个提供商支持多个 API Key，自动轮询负载均衡
- **模型独立限速**: 每个模型可设置独立的 RPM/TPM 速率限制
- **智能路由**: 最低延迟、轮询、随机、加权、优先级多种策略
- **故障预判**: 基于速率限制阈值自动转移请求
- **多级回退**: 支持多条回退规则，拖拽配置优先级
- **超轻量**: 纯内存运行，无数据库依赖
- **热更新**: JSON 配置修改即时生效，无需重启
- **监控面板**: 网页实时查看后端状态、QPS、Token 统计
- **Docker 支持**: 全平台通用，开箱即用
- **服务化**: 支持 systemd 后台稳定运行
- **SSL 可忽略**: 适配内网、自签证书、穿透场景

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
python -m app.main
```

访问 `http://localhost:8080` 查看监控面板。

## 配置说明

### 完整配置示例

```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 8080,
    "log_level": "info"
  },
  "backends": [
    {
      "name": "ollama-local",
      "type": "ollama",
      "url": "http://localhost:11434",
      "api_keys": [],
      "weight": 10,
      "enabled": true,
      "timeout": 120,
      "verify_ssl": false,
      "models": [
        {
          "id": "llama3",
          "name": "llama3",
          "context_length": 8192,
          "enabled": true,
          "rate_limit": {"rpm": 30, "tpm": 50000, "concurrent": 3}
        }
      ],
      "rate_limit": {"rpm": 0, "tpm": 0, "concurrent": 10},
      "priority": 1
    },
    {
      "name": "openai-gpt4",
      "type": "openai",
      "url": "https://api.openai.com/v1",
      "api_keys": ["sk-key1", "sk-key2", "sk-key3"],
      "weight": 5,
      "enabled": true,
      "timeout": 60,
      "verify_ssl": true,
      "models": [
        {
          "id": "gpt-4",
          "name": "gpt-4-turbo",
          "context_length": 128000,
          "enabled": true,
          "rate_limit": {"rpm": 100, "tpm": 200000, "concurrent": 5}
        },
        {
          "id": "gpt-4-mini",
          "name": "gpt-4o-mini",
          "context_length": 16384,
          "enabled": true,
          "rate_limit": {"rpm": 500, "tpm": 800000, "concurrent": 10}
        }
      ],
      "rate_limit": {"rpm": 1000, "tpm": 1000000, "concurrent": 20},
      "priority": 2
    },
    {
      "name": "anthropic-claude",
      "type": "anthropic",
      "url": "https://api.anthropic.com",
      "api_keys": ["sk-ant-key1", "sk-ant-key2"],
      "models": [
        {"id": "claude-sonnet", "name": "claude-3-5-sonnet-20241022"},
        {"id": "claude-haiku", "name": "claude-3-5-haiku-20241022"}
      ],
      "rate_limit": {"rpm": 500, "tpm": 500000, "concurrent": 10},
      "priority": 2
    },
    {
      "name": "google-gemini",
      "type": "google",
      "url": "https://generativelanguage.googleapis.com",
      "api_keys": ["gemini-key1"],
      "models": [
        {"id": "gemini-pro", "name": "gemini-1.5-pro"},
        {"id": "gemini-flash", "name": "gemini-1.5-flash"}
      ],
      "rate_limit": {"rpm": 200, "tpm": 3000000, "concurrent": 15},
      "priority": 3
    }
  ],
  "routes": [
    {
      "name": "default",
      "models": ["*"],
      "strategy": "latency",
      "failover": true,
      "health_check_interval": 30,
      "fallback_order": ["ollama-local", "openai-gpt4", "anthropic-claude"],
      "fallback_rules": [
        {
          "name": "rate-limit-fallback",
          "condition": "rate_limit",
          "threshold": 0,
          "backends": ["openai-gpt4", "anthropic-claude"]
        },
        {
          "name": "error-fallback",
          "condition": "error",
          "threshold": 3,
          "backends": ["anthropic-claude", "google-gemini"]
        },
        {
          "name": "latency-fallback",
          "condition": "latency",
          "threshold": 10.0,
          "backends": ["anthropic-claude"]
        }
      ]
    }
  ],
  "auth": {
    "enabled": false,
    "api_keys": ["sk-openfish"]
  }
}
```

### 配置字段说明

#### 后端配置 (backends)

| 字段 | 说明 |
|------|------|
| `name` | 后端名称，唯一标识 |
| `type` | 后端类型: `ollama`, `openai`, `anthropic`, `google` |
| `url` | 后端地址 |
| `api_keys` | API Key 数组，自动轮询负载均衡 |
| `weight` | 权重，用于加权路由策略 |
| `priority` | 优先级，数字越小优先级越高 |
| `timeout` | 请求超时（秒） |
| `verify_ssl` | 是否验证 SSL 证书 |
| `rate_limit` | 提供商级别速率限制 |
| `models` | 模型列表 |

#### 模型配置 (models)

| 字段 | 说明 |
|------|------|
| `id` | 模型 ID，请求时使用 |
| `name` | 实际模型名称，发送给后端 |
| `context_length` | 上下文长度 |
| `enabled` | 是否启用 |
| `rate_limit` | 模型独立速率限制 |

#### 速率限制 (rate_limit)

| 字段 | 说明 |
|------|------|
| `rpm` | 每分钟请求数，0 表示不限制 |
| `tpm` | 每分钟 Token 数，0 表示不限制 |
| `concurrent` | 最大并发数，0 表示不限制 |

#### 回退规则 (fallback_rules)

| 字段 | 说明 |
|------|------|
| `name` | 规则名称 |
| `condition` | 触发条件: `error`, `timeout`, `rate_limit`, `latency` |
| `threshold` | 阈值（延迟秒数或错误次数） |
| `backends` | 回退后端列表 |

## API 接口

### Chat Completions

通过 model ID 选择模型：

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-openfish" \
  -d '{
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "Hello"}],
    "temperature": 0.7,
    "stream": false
  }'
```

### Embeddings

```bash
curl http://localhost:8080/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{"model": "text-embedding-004", "input": "Hello world"}'
```

### Models

```bash
curl http://localhost:8080/v1/models
```

### 监控接口

```bash
# 系统状态
curl http://localhost:8080/api/monitor/status

# 配置信息
curl http://localhost:8080/api/config
```

## 路由策略

| 策略 | 说明 |
|------|------|
| `latency` | 选择延迟最低的后端（默认） |
| `round_robin` | 轮询 |
| `random` | 随机 |
| `weighted` | 按权重 |
| `priority` | 按优先级 |
| `custom` | 自定义回退顺序 |

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

## 项目结构

```
openfish/
├── app/
│   ├── main.py          # 主入口
│   ├── config.py        # 配置管理
│   ├── api/             # API 端点
│   │   ├── chat.py      # Chat Completions
│   │   ├── embeddings.py # Embeddings
│   │   ├── models.py    # Models
│   │   ├── monitor.py   # 监控
│   │   └── config.py    # 配置管理
│   ├── backends/        # 后端适配器
│   │   ├── base.py      # 基类
│   │   ├── ollama.py    # Ollama
│   │   ├── openai.py    # OpenAI 兼容
│   │   ├── anthropic.py # Anthropic Claude
│   │   └── google.py    # Google Gemini
│   ├── core/            # 核心组件
│   │   ├── balancer.py  # 负载均衡
│   │   ├── auth.py      # API Key 认证
│   │   ├── stats.py     # 统计追踪
│   │   └── ratelimit.py # 速率限制
│   └── web/             # 监控面板
├── static/              # 前端静态文件
├── config.json          # 配置文件
├── Dockerfile           # Docker 镜像
├── docker-compose.yml   # Docker 编排
├── .dockerignore        # Docker 忽略文件
├── .gitignore           # Git 忽略文件
└── requirements.txt     # 依赖
```

## License

MIT
