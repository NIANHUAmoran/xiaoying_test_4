# 实际生成、检查结果、失败与限制

环境为 Windows / Python 3.12.3。通过 `python tests/reproduce.py` 实际执行 11 个离线 CLI 场景，检查退出码及状态并运行全部测试：**38 项通过，0 失败、0 错误**。报告见 [test-results.txt](../examples/test-results.txt)、[offline-validation.json](../examples/offline-validation.json) 和 [run-summary.json](../examples/run-summary.json)。

目录及材料核查结果见 [submission-check.json](../examples/submission-check.json)。核查脚本逐步重算实际记录中的估时和规则检查，核对当时已检索的素材、每稿 revision、逐景及总时长和最后导出，不仅检查文件是否存在。

## 五项必验：预期与实际

| 场景 | 预期与实际结果 | 输入 | 实际输出 | Trace |
| --- | --- | --- | --- | --- |
| 正常生成 | 目标 45 秒，初稿 20+18=38 秒，来源 P01，双检查通过并导出 | [输入](../examples/normal.input.json) | [输出](../examples/normal.output.json) | [记录](../examples/normal.trace.json) |
| 缺关键信息 | 缺受众和目标时长，needs_information，模型调用 0 次，无稿件 | [输入](../examples/missing-info.input.json) | [输出](../examples/missing-info.output.json) | [记录](../examples/missing-info.trace.json) |
| 无素材 | 两次检索均正常执行但空结果，needs_materials，无臆造事实 | [输入](../examples/no-materials.input.json) | [输出](../examples/no-materials.output.json) | [记录](../examples/no-materials.trace.json) |
| 工具失败 | 注入检索失败，tool_failure，与无素材区分；不导出终稿 | [输入](../examples/tool-failure.input.json) | [输出](../examples/tool-failure.output.json) | [记录](../examples/tool-failure.trace.json) |
| 超时长修正 | 目标 30 秒，首稿 38 秒失败；新稿 14+14=28 秒，重新估时和规则检查通过 | [输入](../examples/over-duration.input.json) | [输出](../examples/over-duration.output.json) | [记录](../examples/over-duration.trace.json) |

五组为显式离线 Mock，证明控制流程、工具和校验，不证明真实模型的独立选择效果。每组包含实际生成稿、每稿检查结果和运行记录，正常、信息/资料不足、工具失败三类最低材料要求均覆盖。

## 规则修改、来源与时长对抗

- [rule-limit.output](../examples/rule-limit.output.json)：品牌最多 1 景，首稿 2 景检查失败；模型删除中性 CTA 景后重估 20 秒并复检，最终通过，旧稿失败仍在历史中。
- [query-rewrite.output](../examples/query-rewrite.output.json)：主题“画面文字能力介绍”首轮空，模型改查“字幕”后生成并检查。
- [changed-material.output](../examples/changed-material.output.json)：素材改为“支持调整字幕样式”后，旁白、字幕和引用同步变化。
- [transient-failure.output](../examples/transient-failure.output.json)：一次检索故障由模型选择重试，成功后旧错误标记 resolved，历史不丢失。
- [too-short.output](../examples/too-short.output.json)：目标 1 秒小于最小分镜 2 秒；尝试修订后仍失败，incomplete，不导出成品。
- [step-limit.output](../examples/step-limit.output.json)：两步后达到上限，保留首稿但 script/title/scenes/source_ids 不作为终稿导出。

单元测试明确尝试“效率提升 80%”藏在旁白、字幕、标题和视觉说明中，或把正确 P01 引用挂到任意额外产品结论上；这些均不通过。还检查未检索来源、假 fact ID、假 quote、跨分镜挂引用、重复分镜 ID、全中性无产品证据、长字幕独立估时、长旁白低报时长、改稿后复用旧检查、跳过检查、反向执行两项检查、布尔秒数和非法动作。

38 项中的两个格式回归验证完整 JSON 围栏可被等义去除，以及任意前后说明和损坏 JSON 不能被自动修复或泄露到错误日志。

## 真实模型实际路径

2026 年 11 月 11 日（Asia/Shanghai）使用用户配置的 qwen3.8-max 运行三条成功路径：

| 场景 | 实际观察与后续动作 | 输出 | Trace |
| --- | --- | --- | --- |
| 正常，5 步 | 检索 P01 → 写两景 → 估时 38 秒 → 规则检查 → 完成；目标 45 秒 | [live-normal](../examples/live-normal.output.json) | [记录](../examples/live-normal.trace.json) |
| 超时修正，7 步 | 首稿 38 秒超目标 8 秒；模型将第二景 18 改为 10 秒，新稿 30 秒，重新估时和规则检查后完成 | [live-over-duration](../examples/live-over-duration.output.json) | [记录](../examples/live-over-duration.trace.json) |
| 改写检索，6 步 | 首轮空 → 改“字幕”查询 → 写稿 → 两项检查 → 完成 38 秒稿；目标 45 秒 | [live-query-rewrite](../examples/live-query-rewrite.output.json) | [记录](../examples/live-query-rewrite.trace.json) |

素材原文、每稿、每景与检查结果已由 [check_live_outputs.py](../tests/check_live_outputs.py) 重新计算核对，见 [live-validation-summary.json](../examples/live-validation-summary.json)。真实超时路径修订后是 **30 秒**，离线参考路径是 **28 秒**，二者均不超过目标；保留各自实际结果，不把真实日志改成预设答案。真实模型放弃首稿时尚未检查首稿品牌规则；历史按实际记录保留，最终稿两项检查均完整且绑定 revision 2。

### 保留的格式失败

首次超时路径在第 4 轮出现 JSONDecodeError，此前已写首稿并获得 38 秒超长结果。系统返回 incomplete/model_error，保留草稿和检查，没有导出脚本。原始 [失败输出](../examples/live-format-failure.output.json)、[输入](../examples/live-format-failure.input.json) 与 [Trace](../examples/live-format-failure.trace.json) 均归档，不追加当时未记录的格式字段或规则检查。

随后增加完整外层 Markdown JSON 围栏兼容和仅含行列位置的错误诊断，不进行任意语法修复；重跑通过。因为首次原始响应正文未保存，无法确认具体是哪种格式问题，不能声称围栏兼容已被证明是那次失败的直接修复原因。三次成功样例之外仍存在失败证据，不声称模型输出总是可靠。

## 已知局限与未完成事项

- 素材、事实、品牌规则是受控合成数据；表达必须来自精确事实或预批准中性短句，标题和视觉选项固定。真实自然语言等价改写可能被拒绝，不能据此宣称通用事实蕴含或任意创意质量已解决。
- 受众、平台、风格会传给模型，但没有完整平台专属政策、创意评价或广泛风格库；当前素材主题也很有限。可信表达库和素材需要维护者审阅。
- 文字速度与停留秒数只给出启发式预计时长，未生成视频，也没有真实 TTS、字幕阅读、停顿、音乐或剪辑测量。
- 首稿 20/18 秒是演示的编辑起点，真实模型仍须依据实际检查修订；不把这个起点说成优化结果。
- 已验证三条成功真实路径并保留一次格式失败，没有大样本质量、成功率、调用成本或延迟统计，也未对每种业务故障都运行真实模型。
- 每次调用超时 30 秒，默认最多 20 动作，未提供整任务墙钟超时。模型 JSON 损坏、服务错误或协议不符时明确返回未完成。
- 状态只保留于单次运行和导出 JSON，不提供跨进程续跑、成片渲染、外部发布或生产级执行环境。
- GitHub URL、最终 commit SHA 与私有仓库评审权限待最终提交时填写，当前尚未远程发布。
