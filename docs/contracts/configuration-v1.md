# Gezhi Configuration Contract v1

## 1. Status and authority

This document freezes the concrete source names and resolution behavior of `gezhi.config.v1` for [Parent Spec #1](https://github.com/Dulealex/Gezhi/issues/1) and [T02 / Issue #3](https://github.com/Dulealex/Gezhi/issues/3). It is consumed only after [Gezhi CLI Command Contract v1](./cli-command-v1.md) has recognized a valid daily command.

The contract refines the following authorities without reopening their unaffected decisions:

- [ADR 0001](../adr/0001-isolate-core-and-ocr-runtimes.md), [ADR 0003](../adr/0003-use-codex-cli-as-the-only-semantic-provider.md), [ADR 0004](../adr/0004-pin-codex-cli-in-the-project.md), and [ADR 0007](../adr/0007-isolate-codex-development-and-runtime-planes.md);
- [ADR 0029](../adr/0029-use-versioned-toml-and-environment-only-secrets.md), which owns versioned TOML, closed fields, source precedence, and Data Root isolation;
- [ADR 0117](../adr/0117-freeze-context-scoped-data-root-cli-overrides.md), the explicit replacing decision that supersedes only ADR 0094's provisional CLI token witnesses and leaves Question-before-Configuration ordering intact;
- [ADR 0119](../adr/0119-lazy-load-only-the-selected-context-command-adapter.md), the explicit replacing decision that makes the full routing grammar/graph inert and delays exactly the selected Context adapter plus any ADR 0032 composition until after valid daily-command selection;
- [Environment Contract](../environment-contract.md), which owns the frozen uv, Python, OCR, Codex, model, and build-tool baseline;
- the command-specific outcome and diagnostic contracts, including [Knowledge Ask Diagnostics v1](./knowledge-ask-diagnostics-v1.md).

This document owns the two public CLI override names, two `GEZHI_*` names, two TOML leaf names, exact source locations, merge and validation behavior, and the distinction between user configuration and frozen runtime capability.

## 2. Configuration interface

### 2.1 Trusted project location

The production project root is `E:\Gezhi`. Configuration discovery is anchored to that trusted project root, never to the process current working directory, `argv[0]`, a parent search, the user profile, Windows Registry, or a Data Root.

Production sources are exactly:

~~~text
E:\Gezhi\config\default.toml
E:\Gezhi\config\local.toml
built-in defaults compiled in the installed gezhi package
the current Windows process environment
the parsed root CLI patch
~~~

Tests may inject an isolated trusted project root through a private composition seam. That test seam is not a CLI option, environment variable, config key, or supported production relocation mechanism.

### 2.2 Resolved object

A successful `ResolvedConfigurationV1` contains exactly two runtime leaves:

~~~text
literature.data_root : str
knowledge.data_root  : str
~~~

`config_version` is source metadata. It does not enter the resolved runtime object, command JSON, Human output, Answer assets, provenance, or `effective_config.json`. A resolver may retain invocation-local source provenance for validation and audit construction, but it is not a public configuration field.

## 3. Closed TOML schema

### 3.1 Canonical example

~~~toml
config_version = "gezhi.config.v1"

[literature]
data_root = "E:\\Gezhi\\data\\literature"

[knowledge]
data_root = "E:\\Gezhi\\data\\knowledge"
~~~

Both TOML files are versioned partial patches. `config_version` is required in every active TOML document; either Context table and either `data_root` leaf may be absent. Any TOML syntax that `tomllib` parses to the same closed object shape is equivalent; comments and ordering have no semantic effect.

The complete allowed object shape is:

| Location | Required in an active TOML? | Type | Allowed value |
|---|---:|---|---|
| top-level `config_version` | yes | strict string | lowercase ASCII `gezhi.config.vN`, where `N` is a positive integer without a leading zero; current supported value is exactly `gezhi.config.v1` |
| `literature` | no | table | contains only `data_root` |
| `literature.data_root` | no | strict string | any string at source validation; final value must be nonempty |
| `knowledge` | no | table | contains only `data_root` |
| `knowledge.data_root` | no | strict string | any string at source validation; final value must be nonempty |

TOML `null` does not exist and no sentinel spelling gains null semantics. Arrays, integers, floats, booleans, dates, inline objects in place of a string, empty tables with unknown children, duplicate keys, and every extra top-level/table/leaf field are invalid. An empty string is a present value and is not treated as absent.

Unknown examples include `[core]`, `[ocr]`, `[codex]`, `[operations]`, `[runtime]`, `[model]`, `[future_context]`, `project_root`, `config_path`, `model`, `reasoning`, `timeout`, `backoff`, `limit`, `schema`, `capture_cap`, and `config_version` inside a Context table.

### 3.2 File obligations

| File | Presence | Version | Content role |
|---|---|---|---|
| `config\default.toml` | required | required and supported | Git-managed, secret-free partial deployment patch |
| `config\local.toml` | optional | required and supported when present | Git-ignored, secret-free partial machine patch |

A missing default file is configuration invalidity even when CLI or environment supplies both leaves. A missing local file is the only file absence that is skipped. A present file that cannot be read, is not valid UTF-8 TOML, has an invalid root structure, or violates the closed schema is invalid and cannot be hidden by a higher-priority leaf.

Runtime commands never create, rewrite, normalize, repair, migrate, or persist either file.

## 4. Concrete source names and precedence

### 4.1 Source table

Sources are validated and selected in strict high-to-low priority:

| Priority | Source | Canonical names | Version metadata | Active when |
|---:|---|---|---|---|
| 1 | CLI raw patch | `--literature-data-root VALUE`; `--knowledge-data-root VALUE` | forbidden | at least one option is present |
| 2 | Windows process environment | `GEZHI_LITERATURE_DATA_ROOT`; `GEZHI_KNOWLEDGE_DATA_ROOT` | forbidden | a recognized variable or an unknown `GEZHI_` variable is present |
| 3 | local TOML | `E:\Gezhi\config\local.toml` | required | file exists |
| 4 | default TOML | `E:\Gezhi\config\default.toml` | required | always required |
| 5 | built-in defaults | package constant | fixed to current program generation, not user-settable | always |

Built-in leaves are complete and exact:

~~~text
literature.data_root = E:\Gezhi\data\literature
knowledge.data_root  = E:\Gezhi\data\knowledge
~~~

There is no `--config`, `GEZHI_CONFIG`, `GEZHI_CONFIG_VERSION`, user-global config file, directory search, JSON/YAML config, Windows Registry config, or current-directory override.

### 4.2 Environment rules

Only the two canonical variables above are valid Gezhi configuration variables. Windows environment-name lookup follows the process environment case-insensitive behavior, while documentation, diagnostics, fixtures, and generated commands use the canonical uppercase spellings.

Any other process variable whose name has the case-insensitive prefix `GEZHI_` is an unknown supplied configuration field and invalidates the environment source. Variables outside that prefix are not configuration fields and are ignored by this resolver. In particular, `_GEZHI_COMPLETE` has no configuration meaning and shell completion remains disabled by ADR 0113.

A recognized environment variable with value `""` is present. Values are raw strings: there is no trimming, percent expansion, `$env:` expansion, tilde expansion, quote interpretation, path expansion, or list splitting.

The resolver reads the actual invocation environment once. It does not load `.env`. Gezhi V1 exposes no application secret field; Codex authentication remains in the Codex CLI credential store, and OCR runtime variables are injected by its process adapter rather than merged as user configuration.

### 4.3 CLI rules

The CLI source contains only the two ADR 0117 root-scoped options after grammar succeeds. Missing option operands, duplicate options, late root options, and unknown options are CLI argument failures, not configuration failures. A supplied empty-string operand is a present raw configuration value and reaches final validation. Generic `--data-root` and role-policy `--timeout` are parser-unknown and never become Configuration source fields.

CLI and environment cannot set `config_version`. Attempts through unknown tokens or unknown `GEZHI_*` names fail in their respective parser/configuration boundary rather than being ignored.

## 5. Validation and merge algorithm

### 5.1 Source validation order

The resolver examines active sources in the priority order from Section 4. It stops at the first source error and does not continue to lower-priority sources. Within one source, the order is:

1. source availability/readability and TOML syntax/root-object structure, where applicable;
2. `config_version` presence, strict type, and grammar for active TOML;
3. whether that grammar-valid generation is supported by the current program; an unsupported generation selects configuration incompatibility and stops before its fields are interpreted;
4. unknown field/table/leaf rejection for a supported generation;
5. strict supplied-leaf type validation for a supported generation.

CLI and environment are unversioned current-generation partial patches. Their unknown-name and supplied-value checks occur in the equivalent positions. The built-in source is a program invariant; inability to prove its complete valid shape is an implementation failure, not user configuration invalidity.

Every active source must be valid even when all of its leaves lose to a higher-priority source. Therefore a valid CLI override does not mask an unknown local key, a malformed default file, or an unsupported TOML generation.

Only after every active source passes its own grammar/support/field validation may a resolver evaluate the cross-source invariant that active TOML generations are equal. In the current V1 executable contract this predicate is not independently reachable: the only supported generation is `gezhi.config.v1`, so every source that reaches the cross-source point already has that generation. Cross-generation mismatch remains a forward invariant for a future contract that explicitly supports more than one generation; it is not a V1 executable classification row and cannot compete with the first unsupported source.

### 5.2 Leafwise merge

After every source validates, each closed leaf independently selects the first present value in this order:

~~~text
CLI > environment > local TOML > default TOML > built-in default
~~~

A table does not replace a table. Only a present leaf replaces that same leaf. Scalars and arrays would be atomic, but V1 has only string leaves. No source supports append, interpolation, null, unset, deletion, tombstone, fallback-on-invalid, or a second merge pass.

Example:

~~~text
CLI:        knowledge.data_root = D:\K-cli
environment: literature.data_root = D:\L-env
local:      knowledge.data_root = D:\K-local
default:    literature.data_root = D:\L-default
result:     literature.data_root = D:\L-env
            knowledge.data_root  = D:\K-cli
~~~

### 5.3 Final validation

Only after merge, the resolver validates:

1. both required leaves exist;
2. both values are strict strings and nonempty;
3. the purely lexical cross-Context isolation rules in Section 6.1.

The resolver forms one immutable invocation configuration snapshot. Command-owned adapters reuse it; they do not reread files or environment, rerun precedence, or reinterpret raw source values later in the invocation.

## 6. Data Root boundary

### 6.1 Configuration gate: lexical and cross-field only

Configuration validation performs no filesystem access for either Data Root value. When a final value can be represented as a supported local drive-absolute or local extended-DOS Windows namespace, lexical comparison normalizes drive-letter case, separator form, `.` and `..`, redundant trailing separators, and ordinary versus local extended-DOS prefix.

Across all configured Context roots, normalized namespaces must be distinct and neither may be an ancestor or descendant of another. For V1 this means Literature versus Knowledge; a future Context must arrive through a new configuration generation and join the same pairwise rule.

Each normalized root must also satisfy the project boundary:

- it must not equal or contain `E:\Gezhi`;
- if it is inside `E:\Gezhi`, it must be a strict descendant of `E:\Gezhi\data`;
- it must not equal the shared container `E:\Gezhi\data`;
- a local root outside the project remains allowed.

A provable lexical equality, nesting, or project-boundary violation is configuration invalidity. A value that cannot be reduced at this layer to the supported absolute namespace is not guessed into another path and is left for the consuming Context Data Root gate.

### 6.2 Context Data Root gate: namespace and physical proof

After successful configuration, each command may inspect only the root or roots that its current operation actually consumes. It must not open another Context root merely to prove global health. `doctor` is the explicit read-only inspection command and [Operations v1](./operations-v1.md) owns its complete check matrix; `status` consumes both roots only for its explicitly contracted cross-Context projection and may report one unavailable Context conservatively as partial.

The consuming gate owns:

- local, non-remote drive-absolute or local extended-DOS namespace acceptance;
- rejection of relative, UNC, WSL UNC, remote mapping, device, Volume GUID, ADS, and other unsupported namespaces;
- directory existence and access;
- reparse-point and hidden-alias evidence;
- final-path, parent-chain, File ID, and physical identity proof;
- physical overlap or project-boundary facts discoverable only after safe open.

A Data Root is never created automatically. Missing, inaccessible, non-directory, unsafe, or identity-unprovable roots use the consuming command contract. A defect in `literature.data_root` physical state does not block a Knowledge command that does not consume or probe it; both strings still participated in configuration-level lexical validation.

8.3 short names, SUBST, extra drive letters, volume mounts, remote drive mappings, junctions, symlinks, and other reparse or hidden-alias evidence are unsafe rather than accepted equivalence. The precise Knowledge Ask mapping remains frozen in ADR 0094 and Knowledge Ask Diagnostics v1.

## 7. Core, OCR, Codex, and secrets are capabilities, not settings

### 7.1 Frozen capability table

| Capability | Authoritative project source | User configuration fields | Runtime override |
|---|---|---|---|
| Core Python | `E:\Gezhi\.venv`, root `pyproject.toml`, `.python-version`, and `uv.lock`; CPython `3.11.15`; frozen distributions in the Environment Contract | none | none |
| OCR | `E:\Gezhi\runtimes\ocr\.venv`, its `pyproject.toml`/`uv.lock`, `runtimes\ocr\mineru.template.json`, generated `.local\mineru\mineru.json`, and local model cache | none | none |
| Codex CLI | `runtimes\codex\package.json` and `package-lock.json`, with resolver-proved `@openai/codex==0.146.0` and native `0.146.0-win32-x64` executable | none | none |
| Semantic role policy | versioned Literature Reader / Knowledge Answerer role descriptor, prompt, schema, and audit bytes | none | none |
| Codex credentials | Codex CLI credential store and live login state | none | none |
| Native Ctrl+C bridge build baseline | frozen MSVC/SDK metadata in the Environment Contract | none | none |

For entry classification, the [CLI Command Contract v1](./cli-command-v1.md) defines exactly three direct facts for its stdlib-only typed probe: the live CPython `3.11.15` identity plus the Typer `0.27.0` and Rich `15.0.0` top-level module/distribution facts. The probe is not configuration and does not import those packages. This direct-fact set is not an exhaustive package classification: under [ADR 0119](../adr/0119-lazy-load-only-the-selected-context-command-adapter.md), after ready/valid verdicts the bootstrap runtime import closure contains Typer and Rich plus their frozen Windows transitive dependencies from `uv.lock`—Annotated Doc, Colorama, Shellingham, Markdown-It-Py, Pygments, and Mdurl. Those transitive packages are not separately probed, are not Context-only, and an import failure in any closure member remains an unexpected entry fault.

Context-only here is limited to root-project business direct dependencies outside that bootstrap runtime import closure: Feedparser, HTTPX, Pydantic, Pydantic Settings, PyPDF, RapidFuzz, Tenacity, and future Context business dependencies. OCR and Codex are separate isolated runtime capabilities, not business direct dependencies. Under ADR 0119, the static routing descriptor and graph factory must not import or probe either the listed Context-only dependencies or those runtime capabilities; only a valid selected command may lazy-load its consuming handled adapter, and only that adapter's operation-specific consumption gate may probe or start required OCR/Codex capability. Any subsequent ADR 0032 `open_gezhi()` composition freezes static ownership and deep-module interfaces, but does not authorize eager import or probing of unrelated Context-only business dependencies or unrelated isolated runtime capabilities.

Model name, reasoning effort, Codex version/path, provider, role limits, attempt count, timeout, retry/backoff, retrieval limit, capture cap, schema path, prompt path, OCR device, OCR model source, and model cache are not `gezhi.config.v1` fields. A TOML or `GEZHI_*` attempt to set one is unknown configuration; a CLI attempt is an unknown option.

`tools\uv.ps1` and `tools\codex.ps1` are installation/acceptance and human project tools, not hidden runtime configuration sources. Daily commands do not invoke `uv`, `npm ci`, PowerShell wrappers, global Codex, the desktop-app Codex, Ollama, Docker, Conda, or WSL as a fallback.

### 7.2 Missing and drift behavior

| Missing or invalid fact | Boundary | Required behavior | Unaffected work |
|---|---|---|---|
| Required `config\default.toml` | handled configuration gate | selected command mode; command-specific configuration-invalid result | meta help/version and raw preflight |
| Optional `config\local.toml` | source discovery | skip only this source | all work |
| Consumed Data Root directory | Context Data Root gate | block/fail exactly as the command contract states; never create it | commands that do not consume that root |
| Windows launcher, CPython startup, `site`, entry stub, or project target resolution before `gezhi.bootstrap:main` starts | pre-bootstrap OS/runtime | no Gezhi receipt, envelope, fixed stderr, or application exit guarantee | none; repair is external |
| Post-preflight bootstrap-essential fact is explicitly absent or mismatched | CLI typed prerequisite probe | only explicit `ESSENTIAL_UNAVAILABLE` receives the fixed bootstrap receipt; no JSON and no auto-repair | raw preflight and external frozen-environment repair procedure |
| Typer/Rich bootstrap runtime closure import, graph descriptor provider, validator, factory, or construction directly throws after its typed checks | unexpected entry fault | exception is not relabeled as a bootstrap receipt or handled result | frozen environment remains unchanged |
| Context-only business direct dependency outside the bootstrap runtime import closure | selected consuming Context adapter, after valid command selection | command-owned handled capability/operation failure only when that command contract defines it; never a global bootstrap receipt and never install | meta/parser paths and unrelated Context commands |
| OCR Python, package, CUDA, config, or local model | Literature OCR stage | block that OCR-consuming stage; no CPU/online/other-OCR fallback | completed deterministic stages and non-OCR commands |
| Project Codex package, native executable, lock identity, supported version, or login | first Codex-consuming semantic launch gate | block the semantic stage before launch; no global/desktop/WSL/provider fallback | deterministic commands and semantic branches that do not need a launch |
| Online service rejects the frozen Codex version | Codex-consuming semantic gate | block and require a separate approved dependency window; never auto-upgrade | non-Codex work |
| npm or user-level uv during daily operation | not a runtime prerequisite once environments are installed | do not invoke or install | already runnable frozen environments |
| MSVC build-only tools | bridge build/test only | block bridge build/test; never install or upgrade during an implementation ticket | Python/OCR/Codex work not building the bridge |

The public `doctor` command reports the frozen environment read-only when enough Core bootstrap exists to run it; it never repairs anything. If Windows or CPython fails before `gezhi.bootstrap:main` starts, there is no Gezhi CLI receipt at all. Once `main` has started and raw preflight has passed, only the closed typed probe's explicit `ESSENTIAL_UNAVAILABLE` verdict produces the fixed bootstrap receipt. An actual bootstrap runtime import-closure or graph implementation exception after a ready/valid verdict is not relabeled; repair remains an explicit external environment operation in every case.

A semantic command must resolve capability only at its approved consumption gate. For example, deterministic zero-result Knowledge handling must not probe or launch Codex merely because Codex exists in the project, and a Literature command must not initialize OCR before reaching an OCR stage.

## 8. Failure and presentation ownership

Configuration discovery begins only after a valid leaf grammar selects Human or JSON mode. Therefore:

- configuration failure is never a parser/bootstrap stderr receipt;
- in `--json` mode it is a command-owned `CliResultEnvelopeV1` branch once that command contract freezes its result/diagnostic mapping;
- in Human mode it uses that command contract’s Human renderer;
- raw config values, paths, file contents, environment contents, credentials, and exception text must not be copied into shared diagnostics by this resolver;
- a command without a complete concrete error contract remains locally blocked on that branch; other commands and JSON happy paths continue.

For `knowledge.ask`, ADR 0094 and Knowledge Ask Diagnostics v1 already map this boundary to the frozen primary diagnostic and gate order. This document changes only the previously open source-specific CLI/environment names. [Knowledge Read v1](./knowledge-read-v1.md) and [Knowledge Read Diagnostics v1](./knowledge-read-diagnostics-v1.md) now map the same shared resolver and Knowledge-only physical gate for `knowledge.search` and `knowledge.show`; they validate Query/ID first and do not probe Codex or another Context root.

Unsupported TOML generation, unknown fields, invalid types, unreadable files, and final cross-field failure all belong to the configuration boundary. Cross-generation mismatch remains a configuration-boundary forward invariant, but it has no independent V1 witness because V1 supports only one generation. This shared resolver need not expose internal subtypes publicly; a command contract may present only its approved stable diagnostic.

## 9. Executable acceptance matrices

### 9.1 Source and precedence matrix

| Case | Setup | Expected result |
|---|---|---|
| Built-in fallback | default contains only `config_version`; local absent; no env/CLI | both built-in roots |
| Default leaf | default sets Literature only | default Literature plus built-in Knowledge |
| Local wins | local and default set Knowledge | local Knowledge wins |
| Environment wins | env, local, and default set Literature | environment Literature wins |
| CLI wins | every source sets Knowledge | CLI Knowledge wins |
| Per-leaf merge | CLI sets Knowledge; env sets Literature | each leaf uses its own first-present source |
| Present empty high priority | CLI or env sets a root to empty | final configuration invalid; no fallback |
| Invalid overridden local | CLI supplies both leaves; local has unknown field | configuration invalid at local source |
| Invalid overridden default | CLI supplies both leaves; default TOML malformed | configuration invalid at default source |
| Missing local | local absent | skip local |
| Missing default | CLI supplies both leaves; default absent | configuration invalid |
| No cwd discovery | current directory has another `config\local.toml` | ignore it |
| No `.env` discovery | project has a `.env` with `GEZHI_*` text | ignore file contents |
| No interpolation | root contains `%TEMP%`, `$env:TEMP`, or `~` | preserve raw string; consuming Data Root gate decides namespace |

### 9.2 Schema and version matrix

| Case | Expected classification |
|---|---|
| active TOML omits `config_version` | configuration invalid |
| `config_version=1` | configuration invalid type |
| `gezhi.config.v0`, `gezhi.config.v01`, uppercase, whitespace, or suffix text | configuration invalid grammar |
| grammar-valid `gezhi.config.v2` | unsupported generation; configuration incompatible at that source and stop |
| local declares `gezhi.config.v2`, default declares V1 | local is the first unsupported source; configuration incompatible and default is not examined |
| local declares V1, default declares `gezhi.config.v2` | local passes; default is unsupported; configuration incompatible at default |
| `[literature] data_root=1` | configuration invalid type |
| `[literature] data_root=""` | source valid, final configuration invalid |
| `[literature] extra="x"` | unknown field |
| `[codex] model="x"` | unknown table |
| `model="x"` at top level | unknown field |
| `GEZHI_MODEL=x` | unknown environment configuration field |
| `GEZHI_CONFIG_VERSION=gezhi.config.v1` | unknown environment configuration field |
| `--model x` | CLI parser failure, not configuration failure |
| duplicate TOML key | TOML syntax/source invalid |

### 9.3 Data Root boundary matrix

| Final values or physical fact | Configuration gate | Consuming Data Root gate |
|---|---|---|
| `E:\Gezhi\data\literature` and `E:\Gezhi\data\knowledge` | valid | each command probes only its consumed root |
| same path with case/separator/extended-prefix differences | invalid equality | not reached |
| Knowledge nested under Literature | invalid nesting | not reached |
| Literature nested under Knowledge | invalid nesting | not reached |
| either root is `E:\Gezhi` | invalid project boundary | not reached |
| either root contains `E:\Gezhi`, such as `E:\` | invalid project boundary | not reached |
| either root is `E:\Gezhi\data` | invalid shared-container boundary | not reached |
| root is `E:\Gezhi\other` | invalid project-internal location | not reached |
| roots are strict, separate descendants of `E:\Gezhi\data` | valid | physical proof later |
| roots are separate local paths outside project | valid | physical proof later |
| relative path, UNC, WSL UNC, device path, Volume GUID, or ADS | not reinterpreted and not made absolute | unsafe at the consuming gate |
| consumed directory missing or inaccessible | text config may be valid | unavailable; no creation |
| non-consumed Context directory missing | text config may be valid | not probed and does not block this command |
| consumed path exposes reparse/8.3/SUBST/remote/hidden alias | text config may be valid | unsafe |
| File ID proof cannot complete | text config may be valid | identity unavailable |

### 9.4 Capability isolation matrix

| Invocation | Missing fact | Expected scope |
|---|---|---|
| `knowledge search` | OCR runtime absent | no OCR probe; command may continue |
| `literature add` before OCR stage | Codex absent | no Codex probe; deterministic add may continue |
| Literature resume reaches OCR | OCR absent | only the OCR-consuming stage blocks |
| Literature resume reaches semantic read | Codex absent | only the semantic stage blocks |
| `knowledge ask` has no citable candidates and its contract chooses deterministic insufficiency | Codex absent | no Codex launch merely to report zero evidence |
| `knowledge ask` requires synthesis | Codex absent/drifted/not logged in | semantic launch gate blocks; no fallback |
| any valid leaf | default TOML malformed | selected handled mode receives configuration failure before Data Root/capability probe |
| help/version | any configuration or Context-only runtime missing | metadata succeeds if the closed bootstrap-essential probe is ready and graph descriptor is valid |
| launcher/CPython startup before `bootstrap.main` | startup unavailable | no Gezhi receipt is asserted |
| any valid-looking suffix after preflight | typed probe returns `ESSENTIAL_UNAVAILABLE` | fixed bootstrap receipt; no config or Context probe |
| any suffix after typed ready/valid verdicts | bootstrap runtime import-closure or graph implementation directly throws | no fixed bootstrap receipt; exception is not relabeled |
| valid selected leaf | Context-only business direct dependency absent | only its owning command branch is affected; meta/parser and unrelated commands do not import it |

There is deliberately no V1 executable row for “active supported TOML generations differ”: with only `gezhi.config.v1` supported, the first non-V1 document has already selected unsupported-generation incompatibility and stopped. A future multi-generation resolver must add its own witness and priority contract before the forward mismatch invariant becomes executable.

Tests use fixed source mappings and temporary trusted project roots for resolution logic, then isolated Windows subprocesses for public CLI mode and missing-capability boundaries. Tests must not install, sync, update, authenticate, download, create Data Roots, or mutate the production configuration.

## 10. Traceability and change rule

| Requirement | Frozen here |
|---|---|
| Spec stories 7, 9, 10, 19, 20 | read-only checks, scoped capability blocking, no dependency/model fallback |
| Spec implementation decisions | two Context roots, versioned TOML, unknown rejection, environment-only credentials, fixed providers |
| T02 acceptance | canonical key/source names, source-priority first-error behavior, missing behavior, unknown fields, parser versus handled boundary, and pre-main versus typed-bootstrap distinction |
| ADR 0029 | existing leafwise/source validation and Data Root semantics remain authoritative; this contract supplies concrete names |
| ADR 0117 | exact root-scoped CLI names replace only ADR 0094's provisional token witnesses; `--data-root`/`--timeout` are parser-unknown |
| ADR 0119 / ADR 0032 | inert routing graph precedes selected-adapter late load; static composition preserves ownership/interfaces without making unrelated Context-only dependencies bootstrap or global prerequisites |
| Environment Contract | Core/OCR/Codex identities remain deployment capability rather than user settings; only CPython plus Typer/Rich direct facts are typed-probe inputs, while their frozen transitive dependencies belong to the unprobed bootstrap runtime import closure |
| ADR 0094 | Knowledge Ask Question-before-Configuration and Data Root ordering remain unchanged apart from ADR 0117's explicitly replaced token witnesses |

Adding a configuration leaf, accepting another `GEZHI_*` name, introducing `--config`, changing a source location or priority, making project/runtime/model policy configurable, auto-creating a Data Root, or allowing an unknown field changes `gezhi.config.v1` and requires a new configuration generation or an explicit replacing decision. Changing only a frozen runtime version follows the Environment Contract dependency-window process and does not silently alter this schema.
