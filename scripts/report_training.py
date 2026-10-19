"""由冻结训练、验证和新测试原始记录生成报告，不修改标签或默认模型。"""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/v0.6.0/local-training'
def read(p):return json.loads(p.read_text(encoding='utf-8'))

def main():
    training=read(OUT/'training.json');selection=read(OUT/'selection.json');decision=read(OUT/'decision.json')
    split=read(ROOT/'data/manifests/training_split_audit_v06.json');name=decision['candidate_name']
    baseline=read(OUT/'test/baseline/scores.json');candidate=read(OUT/'test'/name/'scores.json')
    rows={r['id']:r for r in read(ROOT/'data/manifests/training_test_v06.json')}
    before={r['id']:r for r in baseline['records']};after={r['id']:r for r in candidate['records']}
    corrected=[i for i in before if not before[i]['exact_match'] and after[i]['exact_match']]
    regressed=[i for i in before if before[i]['exact_match'] and not after[i]['exact_match']]
    cats={'recyclable':'可回收物','hazardous':'有害垃圾','kitchen':'厨余垃圾','other':'其他垃圾'}
    label=lambda cs:'、'.join(cats[c] for c in cs) or '无确定四分类'
    lines=['# 本轮真实分类层训练与新图测试','',
        ('候选满足预声明条件；是否启用仍以默认配置和集成检查为准。' if decision['promote'] else '**本轮训练已执行，但没有通过升级条件；网页继续保留训练前的默认模型。不能声称整体优化完成。**'),'',
        '按用户要求，本轮结束后先报告并停止，不进入视频、最终交付或考核提交。本轮没有新增收费 API 调用，也没有训练远程多模态模型。','',
        '## 数据与训练事实','',
        f"- 训练 {training['independent_images']} 张（{split['groups']['train']} 个来源/近重复组），验证 {sum(split['counts']['validation'].values())} 张（{split['groups']['validation']} 组），新测试 {baseline['images']} 张（{split['groups']['test']} 组）。",
        '- 历史 61 张测试图及同作者/近重复图排除。作者与近重复分组隔离，测试标签和名单在本轮任何预测之前确定。旧开发图参与训练/验证，未进入新测试。',
        f"- 在 {training['device']} 上实际反向传播更新 {training['trainable_active_parameters']:,} 个有效分类层参数；SAM、CLIP 图像及文本编码器均冻结。",
        f"- 每组训练 {training['parameters']['epochs']} 次全批更新，两个锚定强度、两个混合强度，共四个候选。{training['augmented_views']} 个增强视图仍只来自 {training['independent_images']} 张图，不能算作新增独立样本。",
        '- 完整图片监督只改变类别向量，未训练物品框或分割；没有定位 mAP。20 个标签有监督样本，其中包含背景和未知。药片等缺少训练样本的词向量保持原样。','',
        '| 锚定强度 | 初始交叉熵 | 训练后交叉熵 |', '| --- | ---: | ---: |']
    for anchor,logs in training['histories'].items():lines.append(f"| {anchor} | {logs[0]['cross_entropy']:.4f} | {logs[-1]['cross_entropy']:.4f} |")
    lines+=['','损失是训练集拟合证据，不是未见图正确率。','', '## 验证选择与新测试','',
        f"验证仅按预先规则选出 `{name}`。验证正确张数 {selection['validation_baseline']['exact_count']}/17 → {selection['chosen']['exact_count']}/17，平均 F1 {selection['validation_baseline']['mean_per_image_f1']:.4f} → {selection['chosen']['mean_per_image_f1']:.4f}；升级资格为 {selection['eligible_for_promotion']}。未用测试结果换候选或阈值。",'',
        '| 新测试指标 | 原默认模型 | 训练候选 |','| --- | ---: | ---: |',
        f"| 每图四分类集合完全正确 | {baseline['exact_count']}/{baseline['images']} | {candidate['exact_count']}/{candidate['images']} |",
        f"| 平均逐图 F1 | {baseline['mean_per_image_f1']:.4f} | {candidate['mean_per_image_f1']:.4f} |",
        f"| 8 张未知/背景图被强行归四类 | {baseline['unknown_false_positive_images']}/8 | {candidate['unknown_false_positive_images']}/8 |",
        f"| 推理失败 | {sum(r['status']!='success' for r in baseline['records'])} | {sum(r['status']!='success' for r in candidate['records'])} |",'',
        f'从错误变正确 {len(corrected)} 张，从正确变错误 {len(regressed)} 张。以下保持原参考不改：','',
        '| 图片 | 参考类别 | 原默认模型 | 训练候选 |','| --- | --- | --- | --- |']
    for i in before:
        if not after[i]['exact_match'] or before[i]['predicted']!=after[i]['predicted']:
            lines.append(f"| [{i}]({rows[i]['source_page']}) | {label(before[i]['truth'])} | {label(before[i]['predicted'])} | {label(after[i]['predicted'])} |")
    lines+=['','| 类别 | 新测试出现图片数 | 原模型 TP / FP / FN | 候选 TP / FP / FN |', '| --- | ---: | --- | --- |']
    for c,cn in cats.items():
        a=baseline['per_category'][c];b=candidate['per_category'][c]
        lines.append(f"| {cn} | {a['support_images']} | {a.get('tp',0)} / {a.get('fp',0)} / {a.get('fn',0)} | {b.get('tp',0)} / {b.get('fp',0)} / {b.get('fn',0)} |")
    lines+=['','## 结论与限制','',
        '- 每图指标只比较四个类别是否出现，不代表每件物品名称、数量、框或理由全部正确；未知不强行当作其他垃圾。',
        f"- 测试为公开图像的便利样本：可回收 8、厨余 4、其他 3、有害 2、未知/背景 8；有害类只有 {len({r['training_group'] for r in rows.values() if 'hazardous' in r['categories']})} 个来源组。没有真实多人标注一致性检验，也缺少充分的混合、遮挡和实际投放照片。",
        '- 训练分类层无法直接解决 SAM 没有产生合适区域、区域包含背景、用途依赖上下文等问题；本轮也没有针对这些因素训练定位。',
        '- 本轮与历史 40 图是不同测试集，不能把两次比例直接相减当作模型变化。真实 SAM 区域缓存被公平复用，耗时不用于宣称端到端提速。',
        '- 参考来自作者说明和 Codex 视觉复核，非独立真人金标准。结果只支持本轮有限比较，不能声称日常投放可靠或考核交付已完成。','',
        '## 可追溯文件','',
        '- `protocol-freeze.json`：训练前的源码提交、参数、文件/权重哈希。',
        '- `training.json`：硬件、实际训练轨迹、四个分类权重的 SHA-256。',
        '- `selection.json`：全部验证候选及唯一选定候选。',
        '- `test-freeze.json`：测试开始前选定的权重和测试清单哈希。',
        '- `validation/`、`test/`：全部逐图真实预测和评分，包括失败/空结果。',
        '- `decision.json`：每一项升级条件与决定；数据原图与训练权重仅保存在本机，被 Git 忽略。','']
    (OUT/'训练与测试报告.md').write_text('\n'.join(lines),encoding='utf-8')
    print('Wrote',OUT/'训练与测试报告.md')

if __name__=='__main__':main()
