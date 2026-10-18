"""验证预算估算、凭据排除和中断标记，全部为本地软件检查，不收费。"""
import pytest
from garbage_vision.api import APISettings
from garbage_vision.experiment import estimate_cost, public_api_config, write_new_json


def test_returned_usage_pricing_and_unknown():
    assert estimate_cost({'prompt_tokens': 1766, 'completion_tokens': 50}) == pytest.approx(.002266)
    assert estimate_cost({'prompt_tokens': 40000, 'completion_tokens': 100}) == pytest.approx(.0615)
    assert estimate_cost({}) is None


def test_public_freeze_does_not_contain_credentials():
    import json
    s = APISettings(key='UNIT-TEST-SECRET', enabled=True)
    output = json.dumps(public_api_config(s))
    assert 'UNIT-TEST-SECRET' not in output and 'key' not in public_api_config(s)


def test_started_record_cannot_be_overwritten():
    from pathlib import Path
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as folder:
        p = Path(folder) / 'request.started.json'
        write_new_json(p, {'status': 'started'})
        with pytest.raises(FileExistsError): write_new_json(p, {'status': 'restarted'})
        assert 'restarted' not in p.read_text()
