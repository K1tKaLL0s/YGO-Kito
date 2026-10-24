# 原生适配器指针/长度审计 — 2026-10-24

代码基线：`K1tKaLL0s/YGO-Kito` 分支 `codex/phase-1-cpu-foundation`，提交
`654971726c96469069a623c7bd366370b9b3a896`（远端可读的最新 head）。
行号均指本交付中改动后的 `src/ygo_kito/native.py`。

## 这份审计能证明什么、不能证明什么

能证明的：`src/ygo_kito/native.py` 里每一个把指针交给原生核心、或从原生核心接收
指针的调用点，其**缓冲区容量依据、越界检查时机、缓冲区生命周期**都已逐条列出，并
且响应缓冲区那一条已由独立实验结果支撑（见 §2 与 `tests/test_native_response_buffer.py`）。

**不能证明的**：本机没有 `engine-src`（核心源码、`libocgcore.so`、Lua 5.1/5.4 脚本、
`cards.cdb`），也没有 `configs/native-sources.lock.json` 指向的资源。因此本审计
没有、也不可能重新测出核心真实的读写长度。除响应缓冲区之外各条目的容量，来自
`native_protocol.py` 自身解码器的上界推导，不是对二进制核心的实测。

## 1. 全量调用点

| # | 位置 | 方向 | 缓冲区 / 容量 | 容量依据 | 检查时机 | 生命周期 | 结论 |
|---|---|---|---|---|---|---|---|
| 1 | `script_reader` `native.py:209` | Python → 核心 | `create_string_buffer(content)`，长度 = 脚本字节数 | 由脚本文件实际长度决定 | 无越界风险（核心按 `length[0]` 读取） | **关键**：缓冲区存入 `self._buffers[relative]`，只要引擎存活就不会被 GC；这是核心能安全读取的前提 | 正确 |
| 2 | `card_reader` `native.py:219` | 核心 → Python | 核心自有的 `CardData`（80 字节） | `_bind()` 已断言 `sizeof(CardData) == 80`，不符即 `NativeError` | 结构体大小在绑定期断言 | 核心拥有，回调期间有效 | 正确 |
| 3 | `_query` `native.py:251` | 核心 → Python | `(C.c_uint8 * 1024)` | 该 flag 组合的最大记录 ≤ 12 字节 | `length > len(buffer)` 在**调用之后** | 局部变量，调用内有效 | 容量充裕；检查是事后式（见 §3） |
| 4 | `_visible_data` `native.py:271` | 核心 → Python | `(C.c_uint8 * 64)` | `flags = 0x40001 \| 0x300`，解码 4+4+4+4+8+4 = 28 字节 | `8 <= length <= len(buffer)` 在**调用之后** | 局部变量，调用内有效 | 容量充裕（64 ≥ 28）；检查是事后式（见 §3） |
| 5 | `next_decision` `native.py:473` | 核心 → Python | `(C.c_uint8 * 65536)` | 核心消息缓冲的固定上限 65535 字节，+1 留余量 | `length < 0 or length > len(buffer)` 在**调用之后** | 局部变量，当次迭代内有效 | 正确 |
| 6 | `submit` `native.py:637-638` | Python → 核心 | 由 `native_response_guard.build_response_buffer` 生成，**256 字节** | 见 §2 | 构造期拒绝超长 payload 并断言填充为 0 | 局部变量，但跨 `set_responseb` 调用保持存活（核心同步拷贝） | **本次修复对象**，修复后正确 |
| 7 | `submit` `native.py:641` | Python → 核心 | `set_responsei`，纯整数 | 不涉及指针 | 不适用 | 不适用 | 正确（无指针） |

## 2. 已修复的缺陷：`set_responseb` 响应缓冲区

**缺陷**：原实现为

```python
buffer = (C.c_uint8 * 64)()
buffer[:len(response)] = response
self.lib.set_responseb(self.handle, buffer)
```

64 字节恰好等于适配器自身的编码上界，于是这个数字看起来"够用"：一个选择计数
字节 + 至多 63 个索引字节 = 64。但 `set_responseb` 的签名是
`(duel, void *data)`，**没有长度参数**，核心无法知道这个分配有多长，它会按固定
长度读取。该固定长度在固定核心上为 256 字节，已由核心源码直接证实（`common.h`
的 `SIZE_RETURN_VALUE 256u`、`duel.cpp` 的 `memcpy(..., SIZE_RETURN_VALUE)`），
详见 `2026-10-25-native-response-abi-evidence.md`。用 64 字节缓冲区去满足 256
字节的读取，就是读取越界：Python 侧完全不可见，只有当这块分配恰好紧贴不可读页时
才会崩溃。

**为什么这个数字必须集中管理**：编码上界（64）和核心读取长度（256）是两个互相
独立、来自不同来源的事实。把它们分散写在调用点上，正是这个缺陷的产生方式；
其中任何一个变化，调用点都不会自动跟上。

**修复**：新增 `src/ygo_kito/native_response_guard.py` 单一持有这两个常量，
`submit()` 改为调用 `build_response_buffer(response)`（3 行改动，见
`changes/native.py.patch`）。守卫同时把"payload 超过 64 字节"从原来的
`ValueError: could not broadcast input array` 变成显式 `NativeError` 拒绝——截断
一个选择会提交与模型所选项不同的动作，所以必须失败关闭而不是静默缩短。

**证据**（`tests/test_native_response_buffer.py`，15 项全通过）：其中
`IsolatedBoundaryExperimentTests` 在**子进程**中把两块匿名页映射为
`可读 | 不可读`，让被测缓冲区正好结束在边界上，再执行一次 256 字节读取：

- 64 字节缓冲区 + 256 字节读取 → 子进程非 0 退出、无 `DONE` 输出（复现越界）
- 256 字节缓冲区 + 256 字节读取 → 退出码 0 且读到 256 字节（证明修复成立）
- 256 字节缓冲区 + 64 字节读取 → 退出码 0（对照组，证明前一条的失败来自越界
  而不是测试装置本身总是失败）

这组实验不需要规则核心，因此它是**边界隔离实验**，不是真实对局证据。

## 3. 仍未消除的残余风险（本次未改，需明确记录）

第 3、4、5 条的越界检查都在原生调用**返回之后**才比较 `length`。若核心真的写超
了缓冲区，内存在那次检查执行之前就已经被写坏了，检查只能事后报告，不能预防。
它们的容量依据是协议解码器推导出的上界，而非核心的写入保证，所以严格说这仍是
"依赖核心不超出文档范围"的假设。

本次没有改动这三处，理由：它们的容量在该 flag 组合下有 2 倍以上余量，改动会触及
观测路径（`_query` / `_visible_data` 被 `_observation` 高频调用），在没有真实核心
可做回归的条件下，扩大改动面会违背"优先解决引擎稳定性、不做无关重构"的范围约束。
如果后续能用真实核心复验，建议的方向是把这三处也收敛到同类守卫模块，让容量与
核心契约的对应关系同样集中在一个地方。

## 4. 版本绑定

`CORE_RESPONSE_READ_BYTES = 256` 是**针对被固定核心的**事实，不是通用规则。它绑定
到 `configs/native-sources.lock.json` 所固定的 core 提交（`3209cd8…`），并已在该
提交的 `common.h` / `field.h` / `duel.cpp` / `ocgapi.h` 中逐条核实，见
`2026-10-25-native-response-abi-evidence.md`。若更换核心版本，必须重新核对本常数；
`native_response_guard.describe()` 已把该常数连同编码上界一起导出，便于写进回执与
报告。守卫模块的 docstring 也记录了四行核心源码出处，避免后人把它当成可以随手调大
的"保险值"。
