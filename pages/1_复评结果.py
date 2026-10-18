"""浏览冻结评估的真实历史输出；本页面不导入或调用任何推理入口。"""
import json
import streamlit as st
from garbage_vision.config import ROOT, rules, weight_hash
from garbage_vision.images import decode_image
from garbage_vision.exports import annotate, export_json
from garbage_vision.schema import InferenceResult

st.set_page_config(page_title='40图复评 · 识废', page_icon='♻', layout='wide')
st.title('40 张图，逐张看结果')
st.caption('同一组原图 · 原参考标签不变 · 包括通信失败与分类分歧')
st.info('这里显示已保存的真实评估记录。本页不运行模型、不发送图片、不产生 API 费用。')
folder = ROOT/'evidence/v0.5.0/astra-holdout'
report_path = folder/'comparison.json'
if not report_path.exists():
    report_path = folder/'partial-comparison.json'
if not report_path.exists():
    st.warning('本轮复评报告尚未完成。')
    st.stop()
report = json.loads(report_path.read_text(encoding='utf-8'))
frozen = json.loads((folder/'freeze.json').read_text(encoding='utf-8'))
local_records = json.loads((ROOT/frozen['local_prediction_file']).read_text(encoding='utf-8'))['records']
local = {r['id']:r['result'] for r in local_records}
names = rules()['categories']
cats = lambda values: '、'.join(names[x] for x in sorted(values)) or '无确定类别'
a, b = report['local'], report['api']
count = report['attempted_calls']
if not report['complete']:
    st.warning(f'复评中断：已尝试 {count}/40 张，剩余 {40-count} 张尚未请求。下列数值仅描述已尝试子集，不能代表完整正确率。')
c1, c2, c3 = st.columns(3)
scope = '同组' if report['complete'] else '同子集'
c1.metric(scope+'本地集合完全匹配', f"{round(a['exact_set_accuracy']*count)} / {count}")
c2.metric(scope+'大模型集合完全匹配', f"{round(b['exact_set_accuracy']*count)} / {count}")
c3.metric('大模型通信失败', f"{round(b['failure_rate']*count)} / {count}")
st.caption('匹配的是图片中出现的四分类集合，不代表每个物品、理由和位置均正确。参考标签还需要独立人工复核。')
audit_path = folder/'quality-review.json'
audit = json.loads(audit_path.read_text(encoding='utf-8')) if audit_path.exists() else {}
if audit:
    st.info('已增加逐图质量复核：5张分类分歧涉及参考遗漏或规则歧义。原评分不改，也不据此宣称模型全部正确。')
failures = {r['id'] for method in ('local','api') for r in report[method]['records'] if not r['exact_match']}
only_differences = st.checkbox('只看任一方案与参考不一致的图片')
rows = [r for r in frozen['images'] if r['id'] not in report['pending_image_ids'] and (not only_differences or r['id'] in failures)]
by_id = {r['id']:r for r in rows}
key = st.selectbox('复评图片', list(by_id),
    format_func=lambda value: f"{value} · {by_id[value]['title'].removeprefix('File:')}")
row = by_id[key]
path = ROOT/row['path']
if not path.exists():
    st.error('本机缺少这张原图；请按数据清单下载后查看。')
    st.stop()
if weight_hash(path) != row['sha256']:
    st.error('原图与冻结记录不一致，停止显示，避免错配。')
    st.stop()
source = decode_image(path.read_bytes())
st.image(source.image, caption='评估原图', width=650)
st.markdown(f"[原图与许可来源]({row['source_page']}) · {row['author']} · {row['license']}")
st.write('固定参考类别：'+cats(row['categories']))
for note in audit.get('issues',[]) + audit.get('additional_observations',[]):
    if note['id'] == key:
        st.warning('质量复核（不改变原评分）：'+note['note'])
api = json.loads((folder/'api'/(key+'.json')).read_text(encoding='utf-8'))['result']
results = []
# 一次创建两列，避免重复生成空列。
left, right = st.columns(2)
for record, column, title in [(local[key], left, '本地视觉模型'), (api, right, '多模态大模型')]:
    result = InferenceResult.model_validate(record)
    if result.image_id != source.image_id or result.source_sha256 != source.source_sha256:
        st.error('历史结果与原图标识不一致。')
        st.stop()
    results.append(result.model_copy(update={'metadata':{**result.metadata,'display_mode':'saved_holdout_result'}}))
    with column:
        st.subheader(title)
        st.caption(f'{result.model} · 原调用时间（UTC）：{result.created_at_utc}')
        if result.status != 'success':
            st.error(result.error)
            st.caption('该次没有收到识别内容，计为运行失败；没有自动重试。')
            continue
        st.write('输出类别：'+cats(result.categories))
        if result.method == 'local':
            st.image(annotate(source,result), caption='历史定位；整图分类项无框', width='stretch')
        if result.items:
            st.dataframe([{'物品':i.name,'四分类':names.get(i.category,'无法确定'),'理由 / 不确定项':i.reason}
                          for i in result.items],hide_index=True,width='stretch')
        else:
            st.info('模型返回空清单。')
st.download_button('下载本图历史双侧 JSON',export_json(results),file_name=key+'-holdout.json',mime='application/json')
with st.expander('完整指标、费用与全部失败案例'):
    st.markdown((folder/('同图复评报告.md' if report['complete'] else '复评中断进度.md')).read_text(encoding='utf-8'))
