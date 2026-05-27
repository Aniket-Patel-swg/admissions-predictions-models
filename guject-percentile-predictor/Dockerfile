# Build from this folder (same as college-predictor / marks-predictor):
#   docker build -t guject-percentile-predictor .
#
# Board CSVs live under data/ (gujcet, cbse, gseb, isce).
# Deploys as an AWS Lambda container image (Function URL).
# Uses AWS Lambda Web Adapter so the FastAPI/uvicorn app runs unchanged.
FROM python:3.9-slim

COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.9.0 /lambda-adapter /opt/extensions/lambda-adapter

ENV AWS_LWA_PORT=8080 \
    AWS_LWA_INVOKE_MODE=buffered \
    AWS_LWA_READINESS_CHECK_PATH=/health \
    PORT=8080 \
    PYTHONUNBUFFERED=1

WORKDIR /var/task

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY data ./data

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
