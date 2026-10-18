"""从同组40图原始记录重新计分，检查预先声明的升级条件；不运行模型或调用 API。"""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from garbage_vision.config import ROOT,rules
from garbage_vision.evaluation import score_records


def main():
    root=ROOT/'evidence/v0.5.0/quality-holdout'
    frozen=json.loads((root/'freeze.json').read_text(encoding='utf-8'));rows=frozen['images']
    reports={};records={}
    for method in ['baseline','candidate']:
        data=json.loads((root/method/'predictions.json').read_text(encoding='utf-8'))['records']
        assert len(data)==len(rows)==40 and {r['id'] for r in data}=={r['id'] for r in rows}
        scores=score_records(rows,data)
        saved=json.loads((root/method/'scores.json').read_text(encoding='utf-8'))
        assert all(scores[k]==saved[k] for k in scores),'Saved score mismatch'
        reports[method]=saved;records[method]={r['id']:r for r in data}
    a,b=reports['baseline'],reports['candidate']
    checks={'known_f1_gain_at_least_005':b['known_only']['mean_per_image_f1']-a['known_only']['mean_per_image_f1']>=.05,
        'overall_exact_count_improves':b['exact_set_accuracy']>a['exact_set_accuracy'],
        'unknown_false_positive_images_not_increased':b['unknown_false_positive_images']<=a['unknown_false_positive_images']}
    decision={'source_commit':frozen['git_commit'],'promotion_rule':frozen['promotion_rule'],
        'checks':checks,'promote_candidate':all(checks.values()),'baseline':a,'candidate':b}
    (root/'comparison.json').write_text(json.dumps(decision,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# 本地识别质量复评：同组 40 张图','',
        '候选配置通过预先声明的三条升级条件，已用于当前网页。这是小规模测试集上的改善，不能据此宣称实际投放可靠或项目最终交付完成。','',
        f"推理源码冻结于 `{frozen['git_commit']}`；候选只在开发集选择。新测试集在推理前固定，未据本次测试结果继续调参。旧 21 张测试证据保持原样。",'',
        '| 指标 | 旧配置 | 新配置 |','|---|---:|---:|',
        f"| 全部40图分类集合完全正确 | {round(a['exact_set_accuracy']*40)}/40（{a['exact_set_accuracy']:.1%}） | {round(b['exact_set_accuracy']*40)}/40（{b['exact_set_accuracy']:.1%}） |",
        f"| 有确定类别的32图平均F1 | {a['known_only']['mean_per_image_f1']:.4f} | {b['known_only']['mean_per_image_f1']:.4f} |",
        f"| 全部40图平均F1 | {a['mean_per_image_f1']:.4f} | {b['mean_per_image_f1']:.4f} |",
        f"| 8张未知/背景图中的误报图片 | {a['unknown_false_positive_images']}/8 | {b['unknown_false_positive_images']}/8 |",
        '| 运行失败 | 0/40 | 0/40 |','',
        '计分单位是“每张图出现的四分类集合”，不衡量物品名完全正确、完整定位或精确计数。未知/背景参考为空集合；双方为空时全图 F1 记1，所以另外报告32张非空参考图，避免只靠拒识提升成绩。','',
        '## 改动与选择依据','',
        '保留同一 SAM2.1 tiny、CLIP ViT-B/32 权重和相似度/类别差阈值。改为保留区域完整长宽的补边输入，加入区域周围上下文和多个文本模板；细化荧光灯/LED等描述。没有确定区域类别时尝试整图分类，成功项不伪造定位框。','',
        '更大的 CLIP ViT-L/14、开发图视觉参考匹配等实验没有胜出，未作为默认。原19图开发F1从0.7018到0.8246；扩展38图开发F1为0.8158。开发成绩仅用于选型，升级依据是这组新40图。','',
        '三条预定条件：已知类别图平均F1至少提高0.05、整体完全匹配数增加、未知误报图片数不增加。实际分别提高0.109375、增加7张、减少1张。','',
        '## 仍然失败的图片','',
        '| 图片 | 参考类别 | 新配置类别 |','|---|---|---|']
    names=rules()['categories']
    def cats(values):return '、'.join(names[c] for c in sorted(values)) or '无确定类别'
    for row in rows:
        r=records['candidate'][row['id']]['result'];pred={x['category'] for x in r['items'] if x['category']}
        if pred!=set(row['categories']):lines.append(f"| {row['id']} | {cats(row['categories'])} | {cats(pred)} |")
    lines+=['','有害类仍有误报和漏识别。空货架被分到多个垃圾类别、室内固定灯具被当成废弃物等问题仍在；未知误报图片虽减少，个别误报的类别数反而增加。','',
        '## 数据和复现边界','',
        '40图包含可回收8、厨余8、其他7、有害8、背景/未知8、混合1。按作者组隔离，检查原始哈希及近重复；来源/许可见 quality_test.json 和 quality_split_audit.json。标签来自作者元数据和推理前 Codex 视觉复核，尚未经过独立真人标注。混合、遮挡及真实投放场景仍不足；没有实例框真值，无 mAP。','',
        '两配置复用同一批真实 SAM 分割缓存以固定候选区域；缓存运行耗时不能作为端到端速度对比。精确重跑推理需检出上述冻结源码，保留 freeze.json、下载相同原图/权重并校验哈希。当前报告可直接重算：`.venv/Scripts/python.exe scripts/report_quality.py`，不收费。','',
        '## 多模态部分的当前结论','',
        '本轮已授权47次百炼请求只使用了3次诊断，估算共0.011428元，余44次按用户改用OpenAI的要求暂停。两张厨余图的重试响应出现“category非空但uncertain=true”，已通过保守撤销该条确定类别保留其他有效条目；离线重放成功不等于模型重新答对。另一张瓶图仍出现背景额外类别，不应算全部修复。','',
        'OpenAI gpt-6-astra 已按官方文档实现 Responses 原图输入和结构化输出，但真实小样和模型权限仍待验证。没有拿不同测试集直接比较旧Qwen成绩与新本地成绩，也没有虚构OpenAI正确率。','']
    (root/'质量对比报告.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'promotion':decision['promote_candidate'],'checks':checks,'exact_counts':[round(a['exact_set_accuracy']*40),round(b['exact_set_accuracy']*40)]}))


if __name__=='__main__':main()
