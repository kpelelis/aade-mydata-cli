import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree as ET

from mydata_cli.api import (BASE_URLS, Client, ClientError, NoRedirect, Response,
                            continuation, parse_xml, xml_json)
from mydata_cli.cli import SUBMISSIONS, READS, inspect, main, parser, prepare

SUCCESS = b'<ResponseDoc><response><invoiceMark>123</invoiceMark><statusCode>Success</statusCode></response></ResponseDoc>'
FAILURE = b'<ResponseDoc><response><statusCode>Success</statusCode></response><response><statusCode>ValidationError</statusCode><errors><error><code>202</code><message>Invalid VAT</message></error></errors></response></ResponseDoc>'
PAGE = b'<RequestedDoc xmlns="urn:test"><continuationToken><nextPartitionKey>a+b&amp;c</nextPartitionKey><nextRowKey>r/1</nextRowKey></continuationToken><invoicesDoc/></RequestedDoc>'

class Capture(io.TextIOWrapper):
    def __init__(self):
        super().__init__(io.BytesIO(), encoding='utf-8')
    def value(self):
        self.flush()
        return self.buffer.getvalue()

def invoke(argv):
    out, err = Capture(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.value(), err.getvalue()

class ParsingTests(unittest.TestCase):
    def test_all_18_operations(self):
        self.assertEqual(len(SUBMISSIONS) + len(READS), 18)
        for command in [*SUBMISSIONS, *READS]:
            with self.subTest(command=command), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as cm:
                parser().parse_args([command, '--help'])
            self.assertEqual(cm.exception.code, 0)

    def test_cancel_post_no_body_and_production_path(self):
        args = parser().parse_args(['cancel-invoice', '--mark', '123', '--env', 'production'])
        self.assertEqual(prepare(args), ('POST', 'CancelInvoice', {'mark': '123'}, None))
        code, out, _ = invoke(['cancel-invoice', '--mark', '123', '--env', 'production', '--dry-run'])
        self.assertEqual(code, 0)
        self.assertIn('https://mydatapi.aade.gr/myDATA/CancelInvoice?mark=123', out.decode())

    def test_dates_filters_and_exact_casing(self):
        args = parser().parse_args(['request-vat-info', '--date-from', '2026-09-01', '--date-to', '30/09/2026', '--grouped-per-day', 'false'])
        self.assertEqual(prepare(args)[2], {'dateFrom': '01/09/2026', 'dateTo': '30/09/2026', 'GroupedPerDay': 'false'})

    def test_doc_parameter_spelling_is_explicit(self):
        for option, wire in [('--counter-vat-number', 'counterVatNumber'), ('--receiver-vat-number', 'receiverVatNumber')]:
            args = parser().parse_args(['request-docs', '--mark', '0', option, '012345678'])
            self.assertEqual(prepare(args)[2][wire], '012345678')

    def test_invalid_argument_combinations(self):
        cases = [['request-docs', '--mark', '0', '--next-row-key', 'r'],
                 ['request-docs', '--mark', '9', '--max-mark', '8'],
                 ['request-docs', '--mark', '0', '--all-pages'],
                 ['get-delivery-note-status', '--qr-url', 'https://example.test', '--issuer-vat-number', '123'],
                 ['request-my-income', '--date-from', '2026-09-30', '--date-to', '2026-09-01']]
        for argv in cases:
            with self.subTest(argv=argv):
                self.assertEqual(invoke(argv)[0], 2)

    def test_argparse_rejects_invalid_values(self):
        cases = [['request-docs', '--mark', '-1'], ['request-docs', '--mark', str(2**63)],
                 ['request-docs', '--mark', '0', '--timeout', 'nan'],
                 ['request-my-income', '--date-from', '2026-02-30', '--date-to', '2026-03-01']]
        for argv in cases:
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                parser().parse_args(argv)
            self.assertEqual(cm.exception.code, 2)

    def test_submission_roots_and_byte_preservation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.xml'
            for command, (_, root) in SUBMISSIONS.items():
                if root is None:
                    continue
                data = ET.tostring(ET.Element(root), encoding='utf-16', xml_declaration=True)
                path.write_bytes(data)
                args = parser().parse_args([command, '--file', str(path)])
                self.assertEqual(prepare(args)[3], data)
            path.write_text('<Wrong/>')
            self.assertEqual(invoke(['send-invoices', '--file', str(path), '--dry-run'])[0], 2)

    def test_dry_run_needs_no_credentials_and_redacts(self):
        with patch.dict(os.environ, {'MYDATA_USER_ID': 'private-user', 'MYDATA_SUBSCRIPTION_KEY': 'private-key'}):
            code, out, _ = invoke(['request-docs', '--mark', '0', '--dry-run'])
        self.assertEqual(code, 0)
        self.assertNotIn(b'private', out)

    def test_missing_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(invoke(['request-docs', '--mark', '0'])[0], 2)

    def test_bad_environment(self):
        with patch.dict(os.environ, {'MYDATA_ENV': 'bad'}):
            self.assertEqual(invoke(['request-docs', '--mark', '0'])[0], 2)

class XMLTests(unittest.TestCase):
    def test_escaped_xml_response_wrapper(self):
        for payload, expected in [(SUCCESS, 0), (FAILURE, 4), (PAGE, 0)]:
            wrapper = ET.Element('{http://schemas.microsoft.com/2003/10/Serialization/}string')
            wrapper.text = payload.decode()
            root, code, errors = inspect(Response(200, ET.tostring(wrapper)))
            self.assertEqual(code, expected)
            self.assertNotEqual(root.tag, wrapper.tag)
            if payload == PAGE:
                self.assertEqual(continuation(root), ('a+b&c', 'r/1'))
        self.assertEqual(inspect(Response(200, b'<string>Service unavailable</string>'))[1], 3)

    def test_errors_on_http_200_and_partial_success(self):
        root, code, errors = inspect(Response(200, FAILURE), True)
        self.assertEqual(code, 4)
        self.assertIn('202: Invalid VAT', errors)
        self.assertEqual(inspect(Response(200, SUCCESS), True)[1], 0)

    def test_unexpected_response(self):
        self.assertEqual(inspect(Response(200, b'<html/>'), True)[1], 3)
        self.assertEqual(inspect(Response(200, b'not xml'))[1], 3)
        self.assertEqual(inspect(Response(401, b'Unauthorized'))[1], 3)

    def test_entity_protection_in_multiple_encodings(self):
        for encoding in ['utf-8', 'utf-16']:
            data = f'<?xml version="1.0" encoding="{encoding}"?><!DOCTYPE x [<!ENTITY a "abc">]><x>&a;</x>'.encode(encoding)
            with self.assertRaises(ClientError):
                parse_xml(data)

    def test_continuation_namespace_and_completeness(self):
        self.assertEqual(continuation(parse_xml(PAGE)), ('a+b&c', 'r/1'))
        with self.assertRaises(ClientError):
            continuation(parse_xml(b'<r><continuationToken><nextRowKey>x</nextRowKey></continuationToken></r>'))

    def test_json_preserves_precision_order_and_namespace(self):
        value = xml_json(parse_xml(b'<r xmlns="urn:x"><n>9007199254740993</n><n>001.20</n></r>'))
        self.assertEqual(value['tag'], '{urn:x}r')
        self.assertEqual([c['text'] for c in value['children']], ['9007199254740993', '001.20'])

class TransportTests(unittest.TestCase):
    def test_get_retries_and_post_never_retries(self):
        for method, count in [('GET', 3), ('POST', 1)]:
            opener = Mock()
            opener.open.side_effect = URLError('secret-do-not-log')
            client = Client('test', 'user', 'key', opener=opener, sleep=Mock())
            with self.assertRaises(ClientError) as cm:
                client.request(method, 'CancelInvoice', {'mark': '1'})
            self.assertEqual(opener.open.call_count, count)
            self.assertNotIn('secret', str(cm.exception))

    def test_retry_503_then_success(self):
        opener = Mock()
        response = Mock(status=200)
        response.read.return_value = SUCCESS
        opener.open.side_effect = [HTTPError('https://example.test', 503, '', {'Retry-After': '1'}, io.BytesIO(b'unavailable')), contextlib.nullcontext(response)]
        sleep = Mock()
        client = Client('test', 'user', 'key', opener=opener, sleep=sleep)
        self.assertEqual(client.request('GET', 'RequestDocs', {}).status, 200)
        sleep.assert_called_once_with(1)

    def test_header_injection_rejected(self):
        with self.assertRaises(ClientError):
            Client('test', 'user\r\nX: evil', 'key')

    def test_redirect_blocked(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.test'))

class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.requests, cls.responses = [], []
        owner = cls
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.respond()
            def do_POST(self):
                self.respond()
            def respond(self):
                body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
                owner.requests.append((self.command, self.path, dict(self.headers), body))
                status, payload = owner.responses.pop(0)
                self.send_response(status)
                self.end_headers()
                self.wfile.write(payload)
            def log_message(self, *args):
                pass
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.requests.clear()
        self.responses.clear()
        self.env = patch.dict(os.environ, {'MYDATA_USER_ID': 'test-user', 'MYDATA_SUBSCRIPTION_KEY': 'test-key'})
        self.base = patch.dict(BASE_URLS, {'test': f'http://127.0.0.1:{self.server.server_port}'})
        self.env.start()
        self.base.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.base.stop)

    def test_real_http_post_headers_body_and_error_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'invoice.xml'
            data = b'<InvoicesDoc xmlns="http://www.aade.gr/myDATA/invoice/v1.0"/>'
            path.write_bytes(data)
            self.responses.append((200, FAILURE))
            code, out, err = invoke(['send-invoices', '--file', str(path)])
        self.assertEqual(code, 4)
        self.assertEqual(out, FAILURE)
        method, url, headers, body = self.requests[0]
        self.assertEqual((method, url, body), ('POST', '/SendInvoices', data))
        headers = {k.lower(): v for k, v in headers.items()}
        self.assertEqual(headers['aade-user-id'], 'test-user')
        self.assertEqual(headers['ocp-apim-subscription-key'], 'test-key')
        self.assertEqual(headers['content-type'], 'application/xml')
        self.assertIn('Invalid VAT', err)

    def test_two_pages_and_url_encoding(self):
        self.responses.extend([(200, PAGE), (200, b'<RequestedDoc/>')])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'pages'
            code, out, _ = invoke(['request-docs', '--mark', '0', '--all-pages', '--page-dir', str(path)])
            self.assertEqual(code, 0)
            manifest = json.loads(out)
            self.assertTrue(manifest['complete'])
            self.assertEqual(len(manifest['pages']), 2)
            self.assertEqual((path / 'page-00001.xml').read_bytes(), PAGE)
            self.assertEqual(json.loads((path / 'manifest.json').read_bytes()), manifest)
        query = parse_qs(urlsplit(self.requests[1][1]).query)
        self.assertEqual(query, {'mark': ['0'], 'nextPartitionKey': ['a+b&c'], 'nextRowKey': ['r/1']})

    def test_repeat_and_page_limit_preserve_partial_results(self):
        for maximum, pages in [(10, [PAGE, PAGE]), (1, [PAGE])]:
            with self.subTest(maximum=maximum), tempfile.TemporaryDirectory() as tmp:
                self.responses.extend((200, page) for page in pages)
                code, out, _ = invoke(['request-docs', '--mark', '0', '--all-pages', '--page-dir', str(Path(tmp)/'pages'), '--max-pages', str(maximum)])
                self.assertEqual(code, 5)
                self.assertFalse(json.loads(out)['complete'])
                self.assertIsNotNone(json.loads(out)['next'])

    def test_http_error_json_retains_body(self):
        self.responses.append((401, b'Unauthorized'))
        code, out, _ = invoke(['request-docs', '--mark', '0', '--format', 'json'])
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out)['rawBody'], 'Unauthorized')

    def test_atomic_output_file(self):
        self.responses.append((200, SUCCESS))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'response.xml'
            code, out, _ = invoke(['cancel-invoice', '--mark', '1', '--output', str(path)])
            self.assertEqual((code, out, path.read_bytes()), (0, b'', SUCCESS))
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_cancel_no_retry_on_503(self):
        self.responses.append((503, b'Unavailable'))
        self.assertEqual(invoke(['cancel-invoice', '--mark', '1'])[0], 3)
        self.assertEqual(len(self.requests), 1)

if __name__ == '__main__':
    unittest.main()
