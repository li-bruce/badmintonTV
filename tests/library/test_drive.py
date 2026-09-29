"""Public Drive transport fixtures only; never contact Google or download data."""

from email.message import Message
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import urllib.error
import urllib.parse
import urllib.request

from packages.library.download import DownloadError, _SafeRedirect, download
from packages.library.drive import (
    CONFIRM_ACTION, HTML_LIMIT_BYTES, DriveConfirmationError, open_drive_response,
)
from packages.library.storage import QuotaManager


FILE_ID = "public_file-id_123"
URL = f"https://drive.usercontent.google.com/uc?id={FILE_ID}&export=download"
PAYLOAD = b'{"frames": [1, 2, 3], "fixture": true}'


def confirmation(uuid="fresh-uuid"):
    token = f'<input type="hidden" name="uuid" value="{uuid}">' if uuid is not None else ""
    return (f'<html><body><form id="download-form" action="{CONFIRM_ACTION}" method="get">'
            f'<input type="hidden" name="id" value="{FILE_ID}">'
            '<input type="hidden" name="export" value="download">'
            '<input type="hidden" name="confirm" value="t">' + token +
            '<input type="submit" value="Download anyway"></form></body></html>').encode()


class Response(io.BytesIO):
    def __init__(self, body=PAYLOAD, *, url=URL, status=200, content_type="application/json", **headers):
        super().__init__(body)
        self.url, self.status = url, status
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        for key, value in headers.items():
            self.headers[key] = str(value)
        self.read_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)


def html(body=None, **kwargs):
    return Response(confirmation() if body is None else body, content_type="text/html; charset=utf-8", **kwargs)


class DriveOpenerTests(unittest.TestCase):
    def setUp(self):
        self.transport = mock.Mock()
        self.factory = mock.patch("packages.library.drive.urllib.request.build_opener", return_value=self.transport)
        self.build_opener = self.factory.start()
        self.addCleanup(self.factory.stop)

    def request(self, **kwargs):
        return urllib.request.Request(URL, **kwargs)

    def check_error(self, code, request=None):
        with self.assertRaises(DriveConfirmationError) as caught:
            open_drive_response(self.request() if request is None else request)
        self.assertEqual(caught.exception.code, code)
        self.assertNotIn("https://", str(caught.exception))
        return caught.exception

    def test_direct_file_is_returned_unread_without_second_get(self):
        response = Response(url=CONFIRM_ACTION + f"?id={FILE_ID}&export=download")
        self.transport.open.return_value = response
        request = self.request(headers={"User-Agent": "unchanged-client"})
        self.assertIs(open_drive_response(request, timeout=17), response)
        self.transport.open.assert_called_once_with(request, timeout=17)
        self.assertEqual(response.read_sizes, [])
        self.assertFalse(response.closed)
        self.assertIsInstance(self.build_opener.call_args.args[0], _SafeRedirect)
        response.close()

    def test_standard_confirmation_preserves_range_and_ua(self):
        first, result = html(), Response(status=206)
        self.transport.open.side_effect = [first, result]
        request = self.request(headers={"Range": "bytes=5-", "If-Range": '"etag"',
                                        "User-Agent": "same-client", "Accept-Encoding": "identity"})
        self.assertIs(open_drive_response(request, timeout=19), result)
        self.assertTrue(first.closed)
        self.assertEqual(first.read_sizes, [HTML_LIMIT_BYTES])
        followup = self.transport.open.call_args.args[0]
        self.assertEqual(urllib.parse.urlsplit(followup.full_url)._replace(query="").geturl(), CONFIRM_ACTION)
        self.assertEqual(dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(followup.full_url).query)),
                         {"id": FILE_ID, "export": "download", "confirm": "t", "uuid": "fresh-uuid"})
        self.assertEqual(dict(followup.header_items()), dict(request.header_items()))
        self.assertEqual(self.transport.open.call_args.kwargs, {"timeout": 19})
        result.close()

    def test_uuid_optional_and_button_label_supported(self):
        page = confirmation(None).replace(b'<input type="submit" value="Download anyway">',
                                           b'<button type="submit"> Download <b>anyway</b> </button>')
        self.transport.open.side_effect = [html(page), Response()]
        with open_drive_response(self.request()):
            pass
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.transport.open.call_args.args[0].full_url).query)
        self.assertNotIn("uuid", query)

    def test_html_is_bounded_even_without_content_length(self):
        for length in (HTML_LIMIT_BYTES, HTML_LIMIT_BYTES + 100):
            with self.subTest(length=length):
                self.transport.reset_mock()
                page = html(confirmation() + b" " * length)
                self.transport.open.side_effect = [page]
                self.check_error("drive_html_limit")
                self.assertEqual(page.read_sizes, [HTML_LIMIT_BYTES])
                self.assertTrue(page.closed)
                self.assertEqual(self.transport.open.call_count, 1)

    def test_confirmation_html_is_rejected_without_third_get(self):
        first, second = html(), html()
        self.transport.open.side_effect = [first, second]
        self.check_error("drive_confirmation_rejected")
        self.assertTrue(first.closed and second.closed)
        self.assertEqual(second.read_sizes, [])
        self.assertEqual(self.transport.open.call_count, 2)

    def test_nonstandard_forms_never_trigger_confirmation(self):
        valid = confirmation()
        pages = [
            valid.replace(CONFIRM_ACTION.encode(), b"https://example.com/download"),
            valid.replace(CONFIRM_ACTION.encode(), (CONFIRM_ACTION + "?unexpected=1").encode()),
            valid.replace(b'method="get"', b'method="post"'),
            valid.replace(b'method="get"', b'method'),
            valid.replace(FILE_ID.encode(), b"different-file"),
            valid.replace(b'value="download"', b'value="view"'),
            valid.replace(b'value="t"', b'value="yes"'),
            valid.replace(b'name="uuid"', b'name="credential"'),
            valid.replace(b'value="fresh-uuid"', b'value="not/a/uuid"'),
            valid.replace(b'name="uuid"', b'name="id"'),
            valid.replace(b'type="hidden"', b'type', 1),
            valid.replace(b'type="hidden"', b'type="hidden" disabled', 1),
            valid.replace(b'type="hidden"', b'type="hidden" form="other"', 1),
            valid.replace(b'value="Download anyway"', b'value="Sign in"'),
            valid.replace(b'value="Download anyway"', b'value'),
            valid.replace(b'method="get"', b'method="get" method="get"'),
            valid.replace(b'type="submit"', b'type="submit" formaction="https://example.com"'),
            valid.replace(b'</form>', b'<textarea name="credential">unexpected</textarea></form>'),
            valid.replace(b'</form>', b'<select name="other"><option>unexpected</option></select></form>'),
            valid.replace(b'</form>', b''),
            valid + valid,
            b"<html>No download form</html>",
            b"\xff",
        ]
        for page in pages:
            with self.subTest(page=page[:100]):
                self.transport.reset_mock()
                response = html(page)
                self.transport.open.side_effect = [response]
                self.check_error("drive_invalid_confirmation")
                self.assertTrue(response.closed)
                self.assertEqual(self.transport.open.call_count, 1)

    def test_login_and_captcha_are_access_blocked(self):
        responses = [html(url="https://accounts.google.com/login"),
                     html(confirmation().replace(b'</form>', b'<input type="password"></form>')),
                     html(confirmation() + b'<div class="g-recaptcha"></div>'),
                     html(confirmation() + b'<script src="https://hcaptcha.com/api.js"></script>')]
        for response in responses:
            with self.subTest(url=response.url):
                self.transport.reset_mock()
                self.transport.open.side_effect = [response]
                self.check_error("drive_access_blocked")
                self.assertTrue(response.closed)
                self.assertEqual(self.transport.open.call_count, 1)

    def test_credentials_and_unstable_requests_are_rejected_before_network(self):
        invalid_urls = [URL.replace("https://", "http://"), URL + "&uuid=do-not-send",
                        URL + "&id=duplicate", URL + "#fragment", URL.replace("/uc?", "/download?"),
                        URL.replace("https://", "https://user:secret@"), URL.replace(FILE_ID, "a%2Fb")]
        for url in invalid_urls:
            with self.subTest(url=url):
                self.check_error("drive_invalid_request", urllib.request.Request(url))
        self.check_error("drive_invalid_request", self.request(method="POST"))
        self.check_error("drive_invalid_request", self.request(data=b"data"))
        for header in ("Cookie", "Authorization", "Proxy-Authorization", "X-Goog-AuthUser"):
            with self.subTest(header=header):
                self.check_error("drive_credentials_or_headers", self.request(headers={header: "secret"}))
        self.build_opener.assert_not_called()
        self.transport.open.assert_not_called()

    def test_http_errors_have_stable_codes_and_no_confirmation_url(self):
        for status, code in ((401, "access_denied"), (403, "access_denied"), (404, "not_found"),
                             (429, "rate_limited"), (500, "http_error")):
            with self.subTest(status=status):
                page = html()
                error_body = io.BytesIO(b"private error response")
                error = urllib.error.HTTPError(CONFIRM_ACTION + "?uuid=do-not-log", status, "failed", {}, error_body)
                self.transport.open.side_effect = [page, error]
                caught = self.check_error("drive_" + code)
                self.assertNotIn("do-not-log", str(caught))
                self.assertTrue(error_body.closed and page.closed)

    def test_network_errors_are_sanitized(self):
        for error in (urllib.error.URLError("https://example.com/?uuid=secret"), TimeoutError("secret")):
            self.transport.open.side_effect = [error]
            caught = self.check_error("drive_network_error")
            self.assertNotIn("secret", str(caught))

    def test_redirect_policy_remains_installed_and_errors_are_sanitized(self):
        self.transport.open.side_effect = [DownloadError("unsafe_redirect", "private?uuid=secret")]
        self.check_error("drive_invalid_redirect")
        handler = self.build_opener.call_args.args[0]
        self.assertIsInstance(handler, _SafeRedirect)
        with self.assertRaises(DownloadError):
            handler.redirect_request(self.request(), None, 302, "Found", {}, "http://example.com/payload")

    def test_bad_final_url_or_status_is_closed(self):
        cases = [("http://example.com/file", 200, "invalid_redirect"),
                 ("https://user:pass@example.com/file", 200, "invalid_redirect"),
                 (URL, 403, "access_denied"), (URL, 429, "rate_limited")]
        for url, status, code in cases:
            with self.subTest(url=url, status=status):
                response = Response(url=url, status=status)
                self.transport.open.side_effect = [response]
                self.check_error("drive_" + code)
                self.assertTrue(response.closed)


class DriveDownloadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="library-drive-test-")
        self.addCleanup(temporary.cleanup)
        self.quota = QuotaManager(Path(temporary.name) / "data", allow_test_root=True, min_free_bytes=0)
        self.transport = mock.Mock()
        patcher = mock.patch("packages.library.drive.urllib.request.build_opener", return_value=self.transport)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_download(self, **kwargs):
        return download(URL, "training/source/public.json", quota=self.quota,
                        max_bytes=len(PAYLOAD), response_opener=open_drive_response, **kwargs)

    def test_complete_file_and_receipt_exclude_ephemeral_confirmation_url(self):
        self.transport.open.side_effect = [html(confirmation("ephemeral-secret")),
                                          Response(url=CONFIRM_ACTION + "?uuid=ephemeral-secret",
                                                   **{"Content-Length": len(PAYLOAD), "ETag": '"fixture"'})]
        result = self.run_download(expected_sha256=hashlib.sha256(PAYLOAD).hexdigest())
        self.assertEqual(result.path.read_bytes(), PAYLOAD)
        receipt_text = result.metadata_path.read_text(encoding="utf-8")
        self.assertEqual(json.loads(receipt_text)["url"], URL)
        self.assertNotIn("ephemeral-secret", receipt_text)
        self.assertFalse(result.path.with_name(result.path.name + ".part").exists())

    def test_interruption_resume_reparses_uuid_and_preserves_conditional_range(self):
        offset = 9
        initial = Response(PAYLOAD[:offset], **{"Content-Length": len(PAYLOAD), "ETag": '"fixture"'})
        self.transport.open.side_effect = [html(confirmation("uuid-first")), initial]
        with self.assertRaises(DownloadError) as caught:
            self.run_download()
        self.assertEqual(caught.exception.code, "incomplete")
        self.transport.reset_mock()
        resumed = Response(PAYLOAD[offset:], status=206, **{
            "Content-Length": len(PAYLOAD) - offset, "ETag": '"fixture"',
            "Content-Range": f"bytes {offset}-{len(PAYLOAD) - 1}/{len(PAYLOAD)}"})
        self.transport.open.side_effect = [html(confirmation("uuid-second")), resumed]
        result = self.run_download()
        self.assertEqual(result.resumed_bytes, offset)
        self.assertEqual(result.path.read_bytes(), PAYLOAD)
        stable, confirmed = [call.args[0] for call in self.transport.open.call_args_list]
        self.assertEqual(stable.full_url, URL)
        self.assertIn("uuid=uuid-second", confirmed.full_url)
        for request in (stable, confirmed):
            self.assertEqual(request.get_header("Range"), f"bytes={offset}-")
            self.assertEqual(request.get_header("If-range"), '"fixture"')
        receipt = result.metadata_path.read_text(encoding="utf-8")
        self.assertNotIn("uuid-first", receipt)
        self.assertNotIn("uuid-second", receipt)

    def test_download_still_enforces_streaming_limit_after_confirmation(self):
        self.transport.open.side_effect = [html(), Response(PAYLOAD + b"extra")]
        with self.assertRaises(DownloadError) as caught:
            self.run_download()
        self.assertEqual(caught.exception.code, "size_limit")
        destination = self.quota.resolve_path("training/source/public.json")
        self.assertFalse(destination.exists())
        self.assertLessEqual(destination.with_name(destination.name + ".part").stat().st_size, len(PAYLOAD))

    def test_restriction_error_is_saved_without_ephemeral_url(self):
        self.transport.open.side_effect = [html(confirmation("do-not-record")),
            urllib.error.HTTPError(CONFIRM_ACTION + "?uuid=do-not-record", 403, "Denied", {}, io.BytesIO())]
        with self.assertRaises(DownloadError) as caught:
            self.run_download()
        self.assertEqual(caught.exception.code, "drive_access_denied")
        receipt_text = caught.exception.metadata_path.read_text(encoding="utf-8")
        self.assertEqual(json.loads(receipt_text)["error"]["code"], "drive_access_denied")
        self.assertNotIn("do-not-record", receipt_text)

    def test_ephemeral_input_url_is_rejected_before_any_receipt_write(self):
        for url in (URL + "&uuid=secret-input", CONFIRM_ACTION + f"?id={FILE_ID}&export=download&confirm=t&uuid=secret-input"):
            with self.subTest(url=url):
                with self.assertRaises(DriveConfirmationError) as caught:
                    download(url, "training/source/public.json", quota=self.quota,
                             max_bytes=len(PAYLOAD), response_opener=open_drive_response)
                self.assertEqual(caught.exception.code, "drive_invalid_request")
                self.assertIsNone(caught.exception.metadata_path)
        self.transport.open.assert_not_called()
        self.assertEqual(list(self.quota.data_root.rglob("*.download.json")), [])
        self.assertFalse(self.quota.resolve_path("training/source/public.json.part").exists())


if __name__ == "__main__":
    unittest.main()
