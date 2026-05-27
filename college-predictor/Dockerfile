# Build from this folder:
#   docker build -t college-predictor .
#
# Deploys as an AWS Lambda container image (Function URL or API Gateway).
# Uses AWS Lambda Web Adapter so the FastAPI/uvicorn app runs unchanged.
FROM python:3.11-slim

COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.9.0 /lambda-adapter /opt/extensions/lambda-adapter

ENV AWS_LWA_PORT=8080 \
    AWS_LWA_INVOKE_MODE=buffered \
    AWS_LWA_READINESS_CHECK_PATH=/health \
    AWS_LWA_READINESS_CHECK_TIMEOUT=120000 \
    PORT=8080 \
    PYTHONUNBUFFERED=1

WORKDIR /var/task

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY college_predictor.py .
COPY data ./data
RUN test -f data/acpc_last_admitted_all_years.csv

EXPOSE 8080

CMD ["uvicorn", "college_predictor:app", "--host", "0.0.0.0", "--port", "8080"]
