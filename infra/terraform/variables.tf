variable "subscription_id" {
  description = "Azure subscription to deploy into"
  type        = string
}

variable "prefix" {
  description = "Short name prefix for all resources"
  type        = string
  default     = "geoflood"
}

variable "location" {
  description = "Azure region (Central India is the closest region to Sri Lanka)"
  type        = string
  default     = "centralindia"
}

variable "kubernetes_version" {
  description = "AKS version; null lets AKS pick the default supported version"
  type        = string
  default     = null
}

variable "system_vm_size" {
  type    = string
  default = "Standard_B2s"
}

variable "batch_vm_size" {
  description = "VM size for the spot pool that runs imagery processing jobs"
  type        = string
  default     = "Standard_D4as_v5"
}

variable "batch_max_nodes" {
  type    = number
  default = 3
}

variable "pipeline_namespace" {
  type    = string
  default = "geoflood"
}

variable "pipeline_service_account" {
  type    = string
  default = "geoflood-pipeline"
}

variable "tags" {
  type = map(string)

  default = {
    project    = "geo-flood-monitor"
    managed_by = "terraform"
  }
}
