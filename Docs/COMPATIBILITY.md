# Compatibility

**English** | [简体中文](zh-CN/COMPATIBILITY.md)

## Supported environment

| Component | Supported | Notes |
|---|---|---|
| Operating system | Windows | COM automation; the server starts on other platforms but tool calls fail loud |
| SOLIDWORKS | 2026 (3DEXPERIENCE R2026x) tested | API calls used exist since SOLIDWORKS 2020 SP2, but 2020–2025 are untested |
| Python | 3.11+ | Local validation used 3.12; CI uses the runner's available 3.11+ interpreter |
| MCP SDK | `mcp>=1.26,<2` | `mcp` 2.x renamed `FastMCP`; a migration is required before relaxing the pin |
| pywin32 | `>=306` (Windows only) | Installed by the `sys_platform == 'win32'` marker |
| Part template | Y-up | Z-up templates are refused with an actionable message |
| Modelling standard | GB default; ISO explicit fallback | See `Docs/MODELING-STANDARDS.md` |
| Units | mm and degrees at the tool boundary | Converted to metres/radians inside the COM layer |

## Selftest

With SOLIDWORKS running, from this checkout:

```powershell
uv sync
uv run solidworks-mcp --selftest
```

The selftest reports the SOLIDWORKS release, language, templates and units, then
builds small parts and an assembly, compares each with a hand calculation and
closes them unsaved. Run it before reporting a compatibility problem.

If you are using the **upstream** PyPI package rather than this fork, the
equivalent command is `uvx solidworks-mcp --selftest`; that command does not
install this fork.

## Known compatibility limits

- Only SOLIDWORKS 2026 is verified in this fork.
- The server attaches to a **running** SOLIDWORKS instance; it does not launch
  one.
- Early binding is mandatory on the tested build; the generated `gen_py`
  wrappers must match the installed typelib.
- A Z-up part template is refused; the tools build in the Y-up frame.
- The server makes no network calls and stores no credentials.
- Integration tests require a licensed SOLIDWORKS seat and are not run in CI.

## Reporting compatibility

Open a **Compatibility report** issue and paste the full selftest output,
whether it passed or failed. Include:

- SOLIDWORKS year, service pack and language;
- Windows version;
- Python version;
- the exact `uv run` or `uvx` command used;
- the selftest output and any dialog that appeared.

For a bug rather than a compatibility question, use the bug report template and
include the smallest tool call that reproduces it.

## API change policy

- Tool names and argument names are treated as public API.
- Additive changes are minor releases; breaking changes are major releases.
- The `SolidWorksSession` class is an implementation detail, but its public
  methods are kept stable for scripts in `scripts/` where practical.
- The MCP server identity remains `solidworks-mcp`; this fork does not claim the
  upstream PyPI or MCP Registry identity.
