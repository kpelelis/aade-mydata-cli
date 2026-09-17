"""HTTP transport and lossless XML inspection helpers."""
from dataclasses import dataclass
import socket
import http.client
import time
import urllib.error
import urllib.parse
import urllib.request
from xml.etree import ElementTree as ET
from xml.parsers import expat

BASE_URLS = {
    "test": "https://mydataapidev.aade.gr",
    "production": "https://mydatapi.aade.gr/myDATA",
}


class ClientError(Exception):
    """An actionable client-side or protocol error."""


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes


class NoRedirect(urllib.request.HTTPRedirectHandler):
    # Do not forward subscription credentials or replay submissions on redirects.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, environment, user_id, subscription_key, timeout=30, retries=2,
                 opener=None, sleep=time.sleep):
        self.base_url = BASE_URLS[environment]
        for value in (user_id, subscription_key):
            if not value or any(ord(c) < 32 or ord(c) > 126 for c in value):
                raise ClientError("Credentials must be nonempty printable ASCII header values.")
        self.headers = {"aade-user-id": user_id,
                        "ocp-apim-subscription-key": subscription_key,
                        "Accept": "application/xml", "User-Agent": "aade-mydata-cli/0.1.0"}
        self.timeout, self.retries = timeout, retries
        self.opener = opener or urllib.request.build_opener(NoRedirect())
        self.sleep = sleep

    def request(self, method, endpoint, params, body=None):
        url = build_url(self.base_url, endpoint, params)
        headers = dict(self.headers)
        if body is not None:
            headers["Content-Type"] = "application/xml"
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        attempts = self.retries + 1 if method == "GET" else 1
        for attempt in range(attempts):
            try:
                with self.opener.open(req, timeout=self.timeout) as response:
                    return Response(response.status, response.read())
            except urllib.error.HTTPError as exc:
                result = Response(exc.code, exc.read())
                retry_after = exc.headers.get("Retry-After", "") if exc.headers else ""
                exc.close()
                if exc.code not in (429, 502, 503, 504) or attempt + 1 == attempts:
                    return result
                delay = min(int(retry_after), 60) if retry_after.isdigit() else 2 ** attempt
                self.sleep(delay)
            except (urllib.error.URLError, TimeoutError, socket.timeout, OSError, http.client.HTTPException) as exc:
                if attempt + 1 == attempts:
                    message = "Network request failed."
                    if method == "POST":
                        message += " Submission outcome is unknown; reconcile before resubmitting."
                    # Avoid interpolating exception text that might contain credentials.
                    raise ClientError(message) from exc
                self.sleep(2 ** attempt)
        raise AssertionError("unreachable")


def build_url(base_url, endpoint, params):
    query = urllib.parse.urlencode(params)
    return base_url + "/" + endpoint + ("?" + query if query else "")


def local_name(tag):
    return tag.rsplit("}", 1)[-1]


def parse_xml(data):
    """Reject DTD/entity declarations, including UTF-16 encoded declarations."""
    parser = expat.ParserCreate()

    def forbidden(*args):
        raise ClientError("XML DTDs and entity declarations are not supported.")

    parser.StartDoctypeDeclHandler = forbidden
    parser.EntityDeclHandler = forbidden
    parser.ExternalEntityRefHandler = forbidden
    try:
        parser.Parse(data, True)
        return ET.fromstring(data)
    except (expat.ExpatError, ET.ParseError, ValueError) as exc:
        raise ClientError("Invalid XML document.") from exc


def business_errors(root):
    failures = []
    for element in root.iter():
        if local_name(element.tag) == "statusCode" and (element.text or "").strip() != "Success":
            failures.append((element.text or "").strip() or "Empty statusCode")
        if local_name(element.tag) == "error":
            fields = {local_name(c.tag): (c.text or "").strip() for c in element}
            failures.append(": ".join(filter(None, (fields.get("code"), fields.get("message")))) or "API error")
    return failures


def continuation(root):
    tokens = [e for e in root.iter() if local_name(e.tag) == "continuationToken"]
    if not tokens:
        return None
    if len(tokens) != 1:
        raise ClientError("Response contains multiple continuation tokens.")
    fields = {local_name(c.tag): c.text or "" for c in tokens[0]}
    pair = (fields.get("nextPartitionKey", ""), fields.get("nextRowKey", ""))
    if pair == ("", ""):
        return None
    if not all(pair):
        raise ClientError("Response contains an incomplete continuation token.")
    return pair


def xml_json(element):
    """Explicit tree representation preserves namespaces, order, repeats and strings."""
    result = {"tag": element.tag}
    if element.attrib:
        result["attributes"] = dict(element.attrib)
    if element.text and element.text.strip():
        result["text"] = element.text
    if len(element):
        result["children"] = [xml_json(c) for c in element]
    if element.tail and element.tail.strip():
        result["tail"] = element.tail
    return result
