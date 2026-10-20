"""Run frozen evaluation with sequential label checks on restricted Windows hosts."""
import os,runpy,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]

def main():
    if len(sys.argv)!=2 or sys.argv[1] not in {'validation','test','detection_test'}:
        raise SystemExit('Usage: run_windows_evaluation.py validation|test|detection_test')
    os.environ['YOLO_CONFIG_DIR']=str(ROOT/'.local/ultralytics')
    os.environ['YOLO_AUTOINSTALL']='false'
    os.environ['MPLCONFIGDIR']=str(ROOT/'.local/matplotlib')
    (ROOT/'.local/matplotlib').mkdir(parents=True,exist_ok=True)
    import ultralytics.data.dataset as dataset
    class SequentialPool:
        def __init__(self,*args,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def imap(self,func,iterable):return map(func,iterable)
    dataset.ThreadPool=SequentialPool
    target=Path(__file__).with_name('evaluate_detector_pipeline.py')
    sys.argv[0]=str(target);runpy.run_path(str(target),run_name='__main__')

if __name__=='__main__':main()
