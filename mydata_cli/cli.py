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
from .api import (BASE_URLS, Client, ClientError, PolicyError, environment_read_only, build_url, business_errors,
                  continuation, local_name, parse_xml, xml_json)

from .contracts import SUBMISSIONS, READS, PAGED, PARAMS, EXPECTED_ROOTS
from .records import envelope


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
    schema = commands.add_parser("schema", help="offline machine-readable CLI contract")
    schema.add_argument("--command", dest="schema_command", choices=sorted([*SUBMISSIONS, *READS]))
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
        sub.add_argument("--format", choices=("xml", "json", "records"), default="xml")
        policy = sub.add_mutually_exclusive_group()
        policy.add_argument("--read-only", action="store_true", help="explicitly enforce read-only network access")
        if command in SUBMISSIONS:
            policy.add_argument("--allow-writes", action="store_true", help="opt in to writes unless MYDATA_READ_ONLY locks them")
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
        if not args.page_dir or args.output:
            raise ClientError("--all-pages requires --page-dir and does not accept --output.")
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


def inspect(response, needs_status=False, endpoint=None):
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
    name = local_name(root.tag)
    expected = EXPECTED_ROOTS.get(endpoint, ()) if endpoint else tuple(
        n for names in EXPECTED_ROOTS.values() for n in names)
    if name not in {*expected, "ResponseDoc"}:
        return root, 3, ["Unexpected XML response root for this operation."]
    if (root.text or "").strip() or any((e.tail or "").strip() for e in root):
        return root, 3, ["Unexpected text in structured XML response."]
    # Status enums are case sensitive. Missing/duplicate/unknown values are protocol errors.
    statuses = [e for e in root.iter() if local_name(e.tag) == "statusCode"]
    known = {"Success", "ValidationError", "TechnicalError", "XMLSyntaxError"}
    if any((e.text or "").strip() not in known for e in statuses):
        return root, 3, ["Unknown or empty response statusCode."]
    if name == "ResponseDoc":
        responses = list(root)
        if not responses or any(local_name(e.tag) != "response" or len(
            [c for c in e if local_name(c.tag) == "statusCode"]) != 1 for e in responses):
            return root, 3, ["Incomplete ResponseDoc; every response needs exactly one statusCode."]
    elif len(statuses) > 1:
        return root, 3, ["Duplicate response statusCode."]
    failures = business_errors(root)
    if failures:
        return root, 4, failures
    if endpoint and name not in expected:
        return root, 3, ["Success response does not match the requested operation."]
    if (needs_status or name == "GenerateGroupQRCodeResponse") and not statuses:
        return root, 3, ["Submission response has no statusCode; outcome cannot be confirmed."]
    if name in ("GetDeliveryNoteStatusResponse", "DeliveryNoteStatusResponse"):
        required = ("invoiceMark", "status", "dispatchTimestamp")
        if any(len([e for e in root if local_name(e.tag) == field and (e.text or "").strip()]) != 1
               for field in required):
            return root, 3, ["Delivery status response is missing required fields."]
    if name == "RequestedDoc":
        allowed = {"continuationToken", "invoicesDoc", "cancelledInvoicesDoc",
                   "incomeClassificationsDoc", "expensesClassificationsDoc", "paymentMethodsDoc"}
        names = [local_name(e.tag) for e in root]
        if any(n not in allowed for n in names) or len(names) != len(set(names)):
            return root, 3, ["Unexpected or duplicate document response collection."]
        for collection in root:
            if local_name(collection.tag) == "invoicesDoc" and any(
                local_name(e.tag) != "invoice" for e in collection):
                return root, 3, ["Unexpected element in invoicesDoc."]
    try:
        continuation(root)
    except ClientError as exc:
        return root, 3, [str(exc)]
    return root, 0, []


def run_pages(args, client, endpoint, params):
    args.page_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    manifest = {"schemaVersion": "1.0", "command": args.command, "endpoint": endpoint,
                "environment": args.env, "format": args.format, "complete": False, "pages": [],
                "next": None, "errors": [], "exitCode": 0}
    cursor = (params.get("nextPartitionKey"), params.get("nextRowKey"))
    seen = {cursor} if all(cursor) else set()
    if all(cursor):
        manifest["next"] = dict(zip(("nextPartitionKey", "nextRowKey"), cursor))
    code = 0
    try:
        for number in range(1, args.max_pages + 1):
            response = client.request("GET", endpoint, params)
            name = f"page-{number:05d}.xml"
            write_atomic(args.page_dir / name, response.body)
            manifest["pages"].append({"file": name, "httpStatus": response.status})
            root, code, errors = inspect(response, endpoint=endpoint)
            if args.format != "xml":
                converted = f"page-{number:05d}.json"
                write_atomic(args.page_dir / converted, json_bytes(response_output(
                    args, response, root, code, errors)))
                manifest["pages"][-1]["dataFile"] = converted
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
        code = 6 if isinstance(exc, PolicyError) else 5
        manifest["errors"] = [str(exc)]
    except OSError:
        code = 2
        manifest["errors"] = ["Could not save a page; export is incomplete."]
    except KeyboardInterrupt:
        code = 130
        manifest["errors"] = ["Export interrupted; results are incomplete."]
    finally:
        manifest["exitCode"] = code
        write_atomic(args.page_dir / "manifest.json", json_bytes(manifest))
    emit(json_bytes(manifest))
    for error in manifest.get("errors", []):
        print(error, file=sys.stderr)
    return code


def response_output(args, response, root, code, errors):
    if args.format == "records":
        return envelope(root, args.command, args.env, response.status, code, errors)
    result = {"httpStatus": response.status, "errors": errors,
              "document": xml_json(root) if root is not None else None}
    if root is None:
        result["rawBody"] = response.body.decode("utf-8", errors="replace")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "schema":
            from .discovery import command_schema
            emit(json_bytes(command_schema(parser(), args.schema_command)))
            return 0
        locked = environment_read_only()
        read_only = locked or args.read_only or not getattr(args, "allow_writes", False)
        if args.command in SUBMISSIONS and read_only and not args.dry_run:
            raise PolicyError("Write blocked: read-only is the default. MYDATA_READ_ONLY=1 cannot be overridden by flags.")
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
        client = Client(args.env, user, key, args.timeout, args.retries, read_only=read_only)
        if getattr(args, "all_pages", False):
            return run_pages(args, client, endpoint, params)
        response = client.request(method, endpoint, params, body)
        root, code, errors = inspect(response, needs_status=method == "POST", endpoint=endpoint)
        if args.format in ("json", "records"):
            emit(json_bytes(response_output(args, response, root, code, errors)), args.output)
        else:
            emit(response.body, args.output)
        for error in errors:
            print(error, file=sys.stderr)
        return code
    except ClientError as exc:
        code = 6 if isinstance(exc, PolicyError) else 5 if str(exc).startswith("Network request failed") else 2
        if getattr(args, "format", None) in ("json", "records"):
            emit(json_bytes(envelope(None, args.command, args.env, None, code, [str(exc)])))
        print(f"mydata: {exc}", file=sys.stderr)
        return code
    except OSError:
        if getattr(args, "format", None) in ("json", "records"):
            emit(json_bytes(envelope(None, args.command, args.env, None, 2, ["Local file I/O failure."])))
        print("mydata: Could not read/write a local file or stream. Check paths and permissions.", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("mydata: Interrupted; a submitted request may already have reached AADE.", file=sys.stderr)
        return 130


def read_only_main(argv=None):
    """Dedicated entry point whose flags cannot opt in to writes."""
    previous = os.environ.get("MYDATA_READ_ONLY")
    os.environ["MYDATA_READ_ONLY"] = "1"
    try:
        return main(argv)
    finally:
        if previous is None:
            os.environ.pop("MYDATA_READ_ONLY", None)
        else:
            os.environ["MYDATA_READ_ONLY"] = previous
