"""La URL del hub se valida en `checkpoint_core.urls` (pruebas en `checkpoint-core/tests/test_urls.py`)."""


def test_there_is_no_plain_http_warning_any_more():
    import checkpoint_hub

    assert not hasattr(checkpoint_hub, "is_plain_http")
    assert checkpoint_hub.normalize_hub_url("http://hub:8088/") == "http://hub:8088"  # el plugin usa la del core
