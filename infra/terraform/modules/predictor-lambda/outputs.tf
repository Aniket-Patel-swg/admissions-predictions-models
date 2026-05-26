output "aws_account_id" {
  description = "AWS account id (useful for Jenkins env var)."
  value       = local.account_id
}

output "aws_region" {
  description = "AWS region (useful for Jenkins env var)."
  value       = local.region
}

output "ecr_repository_url" {
  description = "ECR repository URL."
  value       = aws_ecr_repository.this.repository_url
}

output "ecr_repository_name" {
  description = "ECR repository name. Set as ECR_REPO in Jenkins."
  value       = aws_ecr_repository.this.name
}

output "lambda_function_name" {
  description = "Lambda function name. Set as LAMBDA_FUNCTION in Jenkins."
  value       = aws_lambda_function.this.function_name
}

output "lambda_function_arn" {
  description = "Lambda function ARN (useful when granting lambda:InvokeFunctionUrl to a caller's role)."
  value       = aws_lambda_function.this.arn
}

output "lambda_role_arn" {
  description = "Execution role ARN attached to the Lambda."
  value       = aws_iam_role.lambda_exec.arn
}

output "lambda_function_url" {
  description = "Public HTTPS URL for the Lambda Function URL."
  value       = aws_lambda_function_url.this.function_url
}
