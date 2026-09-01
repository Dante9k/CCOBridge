# CCOBridge 操作手册

- 文档版本：1.2
- 离线包：`ccobridge-offline-1.2.0-linux-amd64.tar.gz`
- 目标环境：Ubuntu 20.04+、x86_64、Docker Engine、Docker Compose v2

## 1. 部署模式

CCOBridge 对外暴露宿主机 Ollama 已安装模型：

```text
OpenAI 兼容 Agent ── OpenAI API ───┐
                                    ├─ CCOBridge :4000 ── Ollama :11434
Claude Code ── Anthropic Messages ──┘          │
                                               └─ LiteLLM :4001（仅内部）
```

OpenAI 兼容接口采用直接流式路径；Anthropic Messages 使用 LiteLLM 转换。客户端只应
访问 CCOBridge 4000，Ollama 继续只在宿主机回环地址提供服务。

## 2. 安装条件

服务器必须具备：

- `x86_64` 或 `amd64` 架构；
- 正常运行的 Docker 和 Compose v2 插件；
- `curl`、`sort` 和 `ss`；
- 联网源码安装需要 `git`，离线 Release 安装需要 `sha256sum` 和 `tar`；
- `http://127.0.0.1:11434` 上的 Ollama `0.13.3` 或更高版本；
- Ollama 至少已安装一个模型；
- 未被占用且只允许可信网络访问的 TCP 4000。

复制发布包前检查：

```bash
uname -m
docker info >/dev/null && echo 'Docker OK'
docker compose version
curl -fsS http://127.0.0.1:11434/api/version
curl -fsS http://127.0.0.1:11434/api/tags
ss -ltn | grep ':4000 ' || echo 'Port 4000 is free'
```

根据实际 Agent 场景安装聊天、工具、视觉或 Embeddings 模型。网关不会为模型增加
它本身不具备的能力。

## 3. 选择安装路径

### 3.1 联网源码安装

服务器能够访问镜像仓库时执行：

```bash
git clone https://github.com/Dante9k/CCOBridge.git
cd CCOBridge
sudo ./deploy/install.sh --online
```

安装程序从当前检出的源码构建镜像，严格使用 `BASE-IMAGE.lock` 中的 LiteLLM digest；
本机已有该基础镜像时直接复用，否则才下载锁定版本。

### 3.2 完全离线 Release 的传输与校验

从同一个 Release 复制：

```text
ccobridge-offline-1.2.0-linux-amd64.tar.gz
ccobridge-offline-1.2.0-linux-amd64.tar.gz.sha256
```

解压前验证外层文件：

```bash
sha256sum -c ccobridge-offline-1.2.0-linux-amd64.tar.gz.sha256
```

校验不一致时不要继续安装。

## 4. 安装完全离线 Release

```bash
tar -xzf ccobridge-offline-1.2.0-linux-amd64.tar.gz
cd ccobridge-offline-1.2.0
sudo ./deploy/install.sh --offline
```

解压后的 Release 同时包含完整 Git 已跟踪源码和预构建镜像。使用不带参数的
`sudo ./deploy/install.sh` 也会自动识别并加载包内镜像。完全隔离的主机如果 Docker
中没有锁定的基础镜像，就不能仅凭源码完成构建。

安装程序会：

1. 使用包内 `SHA256SUMS` 校验每个文件；
2. 检查架构、Docker、Compose、4000 端口、已有容器归属、Ollama 版本和模型；
3. 从源码构建 `ccobridge:1.2.0`，或从本地归档加载它；
4. 将管理脚本安装到 `/opt/ccobridge`；
5. 只在 `.env` 不存在时生成随机管理员 `sk-...` API Key；
6. 创建权限受限的用户 Key 配置目录和本地用量数据目录；
7. 检测到 `qwen3.8:latest` 时创建兼容旧版本的 `qwen-code` 别名；
8. 以 host network、`restart: unless-stopped` 和 `--pull never` 启动；
9. 执行模型列表、Chat Completions、Responses 和 Anthropic 验收。

安装程序不会输出 Key。通过合规的管理员会话从受保护服务器文件读取并保存到密码
管理器，同时保持服务器文件权限为 `0600`：

```bash
sudo stat -c '%a %n' /opt/ccobridge/.env
```

重复安装不会覆盖已有 `.env`、用户 Key 摘要或用量数据库。

## 5. 运行配置

默认 `/opt/ccobridge/.env`：

```dotenv
CCOBRIDGE_API_KEY=<安装时生成的-key>
OLLAMA_API_BASE=http://127.0.0.1:11434
CCOBRIDGE_MODEL_ALIASES={"qwen-code":"qwen3.8:latest"}
```

首次安装时如果没有 Qwen 模型，别名对象为空。原生 Ollama 模型名无需配置；除非被
同名别名明确覆盖，否则始终可以直接调用。

配置多个别名：

```dotenv
CCOBRIDGE_MODEL_ALIASES={"qwen-code":"qwen3.8:latest","local-embed":"nomic-embed-text:latest"}
```

别名目标必须是原生 Ollama 模型名。目标未安装时，别名不会出现在 `/v1/models`。
JSON 无效或别名自引用会导致容器明确启动失败。同名别名会覆盖原生模型名，应只在
确实需要覆盖时使用。

使用 `LITELLM_MASTER_KEY` 的 1.0 安装仍可运行。轮换 Key 时建议迁移到
`CCOBRIDGE_API_KEY`，不能让两个变量具有不同值。

修改配置后执行：

```bash
cd /opt/ccobridge
sudo docker compose --env-file .env up -d --force-recreate --pull never
sudo ./verify.sh
```

## 6. 验证服务

```bash
docker ps --filter name=ccobridge
docker inspect --format '{{.State.Health.Status}}' ccobridge
sudo /opt/ccobridge/verify.sh
```

验收脚本优先使用 `qwen-code`，否则自动选择一个已发现模型。也可以强制指定：

```bash
sudo CCOBRIDGE_VERIFY_MODEL='llama3.2:latest' /opt/ccobridge/verify.sh
```

自动验收覆盖就绪状态、动态模型、Chat Completions、Responses、Anthropic Messages
和中途 system 归一化。因为一般服务器不一定安装向量模型，Embeddings 只在集成测试
中自动覆盖，不在服务器安装验收中强制执行。

查看近期日志：

```bash
sudo /opt/ccobridge/logs.sh
```

## 7. 配置 OpenAI 兼容 Agent

多数客户端使用：

```dotenv
OPENAI_BASE_URL=http://192.0.2.10:4000/v1
OPENAI_API_KEY=<安装时生成的-api-key>
```

请替换文档示例地址。部分产品把字段称为 `OpenAI endpoint`、`custom provider` 或
`API base`，有的要求 URL 不带 `/v1`，应以 Agent 自身说明为准。

配置 Agent 前先查看模型：

```bash
curl -fsS http://192.0.2.10:4000/v1/models \
  -H 'Authorization: Bearer <安装时生成的-api-key>'
```

使用列表中返回的原生模型名或别名。除非已配置别名，否则不能假设 `gpt-4o` 等任意
OpenAI 模型名自动存在。

## 8. 配置 Claude Code

Claude Code 的 URL 不带 `/v1`：

```powershell
.\client\claude-ccobridge.ps1 `
  -Gateway "http://192.0.2.10:4000" `
  -Model "qwen-code"
```

```bash
export CCOBRIDGE_URL='http://192.0.2.10:4000'
export CCOBRIDGE_MODEL='qwen-code'
./client/claude-ccobridge.sh
```

手动配置当前 shell：

```bash
export ANTHROPIC_BASE_URL='http://192.0.2.10:4000'
export ANTHROPIC_AUTH_TOKEN='<安装时生成的-api-key>'
unset ANTHROPIC_API_KEY
claude --model qwen-code
```

助手脚本会以不回显方式询问 Key。直接写在命令中的 Key 可能进入 shell 历史。

## 9. Agent 验收流程

接口兼容和模型能力是两件事。每个生产 Agent 与模型组合都要在临时目录验收：

```bash
acceptance_dir="$(mktemp -d)"
cd "$acceptance_dir"
printf '%s\n' 'acceptance input' > README.txt
```

编码 Agent 至少检查：

1. 普通聊天；
2. 列目录和读文件；
3. 创建和修改文件；
4. 执行命令或脚本；
5. 多轮 tool result；
6. 流式输出；
7. Docker 或服务器重启后恢复。

记录 Agent 版本、Ollama 版本、模型 digest、网关镜像 ID、请求模式和脱敏结果。不要
公开包含机密内容的提示词或路径。

## 10. 多用户 Key 与用量统计

管理员密钥位于 `.env`，只用于验收和管理。为每位用户单独创建密钥：

```bash
cd /opt/ccobridge
sudo ./users.sh add alice
sudo ./users.sh list
```

保存命令显示一次的 Key；`config/users.json` 只存 SHA-256 摘要。用户变更会自动加载，
无需重启：

```bash
sudo ./users.sh disable alice
sudo ./users.sh enable alice
sudo ./users.sh rotate alice
```

轮换后旧 Key 立即失效。普通用户不能访问管理接口。查看最近 30 天全部用量或指定用户：

```bash
sudo ./usage.sh
sudo ./usage.sh 30 usr_0123456789abcdef
```

`data/usage.sqlite3` 按 UTC 日期、用户、模型和接口聚合请求、成功请求、已计量请求以及
输入/输出/总 Token。它不保存请求正文或响应正文。只有上游明确返回 usage 的请求才会
增加 `metered_requests`；统计覆盖率不足时不要将结果用于结算。

直接调用管理接口时必须使用管理员 Key：

```bash
curl -fsS 'http://127.0.0.1:4000/admin/usage?days=30' \
  -H 'Authorization: Bearer <admin-key>'
```

## 11. 日常操作

```bash
sudo /opt/ccobridge/start.sh
sudo /opt/ccobridge/stop.sh
sudo /opt/ccobridge/logs.sh
sudo /opt/ccobridge/verify.sh
sudo /opt/ccobridge/users.sh list
sudo /opt/ccobridge/usage.sh
```

`restart: unless-stopped` 会让容器在 Docker 或服务器重启后恢复；手工执行
`stop.sh` 后会保持停止，直到再次运行 `start.sh`。

Ollama 模型安装和删除会动态反映到 `/v1/models`，无需重启网关；修改别名需要重建
容器。

## 12. 升级与回滚

新版本完成生产验收前保留旧归档和校验文件。安装程序会保留
`/opt/ccobridge/.env`、`config/users.json` 和 `data/usage.sqlite3`。

回滚时加载旧镜像，并恢复该版本配套的 Compose 和脚本：

```bash
sudo docker load -i ./image/ccobridge-1.0.0-linux-amd64.tar
cd /opt/ccobridge
sudo docker compose --env-file .env up -d --force-recreate --pull never
sudo ./verify.sh
```

1.0 不支持动态模型透传、Responses 和 Embeddings。回滚后确认客户端重新使用它的
`qwen-code` 固定契约。

## 13. 卸载

```bash
sudo /opt/ccobridge/uninstall.sh
```

该操作删除容器，保留镜像、`.env`、用户 Key 摘要和用量数据库。管理员手工删除
保留文件前应备份整个 `/opt/ccobridge`。

## 14. 常见故障

### HTTP 401

- 管理员客户端确认 Key 等于 `.env` 中的 `CCOBRIDGE_API_KEY`。
- 普通用户执行 `sudo ./users.sh list`，确认用户存在且状态为 `enabled`。
- 旧版升级时确认后备 Key 存在且没有冲突。
- 清除过期的 OpenAI 或 Anthropic 凭据环境变量。
- 检查复制时是否带入空格或引号。

### Model not found

- 调用带认证的 `GET /v1/models`，使用实际返回的 ID。
- 确认 `ollama list` 中包含别名目标。
- 检查 `CCOBRIDGE_MODEL_ALIASES` 是合法 JSON 对象。
- 修改别名后重建容器。

### Responses 返回 404 或字段不支持

- 确认 Ollama 至少为 `0.13.3`。
- Ollama 目前只实现无状态 Responses。
- 移除 `previous_response_id`、`conversation` 等未支持字段。

### Embeddings 失败

- 使用具备向量能力的模型，而不是普通聊天模型。
- 用同一模型直连 Ollama 复现，以区分模型能力和网关问题。

### 无法访问 Ollama

- 在宿主机运行 `curl http://127.0.0.1:11434/api/tags`。
- 检查 `systemctl status ollama`。
- 检查 `OLLAMA_API_BASE` 和 Linux host network。
- 受支持部署不使用 `host.docker.internal`。

### Anthropic system 模板错误

- 确认客户端访问 4000，而不是直连 Ollama。
- 执行 `verify.sh` 并查看脱敏日志。
- 检查运行中的镜像标签和 ID。

### 工具参数为空或不可靠

- 确认所选模型在 Ollama 中支持工具调用。
- 使用最小工具定义通过 Chat Completions 复现。
- 如果下游请求证明协议字段没有丢失，应把错误参数选择视为模型能力问题。

### 用量没有增加

- 确认请求使用用户 Key，并调用了推理接口而不是 `/v1/models`。
- 比较 `requests` 和 `metered_requests`；后端没有返回 usage 时只统计请求数。
- 检查 `data/usage.sqlite3` 所在目录归属为 `10001:10001` 且容器日志没有 SQLite 错误。

## 15. 安全检查清单

- 4000 只允许可信客户端访问。
- Ollama 11434 保持私有。
- `.env` 保持 `0600`。
- `config/users.json` 保持 `0600`，`config/` 与 `data/` 保持 `0700`。
- 每人使用独立 Key，离职或泄露时立即停用或轮换，禁止多人共享用户 Key。
- 不公开包含提示词或环境信息的日志。
- 跨越不可信网络前增加可信 TLS 入口。
- 每次公开发布前运行 `scripts/check-public-release.py`。
