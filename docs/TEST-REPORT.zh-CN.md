# CCOBridge 测试报告

- 报告日期：2026-09-01
- 测试版本：`1.2.0`

结论：模拟协议、镜像恢复、源码安装和离线安装测试通过；真实模型和真实 Agent 仍需按环境验收

## 1. 范围与声明边界

本报告验证 CCOBridge 源码、`linux/amd64` 镜像、确定性 Ollama 模拟服务、导出归档、
安装脚本和恢复流程。报告证明的是协议数据和交付流程，不证明模型智能或 GPU 健康。

- **通过**：记录环境中实际执行了自动断言。
- **模拟**：上游为 Fake Ollama，而不是真实模型。
- **待验收**：必须在目标 Ollama、模型、Agent、网络和硬件组合中验证。

## 2. 测试环境

| 项目 | 测试值 |
|---|---|
| 宿主机 | Windows + WSL 2 |
| Linux | Ubuntu 22.04 |
| Docker Engine | 29.7.2 |
| 目标平台 | Linux / amd64 |
| Gateway 镜像 | `ccobridge:1.2.0` |
| 运行身份 | `10001:10001` |
| LiteLLM | `v1.94.0` |
| 基础镜像 digest | `sha256:65d84a2282137b4dc73bbe184650a7c807177c533e4223b3bfbc87963fe3fabe` |
| 上游 | 独立确定性 Fake Ollama 容器 |
| 网络 | Linux host network |
| 持久化 | 本地 SQLite 用量聚合；无 PostgreSQL / Redis |

Fake Ollama 实现：

- `/api/version`、`/api/tags`、`/api/show`、`/api/chat`；
- `/v1/chat/completions`，包含 SSE 和工具调用；
- `/v1/completions`；
- `/v1/responses`；
- `/v1/embeddings`。

它发布一个聊天模型和一个向量模型，并记录下游字段供断言使用。完整源码 Release
保留测试源码，但 Fake Ollama 不会进入正式镜像。

## 3. 静态与单元检查

| 检查 | 证据 | 结果 |
|---|---|---|
| Python 单元测试 | 24 个 system、别名、模型、多密钥和用量测试 | 通过 |
| Ruff lint | Bug、风格、导入、现代化和简化规则 | 通过 |
| Ruff format | 全部 Python 文件格式检查 | 通过 |
| ShellCheck | 客户端、部署、构建、集成和生命周期脚本 | 通过 |
| PSScriptAnalyzer 1.25.0 | Windows 客户端 Warning 和 Error | 通过 |
| 隐私扫描 | 常见密钥、内网 IP 和用户路径扫描 | 通过 |
| Compose | 使用文档环境文件解析配置 | 通过 |

别名测试覆盖空配置、JSON 校验、空白规范化、原生模型透传、空名称、自引用、规范化后
重名、标识符含空白和别名链。模型列表测试覆盖动态原生模型、已安装和缺失的别名
目标、明确同名覆盖、确定性排序、时间字段和畸形 Ollama 响应。

## 4. 容器集成结果

| 区域 | 断言 | 结果 |
|---|---|---|
| 存活与就绪 | Gateway、Ollama tags、内部 LiteLLM 均就绪 | 通过 |
| 缺少认证 | 受保护接口返回 OpenAI 格式 HTTP 401 | 通过 |
| Bearer | 管理员和独立用户 Key 均可访问推理路径 | 通过 |
| Anthropic `x-api-key` | 正确 Key 可查询单个模型 | 通过 |
| 动态模型 | 返回原生聊天和向量模型 | 通过 |
| 别名发现 | 目标已安装的别名会被发布 | 通过 |
| 单模型查询 | `/v1/models/{model}` 返回别名元数据 | 通过 |
| 别名路由 | 对外聊天别名解析为原生 Ollama 模型 | 通过 |
| 原生路由 | 原生 Ollama 模型名不变 | 通过 |
| 凭据隔离 | Bearer 与 `x-api-key` 不到达 Ollama | 通过 |
| 用户 Key 摘要 | 配置只包含 SHA-256 摘要，不包含用户明文 Key | 通过 |
| 管理员隔离 | 用户 Key 访问 `/admin/users` 和 `/admin/usage` 返回 403 | 通过 |
| 性能管理隔离 | 用户 Key 访问 `/admin/performance` 返回 403 | 通过 |
| 用户列表 | 管理员可查询非机密用户元数据 | 通过 |
| Token 归属 | Chat usage 计入发起请求的用户、模型和接口 | 通过 |
| 用量覆盖 | `requests` 与 `metered_requests` 分开记录 | 通过 |
| 请求关联 | 推理响应包含不可预测的请求 ID 和 `Server-Timing` | 通过 |
| 性能报告 | 管理员可查询近期计时、平均值和观察 Token/s | 通过 |
| 性能脱敏 | 报告可隐藏用户标识且不包含请求或响应正文 | 通过 |
| Chat Completions | OpenAI 响应保持完整 | 通过 |
| Chat SSE | 分段事件重新组成预期文本 | 通过 |
| Completions | 旧版 completion 响应保持完整 | 通过 |
| Responses | response 对象保持完整且别名正确解析 | 通过 |
| Embeddings | 向量数组保持完整且向量别名正确解析 | 通过 |
| OpenAI 工具 | schema 到达 Ollama，tool call 完整返回 | 通过 |
| 管理面隔离 | `/key/generate` 返回 404，不到达 LiteLLM | 通过 |
| Anthropic Messages | 返回 Anthropic message | 通过 |
| 中途 system | 下游 system 全部位于普通消息之前 | 通过 |
| 哨兵内容 | 顶层和中途 system 哨兵均到达下游 | 通过 |
| 文本块元数据 | `cache_control` 在归一化后保留 | 通过 |
| 非文本 system | Anthropic 格式 HTTP 400，无下游请求 | 通过 |
| Anthropic SSE | text delta 重组为 `stream-ok` | 通过 |
| Anthropic 工具定义 | LiteLLM/Ollama 收到 schema | 通过 |
| Anthropic tool call | 返回有名称和参数的 `tool_use` | 通过 |
| Tool result | tool ID 和结果到达下一次下游请求 | 通过 |

集成测试同时配置聊天别名和向量别名，证明网关不依赖单个烘焙模型名。

## 5. 镜像和离线交付物

发布构建脚本完成全部七个阶段：

1. 拉取 LiteLLM `v1.94.0`，解析 digest 并与 `BASE-IMAGE.lock` 比较；
2. 为 `linux/amd64` 构建 `ccobridge:1.2.0`；
3. 执行单元和双容器集成测试；
4. 使用 `docker save` 导出正式镜像；
5. 打包完整 Git 已跟踪源码，并验证包内清单和外层 SHA-256；
6. 删除主镜像标签，从归档重新加载；
7. 对恢复后的镜像再次执行完整测试。

| 交付物属性 | 结果 |
|---|---|
| 目标架构为 amd64 | 通过 |
| 容器以非 root `10001:10001` 运行 | 通过 |
| 基础版本与 digest 锁定 | 通过 |
| 镜像配置没有运行 API Key | 通过 |
| 包内 `SHA256SUMS` 验证全部文件 | 通过 |
| 外层 `.tar.gz.sha256` 验证发布包 | 通过 |
| 重载后的镜像 ID 与导出前一致 | 通过 |
| 完整恢复后集成测试 | 通过 |
| Release 包含完整 Git 已跟踪源码 | 通过 |
| 正式镜像不含 Fake Ollama 和测试占位凭据 | 通过 |

交付文件：

```text
dist/ccobridge-offline-1.2.0-linux-amd64.tar.gz
dist/ccobridge-offline-1.2.0-linux-amd64.tar.gz.sha256
```

最终镜像 ID、源码 revision、构建时间、基础 digest 和目标平台写入包内
`BUILD-INFO.txt`。归档 SHA-256 位于相邻 `.sha256` 文件，不在源码报告中重复硬编码。

## 6. 离线与源码安装生命周期

最终归档被解压到隔离的 `/tmp/ccobridge-install-audit.*`，以 root 模拟 Ubuntu 安装。
测试发现同名既有容器或 4000/11434 端口占用时会直接退出；清理阶段只处理带有本次
审计标识或本次 Compose 工作目录的资源。

生命周期断言全部通过：

- 安装前验证包内全部校验值；
- Fake Ollama `0.13.3` 通过版本和模型预检；
- 本地镜像加载并以 `--pull never` 启动；
- 动态模型、Chat、Responses 和 Anthropic 在线验收通过；
- 生成的 `sk-...` Key 文件权限为 `0600`；
- 用户 Key 新建、动态生效、停用和重新启用通过；
- 用户 Key 明文未写入配置，Key 摘要文件权限和属主符合策略；
- 用户 Chat 的 Token 用量按用户持久化到本地 SQLite；
- 无推理开销的 `diagnose.sh` 可读取容器、控制面延迟和脱敏性能报告；
- host network、`unless-stopped`、非 root 身份符合策略；
- 第二次安装保持 `.env` 和用户配置，且用量数据库继续存在；
- 卸载删除 Gateway 容器，保留镜像、`.env`、用户配置和用量数据库；
- 删除正式镜像后，使用本地缓存的锁定基础镜像从源码重新构建；
- 源码安装通过相同在线验收，并记录 `install_mode=source-build`；
- 审计容器、临时镜像标签、端口、目录和临时凭据已清理。

生命周期脚本为 `tests/run-install-lifecycle.sh`，作为可审计测试源码进入完整源码
Release，但正常目标服务器安装不会自动执行它。

## 7. 安全与隐私观察

- 对外推理接口对管理员和全部用户 Key 摘要执行常量时间比较。
- 接受 Bearer 和 `x-api-key`，两者均不会转发给 Ollama。
- 健康端点只返回粗粒度状态。
- 未支持路径不会暴露内部 LiteLLM 管理面。
- CCOBridge 不记录请求体和响应体，并关闭 Uvicorn access log。
- 管理员 Key 只在安装时生成；用户 Key 只显示一次，配置只保存摘要。
- SQLite 用量表只保存用户标识、模型、接口和聚合计数；性能表额外保存请求 ID、
  状态和耗时，自动限制为最近 1000 条。两者都不保存提示词、响应正文、客户端 IP
  或明文 Key。
- 扫描未发现内网地址、用户 Profile 路径、私钥、GitHub Token、AWS Key 或长生产型
  `sk-...` 字面量。

这不是渗透测试或依赖漏洞审计。默认模式仍为 HTTP，只能用于可信网络；Token 统计
依赖上游返回的 usage，不作为计费账本。

## 8. 真实环境待验收项

自动环境没有使用目标物理 GPU、生产 Ollama 或真实 Agent。以下项目不能宣称通过：

- 目标 Qwen、Llama、向量、视觉等真实模型推理；
- 输出质量、Context、吞吐和并发负载；
- Cursor、Continue、OpenCode、LangChain、LlamaIndex、AutoGen、CrewAI 等应用；
- Claude Code 的 Read、Write、Edit、Bash 和多轮项目工作流；
- 模型特定的工具、推理、视觉和 Embeddings 能力；
- 真实服务器或 Docker 服务重启后的恢复；
- 生产防火墙、TLS 入口和网络策略。

## 9. 生产验收标准

对每个 Agent 与模型组合：

1. 记录 Agent、Ollama、模型和 CCOBridge 版本；
2. 使用目标模型运行 `/opt/ccobridge/verify.sh`；
3. 验证普通和流式聊天；
4. 验证所有必要工具和多轮 tool result；
5. Agent 使用 Responses 或 Embeddings 时分别验证；
6. 检查脱敏日志中没有协议或模板错误；
7. 重启 Docker 或服务器并确认自动恢复；
8. 确认客户端只能访问带认证的 4000，不能访问 Ollama 11434。

## 10. 结论

CCOBridge `1.2.0` 已通过静态、单元、模拟协议、多密钥认证、管理员隔离、Token 归属、
脱敏性能计时、流式、工具、镜像恢复、校验值、源码安装、离线安装、重复安装和卸载
测试，可以作为受控 Release Candidate 发布。
生产批准仍取决于目标环境中的真实模型和真实 Agent 验收。
