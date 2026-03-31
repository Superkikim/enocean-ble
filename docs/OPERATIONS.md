# Operations Runbook

## Local Quality Checks

```bash
ruff check .
mypy custom_components tests
pytest -q
```

## Deploy to HA Test Instance (`ha_test_8124`)

Use `/tmp/enocean_ble` as transfer directory, then sync to persistent volume:

```bash
rm -rf /tmp/enocean_ble
mkdir -p /tmp/enocean_ble
rsync -a --delete custom_components/enocean_ble/ /tmp/enocean_ble/
scp -r /tmp/enocean_ble 172.30.46.1:/tmp/
ssh 172.30.46.1 "sudo mkdir -p /data/hatest/custom_components/enocean_ble && \
  sudo rsync -a --delete /tmp/enocean_ble/ /data/hatest/custom_components/enocean_ble/ && \
  sudo docker restart ha_test_8124"
```

## Deploy to HA Main Instance (`home_assistant`)

```bash
ssh 172.30.46.1 "sudo mkdir -p /data/home_assistant/custom_components/enocean_ble && \
  sudo rsync -a --delete /tmp/enocean_ble/ /data/home_assistant/custom_components/enocean_ble/ && \
  sudo docker restart home_assistant"
```

## Post-Deploy Validation

```bash
ssh 172.30.46.1 "sudo docker logs --tail 200 ha_test_8124 2>&1 | grep -i -E 'enocean_ble|FLOW_TRACE_V3|commissioning'"
```

For main instance:

```bash
ssh 172.30.46.1 "sudo docker logs --tail 200 home_assistant 2>&1 | grep -i -E 'enocean_ble|FLOW_TRACE_V3|commissioning'"
```

## Release Checklist

1. All local checks pass.
2. `manifest.json` version bumped.
3. `README.md` and `docs/` aligned with current behavior.
4. Commit and push on `dev`, merge/update `main`.
5. Create git tag (HA-style: `YYYY.M` or `YYYY.M.patch`).
6. Publish GitHub release from tag.
