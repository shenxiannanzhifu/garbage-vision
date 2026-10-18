from scripts.complete_quality_evaluation import interleaved_unsubmitted
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import pytest
from scripts import complete_quality_evaluation as completion
from garbage_vision.api import APISettings
from garbage_vision.experiment import public_api_config
from garbage_vision.schema import InferenceResult


def test_interleaving_covers_every_unsubmitted_image_once_and_preserves_group_order():
    rows=[{'id':key,'assessment_group':group} for key,group in [('a','hazardous'),('b','hazardous'),('c','other'),('d','unknown'),('e','other')]]
    result=interleaved_unsubmitted(rows,{'a'})
    assert [r['id'] for r in result]==['b','c','d','e']
    assert interleaved_unsubmitted(rows,{r['id'] for r in rows})==[]


@pytest.mark.parametrize('exhausted',[False,True])
def test_paid_boundary_stops_and_rerun_does_not_resend_failed_images(exhausted):
    with TemporaryDirectory() as directory:
        root=Path(directory);(root/'api').mkdir()
        settings=APISettings(provider='nexavlinks',model='gpt-6-astra',key='TEST',enabled=True,
            base_url='https://www.nexavlinks.com/v1',proxy_url='http://127.0.0.1:1')
        (root/'freeze.json').write_text(json.dumps({'api_config':public_api_config(settings),
            'sources':{'prompts/classify_v2.txt':'DIGEST','config/categories.json':'DIGEST'}}))
        rows=[{'id':str(n),'path':str(n)+'.jpg','sha256':'DIGEST','categories':['other']} for n in range(3)]
        for row in rows:(root/row['path']).write_bytes(b'test')
        (root/'completion-freeze.json').write_text(json.dumps({'api_config':public_api_config(settings),
            'proposed_shared_max_calls':42,'maximum_new_calls':22,'sources':{},'images':rows,'git_commit':'TEST_FROZEN_SOURCE'}))
        failure=InferenceResult(image_id='a'*64,source_sha256='b'*64,image_size=(1,1),method='api',model='gpt-6-astra',status='error',error='Test connection failure')
        with patch.object(completion,'DIRECTORY',root),patch.object(completion,'ROOT',root),patch.object(completion,'CANDIDATE',root/'candidate'),patch.object(completion,'api_settings',return_value=settings),patch.object(completion,'text_hash',return_value='DIGEST'),patch.object(completion,'weight_hash',return_value='DIGEST'),patch.object(completion,'decode_image',return_value=object()),patch.object(completion,'reservation_nex',return_value=.218625),patch.object(completion,'infer_api',return_value=failure) as infer,patch('sys.argv',['complete_quality_evaluation.py','run','--confirm-quality-scope']):
            if exhausted:
                with patch.object(completion,'shared_budget',return_value=(42,1)),pytest.raises(ValueError,match='exhausted'):
                    completion.main()
                assert infer.call_count==0 and not list((root/'api').glob('*.started.json'))
            else:
                with pytest.raises(ValueError,match='consecutive'):completion.main()
                assert infer.call_count==2 and len(list((root/'api').glob('*.started.json')))==2
                with pytest.raises(ValueError,match='consecutive'):completion.main()
                assert infer.call_count==2
