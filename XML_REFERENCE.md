# XML structure reference

This guide explains the XML consumed and returned by the CLI. It is a navigation aid for developers and agents, not a replacement for AADE's complete field restrictions or accounting rules. All examples in this repository are synthetic and intended for offline inspection.

## Source versions and validation boundary

The ERP API reference is the [June 2026 preofficial v2.0.2 PDF](https://www.aade.gr/sites/default/files/2026-06/myDATA%20API%20Documentation%20v2.0.2_preofficial_erp.pdf). Delivery operations and the structural field tables below were cross-checked against the [September 2026 delivery v2.0.2 PDF](https://www.aade.gr/sites/default/files/2026-09/myDATA%20API%20Documentation_DeliveryNote_v2.0.2_official_0.pdf) and [official v2.0.2 XSD archive](https://www.aade.gr/sites/default/files/2026-09/v2.0.2XSDs_0.zip), retrieved 2026-09-17. The archive contains variants; tables in this guide use the filenames explicitly named below. Do not silently mix schemas from different releases.

The CLI checks XML syntax and request root namespaces. It checks expected response root names, basic collection/status structure and continuation tokens. It does **not** validate the full XSD or calculate tax totals. Schema-valid XML can still violate AADE business rules; field presence, invoice type, issuer/recipient roles, authorizations and delivery state all matter.

## Namespaces, order and scalar values

| Prefix used here | Namespace URI | Applies to |
|---|---|---|
| `inv` | `http://www.aade.gr/myDATA/invoice/v1.0` | Invoices, invoice detail types and most retrieval envelopes |
| `icls` | `https://www.aade.gr/myDATA/incomeClassificaton/v1.0` | Income classifications |
| `ecls` | `https://www.aade.gr/myDATA/expensesClassificaton/v1.0` | Expense classifications |
| `pm` | `https://www.aade.gr/myDATA/paymentMethod/v1.0` | Standalone payment submissions |
| none | No namespace | ResponseDoc and delivery request roots |

Prefix names are arbitrary; namespace URIs are exact and case-sensitive. `http` versus `https` matters. The spelling `Classificaton` in both classification URIs is intentional. A default namespace applies to unprefixed child elements, but not to unprefixed attributes.

An element's namespace follows its declaration, not simply the namespace of its type. For example, `inv:incomeClassification` is an invoice element whose children use the income-classification namespace. Similarly, `pm:paymentMethodDetails` contains invoice-namespace payment-detail fields. See the invoice example for the first pattern.

XSD `sequence` defines element order. `minOccurs="0"` means schema-optional, not necessarily optional under every business rule. `maxOccurs="unbounded"` permits repeated sibling elements. `choice` means choose an allowed branch, not all branches.

- XML `issueDate` uses `YYYY-MM-DD`. Query-string dates use `DD/MM/YYYY`; the CLI converts supported input date formats.
- Decimal amounts use a dot, with no thousands separator. Preserve values as decimal strings; avoid binary floating-point arithmetic.
- MARK fields are integer identifiers. Their exact decimal strings may exceed JavaScript's safe integer range.
- Omit an absent optional element rather than inserting an empty number/date. Empty, missing and zero are different.
- Escape `&` as `&amp;` and `<` as `&lt;` in text. Build XML with an XML library, not string concatenation.
- Do not add DTDs or entities; the client rejects them.

## Invoice submissions: InvoicesDoc

`SendInvoices` accepts an invoice-namespace `InvoicesDoc` with one or more `invoice` children. [examples/invoice.xml](examples/invoice.xml) is a complete synthetic structural example, validated against the published XSD.

```text
inv:InvoicesDoc
  inv:invoice [1..*]
    uid?, mark?, cancelledByMark?, authenticationCode?, transmissionFailure?
    issuer?                  -> PartyType
    counterpart?             -> PartyType
    invoiceHeader            -> InvoiceHeaderType
    paymentMethods?          -> paymentMethodDetails [1..*]
    invoiceDetails [1..*]     -> InvoiceRowType (each sibling is one line)
    taxesTotals?             -> tax totals, when applicable
    invoiceSummary           -> InvoiceSummaryType
    qrCodeUrl?, downloadingInvoiceUrl?
    packingsDeclarations*, invoiceDeliveryStatus?, deliveryLifecycle?
```

This overview follows the official September invoice XSD order. Metadata such as MARK/UID and cancellation references is commonly populated by AADE; do not invent those values on new submissions. Issuer/recipient name and other nominally optional fields can be prohibited or required for particular invoice types. Use the field rules in ERP section 5.

A classification embedded in an invoice demonstrates the namespace boundary:

```xml
<inv:incomeClassification
    xmlns:inv="http://www.aade.gr/myDATA/invoice/v1.0"
    xmlns:icls="https://www.aade.gr/myDATA/incomeClassificaton/v1.0">
  <icls:classificationType>E3_561_001</icls:classificationType>
  <icls:classificationCategory>category1_1</icls:classificationCategory>
  <icls:amount>100.00</icls:amount>
</inv:incomeClassification>
```

This is a fragment, not a submission document. Invoice lines and summary classifications have different roles; do not duplicate or derive amounts without checking the relevant business rules.

## Standalone classifications

| Operation | Root | Repeated child | Identification | Classification branch |
|---|---|---|---|---|
| SendIncomeClassification | `icls:IncomeClassificationsDoc` | `incomeInvoiceClassification` | `invoiceMark`, optional service `classificationMark`, optional `entityVatNumber` | `transactionMode` **or** repeated `invoicesIncomeClassificationDetails` |
| SendExpensesClassification | `ecls:ExpensesClassificationsDoc` | `expensesInvoiceClassification` | Same identifiers | `transactionMode` **or** repeated `invoicesExpensesClassificationDetails` |

Each details element contains `lineNumber`, then repeated `incomeClassificationDetailData` or `expensesClassificationDetailData`. All these standalone elements use their classification document's namespace. `transactionMode` is 1 (rejection) or 2 (deviation); it is a meaningful operation, not a generic placeholder.

Income classification data orders its fields as `classificationType?`, `classificationCategory`, `amount`, `id?`. Expense classification data orders them as `classificationType?`, `classificationCategory?`, `amount`, `vatAmount?`, `vatCategory?`, `vatExemptionCategory?`, `id?`.

See [examples/income-classification.xml](examples/income-classification.xml) and [examples/expenses-classification.xml](examples/expenses-classification.xml). They demonstrate line-level structure, not universal accounting classifications.

**Version discrepancy:** the supplied June ERP PDF describes `postPerInvoice`; the September archive's `expensesClassification-v2.0.2.xsd` declares `classificationPostMode` after the choice, with values 0..1. The CLI does not translate between them. Neither example sets a posting mode. Consult the version appropriate to your integration and AADE's [per-invoice classification guidance](https://www.aade.gr/sites/default/files/2023-07/SendExpensesClassificationPostPerInvoiceGuidelines.pdf) before using that mode.

## Standalone payment methods

`pm:PaymentMethodsDoc` contains repeated `pm:paymentMethods`. Within each item, the sequence is:

1. `pm:invoiceMark` — target invoice.
2. `pm:paymentMethodMark?` — populated by the service.
3. `pm:entityVatNumber?` — represented entity, when applicable.
4. `pm:paymentMethodDetails` [1..*] — children use the **invoice** namespace: `inv:type`, `inv:amount`, then optional payment/signature fields.

This differs from `inv:paymentMethods` embedded in an invoice, where the wrapper and details elements belong to the invoice namespace. ERP section 4.2.4 adds POS-specific business requirements; a well-formed payment document alone does not establish validity.

`CancelInvoice` has **no XML body**: it is POST with `mark` and optionally `entityVatNumber` in the URL. The read-only executable blocks it.

## Delivery request bodies

These roots have **no target namespace**. The table lists their sequence; `?` is optional and `*` denotes optional repetition. Operational roles and lifecycle restrictions are in delivery specification section 3.2.

| Operation/root | Child elements in order |
|---|---|
| RegisterTransfer / `Transport` | `transferMark?` (service metadata), `qrUrl`, `transportDetail` |
| ConfirmDeliveryOutcome / `ConfirmDeliveryOutcomeRequest` | `qrUrl`, `outcome`, `deliveredWithoutRecipient?`, `deliveredPackaging*` |
| RejectDeliveryNote / `RejectDeliveryNoteRequest` | Exactly one of `qrUrl` or `invoiceMark`, then `rejectionReason?` (at most 150 characters in the XSD) |
| GenerateGroupQRCode / `GenerateGroupQRCodeRequest` | `qrUrls`, containing at least two `qrUrl` children |
| ConfirmDeliveryReturn / `ConfirmDeliveryReturnRequest` | `qrUrl` |

`outcome` is `FULL`, `PARTIAL`, or `NONE`. Transport details and packaging use types in `TransportTypes-v2.0.2.xsd`; those nested types are not interchangeable with the invoice header's planned transport fields. Refer to that schema for complete order/cardinality and to the PDF for roles and state transitions.

[Group QR example](examples/generate-group-qr-code.xml) and [delivery return example](examples/confirm-delivery-return.xml) use `example.invalid` URLs. They are offline templates, not usable QR codes.

The CLI uses GET query parameters for `GetDeliveryNoteStatus` (`mark` or `qrUrl`) and `RequestGroupQRDetails` (`groupId`). No request XML is needed for those CLI commands.

## Submission results: ResponseDoc

A typical no-namespace response has one `response` per submitted item. HTTP 200 does **not** mean every item succeeded.

```xml
<ResponseDoc>
  <response>
    <index>1</index>
    <invoiceMark>123456789</invoiceMark>
    <statusCode>Success</statusCode>
  </response>
  <response>
    <index>2</index>
    <errors>
      <error><message>Synthetic validation failure</message><code>202</code></error>
    </errors>
    <statusCode>ValidationError</statusCode>
  </response>
</ResponseDoc>
```

Identifier fields depend on the operation: `invoiceMark`, `classificationMark`, `cancellationMark`, `paymentMethodMark`, `transferMark`, `rejectMark`, `deliveryOutcomeMark`, or `deliveryReturnMark`. `index` associates a result with its input item. `statusCode` follows the success fields or errors branch and must be `Success`, `ValidationError`, `TechnicalError`, or `XMLSyntaxError`.

A batch can partially succeed. Save the full response and correlate results before any retry. The CLI returns exit 4 for business failures, including partial batches, and never retries POST automatically. [examples/submission-response.xml](examples/submission-response.xml) contains this synthetic mixed result.

GenerateGroupQRCode uses `GenerateGroupQRCodeResponse` instead, containing `groupQrUrl`, `qrUrlsCount`, `expiresAt`, and `statusCode`.

## Retrieved documents: RequestedDoc

RequestDocs and RequestTransmittedDocs return this invoice-namespace envelope. All the collections below are optional; a valid empty `RequestedDoc` is possible.

```text
inv:RequestedDoc
  continuationToken?
    nextPartitionKey
    nextRowKey
  invoicesDoc?
    invoice [0..*]             -> same AadeBookInvoiceType as submissions
  cancelledInvoicesDoc?
    cancelledInvoice [0..*]
      invoiceMark
      cancellationMark
      cancellationDate
  incomeClassificationsDoc?
    incomeInvoiceClassification [0..*]
  expensesClassificationsDoc?
    expensesInvoiceClassification [0..*]
  paymentMethodsDoc?
    paymentMethods [0..*]
```

The retrieval schema declares its collection items in the invoice namespace but uses imported classification/payment types for their children. Preserve namespace URIs from the actual response; matching solely by a guessed prefix is brittle.

When a `continuationToken` is present, pass **both** keys unchanged into the next request with the original filters. Keys are opaque strings, not numbers. URL-encode them; characters such as `+`, `&`, and `/` must survive round-tripping. A page without invoices can still have cancellations or another page. The client rejects missing, duplicated, empty or repeated continuation keys/tokens as appropriate.

[examples/requested-doc.xml](examples/requested-doc.xml) contains a synthetic invoice, a separate cancellation notice, and a continuation token. It is deliberately **not** a complete export.

## Other retrieval envelopes

| API | Root | Contents |
|---|---|---|
| RequestMyIncome / RequestMyExpenses | `RequestedBookInfo` | Book summary rows and optional continuation token; not individual invoices. Rows describe issue date/type/counterparty, amounts, count and MARK range. |
| RequestVatInfo | `RequestedVatInfo` | Optional continuation token, repeated `VatInfo`; fields include `Mark?`, `IsCancelled?`, required `IssueDate`, and optional `Vat301`, `Vat302`, etc. |
| RequestE3Info | `RequestedE3Info` | Optional continuation token, repeated `E3Info`; fields include `V_Afm?`, `V_Mark?`, `vBook?`, `IsCancelled?`, required `IssueDate`, `V_Class_Category?`, `V_Class_Type?`, `V_Class_Value?`. |
| GetDeliveryNoteStatus | `GetDeliveryNoteStatusResponse` in XSD; `DeliveryNoteStatusResponse` in PDF | `invoiceMark`, `status`, `dispatchTimestamp`, optional repeated `lifecycleHistory`. The client accepts both documented root spellings. |
| RequestGroupQRDetails | `RequestGroupQRDetailsResponse` | Optional `groupId`, `qrUrls/qrUrl*`, `qrUrlsCount`, `groupQrCreatorVatNumber`, `createdAt`, `expiresAt`, `statusCode`, `message` in XSD order. |

Case is significant: VAT uses `Mark` and `IssueDate`; invoice documents use `mark` and `issueDate`. Do not apply invoice-field paths to summary or VAT/E3 rows. The official archive does not provide a RequestedBookInfo schema under that name; use ERP section 6.3 rather than inventing an XSD filename or row wrapper.

## Escaped XML response wrappers

AADE can return the document as escaped text inside an XML `string` element, for example:

```xml
<string xmlns="http://schemas.microsoft.com/2003/10/Serialization/">&lt;RequestedDoc xmlns="http://www.aade.gr/myDATA/invoice/v1.0" /&gt;</string>
```

The client unwraps up to three layers for validation, errors, pagination and JSON conversion. `--format xml` retains the original bytes, including the wrapper. Do not interpret a `string` wrapper by itself as success or an empty document. [examples/wrapped-requested-doc.xml](examples/wrapped-requested-doc.xml) is a synthetic wrapper example; validate its inner document with the response XSD, not the outer serialization wrapper.

## Mapping invoice XML into records JSON

| Invoice-relative XML path | `--format records` field |
|---|---|
| `mark`, `uid`, `cancelledByMark` | `mark`, `uid`, `cancellationMark` |
| `invoiceHeader/issueDate` | `issueDate` |
| `invoiceHeader/series`, `invoiceHeader/aa` | `series`, `number` |
| `invoiceHeader/invoiceType`, `invoiceHeader/currency` | `invoiceType`, `currency` |
| `issuer/*`, `counterpart/*` | Party objects: `vatNumber`, `country`, `branch`, `name` |
| `invoiceSummary/totalNetValue`, `totalVatAmount`, `totalGrossValue` | `totals.net`, `totals.vat`, `totals.gross` |
| Other summary amounts | `totals.withheld`, `fees`, `stampDuty`, `otherTaxes`, `deductions` |

The projection does not include invoice lines or every optional field. Missing values become null; identifiers and amounts stay strings. `kind` and `source` are CLI metadata, not XML invoice fields. `source` identifies `received` or `transmitted` retrieval; a transmitted document can be a manually reported foreign purchase and must not automatically be treated as revenue. Non-invoice records use `kind` and a `fields` object with arrays for every XML child name. Use raw XML or `--format json` if you need namespaces, attributes or all nested details. See [AGENT_GUIDE.md](AGENT_GUIDE.md) for pagination and aggregation rules.

## Offline schema validation

Download and extract the official XSD archive into a local directory outside the repository, preserving its filenames and relative include/import relationships. If `xmllint` is installed:

```sh
xmllint --nonet --noout --schema /path/to/schemas/InvoicesDoc-v2.0.2.xsd examples/invoice.xml
xmllint --nonet --noout --schema /path/to/schemas/incomeClassification-v2.0.2.xsd examples/income-classification.xml
xmllint --nonet --noout --schema /path/to/schemas/expensesClassification-v2.0.2.xsd examples/expenses-classification.xml
xmllint --nonet --noout --schema /path/to/schemas/requestedInvoicesDoc-v2.0.2.xsd examples/requested-doc.xml
xmllint --nonet --noout --schema /path/to/schemas/response-v2.0.2.xsd examples/submission-response.xml
```

These commands are local only and do not contact AADE. Optional external XSD checking is not part of the dependency-free CLI runtime. Do not replace the installed schemas silently when AADE publishes a new version; review and retest against it.

## Core invoice field tables

These ordered tables are extracted from `InvoicesDoc-v2.0.2.xsd` in the September archive. Cardinality describes XSD presence only. Inline limits shown are not the complete restrictions of referenced types; use `SimpleTypes-v2.0.2.xsd` for enumerations and numeric constraints. A required field can still have context-specific restrictions.

### AadeBookInvoiceType

| Element, in order | XSD type | Cardinality | Inline limits |
|---|---|---|---|
| `uid` | `xs:string` | 0..1 | — |
| `mark` | `xs:long` | 0..1 | — |
| `cancelledByMark` | `xs:long` | 0..1 | — |
| `authenticationCode` | `xs:string` | 0..1 | — |
| `transmissionFailure` | `xs:byte` | 0..1 | minInclusive=1; maxInclusive=4 |
| `issuer` | `inv:PartyType` | 0..1 | — |
| `counterpart` | `inv:PartyType` | 0..1 | — |
| `invoiceHeader` | `inv:InvoiceHeaderType` | 1..1 | — |
| `paymentMethods` | `inline complex type` | 0..1 | — |
| `invoiceDetails` | `inv:InvoiceRowType` | 1..* | — |
| `taxesTotals` | `inline complex type` | 0..1 | — |
| `invoiceSummary` | `inv:InvoiceSummaryType` | 1..1 | — |
| `qrCodeUrl` | `xs:string` | 0..1 | — |
| `downloadingInvoiceUrl` | `xs:string` | 0..1 | — |
| `packingsDeclarations` | `inv:PackingsDeclaration` | 0..* | — |
| `invoiceDeliveryStatus` | `xs:byte` | 0..1 | minInclusive=1; maxInclusive=9 |
| `deliveryLifecycle` | `inline complex type` | 0..1 | — |

### PartyType

| Element, in order | XSD type | Cardinality | Inline limits |
|---|---|---|---|
| `vatNumber` | `xs:string` | 1..1 | maxLength=30 |
| `country` | `inv:CountryType` | 1..1 | — |
| `branch` | `xs:int` | 1..1 | — |
| `name` | `xs:string` | 0..1 | maxLength=200 |
| `address` | `inv:AddressType` | 0..1 | — |
| `documentIdNo` | `xs:string` | 0..1 | maxLength=100 |
| `supplyAccountNo` | `xs:string` | 0..1 | maxLength=100 |
| `countryDocumentId` | `inv:CountryType` | 0..1 | — |

### InvoiceHeaderType

| Element, in order | XSD type | Cardinality | Inline limits |
|---|---|---|---|
| `series` | `xs:string` | 1..1 | maxLength=50 |
| `aa` | `xs:string` | 1..1 | maxLength=50 |
| `issueDate` | `xs:date` | 1..1 | — |
| `invoiceType` | `inv:InvoiceType` | 1..1 | — |
| `vatPaymentSuspension` | `xs:boolean` | 0..1 | — |
| `currency` | `inv:CurrencyType` | 0..1 | — |
| `exchangeRate` | `inv:ExchangeRateType` | 0..1 | — |
| `correlatedInvoices` | `xs:long` | 0..* | — |
| `selfPricing` | `xs:boolean` | 0..1 | — |
| `dispatchDate` | `xs:date` | 0..1 | — |
| `dispatchTime` | `xs:time` | 0..1 | — |
| `vehicleNumber` | `xs:string` | 0..1 | maxLength=150 |
| `movePurpose` | `xs:int` | 0..1 | minInclusive=1; maxInclusive=20 |
| `fuelInvoice` | `xs:boolean` | 0..1 | — |
| `specialInvoiceCategory` | `inv:SpecialInvoiceCategoryType` | 0..1 | — |
| `invoiceVariationType` | `inv:InvoiceVariationType` | 0..1 | — |
| `otherCorrelatedEntities` | `inv:EntityType` | 0..* | — |
| `otherDeliveryNoteHeader` | `inv:OtherDeliveryNoteHeaderType` | 0..1 | — |
| `isDeliveryNote` | `xs:boolean` | 0..1 | — |
| `otherMovePurposeTitle` | `xs:string` | 0..1 | maxLength=150 |
| `thirdPartyCollection` | `xs:boolean` | 0..1 | — |
| `multipleConnectedMarks` | `xs:long` | 0..* | — |
| `tableAA` | `xs:string` | 0..1 | maxLength=50 |
| `totalCancelDeliveryOrders` | `xs:boolean` | 0..1 | — |
| `reverseDeliveryNote` | `xs:boolean` | 0..1 | — |
| `reverseDeliveryNotePurpose` | `inv:ReverseDeliveryNotePurposeType` | 0..1 | — |
| `toWeigh` | `xs:boolean` | 0..1 | — |
| `receivingNotePurpose` | `inv:ReceivingNotePurposeType` | 0..1 | — |
| `otherReceivingNotePurposeTitle` | `xs:string` | 0..1 | maxLength=150 |
| `nonObligatedRecipient` | `xs:boolean` | 0..1 | — |
| `withoutDigitalTransportTracking` | `xs:boolean` | 0..1 | — |

### InvoiceRowType

| Element, in order | XSD type | Cardinality | Inline limits |
|---|---|---|---|
| `lineNumber` | `xs:int` | 1..1 | minInclusive=1 |
| `recType` | `xs:int` | 0..1 | minInclusive=1; maxInclusive=7 |
| `TaricNo` | `xs:string` | 0..1 | length=10 |
| `itemCode` | `xs:string` | 0..1 | maxLength=50 |
| `itemDescr` | `xs:string` | 0..1 | maxLength=300 |
| `fuelCode` | `inv:FuelCodes` | 0..1 | — |
| `quantity` | `xs:decimal` | 0..1 | minExclusive=0 |
| `measurementUnit` | `inv:QuantityType` | 0..1 | — |
| `invoiceDetailType` | `inv:InvoiceDetailType` | 0..1 | — |
| `netValue` | `inv:AmountType` | 1..1 | — |
| `vatCategory` | `inv:VatType` | 1..1 | — |
| `vatAmount` | `inv:AmountType` | 1..1 | — |
| `vatExemptionCategory` | `inv:VatExemptionType` | 0..1 | — |
| `dienergia` | `inv:ShipType` | 0..1 | — |
| `discountOption` | `xs:boolean` | 0..1 | — |
| `withheldAmount` | `inv:AmountType` | 0..1 | — |
| `withheldPercentCategory` | `inv:WithheldType` | 0..1 | — |
| `stampDutyAmount` | `inv:AmountType` | 0..1 | — |
| `stampDutyPercentCategory` | `inv:StampDutyType` | 0..1 | — |
| `feesAmount` | `inv:AmountType` | 0..1 | — |
| `feesPercentCategory` | `inv:FeesType` | 0..1 | — |
| `otherTaxesPercentCategory` | `inv:OtherTaxesType` | 0..1 | — |
| `otherTaxesAmount` | `inv:AmountType` | 0..1 | — |
| `deductionsAmount` | `inv:AmountType` | 0..1 | — |
| `lineComments` | `xs:string` | 0..1 | maxLength=150 |
| `incomeClassification` | `icls:IncomeClassificationType` | 0..* | — |
| `expensesClassification` | `ecls:ExpensesClassificationType` | 0..* | — |
| `quantity15` | `xs:decimal` | 0..1 | minExclusive=0 |
| `otherMeasurementUnitQuantity` | `xs:int` | 0..1 | — |
| `otherMeasurementUnitTitle` | `xs:string` | 0..1 | maxLength=150 |
| `notVAT195` | `xs:boolean` | 0..1 | — |
| `movePurposeLine` | `xs:int` | 0..1 | minInclusive=1; maxInclusive=20 |
| `otherMovePurposeLineTitle` | `xs:string` | 0..1 | maxLength=150 |

### InvoiceSummaryType

| Element, in order | XSD type | Cardinality | Inline limits |
|---|---|---|---|
| `totalNetValue` | `inv:AmountType` | 1..1 | — |
| `totalVatAmount` | `inv:AmountType` | 1..1 | — |
| `totalWithheldAmount` | `inv:AmountType` | 1..1 | — |
| `totalFeesAmount` | `inv:AmountType` | 1..1 | — |
| `totalStampDutyAmount` | `inv:AmountType` | 1..1 | — |
| `totalOtherTaxesAmount` | `inv:AmountType` | 1..1 | — |
| `totalDeductionsAmount` | `inv:AmountType` | 1..1 | — |
| `totalGrossValue` | `inv:AmountType` | 1..1 | — |
| `incomeClassification` | `icls:IncomeClassificationType` | 0..* | — |
| `expensesClassification` | `ecls:ExpensesClassificationType` | 0..* | — |

### PaymentMethodDetailType

| Element, in order | XSD type | Cardinality | Inline limits |
|---|---|---|---|
| `type` | `xs:int` | 1..1 | minInclusive=1; maxInclusive=8 |
| `amount` | `inv:AmountType` | 1..1 | — |
| `paymentMethodInfo` | `xs:string` | 0..1 | — |
| `tipAmount` | `inv:AmountType` | 0..1 | — |
| `transactionId` | `xs:string` | 0..1 | — |
| `tid` | `xs:string` | 0..1 | maxLength=200 |
| `ProvidersSignature` | `inv:ProviderSignatureType` | 0..1 | — |
| `ECRToken` | `inv:ECRTokenType` | 0..1 | — |
