# Operations Runbook

## Local Quality Checks

```bash
ruff check .
mypy custom_components tests
pytest -q
```

## Deploy to Test HA Container

Example sequence used in this project:

```bash
rm -rf /tmp/enocean_ble_deploy
mkdir -p /tmp/enocean_ble_deploy
rsync -a --delete custom_components/enocean_ble/ /tmp/enocean_ble_deploy/enocean_ble/
scp -r /tmp/enocean_ble_deploy/enocean_ble 172.30.46.1:/tmp/enocean_ble
ssh 172.30.46.1 "sudo mkdir -p /data/hatest/custom_components/enocean_ble && \
  sudo rsync -a --delete /tmp/enocean_ble/enocean_ble/ /data/hatest/custom_components/enocean_ble/ && \
  sudo docker restart ha_test_8124"
```

## Post-Deploy Validation

Check startup:

```bash
ssh 172.30.46.1 "sudo docker logs --tail 200 ha_test_8124 2>&1 | grep -i enocean_ble"
```

Check flow markers:

```bash
ssh 172.30.46.1 "sudo docker logs --tail 500 ha_test_8124 2>&1 | \
  grep -i -E 'ENOCEAN_FLOW|USER_ADD|FLOW_CANCEL_TRACE|STAGE_START|STAGE_ERROR'"
```

## Recommended Incident Capture

When flow behavior is unexpected, capture:

- full unfiltered logs around event time window,
- the exact click sequence performed in UI,
- whether popup was closed or explicitly canceled,
- BLE signal context (RSSI, repeated frames, interference clues).

