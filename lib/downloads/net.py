# coding=utf-8
"""The one place that talks HTTP, so timeouts and failures behave the same everywhere."""

from __future__ import absolute_import

import requests

DEFAULT_TIMEOUT = 6.0


class ServiceError(Exception):
    """A service that could not be reached, or would not answer properly."""

    def __init__(self, message, status=None):
        Exception.__init__(self, message)
        self.status = status

    @property
    def unauthorized(self):
        return self.status in (401, 403)


def describe(exc):
    """A reason short enough to put on a TV."""
    if isinstance(exc, ServiceError):
        return str(exc)
    if isinstance(exc, requests.exceptions.Timeout):
        return "timed out"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "unreachable"
    return str(exc) or exc.__class__.__name__


def normaliseUrl(url):
    if not url:
        return ""
    url = url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    return url


class Session(object):
    """
    A requests session per service, kept for the cookie qBittorrent hands out
    at login. Every call goes through here so nothing can be written without a
    timeout - a hung service must never take the UI with it.
    """

    def __init__(self, base_url, timeout=DEFAULT_TIMEOUT, headers=None):
        self.base_url = normaliseUrl(base_url)
        self.timeout = timeout
        self.session = requests.Session()
        if headers:
            self.session.headers.update(headers)

    def request(self, path, method="get", expect_json=True, ok=(200,), **kwargs):
        url = "{0}{1}".format(self.base_url, path)
        kwargs.setdefault("timeout", self.timeout)
        try:
            response = getattr(self.session, method)(url, **kwargs)
        except Exception as e:
            raise ServiceError(describe(e))

        if response.status_code not in ok:
            raise ServiceError("HTTP {0}".format(response.status_code),
                               status=response.status_code)
        if not expect_json:
            return response.text
        try:
            return response.json()
        except ValueError:
            raise ServiceError("unexpected answer")

    def close(self):
        try:
            self.session.close()
        except Exception:
            pass
