from dndlabs.api.landing import ServiceInfo, render_landing


def test_landing_escapes_content() -> None:
    info = ServiceInfo(
        name="<script>x</script>",
        version="1",
        docs="/docs",
        health="/health",
        endpoints=["GET /a", "POST /b", "GET /c/{id}"],
    )
    page = render_landing(info, "desc & more")
    assert "<script>x</script>" not in page
    assert "&lt;script&gt;" in page
    assert "desc &amp; more" in page
    assert '<a href="/a">/a</a>' in page
    assert '<a href="/b">' not in page and '<a href="/c/{id}">' not in page
