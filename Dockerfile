# Build the Material UI frontend.
FROM node:20-alpine AS frontend
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html vite.config.js ./
COPY src ./src
RUN npm run build

# Serve the frontend and FastAPI comment checker from one web service.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=10000
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py ./
COPY --from=frontend /app/dist ./dist
EXPOSE 10000
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-10000}"]
