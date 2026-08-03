# Gezhi CLI Command Contract v1

## 1. Status and authority

This document freezes `GezhiCliGrammarV1`, the public Windows command grammar shared by the eight V1 daily commands. It is the executable contract for [Parent Spec #1](https://github.com/Dulealex/Gezhi/issues/1) and [T02 / Issue #3](https://github.com/Dulealex/Gezhi/issues/3).

The following sources remain authoritative and are not reopened here:

- [ADR 0023](../adr/0023-ship-one-windows-cli-before-any-gui.md): one Windows CLI, Human and JSON presentation.
- [ADR 0024](../adr/0024-limit-the-daily-cli-to-eight-commands.md): the eight-command public surface.
- [ADR 0032](../adr/0032-use-static-composition-and-context-deep-modules.md): static composition and Context deep modules.
- [CLI JSON v1](./cli-json-v1.md) and [CLI Diagnostics v1](./cli-diagnostics-v1.md): the shared JSON envelope and diagnostic item.
- [ADR 0110](../adr/0110-run-a-decoded-argv-resource-preflight-before-typer.md) through [ADR 0116](../adr/0116-return-2-with-one-fixed-stderr-line-for-raw-argv-resource-violation.md): bootstrap, immutable argv, completion shutdown, resource ceilings, and the fixed resource-failure presenter.

This contract owns public token spelling, arity, option placement, defaults, mutual exclusion, launcher parity, and the boundary between entry failures and handled command outcomes. Command-specific result objects, diagnostics, Human result copy, and domain validation remain owned by T03 through T06.

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

### 2.2 Command paths and JSON identities

The exact case-sensitive lowercase ASCII paths and their `CliResultEnvelopeV1.command` identities are:

| Public path | JSON `command` | Owning module |
|---|---|---|
| `doctor` | `doctor` | Operations |
| `status` | `status` | Operations |
| `literature add` | `literature.add` | Literature |
| `literature resume` | `literature.resume` | Literature |
| `literature review` | `literature.review` | Literature |
| `knowledge search` | `knowledge.search` | Knowledge |
| `knowledge show` | `knowledge.show` | Knowledge |
| `knowledge ask` | `knowledge.ask` | Knowledge |

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

There is no `--config`, `--data-root`, `--human`, `--quiet`, `--verbose`, `--model`, `--reasoning`, `--provider`, `--timeout`, `--force`, or `--prepare-only`. There are no short aliases. Configuration names and precedence are frozen in [Configuration v1](./configuration-v1.md).

### 4.2 Per-command surface

| Command | Required input | Optional input | Default and parser rule |
|---|---|---|---|
| `doctor` | none | `--json` | Human when `--json` is absent |
| `status` | none | positional `WORK_ID`, `--json` | absent `WORK_ID` means overall status; one value means Work status |
| `literature add` | positional `PDF_PATH` | `--work-id WORK_ID`, `--doi DOI`, `--arxiv-id ARXIV_ID`, `--citation CITATION`, `--json` | every optional value is absent unless supplied |
| `literature resume` | positional `WORK_ID` | `--json` | no interactive prompt or implicit current Work |
| `literature review` | positional `CANDIDATE_ID`; exactly one action flag | `--json` | no default action; `--accept`, `--reject`, and `--defer` are mutually exclusive |
| `knowledge search` | positional `QUERY` | `--json` | no CLI result-limit option; T05 owns the fixed retrieval surface |
| `knowledge show` | positional `CANDIDATE_ID` | `--json` | no implicit last Candidate |
| `knowledge ask` | positional `QUESTION` | `--json` | one-shot, one Question; no implicit session or history |

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
- missing review action is a parser failure; an invalid Candidate ID reaches Literature validation;
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

Mode is authoritative only after the complete leaf grammar succeeds. Configuration invalidity, Data Root failure, environment capability failure, and domain validation that occur after that point must respect the selected mode. The command-specific contracts own their outcome, diagnostic, exit, and Human copy; this contract does not invent those seven unfinished command payloads.

The exact Human result prose for T03 through T06 is not a prerequisite for implementing or testing a JSON-only slice. A JSON-only slice can assert the command identity, closed envelope, command-specific result/diagnostic contract, stdout isolation, and exit mapping while its Human adapter remains blocked by its own ticket.

Only `knowledge.ask --json` currently adopts ADR 0107 through ADR 0109 binary fd1 presentation. Other commands and Human mode must not silently reuse that concrete buffer cap, writer, cancellation seal, or hard-fail behavior.

## 7. Entry ordering

For every launcher invocation, observable ordering is:

1. enter the common bootstrap seam and form one immutable argv snapshot;
2. run `RawArgvPreflightV1` exactly once over the suffix;
3. on resource rejection, invoke only the ADR 0116 presenter and return `2`;
4. on PASS, lazy-import Typer, Rich, static command composition, and adapters;
5. construct the command graph with completion disabled;
6. process meta invocation or grammar against the same suffix;
7. on grammar failure, use `ParserFailureV1` and do not enter a handled adapter;
8. on a valid daily command, hand raw values, raw CLI config patch, and mode to exactly one owning adapter.

No configuration file, environment configuration patch, Data Root, Context store, OCR runtime, Codex runtime, model, child process, cancellation bridge, or durable asset may be touched before Step 8. A command-owned contract may impose stricter ordering after Step 8; in particular, the existing `knowledge.ask` Question/configuration/cancellation order remains authoritative.

## 8. Parser and bootstrap failure contract

### 8.1 Closed normal entry outcomes

| Entry outcome | Trigger | Complete stdout | Complete stderr | Normal exit | Handled result? |
|---|---|---|---|---:|---|
| `RAW_ARGV_RESOURCE_LIMIT_EXCEEDED` | ADR 0115 authoritative resource predicate | empty | exact `b"gezhi: error: command-line input exceeds safety limits\r\n"` | `2` | no |
| `CLI_BOOTSTRAP_FAILED` | a project-classified framework import, static graph import, or graph-construction failure after preflight PASS | empty | exact `b"gezhi: error: cli bootstrap failed\r\n"` | `1` | no |
| `CLI_ARGUMENT_FAILED` | unknown/missing/extra/repeated/conflicting token under Sections 3–5 | empty | exact `b"gezhi: error: invalid command line\r\n"` | `2` | no |

The two T02 lines are fixed lowercase ASCII except the product name, contain no BOM, ANSI, usage text, input echo, path, exception detail, traceback, JSON, or second newline. They are not `CliDiagnosticItemV1` values and do not create a cancellation profile or persistent diagnostic.

A project bootstrap classifier may translate only the closed failures it can prove occurred in framework import, command-graph import, or graph construction. Malformed `sys.argv`, snapshot allocation failure, `MemoryError`, `RecursionError`, `KeyboardInterrupt`, `SystemExit`, `GeneratorExit`, process crash, external termination, and an unexpected implementation exception must not be relabeled as one of these normal outcomes. They retain operating-system/runtime behavior and may have no application-controlled exit or complete output.

If presentation of a T02 fixed line itself cannot complete, Gezhi must not write stdout, switch to JSON/Human fallback, echo the exception, or retry through another presenter. That transport failure does not create a complete entry receipt; it may leave stderr empty or an exact prefix. Only a completed line plus the listed normal return is the corresponding complete receipt.

### 8.2 Parser classification

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
| Empty config token | `--knowledge-data-root= knowledge ask q --json` | grammar succeeds; handled configuration owns rejection |
| Dash-prefixed operand | `knowledge search -- --literal` | raw Query is `--literal`; Human mode |
| Missing operand | `knowledge ask --json` | fixed parser stderr, empty stdout, exit `2` |
| Extra operand | `knowledge show cand_a cand_b --json` | fixed parser stderr, empty stdout, exit `2` |
| Unknown option | `doctor --verbose` | fixed parser stderr, empty stdout, exit `2` |
| Wrong scope | `knowledge --json ask q` | fixed parser stderr, empty stdout, exit `2` |
| Late root option | `knowledge ask q --knowledge-data-root D:\K` | fixed parser stderr, empty stdout, exit `2` |
| Repeated option | `doctor --json --json` | fixed parser stderr, empty stdout, exit `2` |
| Missing review action | `literature review cand_example --json` | fixed parser stderr, empty stdout, exit `2` |
| Conflicting review action | `literature review cand_example --accept --defer --json` | fixed parser stderr, empty stdout, exit `2` |
| Completion disabled | `--show-completion` | fixed parser stderr, empty stdout, exit `2` |
| Invalid version combination | `--version doctor` | fixed parser stderr, empty stdout, exit `2` |
| Literal JSON on bad command | `unknown --json` | parser failure, never JSON |
| Raw ceiling beats grammar | any ADR 0115-over-limit suffix containing `--json` | ADR 0116 exact resource receipt |
| Bootstrap failure beats mode | valid-looking `knowledge ask q --json` with a classified missing Typer/graph dependency | fixed bootstrap receipt, never JSON |

Tests also prove that parser/meta paths create no files, start no child, open no Data Root, read no config file, and do not load OCR or Codex.

## 10. Traceability and change rule

| Requirement | Frozen here |
|---|---|
| Spec stories 2–6 | one launcher identity, eight paths, launcher parity, Human/JSON mode |
| Spec stories 8, 13, 30, 34, 51–54 | raw public selectors and one-shot command arity |
| Spec stories 9–11 | entry ordering, scoped missing capability boundary, raw resource priority |
| Spec stories 69–73 | explicit future Context namespace extension, no plugin discovery |
| T02 acceptance | complete grammar, canonical tokens, defaults, mutual exclusion, parser/bootstrap channels and exits |
| ADR 0089 / ADR 0091 | handled JSON outer and diagnostic item remain separate from entry failures |
| ADR 0110–ADR 0116 | immutable input, preflight-first ordering, no completion, fixed raw-resource behavior |

Adding a ninth daily command, an alias, a short option, a repeatable option, a new root configuration option, a different review-action shape, shell completion, or a third launcher changes `GezhiCliGrammarV1` and requires an explicit contract revision. Changing only non-normative help prose or a command-owned Human result does not revise this grammar.
