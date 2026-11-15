# Testing

The project has two test layers plus packaging and portability checks. The
guiding rule is: **a modelling change is verified against a hand calculation,
not against the shape "looking right".**

## Layers

| Layer | Marker / file | Needs SolidWorks | Purpose |
|---|---|---|---|
| Unit | default | No | Pure geometry, selectors, validation, packaging, tool forwarding, modularity guards |
| Integration | `@pytest.mark.solidworks` | Yes, running and licensed | Build real features and compare measured volume/mass/mates with hand calculations |
| Portability | `tests/test_server_portability.py` | No (blocks pywin32) | Server starts off Windows, lists 88 tools, fails loud |
| Packaging | `tests/test_packaging.py` | No | `pyproject.toml`, `server.json`, `__version__` and README marker agree |
| Modularity | `tests/test_modularity.py` | No | Mixins composed, no helper shadowing, 88 unique tools, no cross-mixin imports |
| Selftest | `solidworks-mcp --selftest` | Yes | User-machine smoke test with small parts and hand calculations |

## Commands

```powershell
uv sync --extra dev

uv run pytest -m "not solidworks"          # fast layer, no SolidWorks
uv run pytest                              # all tests, needs SolidWorks
uv run pytest -m solidworks                # integration only
uv run pytest tests/test_server_portability.py
uv run pytest --cov=solidworks_mcp --cov-report=term-missing
```

`pytest` defaults to `tests/` and adds `-ra` for a short summary. The
`solidworks` marker is declared in `pyproject.toml`.

## Coverage

- Statement + branch coverage is measured with `pytest-cov`.
- The CI floor is **35%** (`[tool.coverage.report] fail_under`).
- The current unit-layer baseline is about **37%**. Do not lower the floor to
  make a change pass; add a test instead.
- Integration tests raise coverage substantially but need a SolidWorks seat, so
  they are not part of CI.

## CI matrix

| Job | Runner | What it runs |
|---|---|---|
| Lint and format | Ubuntu | `ruff check src tests`, `ruff format --check src tests` |
| Type check | Ubuntu | `mypy` on the configured core modules |
| Unit tests (Windows) | Windows | `pytest -m "not solidworks"` with coverage XML artifact |
| Build package | Ubuntu | `uv build`, `twine check dist/*` |

All four jobs must pass before a PR is merged.

## Writing tests

### Pure unit tests

- Put pure tests next to the existing domain test file (`test_logic.py`,
  `test_mesh_tools.py`, `test_sketching.py`, ...).
- Use a `SolidWorksSession()` instance only for pure helpers; do not call
  `connect()`.
- Use `pytest.raises(SolidWorksError, match="...")` for refusals before
  SolidWorks is touched.
- Prefer exact geometric expectations and `pytest.approx` only for floating
  point tolerance.
- A new validation rule needs a positive test and at least one refusal test.
- Standard selection is pure: `_wizard_selection` is tested for the GB default,
  the ISO fallback and an unknown standard before SolidWorks is touched.

### Integration tests

- Mark with `@pytest.mark.solidworks`.
- Use the `part` fixture for parts and the `assembly` fixture for assemblies.
  The `part` fixture asserts that no sketch was left under-defined.
- Compare volume, mass, bounding box or mate distance with an explicit hand
  calculation. Put the formula in the docstring or a comment.
- Close documents through the fixtures; do not leave parts open.
- If a test needs a saved component, use the `blocks` fixture rather than a
  machine-specific file.
- A feature that SolidWorks refuses should fail loud and leave the part as it
  was; assert both.

### Tool forwarding

`tests/test_logic.py::test_tool_forwards_its_arguments_in_order` parses every
async tool function under `src/solidworks_mcp/tools/` and checks that it delegates
to an existing session method with the same parameter order. Add a tool wrapper
and this test covers the wiring automatically.

### Modularity guards

`tests/test_modularity.py` fails if:

- a mixin is missing from `SolidWorksSession`;
- two mixins define the same helper name;
- a tool name is duplicated or the total is not 88;
- a mixin imports another mixin;
- `server.py` does not re-export every declared tool.

## Debugging a failure

1. Reproduce with the smallest command:
   `uv run pytest path::test_name -q`.
2. For an integration failure, run the same test with SolidWorks open and check
   whether a modal dialog is blocking (the 120-second call timeout reports it).
3. For a selector/geometry failure, add the measured value and the hand
   calculation to the assertion message.
4. For a portability failure on Windows, ensure the subprocess uses explicit
   UTF-8; the test does this deliberately.
5. Do not weaken an assertion to make a test pass; fix the code or document a
   genuine platform limitation.
