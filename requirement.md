### Requirement 1: Allow CliSubCommand with default value in serialization mode

- **Location**: `pydantic_settings/sources/providers/cli.py` — `_sort_arg_fields` method (line ~538)
- **Description**: `_sort_arg_fields` unconditionally raises `SettingsError` when a `CliSubCommand` field has a default value. However, `CliApp.serialize` creates a synthetic model (`CliSerialize`) where all fields — including subcommand fields — have their actual values set as defaults. This causes `test_cli_serialize_ordering` to fail with `SettingsError: subcommand argument CliSerialize.command has a default value`.
- **Contract**: When `self._is_serialize_args` is `True` (i.e., the root parser is a `_CliInternalArgSerializer` instance), `_sort_arg_fields` must NOT raise an error for subcommand fields that have a default value. In all other modes the existing validation should remain.
- **Acceptance**: `tests/test_source_cli.py::test_cli_serialize_ordering` passes.

---

### Requirement 2: Only serialize non-default field values in `_serialized_args`

- **Location**: `pydantic_settings/sources/providers/cli.py` — `_get_cli_default_value` (line ~1109) and/or `_serialized_args` (line ~1148)
- **Description**: `CliApp.serialize` is expected to return only the CLI arguments that differ from the field's original default. Currently, `_get_cli_default_value` returns the actual model value as the argparse default for every field during serialization, so `env_vars` contains all fields (including ones at their original default). `_serialized_args` then emits all of them, causing `test_cli_serialize_non_default_values` to fail: it expects `['--non_default_val', '456']` but gets `['--default_val', '123', '--non_default_val', '456']`.
- **Contract**: For a field during serialization, `_get_cli_default_value` must return `CLI_SUPPRESS` when the actual model value equals the field's original default (i.e., `field_info.default`). It should return the actual value only when the field is originally required (no default) or when the actual value differs from the original default. This way, argparse's parsed namespace will contain `CLI_SUPPRESS` for unchanged-default fields, and `_serialized_args` will omit them from output.
- **Acceptance**: `tests/test_source_cli.py::test_cli_serialize_non_default_values` passes.

---

### Requirement 3: Skip auto-parsing in `CliSettingsSource.__init__` when a custom root_parser is provided

- **Location**: `pydantic_settings/sources/providers/cli.py` — `__init__` around line 261
- **Description**: When `CliSettingsSource` is constructed with an external `root_parser` argument (not `None`), the `__init__` still auto-parses `sys.argv` if `cli_parse_args` is `True` (from the model's `model_config`). `test_cli_app_with_separate_parser` creates `CliSettingsSource(Cfg, root_parser=parser)` where `Cfg.model_config = SettingsConfigDict(cli_parse_args=True)`. The test comment states "The actual parsing of command line argument should not happen here." The test then manually parses later via `CliApp.run(Cfg, cli_args=parsed_args, cli_settings_source=cli_settings)`. Because `sys.argv` contains pytest's own arguments during the test run, the immediate auto-parse causes `SystemExit: 2`.
- **Contract**: The auto-parse block at lines 261–268 must only execute when the internal parser is being used (i.e., `root_parser` was `None` and `self._root_parser` is an instance of `_CliInternalArgParser` created internally). When the caller supplies a custom `root_parser`, initialization should set up the argument definitions on that parser but must NOT call `_parse_args` / `_load_env_vars` automatically.
- **Acceptance**: `tests/test_source_cli.py::test_cli_app_with_separate_parser` passes.

---

### Requirement 4: Handle Windows-style paths (backslash characters) in CLI alias-path field decoding

- **Location**: `pydantic_settings/sources/providers/cli.py` and/or `pydantic_settings/sources/providers/env.py` / `pydantic_settings/sources/base.py` — `prepare_field_value` / `decode_complex_value`
- **Description**: `test_cli_decoding` constructs `PATH_A_STR = str(PureWindowsPath(Path.cwd()))`, which produces a path string containing backslashes (e.g., `C:\Users\...`). When a `BaseSettings` model has fields with `AliasPath` validation aliases pointing into a list (append-action CLI argument), the collected list value is passed through `decode_complex_value` which calls `json.loads`. A Windows path string is not valid JSON (`\U`, `\s`, etc. are invalid JSON escape sequences), so this raises `JSONDecodeError`. The test expects that raw path strings are accepted without JSON decoding when the CLI source collects them via append action (i.e., each item is already a plain string, not encoded JSON).
- **Contract**: In `prepare_field_value` for CLI sources, when the field has `NoDecode` in its metadata, or when the raw value from CLI is a list of plain strings (already parsed by argparse's append action and not a JSON-encoded string), `decode_complex_value` must not be called. The value should be passed directly for validation. Specifically, values that are already Python lists (not strings) must bypass `json.loads`. Additionally, `ForceDecode`/`NoDecode` annotations on individual fields aliased via `AliasPath` must be respected: mixing `ForceDecode` and `NoDecode` across different `AliasPath` fields for the same CLI argument must raise a `SettingsError`.
- **Acceptance**: `tests/test_source_cli.py::test_cli_decoding` passes.

---

### Requirement 5: Add new feature documentation to `docs/index.md`

- **Location**: `docs/index.md`
- **Description**: The target test report includes doc-example tests at `code/docs/index.md:2467-2491`, `code/docs/index.md:2497-2529`, and `code/docs/index.md:2536-2565`, which correspond to code examples beyond the current end of the file (currently 2445 lines). These examples document the new `cli_shortcuts` and `CliApp.serialize` features introduced in `main.py` and `cli.py`. Additionally, several existing doc-test line ranges differ between the current file and the target (e.g., current `1183-1212` vs target `1180-1197`), indicating that earlier sections were also updated (content condensed or note admonitions removed) as part of this feature addition. The docs file must be updated to exactly match the target version's structure so all parametrized `test_docs_examples` tests collect with the correct line-range IDs and pass.
- **Contract**:
  1. Add a `### CLI Shortcuts` subsection (under the CLI customization section) with a runnable Python code example demonstrating `SettingsConfigDict(cli_shortcuts={...})` usage — this example must occupy the line range `2467-2491` in the final file.
  2. Add a `### CliApp.serialize` subsection with a code example showing `CliApp.serialize(cfg)` round-trip — line range `2497-2529`.
  3. Add a third new code example (e.g., serialization with positional args) at line range `2536-2565`.
  4. Adjust or remove the `!!! note` admonition preceding the Mutually Exclusive Groups code example (around current line 1180) so that the example starts at line 1180 rather than 1183, reducing the code block to match the target's 18-line range `1180-1197`.
- **Acceptance**: All `test_docs_examples[code/docs/index.md:*]` tests from the failing list pass when pytest is run from the `/current/` parent directory (which prefixes paths with `code/`).
