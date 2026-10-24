# 当前整合版本的真实引擎诊断

本轮按用户新授权检查正常引擎启动、合法普通对局与重放，不重做 DP 的故障修复、内存边界实验或 SIGSEGV 复现。此前把旧任务拦截延伸为当前普通验收的理由过宽，现予以纠正。

## 缺口与证据分别是什么

| 项目 | 实际核查结果 |
| --- | --- |
| 适配代码 | a344a39 已集成 NativeNormalEngine、显式normal/effect工具、真实回放/训练与DP的native.py/guard；不是只有DTO或模拟核心。 |
| 当前云端物理资源（恢复前） | 对两个项目`.cache`逐项检查core头文件、scripts、cards.cdb、Lua、libocgcore.so、receipt.json均不存在。历史缓存未随代码Git提交迁移。 |
| 当前操作权限 | 正常锁定源码下载、编译、native-smoke、native-duel/replay及16项检查均实际执行成功，没有这些操作被拒绝的证据。 |
| 为什么此前217项没证明引擎 | 该批明确是CPU/协议白名单，未准备原生资源且整组integration_tests排除；未安排普通引擎重验，不能反推为平台禁止。 |
| 历史完整回归 | 172单元＋172集成的保存收据对应40d3e6510361aa000b87e72d44bd75c7023b6c6a，后发布等价树bb50555；不属于当前DP修复后整合代码的回归。 |
| DP修复范围 | a7085e2依据固定core源码确认set_responseb同步读取256字节，修复原64字节分配。该缺陷成立；DP报告明确不能证明历史SIGSEGV由其单独造成，也未在其本机真实核心验收。 |
| 未解除事项 | 不运行原受限故障注入/保护页实验/崩溃复现，不把普通对局通过说成历史崩溃根因唯一闭合。 |

## 本轮普通真实执行

实际运行已有`prepare_native_engine.py --root .cache`，取得锁定client/core/scripts/database/Lua源码，并本机g++构建，未下载未知可执行文件，未改绑定或DP补丁来取得首次通过。编译54.304秒，产物及每项资源哈希在云端receipt保留。

- core：3209cd866a55e8501a0ed358d3064d9ae0ae6b30；scripts：b83db1cc3f512d3bec2faafb9ecf199143332be1。
- cards：217ae165c1886af2fc36b823fc08f9fc3ec13185；Lua：6e22fedb74cf0c9b6656e9fce8b7331db847c605。
- `native-smoke`：真实通常召唤，手牌5→4，summoned=1，callback_errors=0，读取constant/utility/procedure脚本。
- `native-duel`：明确40张通常怪兽工程池，7回合、217决策，真实MSG_WIN，LP8000:0，winner=0/reason=1。
- `native-replay`：真实重新执行，响应/事件/终局全部一致，trace SHA256为66c1039b33c37f97f157e3f9a3bedb216bb4c15bec07ed8554e36e4ae362e528。
- 明确选取`integration_tests.test_native_engine`、`test_normal_duel`、`test_agent_duel`：16项通过，0失败/错误/跳过，26.790秒。包含正常实局、本席位隐藏信息边界、非法action合法回退、旧窗口拒绝和stdio超时；没有故障注入、kill或内存越界实验。

真实库SHA256为b33b0fb302e24e4757532f224f04aec21e4b16153979b112923c6f746b2e531f；卡库SHA256为ff52f585de24a762a4e613ac37654b1a7fb15a58990c14f5eada85f28c3be152，与历史工程资源相同。原始回放/输出保存在本云端`.cache/pretraining-engine`，不作为玩家输入或正式用户卡组；不上传双席位响应轨迹。后续period上下文/模型设备改动完成后还须在最终提交重跑相应必要回归，首次结果不替代最终结果。

`status.engine.ready=false`属于尚未配置的一般后端。原`engine_status()`已同时列出显式native工具；这个通用字段不能再用于断言已准备的native资源不存在。

## 尚未证明

普通工程对局不等于珠泪/一般卡池支持、历史卡池与旧裁定、官方禁表全表核对、PC标准回放、外部模型、GPU吞吐或训练能力通过。正式用户牌表不是最小普通对局验收的前提；收到后仍须按机制、时期和驱动逐项验证。后续源码会为历史禁表选择增加默认行为不变的独立hook，该变化不触碰ABI或DP响应逻辑，须另列代码差异与验收。
