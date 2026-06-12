# VPS Pack Hosting

Vocomi pack files can be deployed to the Vocomipedia VPS while keeping the
existing Azure upload code for older app versions and rollback support.

## Server Layout

```text
/srv/vocomi-packs/
  incoming/                 transient upload area
  releases/<release-name>/  immutable deployed artifacts
  current -> releases/...   active static root
```

Nginx serves `current` with `sendfile`, byte-range resume support, ETags, and a
per-connection download cap. The initial cap is 25 MB/s after the first 5 MB.
The deploy tool keeps old server releases according to `--keep-releases`; use
`--keep-releases 3` for normal production runs.

## GitHub Environment Secrets

Add these to the protected `production` environment in the Vocomipedia repo:

```text
VPS_PACK_HOST          VPS IP address or packs.vocomipedia.com
VPS_PACK_PORT          22
VPS_PACK_USER          vocomipedia
VPS_PACK_SSH_KEY       private key for the deploy user
VPS_PACK_ROOT          /srv/vocomi-packs
```

`Release And Deploy` uploads to the VPS when `vps_pack_deploy` is enabled. This
is independent of Azure: `upload` controls Azure upload, and `vps_pack_deploy`
controls VPS static hosting.

## Manual Deploy

After building packs locally:

```bash
python3 tools/deploy_packs_to_vps.py \
  --packs-dir release/packs \
  --release-name manual-test \
  --host "$VPS_HOST" \
  --port "$VPS_PORT" \
  --user vocomipedia \
  --ssh-key "$VPS_SSH_KEY_PATH" \
  --remote-root /srv/vocomi-packs \
  --keep-releases 3
```

## Local Artifact Cleanup

Local pack builds can accumulate quickly under `vocomi_pack_generation/packs`.
Use the dry run first:

```bash
python3 tools/prune_pack_artifacts.py \
  --packs-dir ../vocomi_pack_generation/packs \
  --keep 3
```

Then apply:

```bash
python3 tools/prune_pack_artifacts.py \
  --packs-dir ../vocomi_pack_generation/packs \
  --keep 3 \
  --apply
```

The grouping key is deck/artifact family plus pack kind. That means data packs,
preview image packs, full image packs, and individual chunk packs each keep
their own last three artifacts.

## URLs

Pack artifacts are served as plain static files:

```text
https://packs.vocomipedia.com/<file>.vpack
https://packs.vocomipedia.com/<file>.meta.json
https://packs.vocomipedia.com/<file>.sha256
```

During DNS propagation, test with the VPS IP and a Host header:

```bash
curl -I -H 'Host: packs.vocomipedia.com' http://<VPS_IP>/<file>.vpack
```
