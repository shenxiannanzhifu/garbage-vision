"""共同评分：逐图四分类出现集合，不比较框与文本，不删除空结果和失败。"""
from collections import Counter
from statistics import mean, median

CATEGORIES = ('recyclable', 'hazardous', 'kitchen', 'other')


def set_scores(truth, predicted, success=True):
    """非空真值下空预测记零；双方为空仅在成功时记完全正确。"""
    truth, predicted = set(truth), set(predicted) if success else set()
    if not truth <= set(CATEGORIES) or not predicted <= set(CATEGORIES):
        raise ValueError('评分只能使用四分类代码。')
    tp, fp, fn = len(truth & predicted), len(predicted - truth), len(truth - predicted)
    both_empty = success and not truth and not predicted
    p = tp / (tp + fp) if tp + fp else float(both_empty)
    r = tp / (tp + fn) if tp + fn else float(both_empty)
    f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else float(both_empty)
    return {'tp': tp, 'fp': fp, 'fn': fn, 'precision': p, 'recall': r, 'f1': f1,
            'exact_match': bool(success and truth == predicted)}


def score_records(manifest, records):
    """严格对齐完整清单和图片哈希；遗漏/重复记录报错，运行失败则正常计零。"""
    expected = {r['id']: r for r in manifest}
    actual = {r['id']: r for r in records}
    if not manifest or len(expected) != len(manifest) or len(actual) != len(records):
        raise ValueError('清单不能为空，图片记录不能重复。')
    if set(expected) != set(actual):
        raise ValueError('预测必须覆盖完整清单，缺失不能静默删除。')
    details = []
    totals = Counter()
    per_category = {c: Counter() for c in CATEGORIES}
    methods = set()
    for image_id, row in expected.items():
        result = actual[image_id]['result']
        if result['source_sha256'] != row['sha256']:
            raise ValueError('预测图片哈希与清单不符：' + image_id)
        status = result['status']
        if status not in ('success', 'error', 'not_configured'):
            raise ValueError('未知运行状态。')
        methods.add(result['method'])
        truth = set(row['categories'])
        predicted = {item['category'] for item in result['items'] if item['category'] is not None} if status == 'success' else set()
        scores = set_scores(truth, predicted, status == 'success')
        unknown = sum(x['category'] is None for x in result['items']) if status == 'success' else 0
        details.append({'id': image_id, 'truth': sorted(truth), 'predicted': sorted(predicted),
                        'background': row.get('background', '未标注'), 'status': status,
                        'unknown_items': unknown, 'elapsed_seconds': result.get('elapsed_seconds', 0),
                        'load_seconds': result.get('load_seconds', 0), **scores})
        totals.update({k: scores[k] for k in ('tp', 'fp', 'fn')})
        for category in CATEGORIES:
            per_category[category].update(tp=int(category in truth & predicted),
                                          fp=int(category in predicted - truth), fn=int(category in truth - predicted))
    if len(methods) != 1:
        raise ValueError('同一评分文件不能混合两种方案。')
    n = len(details)
    tp, fp, fn = (totals[k] for k in ('tp', 'fp', 'fn'))
    def ratio(a, b): return a / b if b else 0.0
    class_scores = {}
    for category, count in per_category.items():
        a, b, c = (count[k] for k in ('tp', 'fp', 'fn'))
        class_scores[category] = {**dict(count), 'support_images': a+c,
                                 'precision': ratio(a, a+b), 'recall': ratio(a, a+c), 'f1': ratio(2*a, 2*a+b+c)}
    groups = {}
    for group in sorted({r['background'] for r in details}):
        subset = [r for r in details if r['background'] == group]
        groups[group] = {'images': len(subset), 'mean_per_image_f1': mean(r['f1'] for r in subset),
                         'failure_rate': mean(r['status'] != 'success' for r in subset)}
    return {'method': next(iter(methods)), 'images': n,
            'mean_per_image_precision': mean(r['precision'] for r in details),
            'mean_per_image_recall': mean(r['recall'] for r in details),
            'mean_per_image_f1': mean(r['f1'] for r in details),
            'exact_set_accuracy': mean(r['exact_match'] for r in details),
            'failure_rate': mean(r['status'] != 'success' for r in details),
            'empty_prediction_rate': mean(not r['predicted'] for r in details),
            'unknown_image_rate': mean(r['unknown_items'] > 0 for r in details),
            'micro': {'tp': tp, 'fp': fp, 'fn': fn, 'precision': ratio(tp, tp+fp),
                      'recall': ratio(tp, tp+fn), 'f1': ratio(2*tp, 2*tp+fp+fn)},
            'per_category': class_scores, 'by_background': groups,
            'timing': {'mean_request_or_inference_seconds': mean(r['elapsed_seconds'] for r in details),
                       'median_request_or_inference_seconds': median(r['elapsed_seconds'] for r in details),
                       'total_load_seconds': sum(r['load_seconds'] for r in details)},
            'records': details}
