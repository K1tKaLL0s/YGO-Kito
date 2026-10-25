# 维护范围机器人接线交付与真实阻碍

代码保存为 `539368b4f024d5f349e94a974dca2bb6910f74f4`，沿用PR3和原作者提交历史。本批完成独立可做的源码/资源部署、完整构建检查入口、实际本机LAN协议与既有分期训练接线；**没有完成真实C# WindBot加载与逐bot对局，尚不能执行条件合并**。新阻碍不是用户牌表、GPU、PC或LLM。

## 已保存的代码与来源

- 固定四源全部829成员（815原文本/资源＋14核验被动二进制）、许可证、配套YDK与发行配置均进入可校验fetch/bundle/install路径。保留220条Executor来源、81组源码字节身份、144条YDK路径、211配置别名；字节相同不等于运行等价。
- Ice73、Pure74完整构建计划实际生成并核全部输入，未裁成ExternalPolicyOnly。`scripts/bot_build_check.py`默认仅准备计划；显式执行才完整构建、加载程序集并逐名核metadata/资源/constructor，缺失或失败拒绝。自有C#审计器已静态适配两源不同构造签名，**未实际编译**。
- `windbot_room.py`实现真实TCP握手/牌表上传校验、粗粒度事件及提示编码、回复到当前LegalAction的唯一映射。固定127.0.0.1、ServerMode=False、精确Executor/牌表/DB；总期限、迟到回复关闭、自管Popen deadline/terminate/kill/reap与uncertain拒绝均有CPU契约。未发送信号给原生宿主或其他进程。
- `windbot_projection.py`从正常引擎已有接口提取当前席位合法事实，保留原ABI/submit/guard。覆盖普通流程、局部匿名检索、公开素材/extra、已实现的确认/洗切及跨区事件；不传raw buffer、响应表、真实隐藏顺序或seed。registry固定使用实际launcher，不能用自定义room回调冒充pinned C#。完整四Python模块、程序集、来源、工具与资源摘要进入运行身份和持续封印。
- `BotSourceRegistry.training_adapter → PeriodBuildAssets.bind_bot_opponent → period_host.bots → CpuTrainer.sample_episode`已实际接线；构筑改变actor后重绑同一bot与新profile。缺真实完整审计即拒绝，不回退规则AI。既有rule/snapshot及旧描述符兼容。[宿主字段](../development/period-runtime.md)、[支持与拒绝范围](../development/windbot-projection.md)。

147条桌面来源覆盖80/81字节组；library独有Monarch506变体完整保留源码，和Pure对应类仅一行效果配置逻辑不同，不能以同名当已运行等价。额外隔离桌面variant方案已静态准备在[专项packet](2026-10-25-monarch506-overlay-approval-packet.json)，未执行或改写原73/74计划，也未运行Android构建。

## 实际证据，分别解释

| 范围 | 本批真实结果 | 不代表 |
| --- | --- | --- |
| 已提交源码CPU白名单 | `539368b`，462/462，0失败/错误/跳过，29.40秒；Python3.12.14/Torch2.9.1+cpu；implementation SHA256 `987676c4c6b44fc21d529f331d9d06bb75f5c012e1ceaa0ed0b8205a8f7b8304` | 无native调用、无C#、非能力验收 |
| 正常真实core→Python LAN codec | 218合法提交、110席位帧、7回合自然终局 | 未启动C# WindBot |
| 既有Rescue Cat检索→XYZ | 22合法提交、18帧，局部检索及两个公开素材实际完成 | 非自然终局、非一般卡效或强度证明 |
| 四角色初始化/保存/恢复 | 实际已更新工程source→四个新模型，保存后删除临时source副本再恢复，四参数摘要/provenance相等；新run更新0，原source未改 | 非新训练、非正式历史/2026卡池，源仍旧2022-10工程cutoff10/01 |
| 完整机器人输入包 | 829成员实际verify；SHA256 `a40a54efb0a4a3d6283013ec0f9f0bf6808f4eaef66a8a812238a0433e3ad5be` | 无第三方代码加载 |
| C#构建/反射/构造/对局 | 全部0次 | 不能声称all bots可运行 |

统一CPU和初始化收据在[本批evidence](2026-10-25-bot-delivery-evidence/local-cpu.json)，实际两条正常引擎[聚合收据](2026-10-25-windbot-projection-evidence/normal-and-search-xyz.json)绑定最终room/projection/native/guard摘要，旧unsupported尝试保留。独立验收已推动修复来源回调替换、遗漏helper版本身份、overlay公开谓词、私有区域alias和子进程退出边界，见[独立报告](2026-10-25-independent-software-acceptance.md)。远端CI与源码包各另存实际回执，不以本地结果代替。

## 阻碍和下一步

用户已批准限定安装/编译/127.0.0.1验证，不再等待这项授权。实际系统 `apt-get install --no-install-recommends mono-devel` 因uid1000、无sudo和dpkg目录权限失败。保留既定签名/来源而改用工作区APT缓存时，配置的三个Debian snapshot InRelease于06:52:52 UTC被代理HTTP403拒绝，索引取得0；APT exit0不等于成功。已停止该路径，未换镜像、代理或工具绕过，**不是自动审批拒绝**。[准确动作、目标与状态](2026-10-25-bot-toolchain-block.json)。

需要具备已批准Mono工具链，或正常安装权限及可访问签名源的获准环境，再运行现成完整构建审计与逐bot正常资格检查。Debian mono-devel不保证提供msbuild；已有官方xbuild可显式传入，但参数兼容和实际版本仍须实编核实。本云端未安装工具、不运行第三方，不能编造编译成功。

软件还保留明确的fail-closed范围：私人牌组确认位置、部分隐藏对象连续关联、带匿名绑定对象的额外洗切、事件30/35/36/37/42等未实现事件及不支持的私有连锁触发位置。它们不当作模型缺权重；真实具体Executor若遇这些路径需按确切合法信息补适配，不能泛化包装或静默换bot。当前无法用C#真实路径验证这些剩余边界，也不能说除牌表外已经全部就绪。

3＋8正式牌表由用户提供；历史全库由既定DP流程另取，使用[真实导入格式/命令](../development/card-data-collection-contract.md)。2026截止仍11月1日JST含当日正式OCG发行、禁表仍2026.10，未到日/资料未知不提前放行。GPU安装、实测、调优、正式训练及能力验收归腾讯云第二阶段；PC归阶段3，LLM可选。本批没有付费训练、外部模型调用、凭据权限改动或合并。
