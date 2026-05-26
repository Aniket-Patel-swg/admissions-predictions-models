# Build from repository root (parent of this folder):
#   docker build -f guject-percentile-predictor/Dockerfile -t guject-percentile-predictor .
#
# Expects: guject-percentile-predictor/data/ (GUJCET CSVs), cbse/, gseb/, isce/ at repo root.
# Deploys as an AWS Lambda container image (Function URL or API Gateway).
# Uses AWS Lambda Web Adapter so the FastAPI/uvicorn app runs unchanged.
FROM python:3.9-slim

COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.9.0 /lambda-adapter /opt/extensions/lambda-adapter

ENV AWS_LWA_PORT=8080 \
    AWS_LWA_INVOKE_MODE=buffered \
    AWS_LWA_READINESS_CHECK_PATH=/health \
    PORT=8080 \
    PYTHONUNBUFFERED=1

WORKDIR /var/task

COPY guject-percentile-predictor/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY guject-percentile-predictor/main.py .
COPY guject-percentile-predictor/data ./data
COPY cbse ./cbse
COPY gseb ./gseb
COPY isce ./isce

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
