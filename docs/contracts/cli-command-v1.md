# Gezhi CLI Command Contract v1

## 1. Status and authority

This document freezes `GezhiCliGrammarV1`, the public Windows command grammar shared by the eight V1 daily commands. It is the executable contract for [Parent Spec #1](https://github.com/Dulealex/Gezhi/issues/1) and [T02 / Issue #3](https://github.com/Dulealex/Gezhi/issues/3).

The following sources remain authoritative except where the three explicitly scoped replacing decisions below say otherwise:

- [ADR 0023](../adr/0023-ship-one-windows-cli-before-any-gui.md): one Windows CLI, Human and JSON presentation.
- [ADR 0024](../adr/0024-limit-the-daily-cli-to-eight-commands.md): the eight-command public surface without premature concrete result bindings.
- [ADR 0032](../adr/0032-use-static-composition-and-context-deep-modules.md): static composition and Context deep modules.
- [CLI JSON v1](./cli-json-v1.md) and [CLI Diagnostics v1](./cli-diagnostics-v1.md): the shared JSON envelope and diagnostic item.
- [ADR 0110](../adr/0110-run-a-decoded-argv-resource-preflight-before-typer.md) through [ADR 0116](../adr/0116-return-2-with-one-fixed-stderr-line-for-raw-argv-resource-violation.md): bootstrap, immutable argv, completion shutdown, resource ceilings, and the fixed resource-failure presenter.
- [ADR 0117](../adr/0117-freeze-context-scoped-data-root-cli-overrides.md): the two Context-scoped root override tokens; it supersedes only ADR 0094's provisional CLI token witnesses.
- [ADR 0118](../adr/0118-limit-v1-candidate-review-to-one-candidate-and-action.md): one Candidate plus one action in V1; it supersedes only ADR 0008's public-batch permission and leaves ADR 0019 append-only semantics intact.
- [ADR 0119](../adr/0119-lazy-load-only-the-selected-context-command-adapter.md): the inert full routing grammar/graph and selected-adapter late-load boundary; it supersedes only ADR 0111/0112's eager all-Context-adapter/`open_gezhi()` requirement on every preflight-PASS path.

This contract owns public token spelling, arity, option placement, defaults, mutual exclusion, route-to-owning-module selection, launcher parity, and the boundary between entry failures and handled command outcomes. It does not itself bind a concrete `CliResultEnvelopeV1.command`, result object, diagnostic union, Human result copy, or domain validation. [Operations v1](./operations-v1.md) now owns those concrete surfaces for `doctor` and `status`; T04 through T06 own the remaining five previously unbound commands, while `knowledge.ask` keeps its existing binding.

## 2. Public interface

### 2.1 Launch adapters

The two and only two public V1 launch forms are:

~~~text
E:\Gezhi\.venv\Scripts\gezhi.exe ARGS...
E:\Gezhi\.venv\Scripts\python.exe -m gezhi ARGS...
~~~

Both adapters call the same no-argument `gezhi.bootstrap:main` seam. They must:

- form one immutable `tuple(sys.argv)` snapshot;
- exclude `argv[0]` from `RawArgvPreflightV1` measurement;
- pass the exact same suffix to Typer with `prog_name="gezhi"` and `windows_expand_args=False`;
- return the same application exit code and produce the same application-owned stdout/stderr bytes for the same suffix and external state;
- leave the process current working directory unchanged;
- expose no public `python -m gezhi.cli`, per-Context executable, PowerShell runtime wrapper, legacy PaperBot alias, or KnowledgeBot alias.

Operating-system launcher failures that occur before CPython enters `gezhi.bootstrap:main` are outside the application contract. Once `main` starts, the ordering in Section 7 applies.

### 2.2 Command paths and module ownership

The exact case-sensitive lowercase ASCII paths and their owning modules are:

| Public path | Owning module |
|---|---|
| `doctor` | Operations |
| `status` | Operations |
| `literature add` | Literature |
| `literature resume` | Literature |
| `literature review` | Literature |
| `knowledge search` | Knowledge |
| `knowledge show` | Knowledge |
| `knowledge ask` | Knowledge |

This table freezes routing identity and ownership only. T02 did not create or bind `CliResultEnvelopeV1.command` values for `doctor`, `status`, `literature add/resume/review`, or `knowledge search/show`. [Operations v1](./operations-v1.md) now binds the first two; the other five remain with T04 through T06. `knowledge.ask` remains bound by [Knowledge Ask Result v1](./knowledge-ask-result-v1.md) and its existing diagnostic contracts, and this table neither replaces nor generalizes any concrete binding.

`literature` and `knowledge` are namespace tokens, not ninth and tenth daily commands. Future Contexts receive new explicit namespace tokens only after their domain language and state ownership are approved; there is no dynamic command discovery.

## 3. Grammar

### 3.1 Notation

- Uppercase names are exactly one decoded argv element.
- `[X]` means zero or one occurrence.
- `X...` means the listed options may occur in any order within that option scope, but each option itself is single-use.
- `(A | B)` means exactly one alternative.
- Literal tokens are case-sensitive.

### 3.2 Root and leaf grammar

~~~text
ROOT_CONFIG_OPTION =
    "--literature-data-root" VALUE
  | "--knowledge-data-root" VALUE

LEAF_MODE_OPTION = "--json"

INVOCATION = "gezhi" ROOT_CONFIG_OPTION... DAILY_COMMAND

DAILY_COMMAND =
    "doctor" [LEAF_MODE_OPTION]
  | "status" [WORK_ID] [LEAF_MODE_OPTION]
  | "literature" "add" PDF_PATH
        ["--work-id" WORK_ID]
        ["--doi" DOI]
        ["--arxiv-id" ARXIV_ID]
        ["--citation" CITATION]
        [LEAF_MODE_OPTION]
  | "literature" "resume" WORK_ID [LEAF_MODE_OPTION]
  | "literature" "review" CANDIDATE_ID
        ("--accept" | "--reject" | "--defer")
        [LEAF_MODE_OPTION]
  | "knowledge" "search" QUERY [LEAF_MODE_OPTION]
  | "knowledge" "show" CANDIDATE_ID [LEAF_MODE_OPTION]
  | "knowledge" "ask" QUESTION [LEAF_MODE_OPTION]
~~~

`ROOT_CONFIG_OPTION` occurrences must appear after the launcher and before `doctor`, `status`, `literature`, or `knowledge`. A root option after any command or namespace token is an unknown option in that scope. Leaf options may appear in any order after the leaf command token and may appear before or after its positional argument.

A value option accepts either `--name VALUE` or `--name=VALUE`. Boolean flags accept only the bare token. `--` ends option recognition in the current leaf scope; subsequent elements are positional values. Values containing whitespace must already be one argv element after PowerShell processing. Gezhi performs no secondary shell splitting, glob expansion, environment expansion, quote removal, or response-file expansion.

### 3.3 Meta invocations

The following are navigation or metadata, not daily commands:

| Invocation | Behavior |
|---|---|
| `gezhi` | Root help, stdout, exit `0` |
| `gezhi --help` | Root help, stdout, exit `0` |
| `gezhi literature` or `gezhi literature --help` | Literature namespace help, stdout, exit `0` |
| `gezhi knowledge` or `gezhi knowledge --help` | Knowledge namespace help, stdout, exit `0` |
| `gezhi COMMAND_PATH --help` | Leaf help, stdout, exit `0`; required operands are not required |
| `gezhi --version` | Product version, stdout, exit `0` |

Only long `--help` and `--version` exist. `-h`, `-V`, a `help` command, `--install-completion`, and `--show-completion` are not aliases. `--version` is valid only as the sole suffix element. Help may be combined only with the command path that it describes; other operands or leaf options with `--help` are grammar failures. Meta invocations do not resolve configuration, probe a Data Root or runtime, build a cancellation profile, or invoke a Context adapter.

Help and version are Human metadata surfaces. Their exact wording, color, wrapping, terminal width behavior, and version-line newline are not frozen by this contract. Tests assert command inventory, token spelling, channels, exit, absence of a JSON envelope, and absence of domain side effects, not full help bytes.

## 4. Arguments, options, defaults, and mutual exclusion

### 4.1 Shared options

| Token | Scope | Arity | Default | Meaning |
|---|---|---:|---|---|
| `--literature-data-root VALUE` | Root, before command path | 1 | absent patch | Raw CLI patch for `literature.data_root` |
| `--knowledge-data-root VALUE` | Root, before command path | 1 | absent patch | Raw CLI patch for `knowledge.data_root` |
| `--json` | Every leaf command | 0 | `false` | Select handled JSON presentation |

There is no `--config`, `--data-root`, `--human`, `--quiet`, `--verbose`, `--model`, `--reasoning`, `--provider`, `--timeout`, `--force`, or `--prepare-only`. There are no short aliases. Under ADR 0117, both generic `--data-root` and role-policy `--timeout` are parser-unknown tokens; timeout remains an immutable role-descriptor fact rather than user configuration. Configuration names and precedence are frozen in [Configuration v1](./configuration-v1.md).

### 4.2 Per-command surface

| Command | Required input | Optional input | Default and parser rule |
|---|---|---|---|
| `doctor` | none | `--json` | Human when `--json` is absent |
| `status` | none | positional `WORK_ID`, `--json` | absent `WORK_ID` means overall status; one value means Work status |
| `literature add` | positional `PDF_PATH` | `--work-id WORK_ID`, `--doi DOI`, `--arxiv-id ARXIV_ID`, `--citation CITATION`, `--json` | every optional value is absent unless supplied |
| `literature resume` | positional `WORK_ID` | `--json` | no interactive prompt or implicit current Work |
| `literature review` | exactly one positional `CANDIDATE_ID`; exactly one action flag | `--json` | no default action; `--accept`, `--reject`, and `--defer` are mutually exclusive; Review Decision note is absent |
| `knowledge search` | positional `QUERY` | `--json` | no CLI result-limit option; T05 owns the fixed retrieval surface |
| `knowledge show` | positional `CANDIDATE_ID` | `--json` | no implicit last Candidate |
| `knowledge ask` | positional `QUESTION` | `--json` | one-shot, one Question; no implicit session or history |

ADR 0118 fixes `literature review` as a one-Candidate, one-action invocation. V1 has no batch selector and no `--note`; either spelling is a parser failure, and the handled adapter receives one Candidate selector, one action, and an absent note. A future batch must first receive a versioned public contract and must expand to ADR 0019 append-only decisions one Candidate at a time.

The Literature add identity options are independent, not mutually exclusive. `--work-id` lets the handled Literature adapter distinguish an explicitly named existing Work from an add without that selector; DOI, arXiv ID, citation normalization, identity conflict/review, duplicate source behavior, and Active Source behavior remain T04 domain rules.

Every option is single-use. Repeating a boolean flag, repeating a value option, providing two review action flags, or providing the same review action flag twice is a grammar failure. The parser never uses first-wins or last-wins behavior.

## 5. Parser ownership and raw-value handoff

The parser owns only:

- command and namespace recognition;
- option recognition and scope;
- required positional/value presence;
- positional arity;
- duplicate-option rejection;
- the review action exactly-one rule;
- meta invocation recognition;
- selection of the raw CLI configuration patch and the Boolean presentation mode.

After grammar succeeds, the adapter receives each recognized textual operand as the exact decoded Python `str` from the immutable argv snapshot. Parser callbacks must not trim, normalize Unicode, parse identifiers, inspect a path, test existence, open a file, validate DOI/arXiv/citation syntax, validate Question size or meaning, or convert configuration values into `Path` objects.

Consequences include:

- missing `QUESTION` is a parser failure; an explicitly supplied empty-string token reaches Knowledge Question validation;
- missing `--knowledge-data-root` value is a parser failure; `--knowledge-data-root ""` reaches configuration validation as a present empty string;
- missing review action, an extra Candidate operand, or any `--note`/batch token is a parser failure; an invalid single Candidate ID reaches Literature validation;
- `PDF_PATH`, `WORK_ID`, `CANDIDATE_ID`, `QUERY`, and `QUESTION` that begin with `-` require the leaf `--` delimiter or an unambiguous option-value form;
- domain rejection after successful grammar is a handled command outcome, not a parser failure.

## 6. Human and JSON boundary

`--json` is recognized only in a valid leaf scope. The presentation boundary is:

| Boundary | JSON envelope allowed? | stdout | stderr |
|---|---|---|---|
| Raw argv resource failure before command recognition | no | empty | ADR 0116 fixed line |
| Controlled bootstrap failure before parser | no | empty | bootstrap line from Section 8 |
| Grammar failure, even if a literal `--json` occurs | no | empty | parser line from Section 8 |
| Help or version | no | Human metadata | empty on complete success |
| Valid leaf without `--json` | no | command-owned Human result | command-owned Human contract |
| Valid leaf with `--json` | yes | exactly one command-owned `CliResultEnvelopeV1` on complete handled presentation | empty on complete handled presentation |

Mode is authoritative only after the complete leaf grammar succeeds. Configuration invalidity, Data Root failure, environment capability failure, and domain validation that occur after that point must respect the selected mode. The command-specific contracts own their concrete command identity, outcome, diagnostic, exit, and Human copy; [Operations v1](./operations-v1.md) now closes those facts for `doctor` and `status`, while this grammar does not invent the five remaining unfinished payloads.

Before a command-owning ticket freezes its exact Human prose, a JSON-only slice may assert only the concrete surfaces already authorized for that command. [Operations v1](./operations-v1.md) now freezes both presentations for `doctor` and `status`; T02 tests for the five still-unbound paths continue to stop at the narrow route/raw-value handoff seam without constructing a speculative envelope. The existing `knowledge.ask` binding continues to use its authoritative contracts.

Only `knowledge.ask --json` adopts the combined ADR 0107 through ADR 0109 candidate/seal/commit presentation package. [Operations v1](./operations-v1.md) separately and explicitly adopts the same numerical cap and ADR 0109 synchronous binary fd1 primitive only after its own read-only resources are settled; it does not inherit the Knowledge cancellation seal, Answer commit semantics, or manifest parity. The other five commands must not silently reuse either binding.

## 7. Entry ordering

For every launcher invocation, observable ordering is:

1. enter the common bootstrap seam and form one immutable argv snapshot;
2. run `RawArgvPreflightV1` exactly once over the suffix;
3. on resource rejection, invoke only the ADR 0116 presenter and return `2`;
4. on PASS, run the stdlib-only conceptual `BootstrapPrerequisiteProbeV1`;
5. only when that probe explicitly returns `ESSENTIAL_UNAVAILABLE`, invoke the T02 bootstrap presenter and return `1`;
6. otherwise obtain the bootstrap-owned static graph descriptor and run the deterministic conceptual `StaticCommandGraphDescriptorValidatorV1`;
7. only when that validator explicitly returns `GRAPH_DESCRIPTOR_INVALID`, invoke the same T02 bootstrap presenter and return `1`;
8. only after both typed checks pass, import the Typer/Rich bootstrap runtime closure plus the routing graph factory; no Context adapter is imported here;
9. construct the routing graph from the already validated descriptor with completion disabled;
10. process a meta invocation or grammar against the same suffix;
11. on grammar failure, use `ParserFailureV1` and do not enter a handled adapter;
12. on a valid daily command, enter the handled command boundary, lazy-load exactly its owning adapter, and hand it the raw values, raw CLI config patch, and mode.

The two conceptual seam names above freeze inputs, facts, verdicts, and ordering, not a Python module, class, function, or injection path. `BootstrapPrerequisiteProbeV1` imports no third-party module and performs no project/configuration/domain I/O. Its allowlist and fact sources are closed:

| Essential fact | Live fact read with stdlib only | Required frozen fact |
|---|---|---|
| Core interpreter | `sys.implementation.name` and `sys.version_info` | CPython `3.11.15` |
| Typer top-level module/distribution | `importlib.util.find_spec("typer")` plus installed distribution metadata | discoverable `typer`; literal version `0.27.0` |
| Rich top-level module/distribution | `importlib.util.find_spec("rich")` plus installed distribution metadata | discoverable `rich`; literal version `15.0.0` |

The expected literals come from the [Environment Contract](../environment-contract.md) and frozen root lock; they are compiled project facts, so the probe does not read either file at runtime. An expected distribution-not-found fact, a `find_spec` result of `None`, or a literal interpreter/distribution mismatch may produce only `ESSENTIAL_UNAVAILABLE`; all matched facts produce `ESSENTIAL_READY`. The probe does not import Typer or Rich. Any exception other than the explicitly represented not-found fact escapes the probe call and is not a bootstrap receipt.

The typed probe's direct-fact allowlist contains only CPython, Typer, and Rich; it is not an exhaustive package classification. After ready/valid verdicts, the bootstrap runtime import closure contains Typer and Rich plus the frozen Windows transitive dependencies required by `uv.lock`: Annotated Doc, Colorama, Shellingham, Markdown-It-Py, Pygments, and Mdurl. Those transitive packages are not probed separately and are not Context-only. An import failure anywhere in that closure is an unexpected entry fault and is not relabeled as a typed verdict or receipt.

Context-only in this contract means root-project business direct dependencies outside that bootstrap runtime import closure: Feedparser, HTTPX, Pydantic, Pydantic Settings, PyPDF, RapidFuzz, Tenacity, and future Context business dependencies. OCR and Codex are separate isolated runtime capabilities, not business direct dependencies. The routing descriptor and graph factory must not import or probe either the listed Context-only dependencies or those runtime capabilities. Only the selected handled adapter may lazy-load the direct dependencies its operation consumes, and only that adapter's operation-specific consumption gate may probe or start required OCR/Codex capability.

The static graph descriptor is inert project-owned data containing only the eight route paths, namespace/option/arity facts, and symbolic owning-module selection required by Sections 2 through 5. It contains no imported callback, Context object, dependency probe, configuration value, or domain validator. Its validator performs deterministic, I/O-free shape, closed-token, uniqueness, ownership, arity, option-scope, and mutual-exclusion checks. A representable mismatch returns only `GRAPH_DESCRIPTOR_INVALID`; exact conformance returns `GRAPH_DESCRIPTOR_VALID`. Descriptor retrieval/import, validator implementation, bootstrap runtime import-closure import, graph-factory import, or graph construction that throws is not converted into either verdict.

No configuration file, environment configuration patch, Data Root, Context store, Context-only business dependency, OCR runtime, Codex runtime, model, child process, cancellation bridge, or durable asset may be touched before Step 12. Meta and grammar-failure paths never lazy-load a Context adapter. Any subsequent ADR 0032 `open_gezhi()` composition preserves static ownership and deep-module interfaces but must not eager-import or probe unrelated Context-only business dependencies. A command-owned contract may impose stricter ordering after Step 12; in particular, ADR 0117 preserves the existing `knowledge.ask` Question-before-Configuration order.

## 8. Parser and bootstrap failure contract

### 8.1 Closed normal entry outcomes

| Entry outcome | Trigger | Complete stdout | Complete stderr | Normal exit | Handled result? |
|---|---|---|---|---:|---|
| `RAW_ARGV_RESOURCE_LIMIT_EXCEEDED` | ADR 0115 authoritative resource predicate | empty | exact `b"gezhi: error: command-line input exceeds safety limits\r\n"` | `2` | no |
| `CLI_BOOTSTRAP_FAILED` | only explicit `ESSENTIAL_UNAVAILABLE` or `GRAPH_DESCRIPTOR_INVALID` after preflight PASS | empty | exact `b"gezhi: error: cli bootstrap failed\r\n"` | `1` | no |
| `CLI_ARGUMENT_FAILED` | unknown/missing/extra/repeated/conflicting token under Sections 3–5 | empty | exact `b"gezhi: error: invalid command line\r\n"` | `2` | no |

The two T02 lines are fixed lowercase ASCII except the product name, contain no BOM, ANSI, usage text, input echo, path, exception detail, traceback, JSON, or second newline. They are not `CliDiagnosticItemV1` values and do not create a cancellation profile or persistent diagnostic.

### 8.2 Closed bootstrap classification

`CLI_BOOTSTRAP_FAILED` is selected by explicit verdict matching, never by an exception catch. The only positive mappings are:

| Conceptual typed seam | Accepted verdict | Mapping |
|---|---|---|
| `BootstrapPrerequisiteProbeV1` | `ESSENTIAL_UNAVAILABLE` | fixed bootstrap line, empty stdout, return `1` |
| `StaticCommandGraphDescriptorValidatorV1` | `GRAPH_DESCRIPTOR_INVALID` | fixed bootstrap line, empty stdout, return `1` |

`ESSENTIAL_READY` and `GRAPH_DESCRIPTOR_VALID` continue to the next entry step. No Python module/class path for either seam is public. A direct call to the probe, descriptor provider/import, validator, bootstrap runtime import-closure import, routing graph factory/import, graph construction, or selected Context adapter import that raises `ModuleNotFoundError`, `ImportError`, `RuntimeError`, `TypeError`, `MemoryError`, or any other `BaseException` must not be relabeled as `CLI_BOOTSTRAP_FAILED`, `CLI_ARGUMENT_FAILED`, or a handled command outcome. The same exclusion covers malformed `sys.argv`, snapshot allocation failure, `RecursionError`, `KeyboardInterrupt`, `SystemExit`, `GeneratorExit`, process crash, and external termination. These paths retain operating-system/runtime behavior and may have no application-controlled exit or complete output.

This distinction is intentional: the stdlib probe reports only a closed absence/mismatch fact before import, and the descriptor validator reports only closed inert-data invalidity. Actual bootstrap runtime import-closure/factory/validator exceptions are implementation or runtime faults, not evidence that either typed verdict occurred. Context adapter loading begins only after valid command selection, so its missing dependency cannot become a global bootstrap receipt.

If presentation of a T02 fixed line itself cannot complete, Gezhi must not write stdout, switch to JSON/Human fallback, echo the exception, or retry through another presenter. That transport failure does not create a complete entry receipt; it may leave stderr empty or an exact prefix. Only a completed line plus the listed normal return is the corresponding complete receipt.

### 8.3 Parser classification

All of the following map to the single `CLI_ARGUMENT_FAILED` row:

- unknown root command, Context namespace, leaf command, or option;
- wrong token case;
- missing required positional, missing value-option operand, or extra positional;
- root configuration option after a command token;
- leaf option outside its owning leaf;
- any repeated option;
- zero, two, or three review action flags;
- short aliases and completion options that V1 does not expose;
- `--version` combined with another suffix token;
- `--help` combined with operands or leaf options rather than only its described path.

The category intentionally does not disclose which token failed. Callers use exit `2` plus absence of a complete JSON envelope to distinguish entry failure from a handled command outcome.

## 9. Executable acceptance matrix

Every row is exercised through both public launch adapters. Public tests compare application-owned stdout, stderr, exit, side effects, and, where applicable, complete JSON bytes.

| Case | Suffix | Expected boundary |
|---|---|---|
| Root navigation | empty | root help, stdout, exit `0`, no config/domain access |
| Namespace navigation | `literature` | namespace help, stdout, exit `0` |
| Leaf navigation | `knowledge ask --help` | leaf help, stdout, exit `0` |
| Version | `--version` | version on stdout, exit `0` |
| Operations | `doctor --json` | handled `doctor` JSON mode |
| Optional status operand absent | `status --json` | handled overall-status mode |
| Optional status operand present | `status wrk_example --json` | raw `wrk_example` handed to status |
| Literature add minimum | `literature add E:\fixture\paper.pdf --json` | one raw PDF path, optional fields absent |
| Literature add existing Work | `literature add E:\fixture\paper.pdf --work-id wrk_example --doi 10.1/x --arxiv-id 2401.00001 --citation text --json` | all raw values preserved |
| Literature resume | `literature resume wrk_example --json` | one raw Work selector |
| Review accept | `literature review cand_example --accept --json` | exactly-one action succeeds |
| Review reject | `literature review --reject cand_example --json` | leaf options may precede positional |
| Review defer | `literature review cand_example --defer` | Human mode |
| Knowledge search | `knowledge search "graph retrieval" --json` | one raw Query token |
| Knowledge show | `knowledge show cand_example --json` | one raw Candidate selector |
| Knowledge ask | `knowledge ask "What is supported?" --json` | one raw Question token |
| Root override | `--knowledge-data-root D:\GezhiData\knowledge knowledge ask q --json` | CLI patch contains only Knowledge leaf |
| Both root overrides | `--literature-data-root D:\L --knowledge-data-root D:\K doctor --json` | both raw leaves present |
| Empty domain token | `knowledge ask "" --json` | grammar succeeds; handled Question validation owns rejection |
| Question wins overlapping empty values | `--knowledge-data-root= knowledge ask "" --json` | grammar succeeds; Question selects `invalid_question`; Configuration is not run |
| Empty config after valid Question | `--knowledge-data-root= knowledge ask "What is supported?" --json` | grammar succeeds; Question passes; Configuration selects `configuration_invalid` |
| Dash-prefixed operand | `knowledge search -- --literal` | raw Query is `--literal`; Human mode |
| Missing operand | `knowledge ask --json` | fixed parser stderr, empty stdout, exit `2` |
| Extra operand | `knowledge show cand_a cand_b --json` | fixed parser stderr, empty stdout, exit `2` |
| Unknown option | `doctor --verbose` | fixed parser stderr, empty stdout, exit `2` |
| Generic Data Root is unknown | `--data-root D:\K knowledge ask q --json` | fixed parser stderr, empty stdout, exit `2`; no handled gate |
| Role timeout is unknown | `knowledge ask q --timeout 60 --json` | fixed parser stderr, empty stdout, exit `2`; timeout remains role policy |
| Wrong scope | `knowledge --json ask q` | fixed parser stderr, empty stdout, exit `2` |
| Late root option | `knowledge ask q --knowledge-data-root D:\K` | fixed parser stderr, empty stdout, exit `2` |
| Repeated option | `doctor --json --json` | fixed parser stderr, empty stdout, exit `2` |
| Missing review action | `literature review cand_example --json` | fixed parser stderr, empty stdout, exit `2` |
| Conflicting review action | `literature review cand_example --accept --defer --json` | fixed parser stderr, empty stdout, exit `2` |
| Review note is absent in V1 | `literature review cand_example --accept --note text --json` | fixed parser stderr, empty stdout, exit `2` |
| Review batch is absent in V1 | `literature review cand_a cand_b --accept --json` | fixed parser stderr, empty stdout, exit `2` |
| Completion disabled | `--show-completion` | fixed parser stderr, empty stdout, exit `2` |
| Invalid version combination | `--version doctor` | fixed parser stderr, empty stdout, exit `2` |
| Literal JSON on bad command | `unknown --json` | parser failure, never JSON |
| Raw ceiling beats grammar | any ADR 0115-over-limit suffix containing `--json` | ADR 0116 exact resource receipt |
| Typed prerequisite unavailable | valid-looking `knowledge ask q --json`; probe explicitly returns `ESSENTIAL_UNAVAILABLE` | fixed bootstrap receipt, empty stdout, exit `1`, never JSON |
| Typed descriptor invalid | valid-looking `knowledge ask q --json`; validator explicitly returns `GRAPH_DESCRIPTOR_INVALID` | fixed bootstrap receipt, empty stdout, exit `1`, never JSON |
| Probe/validator bug is not classified | either conceptual seam directly raises an unexpected exception | exception escapes; no fixed bootstrap receipt is asserted |
| Bootstrap runtime import fault is not classified | Typer, Rich, or any member of their frozen transitive import closure raises `ModuleNotFoundError`, `ImportError`, `RuntimeError`, `TypeError`, `MemoryError`, or another `BaseException` | exception escapes; it is not `CLI_BOOTSTRAP_FAILED` |
| Graph import/factory bug is not classified | descriptor provider/import, graph factory/import, or graph construction directly raises the same exception matrix | exception escapes; it is not `CLI_BOOTSTRAP_FAILED` |
| Context dependency stays local | valid command selection followed by its owning adapter import/capability failure | no bootstrap receipt; the command-owned handled boundary applies when its contract authorizes one |

Tests also prove that parser/meta paths create no files, start no child, open no Data Root, read no config file, and do not load a Context adapter, Context-only business direct dependency, OCR, or Codex. Typed-verdict acceptance uses a narrow private seam; exception witnesses inject the direct call boundary without uninstalling, installing, or changing frozen dependencies.

## 10. Traceability and change rule

| Requirement | Frozen here |
|---|---|
| Spec stories 2–6 | one launcher identity, eight paths, launcher parity, Human/JSON mode |
| Spec stories 8, 13, 30, 34, 51–54 | raw public selectors and one-shot command arity |
| Spec stories 9–11 | entry ordering, scoped missing capability boundary, raw resource priority |
| Spec stories 69–73 | explicit future Context namespace extension, no plugin discovery |
| T02 acceptance | complete grammar, canonical tokens, defaults, mutual exclusion, route ownership, closed typed bootstrap verdicts, parser/bootstrap channels and exits |
| ADR 0089 / ADR 0091 | handled JSON outer and diagnostic item remain separate from entry failures; T02 does not bind seven concrete command identities |
| ADR 0110–ADR 0116 | immutable input, preflight-first ordering, no completion, fixed raw-resource behavior |
| ADR 0117 | exact Context-scoped root tokens and preserved Question-before-Configuration witnesses |
| ADR 0118 / ADR 0019 | one-Candidate/one-action/no-note V1 surface; future batch still expands to append-only decisions |
| ADR 0119 / ADR 0032 | inert full routing grammar/graph contains only static route facts; valid daily-command selection precedes exact owning-adapter import, and static composition does not eager-load unrelated Context dependencies |

Adding a ninth daily command, an alias, a short option, a repeatable option, a new root configuration option, a different review-action shape, shell completion, or a third launcher changes `GezhiCliGrammarV1` and requires an explicit contract revision. Changing only non-normative help prose or a command-owned Human result does not revise this grammar.
