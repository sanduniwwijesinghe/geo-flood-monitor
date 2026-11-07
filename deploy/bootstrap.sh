#!/usr/bin/env bash
# Install cluster add-ons and the geo-flood-monitor chart onto the AKS cluster created by Terraform.
# Usage: ./deploy/bootstrap.sh            (run from repo root after `terraform apply`)
set -euo pipefail

TF="terraform -chdir=infra/terraform"
RG=$($TF output -raw resource_group)
AKS=$($TF output -raw aks_name)
NS=geoflood

echo ">> Fetching kubeconfig for $AKS"
az aks get-credentials -g "$RG" -n "$AKS" --overwrite-existing

helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update

echo ">> ingress-nginx (with Prometheus metrics for tile SLOs)"
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx -n ingress-nginx --create-namespace \
  --set controller.metrics.enabled=true \
  --set controller.metrics.serviceMonitor.enabled=true \
  --set controller.metrics.serviceMonitor.additionalLabels.release=kube-prometheus-stack \
  --set controller.service.annotations."service\.beta\.kubernetes\.io/azure-load-balancer-health-probe-request-path"=/healthz

echo ">> kube-prometheus-stack + Pushgateway"
helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace \
  --set grafana.sidecar.dashboards.searchNamespace=ALL
helm upgrade --install prometheus-pushgateway prometheus-community/prometheus-pushgateway \
  -n monitoring --set serviceMonitor.enabled=true \
  --set serviceMonitor.additionalLabels.release=kube-prometheus-stack

echo ">> Argo Workflows"
helm upgrade --install argo-workflows argo/argo-workflows -n argo --create-namespace \
  --set "controller.workflowNamespaces={$NS}"

echo ">> Application"
kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f -
kubectl -n "$NS" create secret generic geoflood-db \
  --from-literal=DATABASE_URL="$($TF output -raw database_url)" \
  --dry-run=client -o yaml | kubectl apply -f -

LB_IP=""
until [ -n "$LB_IP" ]; do
  LB_IP=$(kubectl -n ingress-nginx get svc ingress-nginx-controller \
    -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || true)
  [ -z "$LB_IP" ] && sleep 5
done

helm upgrade --install geoflood deploy/helm/geo-flood-monitor -n "$NS" \
  --set serviceAccount.azureClientId="$($TF output -raw pipeline_identity_client_id)" \
  --set pipeline.storageAccountUrl="$($TF output -raw storage_account_url)" \
  --set ingress.host="tiles.${LB_IP}.nip.io"

echo
echo "Tiles:   http://tiles.${LB_IP}.nip.io/docs"
echo "Run now: argo submit --from cronwf/geoflood-pipeline -n $NS --watch"
