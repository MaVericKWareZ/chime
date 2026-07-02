# Fuzzy-suggest IANA names on invalid timezone input

## Status

- **Category:** enhancement
- **State:** done
- **Triaged:** 2026-07-02 — both blockers landed on `feat/timezone-config` ([`01`](01-inline-tz-tracer.md), [`07`](07-config-cli-and-resolution-chain.md)); the resolution/error machinery this slice hooks into is all in HEAD: `chime.tz.resolve → (ZoneInfo, label)` raising `TzResolutionError`/`AmbiguousAbbreviationError` (both `ValueError`), the `chime config set timezone` handler already calls `tz.resolve(value)` for its echo, and `cmd_at` already funnels inline/`--tz`/config-tz parse failures through one `except ValueError`. Agent Brief written against HEAD. Three decisions the issue left open are resolved in the brief — **(1)** `suggest` is a new **pure** function in `chime.tz` (`difflib.get_close_matches` over `zoneinfo.available_timezones()`, tunable cutoff, ≤3 results), no I/O; **(2)** the primary error wording stays `unknown timezone: <spec>` — existing `test_cli`/`test_config` assertions depend on it, and the issue's illustrative "is not a valid timezone" phrasing would break three landed tests — so the suggestion is added as a **separate indented `did you mean:` continuation line**, never folded into the exception message (this also keeps `test_config.py`'s "did you mean" *not*-in-value assertion true); **(3)** `TzResolutionError` gains a `.spec` attribute (mirroring `AmbiguousAbbreviationError.candidates`) so both surfacing sites recover the offending token structurally instead of re-parsing the message — ambiguous and collision errors are explicitly excluded from suggestions. Cleared for dev.
- **Closed:** 2026-07-02 — implemented on `feat/timezone-config` via TDD (4 red→green cycles, 210→225 tests; `ruff check`/`format` clean). **(1)** `chime.tz.suggest` — pure, case-insensitive `difflib.get_close_matches` over `zoneinfo.available_timezones()`, ≤3 results, `[]` when nothing is close; cutoff tuned to `0.5` (documented: a region prefix like `europe/` dilutes the ratio, so the 0.6 default missed `londn`). **(2)** `TzResolutionError` gained a `.spec` attribute set only on the unknown-timezone raise; a single `chime.cli._print_tz_suggestions(e)` helper prints the indented `did you mean:` continuation and is shared by `_config_set` and `cmd_at` — it gates on `getattr(e, "spec", None)`, so ambiguous (`IST`) and collision errors get no suggestion line. **(3)** Discovered during TDD (not in the original brief): the parser's trailing-token detector only recognized known abbreviations / `/`-bearing tokens, so `chime at "9am londn"` failed as `bad time: 9amlondn` instead of `unknown timezone: londn`. Broadened `chime.parsers` (`_looks_like_source_tz`) so a digit-free trailing word that isn't a time keyword (`am/pm/a/p/at/tomorrow`, kept out via `_TIME_WORDS`) is routed to `resolve`; existing `" 3 : 30 pm "` / `"9 am"` parses are byte-identical. Verified end-to-end: `config set timezone londn` → `did you mean: Europe/London…` writing nothing; `xyzzy123` → no suggestion line; `IST` → disambiguation list only; `at "9am londn"` → same shape; valid `EDT` still echoes `America/New_York (EDT)`.

## Parent

[`prd.md`](../prd.md)

## What to build

Add `chime.tz.suggest(bad_spec) → list[str]` returning up to three close IANA zone matches for an invalid input. Implementation uses `difflib.get_close_matches` over `zoneinfo.available_timezones()` with a tunable cutoff. The function is pure (no I/O) so it tests in isolation.

Surface the suggestion in two error paths:

1. **`chime config set timezone <bad>`** — when `chime.tz.resolve(value)` raises an "unknown timezone" error, the CLI captures it, calls `chime.tz.suggest`, and prints `error: 'londn' is not a valid timezone\n       did you mean: Europe/London, Europe/Lisbon`. When `suggest` returns an empty list (no close match), the suggestion line is omitted.

2. **Inline parse** — `chime at "9am londn"` produces the same shape of error through the parser.

This is the substitute for the deferred `chime tz search` discovery command from the RFC — it covers the most common discovery use case without adding a new command namespace.

## Acceptance criteria

- [ ] `chime config set timezone londn` errors with `did you mean: Europe/London` (and possibly other close matches)
- [ ] `chime config set timezone kolkta` suggests `Asia/Kolkata`
- [ ] `chime config set timezone new_york` suggests `America/New_York`
- [ ] `chime at "9am londn"` errors with the same suggestion shape via the inline parser
- [ ] `chime.tz.suggest` returns at most 3 candidates
- [ ] `chime.tz.suggest` returns an empty list for inputs with no close match (e.g., `"xyzzy123"`); the CLI omits the suggestion line in that case
- [ ] `tests/test_tz.py` covers `suggest` in isolation, including the empty-list case
- [ ] `tests/test_cli.py` covers suggestion-surfacing in the `chime config set` error path
- [ ] `tests/test_parsers.py` covers suggestion-surfacing in the inline-parse error path

## Blocked by

- [`01-inline-tz-tracer.md`](01-inline-tz-tracer.md) — **landed.**
- [`07-config-cli-and-resolution-chain.md`](07-config-cli-and-resolution-chain.md) — **landed.** (No open blockers.)

## Agent Brief

> *This was generated by AI during triage.*

**Category:** enhancement
**Summary:** Add a pure `chime.tz.suggest(bad_spec) → list[str]` that returns up to three close IANA-zone matches for an invalid timezone spec, and surface those suggestions on the two existing "unknown timezone" error paths — `chime config set timezone <bad>` and inline parse (`chime at "9am <bad>"`). This is the RFC's deferred `chime tz search` discovery command, delivered as a suggestion line on the errors users already hit. Use the domain terms **source timezone**, **configured timezone**, **zone alias**, **ambiguous abbreviation** verbatim (see [`docs/CONTEXT.md`](../../../CONTEXT.md)).

**Current state of the codebase (HEAD on `feat/timezone-config`):**

- **`chime.tz`** exposes `resolve(spec) → (ZoneInfo, label)`. For an unknown spec it raises `TzResolutionError("unknown timezone: <spec>")`; for `IST/CST/BST/AST` it raises `AmbiguousAbbreviationError(abbrev, candidates)` (a subclass of `TzResolutionError` carrying a structured `.candidates` list); `TimezoneCollisionError` (also a `TzResolutionError` subclass) covers inline + `--tz` given together. `tz` imports only stdlib. There is **no `suggest()` yet** — this slice adds it.
- **`chime config set timezone <value>`** resolves the value via `tz.resolve(value)` for its canonical-name echo, then stores `zone.key`. It catches `ValueError` and prints `error: <message>`, exit 2, writing nothing. Ambiguous values (`IST`) already surface the disambiguation list from `AmbiguousAbbreviationError`; that behavior is covered by slice 07 tests and **must not change**.
- **Inline parse** — `chime at "9am <bad>"` flows through `parse_time`, which strips a trailing tz token and calls `tz.resolve`. The `at` handler catches `ValueError` from `parse_time` and prints `error: <message>`, exit 2. The bad token is consumed inside `parse_time`, so it is **not** directly available at the catch site.

**Desired behavior:**

- A new pure function `chime.tz.suggest(bad_spec: str) → list[str]` returns up to **3** IANA zone names closest to `bad_spec`, using `difflib.get_close_matches` over `zoneinfo.available_timezones()` with a tunable cutoff constant. No filesystem, environment, or network access — it tests in isolation. Returns `[]` when nothing is close enough.
- Both "unknown timezone" error paths, after printing the existing `error: unknown timezone: <spec>` line, print a **second indented continuation line** `       did you mean: Europe/London, Europe/Lisbon` listing the `suggest` results comma-joined. When `suggest` returns `[]`, that line is **omitted** entirely.
- Suggestions apply **only** to the plain unknown-timezone case. Ambiguous-abbreviation errors (which already carry their own candidate list) and collision errors get **no** `did you mean:` line.

**Key interfaces & decisions (resolved during triage):**

- **`suggest` is standalone and pure** — do not fold it into `resolve`; `resolve`'s signature and its existing error messages are unchanged.
- **Primary wording is unchanged:** keep `unknown timezone: <spec>`. Landed tests assert this substring; the suggestion is a *separate* line, not a rewrite of the message. Do **not** put "did you mean" inside any exception message string — it is a display-layer concern added by the CLI/parse error handlers.
- **`TzResolutionError` carries the offending spec:** add a `.spec` attribute set where `resolve` raises the unknown-timezone error (mirroring `AmbiguousAbbreviationError.candidates`). The two surfacing sites read `e.spec` to call `suggest(e.spec)` rather than parsing the message. For the `config set` path the spec is equivalently the typed `value`; prefer the structured attribute so both sites share one mechanism.
- **Excluding ambiguous/collision:** the surfacing sites must suggest only for a *plain* `TzResolutionError` — exclude `AmbiguousAbbreviationError` and `TimezoneCollisionError` (both subclasses). Gate on exact type or on the presence of `.spec`, whichever reads cleaner.

**Acceptance criteria:**

- [ ] `chime.tz.suggest("londn")` returns a list containing `Europe/London` (and possibly `Europe/Lisbon`), length ≤ 3
- [ ] `chime.tz.suggest("kolkta")` returns a list containing `Asia/Kolkata`
- [ ] `chime.tz.suggest("new_york")` returns a list containing `America/New_York`
- [ ] `chime.tz.suggest("xyzzy123")` returns `[]`
- [ ] `chime.tz.suggest` never returns more than 3 candidates for any input
- [ ] `chime config set timezone londn` prints `error: unknown timezone: londn` followed by a `did you mean: Europe/London…` line, exit 2, and writes nothing
- [ ] `chime config set timezone xyzzy123` prints the error with **no** `did you mean:` line
- [ ] `chime config set timezone IST` still prints the ambiguity disambiguation list and **no** `did you mean:` line (slice 07 behavior preserved)
- [ ] `chime at "9am londn"` prints the same error-plus-suggestion shape via the inline parser
- [ ] `tests/test_tz.py` covers `suggest` in isolation, including the empty-list case
- [ ] `tests/test_cli.py` covers suggestion-surfacing in the `chime config set` error path
- [ ] `tests/test_parsers.py` covers suggestion-surfacing in the inline-parse error path
- [ ] `ruff check` / `ruff format` clean; full suite green

**Out of scope:**

- The `chime tz` / `chime tz search` command namespace (deferred per PRD — this slice is its substitute).
- Changing the primary `unknown timezone: <spec>` wording, or the ambiguous/collision error messages.
- Adding suggestions anywhere other than the two named error paths.
- Any new runtime dependency — `difflib` and `zoneinfo` are stdlib; keep the zero-dependency pitch intact.
- Tuning `suggest` into fuzzy *matching that auto-corrects* — it only ever suggests; resolution still fails.
