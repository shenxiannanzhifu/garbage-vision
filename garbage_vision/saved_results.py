"""读取同图的已保存真实API记录供页面查看；不调用模型、不改变原始证据。"""
import json
from .config import ROOT
from .schema import InferenceResult


def find_saved_api(source,settings):
    if settings is None or settings.provider!='nexavlinks':return None
    folder=ROOT/'evidence/v0.5.0/nexavlinks-trial'
    for path in sorted(folder.glob('commons-*.json')):
        if '.started.' in path.name:continue
        try:
            record=json.loads(path.read_text(encoding='utf-8'))
            result=InferenceResult.model_validate(record['result'])
        except (ValueError,KeyError,OSError):continue
        if (result.status!='success' or result.image_id!=source.image_id or
                result.source_sha256!=source.source_sha256 or result.model!=settings.model or
                result.metadata.get('provider')!=settings.provider):continue
        return result.model_copy(update={'metadata':{**result.metadata,
            'display_mode':'saved_real_api_result','saved_record_path':path.relative_to(ROOT).as_posix()}})
    return None
