"""Protect real-coordinate boxes and empty detector behavior in the experiment."""
import importlib.util
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('prepare_detection',ROOT/'scripts/experiments/prepare_detection_data.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def test_xywh_conversion_preserves_non_square_coordinates():
    assert module.yolo_box([100,20,200,40],1000,200)==pytest.approx([.2,.2,.2,.2])

@pytest.mark.parametrize('box',[[0,0,0,4],[-3,0,5,4],[0,0,1002,4],[0,0,4,205]])
def test_invalid_annotations_are_not_silently_used(box):
    with pytest.raises(ValueError):module.yolo_box(box,1000,200)

def test_binary_supplements_only_use_prior_training_images():
    import json
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    train={r['id']:r for r in read(ROOT/'data/manifests/training_train_v06.json')}
    rows=read(ROOT/'data/manifests/commons_detection_annotations_v07.json')['images']
    for row in rows:
        assert row['id'] in train
        assert row['sha256']==train[row['id']]['sha256']
        if row['review_status']=='accepted':
            assert row['boxes_xyxy'] and row['reviewed_before_training']
            w,h=row['image_size']
            for x1,y1,x2,y2 in row['boxes_xyxy']:
                assert 0<=x1<x2<=w and 0<=y1<y2<=h

@pytest.mark.parametrize('size,orientation,target', [((4,2),3,(3,1)),((4,4),6,(3,0))])
def test_exif_is_applied_even_when_dimensions_do_not_change(size,orientation,target):
    from PIL import Image
    from io import BytesIO
    im=Image.new('RGB',size,'black');im.putpixel((0,0),(255,0,0))
    exif=Image.Exif();exif[274]=orientation;buf=BytesIO();im.save(buf,format='PNG',exif=exif)
    oriented,flag=module.oriented_taco_image(buf.getvalue(),size)
    assert oriented.getpixel(target)==(255,0,0) and flag==orientation
    assert oriented.getpixel((0,0))==(0,0,0)
