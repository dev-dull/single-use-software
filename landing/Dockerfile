FROM python:3.12-slim

WORKDIR /app

COPY landing/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY landing/app/ ./app/
COPY apps/ /repo/apps/
COPY claude/skills/ /repo/claude/skills/

ENV SUS_APPS_ROOT=/repo/apps
ENV SUS_SKILLS_DIR=/repo/claude/skills

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
