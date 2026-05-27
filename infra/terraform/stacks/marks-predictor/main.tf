variable "image_tag" {
  type    = string
  default = "latest"
}

variable "memory_size" {
  type    = number
  default = 2048
}

variable "timeout" {
  type    = number
  default = 30
}

variable "architecture" {
  type    = string
  default = "arm64"
}

variable "authorization_type" {
  type    = string
  default = "NONE"
}

variable "cors_allow_origins" {
  type    = list(string)
  default = ["*"]
}

variable "reserved_concurrent_executions" {
  type    = number
  default = -1
}

variable "env_vars" {
  type    = map(string)
  default = {}
}

module "predictor" {
  source = "../../modules/predictor-lambda"

  service_name                   = "marks-predictor"
  image_tag                      = var.image_tag
  memory_size                    = var.memory_size
  timeout                        = var.timeout
  architecture                   = var.architecture
  authorization_type             = var.authorization_type
  cors_allow_origins             = var.cors_allow_origins
  reserved_concurrent_executions = var.reserved_concurrent_executions
  env_vars                       = var.env_vars
}
