# OCG 无效化与次数规则资料

来源为本机只读规则包 `N:\YGO-Kito\ocg-negation-rules-2026-10-28\`。本次纳入保留原文件内容：

- `ocg-negation-counting-manual.zh.md`：手册，复制至本目录。
- `ocg-negation-rules.json`：25 条规则、35 项来源、4 项未决问题，复制至 `src/ygo_kito/resources/rules/`。
- `ocg-negation-regression-cases.json`：23 项参考回归案例，复制至同一资源目录。

两个 JSON 的 schema 版本均为 1.0；安装包通过 setuptools package-data 包含 `resources/rules/*.json`。

这些文件是规则资料及参考案例。资源可读取、案例被收录或查询接口可用，均不代表原生决斗引擎测试已经执行或通过。

未知表示证据不足、仍待核实；推论表示根据已有资料整理得到的结论，其证据等级应继续明确标注。不能把未知补成确定裁定，也不能把推论升格为官方确认规则。4 项未决问题应保留其未决性质。
