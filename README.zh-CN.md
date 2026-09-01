<div align="center">

# CCOBridge

**面向 Ollama 本地模型和各类 Agent 的轻量级 OpenAI / Anthropic 兼容网关。**

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
![Platform: linux/amd64](https://img.shields.io/badge/platform-linux%2Famd64-1793d1)
![LiteLLM: v1.94.0](https://img.shields.io/badge/LiteLLM-v1.94.0-6f42c1)
![Source deployable](https://img.shields.io/badge/source-deployable-success)
![Offline deployable](https://img.shields.io/badge/deployment-offline-success)
![Multi-key](https://img.shields.io/badge/auth-multi--key-success)

[English](README.md) · [操作手册](docs/OPERATION-MANUAL.zh-CN.md) · [测试报告](docs/TEST-REPORT.zh-CN.md) · [安全策略](SECURITY.md)

</div>

CCOBridge 在 Ollama 已安装模型前提供一个带真实认证、适合 Agent 调用的统一入口。
它会动态发现 Ollama 模型，可通过别名形成稳定的客户端模型名，并让 OpenAI 兼容
Agent 和 Claude Code 共用同一个网关。

OpenAI 兼容请求通过流式快速路径直接到达 Ollama；Anthropic Messages 请求由固定
版本 LiteLLM 转换，并经过一层严格的 system 内容兼容处理。项目使用本地 SQLite
汇总各用户 Token 用量和近期脱敏性能计时，不需要 PostgreSQL、Redis、管理后台、
计费系统或外部遥测。

> [!IMPORTANT]
> CCOBridge 解决的是协议、认证和交付问题，不能让模型凭空获得工具调用、视觉、
> Embeddings、上下文长度或推理能力。将模拟测试结果用于生产判断前，请阅读
> [测试报告](docs/TEST-REPORT.zh-CN.md)。

## 为什么不让 Agent 直接连接 Ollama

Ollama 已经实现部分 OpenAI API。如果只是可信电脑上的单用户调用，直连 Ollama
通常最简单。以下需求才是 CCOBridge 的价值：

- 为不同用户签发可单独停用和轮换的 API Key，而不是 Ollama 会忽略的占位 Key；
- 按用户、模型和接口汇总请求数与后端报告的 Token 用量；
- 对客户端只开放一个受保护端口，Ollama 11434 继续保持私有；
- 实时发现 Ollama 模型，同时提供 `qwen-code` 等稳定别名；
- 为 Claude Code 和 Anthropic SDK 提供 Anthropic Messages；
- 兼容 Qwen 等严格模板的中途 system 消息；
- 向隔离网络交付一个可复现镜像和带校验值的离线安装包；
- 对 Chat、Responses、Embeddings、流式和工具调用进行可重复回归测试。

如果需要账号、额度、计费、管理后台或多个上游供应商，应选择 New API 或完整的
LiteLLM 平台。CCOBridge 有意保持在“裸 Ollama”和大型平台之间。

## 架构

```text
OpenAI SDK / Cursor / Continue / OpenCode / 各类 Agent 框架
                              │
                              │ OpenAI 兼容 API
                              ▼
                       CCOBridge :4000
                       ├─ 多 API Key 认证
                       ├─ 本地 SQLite 用量与性能计时
                       ├─ 动态模型与别名
                       ├─ OpenAI 流式快速路径 ─────────────────┐
                       └─ Anthropic 兼容归一化                  │
                                      │                        │
                                      ▼                        │
                         LiteLLM v1.94.0 :4001                 │
                              （仅容器内部）                    │
                                      │                        │
                                      └─────────────┬──────────┘
                                                    ▼
                                      宿主机 Ollama :11434
```

正式部署使用 Linux host network。Ollama 可以继续只监听 `127.0.0.1:11434`，
可信客户端只访问 CCOBridge 的 4000 端口。

## 联网服务器从源码部署

Ubuntu `x86_64` 服务器能够联网，并且已经具备 Docker、Compose、Ollama 和至少一个
Ollama 模型时，直接执行：

```bash
git clone https://github.com/Dante9k/CCOBridge.git
cd CCOBridge
sudo ./deploy/install.sh --online
```

安装程序会在本地没有缓存时下载带 digest 锁定的 LiteLLM 基础镜像，从当前源码构建
`ccobridge:1.2.0`，生成受保护的管理员 API Key，启动网关并执行真实接口验收。重复运行不会
覆盖已有 Key 和配置。

`sudo ./deploy/install.sh` 使用自动模式：离线 Release 中存在镜像归档时直接加载，
普通源码目录则从源码构建。需要固定行为时使用 `--online` 或 `--offline`。

## 支持的接口

| 方法 | 端点 | 实现路径 | 典型用途 |
|---|---|---|---|
| `GET` | `/v1/models` | CCOBridge + Ollama 动态发现 | 查询已安装模型和有效别名 |
| `GET` | `/v1/models/{model}` | CCOBridge | 查询单个模型 |
| `POST` | `/v1/chat/completions` | 流式透传 Ollama | 大多数 OpenAI 兼容 Agent |
| `POST` | `/v1/responses` | 流式透传 Ollama | 新版 OpenAI SDK 和 Agent |
| `POST` | `/v1/completions` | 流式透传 Ollama | 旧版 Completions 客户端 |
| `POST` | `/v1/embeddings` | 流式透传 Ollama | RAG 和向量工作流 |
| `POST` | `/v1/messages` | 归一化 + LiteLLM | Claude Code 和 Anthropic 客户端 |
| `GET` | `/admin/users` | CCOBridge | 管理员查询用户元数据，不返回密钥 |
| `GET` | `/admin/usage` | CCOBridge + SQLite | 管理员查询聚合用量 |
| `GET` | `/admin/performance` | CCOBridge + SQLite | 管理员查询近期脱敏耗时 |
| `GET` | `/health/liveliness` | CCOBridge | 进程存活检查 |
| `GET` | `/health/readiness` | CCOBridge + 上游检查 | Ollama 和 LiteLLM 就绪检查 |

认证同时接受 `Authorization: Bearer ...` 和 Anthropic 常用的 `x-api-key`。
健康检查端点为了容器探针保持免认证。未列出的路径直接返回 404，不会暴露 LiteLLM
的管理接口。

最低要求 Ollama `0.13.3`，因为这是开始支持无状态 OpenAI Responses 接口的版本。
Ollama 当前不支持 `previous_response_id` 等有状态 Responses 字段。准确支持范围以
[Ollama OpenAI 兼容文档](https://github.com/ollama/ollama/blob/main/docs/api/openai-compatibility.mdx)
为准。

## 各类 Agent 的快速配置

将服务器可信内网地址和安装时生成的 Key 配置给 OpenAI 兼容客户端：

```dotenv
OPENAI_BASE_URL=http://192.0.2.10:4000/v1
OPENAI_API_KEY=<installed-api-key>
```

`192.0.2.10` 是专用于文档的示例地址，请替换为真实服务器地址。部分客户端要求
Base URL 不带 `/v1`，应以该客户端的字段说明为准。

查看当前可用模型与别名：

```bash
curl -fsS http://192.0.2.10:4000/v1/models \
  -H 'Authorization: Bearer <installed-api-key>'
```

使用任意已安装 Ollama 模型调用 Chat Completions：

```bash
curl -fsS http://192.0.2.10:4000/v1/chat/completions \
  -H 'Authorization: Bearer <installed-api-key>' \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "qwen3.8:latest",
    "messages": [{"role": "user", "content": "只回复 READY"}],
    "stream": false
  }'
```

调用 Responses：

```bash
curl -fsS http://192.0.2.10:4000/v1/responses \
  -H 'Authorization: Bearer <installed-api-key>' \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.8:latest","input":"只回复 READY"}'
```

Embeddings 必须使用 Ollama 中已安装且具备向量能力的模型：

```bash
curl -fsS http://192.0.2.10:4000/v1/embeddings \
  -H 'Authorization: Bearer <installed-api-key>' \
  -H 'Content-Type: application/json' \
  -d '{"model":"nomic-embed-text:latest","input":"本地向量测试"}'
```

## Claude Code 配置

Claude Code 使用 Anthropic Messages，因此 Base URL 不带 `/v1`：

```powershell
$env:ANTHROPIC_BASE_URL="http://192.0.2.10:4000"
$env:ANTHROPIC_AUTH_TOKEN="<安装时生成的-api-key>"
Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
claude --model qwen-code
```

Windows 助手会以不回显方式询问 Key，并允许指定模型：

```powershell
.\client\claude-ccobridge.ps1 `
  -Gateway "http://192.0.2.10:4000" `
  -Model "qwen-code"
```

Linux 或 macOS：

```bash
export CCOBRIDGE_URL='http://192.0.2.10:4000'
export CCOBRIDGE_MODEL='qwen-code'
./client/claude-ccobridge.sh
```

Claude Code 的工具质量高度依赖模型本身。API 测试通过并不代表模型一定能可靠完成
文件编辑和命令执行。

## 多用户密钥与 Token 统计

首次安装生成的 `CCOBRIDGE_API_KEY` 是管理员密钥，继续用于验收和管理接口。为每个
用户单独创建 Key：

```bash
cd /opt/ccobridge
sudo ./users.sh add alice
sudo ./users.sh list
```

新 Key 只显示一次。服务器仅在 `config/users.json` 中保存 SHA-256 摘要，不保存可还原
的用户明文 Key。用户文件会按修改时间自动重新加载，添加、停用、启用和轮换都不需要
重启网关：

```bash
sudo ./users.sh disable alice
sudo ./users.sh enable alice
sudo ./users.sh rotate alice
```

轮换会立即使旧 Key 失效并只显示一次新 Key。普通用户可以调用模型，但访问
`/admin/users`、`/admin/usage` 或 `/admin/performance` 会得到 HTTP 403。

查看最近 30 天全部用量，或只查看指定用户：

```bash
sudo ./usage.sh
sudo ./usage.sh 30 usr_0123456789abcdef
```

统计按 UTC 日期、用户、模型和接口聚合到 `data/usage.sqlite3`，只保存请求数、成功数、
已计量请求数和输入/输出/总 Token，不保存提示词或响应正文。`metered_requests` 小于
`requests` 表示某些响应没有返回 usage；尤其是后端未提供最终 usage 的流式请求，项目
不会用不准确的字符数猜测 Token。因此该统计适合容量和公平使用观察，不是计费账本。

## 首次调用慢：一键判断网关还是模型

先运行无推理开销的诊断：

```bash
cd /opt/ccobridge
sudo ./diagnose.sh
```

它检查容器健康与重启次数、4000/11434 监听、CPU/内存/GPU、`ollama ps`、Ollama 和
Gateway 控制面延迟，并显示最近 20 个脱敏请求计时。不会输出 Key、提示词、响应正文、
客户端 IP 或用户名。需要用一个很小的真实请求对比网关和 Ollama 时，显式指定 Ollama
原生模型名（不是 `qwen-code` 别名）：

```bash
sudo ./diagnose.sh --benchmark qwen3.8:latest
```

每个推理响应还会带 `x-ccobridge-request-id` 和 `Server-Timing`。性能报告保留最近
1000 条事件，并提供 `upstream_headers_ms`、`first_byte_ms`、`total_ms` 与上游报告
Token 可计算时的 `observed_output_tokens_per_second`：

- `upstream_headers_ms` 或流式 `first_byte_ms` 很高，通常指向 Ollama 排队、模型冷加载
  或长上下文预填充；
- 首字节正常但总耗时高、输出 Token/s 低，通常是模型生成速度；
- Ollama 直连明显快而网关仍慢，再用请求 ID 对照 `sudo ./logs.sh`；
- 只有第一次慢而紧接着的请求快，通常是模型从磁盘加载到内存或显存。

非流式 HTTP 必须等完整正文才能看到首字节，因此判断首 Token 延迟时应优先观察流式
请求。计时只用于运维定位，不保存请求或响应内容，也不是严谨的并发压测结果。

## 动态模型与别名

`GET /v1/models` 每次都会读取 Ollama `/api/tags`。在 Ollama 中安装或删除模型后，
不需要重启 CCOBridge；除非有同名别名明确覆盖，否则原生模型名始终可以直接调用。

别名为可选 JSON 对象：

```dotenv
CCOBRIDGE_MODEL_ALIASES={"qwen-code":"qwen3.8:latest","local-embed":"nomic-embed-text:latest"}
```

只有目标已安装时，别名才会出现在模型列表。别名只解析一层，目标必须是原生 Ollama
模型名，不能指向另一个别名。同名别名会覆盖原生模型名，应只在确实需要覆盖时使用。
JSON 无效、标识符含空白、规范化后重名、名称为空、别名链或自引用都会让容器明确
启动失败。

修改别名后重建容器并验收：

```bash
cd /opt/ccobridge
sudo docker compose --env-file .env up -d --force-recreate --pull never
sudo ./verify.sh
```

为了兼容 1.0，镜像默认保留 `qwen-code` → `qwen3.8:latest`。将
`CCOBRIDGE_MODEL_ALIASES={}` 写入 `.env` 可以关闭全部别名。

## system 消息安全规则

Claude Code 会话可能在普通消息之后再次出现 `system`，严格模型模板通常要求所有
system 内容位于开头。对 `POST /v1/messages`，CCOBridge 保证：

1. 原有顶层 system 内容始终在最前；
2. 中途 system 按原顺序合并；
3. 同时支持字符串和 Anthropic text-block 数组；
4. 保留 `cache_control` 等文本块元数据；
5. 不改变 user、assistant 和 tool 消息顺序；
6. 非文本 system block 明确返回 Anthropic 格式 HTTP 400，不静默丢弃内容。

这是针对当前
[LiteLLM system 消息问题](https://github.com/BerriAI/litellm/issues/36917)
的窄范围兼容措施，不是通用提示词改写功能。

## 完全离线安装

服务器要求：

- Ubuntu 20.04+、`x86_64`；
- Docker Engine 和 Docker Compose v2；
- 宿主机管理的 Ollama `0.13.3` 或更高版本，可通过
  `127.0.0.1:11434` 访问；
- Ollama 至少已安装一个模型；
- 4000 端口只允许可信客户端访问。

在联网机器上从 GitHub Release 下载离线包及相邻 SHA-256 文件，复制到内网服务器后
执行：

```bash
sha256sum -c ccobridge-offline-1.2.0-linux-amd64.tar.gz.sha256
tar -xzf ccobridge-offline-1.2.0-linux-amd64.tar.gz
cd ccobridge-offline-1.2.0
sudo ./deploy/install.sh --offline
```

离线包除了预构建 Docker 镜像、文档和校验值，还包含完整的 Git 已跟踪源码。安装
程序会校验外层和包内文件、检查架构、Ollama、4000 端口和已有同名容器归属，
在不拉取镜像的情况下加载本地镜像、保留已有 `.env`、首次生成权限为 `0600` 的
API Key、使用 `--pull never` 启动 Compose，并执行真实 API 验收。

真正断网的 Docker 主机无法仅凭源码生成一个本地不存在的基础镜像。如果目标机器
不能访问镜像仓库，应使用 Release 中“源码 + 镜像”的离线包；这不是另一套代码，
而是同一源码的完整交付形式。

管理命令安装到 `/opt/ccobridge`：

```bash
sudo /opt/ccobridge/start.sh
sudo /opt/ccobridge/stop.sh
sudo /opt/ccobridge/logs.sh
sudo /opt/ccobridge/verify.sh
sudo /opt/ccobridge/users.sh list
sudo /opt/ccobridge/usage.sh
sudo /opt/ccobridge/diagnose.sh
sudo /opt/ccobridge/uninstall.sh
```

卸载默认删除容器，保留镜像、`.env`、用户 Key 摘要和用量数据库。

## 构建与测试

在 Linux 或启用 Linux 容器的 WSL 2 中执行：

```bash
./scripts/build-offline.sh
```

构建脚本会拉取固定 LiteLLM 基础镜像、验证 digest、构建 `linux/amd64` 镜像、
运行单元和双容器集成测试、导出镜像、打包完整 Git 已跟踪源码、生成校验值、重新
加载正式归档，并再次执行完整测试。结果进入被 Git 忽略的 `dist/`。

快速代码检查：

```bash
python3 -m pip install ruff==0.16.3
make check
```

完整 Docker 集成测试：

```bash
make integration
```

Fake Ollama 测试覆盖多密钥认证、管理员隔离、Token 归属、请求 ID、响应计时、动态
模型、别名、Chat Completions、Responses、Embeddings、OpenAI 与 Anthropic 流式
输出、system 归一化、工具定义、tool call、tool result 和下游模型解析。完整源码
Release 会保留 Fake Ollama 测试源码，但它不会进入正式镜像；包内凭据全部是明确的
非机密测试占位值。

## 配置参考

运行配置位于 `/opt/ccobridge/.env`：

| 变量 | 必需 | 默认值 | 用途 |
|---|---:|---|---|
| `CCOBRIDGE_API_KEY` | 是 | 无 | 管理员 Bearer 或 `x-api-key` 凭据 |
| `OLLAMA_API_BASE` | 否 | `http://127.0.0.1:11434` | 宿主机 Ollama API |
| `CCOBRIDGE_MODEL_ALIASES` | 否 | `qwen-code` 别名 | JSON 模型别名 |
| `GATEWAY_PORT` | 否 | `4000` | host network 下的公开监听端口 |
| `INTERNAL_LITELLM_PORT` | 否 | `4001` | 容器内部转换服务端口 |
| `GATEWAY_LOG_LEVEL` | 否 | `info` | Uvicorn 日志级别 |

为了升级兼容，1.0 的 `LITELLM_MASTER_KEY` 仍可作为后备变量，但不能与
`CCOBRIDGE_API_KEY` 设置为不同值。

## 安全边界

CCOBridge 1.2 面向可信内网，提供独立用户 Key 和聚合用量，但不提供 TLS、限流、
配额、SSO 或计费。必须通过主机或网络防火墙限制 4000，并且不能把无认证的 Ollama
11434 暴露给客户端。

兼容代理不会记录请求体和响应体；性能事件只保存时间、请求 ID、用户 ID、模型、接口、
状态和 Token 计数，最多保留最近 1000 条。OpenAI 兼容流量转发到 Ollama 前会移除
客户端凭据。管理员 Key 只在服务器首次安装时生成，以 `0600` 保存；用户 Key 只显示
一次，磁盘仅保留摘要。密钥不会烘焙进镜像或发布包。

公开发布前运行：

```bash
python3 scripts/check-public-release.py
```

漏洞报告和部署建议见 [SECURITY.md](SECURITY.md)。

## 范围与限制

- 不包含 Ollama、模型权重、GPU 驱动或宿主机性能调优。
- 官方离线包当前只支持 `linux/amd64`。
- Responses 只支持当前 Ollama 已实现的字段，不模拟有状态 Responses。
- 不虚构模型能力：Embeddings 使用向量模型，Agent 工具使用具备工具能力的模型。
- 模型别名固定解析一层。
- 不提供管理后台、配额、计费、SSO 或多供应商路由。
- 本项目独立开发，不隶属于或代表 Ollama、Anthropic、Claude Code、OpenAI、
  Qwen 或 BerriAI/LiteLLM。

## 文档

| 文档 | English | 中文 |
|---|---|---|
| 部署、运维与排障 | [Guide](docs/OPERATION-MANUAL.md) | [操作手册](docs/OPERATION-MANUAL.zh-CN.md) |
| 测试证据与边界 | [Report](docs/TEST-REPORT.md) | [测试报告](docs/TEST-REPORT.zh-CN.md) |
| 公开发布隐私审计 | [Audit](docs/PUBLICATION-AUDIT.md) | — |
| 安全报告 | [Policy](SECURITY.md) | — |
| 贡献流程 | [Contributing](CONTRIBUTING.md) | — |
| 路线图 | [Roadmap](ROADMAP.md) | — |

## 参与贡献与许可证

欢迎提交 Issue 和范围明确的 Pull Request。请先阅读
[CONTRIBUTING.md](CONTRIBUTING.md)，为可观察行为增加测试，并且不要在公开材料中
提交提示词、凭据、内网信息或机器专属路径。

CCOBridge 源码使用 [Apache-2.0](LICENSE)。生成镜像中的第三方组件保留各自许可，
详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
