"""Versioned, compact response projections for agent consumption.

Identifiers and decimals remain strings. This is a convenience projection;
use --format json or raw XML when every XML detail matters.
"""
from .api import local_name, continuation

SCHEMA_VERSION = "1.0"


def child(node, name):
    return next((e for e in node if local_name(e.tag) == name), None) if node is not None else None


def value(node, name):
    element = child(node, name)
    return element.text if element is not None else None


def fields(node):
    """Every XML field maps to an array, including single occurrences."""
    result = {}
    for element in node:
        result.setdefault(local_name(element.tag), []).append(
            fields(element) if len(element) else element.text)
    return result


def party(node):
    return {key: value(node, key) for key in ("vatNumber", "country", "branch", "name")}


def invoice_record(node, command):
    header, summary = child(node, "invoiceHeader"), child(node, "invoiceSummary")
    return {
        "kind": "invoice",
        "direction": "received" if command == "request-docs" else "issued",
        "mark": value(node, "mark"), "uid": value(node, "uid"),
        "cancellationMark": value(node, "cancelledByMark"),
        "issueDate": value(header, "issueDate"), "series": value(header, "series"),
        "number": value(header, "aa"), "invoiceType": value(header, "invoiceType"),
        "currency": value(header, "currency"),
        "issuer": party(child(node, "issuer")),
        "counterpart": party(child(node, "counterpart")),
        "totals": {key: value(summary, xml) for key, xml in (
            ("net", "totalNetValue"), ("vat", "totalVatAmount"),
            ("gross", "totalGrossValue"), ("withheld", "totalWithheldAmount"),
            ("fees", "totalFeesAmount"), ("stampDuty", "totalStampDutyAmount"),
            ("otherTaxes", "totalOtherTaxesAmount"), ("deductions", "totalDeductionsAmount"))},
    }


def records(root, command):
    if root is None:
        return []
    if local_name(root.tag) == "RequestedDoc":
        result = []
        for element in root:
            name = local_name(element.tag)
            if name == "continuationToken":
                continue
            if name == "invoicesDoc":
                result.extend(invoice_record(inv, command) for inv in element if local_name(inv.tag) == "invoice")
            else:
                result.append({"kind": name, "fields": fields(element)})
        return result
    if local_name(root.tag) in ("RequestedBookInfo", "RequestedVatInfo", "RequestedE3Info", "ResponseDoc"):
        return [{"kind": local_name(e.tag), "fields": fields(e)} for e in root
                if local_name(e.tag) != "continuationToken"]
    return [{"kind": local_name(root.tag), "fields": fields(root)}]


def envelope(root, command, environment, http_status, code, errors):
    cursor = continuation(root) if root is not None and code == 0 else None
    return {
        "schemaVersion": SCHEMA_VERSION, "command": command, "environment": environment,
        "httpStatus": http_status, "success": code == 0, "exitCode": code,
        "complete": code == 0 and cursor is None,
        "pagination": {"hasMore": bool(cursor), "next": dict(zip(
            ("nextPartitionKey", "nextRowKey"), cursor)) if cursor else None},
        "errors": errors, "records": records(root, command) if root is not None and code in (0, 4) else [],
    }
