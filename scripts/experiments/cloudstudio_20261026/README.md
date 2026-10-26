# 2026-10-26 CloudStudio 采集脚本归档

compare_actual.py 采集实际模型的冻结对局与工程 PPO 更新；group_update_compare.py 对照四角色真实工程更新；postcheck.py 核同一合法 DTO 批量推理及 CUDA 保存恢复。对应结果在 docs/reports/cloudstudio-20261026/，历史完整报告在仓库根目录。

这些是原采集脚本，依赖 /workspace 下的原始资源、checkpoint、profile 与辅助脚本；主运行会写入 .cache/gpu-compare-20261026/，部分文件在导入时即执行。审计使用 AST／compile，不导入模块。本轮没有运行它们。

今后若单独授权复现：先按迁移清单备齐同一资源，建立独立副本，修改 ROOT／OUT 与所有固定输入、日志、辅助脚本路径，输出选全新目录；配置相同 checkpoint、种子、席位、FP32、batch、单线程和 CUDA 同步，保留预热与失败／超时分账。不要覆盖原实测目录或正式起点。
