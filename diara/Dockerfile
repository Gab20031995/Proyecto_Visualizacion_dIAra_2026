FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN python backend/make_data.py
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "uvicorn api:app --app-dir backend --host 0.0.0.0 --port $PORT"]
