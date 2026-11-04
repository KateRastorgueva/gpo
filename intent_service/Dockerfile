FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MODEL_DIR=/models/intent \
    HF_HUB_OFFLINE=0

WORKDIR /srv

# CPU-сборка PyTorch: без CUDA образ меньше примерно на 2 ГБ.
RUN pip install torch==2.4.1 --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY fetch_model.py categories.py ./
RUN python fetch_model.py

COPY app.py .

# После сборки сеть сервису не нужна.
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
