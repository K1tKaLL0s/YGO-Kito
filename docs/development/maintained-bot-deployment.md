# 固定维护范围机器人：源码部署与运行接续

用户新增范围包含腾讯云部署时实际维护范围内的全部已有bots，不能以六样例或旧dsh副本代替。本模块交付全量源码发现、固定字节安装器、资源清单和typed源码注册表；**尚未接通机器人运行或训练**。本轮仅实际读取第三方源码/许可证，运行本项目自有CPU检查；没有安装Mono、编译C#、加载sqlite库或启动第三方程序。

## 固定来源与实际全量范围

| 来源 | 固定commit | 实际Decks C#文件／YDK | 许可证与构建区别 |
| --- | --- | --- | --- |
| [IceYGO/windbot](https://github.com/IceYGO/windbot/tree/dec0535f8669dca01457a898890a968139711b19) | dec0535f8669dca01457a898890a968139711b19 | 73／71 | 根MIT，IceYGO署名保留；WindBot.csproj为.NET Framework4.8完整exe，AnyCPU/x86 |
| [purerosefallen/windbot](https://github.com/purerosefallen/windbot/tree/1b8f89537afe930ce96d2fc8d57b0e91b1f96457) | 1b8f89537afe930ce96d2fc8d57b0e91b1f96457 | 74／73 | 根MIT，IceYGO署名保留；完整exe，另有AutoChess、额外YDK/对话与网络实现 |
| [mercury233/libWindbot](https://github.com/mercury233/libWindbot/tree/4d8cae5f08c8cd474fc65402bd163971d59bd3c8) | 4d8cae5f08c8cd474fc65402bd163971d59bd3c8 | 73／0 | 根MIT，mercury233/IceYGO署名保留；Android/Xamarin库，不是同一个exe构建 |
| [YGOMobile配置](https://github.com/fallenstardust/YGOMobile-cn-ko-en/blob/6207d220dd5c027ec97e4b400ac60ef50eaf1bd3/mobile/assets/data/conf/bot.conf) | 6207d220dd5c027ec97e4b400ac60ef50eaf1bd3 | 仅bot.conf＋根LICENSE | 根GPLv2许可文本单列保留；不下载/安装或整搬GPL客户端代码 |

[bot-sources-v1.json](../../configs/bot-sources-v1.json)锁定815份文本/资源文件的路径、长度、Git blob SHA-1和SHA-256；实际递归tree均完整返回，444个唯一文本blob均按原字节核对。两个exe工程另有14份图标/bitmap/sqlite DLL资源只记录原blob身份，**未下载或安装**；源码包不因此称为可编译的完整运行包。源码内Mono.Data.Sqlite的Robert Simpson公开领域头声明等保留原文；项目根MIT不代替依赖或卡数据许可判断。

[全量静态inventory](../../configs/maintained-bot-inventory-v1.json)保留220条Executor来源，按源码字节分81组；同名不同实现不合并掉，字节相同也保留全部source/path/class/Deck属性和来源。资源包括144条YDK路径；lib自身没有YDK，跨源候选显式列出，相同名称的不同牌表版本需要宿主选定，不能默认替换。211条bot.conf配置记录保留原名称、参数、说明与flags，其中随机入口不冒充独立Executor。它们只是源码注册名/配置别名，不是已核历史主流或强度。

HorusExecutor的实际CardId为旧黑炎龙Lv6/Lv8，不是现代荷鲁斯、荷鲁斯珠泪或巳剑混轴。ChaosRitual为光与暗之仪式，不是光暗龙；Elfnote对应耀圣。配置保留这些明确标签与排除项。纯轴候选可先作基准，战报或混轴存在不能证明优于纯轴；模块不填用户八个正式对手槽。

## 可调用的源码接口

`src/ygo_kito/bot_deployment.py`只使用Python标准库及既有契约工具，不依赖MCP、shell、编译器或进程执行。只有显式`fetch_sources`执行固定来源GET，其余入口均为本地源码检查。核心入口：

- `fetch_sources(lock, destination)`从锁定的`raw.githubusercontent.com/{repository}/{commit}/{path}`获取815份文本资源，同一Git blob只下载一次并复核每份来源的长度、SHA-256及Git blob身份。默认urllib保留正常代理和证书验证，不变更UA/代理；拒绝所有重定向，并再次核最终URL。403、其他HTTP拒绝、网络错误或字节校验不符立即停止，不重试、不换host/代理或镜像，不下载14份withheld二进制。只有全量静态发现通过才原子发布新目录，失败清理临时树，已有目标不覆盖。
- `inventory(lock, roots)`核所有锁定文件字节、发现全部Deck属性/类、读取四行bot.conf和build XML。锁中73/74/73文件数独立固定；缺/多Executor、未解析Deck、条件Compile或ExternalPolicyOnly裁剪均拒绝。三个实际csproj的完整Decks通配分别覆盖73/74/73，不能只构建外部策略代理。
- `create_bundle/verify_bundle`生成确定性离线源码包，逐成员核对可信lock、SHA和Git blob身份；拒绝重复、额外、缺失、链接、越界和超限成员，重新静态发现核inventory摘要。verify会在临时目录写惰性源码用于静态检查，结束即清理，不执行源码。
- `install_sources`只将已验证的惰性源码原字节写入全新目录，不覆盖、不编译、不启动。原LICENSE与源码头声明一起保留，文件无执行权限。
- `BotSourceRegistry(lock, installed_root)`是typed全量源码注册表。`statuses/resolve`复核来源字节和内存封印；相同来源不靠重命名重复登记。`training_adapter`目前明确拒绝并指出缺少的LAN→本工程合法动作接口，不能伪造可执行对手。

状态分开记录：

| 状态 | 何时成立 | 不包含的结论 |
| --- | --- | --- |
| prepared | 源码包/源码安装成功 | 无C#实例、无加载/对局 |
| loaded_source_registry | 源码与所有typed定义已校验并载入本项目注册表 | `runtime_loaded=false`，不代表第三方库/进程加载 |
| runtime_loaded、normal_duel_verified | 本模块不自行置true；需要后续真实运行接线和精确范围证据 | 不自动带来强度或历史规则资格 |
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

mobile-config目录只含原`LICENSE`与`mobile/assets/data/conf/bot.conf`。普通完整Git检出可作其他三个输入根；`.git`元数据不打包。二进制构建资源若在检出中存在，仅允许清单列明的额外路径，仍不会打包/执行，也不能据源码校验声称其已验。

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

本轮真实第三方源码由先前只读源码工具取得后生成并校验包，未调用实际安装；新增fetch不在当前云端重复执行815个网络请求。fetch拒绝/重定向/强hash/去重/临时树清理，以及安装器和typed加载均由注入假opener和明示合成惰性C# fixture测试，不能声称urllib已实际下载成功。源码包原有实际收据见[本次源码准备](../reports/2026-10-25-bot-source-preparation.json)；缓存中的源码和原始工具响应不是部署依赖或已运行机器人。

## 尚缺的真实运行接线与专项审批

两份exe README要求YGOPro/YGOSharp/SRVPro房间服务。libWindbot虽有公开`InitAndroid(assetPath,databasePath,confPath)`和`RunAndroid(arg)`，后者仍创建GameClient、通过YGOClient.Connect(host,port)接房间并Tick；它没有接本项目DecisionRequest并返回action_id的公开callback。其csproj依赖Mono.Android/Mono.Data.Sqlite、Embeddinator-4000 0.4.0及Xamarin.Android.Support.v7.AppCompat 25.4.0.2，PostBuildEvent会删除output并启动Android/Java生成；**本轮不执行该Android项目**，也不调用Test1中的硬编码公网站点。

当前本项目规则入口是ctypes core与合法单席位DTO，不是YGOPro LAN游戏房间服务。还需实际实现并验证：房间握手/版本与生命周期；严格席位可见的STOC消息/查询投影；WindBot CTOS选择与当前合法action_id之间的绑定和校验；超时/非法/旧窗口、进程结束与重放收据；各实际bot/所选牌表/规则资源的运行结果。不能直接把WindBot原始response绕过本项目合法选项/guard，也不能让隐藏身份或seed进入策略。已有PreparedIndexWindow只转DTO索引，不承担整个LAN协议。

这是当前新增“实际维护全量bots部署”范围尚缺的具体工程接线，不是缺GPU或provider凭据，也不是一个任意bot泛化占位能代替的接口。准备工作不等于已将220条来源接入训练；父任务将处理运行专项审批与接线实现。

[专项审批packet](../reports/2026-10-25-bot-build-run-approval-packet.json)为两个完整MIT exe分别列固定repo/commit、工作目录、Mono工具安装候选、完整WindBot.csproj构建argv及仅`Host=127.0.0.1`的测试argv。当前mono/msbuild/xbuild/dotnet均未安装，工具链版本未冻结；packet只准备命令，**未执行**。实际构建前须落实工具版本、.NET4.8引用与缺失本地资源；安装包会变更系统，MSBuild可以执行第三方tasks，mono/sqlite运行须有界隔离，故交父任务按具体命令单独处理批准。没有以更换工具绕过拒绝。

GPU锁安装、实机调优、正式能力训练仍属于腾讯云第二阶段；PC和可选LLM后置。这里报告的源码/真实机器人接线范围是用户本次新增的软件工作，不能以静态清单替代，也不扩大成模型强度或所有时期历史资格要求。
