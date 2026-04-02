"""Hello World — minimal SUS example app (Python + HTMX)."""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="Hello World")

HTML_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Hello from SUS!</title>
    <script src="https://unpkg.com/htmx.org@2.0.4"></script>
    <style>
        body {
            font-family: system-ui, -apple-system, sans-serif;
            max-width: 600px;
            margin: 4rem auto;
            padding: 0 1rem;
            color: #1a1a1a;
        }
        h1 { color: #2563eb; }
        button {
            background: #2563eb;
            color: white;
            border: none;
            padding: 0.6rem 1.2rem;
            border-radius: 6px;
            font-size: 1rem;
            cursor: pointer;
        }
        button:hover { background: #1d4ed8; }
        #greeting {
            margin-top: 1rem;
            padding: 1rem;
            border-radius: 6px;
            background: #f0f9ff;
        }
    </style>
</head>
<body>
    <h1>Hello from SUS!</h1>
    <p>This is a minimal example app running on the SUS platform.</p>
    <button hx-get="/greet" hx-target="#greeting" hx-swap="innerHTML">
        Click me
    </button>
    <div id="greeting"></div>
</body>
</html>
"""

_click_count = 0


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main page."""
    return HTML_PAGE


@app.get("/greet", response_class=HTMLResponse)
async def greet():
    """HTMX endpoint that returns a dynamic greeting."""
    global _click_count
    _click_count += 1
    ordinal = "time" if _click_count == 1 else "times"
    return (
        f'<p>You clicked <strong>{_click_count}</strong> {ordinal}. '
        f"The SUS platform is working.</p>"
    )
