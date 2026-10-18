# NexaVLinks / GPT-6 Astra 当前接入

当前服务商为用户提供的NexaVLinks，模型名保留可配置，默认 `gpt-6-astra`。已用该账户密钥验证模型列表，并完成4张公开开发图的真实图片调用。不是直接调用OpenAI官方账号；不能仅凭第三方返回模型名独立证明其上游实现。

## 已验证的配置

- `GV_API_PROVIDER=nexavlinks`
- `NEXAVLINKS_API_KEY=`：用户已有密钥，已从误填的OPENAI_API_KEY移动到独立字段。不要再次在聊天粘贴配置文件。
- `NEXAVLINKS_MODEL=gpt-6-astra`
- 接口固定为 `https://www.nexavlinks.com/v1/chat/completions`，模型目录确认支持image输入。
- 请求为完整方向校正RGB图片、版本化分类规则和严格JSON Schema。输出限制2048 token、low推理强度、关闭自动重试。
- `NEXAVLINKS_PROXY_URL` 仅本地配置为已存在且验证可用的代理；不自动切换网络重发。
- `NEXAVLINKS_API_ENABLED=false`：当前网页不发起新收费请求，已授权的小样由脚本完成。

密钥、环境和原始图片不进入Git。最初官方地址返回401，是因为用户持有第三方平台密钥；没有产生图片生成请求。第三方模型列表返回200且包含gpt-6-astra。

## 小样结果和费用

4次均成功返回；荧光灯、厨余、烟蒂与参考一致。塑料瓶输出额外烟蒂，原图瓶内可见疑似烟蒂，需要独立复核参考标签，未改原标注。按原参考3/4集合一致，平均F1 0.9167；开发图小样不是独立测试成绩。

用户授权4次/1 NEX已全部使用（剩余资金不等于剩余调用次数）。实际站内日志扣款共 **0.1042992 NEX**，所有请求均走“[自建] ASTRA专属分组”，见[小样报告](../evidence/v0.5.0/nexavlinks-trial/小样验证报告.md)。NEX不能直接等同美元或人民币。

已核实Astra专属分组每百万token输入3.6、输出18、缓存写入4.5、缓存读取0.36 NEX；同一密钥可见订阅组价格为10/50/12.5/1，程序按更高费率预留/核算并用站内日志确认实际金额。

## 不收费查看四张真实结果

打开 http://127.0.0.1:8501 ，展开“使用开发样例”，选择 Spiral fluorescent lamp.jpg 或另三张试验图片，点击“开始识别”运行本地，再点“查看本图已保存的大模型实测（不收费）”。右侧显示保存的真实API输出及原调用时间，可导出JSON。换图会清空旧结果。

## 固定40图复评计划（待新预算授权）

已固定的quality_test.json为40张新图，其中32张有确定类别、8张背景/未知。本地旧/新配置已全量推理，新配置33/40集合一致。拟新增最多40次Astra请求、合计4 NEX；按小样当前费率粗估约1.1 NEX，较高分组用量估算约3.6 NEX，较复杂图和较长输出会增加费用。

每次发送前预留约0.219 NEX，累计按保守价格检查预算。无法安全预留下一次时会停，不保证4 NEX能覆盖任何输出长度下的全部40图；需补预算时先报告已发生记录，不能自行超额。失败/用量不明/中断标记均停止后续调用，不自动重试。模型、提示词、原图和参考标签冻结后不据测试结果调整。

入口 `scripts/evaluate_nexavlinks.py prepare` 只冻结，不请求模型；`run --budget-nex 4 --confirm-paid-api` 只能在用户批准新增40次后执行。结果完整后才评分，与已归档本地同图结果比较。网页付费开关继续关闭。

资料：https://www.nexavlinks.com/doc/endpoints-and-capabilities ；https://www.nexavlinks.com/modelsmarket/gpt-6-astra ；https://www.nexavlinks.com/doc/billing-balance-issues 。
