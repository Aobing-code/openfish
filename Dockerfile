FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY static/ ./static/
COPY config.example.json ./config.json

EXPOSE 8080

CMD ["python", "-m", "app.main"]
