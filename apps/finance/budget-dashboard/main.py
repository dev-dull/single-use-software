"""Budget Dashboard — finance visualization SUS app."""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="Budget Dashboard")


@app.get("/", response_class=HTMLResponse)
async def index():
    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>Budget Dashboard</title>
<script src="https://unpkg.com/htmx.org@2.0.4"></script>
<style>body{font-family:system-ui,sans-serif;max-width:600px;margin:4rem auto;padding:0 1rem}</style>
</head><body>
<h1>Budget Dashboard</h1>
<p>Visualize team budgets and spending trends in real time.</p>
</body></html>"""
