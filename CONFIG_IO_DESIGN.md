# SAT Config IO — Architectural Decisions

**Status:** design agreed, not implemented
**Date:** 2026-09-02
**Source:** `INSTRUCTIONS.md` (exploration prompt), refined through design dialogue
**Scope:** accept `.toml` configuration input, produce a `.json` lock consumed at runtime, alongside the existing `pyconf` machinery

---

## 1. Model

TOML is **source**, written by humans. JSON is not an export or a report — it is the
artifact SAT executes against, in the spirit of `Cargo.lock`.

```
  ┌──────────────┐                                    ┌──────────────┐
  │ *.pyconf     │──── all-pyconf config ────────────▶│  in-memory   │
  │              │     (today's path, untouched)      │  Config      │
  └──────────────┘                                    └──────┬───────┘
                                                             │
  ┌──────────────┐    ┌───────────┐    ┌────────────┐        │
  │ *.toml       │───▶│  merge +  │───▶│ sat.lock.  │───────▶│  commands
  │ (+ any       │    │ platform  │    │   json     │  Json  │  compile
  │  pyconf)     │    │ collapse  │    │(gitignored)│ Reader │  prepare
  └──────────────┘    └───────────┘    └────────────┘        │  launcher
```

**Gate:** if any layer resolves to `.toml`, the whole config goes through the lock.
A configuration that is 100% pyconf keeps today's in-memory lazy path, unchanged.

---

## 2. Feasibility evidence

Measured against the real corpus: 461 `.pyconf` files in `SAT_SALOME`
(294 products, plus applications, jobs, machines).

| pyconf feature | usage | consequence |
|---|---|---|
| mappings / sequences / scalars | everywhere | native TOML |
| `$refs` (`$name`, `$VARS.sep`, `$APPLICATION.products.boost`) | **457 / 461 files** | must be layered onto TOML |
| `+` concatenation of refs | very common | must be layered onto TOML |
| backtick Python eval `` `sys.stderr` `` | **0 files** | out of scope |
| `@include` directives | **0 files** | out of scope |
| arithmetic beyond `+` (`*`, `/`, `%`) | **0 files** | out of scope |
| bare unquoted WORD values (`OpenMP`) | present | TOML forces quoting — an improvement |

The semantic surface TOML must cover is therefore small: mappings, sequences,
scalars, comments, references, and `+` concatenation.

### Premise correction

The source prompt states TOML has "interpolation of variables". It does not —
that is a deliberate non-goal of the format. Interpolation must be layered on
top as a string convention we parse ourselves (§4).

---

## 3. Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | TOML expresses references as shell-style `${SECTION.key}`, converted at load into `pyconf.Reference` / `Expression` objects | Reads well for the newcomer audience the feature targets; needs no pyconf internals |
| D2 | `JsonWriter` has two modes: **resolved** (the lock, default) and **raw** (`--raw`, templates preserved) | Resolved serves the runtime; raw is a diagnostic for inspecting templates pre-resolution |
| D3 | TOML is accepted at **all six layers** (INTERNAL, LOCAL, PROJECTS, APPLICATION, PRODUCTS, USER) | Uniform; no rule about where TOML is allowed |
| D4 | Both `X.pyconf` and `X.toml` for one layer is a **fatal error** naming both paths. SAT **refuses to write** a TOML-sourced layer | Silent precedence is exactly how two files drift apart unnoticed — the "double parsing" pitfall from the prompt |
| D5 | Parser is stdlib `tomllib` only. Python < 3.11 raises a clear error pointing at `.pyconf` | Zero dependencies; no parser code we own |
| D6 | The lock is **machine-local and gitignored**, fully resolved | A resolved SAT config contains absolute paths, distro tag and user name — it is not portable, so it must not pretend to be |
| D7 | The lock is **platform-evaluated**: products are collapsed to their single applicable section, other platforms discarded | See §5 — this is what removes the eager-resolution hazard |
| D8 | Collapsed products are stored **flat with a `__section__` marker**; `get_product_config` gains an early branch to use them verbatim | The platform decision is made exactly once, so runtime cannot diverge from the lock |
| D9 | `src/pyconf.py` is **not modified** | Hard constraint from the prompt |

### D5 note — the version constraint is softer than it looks

`tomllib` is stdlib only from Python 3.11, while SAT runs on the system Python of
every supported distro (`src/internal_config/distrib.pyconf`: CO/DB/FD/UB/MG/OS —
Rocky 9 = 3.9, Ubuntu 22.04 = 3.10, Debian 11 = 3.9).

But under the model in §1, **only the machine that generates the lock parses TOML**.
Build machines consume JSON, which is stdlib on every version. Old-Python platforms
can therefore consume locks; they simply cannot author from TOML.

---

## 4. The `${}` grammar

Minimal by design — it expresses what the corpus uses and nothing more.

```toml
source_dir    = "${APPLICATION.workdir}/SOURCES/${name}"
compil_script = "${name}${VARS.scriptExtension}"
archive       = "boost-${APPLICATION.products.boost}.tar.gz"
literal       = "costs $${100}"    # -> literal "${100}"
```

- `${A.b.c}` and `${A["x"]}` become `pyconf.Reference`
- adjacent parts become `pyconf.Expression(+, ...)`
- `$${` escapes a literal `${`
- an unterminated `${` is a **parse error**, never silently literal
- a string with no `${` is a plain string — no scan, no surprises

---

## 5. Platform evaluation (D7) — and the hazard it removes

### The hazard

`Reference.resolve` (`src/pyconf.py:932`) raises `ConfigResolutionError` when a
reference cannot be found, and resolution today is **lazy** — it happens on
attribute access, in whatever container context that access occurs.

Writing a fully-resolved lock means resolving the entire tree **eagerly**, which is
strictly more demanding than anything SAT does today. Every product file carries
platform-specific sections that are inert on the current machine, e.g. in
`boost.pyconf`:

```
default_win :
{
   compil_script : "boost_V" + $APPLICATION.products.boost + ".bat"
   archive_info : {archive_name : "boost-" + $APPLICATION.products.boost + "_windows.tar.gz"}
}
```

Nothing reads `default_win` on Linux today, so that reference is never evaluated.

### The resolution

SAT **already** discards non-matching platforms at merge time.
`__overwrite__` / `__condition__` (`src/pyconf.py:1614`) is evaluated against the
current machine:

```
__condition__ : "VARS.dist in ['CO9']"
__condition__ : "VARS.dist in ['FD32', 'UB20.04']"
__condition__ : "VARS.dist in ['CO7'] and APPLICATION.environ.build.VTK_SMP_IMPLEMENTATION_TYPE == 'TBB'"
```

So the merged tree is already platform-specific. What remains un-collapsed is only
the per-product section family (`default`, `default_win`, `version_1_71_0`,
`version_1_71_0_UB22_04`, …), collapsed later by `get_product_section`
(`src/product.py:395`).

**Running that collapse during lock generation, rather than at runtime, means
`default_win` is *dropped* on Linux rather than evaluated.** The eager-resolution
hazard disappears, and the lock becomes far smaller — one section per product
instead of the ~15 in `boost.pyconf`.

The lock is consequently platform- *and* application-specific, which is consistent
with D6.

> This revises an earlier position that the lock would mirror the config tree only.
> It now bakes in the platform/section decision, which is `product.py` territory.

---

## 6. Module layout

New package `src/configio/`. Nothing outside it imports `tomllib`.

| file | responsibility |
|---|---|
| `readers.py` | `Reader` ABC; `PyconfReader` (delegates to `src.pyconf`), `TomlReader`, `JsonReader`. Each returns a `src.pyconf.Config`. |
| `writers.py` | `Writer` ABC; `JsonWriter` (resolved / raw), `PyconfWriter` (wraps existing `__save__`). No `TomlWriter`. |
| `interp.py` | `${...}` grammar → `Reference` / `Expression`. The only new parser we own. |
| `discovery.py` | layer resolution; the two-files-one-layer error (D4). |
| `lock.py` | merge → platform collapse → write/read `sat.lock.json`; staleness. |

`readers.py` only *constructs* pyconf's public classes — it does not modify them (D9).
A `Config` rebuilt from a lock is a real `src.pyconf.Config`, so `product.py`,
`environment.py` and every command keep working unchanged; they see plain strings
where `Reference` objects used to be, which is what those resolve to anyway.

### On the `Reader` factory in the prompt

The prompt sketches one `Reader` ABC with three children, the TOML child lacking
`write`. A child that raises `NotImplementedError` on half its interface is a sign
the read and write axes want separating — hence `Reader` **and** `Writer` above:

```
Reader : PyconfReader, TomlReader, JsonReader
Writer : PyconfWriter, JsonWriter
```

Read-capable = {pyconf, toml, json}; write-capable = {pyconf, json}. No crippled child.

---

## 7. Lock generation

- **Location:** `<LOCAL.workdir>/.sat/<APPLICATION>.lock.json` *(assumption — not yet confirmed)*
- **Content:** merged tree with `__overwrite__` applied by the existing merger, then
  each product collapsed via `get_product_section` into a flat block carrying `__section__`
- **Staleness:** header records `sat_version`, `VARS.dist`, application name, and
  `(path, mtime, size)` for every source file consumed. Any mismatch regenerates.
  `sat config --relock` forces.
- **Shape:**

```json
{
  "__lock__": { "sat_version": "5.x", "dist": "UB24.04", "application": "MYAPP",
                "sources": [["applications/MYAPP.toml", 1756800000, 812]] },
  "PRODUCTS": {
    "boost": {
      "__section__": "version_1_71_0",
      "name": "boost",
      "patches": [],
      "source_dir": "/home/flo/ws/MYAPP/SOURCES/boost"
    }
  }
}
```

---

## 8. Integration points

| file | change |
|---|---|
| `commands/config.py:234` `get_config` | route the 6 load sites through `discovery`; add lock stage |
| `src/product.py:38` `get_product_config` | early branch on `__section__` (D8) |
| `commands/init.py` (3 sites), `commands/config.py:651`, `commands/jobs.py:1773` | refuse to write when the layer's source was TOML, naming file and key (D4) |

These are the only writers of config today; all go through `Config.__save__`.

---

## 9. Test strategy

The strongest asset is an **equivalence oracle**: `test/APPLI_TEST/APPLI_TEST.pyconf`
translated to TOML, asserting both paths produce identical resolved trees. Every
existing SAT behaviour then acts as a test for the TOML path.

- **Unit** (TDD, written first): `${}` grammar including escapes and malformed input;
  each reader/writer in isolation; ambiguity detection (D4); the `tomllib` version guard (D5).
- **Integration:** write a TOML app → `sat config -v` → `sat compile`, following the
  real user workflow.
- **Roundtrip:** (a) TOML artefact ≡ pyconf artefact — the oracle above;
  (b) `pyconf → json → Config` equivalence at resolved-value level.
- **Second pass**, driven by *"what could fail without the user knowing immediately?"* —
  candidates: a stale lock silently used after a source edit; a product collapsing to
  the wrong section on an untested distro; `$${` mis-escaped so a literal becomes a reference.
- **Final acceptance** (performed by the user, not this work): compile one SALOME
  application from a TOML configuration.

---

## 10. Rejected alternatives

| Rejected | Why |
|---|---|
| Keep verbatim pyconf expression syntax inside TOML strings | Mechanical migration, but opaque to TOML tooling and depends on a pyconf internal entry point |
| JSON as resolved-only, or raw-only | Resolved-only breaks the roundtrip requirement; raw-only defeats the "bash can parse it" motivation |
| Committed, machine-independent lock | A resolved SAT config is machine-specific; a portable lock would require classifying every key as portable or local |
| Vendored TOML parser, or `tomli` dependency | A subset parser that mis-reads valid TOML is a real hazard; a pip dependency fails on a fresh git clone. §3 D5 shows the constraint is soft |
| **Universal lock pipeline** (all configs, including pure pyconf) | Imposes eager resolution on all 461 existing config files; `ConfigResolutionError` is a hard raise, so this surfaces latent failures in configs that work today |
| **Sidecar lock** (written but never read back) | Contradicts the model — the lock would be a report, not the execution artifact |
| Baking `get_product_config`'s full derived output (install_dir, dependency order) into the lock | Duplicates ~300 lines of logic into the lock schema, which can then drift. Only the *section* decision is baked (D7/D8) |

---

## 11. Residual risks

1. **Migration is all-or-nothing per configuration, not per file.** Converting one
   file routes that user's remaining pyconf files through the lock. The platform
   collapse (§5) removes the reference hazard, but this is a larger behavioural step
   than "I changed one file" suggests. Must be stated in user documentation.
2. **`get_product_section` has real subtlety** — incremental mode, version *ranges*
   via `getRange_majorMinorPatch`, `_win` overlays. The lock generator must **call**
   it, never reimplement it.
3. **Windows** — the `default_win` collapse path cannot be tested on this machine.
4. **Lock location** (§7) is an unconfirmed assumption.

---

## 12. Out of scope (YAGNI)

Backtick evaluation, `@include`, arithmetic beyond `+`, a TOML writer, a vendored
TOML parser, a `RESOLVED` convenience section for jq, and committed portable locks.
