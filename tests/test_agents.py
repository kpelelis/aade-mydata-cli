"""Synthetic fixtures only; no credentials or responses from real accounts."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from xml.etree import ElementTree as ET

from mydata_cli.api import Client, PolicyError, Response
from mydata_cli.cli import inspect, parser
from mydata_cli.contracts import READS, SUBMISSIONS, EXPECTED_ROOTS
from mydata_cli.discovery import command_schema
from mydata_cli.records import envelope
from test_cli import invoke, PAGE, FAILURE, SUCCESS

INVOICE = b'''<RequestedDoc xmlns="http://www.aade.gr/myDATA/invoice/v1.0">
<invoicesDoc><invoice><mark>9007199254740993</mark><uid>synthetic-id</uid>
<issuer><vatNumber>000000000</vatNumber><country>GR</country></issuer>
<counterpart><vatNumber>000000001</vatNumber></counterpart>
<invoiceHeader><series>EXAMPLE</series><aa>001</aa><issueDate>2025-01-10</issueDate>
<invoiceType>1.1</invoiceType><currency>EUR</currency></invoiceHeader>
<invoiceSummary><totalNetValue>100.00</totalNetValue><totalVatAmount>24.00</totalVatAmount>
<totalGrossValue>124.00</totalGrossValue></invoiceSummary></invoice></invoicesDoc>
<cancelledInvoicesDoc><cancelledInvoice><invoiceMark>1</invoiceMark><cancellationMark>2</cancellationMark>
</cancelledInvoice></cancelledInvoicesDoc></RequestedDoc>'''


class PolicyTests(unittest.TestCase):
    def test_default_blocks_every_submission_before_file_read_or_client(self):
        with patch('mydata_cli.cli.Client') as client:
            for command, (_, root) in SUBMISSIONS.items():
                args = ['--file', 'does-not-exist.xml'] if root else ['--mark', '1']
                code, out, _ = invoke([command, *args, '--format', 'records'])
                self.assertEqual(code, 6, command)
                self.assertEqual(json.loads(out)['exitCode'], 6)
            client.assert_not_called()

    def test_environment_lock_wins_over_write_flag(self):
        with patch.dict(os.environ, {'MYDATA_READ_ONLY': '1'}), patch('mydata_cli.cli.Client') as client:
            code, out, _ = invoke(['cancel-invoice', '--mark', '1', '--allow-writes', '--format', 'records'])
            self.assertEqual(code, 6)
            self.assertFalse(json.loads(out)['success'])
            client.assert_not_called()

    def test_transport_blocks_post_unknown_method_and_get_disguised_write(self):
        opener = Mock()
        client = Client('test', 'synthetic-user', 'synthetic-key', opener=opener)
        for method, endpoint, body in [('POST', 'CancelInvoice', None), ('GET', 'CancelInvoice', None),
                                       ('DELETE', 'RequestDocs', None), ('GET', 'RequestDocs', b'<x/>'),
                                       ('GET', '../CancelInvoice', None)]:
            with self.subTest(method=method, endpoint=endpoint), self.assertRaises(PolicyError):
                client.request(method, endpoint, {}, body)
        opener.open.assert_not_called()

    def test_transport_environment_lock_even_for_direct_opt_in(self):
        opener = Mock()
        client = Client('test', 'synthetic-user', 'synthetic-key', read_only=False, opener=opener)
        with patch.dict(os.environ, {'MYDATA_READ_ONLY': 'true'}), self.assertRaises(PolicyError):
            client.request('POST', 'CancelInvoice', {'mark': '1'})
        opener.open.assert_not_called()

    def test_dry_run_is_allowed_under_lock_without_network(self):
        with patch.dict(os.environ, {'MYDATA_READ_ONLY': '1'}), patch('mydata_cli.cli.Client') as client:
            code, out, _ = invoke(['cancel-invoice', '--mark', '1', '--dry-run'])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)['method'], 'POST')
            client.assert_not_called()

    def test_invalid_lock_value_fails_closed(self):
        with patch.dict(os.environ, {'MYDATA_READ_ONLY': 'maybe'}), patch('mydata_cli.cli.Client') as client:
            self.assertEqual(invoke(['request-docs', '--mark', '0'])[0], 6)
            client.assert_not_called()


class ReadOnlyEntryPointTests(unittest.TestCase):
    def test_readonly_entry_point_cannot_be_overridden_and_restores_environment(self):
        import contextlib
        import io
        from mydata_cli.cli import read_only_main
        from test_cli import Capture
        with patch.dict(os.environ, {'MYDATA_READ_ONLY': '0'}), patch('mydata_cli.cli.Client') as client:
            with contextlib.redirect_stdout(Capture()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(read_only_main(['cancel-invoice', '--mark', '1', '--allow-writes']), 6)
            self.assertEqual(os.environ['MYDATA_READ_ONLY'], '0')
            client.assert_not_called()


class DiscoveryTests(unittest.TestCase):
    def test_offline_schema_and_filters(self):
        with patch.dict(os.environ, {}, clear=True), patch('mydata_cli.cli.Client') as client:
            code, out, _ = invoke(['schema'])
            self.assertEqual(code, 0)
            data = json.loads(out)
            self.assertEqual(len(data['commands']), 18)
            client.assert_not_called()
            code, out, _ = invoke(['schema', '--command', 'request-docs'])
            self.assertEqual(len(json.loads(out)['commands']), 1)

    def test_metadata_matches_runtime_arguments_and_side_effects(self):
        data = command_schema(parser())
        for command in data['commands']:
            props = command['inputSchema']['properties']
            name = command['name']
            self.assertEqual(command['requiresWriteOptIn'], name in SUBMISSIONS)
            self.assertEqual(command['httpMethod'], 'GET' if name in READS else 'POST')
            self.assertIn('records', props['format']['enum'])
            if name == 'request-docs':
                self.assertIn('mark', command['inputSchema']['required'])
                self.assertEqual(command['wireParameters']['date-from'], 'dateFrom')
            if name == 'get-delivery-note-status':
                self.assertIn({'oneOf': [{'required': ['mark']}, {'required': ['qr-url']}]}, command['inputSchema']['allOf'])

    def test_schema_does_not_echo_environment_values(self):
        with patch.dict(os.environ, {'MYDATA_USER_ID': 'never-output-user', 'MYDATA_SUBSCRIPTION_KEY': 'never-output-key', 'MYDATA_ENV': 'production'}):
            text = json.dumps(command_schema(parser()))
            self.assertNotIn('never-output', text)
            data = command_schema(parser(), 'request-docs')
            self.assertEqual(data['commands'][0]['inputSchema']['properties']['env']['default'], 'test')


class ResponseValidationTests(unittest.TestCase):
    def test_text_in_known_response_is_not_empty_success(self):
        self.assertEqual(inspect(Response(200, b'<RequestedDoc>Service error</RequestedDoc>'), endpoint='RequestDocs')[1], 3)

    def test_wrong_endpoint_root_and_unknown_xml_fail(self):
        for xml in [b'<Unexpected/>', b'<RequestedVatInfo/>', b'<html/>', SUCCESS]:
            self.assertEqual(inspect(Response(200, xml), endpoint='RequestDocs')[1], 3)

    def test_all_read_roots_allow_empty_collection_responses(self):
        for endpoint in READS.values():
            root = EXPECTED_ROOTS[endpoint][0]
            body = '<invoiceMark>1</invoiceMark><status>Registered</status><dispatchTimestamp>2025-01-10T00:00:00</dispatchTimestamp>' if endpoint == 'GetDeliveryNoteStatus' else ''
            self.assertEqual(inspect(Response(200, f'<{root}>{body}</{root}>'.encode()), endpoint=endpoint)[1], 0)

    def test_business_error_response_is_valid_for_reads(self):
        self.assertEqual(inspect(Response(200, FAILURE), endpoint='RequestDocs')[1], 4)

    def test_unknown_duplicate_and_missing_statuses_fail(self):
        cases = [b'<ResponseDoc/>', b'<ResponseDoc><response/></ResponseDoc>',
                 b'<ResponseDoc><response><statusCode>Surprise</statusCode></response></ResponseDoc>',
                 b'<ResponseDoc><response><statusCode>Success</statusCode><statusCode>Success</statusCode></response></ResponseDoc>']
        for payload in cases:
            self.assertEqual(inspect(Response(200, payload), endpoint='CancelInvoice')[1], 3)

    def test_bad_continuation_fails_even_without_all_pages(self):
        for token in ['<nextRowKey>r</nextRowKey>', '<nextPartitionKey/><nextRowKey/>',
                      '<nextPartitionKey>p</nextPartitionKey><nextRowKey>r</nextRowKey><nextRowKey>r2</nextRowKey>']:
            data = f'<RequestedDoc><continuationToken>{token}</continuationToken></RequestedDoc>'.encode()
            self.assertEqual(inspect(Response(200, data), endpoint='RequestDocs')[1], 3)

    def test_wrong_doc_children_do_not_become_empty_success(self):
        for xml in [b'<RequestedDoc><invoice/></RequestedDoc>',
                    b'<RequestedDoc><invoicesDoc><wrong/></invoicesDoc></RequestedDoc>',
                    b'<RequestedDoc><invoicesDoc/><invoicesDoc/></RequestedDoc>']:
            self.assertEqual(inspect(Response(200, xml), endpoint='RequestDocs')[1], 3)

    def test_wrapped_failure_and_pagination(self):
        for data, code in [(FAILURE, 4), (PAGE, 0)]:
            wrapper = ET.Element('string')
            wrapper.text = data.decode()
            root, actual, errors = inspect(Response(200, ET.tostring(wrapper)), endpoint='RequestDocs')
            self.assertEqual(actual, code)
            record = envelope(root, 'request-docs', 'test', 200, actual, errors)
            self.assertFalse(record['complete'])
            if code == 0:
                self.assertEqual(record['pagination']['next']['nextRowKey'], 'r/1')


class RecordsTests(unittest.TestCase):
    def test_invoice_projection_preserves_identifiers_decimals_and_nulls(self):
        root, code, errors = inspect(Response(200, INVOICE), endpoint='RequestDocs')
        result = envelope(root, 'request-docs', 'test', 200, code, errors)
        invoice = result['records'][0]
        self.assertEqual(invoice['mark'], '9007199254740993')
        self.assertEqual(invoice['number'], '001')
        self.assertEqual(invoice['totals']['gross'], '124.00')
        self.assertEqual(invoice['issuer']['vatNumber'], '000000000')
        self.assertIsNone(invoice['issuer']['name'])
        self.assertIsNone(invoice['cancellationMark'])
        self.assertEqual(invoice['direction'], 'received')
        self.assertEqual(result['records'][1]['kind'], 'cancelledInvoicesDoc')
        self.assertIsInstance(result['records'][1]['fields']['cancelledInvoice'], list)

    def test_empty_records_and_generic_rows_are_always_arrays(self):
        for payload in [b'<RequestedDoc/>', b'<RequestedVatInfo><VatInfo><Mark>0001</Mark><Vat301>1.20</Vat301></VatInfo></RequestedVatInfo>']:
            root, code, errors = inspect(Response(200, payload))
            output = envelope(root, 'request-vat-info', 'test', 200, code, errors)
            self.assertIsInstance(output['records'], list)
            if output['records']:
                self.assertEqual(output['records'][0]['fields']['Mark'], ['0001'])

    def test_protocol_errors_do_not_project_invoice_data(self):
        root = ET.fromstring(INVOICE)
        self.assertEqual(envelope(root, 'request-docs', 'test', 200, 3, ['error'])['records'], [])

    def test_cli_records_and_paginated_output(self):
        with patch.dict(os.environ, {'MYDATA_USER_ID': 'synthetic-user', 'MYDATA_SUBSCRIPTION_KEY': 'synthetic-key'}), patch('mydata_cli.cli.Client') as client:
            client.return_value.request.return_value = Response(200, INVOICE)
            code, out, _ = invoke(['request-docs', '--mark', '0', '--format', 'records'])
            self.assertEqual(code, 0)
            self.assertEqual(len(json.loads(out)['records']), 2)
            client.return_value.request.side_effect = [Response(200, PAGE), Response(200, INVOICE)]
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/'pages'
                code, out, _ = invoke(['request-docs', '--mark', '0', '--all-pages', '--page-dir', str(path), '--format', 'records'])
                manifest = json.loads(out)
                self.assertEqual(code, 0)
                self.assertTrue(manifest['complete'])
                self.assertEqual(len(manifest['pages']), 2)
                converted = json.loads((path/manifest['pages'][1]['dataFile']).read_text())
                self.assertEqual(converted['records'][0]['totals']['gross'], '124.00')
                self.assertEqual((path/'page-00002.xml').read_bytes(), INVOICE)

    def test_initial_resume_token_retained_if_first_request_fails(self):
        from mydata_cli.api import ClientError
        with patch.dict(os.environ, {'MYDATA_USER_ID': 'synthetic-user', 'MYDATA_SUBSCRIPTION_KEY': 'synthetic-key'}), patch('mydata_cli.cli.Client') as client, tempfile.TemporaryDirectory() as tmp:
            client.return_value.request.side_effect = ClientError('Network request failed.')
            code, out, _ = invoke(['request-docs', '--mark', '0', '--next-partition-key', 'p', '--next-row-key', 'r', '--all-pages', '--page-dir', str(Path(tmp)/'pages'), '--format', 'records'])
            result = json.loads(out)
            self.assertEqual(code, 5)
            self.assertEqual(result['next'], {'nextPartitionKey': 'p', 'nextRowKey': 'r'})
            self.assertFalse(result['complete'])

    def test_partial_export_contains_failure_and_nonzero_manifest_code(self):
        with patch.dict(os.environ, {'MYDATA_USER_ID': 'synthetic-user', 'MYDATA_SUBSCRIPTION_KEY': 'synthetic-key'}), patch('mydata_cli.cli.Client') as client, tempfile.TemporaryDirectory() as tmp:
            client.return_value.request.side_effect = [Response(200, PAGE), Response(200, b'<Surprise/>')]
            code, out, _ = invoke(['request-docs', '--mark', '0', '--all-pages', '--page-dir', str(Path(tmp)/'pages'), '--format', 'records'])
            result = json.loads(out)
            self.assertEqual(code, 3)
            self.assertFalse(result['complete'])
            self.assertEqual(result['exitCode'], 3)
            self.assertEqual(len(result['pages']), 2)

    def test_missing_credentials_and_file_errors_are_structured(self):
        with patch.dict(os.environ, {}, clear=True):
            code, out, _ = invoke(['request-docs', '--mark', '0', '--format', 'records'])
            self.assertEqual(code, 2)
            self.assertFalse(json.loads(out)['success'])
        with patch.dict(os.environ, {'MYDATA_READ_ONLY': '0'}):
            code, out, _ = invoke(['send-invoices', '--allow-writes', '--file', '/nonexistent/synthetic.xml', '--format', 'records'])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(out)['exitCode'], 2)
