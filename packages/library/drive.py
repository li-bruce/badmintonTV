"""Anonymous public Drive downloads with one tightly validated confirmation.

No login, cookies, captcha solving, alternate UA/proxy, cached tokens, or URL
rewrites are attempted. Pass open_drive_response as download's response_opener;
only the original stable URL belongs in provenance/receipts.
"""

from html.parser import HTMLParser
from http.client import HTTPException
import re
import urllib.error
import urllib.parse
import urllib.request

from .download import DownloadError, _SafeRedirect, _validate_url


HTML_LIMIT_BYTES = 65_536
DRIVE_HOST = "drive.usercontent.google.com"
CONFIRM_ACTION = "https://" + DRIVE_HOST + "/download"
_FORM_FIELDS = {"id", "export", "confirm", "uuid"}
_HEADERS = {"user-agent", "accept", "accept-encoding", "range", "if-range"}


class DriveConfirmationError(DownloadError):
    """A public Drive response cannot be safely treated as a download."""


def _error(code, message):
    return DriveConfirmationError("drive_" + code, message)


def _request_id(request):
    if not isinstance(request, urllib.request.Request):
        raise _error("invalid_request", "Drive opener requires an HTTP Request")
    try:
        _validate_url(request.full_url)
    except ValueError:
        raise _error("invalid_request", "Public Drive URL is invalid or contains credentials") from None
    parsed = urllib.parse.urlsplit(request.full_url)
    if (request.get_method() != "GET" or request.data is not None or parsed.scheme != "https"
            or parsed.netloc != DRIVE_HOST or parsed.path != "/uc" or parsed.fragment):
        raise _error("invalid_request", "Only the stable anonymous HTTPS Drive uc download endpoint is supported")
    try:
        pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        raise _error("invalid_request", "Malformed public Drive query") from None
    fields = dict(pairs)
    if (len(pairs) != 2 or set(fields) != {"id", "export"} or fields.get("export") != "download"
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", fields.get("id", ""))):
        raise _error("invalid_request", "Public Drive request requires exactly id and export=download")
    if any(name.lower() not in _HEADERS for name, _ in request.header_items()):
        raise _error("credentials_or_headers", "Only anonymous download and byte-range headers are supported")
    return fields["id"]


class _ConfirmationParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms = []
        self.active = None
        self.invalid = False
        self.blocked = False
        self.button_text = None

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if len(attrs) != len(attributes):
            self.invalid = True
        # Captcha widgets/password inputs signal an access step, never a
        # download-confirmation flow. Ordinary navigation links are not login.
        if (attrs.get("type") or "").lower() == "password" or any(
            marker in (value or "").lower()
            for key, value in attributes if key in {"src", "id", "class", "name"}
            for marker in ("recaptcha", "hcaptcha", "g-recaptcha")
        ):
            self.blocked = True
        if "formaction" in attrs or "formmethod" in attrs or "onsubmit" in attrs:
            self.invalid = True
        if tag == "form":
            if self.active is not None:
                self.invalid = True
            self.active = {"attrs": attrs, "fields": {}, "submit_labels": [], "closed": False}
            self.forms.append(self.active)
        elif tag == "input":
            if self.active is None:
                if attrs.get("name"):
                    self.invalid = True
                return
            kind = (attrs.get("type", "text") or "").lower()
            name = attrs.get("name")
            if "disabled" in attrs or "form" in attrs:
                self.invalid = True
            if kind == "hidden":
                if name not in _FORM_FIELDS or name in self.active["fields"] or attrs.get("value") is None:
                    self.invalid = True
                else:
                    self.active["fields"][name] = attrs["value"]
            elif kind == "submit" and not name:
                self.active["submit_labels"].append(attrs.get("value") or "")
            else:
                self.invalid = True
        elif tag == "button" and self.active is not None:
            if ((attrs.get("type", "submit") or "").lower() != "submit" or attrs.get("name")
                    or "disabled" in attrs or "form" in attrs or self.button_text is not None):
                self.invalid = True
            self.button_text = []
        elif self.active is not None and (tag in {"select", "textarea", "keygen"}
                                         or (tag == "fieldset" and "disabled" in attrs)):
            self.invalid = True

    def handle_endtag(self, tag):
        if tag == "button" and self.button_text is not None:
            if self.active is not None:
                self.active["submit_labels"].append("".join(self.button_text))
            self.button_text = None
        elif tag == "form":
            if self.active is None:
                self.invalid = True
            else:
                self.active["closed"] = True
            self.active = None

    def handle_data(self, data):
        if self.button_text is not None:
            self.button_text.append(data)


def _confirmation_fields(body, source_id):
    parser = _ConfirmationParser()
    try:
        parser.feed(body.decode("utf-8-sig"))
        parser.close()
    except (UnicodeError, ValueError):
        raise _error("invalid_confirmation", "Drive confirmation HTML could not be parsed") from None
    if parser.blocked:
        raise _error("access_blocked", "Drive requires login or captcha rather than public download confirmation")
    if parser.invalid or parser.active is not None or parser.button_text is not None or len(parser.forms) != 1:
        raise _error("invalid_confirmation", "Drive confirmation must contain exactly one standard download form")
    form = parser.forms[0]
    attrs, fields = form["attrs"], form["fields"]
    if (not form["closed"] or attrs.get("action") != CONFIRM_ACTION
            or (attrs.get("method", "get") or "").lower() != "get"
            or fields.get("id") != source_id or fields.get("export") != "download"
            or fields.get("confirm") != "t" or set(fields) - _FORM_FIELDS):
        raise _error("invalid_confirmation", "Drive confirmation form does not match the requested public file")
    if "uuid" in fields and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", fields["uuid"]):
        raise _error("invalid_confirmation", "Drive confirmation identifier is invalid")
    labels = {" ".join(label.split()).casefold() for label in form["submit_labels"]}
    if not labels.intersection({"download anyway", "仍要下载", "仍然下载"}):
        raise _error("invalid_confirmation", "Drive form is not a standard Download anyway confirmation")
    return fields


def _open_public(transport, request, timeout):
    try:
        response = transport.open(request, timeout=timeout)
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
        code = {401: "access_denied", 403: "access_denied", 404: "not_found", 429: "rate_limited"}.get(status, "http_error")
        raise _error(code, f"Public Drive request returned HTTP {status}") from None
    except (urllib.error.URLError, OSError, HTTPException):
        raise _error("network_error", "Public Drive request failed before receiving a response") from None
    except DownloadError:
        raise _error("invalid_redirect", "Public Drive redirect was refused by the download safety policy") from None
    except ValueError:
        raise _error("invalid_redirect", "Public Drive redirect was not an allowed HTTP(S) URL") from None
    try:
        try:
            _validate_url(response.url)
        except ValueError:
            raise _error("invalid_redirect", "Public Drive response URL is invalid or contains credentials") from None
        if urllib.parse.urlsplit(response.url).scheme != "https":
            raise _error("invalid_redirect", "Public Drive downloads must remain on HTTPS")
        if response.status not in (200, 206):
            code = {401: "access_denied", 403: "access_denied", 404: "not_found", 429: "rate_limited"}.get(response.status, "http_error")
            raise _error(code, f"Public Drive response returned HTTP {response.status}")
        return response
    except BaseException:
        response.close()
        raise


def _is_html(response):
    return response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() in {"text/html", "application/xhtml+xml"}


def open_drive_response(request, *, timeout=30):
    """Return a file response, following at most one public Download anyway form.

    Every invocation starts from its original uc URL and parses a fresh UUID.
    Range/If-Range and the caller's UA are retained across the confirmation GET.
    The returned response is owned/closed by the caller; HTML responses are
    closed here. No confirmation URL or HTML body is persisted or logged.
    """
    source_id = _request_id(request)
    transport = urllib.request.build_opener(_SafeRedirect())
    response = _open_public(transport, request, timeout)
    if not _is_html(response):
        return response
    try:
        location = urllib.parse.urlsplit(response.url)
        if location.netloc != DRIVE_HOST or location.path not in {"/uc", "/download"}:
            raise _error("access_blocked", "Drive redirected to a non-download access page")
        # Reject a full buffer rather than reading a sentinel byte: even a
        # misleading/absent Content-Length cannot consume more than 64 KiB.
        body = response.read(HTML_LIMIT_BYTES)
        if len(body) >= HTML_LIMIT_BYTES:
            raise _error("html_limit", "Drive confirmation HTML reaches the 64 KiB limit")
    except (OSError, urllib.error.URLError, HTTPException):
        raise _error("network_error", "Drive confirmation page could not be read") from None
    finally:
        response.close()
    fields = _confirmation_fields(body, source_id)
    confirmed = urllib.request.Request(CONFIRM_ACTION + "?" + urllib.parse.urlencode(fields),
                                       headers=dict(request.header_items()), method="GET")
    result = _open_public(transport, confirmed, timeout)
    if _is_html(result):
        result.close()
        raise _error("confirmation_rejected", "Drive still returned HTML after public download confirmation")
    return result


# download() calls this before writing the original URL into its first receipt.
# Validation inside open_drive_response remains necessary for standalone use.
open_drive_response.validate_request = _request_id
