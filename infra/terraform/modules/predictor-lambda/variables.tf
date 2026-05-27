variable "service_name" {
  description = "Logical service name; used for ECR repo, Lambda, IAM role, log group."
  type        = string
}

variable "image_tag" {
  description = "ECR image tag the Lambda points to at apply time. Jenkins overrides this on subsequent deploys."
  type        = string
  default     = "latest"
}

variable "memory_size" {
  description = "Lambda memory size in MB (also scales CPU)."
  type        = number
  default     = 2048
}

variable "timeout" {
  description = "Lambda timeout in seconds (Function URL hard ceiling is 30)."
  type        = number
  default     = 30
}

variable "architecture" {
  description = "Lambda CPU architecture. arm64 is ~20% cheaper and works for pandas/sklearn images."
  type        = string
  default     = "arm64"
  validation {
    condition     = contains(["x86_64", "arm64"], var.architecture)
    error_message = "architecture must be either 'x86_64' or 'arm64'."
  }
}

variable "env_vars" {
  description = "Extra environment variables injected into the Lambda."
  type        = map(string)
  default     = {}
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for the function."
  type        = number
  default     = 14
}

variable "ecr_image_retention_count" {
  description = "Number of most-recent ECR images to retain via lifecycle policy."
  type        = number
  default     = 10
}

variable "authorization_type" {
  description = "Lambda Function URL auth: 'NONE' (public) or 'AWS_IAM' (callers must sign with SigV4). Use AWS_IAM in production."
  type        = string
  default     = "NONE"
  validation {
    condition     = contains(["NONE", "AWS_IAM"], var.authorization_type)
    error_message = "authorization_type must be 'NONE' or 'AWS_IAM'."
  }
}

variable "cors_allow_origins" {
  description = "List of origins allowed by the Function URL CORS policy. Use ['*'] only for dev."
  type        = list(string)
  default     = ["*"]
}

variable "reserved_concurrent_executions" {
  description = "Cap on concurrent executions for this Lambda (-1 = unreserved). Set a small value (e.g. 20) to bound blast radius and cost."
  type        = number
  default     = -1
}
