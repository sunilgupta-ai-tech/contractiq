variable "project" {
  type    = string
  default = "contractiq"
}

variable "environment" {
  description = "staging | production"
  type        = string
  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be staging or production."
  }
}

variable "region" {
  type    = string
  default = "ap-south-1"
}

# --- Network ---------------------------------------------------------------------

variable "vpc_cidr" {
  type    = string
  default = "10.40.0.0/16"
}

variable "az_count" {
  type    = number
  default = 2
}

variable "single_nat_gateway" {
  description = "One NAT gateway (cheaper) instead of one per AZ (survives an AZ outage)."
  type        = bool
  default     = true
}

# --- Public endpoint ---------------------------------------------------------------

variable "domain_name" {
  description = "Public hostname of the app, e.g. contracts.example.com (DNS points at the ALB)."
  type        = string
}

variable "certificate_arn" {
  description = "ACM certificate for domain_name, in var.region."
  type        = string
}

# --- Images and capacity -----------------------------------------------------------

variable "image_tag" {
  description = "Tag of the backend, worker and frontend images in ECR (the deploy workflow uses the git SHA)."
  type        = string
  default     = "latest"
}

variable "backend" {
  type = object({ cpu = number, memory = number, desired = number, min = number, max = number })
  default = { cpu = 1024, memory = 2048, desired = 2, min = 2, max = 6 }
}

variable "worker" {
  description = "OCR and embedding are CPU/memory heavy: size generously."
  type = object({ cpu = number, memory = number, desired = number, min = number, max = number })
  default = { cpu = 2048, memory = 4096, desired = 2, min = 1, max = 8 }
}

variable "frontend" {
  type    = object({ cpu = number, memory = number, desired = number })
  default = { cpu = 512, memory = 1024, desired = 2 }
}

# --- Data stores -------------------------------------------------------------------

variable "db_instance_class" {
  type    = string
  default = "db.t4g.medium"
}

variable "db_allocated_storage_gb" {
  type    = number
  default = 50
}

variable "db_multi_az" {
  type    = bool
  default = true
}

variable "redis_node_type" {
  type    = string
  default = "cache.t4g.small"
}

variable "qdrant_url" {
  description = "Qdrant Cloud cluster URL (https://…:6333). Its API key goes into the qdrant_api_key secret."
  type        = string
}

# --- Application -------------------------------------------------------------------

variable "app_environment" {
  description = <<-EOT
    Extra non-secret settings for backend and worker (see docs/configuration.md),
    e.g. { GEMINI_MODEL = "gemini-2.5-flash", GROUNDING_MODE = "enforce" }.
  EOT
  type    = map(string)
  default = {}
}

variable "alarm_email" {
  description = "Receives CloudWatch alarm notifications (confirm the subscription email)."
  type        = string
}
