"""离线重算同图40样本：保留失败、区分端到端与成功响应指标，不调用API。"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from garbage_vision.config import ROOT, rules, weight_hash
from garbage_vision.evaluation import score_records
from garbage_vision.experiment import text_hash

DIRECTORY = ROOT/'evidence/v0.5.0/astra-holdout'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def metrics(rows, records):
    score = score_records(rows, records)
    known = [r for r in rows if r['categories']]
    by_id = {r['id']: r for r in records}
    score['known_only'] = score_records(known, [by_id[r['id']] for r in known])
    score['unknown_false_positive_images'] = sum(
        r['result']['status'] == 'success' and any(x['category'] for x in r['result']['items'])
        for r in records if not r['expected_categories'])
    return score


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--partial', action='store_true', help='明确生成未完成报告，不冒充完整40图成绩')
    args = parser.parse_args()
    frozen = read(DIRECTORY/'freeze.json')
    planned = frozen['images']
    assert len(planned) == 40
    missing = [r['id'] for r in planned if not (DIRECTORY/'api'/(r['id']+'.json')).exists()]
    if missing and not args.partial:
        raise ValueError('Incomplete evaluation; use --partial and disclose missing images.')
    rows = [r for r in planned if r['id'] not in missing]
    count = len(rows)
    known_count = sum(bool(r['categories']) for r in rows)
    unknown_count = count-known_count
    prefix = 'partial-' if missing else ''
    assert weight_hash(ROOT/frozen['local_prediction_file']) == frozen['local_predictions_sha256']
    api = [read(DIRECTORY/'api'/(r['id']+'.json')) for r in rows]
    local = [r for r in read(ROOT/frozen['local_prediction_file'])['records'] if r['id'] not in missing]
    for path in ('prompts/classify_v2.txt','config/categories.json'):
        assert text_hash(ROOT/path) == frozen['sources'][path]
    prompt_digest = hashlib.sha256(((ROOT/'prompts/classify_v2.txt').read_text(encoding='utf-8')+json.dumps(rules(),ensure_ascii=False)).encode('utf-8')).hexdigest()
    for row, record in zip(rows, api):
        result = record['result']
        assert result['image_id'] == row['image_id'] and result['source_sha256'] == row['sha256']
        assert result['model'] == 'gpt-6-astra' and result['metadata']['provider'] == 'nexavlinks'
        assert result['metadata']['attempts'] == 1
        assert result['metadata']['prompt_sha256'] == prompt_digest
    a, b = metrics(rows, local), metrics(rows, api)
    successful = {r['id'] for r in api if r['result']['status'] == 'success'}
    valid_rows = [r for r in rows if r['id'] in successful]
    paired = {name: score_records(valid_rows, [r for r in records if r['id'] in successful])
              for name, records in [('local', local), ('api', api)]} if valid_rows else {}
    billing = read(DIRECTORY/'billing-review.json') if (DIRECTORY/'billing-review.json').exists() else None
    observed_estimate = sum(r['estimated_cost_nex'] or 0 for r in api)
    missing_usage = [r['id'] for r in api if r['estimated_cost_nex'] is None]
    reviews = read(DIRECTORY/'interruption-review.json')['reviewed_failures']
    budget_accounted = observed_estimate + sum(read(DIRECTORY/'api'/(key+'.started.json'))['reserved_nex'] for key in missing_usage)
    data = {'provider':'nexavlinks', 'model':'gpt-6-astra', 'api_source_commit':frozen['git_commit'],
        'local_source_commit':frozen['local_freeze_commit'], 'local':a, 'api':b,
        'same_successful_subset_diagnostic_only':paired, 'authorized_max_calls':40, 'attempted_calls':len(api),
        'authorized_budget_nex':4, 'returned_usage_estimated_nex':observed_estimate,
        'records_without_returned_usage':missing_usage, 'conservative_budget_accounted_nex':budget_accounted,
        'billing':billing, 'reference_labels_changed':False}
    data['api_source_commits']=sorted({read(DIRECTORY/'api'/(r['id']+'.started.json')).get('inference_source_commit',frozen['git_commit']) for r in rows})
    data.update(complete=not missing, pending_image_ids=missing, planned_images=40)
    (DIRECTORY/(prefix+'comparison.json')).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    (DIRECTORY/('api/'+prefix+'predictions.json')).write_text(json.dumps({'records':api,'api_config':frozen['api_config'],
        'returned_usage_estimated_nex':observed_estimate,'records_without_returned_usage':missing_usage}, ensure_ascii=False, indent=2),encoding='utf-8')
    (DIRECTORY/('api/'+prefix+'scores.json')).write_text(json.dumps(b,ensure_ascii=False,indent=2),encoding='utf-8')
    names = rules()['categories']
    cats = lambda values: '、'.join(names[c] for c in sorted(values)) or '无确定类别'
    exact = lambda s: round(s['exact_set_accuracy']*s['images'])
    lines = ['# NexaVLinks / gpt-6-astra 同图40样本复评'+('（尚未完成）' if missing else ''), '',
        f'计划40图，已尝试{count}图，未请求{len(missing)}图。'+('以下只是已尝试子集的进度统计，不是完整测试正确率；尚未覆盖全部类别及背景图。' if missing else '全部40图已覆盖。'), '',
        '比较升级后的本地 SAM2 + CLIP 与第三方 NexaVLinks 返回的 gpt-6-astra。所有已尝试记录保留，失败计零，未按结果更换图片、修改参考标签或调参。第三方模型名不能独立证明其上游实现。', '',
        '| 指标 | 升级后的本地模型 | NexaVLinks / gpt-6-astra |', '|---|---:|---:|',
        f"| 已尝试{count}图类别集合完全正确 | {exact(a)}/{count}（{a['exact_set_accuracy']:.1%}） | {exact(b)}/{count}（{b['exact_set_accuracy']:.1%}） |",
        f"| {known_count}张非空参考图平均F1 | {a['known_only']['mean_per_image_f1']:.4f} | {b['known_only']['mean_per_image_f1']:.4f} |",
        f"| 已尝试{count}图平均F1 | {a['mean_per_image_f1']:.4f} | {b['mean_per_image_f1']:.4f} |",
        f"| 已尝试背景/未知图的误报图片 | {str(a['unknown_false_positive_images'])+'/'+str(unknown_count) if unknown_count else '尚未测试'} | {str(b['unknown_false_positive_images'])+'/'+str(unknown_count) if unknown_count else '尚未测试'} |",
        f"| 运行失败 | {round(a['failure_rate']*count)}/{count} | {round(b['failure_rate']*count)}/{count} |", '',
        '“完全正确”只衡量图片中出现的四分类集合，不代表每个物品名、数量、理由和定位均正确。双方空集合且运行成功时F1为1，故同时给出非空参考图指标。没有实例框真值，不报告mAP。', '',
        '## 分类表现', '', '| 类别 | 参考出现图片数 | 本地精确率 / 召回率 / F1 | 大模型精确率 / 召回率 / F1 |', '|---|---:|---|---|']
    for key in names:
        x, y = a['per_category'][key], b['per_category'][key]
        lines.append(f"| {names[key]} | {x['support_images']} | {x['precision']:.3f} / {x['recall']:.3f} / {x['f1']:.3f} | {y['precision']:.3f} / {y['recall']:.3f} / {y['f1']:.3f} |")
    if paired:
        x, y = paired['local'], paired['api']
        lines += ['', f"仅为诊断，取大模型成功返回的同一{len(successful)}图子集：本地完全匹配{exact(x)}/{x['images']}，大模型{exact(y)}/{y['images']}。这个子集不能取代完整40图端到端评估。"]
    lines += ['', '## 通信失败与费用', '',
        '首图 commons-128095601 在约48秒后出现本地通信错误，没有收到识别内容或token用量；平台对应时间存在 Chat Completions / low 账单，扣款0.009252 NEX（输入2380、输出38 token）。依据时间、模型、端点和推理强度匹配，没有可核对的本地响应ID。不能恢复其识别结果，也不能把它记为模型答错或答对。', '',
        '首轮已停止。只读连接恢复并人工核对账单后，单独的续评入口跳过首张失败图，继续未发送图片；第17张在1.34秒后通信失败。用户明确授权保留失败和未知费用预留、改直连后，第18张在124.36秒后超时，已再次停止。失败均占一次额度，预算上分别保留原0.218625 NEX完整预留。没有自动重试或重发。所有原始结果和开始标记保留；具体底层错误未在旧版记录，不能凭结果断定某条线路或服务商的根因。', '',
        f'授权40次、4 NEX；共启动{len(api)}次，收到有效结构结果{len(successful)}次。返回用量按较高分组费率估算{observed_estimate:.6f} NEX；对所有用量未知请求保留完整预留后的保守预算占用为{budget_accounted:.6f} NEX。此数不是实际账单，也不表示费用未知时可继续运行。']
    if billing:
        lines.append(f"站内日志目前核对本批{len(billing['rows'])}条，已确认扣款合计 **{billing['actual_total_nex']:.8f} NEX**；四图开发小样另计0.1042992 NEX。NEX为站内额度，不等同美元或人民币。")
        if billing.get('unreconciled_image_ids'):
            lines.append('尚未查到对应账单、不能认定零费用的请求：'+', '.join(billing['unreconciled_image_ids'])+'。该错误发生后已停止，不能把账单缺失当作免费重试授权。')
    else:
        lines.append('全批实际账单尚未核对；不可把估算当作实际扣费。')
    lines += ['', '## 大模型所有分歧与失败', '', '| 图片 | 原参考 | 大模型输出 | 状态 / 解释 |', '|---|---|---|---|']
    by_api = {r['id']:r for r in api}
    for row in b['records']:
        if row['exact_match']:
            continue
        result = by_api[row['id']]['result']
        reason = result['error'] if result['status'] != 'success' else '；'.join(i['name']+'：'+i['reason'] for i in result['items']) or '返回空清单'
        lines.append(f"| {row['id']} | {cats(row['truth'])} | {cats(row['predicted'])} | {reason.replace('|','／').replace(chr(10),' ')} |")
    lines += ['', '## 全40图对照', '', '| 图片 | 参考 | 本地 | 大模型 | 本地 / 大模型完全匹配 |', '|---|---|---|---|---|']
    by_a = {r['id']:r for r in a['records']}
    for row in b['records']:
        x = by_a[row['id']]
        lines.append(f"| {row['id']} | {cats(row['truth'])} | {cats(x['predicted'])} | {cats(row['predicted']) if row['status']=='success' else '通信失败'} | {'是' if x['exact_match'] else '否'} / {'是' if row['exact_match'] else '否'} |")
    for row in planned:
        if row['id'] in missing:
            lines.append(f"| {row['id']} | {cats(row['categories'])} | 已有归档，未纳入当前子集统计 | 尚未请求 | — |")
    lines += ['', '## 证据与限制', '',
        f"- API推理源码："+'、'.join('`'+c+'`' for c in data['api_source_commits'])+f"；本地推理冻结源码：`{frozen['local_freeze_commit']}`。阶段冻结文件和开始标记记录各自版本；原图、模型参数、提示词、分类规则不变。",
        '- 同图独立输入：API只接收完整方向校正图片、提示词和固定规则，没有接收本地预测。',
        '- 40图：可回收8、厨余8、其他7、有害8、背景/未知8、混合1。标签来自Commons作者元数据和推理前Codex视觉复核，非独立真人标注；正式成绩保持原参考，疑似标注问题另列，不回改分数。',
        '- 样本规模小、混合和遮挡不足。本地复用了SAM区域缓存，因此其耗时不能与API网络耗时作为端到端性能排名。',
        '- 旧Qwen使用不同测试集，本报告不能证明相对Qwen的同集准确率提升。',
        '- 本报告是实验质量证据，不是实际投放可靠性保证，也不表示视频、个人感悟和考核材料已全部完成。',
        '- 离线重算：`.venv/Scripts/python.exe scripts/report_astra.py'+(' --partial' if missing else '')+'`。不调用模型、不收费。',
        '- 中断后另行实现无损上传候选和更细的网络错误诊断。18条原始记录没有使用新候选；精确继续原基线应检出冻结源码，不可绕过校验。', '']
    (DIRECTORY/('复评中断进度.md' if missing else '同图复评报告.md')).write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps({'local_exact':exact(a),'api_exact':exact(b),'api_success':len(successful),'budget_accounted_nex':budget_accounted},ensure_ascii=False))


if __name__ == '__main__':
    main()
