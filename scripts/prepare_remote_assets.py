"""Prepare private deployment assets; no credentials, API calls or cloud resources."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = {
    'sam2.1_t.pt': '3c1e81ca9b037dd39d70a014ddb9a813d6c4c4e12555420db7eaff31689bd4e3',
    'ViT-B-32.pt': '40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af',
}
SAMPLES = ['commons-179028310.jpg', 'commons-79273563.jpg']


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check():
    for name, expected in WEIGHTS.items():
        if sha(ROOT/'weights'/name) != expected:
            raise RuntimeError(f'Weight checksum mismatch: {name}')
    for name in SAMPLES:
        if not (ROOT/'data/raw/commons'/name).is_file():
            raise RuntimeError(f'Missing sample: {name}')
    return {'weights_verified': list(WEIGHTS), 'samples_present': SAMPLES}


def portable_identity(archive_path, image, commit):
    """Docker classic uses config IDs; containerd can expose OCI index IDs."""
    with tarfile.open(archive_path, 'r:') as archive:
        records = json.load(archive.extractfile('manifest.json'))
        record, = [r for r in records if image in r.get('RepoTags', [])]
        raw = archive.extractfile(record['Config']).read()
        config_digest = 'sha256:' + hashlib.sha256(raw).hexdigest()
        config = json.loads(raw)
        assert config['architecture'] == 'amd64' and config['os'] == 'linux'
        assert config['config']['Labels']['org.opencontainers.image.revision'] == commit
        ids = {config_digest}

        def walk(descriptor):
            digest = descriptor['digest']
            if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
                raise ValueError('Unsupported OCI digest')
            payload = archive.extractfile('blobs/sha256/' + digest.split(':')[1]).read()
            assert 'sha256:' + hashlib.sha256(payload).hexdigest() == digest
            node = json.loads(payload)
            matches = node.get('config', {}).get('digest') == config_digest
            for child in node.get('manifests', []):
                matches = walk(child) or matches
            if matches:
                ids.add(digest)
            return matches

        if 'index.json' in archive.getnames():
            for descriptor in json.load(archive.extractfile('index.json'))['manifests']:
                # Only traverse the selected app reference; other images may have
                # descriptors for platforms absent from this single-platform save.
                reference = descriptor.get('annotations', {}).get('io.containerd.image.name', '')
                if reference.endswith('/' + image) or reference == image:
                    walk(descriptor)
        return {'accepted_image_ids': sorted(ids), 'config_digest': config_digest,
                'rootfs_diff_ids': config['rootfs']['diff_ids']}


def pack(out, commit, image):
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Expected full Git commit')
    if image != f'garbage-vision-stage3:gpu-{commit[:12]}':
        raise ValueError('Image tag must match source commit')
    check()
    identity = json.loads((out/'image-identity.json').read_text(encoding='utf-8-sig'))
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', identity['image_id']):
        raise ValueError('Invalid image identity')
    portable = portable_identity(out/'images.tar', image, commit)
    if identity['image_id'] not in portable['accepted_image_ids']:
        raise ValueError('Export does not match the locally verified image')
    summary = json.loads((out/'summary.json').read_text(encoding='utf-8'))
    if len(summary['tasks']) != 2 or any(
        t['status'] != 'succeeded' or t['device'] != 'cuda:0' for t in summary['tasks']
    ):
        raise RuntimeError('Two real CUDA tasks must pass before packaging')
    bundle = out/'bundle'
    bundle.mkdir(exist_ok=False)
    subprocess.run(['git', '-C', str(ROOT), 'archive', '--format=tar.gz',
                    '-o', str(bundle/'source.tar.gz'), commit], check=True)
    # This private runtime archive is not a public release or a Git artifact.
    with tarfile.open(bundle/'runtime-assets.tar.gz', 'w:gz', compresslevel=1) as archive:
        for name in WEIGHTS:
            archive.add(ROOT/'weights'/name, arcname=f'weights/{name}')
        for name in SAMPLES:
            archive.add(ROOT/'data/raw/commons'/name, arcname=f'data/raw/commons/{name}')
    with (out/'images.tar').open('rb') as src, gzip.open(bundle/'images.tar.gz', 'wb', compresslevel=1) as dst:
        shutil.copyfileobj(src, dst, length=8*1024*1024)
    shutil.copyfile(ROOT/'scripts/deploy_prebuilt.sh', bundle/'deploy_prebuilt.sh')
    files = {p.name: {'bytes': p.stat().st_size, 'sha256': sha(p)}
             for p in sorted(bundle.iterdir()) if p.is_file()}
    manifest = {'schema': 1, 'commit': commit, 'image': image, 'image_id': identity['image_id'],
                'portable_identity': portable,
                'platform': 'linux/amd64', 'device': 'cuda:0', 'paid_call_limit': 0,
                'local_gpu_verified': True, 'remote_verified': False, 'files': files,
                'total_bytes': sum(v['bytes'] for v in files.values())}
    (bundle/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'bundle': str(bundle), 'total_bytes': manifest['total_bytes'],
                      'remote_verified': False}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--commit')
    parser.add_argument('--image')
    args = parser.parse_args()
    if args.check:
        print(json.dumps(check(), ensure_ascii=False))
    else:
        if not all([args.out, args.commit, args.image]):
            parser.error('--out, --commit and --image are required')
        pack(args.out.resolve(), args.commit, args.image)
