FROM python:3.13-slim
WORKDIR /app
COPY service.py .
ENV PYTHONUNBUFFERED=1\nENV POCKETFUL_STAGE=1
CMD ["python3","service.py"]
