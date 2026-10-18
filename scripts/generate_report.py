"""只从完整冻结实验生成双方案报告与图表；重新计分校验，不发请求或挑选样本。"""
import argparse
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from garbage_vision.config import ROOT
from garbage_vision.evaluation import score_records, CATEGORIES
from garbage_vision.experiment import file_hash

NAMES = {'recyclable':'可回收物','hazardous':'有害垃圾','kitchen':'厨余垃圾','other':'其他垃圾'}


def generate(directory):
    """核对两侧冻结文件与每张标准化图片标识，保留所有逐图错误。"""
    frozen = json.loads((directory / 'freeze.json').read_text(encoding='utf-8'))
    evidence, scores = {}, {}
    for method in ('local', 'api'):
        evidence[method] = json.loads((directory / method / 'predictions.json').read_text(encoding='utf-8'))
        if evidence[method]['freeze_sha256'] != file_hash(directory / 'freeze.json'):
            raise ValueError('两方案不是同一个冻结实验。')
        records = evidence[method]['records']
        scores[method] = score_records(frozen['images'], records)
        by_id = {r['id']: r for r in records}
        for row in frozen['images']:
            if by_id[row['id']]['result']['image_id'] != row['image_id']:
                raise ValueError('标准化图片 ID 不同，拒绝同图比较。')
    out = directory / 'report'; out.mkdir(exist_ok=True)
    summary = {'freeze_sha256': file_hash(directory / 'freeze.json'), 'split': frozen['split'],
               'local': scores['local'], 'api': scores['api']}
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    plot(scores, out)
    split_name = '独立测试' if frozen['split']=='test' else '开发验证'
    lines = [f'# 同图双方案{split_name}报告', '',
             f"代码提交：`{frozen['git_commit']}`。共 {len(frozen['images'])} 张固定图片。来源和预先复核标签见 freeze.json。", '',
             '**参考标签来自作者元数据和 Codex 预先视觉复核，非独立真人标注。以下是小样本的探索性比较。**', '',
             '## 共同任务与计分', '',
             '主指标为每图四分类出现集合的 precision/recall/F1，再等权平均。未知不当作其他垃圾，空预测和失败不删除。没有真实框标注，不计算 mAP；不比较模型自述信心。', '',
             '| 方案 | 平均 Precision | 平均 Recall | 平均 F1 | 集合完全一致率 | 失败率 | 空类别集合比例 | 含未知图片比例 |',
             '|---|---:|---:|---:|---:|---:|---:|---:|']
    for method, label in [('local','SAM2.1 + CLIP'), ('api','Qwen3-VL-Plus')]:
        s=scores[method]
        keys=['mean_per_image_precision','mean_per_image_recall','mean_per_image_f1','exact_set_accuracy',
              'failure_rate','empty_prediction_rate','unknown_image_rate']
        lines.append('| '+label+' | '+' | '.join(f'{s[k]:.4f}' for k in keys)+' |')
    lines += ['', '![按类别统计的 F1](category-f1.png)', '',
              '| 类别 | 真值出现图片数 | 本地 F1 | API F1 |', '|---|---:|---:|---:|']
    for category in CATEGORIES:
        l=scores['local']['per_category'][category]; a=scores['api']['per_category'][category]
        lines.append(f"| {NAMES[category]} | {l['support_images']} | {l['f1']:.4f} | {a['f1']:.4f} |")
    lines += ['', '逐类别指标在所有图上聚合 TP/FP/FN，和先逐图平均的主指标不是同一种平均方式。', '',
              '## 背景、耗时与费用', '', '| 背景组 | 图片数 | 本地逐图平均 F1 | API 逐图平均 F1 |', '|---|---:|---:|---:|']
    for group, l in scores['local']['by_background'].items():
        a=scores['api']['by_background'][group]
        lines.append(f"| {group} | {l['images']} | {l['mean_per_image_f1']:.4f} | {a['mean_per_image_f1']:.4f} |")
    lines += ['', '| 方案 | 平均推理/请求秒 | 中位数秒 | 模型加载秒（单列） |', '|---|---:|---:|---:|']
    for method, label in [('local','本地'), ('api','API')]:
        t=scores[method]['timing']
        lines.append(f"| {label} | {t['mean_request_or_inference_seconds']:.3f} | {t['median_request_or_inference_seconds']:.3f} | {t['total_load_seconds']:.3f} |")
    api=evidence['api']
    lines += ['', 'API 耗时包含网络，本地运行于记录中的 GPU；不同硬件/网络和并行负载会改变速度，不能据此给出普遍速度结论。', '',
              f"本批有返回用量的请求按公开价估算合计 **{api['estimated_cost_yuan']:.6f} 元**；用量未知记录 {api['unknown_cost_records']} 条。免费额度与实际账单未核实。开发调用和网页验收费用不混入本批。", '',
              '## 全部逐图对照', '', '| 图片 | 参考类别 | 本地类别 | API 类别 | 本地 F1 | API F1 | 本地/API 状态 |', '|---|---|---|---|---:|---:|---|']
    local={r['id']:r for r in scores['local']['records']}; remote={r['id']:r for r in scores['api']['records']}
    for row in frozen['images']:
        l,a=local[row['id']],remote[row['id']]
        fmt=lambda values:'、'.join(NAMES[x] for x in values) or '空/未知'
        lines.append(f"| {row['id']} | {fmt(row['categories'])} | {fmt(l['predicted'])} | {fmt(a['predicted'])} | {l['f1']:.3f} | {a['f1']:.3f} | {l['status']}/{a['status']} |")
    lines += ['', '## 局限与证据追溯', '',
              '- 类别出现集合不检查物品名称、数量或定位是否准确。即使集合一致，也可能包含物品幻觉或错误局部框。',
              '- 测试样本小且类别不均，多物品主要为同类别；混合类别、遮挡和未知场景覆盖不足，不能外推城市实用准确率。',
              '- SAM 的框可能表示局部区域；过滤未知部件只能减少部分重复，不保证物品计数。API 的文字解释同样可能误判材质与用途。',
              '- 公共预训练数据重叠未知；测试独立性仅指未参与本项目选型/调参，参考标签尚缺独立人工复核。',
              '- 模型别名可能更新；每次 API 原始记录保留返回 model、响应 ID、usage、时间和提示词哈希。',
              '- 上级 freeze.json 保存代码、参数、权重和数据清单指纹；local/api 目录保留逐图结果与开始标记，包含失败。', '',
              '本报告由 scripts/generate_report.py 从全部原始记录重新计分生成；没有隐藏失败图片或基于测试结果改参数。']
    (out/'对比报告.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print('报告：', out/'对比报告.md')


def plot(scores, out):
    """标准绘图库生成可独立分享的图表，配置缓存限制在项目本地。"""
    os.environ['MPLCONFIGDIR']=str(ROOT/'.local/matplotlib')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties
    font=FontProperties(fname='C:/Windows/Fonts/msyh.ttc') if Path('C:/Windows/Fonts/msyh.ttc').exists() else None
    fig, ax=plt.subplots(figsize=(9,4.5), layout='constrained')
    x=list(range(4));width=.34
    for offset, method, color, label in [(-width/2,'local','#157960','SAM2.1 + CLIP'),(width/2,'api','#dd8743','Qwen3-VL-Plus')]:
        values=[scores[method]['per_category'][c]['f1'] for c in CATEGORIES]
        bars=ax.bar([i+offset for i in x],values,width,color=color,label=label)
        ax.bar_label(bars,fmt='%.2f',padding=3,fontsize=10)
    ax.set_xticks(x,[NAMES[c] if font else c for c in CATEGORIES],fontproperties=font)
    ax.set_ylim(0,1.18);ax.set_ylabel('F1');ax.set_title('四分类出现集合：按类别 F1' if font else 'Category-presence F1',fontproperties=font)
    ax.spines[['top','right']].set_visible(False);ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True);ax.legend(loc='upper center',ncol=2,frameon=False)
    fig.savefig(out/'category-f1.png',dpi=180);fig.savefig(out/'category-f1.svg');plt.close(fig)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=Path)
    generate(parser.parse_args().directory)
