# OpenAI 接入与小样验证

2026-10-18：按用户要求，首选可配置的 `gpt-6-astra`。Responses API 适配、原图输入、严格 JSON Schema、用量记录和失败处理已实现；尚无 OpenAI 密钥，尚未验证账户访问权限或完成真实生成。不能声称 Astra 的效果已经优于百炼。

## 需要你做：在本地填写自己的 OpenAI API 密钥

原因：聊天中的模型权限不能作为项目的 API 凭据。OpenAI API 独立计费，百炼免费额度不通用；官方模型页列明 Free 层不支持此模型。是否有可用余额和模型权限取决于你的 API 账户。

1. 打开 https://platform.openai.com/api-keys ，使用自己的 OpenAI API 平台账号登录。没有 API 账号时先完成平台要求的本人开通步骤；若账户显示所在地区不可用或无访问权限，告诉助手页面提示，不使用第三方转发或绕过限制。
2. 在你的项目下创建 Secret key（若项目限制了模型或接口权限，需要允许 `gpt-6-astra` 和 Responses）。不要把密钥发到聊天。
3. 双击 `C:/Users/Cipher/Documents/Codex/2026-10-17/zhe-2/outputs/garbage-vision/配置API.cmd`，在打开的本地文件末尾找到 `OPENAI_API_KEY=`，把密钥粘到等号后，保存并关闭。
4. 保持 `OPENAI_API_ENABLED=false`；这时网页不会调用 OpenAI。其他字段已经准备好：`GV_API_PROVIDER=openai`、`OPENAI_MODEL=gpt-6-astra`。不要覆盖原有 `GV_API_KEY`，那是百炼密钥。
5. 回复“OpenAI 本地已配置”。助手先做不提交图片的模型权限查询，再在明确预算授权范围内试调用。

如果没有 OpenAI API 账户，先回复“没有 API 账户”，助手再按你实际页面指导。无需在尚未确认模型权限和预算前直接充值大额余额。

## 已授权的小样计划

四张公开开发图片依次为：用户反馈的荧光灯 `commons-701056`、塑料瓶 `commons-179028310`、厨余 `commons-136457085`、烟头 `commons-79335127`。先单独验证荧光灯，检查用量和输出，再继续其余三张；失败就停。总计最多 4 次，无自动重试。后续 40 图评估另行确定，不在本计划内。

请求发送同一张经过方向校正、无裁剪的完整 RGB 图片；`detail=high` 控制服务端图像处理预算。图片上不画本地框，不附本地结果或参考答案。只输出物品名、四分类、简短依据和不确定项，不请求坐标或虚构置信度。`reasoning.effort=low`，`max_output_tokens=2048`（包含推理 token），`store=false`。

用户已授权预算：**合计 1.00 美元，最多4次**。这是新的 OpenAI 预算，不能挪用先前的百炼 1.50 元授权。

已核实标准价格为输入 $10/百万 token、输出 $50/百万 token；缓存写入另按输入的 1.25 倍。脚本按文本 UTF-8 字节数、最多 3,001 图像输入 token、全部 2,048 输出 token 和缓存写入溢价保守预留 **每图 $0.2185625，四图 $0.87425**。不是实际账单或固定套餐价；税费/汇率另计，返回用量会保存。未完成/用量不明的请求停止后续调用，防止无意重复付费。

助手使用的命令（用户无需手工执行）：

```powershell
.venv\Scripts\python.exe scripts/openai_trial.py plan
.venv\Scripts\python.exe scripts/openai_trial.py check
# 以下命令的4次/1美元预算已获同意；本地密钥配置完成后由助手执行。
.venv\Scripts\python.exe scripts/openai_trial.py trial --max-calls 1 --budget-usd 1.00 --confirm-paid-api
# 首张成功、费用正常且结果经检查后，继续原来的四图计划；不会重复第一张。
.venv\Scripts\python.exe scripts/openai_trial.py trial --max-calls 4 --budget-usd 1.00 --confirm-paid-api
```

模型查询成功只说明账户能看到该模型，真实生成仍需验证。若出现鉴权、模型不可用、余额不足、预算不足或输出被截断，保留记录、解释原因并讨论后续；不会静默改成其他模型。模型名称仍可在 `OPENAI_MODEL` 修改，但当前小样预算工具仅对已核实的 `gpt-6-astra` 开放。

## 官方资料

- 模型、图片输入、结构化输出、价格和账户层级：https://developers.openai.com/api/docs/models/gpt-6-astra
- Responses 迁移参数：https://developers.openai.com/api/docs/guides/latest-model/gpt-6-astra.md
- 结构化输出：https://developers.openai.com/api/docs/guides/structured-outputs
- 图片输入与 token 计算：https://developers.openai.com/api/docs/guides/images-vision

联网仅使用既有合法网络配置。OpenAI 默认不继承环境代理；有正常可用的环境代理且确实需要时，可设 `OPENAI_USE_ENV_PROXY=true`，不在请求失败后自动切网重发。
