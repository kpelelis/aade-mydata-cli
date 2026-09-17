"""Operation metadata shared by the CLI, transport policy and discovery command."""
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


READ_ENDPOINTS = frozenset(READS.values())
EXPECTED_ROOTS = {
    "RequestDocs": ("RequestedDoc",),
    "RequestTransmittedDocs": ("RequestedDoc",),
    "RequestMyIncome": ("RequestedBookInfo",),
    "RequestMyExpenses": ("RequestedBookInfo",),
    "RequestVatInfo": ("RequestedVatInfo",),
    "RequestE3Info": ("RequestedE3Info",),
    "GetDeliveryNoteStatus": ("GetDeliveryNoteStatusResponse", "DeliveryNoteStatusResponse"),
    "RequestGroupQRDetails": ("RequestGroupQRDetailsResponse",),
    **{endpoint: ("ResponseDoc",) for endpoint, _ in SUBMISSIONS.values()},
    "GenerateGroupQRCode": ("GenerateGroupQRCodeResponse",),
}
