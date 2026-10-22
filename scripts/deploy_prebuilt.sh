#!/usr/bin/env bash
# Execute on the confirmed Linux GPU server, from the uploaded private bundle.
# Requires existing Docker Compose and NVIDIA Container Toolkit; installs nothing.
set -euo pipefail
umask 077
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
python3 - <<'PY'
import hashlib, json, pathlib, re
p = pathlib.Path('.')
m = json.loads((p/'manifest.json').read_text())
assert m['schema'] == 1 and re.fullmatch('[0-9a-f]{40}', m['commit'])
assert m['image'] == 'garbage-vision-stage3:gpu-' + m['commit'][:12]
assert m['local_gpu_verified'] and not m['remote_verified']
assert set(m['files']) == {'source.tar.gz','runtime-assets.tar.gz','images.tar.gz','deploy_prebuilt.sh'}
for name, record in m['files'].items():
    with (p/name).open('rb') as f:
        assert hashlib.file_digest(f, 'sha256').hexdigest() == record['sha256'], name
print('Bundle checksums passed; remote validation still required.')
PY
docker info >/dev/null
docker compose version
nvidia-smi
docker image load -i images.tar.gz
python3 - <<'PY'
import json, subprocess
m=json.load(open('manifest.json'))
actual=json.loads(subprocess.check_output(['docker','image','inspect',m['image']]))[0]
identity=m['portable_identity']
assert m['image_id'] in identity['accepted_image_ids']
assert actual['Id'] in identity['accepted_image_ids'], 'Image identity mismatch'
assert actual['RootFS']['Layers']==identity['rootfs_diff_ids'], 'Image layers mismatch'
assert actual['Architecture']=='amd64' and actual['Os']=='linux'
assert actual['Config']['Labels']['org.opencontainers.image.revision']==m['commit']
print('Loaded Linux image matches the locally verified source and image ID.')
PY
commit=$(python3 -c 'import json;print(json.load(open("manifest.json"))["commit"])')
image="garbage-vision-stage3:gpu-${commit:0:12}"
release="$PWD/release-$commit"
# A fresh release is intentional: never overwrite an existing database or .env.
mkdir -- "$release"
tar -xzf source.tar.gz -C "$release"
tar -xzf runtime-assets.tar.gz -C "$release"
cd -- "$release"
mkdir -p .local/container-data evidence/stage3/remote-linux
# Mounted model/sample/evidence directories must be readable by UID 10001.
# Credentials are created separately below and remain mode 0600.
chmod -R a+rX weights data/raw evidence
python3 - <<'PY'
import pathlib, secrets
p=pathlib.Path('.')
(p/'.env').write_text('# No external model credentials transferred.\n')
(p/'.env.stage3').write_text('GV_S3_ACCESS_TOKEN='+secrets.token_urlsafe(32)+'\nGV_S3_PAID_CALL_LIMIT=0\nGV_S3_DEVICE=cuda:0\n')
for name in ['.env','.env.stage3']: (p/name).chmod(0o600)
PY
python3 - "$image" <<'PY'
import json, pathlib, sys
pathlib.Path('.local/prebuilt.json').write_text(json.dumps({'services':{
    'api':{'image':sys.argv[1]},'web':{'image':sys.argv[1]}}}))
PY
docker run --rm --user 0 --mount "type=bind,src=$release/.local/container-data,dst=/data" "$image" chown 10001:10001 /data
docker run --rm --gpus all "$image" python -c 'import torch; assert torch.cuda.is_available(); x=torch.ones(4,device="cuda"); assert x.sum().item()==4; print(torch.cuda.get_device_name())'
docker compose -f compose.yaml -f compose.gpu.yaml -f .local/prebuilt.json config --quiet
docker compose -f compose.yaml -f compose.gpu.yaml -f .local/prebuilt.json up -d --no-build --pull never --wait --wait-timeout 180
docker compose -f compose.yaml -f compose.gpu.yaml -f .local/prebuilt.json ps
printf '%s\n' 'Services started on server loopback:8080. Next: SSH tunnel, two real image tasks, persistence, export and recording.'
printf '%s\n' 'This message does not certify remote model acceptance. Paid API limit is still zero.'
