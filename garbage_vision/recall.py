"""Conservative supplementation of detector results by independent SAM regions.

Uses image-derived outputs only. Category references, filenames and image IDs
are never used to select items. Score margins are uncalibrated CLIP evidence.
"""
from .local import box_iou
from .schema import InferenceResult


def supplement_regions(primary: InferenceResult, automatic: InferenceResult, *,
                       margin_min: float, mode: str, max_objects: int = 40):
    if mode not in ('empty-only', 'uncovered'):
        raise ValueError('Unknown supplementation mode')
    if not 0 <= margin_min <= 2 or max_objects < 1:
        raise ValueError('Invalid supplementation thresholds')
    if (primary.image_id, primary.source_sha256, primary.image_size) != (
            automatic.image_id, automatic.source_sha256, automatic.image_size):
        raise ValueError('Cannot combine results for different images')
    if primary.method != 'local' or automatic.method != 'local':
        raise ValueError('Only local image-derived results may be combined')
    if primary.status != 'success' or automatic.status != 'success':
        raise ValueError('Incomplete inference cannot silently become a success')
    kept=[x.model_copy(deep=True) for x in primary.items]
    localized=[x for x in primary.items if x.bbox and x.category]
    added=[];rejected=[]
    for item in automatic.items:
        if mode=='empty-only' and localized:break
        # No scene-only labels, unknowns, or synthetic box proposals.
        if not item.bbox or not item.category or item.uncertain or item.mask_quality is None:continue
        if item.category_margin is None or item.category_margin < margin_min:continue
        if any(x.bbox and box_iou(x.bbox,item.bbox)>.5 for x in localized):
            rejected.append({'bbox':item.bbox,'label':item.label,'reason':'overlaps confirmed detector region'});continue
        if any(x.bbox and box_iou(x.bbox,item.bbox)>.7 for x in kept):continue
        copied=item.model_copy(deep=True)
        copied.reason+=' 自动分割补充区域；检测器未给出覆盖该区域的确定分类，需人工核对。'
        added.append(copied);kept.append(copied)
    # Localized recovery supersedes scene-only duplicate labels, not different
    # categories. Retain raw scene output in the component record for audit.
    recovered_categories={x.category for x in added}
    kept=[x for x in kept if x.bbox or x.category not in recovered_categories]
    truncated=len(kept)>max_objects
    result=primary.model_copy(deep=True)
    result.items=kept[:max_objects]
    result.model='YOLOv8n + SAM2 + CLIP with conservative SAM supplementation'
    result.elapsed_seconds=primary.elapsed_seconds+automatic.elapsed_seconds
    result.load_seconds=primary.load_seconds+automatic.load_seconds
    result.cache_hit=primary.cache_hit and automatic.cache_hit
    result.metadata={**primary.metadata,'recall_supplement':{
        'mode':mode,'margin_min':margin_min,'added_count':len(added),
        'added':[x.model_dump() for x in added],'rejected_overlap':rejected,
        'automatic_config_sha256':automatic.metadata.get('config_sha256'),
        'automatic_weight_sha256':automatic.metadata.get('weight_sha256'),
        'truncated':truncated,'score_note':'CLIP category margin is not calibrated probability.'},
        'experimental':True,'truncated':truncated or primary.metadata.get('truncated',False)}
    return result
