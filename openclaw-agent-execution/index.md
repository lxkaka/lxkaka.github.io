# OpenClaw 任务执行机制：从 Tool Call 到多 Agent 编排


OpenClaw 是一个开源、自托管的自主 AI agent——运行在你自己的机器上，通过你已在使用的消息平台（Mattermost、Slack、Discord、WhatsApp、Telegram 等）作为交互界面，能够真正执行任务，而不只是回答问题。

当用户发送一条消息，OpenClaw 底层究竟发生了什么？答案取决于任务的复杂程度——它有三种完全不同的执行路径：

1. **单步 Tool Call**：简单任务，如生成一张图片
2. **内置子 Agent**：复杂任务，需要多轮推理，在进程内 fork 出子 Agent
3. **外部 Coding Agent**：需要写代码、操作文件系统，启动 Claude Code / Codex 等外部进程

本文从最简单的场景出发，逐步深入到最复杂的多 Agent 编排，把三条路径讲清楚。

---

## 基础：消息是如何到达 Bot 的

在讨论三种路径之前，先理解消息进入系统的通路，因为这部分对所有路径都一样。

OpenClaw 的核心是一个 **Gateway** 进程，它同时维护多个消息频道的 WebSocket 连接（Mattermost、Slack、Discord 等）。

以 Mattermost 为例（`extensions/mattermost/src/mattermost/monitor-websocket.ts`）：

```
WebSocket 连接 wss://mattermost/api/v4/websocket
    │
    │  收到 event: "posted"
    ▼
monitor.ts — debouncer 去重 + 权限/mention 校验
    │
    ▼
createChannelReplyPipeline() — 设置 typing 指示器、分块限制
    │
    ▼
dispatch-from-config.ts — 会话路由、插件钩子触发
    │
    ▼
get-reply.ts — 解析 agent 配置，调用 runEmbeddedPiAgent()
```

Gateway 管理着每个 channel 的重连策略（指数退避，最大 10 次），确保连接始终在线。

消息经过这条公共路径之后，才进入三种不同的执行路径。

---

## LLM 如何决定走哪条路径

这是整个架构最关键的问题：三条路径的"路由器"在哪里？

答案是：**路由器就是 LLM 本身，它通过工具描述和系统提示词来做决策。**

### 工具是怎么传给 LLM 的

`createOpenClawTools()`（`src/agents/openclaw-tools.ts`）负责实例化所有可用工具，包括 `image_generate`、`web_search`、`sessions_spawn` 等。之后 `createOpenClawCodingTools()`（`src/agents/pi-tools.ts`）将这些工具与文件系统工具合并，经过策略过滤（权限、模型限制等），最终通过 `toClientToolDefinitions()` 转换成 LLM API 规定的 JSON Schema 格式，随每次请求一起发出。

LLM 看到的，是一份工具列表——每个工具有名称、描述、参数 schema。它根据这份列表和当前的对话上下文，决定调用哪个工具、传什么参数。

### 系统提示词里的路由指引

`sessions_spawn` 工具在 schema 层面的 description 只有一句话：

> "Spawn an isolated session (runtime="subagent" or runtime="acp"). mode="run" is one-shot and mode="session" is persistent/thread-bound."

这远不足以让 LLM 知道什么时候该用哪个 runtime。**真正的路由逻辑写在系统提示词里**（`src/agents/system-prompt.ts`）：

> "If a task is more complex or takes longer, spawn a sub-agent. Completion is push-based: it will auto-announce when done."

> "For requests like 'do this in codex / claude code / cursor / gemini' or similar ACP harnesses, treat it as ACP harness intent and call sessions_spawn with runtime: 'acp'."

也就是说，系统提示词用自然语言告诉 LLM：
- 遇到复杂多步骤任务 → `sessions_spawn(runtime="subagent")`
- 用户明确提到外部工具或需要操作文件系统 → `sessions_spawn(runtime="acp")`
- 其他情况 → 直接调用对应工具函数

这是一种**用提示词编写的软路由**，而非硬编码的条件判断。LLM 的理解能力就是路由逻辑本身。这意味着路由规则可以随着提示词演进，不需要改动代码，但也意味着边界情况下 LLM 有可能选错路径。

---

## 路径一：单步 Tool Call

### 场景

用户发送：`帮我画一只猫`

### 执行流程

```
runEmbeddedPiAgent()  ← src/agents/pi-embedded-runner/run.ts
    │
    │  调用 LLM（Anthropic / OpenAI 等）
    │  LLM 返回: tool_call → image_generate(prompt="一只可爱的猫")
    │
    ▼
image-generate-tool.ts  ← src/agents/tools/image-generate-tool.ts
    │
    ├─ 解析参数（prompt / size / aspectRatio / count）
    ├─ resolveSelectedImageGenerationProvider() 选择 provider
    └─ generateImage()
         ├─ extensions/image-generation-core/src/runtime.ts
         ├─ 按候选链逐一尝试（Failover）
         │   候选 1: OpenAI gpt-image-1  → 失败？
         │   候选 2: Google Imagen        → 成功
         └─ saveMediaBuffer() 保存到本地 media 目录

    │  tool result: { media: { mediaUrls: ["..."] } }
    ▼
pi-embedded-subscribe.handlers.tools.ts
    └─ 提取 mediaUrls，加入待发送队列

    ▼
reply-delivery.ts  ← extensions/mattermost/src/mattermost/reply-delivery.ts
    └─ 文本分块 + 调用 Mattermost API 上传图片文件
```

### 关键特点

**同步阻塞**：LLM 发出 `tool_call` 后，Gateway 同步等待工具函数执行完毕，拿到结果后继续推理（或直接回复）。整个过程在一个 `runEmbeddedPiAgent()` 的异步调用栈里完成，不涉及任何进程间通信。

**Failover 机制**：图片生成支持多 provider 候选链。一个 provider 失败，自动切换下一个，所有候选都失败才报错。

**工具注册**：`createOpenClawTools()` 在创建 agent 时注册所有可用工具。`image_generate` 工具只有在配置了图片生成模型，或环境变量中有兼容 provider 的 API key 时才注册。

### 适用场景

- 图片生成、视频生成
- 网络搜索
- 文件读写
- 单次外部 API 调用

一句话：**LLM 决策 → 执行函数 → 返回结果**，一个来回搞定。

---

## 路径二：内置子 Agent

### 场景

用户发送：`帮我调研一下 X 技术的优缺点，然后写一份对比报告`

这种任务有多个独立子任务（并行调研各个方向），并且每个子任务本身也可能需要多轮工具调用。直接用单步 tool call 搞不定——任务需要独立的上下文、独立的推理链。

### LLM 如何决定启动子 Agent

OpenClaw 向 LLM 提供了两个特殊工具，与 `web_search`、`image_generate` 完全平级：

- **`sessions_spawn`**：创建并启动一个子 Agent（`src/agents/tools/sessions-spawn-tool.ts`）
- **`subagents`**：管理已有子 Agent（list / kill / steer）

LLM 根据任务复杂度自主决定是否 spawn——**系统里没有硬编码的 orchestrator**，完全靠 LLM 的判断。

### 执行流程

```
父 Agent LLM 决定 spawn
    │
    │  tool_call: sessions_spawn({
    │    task: "调研 X 技术的优点",
    │    runtime: "subagent",
    │    mode: "run",
    │    cleanup: "delete"
    │  })
    │
    ▼
src/agents/acp-spawn.ts → spawnSubagentDirect()
    │
    ├─ 深度检查：callerDepth < maxSpawnDepth（默认 1）
    ├─ 并发检查：activeChildren < maxChildren（默认 5）
    ├─ 生成 childSessionKey = "agent:<id>:subagent:<UUID>"
    ├─ buildSubagentSystemPrompt()
    │   └─ 根据深度确定角色：
    │       depth < maxSpawnDepth → orchestrator（可继续 spawn）
    │       depth = maxSpawnDepth → leaf（不可再 spawn）
    └─ Gateway RPC: callGateway({ method: "agent", lane: AGENT_LANE_SUBAGENT })
              │
              ▼ 立即返回 { status: "accepted" }
              ⚠️ 父 Agent 不阻塞！

    ▼
[子 Agent Session] 在 Gateway 进程内独立运行
    ├─ 独立 transcript
    ├─ 独立工具集（完整 createOpenClawTools()）
    ├─ 独立 LLM 调用循环
    └─ 任务完成，产出最终输出

    ▼
SubagentRegistry 监听 lifecycle "end" 事件
    └─ runSubagentAnnounceFlow()
         ├─ 读取子 Agent 最后一条 assistant 消息
         ├─ 格式化为"内部事件消息"
         └─ 注入父 Agent session（作为 user turn）
               失败则指数退避重试

    ▼
父 Agent 收到 announce，继续推理，汇总所有子 Agent 结果
```

### 并发执行

父 Agent 可以同时 spawn 多个子 Agent：

```
父 Agent
    ├── spawn: 调研 X 的优点     ─┐
    ├── spawn: 调研 X 的缺点     ─┤ 并发执行
    └── spawn: 调研 X 的竞品     ─┘
              │
              │  三个子 Agent 各自完成后
              │  依次 announce 回父 Agent
              ▼
         父 Agent 汇总，写对比报告
```

### 层级化能力模型

```
depth=0   main agent       可 spawn，完整权限
depth=1   orchestrator     可 spawn 自己的子 Agent
depth=N   leaf agent       不可再 spawn（N = maxSpawnDepth）
```

子 Agent 的系统提示词里明确写明角色约束。leaf 会被告知 "You are a leaf worker and CANNOT spawn further sub-agents"。

### 推送式完成通知

这是内置子 Agent 最重要的设计决策：**父 Agent 不轮询，不阻塞**。

`sessions_spawn` 的返回结果里明确包含提示：

> "Auto-announce is push-based. After spawning children, do NOT call sessions_list, sessions_history, exec sleep, or any polling tool. Wait for completion events to arrive as user messages..."

子 Agent 完成 → SubagentRegistry 监听到事件 → 自动将结果 announce 回父 Agent。如果父 Agent 当时正忙，重试机制会指数退避，确保消息最终送达。

### 故障恢复

- **Sweeper**：每 60 秒清理过期的 run 记录
- **孤儿恢复**：进程重启后从磁盘恢复 run 记录（`subagent-orphan-recovery.ts`），处理被 reload 中断的 session

---

## 路径三：外部 Coding Agent（ACP）

### 场景

用户发送：`用 Claude Code 帮我给这个项目写单测`

这类任务需要的能力超出了 OpenClaw 内置工具集——要在文件系统里读写代码、执行 shell 命令、进行多轮代码迭代。这时需要启动一个外部 coding agent。

### 三层进程链

```
OpenClaw Gateway（bot Pod 内主进程）
    └─ acpx CLI（子进程）
         └─ 外部 Harness（claude-agent-acp / codex-acp 进程）
```

外部 coding agent **不在独立 Pod 里**，而是在 bot Pod 内通过 `child_process.spawn()` 层层创建的子进程。

### 执行流程

```
父 Agent LLM 决定启动外部 coding agent
    │
    │  tool_call: sessions_spawn({
    │    task: "给项目写单测",
    │    runtime: "acp",          ← 关键：选 ACP runtime
    │    agentId: "claude",       ← 目标 harness
    │    mode: "run",
    │    thread: true             ← 绑定到消息 thread，实时输出
    │  })
    │
    ▼
src/agents/acp-spawn.ts → spawnAcpDirect()
    │
    ├─ 检查 acp.enabled 开关
    ├─ 沙箱策略检查（沙箱内禁止 ACP）
    ├─ resolveTargetAcpAgentId()
    │   优先级：参数 agentId > 配置 acp.defaultAgent
    ├─ 生成 sessionKey = "agent:<id>:acp:<UUID>"
    ├─ Gateway session 注册（sessions.patch RPC）
    ├─ initializeAcpSpawnRuntime()
    │   → getAcpSessionManager().initializeSession()
    ├─ 线程绑定（thread=true → 绑定 Mattermost thread）
    └─ callGateway({ method: "agent" }) 分派任务
              │
              ▼ 立即返回 { status: "accepted" }

    ▼
extensions/acpx/src/runtime.ts → AcpxRuntime
    │
    ├─ resolveAcpxAgentCommand("claude")
    │   先查用户覆盖配置，再查内置映射表：
    │   "claude"  → "npx -y @zed-industries/claude-agent-acp@0.21.0"
    │   "codex"   → "npx -y @zed-industries/codex-acp@0.9.5"
    │   "gemini"  → "gemini --acp"
    │   "opencode"→ "npx -y opencode-ai acp"
    │
    ├─ ensureSession():
    │   child_process.spawn("acpx", ["sessions", "ensure", "--name", <name>])
    │   acpx 再 spawn claude-agent-acp 进程，建立持久 session
    │
    └─ runTurn():
        child_process.spawn("acpx", ["prompt", "--session", <name>, "--file", "-"])
        │
        │  stdin:  "给项目写单测..."（任务文本）
        │
        │  stdout: NDJSON 事件流（每行一个 JSON）
        │  {"type":"text_delta","text":"好的，我来分析项目结构..."}
        │  {"type":"tool_call","tool":"read_file","input":{"path":"..."}}
        │  {"type":"text_delta","text":"文件读取完成，开始写测试..."}
        │  {"type":"tool_call","tool":"write_file","input":{"path":"..."}}
        │  {"type":"done","exitCode":0}
        │
        ▼ AsyncIterable<AcpRuntimeEvent> 回传 OpenClaw

    ▼
结果回传（两种模式）

  模式 A — thread 绑定（thread=true）：
    dispatch-acp.ts + dispatch-acp-delivery.ts
    → 实时将每个 text_delta 投递到 Mattermost thread
    → 用户在 thread 里实时看到 coding agent 的工作过程

  模式 B — 流式转发到父 session（streamTo="parent"）：
    acp-spawn-parent-stream.ts
    → 将子 session 输出摘要注入父 Agent 的 system events
    → 父 Agent 收到后继续推理
```

### ACP 协议

ACP（Agent Client Protocol）基于 **JSON-RPC 2.0**，通过 **stdin/stdout NDJSON** 传输。OpenClaw 不直接实现完整的 ACP 通信——它通过 `acpx` CLI 作为中间层，自己只需要读 acpx 输出的标准化事件流。

```
OpenClaw ──spawn──▶ acpx CLI
          stdin: 任务文本
          stdout: {"type":"text_delta","text":"..."}\n
                  {"type":"tool_call",...}\n
                  {"type":"done",...}\n
                       │
                  acpx ──ACP JSON-RPC──▶ claude-agent-acp
                                         （真正的 coding agent）
```

### Harness 命令映射表

`extensions/acpx/src/runtime-internals/mcp-agent-command.ts` 维护内置映射：

| agentId | 实际命令 |
|---------|---------|
| `claude` | `npx -y @zed-industries/claude-agent-acp@0.21.0` |
| `codex` | `npx -y @zed-industries/codex-acp@0.9.5` |
| `openclaw` | `openclaw acp`（OpenClaw 递归作为自身的 ACP server！） |
| `gemini` | `gemini --acp` |
| `cursor` | `cursor-agent acp` |
| `opencode` | `npx -y opencode-ai acp` |

用户可以通过 `acpx config` 覆盖这些命令，指向自定义的 harness。

---

## 多轮对话：上下文如何跨消息保持

一个 Bot 能持续记住对话内容，依赖的是 transcript 的持久化机制。

### Transcript 存储

每个 session 的对话历史存储为磁盘上的 **JSONL 文件**，路径格式为：

```
~/.openclaw/agents/{agentId}/sessions/{sessionId}.jsonl
```

每一行是一条消息（user / assistant / tool_result），追加写入。每次 `runEmbeddedPiAgent()` 被调用时，`SessionManager.open(sessionFile)` 从磁盘加载全部历史，连同新消息一起构造 LLM 请求。历史过长时，`limitHistoryTurns` 可按配置截断。

### Session Key 的分配

一条新消息如何知道自己属于哪个 session？**这在 `dispatch-from-config` 的上游已经完成**——消息到达该函数时，`ctx.SessionKey` 已经被赋值好了（例如 Mattermost 的 channel ID + thread ID 决定了 session key）。`dispatch-from-config` 只是消费这个 key，然后决定走哪条执行路径。

### 子 Agent 的上下文隔离

子 Agent 有自己独立的 transcript 文件（独立的 sessionId）。父 Agent 看不到子 Agent 的内部推理过程。

子 Agent 完成后，announce flow 向父 Agent 的 session 注入的是一条结构化摘要消息，格式大致如下：

```json
{
  "type": "task_completion",
  "source": "subagent",
  "status": "ok",
  "result": "调研结果：X 技术优点是...",
  "statsLine": "12 turns, 3 tool calls, 45s"
}
```

父 Agent 的 transcript 里只留下这条摘要，**不包含子 Agent 的完整对话历史**。这是有意为之的设计——防止子 Agent 的大量中间推理污染父 Agent 的上下文窗口。父 Agent 基于这条摘要决定下一步行动。

### ACP session 的上下文

ACP session（外部 coding agent）的上下文由 harness 自身管理，通过 acpx 的 named session 机制持久化，与 OpenClaw 的 JSONL transcript 体系完全独立。OpenClaw 这侧只保留一个 session handle（base64url 编码的 runtimeSessionName），用于后续的 cancel / close 操作。

---

## 三种路径横向对比

| 维度 | 单步 Tool Call | 内置子 Agent | 外部 Coding Agent（ACP） |
|------|---------------|-------------|-------------------------|
| **触发方式** | LLM 调用工具函数 | LLM 调用 `sessions_spawn` | LLM 调用 `sessions_spawn(runtime="acp")` |
| **执行位置** | Gateway 进程内，同步函数调用 | Gateway 进程内，独立异步协程 | Bot Pod 内，独立子进程链 |
| **LLM** | OpenClaw 配置的 LLM | OpenClaw 配置的 LLM（可覆盖） | Harness 自带的 LLM（Claude Code 用 Anthropic API） |
| **工具集** | OpenClaw 注册的工具 | 完整 OpenClaw 工具集 | Harness 自身的工具（文件读写、shell 执行等） |
| **执行模型** | 同步阻塞 | 异步，push-based 完成通知 | 异步，流式事件输出 |
| **输出方式** | 任务完成后一次性返回 | 完成后 announce 回父 Agent | 实时流式输出到绑定 thread |
| **嵌套能力** | 不支持 | 支持（最多 maxSpawnDepth 层） | 不支持进一步 spawn |
| **沙箱兼容** | 兼容 | 兼容 | **不兼容**（harness 运行在宿主 fs 上） |
| **适用场景** | 图片生成、搜索、单次 API 调用 | 多步骤调研、并行任务分解 | 代码编写、文件操作、复杂工程任务 |

---

## 架构总结

### 三条路径的本质

**LLM 是唯一的决策者，工具调用是任务分发的唯一机制，三种路径本质上是同一套 tool call 机制在不同复杂度下的不同形态。**

- 简单任务 → tool call 调用一个函数，同步返回结果
- 中等复杂任务 → tool call 触发 `sessions_spawn`，在进程内 fork 出独立的推理上下文
- 高复杂度工程任务 → tool call 触发 `sessions_spawn(runtime="acp")`，通过 ACP 协议调起外部 coding agent 进程

三条路径共享同一个消息接收层（Gateway WebSocket）和同一个 reply pipeline，区别只在 `runEmbeddedPiAgent()` 之后如何分发和执行。

### 为什么这样设计

**为什么是 push-based，而不是让父 Agent 轮询子 Agent 的状态？**

轮询模式下，父 Agent 每次检查子 Agent 状态都要消耗一次 LLM 调用（token 和延迟），而且需要在系统提示里描述轮询逻辑，增加提示词复杂度。更根本的问题是：LLM 本质上是无状态的请求-响应模型，一个运行中的 LLM 没有能力"等待"——它只能在收到新消息时才激活。Push-based 正好契合这个模型：父 Agent 在发出 spawn 后完成本轮对话，子 Agent 完成后系统将结果作为一条新消息投递进来，父 Agent 自然地被唤醒继续推理，中间不消耗任何资源。

**为什么 subagent 和 ACP 要分成两条路径，而不是统一？**

两者的本质差异在于**信任边界和执行环境**。内置 subagent 运行在 Gateway 进程的沙箱里，工具集由 OpenClaw 完全控制；ACP session 运行在宿主文件系统上，能执行任意 shell 命令，接触真实的代码仓库。这是不同级别的权限，必须分开管控。此外，ACP harness 有自己的 LLM 配置（Claude Code 用 Anthropic API，Codex 用 OpenAI API），OpenClaw 无法统一管理，只能通过标准化的 ACP 协议与它通信，把对话协议和执行环境都委托给外部。文档对此的总结是：

> "Use ACP when you want an external harness runtime. Use sub-agents when you want OpenClaw-native delegated runs."

**为什么路由逻辑写在系统提示词里，而不是代码里？**

硬编码的路由（"如果任务包含关键词 X 则走路径 Y"）脆弱且难以维护。用提示词表达路由意图，让 LLM 结合上下文语义做判断，覆盖面更广，也更容易迭代——改提示词不需要发布新版本。代价是边界情况下可能选错路径，但这可以通过丰富提示词示例和加强测试来缓解。

