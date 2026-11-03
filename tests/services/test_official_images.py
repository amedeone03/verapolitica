from backend.app.services.official_images import official_https_image_url


def test_camera_http_portraits_become_https():
    assert (
        official_https_image_url("http://documenti.camera.it/app/sindicari/thumb.aspx?id=1")
        == "https://documenti.camera.it/app/sindicari/thumb.aspx?id=1"
    )


def test_non_official_http_is_dropped():
    assert official_https_image_url("http://example.com/face.jpg") is None


def test_https_official_url_is_kept():
    assert (
        official_https_image_url("https://www.governo.it/sites/default/files/meloni.jpg")
        == "https://www.governo.it/sites/default/files/meloni.jpg"
    )


def test_javascript_and_empty_are_dropped():
    assert official_https_image_url("javascript:alert(1)") is None
    assert official_https_image_url("") is None
    assert official_https_image_url(None) is None
