"""Generate discovery metadata from the same argparse definitions used at runtime."""
import argparse
from . import __version__
from .contracts import SUBMISSIONS, READS, PAGED, PARAMS, EXPECTED_ROOTS


def command_schema(parser, selected=None):
    subcommands = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    commands = []
    for name in sorted([*READS, *SUBMISSIONS]):
        if selected and name != selected:
            continue
        sub = subcommands.choices[name]
        properties, required, constraints = {}, [], []
        for action in sub._actions:
            if action.dest == "help":
                continue
            flag = next(f for f in action.option_strings if f.startswith("--"))
            key = flag[2:]
            kind = "boolean" if isinstance(action, argparse._StoreTrueAction) else (
                "integer" if action.type is int or getattr(action.type, "__name__", "") == "positive" else
                "number" if getattr(action.type, "__name__", "") == "timeout" else "string")
            prop = {"type": kind, "description": action.help or key}
            if action.choices is not None:
                prop["enum"] = list(action.choices)
            if action.default is not None:
                prop["default"] = "test" if key == "env" else action.default
            converter = getattr(action.type, "__name__", "")
            if converter == "mark":
                prop.update(pattern="^[0-9]+$", description="Decimal integer string in [0, 9223372036854775807].")
            if converter == "positive":
                prop["minimum"] = 1
            if converter == "timeout":
                prop["exclusiveMinimum"] = 0
            if converter == "nonempty":
                prop["pattern"] = "\\S"
            if converter == "date":
                prop["description"] = "Valid calendar date in YYYY-MM-DD or DD/MM/YYYY; serialized DD/MM/YYYY."
            properties[key] = prop
            if action.required:
                required.append(key)
        for group in sub._mutually_exclusive_groups:
            keys = [a.option_strings[0][2:] for a in group._group_actions]
            if group.required:
                constraints.append({"oneOf": [{"required": [k]} for k in keys]})
            else:
                for i, a in enumerate(keys):
                    for b in keys[i+1:]:
                        constraints.append({"not": {"required": [a, b]}})
        input_schema = {"$schema": "https://json-schema.org/draft/2020-12/schema",
                        "type": "object", "properties": properties,
                        "required": required, "additionalProperties": False}
        dependencies = {}
        if name in PAGED:
            dependencies.update({"next-partition-key": ["next-row-key"],
                                 "next-row-key": ["next-partition-key"]})
            constraints.extend([
                {"if": {"properties": {"all-pages": {"const": True}}, "required": ["all-pages"]},
                 "then": {"required": ["page-dir"], "not": {"required": ["output"]}}},
                {"if": {"required": ["page-dir"]},
                 "then": {"properties": {"all-pages": {"const": True}}, "required": ["all-pages"]}},
            ])
        if name == "get-delivery-note-status":
            dependencies["issuer-vat-number"] = ["mark"]
        if dependencies:
            input_schema["dependentRequired"] = dependencies
        if constraints:
            input_schema["allOf"] = constraints
        endpoint = READS[name] if name in READS else SUBMISSIONS[name][0]
        commands.append({
            "name": name, "httpMethod": "GET" if name in READS else "POST",
            "endpoint": endpoint, "sideEffects": "none" if name in READS else "writesRemoteData",
            "requiresWriteOptIn": name in SUBMISSIONS, "supportsPagination": name in PAGED,
            "requestXmlRoot": SUBMISSIONS[name][1] if name in SUBMISSIONS else None,
            "responseRoots": list(EXPECTED_ROOTS[endpoint]), "inputSchema": input_schema,
            "wireParameters": {flag: PARAMS[flag.replace("-", "_")] for flag in properties
                               if flag.replace("-", "_") in PARAMS},
        })
    return {
        "schemaVersion": "1.0", "cliVersion": __version__, "commands": commands,
        "policy": {"default": "readOnly", "writeOptInFlag": "--allow-writes",
                   "environmentLock": "MYDATA_READ_ONLY=1", "lockOverridesFlags": True,
                   "dryRunUsesNetwork": False,
                   "boundary": "Process policy, not a sandbox against an agent able to edit code or environment."},
        "credentials": {"userIdEnvironment": "MYDATA_USER_ID", "subscriptionKeyEnvironment": "MYDATA_SUBSCRIPTION_KEY"},
        "environment": {"default": "test", "defaultOverride": "MYDATA_ENV", "explicitFlag": "--env"},
        "runtimeConstraints": ["date-from <= date-to", "max-mark >= mark", "MARK fits signed 64-bit integer",
                               "page-dir must not already exist", "timeout must be finite",
                               "Dates must be valid calendar dates", "Continuation keys must be supplied together"],
        "exitCodes": {"0": "success", "2": "invalid input/configuration or local I/O failure",
                      "3": "HTTP/protocol failure", "4": "AADE business failure",
                      "5": "network failure or incomplete pagination", "6": "read-only policy refusal",
                      "130": "interrupted; reconcile any possible submission"},
        "outputFormats": {"xml": "Original response bytes", "json": "Namespace-preserving XML tree",
                          "records": "Version 1.0 envelope with records array; identifiers and amounts stay strings"},
        "recordsEnvelope": {"schemaVersion": "string", "command": "string", "environment": "string",
                            "httpStatus": "integer|null", "success": "boolean", "exitCode": "integer",
                            "complete": "boolean", "pagination": {"hasMore": "boolean", "next": "object|null"},
                            "errors": "array<string>", "records": "array<object>"},
        "pagination": {"mode": "--all-pages --page-dir NEW_DIRECTORY",
                       "stdout": "manifest with complete, exitCode, next and pages",
                       "pageData": "raw XML always; dataFile additionally points to JSON for json/records formats"},
        "diagnostics": "stderr; runtime records/json errors also emit JSON. Argument syntax errors use stderr and exit 2.",
    }
