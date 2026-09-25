"""HTML landing page served at the API root to browsers."""

from html import escape

from pydantic import BaseModel


class ServiceInfo(BaseModel):
    """Service description returned at the API root."""

    name: str
    version: str
    docs: str
    health: str
    endpoints: list[str]


_STYLE = """
:root { color-scheme: light dark; --fg: #12151A; --muted: #5f6368; --bg: #FAF9F6;
        --card: #fff; --line: #e3e3e3; --accent: #1D7A85; --on-accent: #fff; }
@media (prefers-color-scheme: dark) {
  :root { --fg: #FAF9F6; --muted: #a0a4a8; --bg: #12151A; --card: #1a1f25;
          --line: #2c333b; --accent: #4FB3BF; --on-accent: #0b1220; } }
* { box-sizing: border-box; }
body { margin: 0; font: 16px/1.5 system-ui, -apple-system, sans-serif; color: var(--fg);
       background: var(--bg); }
main { max-width: 760px; margin: 0 auto; padding: 48px 16px; }
h1 { margin: 0 0 4px; font-size: 28px; }
p.lead { margin: 0 0 24px; color: var(--muted); }
.links { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 32px; }
.links a { padding: 8px 16px; border-radius: 8px; border: 1px solid var(--line);
           background: var(--card); color: var(--accent); text-decoration: none; }
.links a.primary { background: var(--accent); color: var(--on-accent);
                   border-color: var(--accent); }
table { width: 100%; border-collapse: collapse; background: var(--card);
        border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
td { padding: 10px 14px; border-top: 1px solid var(--line); font-family: ui-monospace, monospace;
     font-size: 14px; overflow-wrap: anywhere; }
tr:first-child td { border-top: 0; }
td.method { width: 72px; font-weight: 600; color: var(--muted); }
td a { color: var(--accent); }
footer { margin-top: 24px; color: var(--muted); font-size: 14px; }
"""


def _endpoint_row(endpoint: str) -> str:
    """Render one ``METHOD /path`` row, linking parameter-free GET routes."""
    method, _, path = endpoint.partition(" ")
    label = escape(path)
    if method == "GET" and "{" not in path:
        label = f'<a href="{escape(path)}">{label}</a>'
    return f'<tr><td class="method">{escape(method)}</td><td>{label}</td></tr>'


def render_landing(info: ServiceInfo, description: str) -> str:
    """Render the landing page.

    Args:
        info: Service description (the same data the JSON root returns).
        description: One-line summary of the service.

    Returns:
        A complete HTML document.
    """
    rows = "\n".join(_endpoint_row(e) for e in info.endpoints)
    name = escape(info.name)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name}</title>
<style>{_STYLE}</style>
</head>
<body>
<main>
  <h1>{name}</h1>
  <p class="lead">{escape(description)} Version {escape(info.version)}.</p>
  <div class="links">
    <a class="primary" href="{escape(info.docs)}">Interactive API docs</a>
    <a href="{escape(info.health)}">Health</a>
    <a href="/openapi.json">OpenAPI schema</a>
  </div>
  <table>
{rows}
  </table>
  <footer>This page is shown to browsers. API clients requesting JSON receive the same
  information as JSON. Every endpoint under /api/v1 requires an X-API-Key header.</footer>
</main>
</body>
</html>
"""
