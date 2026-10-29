# 一次 OpenClaw Bot 卡死问题排查：Telegram Polling、Kubernetes Service Env 与 Node.js process.env


这次问题的表象很普通：一个 OpenClaw bot 在生产环境里突然长时间不回复消息。更麻烦的是，它不是单次模型调用超时，而是 runtime 本身变得很不稳定，`/readyz` 偶发超时，event loop delay 明显升高，Mattermost 这类非 Telegram 入口也会受到影响。

前几天我们刚做过 JuiceFS 对 OpenClaw runtime 影响的实验，也做过 LiteLLM 与模型直连的对比，所以第一反应很容易落到两个方向：

1. 是不是持久化文件系统拖慢了 runtime？
2. 是不是模型调用或 LiteLLM 代理导致了长尾？

但这次现场证据把我们带到了一个更隐蔽的方向：Telegram channel 的 isolated ingress polling。

## 现象

问题出现在 OpenClaw `2026.6.6` 系列 runtime 上。主要现象包括：

- bot 对 Mattermost 消息不回复，或者回复明显变慢；
- pod CPU 可以持续接近或超过 1 core；
- `/readyz` 出现 event loop degraded / timeout；
- 日志里并不总能看到对应的 model call 正在长时间执行；
- 降回较早的 `2026.6.6.4` 镜像后，现象明显缓解。

这里最重要的一点是：这不是单纯的“某次 LLM 慢”。如果只是模型调用慢，event loop 不应该持续被拖死，`/readyz` 也不应该在 idle 状态下频繁 degraded。换句话说，必须沿着 runtime 主进程的同步热点继续查。

## 第一轮排除：不是 JuiceFS，也不是 SQLite

因为 OpenClaw bot 挂载了 JuiceFS 来持久化会话、配置和 workspace，最初我们怀疑过文件系统。

但现场检查后有两个关键事实：

1. channel ingress queue 的主状态库实际落在本地 state 目录，例如 `/home/node/.local/state/openclaw.sqlite`。
2. 对同一张表做裸 SQLite 查询很快。

现场基准如下：

```text
direct sqlite SELECT count(*) x10000: ~118ms
direct OpenClaw state DB + Kysely query: ~0-2ms
```

如果 SQLite 或文件系统是主瓶颈，那么直接查询不可能稳定在这个量级。于是 JuiceFS 和 SQLite 查询本身都被排除：慢点不在 I/O，而在进入查询之前的某段同步 JS 代码。

## 第二轮排除：不是模型调用长尾

此前 trace 实验已经证明，在一些复杂任务里，端到端耗时确实会被 model call 和工具循环主导。但本次现场不同：

- bot 在 idle 或低流量时也可能 CPU 异常；
- event loop delay 与 readiness 退化可以独立于具体一次模型调用出现；
- Mattermost 消息链路被阻塞时，runtime 主线程已经不健康。

所以这次不能只盯着 `openclaw.model.call`。真正的问题更像是：某个 channel 或 background loop 在没有用户请求时，也在持续消耗主 event loop。

## 关键线索：Telegram Isolated Ingress Polling

OpenClaw 的 Telegram channel 支持 isolated ingress。它的目的可以理解为把 Telegram update 先落到一个本地 durable queue，再由 runtime 定期 drain：

```text
Telegram update
    -> local ingress spool / queue
    -> polling drain loop
    -> recoverStaleClaims()
    -> listClaims()
    -> listPending()
    -> dispatch message
```

这个设计本身合理：它可以把 update 接收和消息处理解耦，并通过 claim/recover 机制处理异常中断。

问题在于 polling drain 是周期性的，约每 500ms 会醒来一次。即使没有 Telegram 消息，只要 Telegram channel 处于 enabled 状态，这条 drain 路径仍然会持续运行一些 queue 操作。因为 OpenClaw 的多个 channel 共享同一个 Node.js 主进程 event loop，Telegram idle polling 如果占满 CPU，Mattermost 也会一起变慢。

继续往下看源码，慢点落到了 channel ingress queue 打开 state database 的路径。

## 根因代码：热路径里复制整个 process.env

OpenClaw `src/channels/message/ingress-queue.ts` 中有类似这样的逻辑：

```ts
function openStateDatabase(stateDir?: string) {
  return openOpenClawStateDatabase({
    env: stateDir ? { ...process.env, OPENCLAW_STATE_DIR: stateDir } : process.env,
  });
}
```

这里的意图很简单：给某个 queue 指定独立的 `OPENCLAW_STATE_DIR`，同时继承已有环境变量。

但 `{ ...process.env }` 在 Node.js 里不是一次普通对象拷贝。`process.env` 是 Node 暴露出来的特殊对象，枚举和读取每个 key 都有额外成本。如果 Kubernetes pod 里环境变量数量很大，这个成本会被放大。

而 Kubernetes 默认 `enableServiceLinks: true` 时，会把 namespace 内大量 Service 注入成环境变量。现场 pod 的数据是：

```text
process.env keys: 9274
deployment explicit env keys: ~39
```

也就是说，绝大多数环境变量不是业务显式配置，而是 Kubernetes service links 自动注入的。

现场测到的耗时非常直观：

```text
{ ...process.env } once: 917ms to 1192ms
ingress queue listPending() once: ~982ms
ingress queue listClaims() once: ~816ms
ingress queue recoverStaleClaims() once: ~869ms
```

这解释了为什么问题会表现成 CPU 和 event loop 卡顿：每 500ms 的 polling drain 会触发多次 queue 操作，而每次操作都可能先同步复制一个 9000 多 key 的 `process.env`。这个耗时不在 await 之后，不会让出 event loop；它就是主线程上的同步 CPU。

## 为什么会影响非 Telegram 消息

这是排查中很容易误判的一点。

用户感知到的是 Mattermost bot 不回复，所以直觉上会去查 Mattermost websocket、模型调用、消息发送 ACK。但真正拖慢 runtime 的是 Telegram polling。原因是 OpenClaw gateway 是同一个 Node.js 进程：

```text
Telegram polling drain
        |
        | synchronous process.env copy
        v
Node.js event loop blocked
        |
        +--> /readyz timeout
        +--> Mattermost receive/reply slow
        +--> model/tool dispatch delayed
```

也就是说，一个 channel 的 idle background loop 可以拖慢整个 gateway 进程。这类问题只看用户入口 channel 很容易查偏。

## 对照实验：关闭 Kubernetes Service Links

为了验证 `process.env` 数量是关键放大器，我们在不改 OpenClaw 代码的情况下，只调整 pod spec：

```yaml
spec:
  enableServiceLinks: false
```

效果非常明显：

```text
process.env keys: 60
{ ...process.env } once: 0ms
listPending1: 39ms
listClaims1: 1ms
recover1: 1ms
CPU after stable: ~10m
readyz eventLoop.delayP99Ms: ~20ms
eventLoop.utilization: ~0.004
```

这一步确认了两个判断：

1. Kubernetes service env 注入是这次问题的重要放大器。
2. 但 OpenClaw runtime 在热路径里复制整个 `process.env` 仍然是不合理的。

如果只改基础设施，问题可以被缓解；但只要用户运行在 service env 很多的环境，或者其他环境变量继续膨胀，runtime 仍然存在结构性风险。

## 代码级验证：用 Prototype Env Overlay 取代 Spread

真正需要的是：覆盖 `OPENCLAW_STATE_DIR`，但不要枚举复制所有环境变量。

修复思路是构造一个 prototype overlay：

```ts
export function createStateDirEnv(
  stateDir: string,
  baseEnv: NodeJS.ProcessEnv = process.env,
): NodeJS.ProcessEnv {
  return Object.assign(Object.create(baseEnv) as NodeJS.ProcessEnv, {
    OPENCLAW_STATE_DIR: stateDir,
  });
}
```

然后：

```ts
function openStateDatabase(stateDir?: string) {
  return openOpenClawStateDatabase({
    env: stateDir ? createStateDirEnv(stateDir) : process.env,
  });
}
```

这个对象只有一个 own enumerable key：`OPENCLAW_STATE_DIR`。像 `HOME`、`PATH`、`OPENCLAW_HOME` 这样的读取仍然可以沿 prototype 链回到原始 `process.env`。

本地行为验证：

```text
{"spreadOwnKeys":10002,"overlayOwnKeys":1,"overlayHome":"/home/openclaw","spreadMs":3,"overlayMs":0}
```

在真实 runtime 上做同等 patch 后，queue 操作恢复到毫秒级：

```text
Before patch:
listPending1: ~700-900ms
listClaims1: ~600-1000ms
recover1: ~700-1000ms

After patch:
listPending1: 47ms first call, then 0-1ms
listPending1000: 270ms
listClaims1000: 140ms
recover1000: 147ms
CPU after stable: ~50m
readyz eventLoop.utilization: ~0.003
```

这一步把根因闭环了：慢的不是 queue SQL，不是 SQLite，不是 JuiceFS，而是每次打开 state DB 前为了覆盖一个 env key 而复制了整个 `process.env`。

## 解决方案的取舍

最终我们采用两层方案。

### 1. 基础设施层：关闭 service env 注入

在 OpenClaw bot pod template 中设置：

```yaml
spec:
  enableServiceLinks: false
```

这是生产止血方案。它的收益不只针对 OpenClaw：在现代 Kubernetes 应用里，服务发现通常应依赖 DNS 或显式配置，而不是依赖 Kubernetes 为所有 Service 注入环境变量。关闭 service links 可以避免 `process.env` 随 namespace 规模膨胀，也能降低其他库误用环境变量枚举时的风险。

但它不是根因修复，因为 runtime 不应该在高频路径里做 O(N) 环境变量复制。

### 2. OpenClaw Runtime 层：修复热路径

我们向 upstream 提交了 issue 和 PR：

- Issue: [Telegram isolated ingress copies large process.env in queue hot path](https://github.com/openclaw/openclaw/issues/94571)
- PR: [Avoid copying process.env in ingress queue state DB opens](https://github.com/openclaw/openclaw/pull/94573)

PR 的核心改动很小：用 prototype overlay 替代 `{ ...process.env, OPENCLAW_STATE_DIR: stateDir }`，并加了一个 10000-key env 的回归测试，确保 overlay 只有一个 own key，同时仍能继承 `HOME`。

这个修复的性质很明确：

- 行为不变：仍然支持通过 env 解析 state dir；
- 复杂度下降：从每次 DB open O(env keys) 变为 O(1)；
- 风险可控：只影响有 `stateDir` override 的 ingress queue DB open 路径；
- 对基础设施更鲁棒：即使 pod env 很大，也不会被这个热路径放大。

## 为什么不是简单禁用 Telegram

临时禁用 Telegram isolated ingress 可以止血，但它不是一个好结论。

首先，Telegram channel 的 durable ingress 有实际用途：它要处理 update 接收、持久化、claim 和异常恢复。其次，问题的本质不是“Telegram 不该 polling”，而是 polling 的空转路径里包含了不应该存在的同步 O(N) 操作。

更合理的后续优化是：

- 空队列时降低 drain 成本；
- stale claim recovery 降低频率，而不是每轮都做；
- 给 drain duration 增加 metric 或 warning log；
- 把 channel background loop 的耗时纳入 OpenTelemetry trace/metrics。

这些优化可以让类似问题更早暴露，但不替代这次的根因修复。

## 经验总结

这次排障有几个值得记录的点。

第一，event loop 卡顿不一定来自“大任务”。一个看起来无害的 background polling，只要包含同步热点，就足以拖死整个 Node.js gateway。

第二，Kubernetes 默认 service env 注入在大 namespace 里是隐形风险。它会让 `process.env` 从几十个 key 变成几千甚至上万个 key。任何库只要在热路径里枚举环境变量，都可能被放大。

第三，排查 AI agent runtime 时，不能只看模型耗时。模型慢会拉长一次 turn，但 runtime event loop 被同步 CPU 卡住，会影响所有 channel、所有请求，表现更接近“系统不回复”。

第四，定位性能问题要做分层对照：

```text
端到端慢
  -> readiness/event loop 是否异常
  -> 是否与 model call 对齐
  -> 是否与 channel background loop 对齐
  -> SQL / I/O 裸测是否慢
  -> wrapper 调用是否慢
  -> wrapper 里的同步代码是否慢
```

这次正是通过裸 SQLite、Kysely、queue wrapper、`process.env` spread 四层对照，才把问题从“文件系统/数据库/模型”收敛到一行 env spread。

最后，这类问题最好的长期防线仍然是 observability。OpenClaw 已经有 OTel 插件和 event loop liveness 指标，下一步应该把单条消息粒度的 trace 做到生产可查询：从 message receive、queue、context assembly、model call、tool execution 到 channel delivery，能按一次用户消息完整串起来。只有这样，下一次“bot 没回复”才不会再靠人肉拼日志。

