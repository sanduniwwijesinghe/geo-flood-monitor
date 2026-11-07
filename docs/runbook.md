# Runbook - Geo Flood Monitor

## SLOs

| SLO | SLI | Target | Window | Alerting |
|---|---|---|---|---|
| Freshness | Time since last successful analysis per AOI | < 26 h | continuous | `GeofloodPipelineStale` |
| Tile latency | Share of tile requests served in < 500 ms (ingress-nginx histogram) | 99 % | 30 d | Multi-window burn rate: 14.4x (1h & 5m) page, 6x (6h & 30m) ticket |
| Tile availability | Share of tile requests not returning 5xx | 99.5 % | 30 d | Same burn-rate pattern |

## pipeline-stale

**Meaning:** no successful run for an AOI in 26 h.

1. Check the last workflows: `argo list -n geoflood` / `kubectl -n geoflood get wf`.
2. If none ran: check the CronWorkflow is not suspended (`argo cron list -n geoflood`) and the
   Argo controller is healthy (`kubectl -n argo get pods`).
3. If runs are pending: the spot pool may be unable to scale up (spot capacity / quota).
   `kubectl get nodes -l workload=geoflood-batch`, `kubectl describe pod <pending-pod>`.
   Mitigation: temporarily remove the spot toleration / nodeSelector via
   `helm upgrade ... --set pipeline.nodeSelector=null` so jobs run on the system pool.
4. If runs fail, follow **pipeline-failing**.

## pipeline-failing

1. Logs: `argo logs -n geoflood @latest` or `kubectl -n geoflood logs <pod>`.
2. Common causes:
   - **No event scene**: heavy monsoon cloud cover for the whole lookback window. Expected
     during NE/SW monsoon; raise `--lookback-days` or `--max-cloud`, or accept and ack.
   - **STAC / SAS token errors (HTTP 403/5xx from Planetary Computer)**: upstream issue;
     retries with backoff are built in. Check https://planetarycomputer.microsoft.com status.
   - **Blob upload 403**: workload identity broken. Verify the service account annotation
     `azure.workload.identity/client-id`, pod label `azure.workload.identity/use=true`, and the
     federated credential subject `system:serviceaccount:geoflood:geoflood-pipeline`.
   - **OOMKilled**: AOI too large for the memory limit; raise `pipeline.resources.limits.memory`.
3. Re-run once fixed: `argo submit --from cronwf/geoflood-pipeline -n geoflood`.

## tile-latency / tile-availability burn

1. Grafana -> *Geo Flood Monitor - SLOs*: confirm p95 latency and 5xx rate.
2. `kubectl -n geoflood get hpa,pods -l app.kubernetes.io/name=titiler` - is the HPA at max?
3. Slow COG reads from Blob are the usual cause: check GDAL cache env vars and that COGs
   have overviews (`rio cogeo validate <url>`).
4. Mitigate: scale out (`kubectl -n geoflood scale deploy geoflood-titiler --replicas=6`
   after raising `titiler.autoscaling.maxReplicas`), roll back the last release
   (`helm rollback geoflood`).
