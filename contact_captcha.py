"""Google reCAPTCHA v2 verification for the public contact form."""
import json
import os
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


def configuration():
    site = os.environ.get('RECAPTCHA_SITE_KEY', '').strip()
    secret = os.environ.get('RECAPTCHA_SECRET_KEY', '').strip()
    return site, secret


def verify(token, public_url):
    site, secret = configuration()
    if not site and not secret:
        return True  # Existing installations remain usable until keys are supplied.
    if not site or not secret:
        return False
    if not token or len(token) > 8192:
        return False
    hostnames = os.environ.get('RECAPTCHA_ALLOWED_HOSTNAMES', '')
    allowed = {host.strip().lower() for host in hostnames.split(',') if host.strip()}
    if not allowed:
        allowed = {urlsplit(public_url).hostname}
    payload = urlencode({'secret': secret, 'response': token}).encode('ascii')
    req = Request('https://www.google.com/recaptcha/api/siteverify', data=payload,
                  headers={'Content-Type': 'application/x-www-form-urlencoded'}, method='POST')
    try:
        with urlopen(req, timeout=8) as response:
            result = json.loads(response.read(65536))
        return (isinstance(result, dict) and result.get('success') is True
                and result.get('hostname', '').lower() in allowed)
    except (OSError, ValueError, TypeError, AttributeError):
        return False
