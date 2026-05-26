output "aws_account_id"       { value = module.predictor.aws_account_id }
output "aws_region"           { value = module.predictor.aws_region }
output "ecr_repository_url"   { value = module.predictor.ecr_repository_url }
output "ecr_repository_name"  { value = module.predictor.ecr_repository_name }
output "lambda_function_name" { value = module.predictor.lambda_function_name }
output "lambda_function_arn"  { value = module.predictor.lambda_function_arn }
output "lambda_role_arn"      { value = module.predictor.lambda_role_arn }

# Plug into the Node backend env: PERCENTILE_PREDICTOR_URL
output "lambda_function_url" { value = module.predictor.lambda_function_url }
