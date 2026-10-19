"""验证真实梯度更新和数据隔离；合成向量仅测试训练数学，不作为模型效果证据。"""
import copy,importlib.util
from pathlib import Path
import pytest
import torch
from garbage_vision.config import ROOT

spec=importlib.util.spec_from_file_location('train_classifier',ROOT/'scripts/experiments/train_classifier.py')
training=importlib.util.module_from_spec(spec);spec.loader.exec_module(training)

def test_supervised_gradient_reduces_loss_and_preserves_unseen_class():
    base=torch.eye(3);features=torch.tensor([[.8,.6,0.],[.7,.7,0.],[0.,.8,.6]])
    features=torch.nn.functional.normalize(features,dim=-1);targets=torch.tensor([1,1,0])
    learned,logs=training.fit_head(features,targets,base,torch.ones(3),1.,{'epochs':40,'learning_rate':.01,'temperature':10.})
    assert logs[-1]['cross_entropy']<logs[0]['cross_entropy']
    assert not torch.allclose(learned[:2],base[:2])
    assert torch.equal(learned[2],base[2])
    assert torch.allclose(learned.norm(dim=1),torch.ones(3))

def test_real_training_splits_exclude_historical_tests():
    splits={s:training.manifest(s) for s in ['train','validation','test']}
    old=training.read(ROOT/'data/manifests/test.json')+training.read(ROOT/'data/manifests/quality_test.json')
    assert training.audit_splits(splits,old)
    assert all(not r['prior_development'] for r in splits['test'])
    assert {c for r in splits['validation'] for c in r['categories']}=={'recyclable','hazardous','kitchen','other'}

def test_author_and_near_duplicate_leakage_are_rejected():
    splits={s:training.manifest(s) for s in ['train','test']}
    for field in ['author','sha256','dhash','training_group']:
        bad=copy.deepcopy(splits);bad['test'][0][field]=bad['train'][0][field]
        with pytest.raises(ValueError,match='leakage'):training.audit_splits(bad,[])
