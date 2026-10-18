# 当前实现验证

2026-10-18：项目隔离环境运行 `$env:RUN_REAL_LOCAL='1'; .venv/Scripts/python.exe -m pytest tests -q`，结果 **48 passed in 36.07s**。实际执行的是离线协议/边界检查、数据隔离与评分检查，以及真实GPU通过Streamlit AppTest的塑料瓶/换图/坏图流程。

OpenAI协议测试使用明确的MockTransport，不产生真实API请求，不作为模型效果证据。已验证完整图像字节、Responses严格结构、reasoning项不混入答案、拒绝/截断保留用量、不重试、服务商密钥隔离与美元预算。

荧光灯和整图香蕉皮另由 scripts/verify_quality_ui.py 真实运行，见ui-regression。服务健康检查 http://127.0.0.1:8501/_stcore/health 返回200 ok。

本轮本地40图运行没有失败，评分与保存原始逐图记录重算一致；不是拿软件测试数量代替分类正确率。
