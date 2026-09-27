import os


def install():
    """Point OpenSSL at a CA bundle the frozen app can always find."""
    path = ""
    try:
        import certifi
        path = certifi.where()
    except Exception:
        path = ""
    if not path or not os.path.isfile(path):
        for candidate in (
            os.environ.get("SSL_CERT_FILE") or "",
            "/etc/ssl/certs/ca-certificates.crt",
            "/etc/ssl/cert.pem",
            "/etc/ca-certificates/extracted/tls-ca-bundle.pem",
            "/etc/pki/tls/certs/ca-bundle.crt",
        ):
            if candidate and os.path.isfile(candidate):
                path = candidate
                break
    if not path:
        return
    os.environ.setdefault("SSL_CERT_FILE", path)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", path)
    os.environ.setdefault("CURL_CA_BUNDLE", path)
