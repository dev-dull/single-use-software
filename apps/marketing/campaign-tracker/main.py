"""Campaign Tracker — marketing analytics SUS app."""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="Campaign Tracker")


@app.get("/", response_class=HTMLResponse)
async def index():
    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>Campaign Tracker</title>
<script src="https://unpkg.com/htmx.org@2.0.4"></script>
<style>body{font-family:system-ui,sans-serif;max-width:600px;margin:4rem auto;padding:0 1rem}</style>
</head><body>
<h1>Campaign Tracker</h1>
<p>Track marketing campaign performance across channels.</p>
</body></html>"""
