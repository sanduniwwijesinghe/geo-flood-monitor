output "resource_group" {
  value = azurerm_resource_group.this.name
}

output "aks_name" {
  value = azurerm_kubernetes_cluster.this.name
}

output "acr_login_server" {
  value = azurerm_container_registry.this.login_server
}

output "storage_account_url" {
  value = azurerm_storage_account.this.primary_blob_endpoint
}

output "pipeline_identity_client_id" {
  description = "Goes into the Helm value serviceAccount.azureClientId"
  value       = azurerm_user_assigned_identity.pipeline.client_id
}

output "postgres_host" {
  value = azurerm_postgresql_flexible_server.this.fqdn
}

output "database_url" {
  description = "Store as a Kubernetes secret; never commit"
  sensitive   = true

  value = format(
    "postgresql://%s:%s@%s:5432/%s?sslmode=require",
    azurerm_postgresql_flexible_server.this.administrator_login,
    random_password.pg.result,
    azurerm_postgresql_flexible_server.this.fqdn,
    azurerm_postgresql_flexible_server_database.geoflood.name,
  )
}
