resource "random_string" "suffix" {
  length  = 5
  upper   = false
  special = false
}

locals {
  name   = "${var.prefix}-${random_string.suffix.result}"
  name_c = "${var.prefix}${random_string.suffix.result}" # for resources that disallow dashes
}

resource "azurerm_resource_group" "this" {
  name     = "rg-${local.name}"
  location = var.location
  tags     = var.tags
}

# ---------------------------------------------------------------- monitoring
resource "azurerm_log_analytics_workspace" "this" {
  name                = "log-${local.name}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = var.tags
}

# ---------------------------------------------------------------- registry
resource "azurerm_container_registry" "this" {
  name                = "acr${local.name_c}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku                 = "Basic"
  admin_enabled       = false
  tags                = var.tags
}

# ---------------------------------------------------------------- AKS
resource "azurerm_kubernetes_cluster" "this" {
  name                = "aks-${local.name}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  dns_prefix          = local.name
  kubernetes_version  = var.kubernetes_version
  sku_tier            = "Free"

  # Workload Identity: pods get Entra ID tokens without stored secrets
  oidc_issuer_enabled       = true
  workload_identity_enabled = true

  default_node_pool {
    name                         = "system"
    vm_size                      = var.system_vm_size
    auto_scaling_enabled         = true
    min_count                    = 1
    max_count                    = 2
    only_critical_addons_enabled = false
    os_disk_size_gb              = 64
    upgrade_settings {
      max_surge = "10%"
    }
  }

  identity {
    type = "SystemAssigned"
  }

  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = "overlay"
    load_balancer_sku   = "standard"
  }

  oms_agent {
    log_analytics_workspace_id = azurerm_log_analytics_workspace.this.id
  }

  tags = var.tags
}

# Spot pool for the bursty imagery jobs; scales to zero between runs
resource "azurerm_kubernetes_cluster_node_pool" "batch" {
  name                  = "batch"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.this.id
  vm_size               = var.batch_vm_size
  priority              = "Spot"
  eviction_policy       = "Delete"
  spot_max_price        = -1
  auto_scaling_enabled  = true
  min_count             = 0
  max_count             = var.batch_max_nodes

  node_labels = {
    "workload" = "geoflood-batch"
  }
  # AKS adds this taint to spot pools; declaring it avoids a perpetual plan diff
  node_taints = ["kubernetes.azure.com/scalesetpriority=spot:NoSchedule"]
  tags        = var.tags
}

resource "azurerm_role_assignment" "aks_acr_pull" {
  scope                            = azurerm_container_registry.this.id
  role_definition_name             = "AcrPull"
  principal_id                     = azurerm_kubernetes_cluster.this.kubelet_identity[0].object_id
  skip_service_principal_aad_check = true
}

# ---------------------------------------------------------------- storage
resource "azurerm_storage_account" "this" {
  name                     = "st${local.name_c}"
  location                 = azurerm_resource_group.this.location
  resource_group_name      = azurerm_resource_group.this.name
  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_2"
  # Flood maps are public information; anonymous read lets TiTiler and browsers
  # fetch COGs over plain HTTPS. Writes still require Entra ID.
  allow_nested_items_to_be_public = true
  shared_access_key_enabled       = false

  blob_properties {
    cors_rule {
      allowed_methods    = ["GET", "HEAD"]
      allowed_origins    = ["*"]
      allowed_headers    = ["*"]
      exposed_headers    = ["*"]
      max_age_in_seconds = 3600
    }
  }
  tags = var.tags
}

resource "azurerm_storage_container" "cogs" {
  name                  = "flood-cogs"
  storage_account_id    = azurerm_storage_account.this.id
  container_access_type = "blob"
}

resource "azurerm_storage_management_policy" "cogs" {
  storage_account_id = azurerm_storage_account.this.id
  rule {
    name    = "cool-old-cogs"
    enabled = true
    filters {
      prefix_match = ["flood-cogs/"]
      blob_types   = ["blockBlob"]
    }
    actions {
      base_blob {
        tier_to_cool_after_days_since_modification_greater_than = 30
      }
    }
  }
}

# ---------------------------------------------------------------- workload identity
resource "azurerm_user_assigned_identity" "pipeline" {
  name                = "id-${local.name}-pipeline"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  tags                = var.tags
}

resource "azurerm_federated_identity_credential" "pipeline" {
  name                = "aks-${var.pipeline_service_account}"
  resource_group_name = azurerm_resource_group.this.name
  parent_id           = azurerm_user_assigned_identity.pipeline.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = azurerm_kubernetes_cluster.this.oidc_issuer_url
  subject             = "system:serviceaccount:${var.pipeline_namespace}:${var.pipeline_service_account}"
}

resource "azurerm_role_assignment" "pipeline_blob" {
  scope                = azurerm_storage_container.cogs.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.pipeline.principal_id
}

# ---------------------------------------------------------------- PostGIS
resource "random_password" "pg" {
  length  = 24
  special = false
}

resource "azurerm_postgresql_flexible_server" "this" {
  name                          = "psql-${local.name}"
  location                      = azurerm_resource_group.this.location
  resource_group_name           = azurerm_resource_group.this.name
  version                       = "16"
  sku_name                      = "B_Standard_B1ms"
  storage_mb                    = 32768
  backup_retention_days         = 7
  administrator_login           = "geofloodadmin"
  administrator_password        = random_password.pg.result
  public_network_access_enabled = true
  tags                          = var.tags

  lifecycle {
    ignore_changes = [zone]
  }
}

# 0.0.0.0 rule = "allow Azure services" (AKS egress). Use private access for production.
resource "azurerm_postgresql_flexible_server_firewall_rule" "azure" {
  name             = "allow-azure-services"
  server_id        = azurerm_postgresql_flexible_server.this.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

resource "azurerm_postgresql_flexible_server_configuration" "extensions" {
  name      = "azure.extensions"
  server_id = azurerm_postgresql_flexible_server.this.id
  value     = "POSTGIS"
}

resource "azurerm_postgresql_flexible_server_database" "geoflood" {
  name      = "geoflood"
  server_id = azurerm_postgresql_flexible_server.this.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}
