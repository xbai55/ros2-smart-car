"""Train/evaluate an explicit YOLO11 specialist; preserve real metrics and hashes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--epochs', type=int, default=60)
    parser.add_argument('--batch', type=int, default=8)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault('YOLO_CONFIG_DIR', str(root / 'ultralytics-config'))
    Path(os.environ['YOLO_CONFIG_DIR']).mkdir(parents=True, exist_ok=True)
    import torch
    import ultralytics
    from ultralytics import YOLO
    model = YOLO(args.model)
    if '11' not in str(model.model.yaml.get('yaml_file', '')) and not args.resume:
        raise ValueError('This workflow is locked to YOLO11; supply an explicit YOLO11 checkpoint')
    metadata = {'state': 'training', 'data': str(args.data.resolve()), 'initial_model': args.model,
                'torch': torch.__version__, 'ultralytics': ultralytics.__version__,
                'gpu': torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'cpu',
                'started_at': time.time(), 'epochs': args.epochs, 'batch': args.batch, 'workers': args.workers,
                'deployment_validation': 'not_evaluated'}
    manifest = root / 'training-manifest.json'
    manifest.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    try:
        model.train(data=str(args.data.resolve()), epochs=args.epochs, batch=args.batch, imgsz=640, device=0,
                    workers=args.workers, seed=20261017, deterministic=True, project=str(root), name='train', exist_ok=True,
                    patience=15, cache=False, plots=True, resume=args.resume, close_mosaic=10)
        best = Path(model.trainer.best)
        detector = YOLO(str(best))
        result = detector.val(data=str(args.data.resolve()), split='test', imgsz=640, batch=args.batch, device=0,
                              project=str(root), name='test', exist_ok=True, plots=True)
        metadata.update(state='trained_public_data_only', best=str(best), sha256=hashlib.sha256(best.read_bytes()).hexdigest(),
                        test_metrics={k: float(v) for k, v in result.results_dict.items()}, finished_at=time.time())
    except BaseException as exc:
        metadata.update(state='interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed', error=str(exc), finished_at=time.time())
        raise
    finally:
        manifest.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
