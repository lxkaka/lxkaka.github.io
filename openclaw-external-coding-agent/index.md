# OpenClaw 使用外部 Coding Agent 的原理与调用链路


## 概述

OpenClaw 支持通过两种方式调用外部 coding agent（Codex、Claude Code、OpenCode、Pi 等）：

| 方式 | 入口工具 | 执行环境 | 通信协议 | 适用场景 |
|------|---------|---------|---------|---------|
| **Bash（exec）** | `exec` tool | OS 子进程（PTY/child） | stdin/stdout 原始流 | 一次性任务、直接 CLI 调用 |
| **ACP** | `sessions_spawn` tool | acpx CLI → ACP adapter | JSON-RPC 2.0 over stdio | 持久化会话、线程绑定、结构化交互 |

两条路径最终都由 OpenClaw 的内嵌 Pi Agent 触发——Pi Agent 是 OpenClaw 唯一的官方 agent runtime，外部 coding agent 作为 Pi 的"工具"被调用。

---

## 方式一：Bash（exec tool）直接调用

### 1.1 入口：coding-agent Skill

OpenClaw 通过 Skill 系统（`skills/coding-agent/SKILL.md`）教会 Pi Agent 何时以及如何调用外部 coding agent。Skill 定义了：

- **触发条件**：构建新功能、PR Review、大规模重构等场景
- **前置条件**：`anyBins: ["claude", "codex", "opencode", "pi"]`——系统中至少有一个 CLI 可用
- **每种 agent 的调用差异**：
  - Codex/Pi/OpenCode：需要 `pty:true`（交互式终端应用）
  - Claude Code：使用 `--print --permission-mode bypassPermissions`（非交互模式，不需要 PTY）

### 1.2 exec tool 执行链路

```
Pi Agent 根据 Skill 决定调用某个 coding agent
│
▼
exec tool (src/agents/bash-tools.exec.ts)
│  参数: command, pty, workdir, background, timeout, elevated
│  安全检查: host/security/ask 模式
│
▼
runExecProcess() (src/agents/bash-tools.exec-runtime.ts)
│  构造 SpawnInput，选择 PTY 或 child 模式
│
▼
ProcessSupervisor.spawn()
│
├─ pty: true ────────────────────────────────────┐
│  supervisor.spawn({ mode: "pty", ptyCommand })  │
│  → createPtyAdapter() (src/process/supervisor/adapters/pty.ts)
│  → @lydell/node-pty spawn                       │
│  → 分配伪终端 (cols:120, rows:30)               │
│                                                  │
├─ pty: false ───────────────────────────────────┐
│  supervisor.spawn({ mode: "child", argv })      │
│  → Node.js child_process.spawn                  │
│  → stdio: pipe                                  │
│                                                  │
▼
外部 coding agent CLI 进程
│  例: codex exec "Build a REST API"
│  例: claude --print --permission-mode bypassPermissions "Fix the bug"
│
▼
bash-process-registry (src/agents/bash-process-registry.ts)
│  注册为 ProcessSession (runningSessions Map)
│  缓冲 stdout/stderr 输出
│  TTL 管理 (30min 默认)
│
▼
process tool (src/agents/bash-tools.process.ts)
│  后台任务管理: list/poll/log/write/submit/send-keys/kill
│
▼
Pi Agent 读取输出，汇总结果返回用户
```

### 1.3 关键代码路径

| 文件 | 核心函数/类 | 职责 |
|------|-----------|------|
| `src/agents/bash-tools.exec.ts` | `createExecTool()` | 定义 exec tool 的 schema、安全检查、参数解析 |
| `src/agents/bash-tools.exec-runtime.ts` | `runExecProcess()` | 实际 spawn 逻辑，根据 `usePty` 分流 |
| `src/process/supervisor/adapters/pty.ts` | `createPtyAdapter()` | PTY 适配器，使用 `@lydell/node-pty` |
| `src/process/supervisor/types.ts` | `ProcessSupervisor` interface | spawn/cancel/reconcile 接口 |
| `src/agents/bash-process-registry.ts` | `runningSessions` / `finishedSessions` | 进程会话生命周期管理 |
| `src/agents/bash-tools.process.ts` | `createProcessTool()` | 后台进程交互工具 |

### 1.4 Bash 方式的数据流

```
用户: "帮我用 Codex 重构 auth 模块"
  │
  ▼
OpenClaw Gateway (WebSocket)
  │
  ▼
Pi Agent (embedded, createAgentSession)
  │ Pi 识别到 coding-agent Skill，决定使用 exec tool
  │
  ▼
exec tool 调用:
  command: "codex exec --full-auto 'Refactor the auth module'"
  pty: true
  workdir: ~/project
  background: true
  │
  ▼
ProcessSupervisor.spawn({
  mode: "pty",
  ptyCommand: "codex exec --full-auto 'Refactor the auth module'"
})
  │
  ▼
@lydell/node-pty 分配伪终端
  └─ codex CLI 进程启动（pid: 12345）
  │
  ▼
bash-process-registry 注册 ProcessSession
  │  sessionId: "ps_abc123"
  │  缓冲 stdout 输出
  │
  ▼
Pi Agent 使用 process tool 监控:
  process action:poll sessionId:"ps_abc123"    → 检查是否完成
  process action:log  sessionId:"ps_abc123"    → 获取输出日志
  │
  ▼
Codex 完成后 → Pi Agent 汇总结果 → 返回用户
```

---

## 方式二：ACP（Agent Client Protocol）调用

### 2.1 架构总览

ACP 方式相比 Bash 方式多了两层抽象，提供了结构化的会话管理和事件流：

```
OpenClaw Gateway
  │
  ▼
Pi Agent (embedded)
  │ sessions_spawn tool, runtime="acp"
  │
  ▼
spawnAcpDirect() ─── 策略检查、会话创建、线程绑定
  │
  ▼
AcpSessionManager.initializeSession()
  │
  ▼
AcpxRuntime (extensions/acpx/src/runtime.ts)     ← OpenClaw acpx 插件
  │ spawn child_process: acpx CLI
  │
  ▼
acpx CLI binary (npm: acpx@0.1.15)               ← 外部 npm 包
  │ spawn child_process: Agent ACP Adapter
  │ ACP 协议通信 (JSON-RPC 2.0 over stdio)
  │
  ▼
Agent ACP Adapter                                  ← 第三方适配器
  (e.g. @zed-industries/codex-acp)
  │ 调用底层 Codex/Claude API
  │
  ▼
实际 Coding Agent (Codex / Claude Code / etc.)
```

### 2.2 sessions_spawn tool 入口

`sessions_spawn`（`src/agents/tools/sessions-spawn-tool.ts`）是 ACP 路径的入口工具：

```typescript
const SESSIONS_SPAWN_RUNTIMES = ["subagent", "acp"] as const;

// 当 runtime="acp" 时:
if (runtime === "acp") {
  const result = await spawnAcpDirect({ task, agentId, cwd, mode, ... }, ctx);
}
// 当 runtime="subagent" 时:
else {
  const result = await spawnSubagentDirect({ ... }, ctx);
}
```

参数说明：
- `runtime`: `"subagent"`（默认，内部 Pi 子会话）或 `"acp"`（外部 coding agent）
- `mode`: `"run"`（一次性）或 `"session"`（持久化/线程绑定）
- `thread`: 是否绑定到当前消息线程
- `streamTo`: `"parent"` 可将 ACP 事件流式传回父会话
- `agentId`: 目标 agent 标识（如 `"codex"`、`"claude"`）

### 2.3 spawnAcpDirect() 策略与初始化

`spawnAcpDirect()`（`src/agents/acp-spawn.ts`）负责策略检查和会话初始化：

1. **策略检查**：
   - ACP 是否被策略启用（`acp.enabled`）
   - 沙箱限制（ACP 必须在宿主机运行，沙箱会话不能 spawn ACP）
   - Agent 策略校验（`resolveAcpAgentPolicyError`）

2. **创建会话 key**：`agent:<agentId>:acp:<uuid>`

3. **Gateway 注册**：通过 `callGateway("sessions.patch", { key: sessionKey })` 在 gateway 注册新会话

4. **初始化 ACP Runtime**：
   ```typescript
   const acpManager = getAcpSessionManager();
   await acpManager.initializeSession({
     cfg, sessionKey, agent: targetAgentId,
     mode: runtimeMode, cwd, backendId
   });
   ```

5. **线程绑定**（可选）：通过 `bindingService.bind()` 将 ACP 会话绑定到 Discord/Telegram 线程

6. **分发任务**：通过 `callGateway("agent", { key: sessionKey, text: task })` 触发 agent 事件循环

### 2.4 AcpxRuntime：OpenClaw 与 acpx 的桥梁

`AcpxRuntime`（`extensions/acpx/src/runtime.ts`）实现了 `AcpRuntime` 接口，是 OpenClaw 插件层与 acpx CLI 之间的桥梁。

#### AcpRuntime 接口

```typescript
interface AcpRuntime {
  ensureSession(input): Promise<AcpRuntimeHandle>;    // 创建/复用会话
  runTurn(input): AsyncIterable<AcpRuntimeEvent>;     // 执行一轮对话
  cancel(input): Promise<void>;                        // 取消当前对话
  close(input): Promise<void>;                         // 关闭会话
  getCapabilities(): AcpRuntimeCapabilities;           // 查询能力
  getStatus(input): Promise<AcpRuntimeStatus>;         // 查询状态
  setMode(input): Promise<void>;                       // 设置模式
  setConfigOption(input): Promise<void>;               // 设置配置
  doctor(): Promise<AcpRuntimeDoctorReport>;           // 健康检查
}
```

#### 全局 Backend 注册

`AcpxRuntime` 通过 `registerAcpRuntimeBackend()` 注册到全局注册表（`src/acp/runtime/registry.ts`），使其对整个系统可用：

```typescript
// extensions/acpx/src/service.ts
registerAcpRuntimeBackend({
  id: "acpx",
  runtime,
  healthy: () => runtime?.isHealthy() ?? false,
});
```

#### 核心方法实现

**ensureSession** — 创建或复用 agent 会话：
```
acpx --format json --json-strict --cwd /path <agent> sessions ensure --name <key>
  ↓ 如果失败 fallback ↓
acpx --format json --json-strict --cwd /path <agent> sessions new --name <key>
```

**runTurn** — 执行一轮 prompt：
```
acpx --format json --json-strict --cwd /path \
  --approve-reads --non-interactive-permissions fail \
  --timeout 300 --ttl 0.1 \
  <agent> prompt --session <name> --file -
```
- 通过 stdin 写入 prompt 文本
- 通过 stdout 逐行读取 JSON 事件（`parsePromptEventLine`）
- 返回 `AsyncIterable<AcpRuntimeEvent>`

**cancel** / **close**：
```
acpx --format json --json-strict --cwd /path <agent> cancel --session <name>
acpx --format json --json-strict --cwd /path <agent> sessions close <name>
```

### 2.5 acpx CLI：统一的 Agent 协调器

acpx（npm 包 `acpx@0.1.15`，源码仓库 `github.com/openclaw/acpx`）是一个独立的命令行工具，职责是通过 ACP 协议与各种 coding agent 通信。

#### Agent 注册表

acpx 内部维护了一个 agent 名称到启动命令的映射：

```javascript
AGENT_REGISTRY = {
  codex:    "npx @zed-industries/codex-acp",       // Codex 的 ACP 适配器
  claude:   "npx -y @zed-industries/claude-agent-acp",  // Claude Code 的 ACP 适配器
  gemini:   "gemini",                               // Gemini 原生支持
  opencode: "npx -y opencode-ai acp",               // OpenCode 的 ACP 适配器
  pi:       "npx pi-acp"                            // Pi 的 ACP 适配器
};
```

**关键设计**：acpx 不直接调用 `codex` 或 `claude` CLI，而是调用各 agent 的 **ACP 协议适配器**（`*-acp` 包）。这些适配器由 Zed Industries 等第三方维护，负责将 ACP 协议翻译为各 agent 的内部 API。

#### acpx 启动 Agent 的过程

```javascript
// 1. 解析命令
const { command, args } = splitCommandLine("npx @zed-industries/codex-acp");

// 2. Spawn 子进程
const child = spawn(command, args, {
  cwd: options.cwd,
  env: buildAgentEnvironment(authCredentials),  // 注入认证环境变量
  stdio: ["pipe", "pipe", "pipe"]               // stdin/stdout 用于 ACP 通信
});

// 3. 建立 ACP 连接 (NDJSON 双向流)
const input  = Writable.toWeb(child.stdin);     // acpx → agent
const output = Readable.toWeb(child.stdout);    // agent → acpx
const stream = ndJsonStream(input, output);     // NDJSON 编解码
const connection = new ClientSideConnection(handlers, stream);

// 4. 协议初始化握手
const initResult = await connection.initialize({
  protocolVersion: PROTOCOL_VERSION,
  clientCapabilities: {
    fs: { readTextFile: true, writeTextFile: true },
    terminal: true
  },
  clientInfo: { name: "acpx", version: "0.1.0" }
});

// 5. 认证（如果 agent 要求）
await authenticateIfRequired(connection, initResult.authMethods);
```

#### ACP 协议通信方向

| 方向 | 方法 | 说明 |
|------|------|------|
| acpx → agent | `initialize` | 协议握手，声明能力 |
| acpx → agent | `prompt` | 发送用户任务/指令 |
| acpx → agent | `cancel` | 取消当前任务 |
| acpx → agent | `loadSession` | 恢复已有会话 |
| acpx → agent | `setSessionMode` | 切换 agent 模式 |
| agent → acpx | `session/update` | 流式输出（文本、思考、工具调用） |
| agent → acpx | `requestPermission` | 请求操作权限 |
| agent → acpx | `readTextFile` | 读取文件 |
| agent → acpx | `writeTextFile` | 写入文件 |
| agent → acpx | `createTerminal` | 创建终端执行命令 |
| agent → acpx | `terminalOutput` | 终端输出数据 |
| agent → acpx | `killTerminal` | 终止终端 |

acpx 在此扮演 ACP 协议中 **Client（编辑器）** 的角色，为 agent 提供文件系统访问和终端能力。

#### acpx 的权限控制

acpx 内部实现了 `FileSystemHandlers` 类，根据 `permissionMode` 控制 agent 的文件操作：

| 模式 | 读文件 | 写文件 |
|------|--------|--------|
| `approve-all` | 允许 | 允许 |
| `approve-reads` | 允许 | 需确认（非交互模式拒绝/失败） |
| `deny-all` | 拒绝 | 拒绝 |

OpenClaw 默认使用 `approve-reads`，即 agent 可以自由读文件，但写操作受限。

### 2.6 ACP 事件流解析

`AcpxRuntime.runTurn()` 逐行读取 acpx stdout 的 JSON 事件，通过 `parsePromptEventLine()` 解析为统一的 `AcpRuntimeEvent`：

| acpx 输出的事件 type | 解析后的 AcpRuntimeEvent type | 说明 |
|---------------------|-------------------------------|------|
| `text` | `text_delta` (stream: "output") | agent 输出文本片段 |
| `thought` | `text_delta` (stream: "thought") | agent 思考过程 |
| `tool_call` / `tool_call_update` | `tool_call` | 工具调用状态 |
| `agent_message_chunk` | `text_delta` (stream: "output") | agent 消息文本块 |
| `agent_thought_chunk` | `text_delta` (stream: "thought") | agent 思考文本块 |
| `usage_update` | `status` | token 使用量 |
| `available_commands_update` | `status` | 可用命令更新 |
| `current_mode_update` | `status` | 模式切换 |
| `done` | `done` | 任务完成 |
| `error` | `error` | 错误 |

同时支持 JSON-RPC 2.0 `session/update` 通知格式——这是 ACP 协议的原生格式。

### 2.7 ACP 方式的完整数据流

```
用户: "用 Codex 给我在这个 thread 里搞个 snake game"
  │
  ▼
OpenClaw Gateway (WebSocket) → Discord/Telegram thread
  │
  ▼
Pi Agent (embedded, createAgentSession)
  │ 识别到应使用 ACP 方式（thread-bound 场景）
  │ 调用 sessions_spawn tool, runtime="acp"
  │
  ▼
createSessionsSpawnTool.execute()
  │ runtime="acp" → spawnAcpDirect()
  │
  ▼
spawnAcpDirect() (src/agents/acp-spawn.ts)
  │ 1. 策略检查: ACP 启用？沙箱限制？Agent 策略？
  │ 2. 生成 sessionKey: "agent:codex:acp:<uuid>"
  │ 3. Gateway 注册: sessions.patch
  │ 4. ACP Runtime 初始化:
  │    acpManager.initializeSession({ agent: "codex", ... })
  │ 5. 线程绑定: bindingService.bind()
  │ 6. 分发任务: callGateway("agent", { key, text: task })
  │
  ▼
AcpxRuntime.ensureSession() (extensions/acpx/src/runtime.ts)
  │ spawn: acpx --format json codex sessions ensure --name <key>
  │ 返回: AcpRuntimeHandle { sessionKey, runtimeSessionName, ... }
  │
  ▼
AcpxRuntime.runTurn(prompt) — 执行 prompt
  │ spawn: acpx --format json --approve-reads --cwd /path \
  │        codex prompt --session <name> --file -
  │ stdin.end(promptText)     ← 写入用户任务
  │ stdout readline           ← 逐行读取 JSON events
  │
  ▼ ─── acpx CLI 内部 ───
  │
  │ resolveAgentCommand("codex")
  │   → "npx @zed-industries/codex-acp"
  │
  │ splitCommandLine → spawn("npx", ["@zed-industries/codex-acp"])
  │   stdio: ["pipe", "pipe", "pipe"]
  │
  │ ClientSideConnection over ndJsonStream(stdin, stdout)
  │   → connection.initialize()      ACP 握手
  │   → connection.prompt({          发送 prompt
  │       sessionId, prompt: [{ type: "text", text }]
  │     })
  │
  ▼ ─── @zed-industries/codex-acp 内部 ───
  │
  │ 调用 Codex API / runtime
  │ 执行编码任务（读写文件、运行命令等）
  │ 通过 ACP 协议发回 session/update 通知
  │
  ▼ ─── 回到 acpx ───
  │
  │ agent 请求 readTextFile → acpx FileSystemHandlers 处理
  │ agent 请求 writeTextFile → acpx 检查权限后执行
  │ agent 请求 createTerminal → acpx 创建子终端
  │ agent 发送 session/update → acpx 转为 JSON 事件输出到 stdout
  │
  ▼ ─── 回到 OpenClaw ───
  │
  AcpxRuntime.runTurn() 逐行解析:
  │ parsePromptEventLine(line) → AcpRuntimeEvent
  │   { type: "text_delta", text: "...", stream: "output" }
  │   { type: "tool_call", text: "edit file", status: "running" }
  │   { type: "done" }
  │
  ▼
  ACP 事件 → 流式传回 Pi Agent → Gateway → 用户消息 thread
```

---

## 两种方式的对比

| 维度 | Bash (exec) | ACP (sessions_spawn) |
|------|-------------|---------------------|
| **调用层级** | Pi → exec tool → ProcessSupervisor → CLI 进程 | Pi → sessions_spawn → acpManager → AcpxRuntime → acpx CLI → ACP adapter → agent |
| **通信协议** | 原始 stdin/stdout 文本流 | JSON-RPC 2.0 (ACP 协议) |
| **会话管理** | bash-process-registry（内存，无持久化） | acpx session store（支持持久化和恢复） |
| **输出解析** | 原始文本，Pi 自行理解 | 结构化 JSON 事件（text_delta, tool_call, done, error） |
| **权限控制** | agent CLI 自身的权限机制 | acpx FileSystemHandlers（approve-all/approve-reads/deny-all） |
| **线程绑定** | 不支持 | 支持绑定到 Discord/Telegram 线程 |
| **流式回传** | 通过 process tool 手动轮询 | 支持 streamTo="parent" 自动流式回传 |
| **PTY 支持** | 原生支持 PTY（交互式 CLI） | 不使用 PTY（child_process + pipe） |
| **多 agent 协同** | 手动管理多个后台进程 | 通过 subagent-registry 自动管理生命周期 |
| **适用场景** | 快速一次性任务、需要 PTY 的交互式 CLI | 持久会话、线程绑定、需要结构化事件流的场景 |

---

## 核心组件关系图

```
                          ┌──────────────────────────────┐
                          │     OpenClaw Gateway         │
                          │     (WebSocket API)          │
                          └──────────┬───────────────────┘
                                     │
                          ┌──────────▼───────────────────┐
                          │    Pi Agent (embedded)        │
                          │  createAgentSession()         │
                          │  @mariozechner/pi-coding-agent│
                          └──┬───────────────────────┬───┘
                             │                       │
                    ┌────────▼─────────┐   ┌────────▼──────────┐
                    │   exec tool      │   │ sessions_spawn     │
                    │ (Bash 方式)       │   │ tool (ACP 方式)    │
                    └────────┬─────────┘   └────────┬──────────┘
                             │                       │
                    ┌────────▼─────────┐   ┌────────▼──────────┐
                    │ ProcessSupervisor │   │ spawnAcpDirect()  │
                    │  ├─ PTY adapter  │   │  ├─ 策略检查       │
                    │  └─ child adapter│   │  ├─ 会话注册       │
                    └────────┬─────────┘   │  └─ 线程绑定       │
                             │             └────────┬──────────┘
                             │                       │
                    ┌────────▼─────────┐   ┌────────▼──────────┐
                    │ bash-process-    │   │ AcpxRuntime        │
                    │ registry         │   │ (extensions/acpx)  │
                    │  进程生命周期管理  │   │  ensureSession()   │
                    └────────┬─────────┘   │  runTurn()         │
                             │             └────────┬──────────┘
                             │                       │
                    ┌────────▼─────────┐   ┌────────▼──────────┐
                    │ 外部 CLI 进程     │   │ acpx CLI binary   │
                    │ codex exec ...   │   │ (npm: acpx@0.1.15)│
                    │ claude --print ..│   └────────┬──────────┘
                    │ opencode run ... │             │
                    └──────────────────┘   ┌────────▼──────────┐
                                           │ ACP adapter       │
                                           │ @zed-industries/  │
                                           │   codex-acp       │
                                           │   claude-agent-acp│
                                           └────────┬──────────┘
                                                     │
                                           ┌────────▼──────────┐
                                           │ Agent runtime     │
                                           │ (Codex/Claude API)│
                                           └───────────────────┘
```

---

## 关键源码文件索引

### Bash 路径
| 文件 | 说明 |
|------|------|
| `skills/coding-agent/SKILL.md` | Coding agent skill 定义（触发条件、调用方式） |
| `src/agents/bash-tools.exec.ts` | exec tool 定义（参数、安全检查） |
| `src/agents/bash-tools.exec-runtime.ts` | exec 执行逻辑（spawn 分流） |
| `src/agents/bash-tools.exec-types.ts` | exec 类型定义 |
| `src/agents/bash-tools.process.ts` | process tool（后台进程管理） |
| `src/agents/bash-process-registry.ts` | 进程会话注册表 |
| `src/process/supervisor/adapters/pty.ts` | PTY 适配器 |
| `src/process/supervisor/types.ts` | ProcessSupervisor 接口 |

### ACP 路径
| 文件 | 说明 |
|------|------|
| `src/agents/tools/sessions-spawn-tool.ts` | sessions_spawn tool 定义（runtime 分流） |
| `src/agents/acp-spawn.ts` | ACP 会话 spawn 逻辑（策略、初始化、线程绑定） |
| `src/acp/runtime/types.ts` | AcpRuntime 接口定义 |
| `src/acp/runtime/registry.ts` | ACP runtime 全局注册表 |
| `extensions/acpx/src/runtime.ts` | AcpxRuntime 实现（OpenClaw → acpx 桥梁） |
| `extensions/acpx/src/config.ts` | acpx 插件配置（版本、权限模式） |
| `extensions/acpx/src/service.ts` | acpx 插件服务（注册、启动、健康检查） |
| `extensions/acpx/src/ensure.ts` | acpx binary 版本检查与自动安装 |
| `extensions/acpx/src/runtime-internals/process.ts` | 子进程 spawn 工具函数 |
| `extensions/acpx/src/runtime-internals/events.ts` | ACP 事件解析（JSON → AcpRuntimeEvent） |
| `extensions/acpx/src/runtime-internals/jsonrpc.ts` | JSON-RPC 2.0 消息识别 |
| `extensions/acpx/src/runtime-internals/shared.ts` | 共享工具函数（权限参数、session key 解析） |

### 共享基础设施
| 文件 | 说明 |
|------|------|
| `src/auto-reply/reply/agent-runner.ts` | 顶层 reply agent 编排器 |
| `src/auto-reply/reply/agent-runner-execution.ts` | agent turn 执行与 fallback 逻辑 |
| `src/agents/subagent-registry.ts` | 子 agent 生命周期跟踪 |
| `src/agents/subagent-announce.ts` | 子 agent 结果通知回父会话 |

---

## 设计亮点

1. **协议标准化**：ACP 路径通过 Agent Client Protocol 实现了与任意 coding agent 的标准化交互，新增 agent 只需提供 ACP 适配器
2. **双层 spawn 隔离**：OpenClaw spawn acpx → acpx spawn agent-acp，两层 child_process 都使用 stdio pipe，实现进程隔离
3. **权限集中管控**：acpx 作为"虚拟编辑器"统一管控文件读写权限，agent 自身不直接操作文件系统
4. **灵活降级**：Bash 路径作为简单直接的备选，当 ACP 不可用或不适用时仍能调用 coding agent
5. **自动安装**：acpx 插件支持自动检测版本并安装匹配的 acpx binary（`ensureAcpx()`）
6. **会话持久化**：ACP 方式支持 `loadSession` 恢复之前的会话上下文，适合长期交互场景

