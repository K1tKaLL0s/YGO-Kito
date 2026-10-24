# 通用编程 Agent 接入说明（厂商无关）

本文件说明一个**具备文件读取、命令执行与进程通信能力的编程 Agent** 如何接管本项目，
不绑定 CodeBuddy、DeepSeek、DSH 或任何 SDK。CodeBuddy 只作为仓库内已有的一个具体适配
示例出现在 `coding_agent.py`，不是运行依赖。

**接口存在不等于已接通。** 本文标注的"已核实"指源码与独立测试层面；实际宿主、真实
provider、腾讯云实例均**未验证**，见 §9。

**集成与启动前提。** 本说明中的 CLI 命令需在完整项目中执行。独立交付中的 `_work/` 仅为审查与选定测试准备的局部源码副本，不含 `src/ygo_kito/cli.py`、`src/ygo_kito/__main__.py`，不能直接按独立安装包启动。应用原生响应修复时，`native.py` 与新增 `native_response_guard.py` 必须作为同一组集成；守卫依赖项目现有的 `native_protocol.NativeError`，无需新增第三方依赖。

## 1. 宿主需要什么能力

| 能力 | 说明 | 缺失后果 |
|---|---|---|
| 读文件 | 读仓库文档、`agent_serve` 的 `--state-root` 产出 | 只能空转 |
| 启动本地进程 | 起 `python -m ygo_kito agent-serve --role ...` | 无法通信 |
| UTF-8 JSON Lines 收发 | 每行一个 JSON 对象，`\n` 结尾 | 全部方法不可用 |
| 保留 request `id` | 重试与"新请求"必须可区分 | 控制类操作会重复执行 |
| 处理错误/超时/取消 | 读 `ok:false` 的 `error.code` | 会把拒绝当成成功 |
| 遵守本地文件与进程权限 | 不越出获批目录 | 角色隔离失效 |

**不需要**：MCP、特定插件、LLM SDK、云账号。网络也不是必需——除下载源码与依赖那一次。

## 2. 传输与信封

传输是**本地 stdio 上的 JSON Lines**，不是 HTTP、不是 MCP。

请求一行：

```json
{"schema_version":1,"id":"req-1","method":"capabilities","params":{}}
```

成功：

```json
{"schema_version":1,"id":"req-1","ok":true,"result":{...}}
```

失败：

```json
{"schema_version":1,"id":"req-1","ok":false,"error":{"code":"PERMISSION_DENIED","message":"method unavailable to this fixed role"}}
```

约束（已在 `dispatch` 中强制）：

- `schema_version` 必须为 `1`，信封不接受多余字段。
- `id` 必须匹配 `[A-Za-z0-9][A-Za-z0-9_-]{0,63}`。**方法名含点，不能直接用作 `id`**；
  参考驱动会把点替换成 `-`。
- 解析失败时服务端回 `id: null` 的 `INVALID_REQUEST`。
- 单行上限 1 MiB，超过即断开。

**传输层错误统一为 `ProtocolError`**：对端关闭、该行不是合法 JSON、读管道不是 UTF-8、
或写管道无法以 UTF-8 编码请求，都由参考驱动转成 `ProtocolError`（保留 `from error` 因果链），
不会把 `JSONDecodeError`/`UnicodeDecodeError` 泄漏给宿主。服务端回的 `ok:false` 则是
`RemoteError`，带稳定 `error.code`。

## 3. 角色与权限表（固定，不可由请求指定）

角色是**宿主启动参数**，不是请求字段。`method` 不在本角色集合内即 `PERMISSION_DENIED`。

| 角色 | 方法 | 个数 |
|---|---|---|
| `monitor` | `capabilities`, `runs.list`, `runs.read`, `runs.metrics`, `checkpoints.read`, `opponents.summary` | 6 |
| `trainer` | monitor 全部 + `training.prepare`, `training.recover`, `training.control` | 9 |
| `manager` | monitor 全部 + `environment.runtime`, `environment.register`, `deck.import`, `deck.read`, `opponent.register`, `coding.prepare_handoff` | 12 |
| `opponent` | `capabilities` + `duel.open`, `duel.next`, `duel.status`, `duel.submit_action`, `duel.close`, `cards.lookup` | 7 |

去重合计 **21 个方法**（`capabilities` 四个角色都有，只算一次）。

要点：

- **只有 `trainer` 能控制训练**；只有 `opponent` 能碰 `duel.*`；两者交集为空。
- `opponent` 不能写注册表、不能读 `runs.*`，因此拿不到训练私有记录。
- **角色参数不是系统沙箱。** 若同一宿主进程同时具备 shell、文件与 manager/trainer 工具，
  它可以绕过角色读取不该看的状态。真正的隔离依赖宿主权限，见 §8。

## 4. 能力发现

```json
{"schema_version":1,"id":"cap-1","method":"capabilities","params":{}}
```

返回 `api`（`ygo-kito-local-json-v1`）、`transport`（`json-lines-not-mcp`）、`role`、
`methods`（本角色可用方法排序列表）、`training_backend_configured`，以及恒为 `false` 的
`provider_connected` / `model_verified` / `provider_invocation_implemented` /
`cloud_resource_control_implemented`。

**请以 `methods` 为准，不要硬编码方法表**——上面的角色表是本版快照。

## 5. 任务接续与监控（`monitor` / `trainer`）

`runs.list` 返回每个运行目录的完整快照，字段固定：
`schema_version`, `run_id`, `state`, `revision`, `model_versions`, `metrics`,
`checkpoint_ids`, `source`。

`state` ∈ `created | running | paused | completed | failed | stopped`。
`revision` 单调递增，服务端拒绝不前进的写入。

**识别续作候选**（参考驱动 `Client.resumable_runs()` 已实现同一判定）。
关键在于：**`failed` 不能当作可直接恢复**，它必须先过 `training.recover`，因为
`training.control` 的 `resume` 只在 `paused` 下合法。

| 状态 | 是否列入候选 | `resumable` | `requires_recovery` | `next_step` |
|---|---|---|---|---|
| `created` | 是（需有 checkpoint） | `true` | `false` | `training.control` / `start` |
| `paused` | 是（需有 checkpoint） | `true` | `false` | `training.control` / `resume` |
| `failed` | 是（需有 checkpoint） | **`false`** | **`true`** | `training.recover` / 无 operation |
| `running` | 否 | — | — | 属于持有活进程的一方，绕过它去续作会争抢同一份状态 |
| `completed` / `stopped` | 否 | — | — | 终态 |

每条候选还带 `revision` 与 `expected_revision`（同值），供直接填入控制请求；
`failed` 候选的 `expected_revision` 就是 `training.recover` 要的那个值。
丢弃 `failed` 候选是不对的——那会把"需要恢复"的工作藏起来；正确做法是列出它、
标明 `requires_recovery`，再由宿主决定是否先恢复。

`checkpoints.read` 返回 `artifact_sha256` / `artifact_bytes` / `step`，并**实际读取并校验
制品哈希**后返回 `integrity_verified: true`、`deserialized: false`（不反序列化权重）。

### 指标：缺失不等于零

`metrics` 是白名单键的子集，允许为空。已知可采集与当前实际采集并不一致：

| 指标 | 含义 | 当前是否真的被采集 |
|---|---|---|
| `elapsed_seconds` | 墙钟耗时 | 是（`RunReporter.resources`） |
| `process_cpu_seconds` | 本进程 CPU | 是 |
| `process_peak_rss_bytes` | 峰值 RSS | 是，但仅 POSIX；Windows 上缺失 |
| `samples_per_second` | 吞吐 | 由训练模块计算，非 monitor 采样 |
| `cpu_percent` | CPU 占用率 | **白名单允许，但无任何代码写入** |
| `rss_bytes` | 当前 RSS | **同上** |
| `gpu_memory_bytes` | 显存 | **同上**；无 VRAM 总量键 |

因此：**键不存在表示"没采到"，绝不要渲染成 0。** 参考驱动的
`metric_gaps(metrics)` 会把 `present`/`absent` 分开并附注说明，供宿主打印 `unknown`。

## 6. 授权控制（`trainer`）

```json
{"schema_version":1,"id":"ctl-1","method":"training.control",
 "params":{"run_id":"run-a","operation":"start","expected_revision":3}}
```

- `operation` ∈ `start | pause | resume | stop | save_checkpoint`。
- **必须**带 `expected_revision`；与实际 `revision` 不符即 `STALE_STATE`，不做任何操作。
- 状态机：`start`←`created`；`pause`←`running`；`resume`←`paused`；
  `stop`←`created|running|paused`；`save_checkpoint`←`running|paused`。
- 同一 `id` + 同参数重放返回缓存结果（幂等）；同 `id` 换参数 → `control request ID conflict`。
- 同一 `(run_id, revision)` 只能预留一次控制操作。
- 执行结果不确定时返回 `{"execution":"uncertain","retry_allowed":false}`——**不要自动重试**。

**不会默认启动付费资源**：未附加训练后端时直接 `TRAINING_BACKEND_NOT_CONFIGURED`，
不执行任何操作；即使执行，回执里 `cloud_billing_stopped` 恒为 `false`，因为本地 worker
停止无法证明腾讯云实例已停止。

## 7. 卡组、环境与时期（`manager`）

当前接口**已经支持**后续配置三期资料，但没有内置任何一期数据。

### 7.1 注册环境

```json
{"method":"environment.register","params":{
  "environment_id":"ocg-2022-07","versions":{...},"authority":"community",
  "release_cutoff":"2022-09-30"}}
```

- `release_cutoff` 为 ISO 日期或 `null`。**`null` 当前语义是"当前/未限定"，不是"未知"**。
  2026 期截止日未冻结时，请注册为待定并**不要**填入猜测日期。
- `authority` ∈ `custom | community | official`。
- 返回值含 `validation`、`runtime_compatible`、`historical_rules_verified`（恒 `false`）。
  只有与运行时资源完全一致的 `custom` 环境才可能 `runtime_compatible: true`。
- 旧设计提到的 2022-07→2022-09-30、2022-10→2022-12-31 两个截止日**未经本轮核对**，
  属待用户确认资料，不得当作既成事实写入代码。

### 7.2 导入卡组

```json
{"method":"deck.import","params":{
  "deck_id":"tearlaments-2022-07-a","environment_id":"ocg-2022-07",
  "source":"user_provided","format":"ydk","content":"#created by ...\n#main\n..."}}
```

- `format` ∈ `ydk | json`；`json` 时 `content` 为 `{"main":[...],"extra":[...],"side":[...]}`。
- `source` ∈ `engineering_fixture | user_provided | external_submission`。
- 解析 `.ydk` 时分区标记**必须是** `#main` / `#extra` / `!side`；其它 `#` 开头行被静默忽略。
- 校验：卡号存在于固定卡库、张数规则（主 40–60、额外 ≤15、副 ≤15、同名上限）；
  仅当环境 `runtime_compatible` 时才套用禁限表，否则**不套用禁限表**。
- 落库：`sha256`（对规范化卡表）、`validation`、`runtime_compatible`、
  `historical_rules_verified:false`、`user_acceptance_verified:false`。
- **幂等/冲突**：同 `deck_id` + 同内容可重放；同 `deck_id` + 不同内容 →
  `registered resource conflict; use a new version ID`。不会静默覆盖。

### 7.3 已知不足（本轮未改）

- 只保存解析后的卡表与规范化哈希，**不保存 `.ydk` 原文**，牌表原始字节/注释/顺序会丢。
- 内容哈希不是记录键，无版本链、无法按哈希去重。
- 无命名"时期"概念；三期仅是训练预算阶段名，未与卡池/禁表/截止日绑定。
- 未区分"结构合法"与"该期卡池合法"：`allowed` 池参数从未由导入路径传入。
- 禁限表分区在 `native.banlist_limits` 内固定为 `2026.10`。

## 8. 对手席位（`opponent`）

```json
{"method":"duel.open","params":{}}
{"method":"duel.next","params":{}}
{"method":"duel.submit_action","params":{"state_version":"<上一窗口返回值>","action_id":"choice-3"}}
{"method":"duel.close","params":{}}
```

- `duel.open` 使用宿主配置的席位（0/1）与固定构筑，返回首窗口。
- `duel.next` 返回 `terminal`、`state_version`、`timeout_seconds`、`request`（含
  `actions`，即本席位合法动作）、`provenance`。
- `duel.submit_action` 必须回传当前 `state_version`；**不匹配即 `STALE_STATE`，动作不生效**。
- 超时或非法 `action_id` 时，服务端用确定性回退动作推进，并返回
  `accepted:false`、`fallback_applied:true`、`reason:"timeout"|"illegal_action"`。
  **回退不得计为模型决策，也不得作为有效训练样本**；该事件写入注册表审计。
- 席位信息只含本席位合法 DTO；对手手牌身份、牌序、种子不出现在返回中。

**本轮未验证**：`duel.open` 需要完整原生资源（`engine-src`、`libocgcore.so`、Lua、
`cards.cdb`）。本机没有这些，故上述动作序列的真实运行**未执行**；`STALE_STATE` 与超时
回退的**引擎内路径未验证**。同类校验在 `training.control` 上已用独立测试覆盖
（`STALE_STATE`、状态机、幂等）。

## 9. 参考驱动与独立测试

`src/ygo_kito/agent_driver.py` 是无依赖的参考客户端：

```python
from ygo_kito.agent_driver import Client, StreamTransport
client = Client(StreamTransport(proc.stdout, proc.stdin))
client.capabilities()               # 能力发现
client.resumable_runs()             # 可续作任务
client.metric_gaps("run-a")         # present/absent，缺失不填零
client.training_control("run-a", "pause", expected_revision=7, request_id="ctl-pause-1")
```

三层返回对象不要混用：

| 调用 | 返回 |
|---|---|
| `runs.metrics` / `client.metrics(run_id)` | `{"run_id", "revision", "metrics": {...}, "source"}`——读数在 **`metrics` 键下** |
| `metric_gaps(metrics_object)` | 只接受上表里 **`metrics` 的值** |
| `client.metric_gaps(run_id)` | 内部取 `snapshot["metrics"]`，推荐用这个 |

把整个运行记录直接传给 `metric_gaps` 会被判为 `ProtocolError` 而**不会**静默返回"全部缺失"。

**重试语义**：默认 request id 每次调用都不同（含每客户端随机前缀，两个客户端不会撞号）。
需要幂等的操作（尤其 `training.control`）必须**显式传同一个 `request_id` 重试**；
换新 id 会被服务端当作第二次尝试，撞上"同一 revision 只能预留一次"。

`LoopbackTransport(dispatch)` 可在同进程内驱动真实 `AgentBridge.dispatch`，用于契约测试。

独立测试：`tests/test_agent_contract.py`（22 项，全通过），覆盖信封校验、能力发现、
全角色×全方法的权限拒绝矩阵、未知方法、空状态根、无后端时控制不执行、可续作判定、
指标缺失语义、传输关闭、磁盘/编码回归、路径穿越拒绝。

## 10. 仍依赖真实宿主或资源的项目（未验证，勿视为通过）

1. 任一实际编程 Agent 宿主（CodeBuddy/DSH/其他）的端到端调用与权限隔离。
2. `duel.*` 全链路：需完整原生资源；含 `STALE_STATE`、超时回退的真实引擎路径。
3. 真实 `deck.import`：需 `cards.cdb` 与 `lflist.conf`。
4. 腾讯云部署、计费停机确认、吞吐与硬件压力。
5. 3 套主构筑与 8 套对手构筑（尚未提供，接口已预留，未虚构内容）。
6. 2026 期卡池截止日（未冻结）。
