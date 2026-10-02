FROM python:3.13-slim
WORKDIR /app
COPY service.py index.html ./
COPY assets ./assets
ENV PYTHONUNBUFFERED=1
ENV POCKETFUL_STAGE=2
CMD ["python3","service.py"]
