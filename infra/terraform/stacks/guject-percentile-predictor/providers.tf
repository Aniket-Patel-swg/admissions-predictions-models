variable "aws_region" {
  description = "AWS region for all resources in this stack."
  type        = string
  default     = "ap-south-1"
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = "admission-buddy"
      Service   = "guject-percentile-predictor"
      ManagedBy = "terraform"
    }
  }
}
