# 验证材料索引

每个场景提供 `.input.json`、`.output.json`、`.trace.json`。输出为实际程序运行结果；独立 Trace 逐项提取原输出，不补造模型动作。mode=mock 为离线策略，mode=live 为真实模型，mode=validation 为输入校验。revisions 保留实际生成稿及其实际检查结果。

## 五项必验

| 场景 | 输入 | 实际输出 | 运行记录 | 语料 |
| --- | --- | --- | --- | --- |
| 正常生成 | [normal.input](normal.input.json) | [normal.output](normal.output.json) | [normal.trace](normal.trace.json) | world |
| 缺关键信息 | [missing-info.input](missing-info.input.json) | [missing-info.output](missing-info.output.json) | [missing-info.trace](missing-info.trace.json) | world |
| 无素材 | [no-materials.input](no-materials.input.json) | [no-materials.output](no-materials.output.json) | [no-materials.trace](no-materials.trace.json) | no-materials.world |
| 工具失败 | [tool-failure.input](tool-failure.input.json) | [tool-failure.output](tool-failure.output.json) | [tool-failure.trace](tool-failure.trace.json) | tool-failure.world |
| 超时长修正 | [over-duration.input](over-duration.input.json) | [over-duration.output](over-duration.output.json) | [over-duration.trace](over-duration.trace.json) | world |

语料在 [data](../data) 下按名称加 `.json` 读取。上述覆盖正常、资料不足、工具失败最低材料要求，并补齐本题必验点；离线结果不能代替真实模型效果。

## 扩展场景

`too-short` 明确返回无法满足当前时长；`rule-limit` 记录品牌最多一景的规则失败、删除 CTA 分镜和新版双重复检；`query-rewrite` 首轮无匹配后改“字幕”查询；`transient-failure` 保留故障与恢复记录；`changed-material` 随素材改为“支持调整字幕样式”；`step-limit` 保留未完成稿但不导出成品。每个扩展也有同名三件材料。

## 真实模型与失败归档

| 场景 | 输入 | 实际输出 | 运行记录 |
| --- | --- | --- | --- |
| 正常 38 秒脚本 | [live-normal.input](live-normal.input.json) | [live-normal.output](live-normal.output.json) | [live-normal.trace](live-normal.trace.json) |
| 38→30 秒并复检 | [live-over-duration.input](live-over-duration.input.json) | [live-over-duration.output](live-over-duration.output.json) | [live-over-duration.trace](live-over-duration.trace.json) |
| 空结果后改写检索 | [live-query-rewrite.input](live-query-rewrite.input.json) | [live-query-rewrite.output](live-query-rewrite.output.json) | [live-query-rewrite.trace](live-query-rewrite.trace.json) |
| 初次 JSON 格式失败 | [live-format-failure.input](live-format-failure.input.json) | [live-format-failure.output](live-format-failure.output.json) | [live-format-failure.trace](live-format-failure.trace.json) |

三条成功真实模型路径来自 qwen3.8-max，分别为 5、7、6 步；历史失败为 4 步后 JSONDecodeError，未导出可用脚本。成功核对见 [live-validation-summary.json](live-validation-summary.json)。初次失败原文响应未保存，不推断其具体格式原因；后续实现兼容完整外层 JSON 围栏，任意损坏语法仍会报未完成。

## 复现与报告

在项目根目录执行 `python tests/reproduce.py` 复现 11 个离线场景、生成各稿及检查记录并运行 38 项测试；执行 `python tests/check_submission.py` 核查 15 组三件材料、逐景时长、事实引用、版本检查与目录/文档链接。

报告：[test-results.txt](test-results.txt)、[offline-validation.json](offline-validation.json)、[run-summary.json](run-summary.json)、[submission-check.json](submission-check.json)、[delivery-status.json](delivery-status.json)。预期、实际行为与局限见 [评估文档](../docs/03-evaluation.md)。
