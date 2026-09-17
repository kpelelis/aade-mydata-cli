"""Documented myDATA operations exposed as argparse subcommands."""
import argparse
from datetime import datetime
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from xml.etree import ElementTree as ET

from . import __version__
from .api import (BASE_URLS, Client, ClientError, build_url, business_errors,
                  continuation, local_name, parse_xml, xml_json)

# command: (endpoint, XML root; None means no request body)
SUBMISSIONS = {
    "send-invoices": ("SendInvoices", "{http://www.aade.gr/myDATA/invoice/v1.0}InvoicesDoc"),
    "send-income-classification": ("SendIncomeClassification", "{https://www.aade.gr/myDATA/incomeClassificaton/v1.0}IncomeClassificationsDoc"),
    "send-expenses-classification": ("SendExpensesClassification", "{https://www.aade.gr/myDATA/expensesClassificaton/v1.0}ExpensesClassificationsDoc"),
    "send-payments-method": ("SendPaymentsMethod", "{https://www.aade.gr/myDATA/paymentMethod/v1.0}PaymentMethodsDoc"),
    "cancel-invoice": ("CancelInvoice", None),
    "register-transfer": ("RegisterTransfer", "Transport"),
    "confirm-delivery-outcome": ("ConfirmDeliveryOutcome", "ConfirmDeliveryOutcomeRequest"),
    "reject-delivery-note": ("RejectDeliveryNote", "RejectDeliveryNoteRequest"),
    "generate-group-qr-code": ("GenerateGroupQRCode", "GenerateGroupQRCodeRequest"),
    "confirm-delivery-return": ("ConfirmDeliveryReturn", "ConfirmDeliveryReturnRequest"),
}
READS = {
    "request-docs": "RequestDocs", "request-transmitted-docs": "RequestTransmittedDocs",
    "request-my-income": "RequestMyIncome", "request-my-expenses": "RequestMyExpenses",
    "request-vat-info": "RequestVatInfo", "request-e3-info": "RequestE3Info",
    "get-delivery-note-status": "GetDeliveryNoteStatus",
    "request-group-qr-details": "RequestGroupQRDetails",
}
PAGED = set(READS) - {"get-delivery-note-status", "request-group-qr-details"}
PARAMS = {
    "mark": "mark", "max_mark": "maxMark", "entity_vat_number": "entityVatNumber",
    "counter_vat_number": "counterVatNumber", "receiver_vat_number": "receiverVatNumber",
    "issuer_vat_number": "issuerVatNumber", "inv_type": "invType",
    "date_from": "dateFrom", "date_to": "dateTo", "grouped_per_day": "GroupedPerDay",
    "next_partition_key": "nextPartitionKey", "next_row_key": "nextRowKey",
    "qr_url": "qrUrl", "group_id": "groupId",
}


def mark(value):
    if not value.isascii() or not value.isdigit() or not 0 <= int(value) <= 2**63 - 1:
        raise argparse.ArgumentTypeError("MARK must be an integer between 0 and 9223372036854775807")
    return str(int(value))


def positive(value):
    try:
        number = int(value)
        if number > 0:
            return number
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("must be a positive integer")


def timeout(value):
    try:
        number = float(value)
        if math.isfinite(number) and number > 0:
            return number
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("must be a positive finite number")


def date(value):
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).strftime("%d/%m/%Y")
        except ValueError:
            pass
    raise argparse.ArgumentTypeError("use a valid YYYY-MM-DD or DD/MM/YYYY date")


def nonempty(value):
    if not value.strip():
        raise argparse.ArgumentTypeError("must not be empty")
    return value


def parser():
    p = argparse.ArgumentParser(description="AADE myDATA ERP API v2.0.2 command-line client.")
    p.add_argument("--version", action="version", version=__version__)
    commands = p.add_subparsers(dest="command", required=True)
    for command in list(SUBMISSIONS) + list(READS):
        endpoint = SUBMISSIONS[command][0] if command in SUBMISSIONS else READS[command]
        sub = commands.add_parser(command, help=endpoint, description=endpoint)
        sub.add_argument("--env", choices=BASE_URLS, default=os.getenv("MYDATA_ENV", "test"),
                         help="AADE environment (default MYDATA_ENV or test)")
        sub.add_argument("--timeout", type=timeout, default=30, help="per-request timeout in seconds")
        sub.add_argument("--retries", type=int, choices=range(0, 6), default=2,
                         help="GET retries only, 0-5 (default 2)")
        sub.add_argument("--dry-run", action="store_true", help="print request without credentials or network I/O")
        sub.add_argument("--output", type=Path, help="write response to file instead of stdout")
        sub.add_argument("--format", choices=("xml", "json"), default="xml")
        if command in SUBMISSIONS and SUBMISSIONS[command][1]:
            sub.add_argument("--file", required=True, help="XML file, or - for stdin")
        if command in PAGED:
            sub.add_argument("--all-pages", action="store_true", help="save all pages to a new --page-dir")
            sub.add_argument("--page-dir", type=Path, help="new directory for raw XML pages and manifest.json")
            sub.add_argument("--max-pages", type=positive, default=1000)
            sub.add_argument("--next-partition-key", type=nonempty)
            sub.add_argument("--next-row-key", type=nonempty)
            sub.add_argument("--entity-vat-number", type=nonempty)
            required_dates = command not in ("request-docs", "request-transmitted-docs")
            sub.add_argument("--date-from", type=date, required=required_dates)
            sub.add_argument("--date-to", type=date, required=required_dates)
            if command in ("request-vat-info", "request-e3-info"):
                sub.add_argument("--grouped-per-day", choices=("true", "false"))
            else:
                sub.add_argument("--inv-type", type=nonempty, help="invoice type parameter from AADE table 8.1; forwarded unchanged")
                counter = sub.add_mutually_exclusive_group()
                counter.add_argument("--counter-vat-number", type=nonempty)
                if not required_dates:
                    counter.add_argument("--receiver-vat-number", type=nonempty,
                                         help="alternative parameter spelling in PDF tables")
            if not required_dates:
                sub.add_argument("--mark", type=mark, required=True)
                sub.add_argument("--max-mark", type=mark)
        elif command == "cancel-invoice":
            sub.add_argument("--mark", type=mark, required=True)
            sub.add_argument("--entity-vat-number", type=nonempty)
        elif command == "get-delivery-note-status":
            identity = sub.add_mutually_exclusive_group(required=True)
            identity.add_argument("--mark", type=mark)
            identity.add_argument("--qr-url", type=nonempty)
            sub.add_argument("--issuer-vat-number", type=nonempty)
        elif command == "request-group-qr-details":
            sub.add_argument("--group-id", required=True, type=nonempty)
    return p


def prepare(args):
    if args.env not in BASE_URLS:
        raise ClientError("MYDATA_ENV must be test or production.")
    params = {wire: getattr(args, key) for key, wire in PARAMS.items()
              if getattr(args, key, None) is not None}
    if bool(params.get("nextPartitionKey")) != bool(params.get("nextRowKey")):
        raise ClientError("Supply both continuation keys together.")
    if "dateFrom" in params and "dateTo" in params:
        if datetime.strptime(params["dateFrom"], "%d/%m/%Y") > datetime.strptime(params["dateTo"], "%d/%m/%Y"):
            raise ClientError("date-from must not be after date-to.")
    if "maxMark" in params and int(params["maxMark"]) < int(params["mark"]):
        raise ClientError("max-mark must not be less than mark.")
    if params.get("qrUrl") and params.get("issuerVatNumber"):
        raise ClientError("issuer-vat-number is only allowed with mark.")
    if getattr(args, "all_pages", False):
        if not args.page_dir or args.output or args.format != "xml":
            raise ClientError("--all-pages requires --page-dir and raw XML (no --output/--format json).")
    elif getattr(args, "page_dir", None):
        raise ClientError("--page-dir requires --all-pages.")
    body = None
    if args.command in SUBMISSIONS:
        endpoint, root_tag = SUBMISSIONS[args.command]
        if root_tag:
            raw = sys.stdin.buffer.read() if args.file == "-" else Path(args.file).read_bytes()
            root = parse_xml(raw)
            if root.tag != root_tag:
                raise ClientError(f"Expected XML root {root_tag}, got {root.tag}.")
            body = raw  # Preserve namespaces, prefixes, declarations and payload bytes.
        return "POST", endpoint, params, body
    return "GET", READS[args.command], params, body


def write_atomic(path, data):
    """Create private result files; never leave a half-written response."""
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
            name = f.name
            f.write(data)
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def emit(data, output=None):
    if output:
        write_atomic(output, data)
    else:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def inspect(response, needs_status=False):
    if not 200 <= response.status < 300:
        return None, 3, [f"HTTP {response.status}"]
    try:
        root = parse_xml(response.body)
        # AADE's development service can serialize the XML document as an
        # escaped string. Inspect the inner document, retaining raw wire bytes.
        for _ in range(3):
            if local_name(root.tag) != "string":
                break
            root = parse_xml((root.text or "").strip())
        if local_name(root.tag) == "string":
            raise ClientError("Response has too many XML string wrappers.")
    except ClientError as exc:
        return None, 3, [str(exc)]
    if local_name(root.tag).lower() == "html":
        return root, 3, ["Expected an API XML response, received HTML."]
    failures = business_errors(root)
    if failures:
        return root, 4, failures
    responses = [e for e in root.iter() if local_name(e.tag) == "response"]
    if local_name(root.tag) == "ResponseDoc" and (not responses or any(
        not any(local_name(c.tag) == "statusCode" for c in e) for e in responses
    )):
        return root, 3, ["Incomplete ResponseDoc; an item is missing its statusCode."]
    if needs_status and not any(local_name(e.tag) == "statusCode" for e in root.iter()):
        return root, 3, ["Submission response has no statusCode; outcome cannot be confirmed."]
    return root, 0, []


def run_pages(args, client, endpoint, params):
    args.page_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    manifest = {"endpoint": endpoint, "environment": args.env, "complete": False, "pages": []}
    cursor = (params.get("nextPartitionKey"), params.get("nextRowKey"))
    seen = {cursor} if all(cursor) else set()
    code = 0
    try:
        for number in range(1, args.max_pages + 1):
            response = client.request("GET", endpoint, params)
            name = f"page-{number:05d}.xml"
            write_atomic(args.page_dir / name, response.body)
            manifest["pages"].append({"file": name, "httpStatus": response.status})
            root, code, errors = inspect(response)
            if code:
                manifest["errors"] = errors
                break
            cursor = continuation(root)
            manifest["next"] = dict(zip(("nextPartitionKey", "nextRowKey"), cursor)) if cursor else None
            if cursor is None:
                manifest["complete"] = True
                break
            if cursor in seen:
                raise ClientError("Repeated continuation token; stopped to avoid an infinite loop.")
            seen.add(cursor)
            params.update(manifest["next"])
        else:
            raise ClientError("Reached max-pages; results are incomplete. Resume with manifest continuation keys.")
    except ClientError as exc:
        code = 5
        manifest["errors"] = [str(exc)]
    finally:
        write_atomic(args.page_dir / "manifest.json", json_bytes(manifest))
    emit(json_bytes(manifest))
    for error in manifest.get("errors", []):
        print(error, file=sys.stderr)
    return code


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        method, endpoint, params, body = prepare(args)
        if args.dry_run:
            emit(json_bytes({"method": method, "url": build_url(BASE_URLS[args.env], endpoint, params),
                             "headers": {"aade-user-id": "<redacted>", "ocp-apim-subscription-key": "<redacted>"},
                             "body": ET.tostring(parse_xml(body), encoding="unicode") if body else None}), args.output)
            return 0
        user = os.getenv("MYDATA_USER_ID", "")
        key = os.getenv("MYDATA_SUBSCRIPTION_KEY", "")
        if not user or not key:
            raise ClientError("Set MYDATA_USER_ID and MYDATA_SUBSCRIPTION_KEY (AADE API credentials).")
        # Validate output destination before issuing a potentially mutating request.
        if args.output and (not args.output.parent.is_dir() or args.output.is_dir()):
            raise ClientError("Output must be a file in an existing directory.")
        client = Client(args.env, user, key, args.timeout, args.retries)
        if getattr(args, "all_pages", False):
            return run_pages(args, client, endpoint, params)
        response = client.request(method, endpoint, params, body)
        root, code, errors = inspect(response, needs_status=method == "POST")
        if args.format == "json":
            result = {"httpStatus": response.status, "errors": errors,
                      "document": xml_json(root) if root is not None else None}
            if root is None:
                result["rawBody"] = response.body.decode("utf-8", errors="replace")
            emit(json_bytes(result), args.output)
        else:
            emit(response.body, args.output)
        for error in errors:
            print(error, file=sys.stderr)
        return code
    except ClientError as exc:
        print(f"mydata: {exc}", file=sys.stderr)
        return 2 if not str(exc).startswith("Network request failed") else 5
    except OSError:
        print("mydata: Could not read/write a local file or stream. Check paths and permissions.", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("mydata: Interrupted; a submitted request may already have reached AADE.", file=sys.stderr)
        return 130
