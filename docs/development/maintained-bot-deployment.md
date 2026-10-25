# 固定维护范围机器人：源码部署与运行接续

用户新增范围包含腾讯云部署时实际维护范围内的全部已有bots，不能以六样例或旧dsh副本代替。本模块交付全量源码发现、固定字节安装器、资源清单、完整构建/反射检查入口及typed注册表。合法席位投影、loopback房间和托管训练入口已有代码，但**尚无真实C#加载或对局证据**；没有可用Mono，未编译C#、加载其sqlite库或启动第三方程序。

## 固定来源与实际全量范围

| 来源 | 固定commit | 实际Decks C#文件／YDK | 许可证与构建区别 |
| --- | --- | --- | --- |
| [IceYGO/windbot](https://github.com/IceYGO/windbot/tree/dec0535f8669dca01457a898890a968139711b19) | dec0535f8669dca01457a898890a968139711b19 | 73／71 | 根MIT，IceYGO署名保留；WindBot.csproj为.NET Framework4.8完整exe，AnyCPU/x86 |
| [purerosefallen/windbot](https://github.com/purerosefallen/windbot/tree/1b8f89537afe930ce96d2fc8d57b0e91b1f96457) | 1b8f89537afe930ce96d2fc8d57b0e91b1f96457 | 74／73 | 根MIT，IceYGO署名保留；完整exe，另有AutoChess、额外YDK/对话与网络实现 |
| [mercury233/libWindbot](https://github.com/mercury233/libWindbot/tree/4d8cae5f08c8cd474fc65402bd163971d59bd3c8) | 4d8cae5f08c8cd474fc65402bd163971d59bd3c8 | 73／0 | 根MIT，mercury233/IceYGO署名保留；Android/Xamarin库，不是同一个exe构建 |
| [YGOMobile配置](https://github.com/fallenstardust/YGOMobile-cn-ko-en/blob/6207d220dd5c027ec97e4b400ac60ef50eaf1bd3/mobile/assets/data/conf/bot.conf) | 6207d220dd5c027ec97e4b400ac60ef50eaf1bd3 | 仅bot.conf＋根LICENSE | 根GPLv2许可文本单列保留；不下载/安装或整搬GPL客户端代码 |

[bot-sources-v1.json](../../configs/bot-sources-v1.json)当前锁定829份文件的路径、长度、Git blob SHA-1和SHA-256：先前815份文本/资源加已获准补齐的14份图标/bitmap/sqlite DLL。实际14个路径共6个唯一blob已正常GET并核对原字节，见[资源收据](../reports/2026-10-25-bot-build-resources.json)；被动DLL文件不代表加载成功。当前完整输入包已生成并重新验证829个成员，见[完整输入收据](../reports/2026-10-25-bot-complete-build-inputs.json)。原815份收据保留当时边界，不回写成当时已有829份。源码内Mono.Data.Sqlite的Robert Simpson公开领域头声明等保留原文；项目根MIT不代替依赖或卡数据许可判断。

[全量静态inventory](../../configs/maintained-bot-inventory-v1.json)保留220条Executor来源，按源码字节分81组；同名不同实现不合并掉，字节相同也保留全部source/path/class/Deck属性和来源。资源包括144条YDK路径；lib自身没有YDK，跨源候选显式列出，相同名称的不同牌表版本需要宿主选定，不能默认替换。211条bot.conf配置记录保留原名称、参数、说明与flags，其中随机入口不冒充独立Executor。它们只是源码注册名/配置别名，不是已核历史主流或强度。

Ice/Pure的147条桌面来源覆盖其中80个字节组；唯一仅library来源的组是`libWindbot/Game/AI/Decks/Monarch506Executor.cs`。与Pure同名文件实际仅一行配置初始化不同，但不能推导运行等价或已桌面覆盖。额外精确模块的独立桌面覆盖方案见[补充packet](../reports/2026-10-25-monarch506-overlay-approval-packet.json)，未改现有73/74份源码/计划，未执行Android或该额外移植。

HorusExecutor的实际CardId为旧黑炎龙Lv6/Lv8，不是现代荷鲁斯、荷鲁斯珠泪或巳剑混轴。ChaosRitual为光与暗之仪式，不是光暗龙；Elfnote对应耀圣。配置保留这些明确标签与排除项。纯轴候选可先作基准，战报或混轴存在不能证明优于纯轴；模块不填用户八个正式对手槽。

## 可调用的源码接口

源码准备入口只使用Python标准库及既有契约工具，不依赖MCP、shell或编译器；只有显式`fetch_sources`执行固定来源GET。注册表的独立运行入口必须先有真实完整构建审计，才会创建托管C#对手。核心入口：

- `fetch_sources(lock, destination)`从锁定的`raw.githubusercontent.com/{repository}/{commit}/{path}`获取当前829份已审输入，同一Git blob只下载一次并复核每份来源的长度、SHA-256及Git blob身份。默认urllib保留正常代理和证书验证，不变更UA/代理；拒绝所有重定向，并再次核最终URL。403、其他HTTP拒绝、网络错误或字节校验不符立即停止，不重试、不换host/代理或镜像。只有全量静态发现通过才原子发布新目录，失败清理临时树，已有目标不覆盖。
- `inventory(lock, roots)`核所有锁定文件字节、发现全部Deck属性/类、读取配置和build XML。锁中73/74/73文件数独立固定；缺/多Executor、未解析Deck、条件Compile或ExternalPolicyOnly裁剪均拒绝。三个实际csproj的完整Decks通配分别覆盖73/74/73，不能只构建外部策略代理。
- `create_bundle/verify_bundle`生成确定性离线源码包，逐成员核对可信lock、SHA和Git blob身份；拒绝重复、额外、缺失、链接、越界和超限成员，重新静态发现核inventory摘要。verify会在临时目录写惰性源码用于静态检查，结束即清理，不执行源码。
- `install_sources`只将已验证的惰性源码原字节写入全新目录，不覆盖、不编译、不启动。原LICENSE与源码头声明一起保留，文件无执行权限。
- `BotSourceRegistry(lock, installed_root)`是typed全量源码注册表。`statuses/resolve`复核来源字节和内存封印；相同来源不靠重命名重复登记。`training_adapter`须精确选择Ice/Pure Executor并提供真实全量构建/资源/构造审计、固定CDB/YDK、Mono与源码身份；通过后返回`WindBotOpponent`，其唯一生产房间为`windbot_session`。没有可注入fixture替代真实房间的生产参数。当前没有实际审计，因此请求运行仍拒绝。

状态分开记录：

| 状态 | 何时成立 | 不包含的结论 |
| --- | --- | --- |
| prepared | 源码包/源码安装成功 | 无C#实例、无加载/对局 |
| loaded_source_registry | 源码与所有typed定义已校验并载入本项目注册表 | `runtime_loaded=false`，不代表第三方库/进程加载 |
| runtime_loaded | 真实完整程序集审计才可记录；注入进程fixture永远false | 当前实际0次，不由源码登记推导 |
| normal_duel_verified | 精确bot/牌表/规则资源实际正常对局证据 | 不从反射/构造或Python投影对局推导 |
| strength_verified、history_verified | 本模块始终false，须各自独立证据 | 不从文件存在、源码数量、一次正常对局推导 |

普通腾讯云源码检出可以直接运行以下固定fetch入口，无需携带当前云端`.cache`或安装MCP。源码准备入口只需Python3.12标准库，不必先安装Torch；实际训练环境另按[训练交接](training-handoff.md)准备。从完整项目根执行：

```bash
python3.12 scripts/bot_deployment.py \
  --output .cache/bot-fetch-result.json fetch \
  --destination .cache/fetched-bot-sources --timeout 30
python3.12 scripts/bot_deployment.py \
  --output .cache/bot-bundle.json bundle \
  --roots .cache/fetched-bot-sources/roots.json \
  --archive .cache/maintained-bot-sources.tar.gz
python3.12 scripts/bot_deployment.py \
  verify --archive .cache/maintained-bot-sources.tar.gz
```

fetch成功生成`roots.json`和`fetch-receipt.json`，后续bundle不需要手填路径。失败退出2，报告包含固定target/source/path/HTTP状态、已成功的唯一blob数以及`retried:false/fallback_attempted:false`，不会发布部分目录；若遇拒绝应保存报告并停止，不靠换地址、工具或代理继续。urllib的[redirect_request](https://docs.python.org/3.12/library/urllib.request.html#urllib.request.HTTPRedirectHandler.redirect_request)允许拒绝重定向；[build_opener](https://docs.python.org/3.12/library/urllib.request.html#urllib.request.build_opener)保留默认代理处理，本实现不安装空ProxyHandler绕过它。

如果由获准渠道已有完整源码，也可按原离线路径手填JSON。四个key必须完整，值建议使用绝对路径：

```json
{
  "ice": "/explicit/source/IceYGO-windbot",
  "pure": "/explicit/source/purerosefallen-windbot",
  "library": "/explicit/source/libWindbot",
  "mobile-config": "/explicit/source/mobile-config-only"
}
```

mobile-config目录只含原`LICENSE`与`mobile/assets/data/conf/bot.conf`。普通完整Git检出可作其他三个输入根；`.git`元数据不打包。当前14份已审二进制构建资源是锁定包成员，仍只按惰性字节核验与安装，不加载执行。

```bash
python3.12 scripts/bot_deployment.py \
  --output .cache/bot-inventory.json inventory --roots .cache/bot-roots.json
python3.12 scripts/bot_deployment.py \
  --output .cache/bot-bundle.json bundle --roots .cache/bot-roots.json \
  --archive .cache/maintained-bot-sources.tar.gz
python3.12 scripts/bot_deployment.py \
  verify --archive .cache/maintained-bot-sources.tar.gz
```

接收方经获准的源码传输渠道核对包与可信源码提交/lock后，可执行惰性源码安装及注册表检查；包内普通哈希不是发布者签名：

```bash
python3.12 scripts/bot_deployment.py \
  install --archive .cache/maintained-bot-sources.tar.gz \
  --destination .cache/prepared-bot-sources
python3.12 scripts/bot_deployment.py \
  registry --installed-root .cache/prepared-bot-sources
```

本轮没有用fetch重复下载已有的815份源码；仅补资源时真实GET了6个唯一blob。fetch完整流程、拒绝/重定向/强hash/去重/临时树清理，以及安装器和typed加载有注入假opener和明示合成惰性C# fixture测试，不能称整个829文件网络流程已实测成功。源码包原有实际收据见[本次源码准备](../reports/2026-10-25-bot-source-preparation.json)；缓存中的源码和原始工具响应不是部署依赖或已运行机器人。

## 完整构建与逐名加载检查

`scripts/bot_build_check.py`默认只核定当前源码与卡库，写计划，不启动进程。下例的roots仍须指向完整安装后的四个固定来源；实际审计和注册必须使用同一源码根及工作区内资源。Ice/Pure分别执行，输出目录不能在不可变源码内：

```bash
python3.12 scripts/bot_build_check.py \
  --roots .cache/fetched-bot-sources/roots.json --source-id ice \
  --cards-cdb /absolute/workspace/cards.cdb --cards-sha256 VERIFIED_CARD_DATABASE_SHA256 \
  --build-directory .cache/bot-build/ice --report .cache/ice-build-plan.json
```

本轮已用实际829份输入和锁定CDB生成Ice73/Pure74份完整计划。Ice的`Test`与`Lucky`无本源默认YDK，显式选择唯一相同内容候选Pure `AI_Test.ydk`；Pure的`OldSchool`显式选择Ice `AI_OldSchool.ydk`。候选存在不同内容而不能唯一选择时拒绝，不随机换牌表。这些是工程资源配对，不是用户正式对手或历史合法性结论。

在已有获准Mono工具链的环境，下一步才增加下列参数，**会编译第三方源码并加载/构造全部Executor**：

```bash
python3.12 scripts/bot_build_check.py \
  --roots .cache/fetched-bot-sources/roots.json --source-id ice \
  --cards-cdb /absolute/workspace/cards.cdb --cards-sha256 VERIFIED_CARD_DATABASE_SHA256 \
  --build-directory .cache/bot-build/ice --report .cache/ice-build-audit.json \
  --execute --construct \
  --mono /usr/bin/mono --compiler /usr/bin/mcs --msbuild /usr/bin/xbuild
```

工具路径是显式示例，须核实际安装版本及哈希。Debian `mono-devel`常见提供`xbuild/mcs`而不是`msbuild`；`--msbuild`可传已获准的xbuild路径，但其.NET4.8引用、参数与项目构建兼容性当前未实编。源码默认完整`WindBot.csproj`，`ExternalPolicyOnly=false`，禁PostBuild，独立bin/obj；不缩减Executor，也没有失败后换项目的后备路线。是否所有ProjectReferences都支持共享输出参数仍须真实编译核实。

自有`BotAssemblyAudit.cs`逐名比较全部类型、Deck属性和资源。`--execute`不加`--construct`只加载程序集并检查元数据；加`--construct`还初始化配置/锁定CDB，验证每份YDK卡ID，构造每个精确Executor。Pure构造GameClient显式传其第二参数null；Ice按单参API。检查器不调用`GameClient.Start`、Android或公网入口。任一类缺失、额外、资源不符或构造失败均拒绝，不静默省略。审计记录原工具/程序集/输出哈希，当前**没有C#编译器语法或运行通过证据**。

14份被动资源中的sqlite DLL为Windows PE。固定源码在Linux不走Win32 LoadLibrary分支，仍需要实际系统`libsqlite3`；文件下载不证明该依赖可加载。反射、构造通过也不证明正常对局或强度。

## 当前运行接线与真实阻碍

两份exe README要求YGOPro/YGOSharp/SRVPro房间服务。libWindbot虽有公开`InitAndroid(assetPath,databasePath,confPath)`和`RunAndroid(arg)`，后者仍创建GameClient、通过YGOClient.Connect(host,port)接房间并Tick；它没有接本项目DecisionRequest并返回action_id的公开callback。其csproj依赖Mono.Android/Mono.Data.Sqlite、Embeddinator-4000 0.4.0及Xamarin.Android.Support.v7.AppCompat 25.4.0.2，PostBuildEvent会删除output并启动Android/Java生成；**本轮不执行该Android项目**，也不调用Test1中的硬编码公网站点。

本项目规则入口仍是ctypes core与合法单席位DTO。现有`windbot_room.py`实现仅loopback握手/版本/牌表绑定、选择窗口与合法action映射及有界真实进程上下文；`windbot_projection.py`保留正常core/guard路径，提供严格席位可见投影和托管`WindBotOpponent`；period host与训练sampler已按typed适配接线。源码/配置/audit/CDB/YDK/工具及完整Python codec模块变更会使运行封印失败。不能把原始response绕过合法选项/guard或将隐藏身份/seed交给策略。不支持的消息或选择显式拒绝，无任意bot后备策略。

这些接口已有CPU契约测试，Python投影也有独立正常native证据，见[投影说明](windbot-projection.md)；它们没有实际接过C#。仍须在可用工具环境实编两份完整程序、逐名审计资源/构造，并验证精确bot/牌表的真实loopback正常对局与覆盖结果。不把接口存在、Python正常对局或220条来源登记写成全部机器人已运行。额外library-only版本另见补充packet。

[旧审批packet](../reports/2026-10-25-bot-build-run-approval-packet.json)保留当时815文件和未接线的历史状态；其后用户已明确批准固定Ice/Pure完整编译及127.0.0.1有界验证，不是仍等该项批准。当前安装因uid1000无sudo、系统dpkg锁EACCES失败；工作区缓存APT对配置的签名源InRelease又收到代理HTTP403，见[准确阻碍收据](../reports/2026-10-25-bot-toolchain-block.json)。该路径已停，无镜像/域名/代理/工具切换；没有可用Mono，实际构建/反射/构造/第三方正常对局均为0。需允许安装且可访问获准签名源的环境，或已装获准工具链；不能靠此任务绕过当前拒绝。

GPU锁安装、实机调优、正式能力训练仍属于腾讯云第二阶段；PC和可选LLM后置。这里报告的源码/真实机器人接线范围是用户本次新增的软件工作，不能以静态清单替代，也不扩大成模型强度或所有时期历史资格要求。
