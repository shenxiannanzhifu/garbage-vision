from pathlib import Path
from tempfile import TemporaryDirectory
import json
import pytest
from scripts.probe_transport_optimization import shared_budget


def test_shared_scope_counts_failed_and_unresolved_requests_with_full_reservation():
    with TemporaryDirectory() as directory:
        folder=Path(directory)
        for key in ('success','failed','unresolved'):
            (folder/(key+'.started.json')).write_text(json.dumps({'reserved_nex':.218625}))
        (folder/'success.json').write_text(json.dumps({'estimated_cost_nex':.04}))
        (folder/'failed.json').write_text(json.dumps({'estimated_cost_nex':None}))
        count,spent=shared_budget([folder])
        assert count==3 and spent==pytest.approx(.47725)
