FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY landing/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY landing/app/ ./app/
COPY claude/skills/ /repo/claude/skills/

ENV SUS_SKILLS_DIR=/repo/claude/skills

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
