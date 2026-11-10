# 第 4 题：短视频脚本 Agent

根据主题、受众、平台、时长和风格，利用产品事实及品牌规则生成可编辑脚本。输出标题、分镜、旁白/字幕、逐景及总预计时长、素材来源、风险和状态。每次改稿后重新检查，只有当前稿时长和规则都通过，才导出终稿。

本目录为独立项目根目录。若位于外层工作区，请先执行 `cd .\xiaoying_test_4`；下文命令均从本目录运行，上传 GitHub 时以本目录内容作为仓库根目录。代码不依赖其他题目录。

已完成 **38 项测试、11 个离线场景及三条真实模型路径**。离线参考路径验证 38→28 秒；真实模型观察 38 秒超时后选择 38→30 秒，重新估时并通过规则检查。一次真实模型格式失败也原样保留，详见 [评估文档](docs/03-evaluation.md)。

## 项目目录

```text
xiaoying_test_4/
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── src/                          # 生成动作、模型接入、素材/估时/规则工具、CLI
├── tests/                        # 可执行测试、复现及交付核查脚本
├── examples/                     # 成组输入、实际输出、Trace、测试报告
│   ├── README.md
│   ├── normal.input.json
│   ├── normal.output.json
│   ├── normal.trace.json
│   ├── missing-info.*.json
│   ├── no-materials.*.json
│   ├── tool-failure.*.json
│   ├── over-duration.*.json
│   ├── live-*.{input,output,trace}.json
│   └── test-results.txt
├── data/                         # 合成产品事实、品牌规则、估时参数与故障配置
└── docs/
    ├── 01-requirements.md        # 用户、目标、范围、成功标准
    ├── 02-solution.md            # 调用流程、动态决策、技术取舍
    ├── 03-evaluation.md          # 预期、实际结果、失败与限制
    ├── 04-ai-usage.md            # AI 辅助、个人贡献及验证
    └── 05-retrospective.md       # 难点、学习收获、下一步
```

## 环境、安装与离线复现

要求 Python 3.12+，已在 Windows / Python 3.12.3 验证。全部使用标准库，无须安装第三方依赖，声明见 requirements.txt。无需模型配置即可运行：

```powershell
python --version
python tests/reproduce.py
python tests/check_submission.py
```

复现脚本实际调用 CLI，核对退出码和关键结果，生成离线输出、独立 Trace 并运行测试；不会调用真实模型或覆盖归档的真实模型输出。交付核查逐步重算记录中的检查，验证实际来源、分镜时长、修订与检查绑定、五份文档和材料链接，结果见 [submission-check.json](examples/submission-check.json)。

单独执行生成或测试：

```powershell
python -B -m src --mock --input examples/normal.input.json --output .runtime/normal.output.json
python -B -m src --mock --input examples/over-duration.input.json
python -B -m unittest discover -s tests -v
```

## 输入与脚本结构

```json
{
  "request_id": "video-001",
  "theme": "字幕介绍",
  "audience": "新手创作者",
  "platform": "短视频",
  "target_seconds": 30,
  "style": "简洁"
}
```

除可选 request_id 外，其余字段必填。target_seconds 是 1..600 的整数上限，不接受布尔值；其余项是非空字符串。缺字段/null/空字符串返回 needs_information；非法类型、纯空白或超范围输入以退出码 2 拒绝。未提供 request_id 时根据输入生成记录标识，不提供跨进程任务恢复。

每景含 id、visual、narration、subtitle、duration_seconds、source_refs，引用包含 material_id、fact_id、quote。最终导出额外给出每景 estimated_seconds 和脚本 estimated_total_seconds、revision，便于编辑及复核。

P01 仅提供“支持字幕”，没有效率数据。旁白和字幕每句须等于本景引用的事实，或品牌允许的中性短句；标题与画面说明来自预批准选项。合法 P01 引用不能支持“效率提升 80%”等额外结论，也不能跨景代替引用。至少有一个实际使用的产品事实，全中性口号不算完成产品介绍。

**这是受控表达范围内的脚本生成，不是通用自由创作或自然语言事实蕴含检测。** 源事实、标题、画面和中性短句均在 data 中可审阅，扩大创作范围需要同时扩展校验。受众、平台和风格提供给模型，但当前没有完整平台专属规则或创意质量评估。

## 时长、改稿与终稿

每景预计秒数为指定停留秒数、旁白字数估时、字幕字数估时、最小 2 秒的最大值，再求和。默认每秒 5 个有效字符，忽略空白和标点；不把相同旁白和字幕重复累加。长字幕或长旁白不能靠填 1 秒规避检查。这是启发式估算，不是实际配音或视频成片测量。

每次 write_script 创建新 revision，并清空两项当前检查。终稿只能使用同一最新 revision 的 estimate_duration 与 check_rules 通过结果；被放弃的历史稿仅保留实际执行过的检查。未完成时 script/title/scenes/source_ids 不作为成品导出，诊断稿保留在 last_draft/revisions。

| 验收点 | 示例与实际行为 |
| --- | --- |
| 正常生成 | normal：目标 45 秒，首稿估算 38 秒，两项检查通过 |
| 缺关键信息 | missing-info：明确列出受众、目标时长缺失，不调用模型 |
| 无素材 | no-materials：补查后仍为空，请求补充，不虚构产品事实 |
| 工具失败 | tool-failure：检索异常明确结束为 tool_failure，不说成无素材 |
| 超时长修正 | over-duration：目标 30 秒，首稿 38 秒，改为 28 秒并复检 |

成组文件见 [材料索引](examples/README.md)。工具失败单独复现：

```powershell
python -B -m src --mock --input examples/tool-failure.input.json --data data/tool-failure.world.json
```

该负例退出码 1 是预期结果。rule-limit 展示品牌分镜上限触发修改，too-short 展示当前条件下无法满足；changed-material、query-rewrite、transient-failure 和 step-limit 也有实际记录。

## 真实模型配置与运行

参照 [.env.example](.env.example) 在本目录创建 .env，填写 LLM_BASE_URL、LLM_MODEL、LLM_API_KEY，也可用 --env-file 指定本机文件。环境变量优先；支持单行 KEY=VALUE、整行注释及成对引号，不做变量展开和多行解析。交付目录不含真实密钥。

服务需支持 HTTPS、Bearer 认证及 /chat/completions JSON 协议。LLM_BASE_URL 填接口前缀，程序自动追加 /chat/completions；响应读取 choices[0].message.content 的动作 JSON。允许完整外层 Markdown JSON 围栏，不提取任意说明文字或修复损坏 JSON；错误日志只记类型、格式和位置，不保存原始响应正文。

配置好后执行，不加 --mock：

```powershell
python -B -m src --input examples/live-normal.input.json --output examples/live-normal.output.json
python -B -m src --input examples/live-over-duration.input.json --output examples/live-over-duration.output.json
python -B -m src --input examples/live-query-rewrite.input.json --output examples/live-query-rewrite.output.json
python -B tests/check_live_outputs.py
python tests/reproduce.py
```

独立 Trace 从实际输出提取；最后一条离线命令不会再调用模型。真实路径的具体修订时长由模型选择，不保证每次恰好 28 或 30 秒；核查以当前稿通过两项检查且不超过目标为准，历史样例保留其真实结果。

每次请求超时 30 秒，响应大小上限 1 MiB；默认最多 20 次模型动作（--max-steps 可设 1..100）。工具重试由模型选择，不无限自动重试；JSON/协议错误返回 incomplete/model_error，保留已生成稿与实际观察。

退出码：0 为 completed、needs_information 或 needs_materials；1 为 tool_failure 或 incomplete；2 为输入、配置或数据错误。退出码 0 不代表必然获得可用终稿，应同时查看 status。

## 评审入口与提交信息

| 检查项 | 入口 |
| --- | --- |
| 用户、范围与成功标准 | [01-requirements.md](docs/01-requirements.md) |
| 动态决策、事实和估时设计 | [02-solution.md](docs/02-solution.md) |
| 实际生成、检查、失败与局限 | [03-evaluation.md](docs/03-evaluation.md) |
| AI 使用与个人贡献 | [04-ai-usage.md](docs/04-ai-usage.md) |
| 难点、用时、下一步 | [05-retrospective.md](docs/05-retrospective.md) |
| 全部验证材料 | [examples/README.md](examples/README.md) |

题号：4。GitHub URL、最终 commit SHA 与私有仓库评审权限待最终提交时填写，尚未远程发布；本人实际用时、独立修改和亲自验证内容应如实补充。
