# AADE myDATA CLI

Python 3.10+ command-line client for the 18 operations listed in AADE's myDATA ERP API v2.0.2. No runtime dependencies. Submissions use your XML files; responses remain raw XML by default. This is an API transport client, not an invoice-generation or accounting system.

## Install and first request

Run from this directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/mydata --help
```

Alternatively, without installing anything: `python3 -m mydata_cli --help` from this directory. Replace `mydata` in the examples below with `.venv/bin/mydata` or activate the virtual environment.

Two **development API** credentials are required: the API username and subscription key. These are the `aade-user-id` and `ocp-apim-subscription-key` headers, respectively. They are not your TAXISnet login. Do not paste the key into chat or commit it to source control.

For the macOS default zsh terminal:

```sh
export MYDATA_USER_ID='your-dev-api-username'
read -rs 'MYDATA_SUBSCRIPTION_KEY?Development subscription key: '
export MYDATA_SUBSCRIPTION_KEY
echo
```

For bash, use `read -rs -p 'Development subscription key: ' MYDATA_SUBSCRIPTION_KEY` instead. Environment variables belong to that terminal and its child processes; setting them there does not set them in a separate Codex execution session.

A first read-only sandbox request:

```sh
.venv/bin/mydata request-transmitted-docs --env test --mark 0 --output dev-response.xml
```

An empty successful response is normal for a new account. `--mark 0` starts at the beginning; RequestDocs/RequestTransmittedDocs retrieve records whose MARK is **greater than** the given cursor. An explicit `--max-mark` bounds the upper end inclusively.

## Commands

All options follow the command. Each command has its own `--help`.

| CLI command | HTTP | API operation | Required input |
|---|---|---|---|
| `send-invoices` | POST | SendInvoices | `--file` |
| `send-income-classification` | POST | SendIncomeClassification | `--file` |
| `send-expenses-classification` | POST | SendExpensesClassification | `--file` |
| `send-payments-method` | POST | SendPaymentsMethod | `--file` |
| `cancel-invoice` | POST | CancelInvoice | `--mark` |
| `request-docs` | GET | RequestDocs | `--mark` |
| `request-transmitted-docs` | GET | RequestTransmittedDocs | `--mark` |
| `request-my-income` | GET | RequestMyIncome | `--date-from`, `--date-to` |
| `request-my-expenses` | GET | RequestMyExpenses | `--date-from`, `--date-to` |
| `request-vat-info` | GET | RequestVatInfo | `--date-from`, `--date-to` |
| `request-e3-info` | GET | RequestE3Info | `--date-from`, `--date-to` |
| `register-transfer` | POST | RegisterTransfer | `--file` |
| `confirm-delivery-outcome` | POST | ConfirmDeliveryOutcome | `--file` |
| `reject-delivery-note` | POST | RejectDeliveryNote | `--file` |
| `get-delivery-note-status` | GET | GetDeliveryNoteStatus | `--mark` or `--qr-url` |
| `generate-group-qr-code` | POST | GenerateGroupQRCode | `--file` |
| `request-group-qr-details` | GET | RequestGroupQRDetails | `--group-id` |
| `confirm-delivery-return` | POST | ConfirmDeliveryReturn | `--file` |

RequestGroupQRDetails uses the documented GET variant. CancelInvoice is POST with URL parameters and no XML body. `--issuer-vat-number` is available for delivery status with `--mark`; AADE requires it when the caller is not the issuer. Delegated ERP operations expose `--entity-vat-number` where documented; classification/payment delegation belongs inside the XML payload.

## Examples

```sh
# Offline request inspection; no credentials required.
mydata request-docs --mark 0 --dry-run
mydata send-invoices --file examples/invoice.xml --dry-run

# Both ISO dates and DD/MM/YYYY are accepted; wire dates use DD/MM/YYYY.
mydata request-my-income --date-from 2026-09-01 --date-to 2026-09-30 --format json
mydata request-vat-info --date-from 01/09/2026 --date-to 30/09/2026 --grouped-per-day true

# A single raw response, suitable for your XML tooling.
mydata request-transmitted-docs --mark 0 --output transmitted.xml

# Submit your completed XML file, or use --file - to read standard input.
mydata send-invoices --file invoice.xml --output submission-response.xml
mydata send-income-classification --file income.xml
mydata send-expenses-classification --file expenses.xml
mydata send-payments-method --file payments.xml

# Cancellation changes the selected environment's records.
mydata cancel-invoice --mark 123456789
mydata get-delivery-note-status --mark 123456789
mydata request-group-qr-details --group-id 'your-group-id'
```

The files in `examples/` are illustrative payload templates with fictional values. Replace identifiers, dates, VAT numbers, financial amounts and QR URLs before submitting. No example has been submitted to AADE.

## Pagination

The six paginated retrieval commands support `--all-pages`. The destination must be a **new directory**, preventing accidental mixing of exports:

```sh
mydata request-docs --mark 0 --all-pages --page-dir received-pages --max-pages 1000
```

Each raw response is written atomically to `page-00001.xml`, etc. `manifest.json` records page HTTP statuses, errors, the last continuation pair, and whether the export is complete. The manifest is also printed to stdout. Failed responses are retained for diagnosis. Page files are mode 0600 and the new directory is mode 0700 on POSIX systems.

The client resends the original filters plus both continuation keys, without changing the MARK cursor. Repeated/incomplete tokens and page limits fail explicitly; partial files remain available. Resume an interrupted export into a new directory using the same filters and the manifest's `next` keys:

```sh
mydata request-docs --mark 0 --next-partition-key 'partition' --next-row-key 'row' \
  --all-pages --page-dir received-pages-resumed
```

`--all-pages` requires raw XML and `--page-dir`; it cannot be combined with `--output` or JSON formatting. Files are paged separately instead of concatenating multiple XML documents into an invalid XML file.

## Environments, output and failures

- Default environment: `test` at `https://mydataapidev.aade.gr`.
- Production: `--env production` at `https://mydatapi.aade.gr/myDATA`.
- `MYDATA_ENV` can set the default; the command flag takes precedence. Use explicit `--env test` for sandbox checks if your terminal has a production default.
- Default timeout: 30 seconds per request. `--timeout` changes it.
- GET requests retry connection/read failures and HTTP 429/502/503/504 up to twice. `--retries 0` disables retries. Numeric Retry-After is honored up to 60 seconds; other retries use bounded exponential delays.
- POST requests are never retried automatically. After a connection failure, reconcile the result before resubmitting. A batch can contain both successful and failed items; do not blindly resend the whole batch.
- TLS verification is enabled. HTTP redirects are not followed, so credentials cannot be forwarded to a redirect target.
- XML documents escaped inside an AADE XML `string` wrapper are unwrapped for error detection, JSON conversion, and pagination. Raw XML output preserves the original response bytes.
- Diagnostics go to stderr. Raw response bytes go to stdout or `--output`, including responses reporting business failures.
- `--format json` wraps the HTTP status, errors, and a namespace-aware XML tree using `tag`, `attributes`, `text`, `children`, and `tail`. Repeated elements and ordering are preserved. Values stay strings to preserve MARKs, leading zeroes, and decimal precision. Non-XML errors are retained as `rawBody`.
- `--dry-run` outputs a redacted request description; payloads and query parameters remain visible. Namespace prefixes may be normalized for that preview; actual submissions preserve the original bytes.

| Exit | Meaning |
|---|---|
| 0 | Successful response or offline dry run |
| 2 | Invalid input/configuration or local file I/O failure |
| 3 | HTTP failure or malformed/unexpected response |
| 4 | AADE business failure, including HTTP 200 partial batch failures |
| 5 | Network failure or incomplete pagination |
| 130 | Interrupted; a submission might already have reached AADE |

## Scope and specification notes

The primary contract is the user-supplied [June 2026 preofficial ERP v2.0.2 PDF](https://www.aade.gr/sites/default/files/2026-06/myDATA%20API%20Documentation%20v2.0.2_preofficial_erp.pdf), particularly sections 4, 6 and 7. The seven delivery operations refer out to another document; their contracts were checked against the [September 2026 official delivery-note v2.0.2 PDF](https://www.aade.gr/sites/default/files/2026-09/myDATA%20API%20Documentation_DeliveryNote_v2.0.2_official_0.pdf), sections 3.2 and 5. XML root names/namespaces were cross-checked with the [official v2.0.2 XSD archive](https://www.aade.gr/sites/default/files/2026-09/v2.0.2XSDs_0.zip). Sources were retrieved on 2026-09-17. The newer ERP PDF is available on AADE's specifications page, but does not silently replace the requested June contract here.

Specific discrepancies are handled explicitly:

1. ERP section 4.1 describes cancellation generically as GET, while section 4.2.5 specifies POST. The CLI follows the operation-specific POST definition.
2. RequestDocs/RequestTransmittedDocs URLs use `counterVatNumber`, while their tables and notes use `receiverVatNumber`. Both are exposed as separate, mutually exclusive flags. Each sends exactly its named parameter; the client does not assume they are server-side aliases. Confirm the correct filter with your sandbox records.
3. VAT/E3 tables describe continuation keys when `GroupedPerDay=false`, but the following prose says they are ignored in that case. The CLI forwards your choice and follows continuation tokens actually returned. Verify the behavior against your account before depending on a large export.
4. The official classification namespaces contain `Classificaton` (without the second “i”). This spelling is intentional in the client.

The CLI validates query dates, identifiers, option combinations, XML well-formedness and the submission root/namespace. It rejects DTDs and entity declarations. It does **not** perform full XSD validation, calculate taxes, populate missing fields, or enforce the full invoice/delivery lifecycle business rules. AADE performs those checks. Author payloads using the published schemas or an existing ERP exporter. Output XML may contain confidential business data.

## Development and verification

```sh
python3 -m unittest discover -s tests -v
```

Tests exercise all commands, exact parameter casing and URL encoding, XML roots, date/argument validation, credential handling, HTTP-200 business failures, error response retention, large identifier preservation, retries, redirect blocking, and pagination against a local HTTP server. No credentials or AADE connections are needed. Authenticated sandbox verification remains a separate step.

## Repository privacy

Only source code, tests, documentation and synthetic XML examples belong in this repository. Credentials, API responses and business exports are local data and must not be committed. The ignore rules exclude XML outside `examples/`, JSON, CSV, spreadsheets, logs and environment files. Review the staged diff before every push; ignore rules do not remove files already tracked by Git. All example identities are fictional placeholders.
