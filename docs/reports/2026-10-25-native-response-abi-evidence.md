# `set_responseb` 读取长度与调用约定 — 核心源码实证

日期：2026-10-25
用途：为「原生响应缓冲区」最小修复提供可核对的 ABI 依据，取代此前只能引用交接说明的状态。

## 1. 核对对象与方法

| 项目 | 值 |
|---|---|
| 规则核心仓库 | `https://github.com/Fluorohydride/ygopro-core` |
| 固定提交 | `3209cd866a55e8501a0ed358d3064d9ae0ae6b30` |
| 该身份的来源 | 仓库内 `configs/native-sources.lock.json` → `sources.core.commit`；与交接说明记录的 `core 3209cd8` 一致 |
| 读取方式 | 通过 GitHub contents API 逐个读取下列文件（未克隆、未构建、未执行核心） |

读取的文件与 SHA-256（供独立复核）：

| 文件 | 字节 | SHA-256 |
|---|---|---|
| `common.h` | 12468 | `2c78c4c7c92306cd76f09cc111c28e6604e0e3d4fc16252ec31e8cb8d1493e17` |
| `field.h` | 41163 | `fcbfc72680bbb6f53d0d6fd7555011e1213e7068ce13cef9ae6fcec7a2a5360e` |
| `duel.cpp` | 3664 | `8e5e31adb474f25a2d37c530f9cd821da8f9099e11fe6c9e46da47c657c5856f` |
| `duel.h` | 1576 | `b30b67626cf6188d4c214aed996c2bcad7c37f39e3e86d6cb27ba1295fd7434e` |
| `ocgapi.h` | 2479 | `cb7b33d709791e86be0b821152c1ca34c2a2c72847c3603b4a07826c88b802af` |
| `ocgapi.cpp` | 11745 | `31d37252ee949103bf6a93d874dcb5caa3e052a610b306f87823cb5015c86019` |
| `playerop.cpp` | 31494 | `bfa381ff02e364346d29624689d69614aca7ebb2a0cb18cff5f05138df4cc46b` |
| `field.cpp` | 133326 | `f4aab9ee9599b53117825c3dd2c31060b7b688f4731223b2029ba2c67015d846` |
| `libduel.cpp` | 192901 | `144a0da8605813016ac391d1728d8fd8bdfec7ac1f4c160917e680b529e24365` |

## 2. 五条直接证据

**① 读取长度的定义** `common.h:31`

```c
#define SIZE_RETURN_VALUE 256u
```

**② 目标缓冲区** `field.h:159-166`

```cpp
constexpr size_t SIZE_SVALUE = SIZE_RETURN_VALUE / 2;
constexpr size_t SIZE_IVALUE = SIZE_RETURN_VALUE / 4;
constexpr size_t SIZE_LVALUE = SIZE_RETURN_VALUE / 8;

union return_value {
    uint8_t bvalue[SIZE_RETURN_VALUE];
    uint16_t svalue[SIZE_SVALUE];
    int32_t  ivalue[SIZE_IVALUE];
    ...
```

**③ 唯一的实现** `duel.cpp:149-151`

```cpp
void duel::set_responseb(byte* resp) {
    std::memcpy(game_field->returns.bvalue, resp, SIZE_RETURN_VALUE);
}
```

**④ C 导出与转发** `ocgapi.h:56`、`ocgapi.cpp:357-358`

```c
OCGCORE_API void set_responseb(intptr_t pduel, byte* buf);
```
```cpp
void set_responseb(intptr_t pduel, byte* buf) {
    ((duel*)pduel)->set_responseb(buf);
}
```

**⑤ 对照：整数响应不读指针** `duel.cpp:146-148`

```cpp
void duel::set_responsei(int32_t resp) {
    game_field->returns.ivalue[0] = resp;
}
```

## 3. 由证据得出的结论

| 问题 | 结论 | 依据 |
|---|---|---|
| 核心读取多少字节？ | **恒定 256 字节**，与响应类型、`bvalue[0]` 的计数值无关 | ①③，`memcpy` 长度是编译期常量 |
| 读取方向？ | 核心从**调用方的指针**读取 256 字节，写入自己持有的 `bvalue[256]` | ③② |
| 谁拥有内存？ | 源缓冲区始终由 **Python 侧**拥有；核心不保存该指针，只保存数据副本 | ③ 是 `memcpy`，没有指针存储 |
| 存活期要求？ | 只需**在调用期间**可读满 256 字节；调用返回后即可回收 | ③ 同步拷贝 |
| 调用约定？ | `set_responseb(intptr_t, byte*)` 无长度参数；Python 侧绑定 `([C.c_void_p, C.c_void_p], None)` 在 64 位上与 `intptr_t` / `byte*` 宽度一致 | ④ `native.py:187` |
| 原 64 字节分配的性质？ | 相对 256 字节读取少 192 字节，是**确定性的越界读**（读取超出分配对象边界，属未定义行为） | ①③ |

**结论：越界读成立，且长度既有上限也有下界要求** —— 必须"至少 256 字节可读"，而旧代码只保证 64。

## 4. 对交接说明的核对结果

交接说明称"固定 core 的 `set_responseb` 无条件读取 256 字节，而适配器只分配 64 字节"。

**核对结果为：该陈述在固定提交上完全正确，并已从一手源码确认**，不是仅凭报告采信。上一轮交付把 `256` 标为"取自交接说明、未实测"，该保留意见现已可撤销：数值本身有源码依据。仍未撤销的是下面 §6 的两项。

## 5. 64 字节是"编码宽度"，与 256 是两个独立事实

适配器自身能编码的响应最长为 64 字节（1 个计数字节 + 至多 63 个索引字节），由三处编解码器各自强制：

| 位置 | 约束 |
|---|---|
| `native_protocol.py:181` | `top > 63` 即 `raise NativeError("selection exceeds bounded action enumeration")` |
| `private_selection.py:88` | `top > 63` 即 `raise NativeError('selection response/complete enumeration exceeds explicit budget')` |
| `sum_protocol.py:61` | `high + len(mandatory) > 63` 即拒绝；同行注释写明 "outside the 64-byte response" |

因此 `MAX_RESPONSE_BYTES = 64` 不会误拒任何当前编码器能产生的合法响应——超过 63 索引的候选在解码阶段就已经失败关闭，到不了提交路径。**这同时说明旧代码的 64 是有意贴着编码上界的，缺陷不在"少给了一个字节"，而在于把"编码宽度"当成了"核心读取宽度"。**

## 6. 本证据不能证明什么（明确保留）

1. **不能证明历史 SIGSEGV 由它单独造成。** 越界读是确定存在的未定义行为，但没有原始崩溃栈、没有原始种子/牌表/调用序列，因此无法把那次业务崩溃唯一归因于此。任何反向结论都需要复现条件。
2. **不能证明修复在真实核心上工作。** 本机没有 `engine-src`、`libocgcore.so`、Lua 与 `cards.cdb`，一局原生对局都跑不起来。源码核对证明的是**契约**，不是运行时行为。
3. **不能替代真实 ABI 测试。** `tests/test_native_response_buffer.py` 用真实的内存页保护复现了"读越界会崩、读 256 有 256 才安全"这一内存语义，但它测的是**我们自己构造的缓冲区契约**，没有调用真实导出函数；`ctypes` 层的 256 字节读取不是 `memcpy` 的 ABI 验证。

## 7. 顺带核对的相邻契约（同源，供审计参考）

| 调用 | 核心行为 | 位置 | 对适配器的含义 |
|---|---|---|---|
| `get_message(intptr_t, byte*)` | `read_buffer(buf)` 拷贝 `buffer_size()` 字节后返回长度；**不接收缓冲区大小** | `ocgapi.cpp:147-150`、`duel.cpp:110-115` | 适配器用 65536 字节并事后比较返回长度（`native.py:473-475`）；实际写入量取决于核心消息缓冲上限，属"信任核心不超出其缓冲"的假设，未在本轮消除 |
| `query_card(..., byte* buf, int32_t use_cache)` | 同上，写入长度由查询结果决定，不接收缓冲区大小 | `ocgapi.h:51` | `_query` 1024 字节 / `_visible_data` 64 字节，均为事后检查（见 `2026-10-24-native-pointer-audit.md` §3） |
| `set_responsei(intptr_t, int32_t)` | 直接写 `ivalue[0]`，不读指针 | `duel.cpp:146-148` | 无需缓冲区，适配器路径正确 |

## 8. 最小修复如何被本证据支持

修复只做一件事：把交给 `set_responseb` 的缓冲区从"按编码宽度分配"改为"按核心读取宽度分配"，并把两个宽度集中到一个模块。3 行改动，不触碰解码、观测或生命周期逻辑。

因为 ③ 是同步 `memcpy` 且核心不保留指针，修复**不需要**延长缓冲区寿命、不需要在 `close()` 里释放它，也不需要改动 `_buffers`（那是 Lua 脚本缓冲，属于另一类必须长期存活的对象）。这一点已在 `native.py` 注释与本文件中写明，避免后续误加额外生命周期管理。
