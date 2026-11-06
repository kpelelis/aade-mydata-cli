# Local runtime

Install the CLI from this repository with Python 3.10+ as described in the root [README.md](../../../../README.md):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
```

The launcher prefers the repository's `.venv/bin/mydata-readonly`, then an installed `mydata-readonly` on PATH. It sets `MYDATA_READ_ONLY=1` and executes that dedicated read-only entry point. The launcher does not load shell startup files or manage credentials. Supply `MYDATA_USER_ID` and `MYDATA_SUBSCRIPTION_KEY` securely in the agent process environment; never commit or print them. For production and test use the corresponding AADE credentials and pass `--env` explicitly.

The root `AGENT_GUIDE.md` covers CLI usage, pagination, error handling and aggregation cautions. Read `XML_REFERENCE.md` when XML structure matters. Schema and help commands are offline.

A remote or cloud agent needs its own CLI installation and credential access; this skill does not bundle either. Do not silently upgrade or fetch unrelated code during a query.
