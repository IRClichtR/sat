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

### Application layer schema, measured

The 162 application files in `SAT_SALOME/applications` carry two top-level keys:
`APPLICATION` (162/162) and `__overwrite__` (127/162).

**`APPLICATION` scalars** — counts are files out of 162:

| key | files | type | observed |
|---|---|---|---|
| `name` | 162 | str | `'MEDCOUPLING-9.12.0'` |
| `workdir` | 162 | **Expression** | `$LOCAL.workdir + $VARS.sep + $APPLICATION.name + '-' + $VARS.dist` |
| `tag` | 161 | str | `'master'`, `'V9_12_0'` |
| `base` | 157 | str | `'no'`, `'base'` |
| `debug` | 150 | str | `'no'` |
| `python3` | 146 | str | `'yes'` |
| `dev` | 87 | str | `'no'` |
| `verbose` | 80 | str | `'no'` |
| `cmake_generator` | 30 | str | `'Visual Studio 16 2019'` |
| `cmake_build_type` | 12 | str | `'Release'` |
| `use_pyside` | 9 | str | `'no'` |
| `get_method` | 2 | str | `'git'` |
| `grid_to_test` | 1 | str | `'SALOME_V7'` |

Read by SAT but present in none of the 162: `hook`, `hpc`, `rm_products`,
`rm_products_for_all_distributions`, `version_salome`. Rare or legacy; the schema
must still admit them.

**Arrays:** `platform` (43 files, e.g. `['CO8', 'CO7', 'DB09', 'UB22.04']`) and
`dev_products` (1 file).

**Fixed-schema sub-tables:**

| table | files | keys |
|---|---|---|
| `test_base` | 161 | `name`, `tag` |
| `profile` | 89 | `launcher_name` 79, `product` 8; `exe` read by code |
| `virtual_app` | 42 | `name`, `application_name`; `catalog`, `configure` read by code |
| `properties` | 148 | `single_install_dir` 147, `pip` 146, `pip_install_dir` 146, `repo_dev` 87, `mesa_launcher_in_package` 79, `git_server` 61, `modules_use_pip` 13 |

`properties` is shared with product files. SAT reads about twenty property names in
total; only those seven ever appear at application level.

**Open key spaces** — no fixed schema, any name is legal:

- `environ`: `build` (151 files) and `launch` (146) are sub-tables; any other key is a
  plain variable set in both phases. 15 distinct direct names across the corpus.
- `products`: ~15,400 entries in three value shapes — string 11,484 (version or
  `'native'`), bool 2,924 (a bare name, no value), table 1,020 (override, with keys
  `tag` 879, `section` 720, `base` 562, `hpc` 492, `dev` 101, `verbose` 69).

**`__overwrite__`** is a sequence of mappings, each with a `__condition__` string and
dotted-path assignments such as `'APPLICATION.products.scipy' : '1.5.2'`.

### Four consequences for the TOML surface

| # | observation | consequence |
|---|---|---|
| 1 | `'yes'`/`'no'` are **strings**, and SAT compares against `'yes'` | TOML makes `true`/`false` natural. A file written with `debug = false` produces a value that compares unequal to `'no'` with no error. Either the reader coerces booleans in these positions, or the schema forbids them. Affects `debug`, `python3`, `dev`, `verbose`, `base`, `use_pyside` and most of `properties`. |
| 2 | 2,924 product entries are a **bare name** with no value | pyconf reads a lone key as `key : True` (`src/pyconf.py:1320`), and `get_product_config` turns that into `version = APPLICATION.tag` (`src/product.py:78`). TOML has no bare key, so the entry must be written `CONFIGURATION = true` or `CONFIGURATION = {}`. Note that `false` takes the *same* branch — `isinstance(version, bool)` — and product membership is by key presence only (`src/product.py:796`), so `SMESH = false` enables SMESH. The reader must refuse it. |
| 3 | `__overwrite__` keys are **dotted paths** | `"APPLICATION.products.scipy" = "1.5.2"` must stay quoted. Unquoted, TOML nests it into three tables: same characters, different document. |
| 4 | references are **420 nodes over 8 key paths**, in 162/162 files | 414 Expression, 6 Reference. `APPLICATION.workdir` 162, `environ.build.CONFIGURATION_ROOT_DIR` 151, `environ.build.RESTRICTED_ROOT_DIR` 75, `products.mesa.tag` 11, `environ.SALOME_APPLICATION_NAME` 6, `products.{cgal,cork,libigl}.tag` 5 each. A narrow surface, but present in every file — §4's grammar cannot be skipped. `$VARS.sep` alone accounts for 614 of the reference uses: it is `os.path.sep` (`commands/config.py:148`), so the mechanism is what keeps paths platform-neutral in the data layer. Alternatives to `${}` are rejected in §10. |

Items 1 and 2 are format-conversion decisions rather than parser decisions, and belong
to the TOML reader. Item 3 is a documentation hazard for whoever writes the files.

### A complete application file

What the end state looks like for the person writing configuration. This is
`SALOME-9.12.0-MPI.pyconf` transposed, with the products block trimmed to one entry of
each kind; everything else is as it appears in the real file. It parses with `tomllib`
and loads through `TomlReader`.

```toml
[APPLICATION]
name     = "SALOME-9.12.0-MPI"
workdir  = "${LOCAL.workdir}${VARS.sep}${APPLICATION.name}-${VARS.dist}"
tag      = "V9_12_0"
dev      = "no"      # quoted, never false -- SAT compares == "no" (D10)
verbose  = "no"
debug    = "no"
base     = "no"
python3  = "yes"
platform = ["CO7"]

[APPLICATION.environ]
SALOME_trace   = "local"
SALOME_MODULES = "SHAPER,SHAPERSTUDY,GEOM,SMESH,PARAVIS,YACS,JOBMANAGER"

[APPLICATION.environ.build]
CONFIGURATION_ROOT_DIR      = "${workdir}${VARS.sep}SOURCES${VARS.sep}CONFIGURATION"
RESTRICTED_ROOT_DIR         = "${workdir}${VARS.sep}SOURCES${VARS.sep}RESTRICTED"
SALOME_USE_64BIT_IDS        = "1"
VTK_SMP_IMPLEMENTATION_TYPE = "TBB"
SALOME_GMSH_HEADERS_STD     = "1"

[APPLICATION.environ.launch]
PYTHONIOENCODING     = "UTF_8"
SALOME_MODULES_ORDER = "SHAPER:SHAPERSTUDY:GEOM:SMESH"
ROOT_SALOME_INSTALL  = "$PRODUCT_ROOT_DIR"
SALOME_ON_DEMAND     = "HIDE"

[APPLICATION.products]
Python        = "native"              # pinned version, or "native"
boost         = "1.58.0"
CONFIGURATION = {}                    # canonical: no overrides, use APPLICATION.tag
KERNEL        = true                  # accepted alias of {}
MEDCOUPLING   = { tag = "V9_12_0", section = "default_MPI" }
mesa          = { tag = "${APPLICATION.tag}" }

[APPLICATION.profile]
launcher_name = "salome"

[APPLICATION.test_base]
name = "SALOME"
tag  = "SalomeV9"

[APPLICATION.properties]
mesa_launcher_in_package = "yes"      # properties are yes/no strings too
git_server               = "tuleap"
pip                      = "yes"
pip_install_dir          = "python"
single_install_dir       = "no"

[[__overwrite__]]
__condition__              = "VARS.dist in ['FD30']"
"APPLICATION.products.gcc" = "9.3.0"

[[__overwrite__]]
__condition__                = "VARS.dist in ['FD32']"
"APPLICATION.products.scipy" = "1.5.2"
```

**What the reader refuses**, so the file above is the only shape that loads:

```toml
[APPLICATION]
debug = false                 # ERROR -- a bool never equals "yes"/"no", so this
                              #          would silently read as "no" either way

[APPLICATION.products]
SMESH = false                 # ERROR -- false does not remove a product; membership
                              #          is by key, so delete the line instead

[[__overwrite__]]
"APPLICATION.products.SMESH" = false   # ERROR -- same rule, reached by the dotted
                                       #          key route rather than by nesting
```

Each raises at load time naming the key, before any configuration is built. The
reasoning is D10; the ergonomic cost and what would relax it are in §13.

There is no declared schema for these keys yet -- the inventory above is measured from
the corpus, not enforced by code -- so this snippet is the reference for what a written
file should look like until one exists.

**What to notice, in the order it bites:**

| | |
|---|---|
| `workdir` | `${LOCAL.workdir}` and `${VARS.sep}` come from layers this file never sees. The reference mechanism is what keeps the path platform-neutral (§2, consequence 4). |
| `${workdir}` in `environ.build` | a bare name, resolved by walking **up** the parent chain from `environ.build` to `APPLICATION`. It does not need the full path, exactly as in pyconf. |
| `ROOT_SALOME_INSTALL` | `"$PRODUCT_ROOT_DIR"` stays literal: `$` not followed by `{` is an ordinary character (§4). A shell variable passes through untouched. |
| `dev`, `debug`, `python3`, `properties.*` | quoted `"no"` / `"yes"`, never `false` / `true`. SAT compares against those strings, so a boolean would silently read as `"no"` (D10). |
| `CONFIGURATION = {}` | the canonical "include at `APPLICATION.tag`, no overrides". `KERNEL = true` is the accepted alias; `false` is refused (D10). |
| `VTK_SMP_IMPLEMENTATION_TYPE` | `"TBB"` was a bare unquoted `TBB` in pyconf. TOML forces the quotes, which removes a real ambiguity. |
| `[[__overwrite__]]` | an array of tables. The assignment keys **must stay quoted** -- unquoted, `APPLICATION.products.gcc` would nest into three tables instead of naming one key (§2, consequence 3). |

### What the lock costs and saves, measured

Every SAT command rebuilds the whole configuration from scratch
(`src/salomeTools.py:430`), including sub-commands invoked through the runner API. The
lock therefore replaces a repeated 461-file parse with a single JSON read.

On `MEDCOUPLING-9.12.0`, 42 products:

| operation | time | lock size |
|---|---|---|
| full `get_config` from pyconf | 0.081 s | — |
| `read_lock`, one JSON file | **0.002 s** | 51 KB |
| | **39x faster** | |

On `SALOME-9.12.0-MPI`, 148 products, the product layer alone parses in 0.278 s, and
`collapse_products` adds 0.005 s.

The figure that matters is not one command but a delegating one. `sat prepare`
(`commands/prepare.py:176-200`) calls `get_products_list` itself and then invokes
`clean`, `source` and `patch` through the API — **four full configuration builds for one
user action**:

| | `sat prepare` |
|---|---|
| today, pyconf | 0.32 s |
| via the lock | **0.01 s** |

Two conclusions follow, and they shape §8's integration rather than merely justifying it.

**The lock must be a file, not an in-memory cache.** Each sub-command is a separate
rebuild, so nothing held in process survives to the next one.

**`is_stale` runs four times per `sat prepare`**, which is why it compares mtime and size
rather than hashing 294 product files — the check has to be cheaper than the work it
avoids, four times over.

It also means **removing the four rebuilds is not the fix**. Passing one configuration
down from `prepare` to its delegates would save ~10 ms once the lock exists, while
introducing a re-entrancy requirement nothing in SAT has today: `get_product_section`
mutates the tree for incremental products, so the second command would see the first
command's overlay. Making repeated work cheap beats making the control flow cleverer.

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
| D6 | The lock is **machine-local and gitignored**, fully resolved (— *"fully" is contingent on §16*) | A resolved SAT config contains absolute paths, distro tag and user name — it is not portable, so it must not pretend to be |
| D7 | The lock is **platform-evaluated**: products are collapsed to their single applicable section, other platforms discarded | See §5 — this is what removes the eager-resolution hazard |
| D8 | Collapsed products are stored **flat with a `__section__` marker**; `get_product_config` gains an early branch to use them verbatim | The platform decision is made exactly once, so runtime cannot diverge from the lock |
| D9 | `src/pyconf.py` is **not modified** | Hard constraint from the prompt |
| D10 | A `bool` is valid **only** inside `APPLICATION.products`, and only as `true`. The canonical spelling of a product with no overrides is `{}`; `true` is an accepted alias; `false` is refused. Booleans anywhere else raise, naming the key | A bool never equals a str, so `debug = true` fails `== "yes"` (`src/compilation.py:59`) and reads as **off**, while `SMESH = false` passes `isinstance(version, bool)` (`src/product.py:77`) and reads as **enabled** -- both silently, in opposite directions. Coercion would need a complete list of yes/no-typed keys, which `properties` (open-ended, shared with product files) makes impossible to maintain; rejection needs no list. `{}` routes through the Mapping branch to the same `version = APPLICATION.tag` with no value to mistype. Two properties worth recording, since both are easy to re-open later: the rule is **positional**, so a bool reaching the products position by the `__overwrite__` dotted-key route (`"APPLICATION.products.SMESH" = false`) is refused too, where coercion would have silently assigned the *version string* `"no"`; and rejection is the **reversible** choice -- a file written under the strict rule stays valid if the rule is later relaxed to coercion, whereas a file written under coercion breaks if the rule is ever tightened. Measured cost to the corpus: zero. Across the 162 application files there is no bool anywhere outside `APPLICATION.products.<name>`, and none in any `__overwrite__` assignment. The cost is ergonomic -- see §13 |

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
| **Structured reference arrays** (`workdir = [{ref="LOCAL.workdir"}, ...]`) instead of `${}` strings | TOML parses the structure, so no string grammar is needed and values become machine-checkable -- but it is unpleasant to write for the common case, still needs a resolver, and would have to apply to all 8 reference paths including `products.cgal.tag`, where it is absurd |
| **Forbidding references in TOML**, resolving everything at lock time | `${workdir}` inside `environ.build` refers to a sibling key in the same file; there is no earlier point at which SAT could compute it. The user would be asked to paste an absolute path |
| **Alternative delimiters** (`{LOCAL.workdir}`, `@LOCAL.workdir`) | Cosmetic. `${}` is safer because `{` occurs in values such as `cmake_generator` and in CMake-flavoured strings generally |
| **Defaulting `workdir` in SAT code** and omitting it from TOML | Tempting -- 162 files carry only two formulas, so it is a convention wearing a costume. But `$VARS.sep` is `os.path.sep` (`commands/config.py:148`) and is referenced 614 times across the corpus, so the grammar is required by the other 151 files regardless. Removing `workdir` would save one key while keeping the whole parser, and would make the TOML and pyconf layers express the same thing differently -- the divergence §9's oracle exists to catch. Revisit as a follow-up, not as part of this feature |
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

---

## 13. Evolution — if SAT detaches further from pyconf

Several decisions here are shaped by one constraint: the object model and the value
conventions are pyconf's, because 461 files and every consumer in `src/` and
`commands/` assume them. That constraint is not permanent, and D10 in particular is
the visible cost of it. If pyconf ever stops being the lingua franca, the following
becomes available — in this order, because each step makes the next one safe.

**Step 1 — grow the oracle into coverage.** §9's differential test exists to compare
two loaders. Its more valuable second life is as the regression net that `src/product.py`
and `src/environment.py` have never had: 11 test files today, 3 of which touch either.
Nothing below should be attempted before that net exists.

**Step 2 — centralise the yes/no test.** 58 direct `== "yes"` / `== "no"` comparisons
across 14 files (`src/product.py` 19, `commands/package.py` 11, `src/environment.py` 10),
plus the two helpers `appli_test_property` and `product_test_property` already used at
33 call sites. Route all of them through one predicate that accepts `True` and `"yes"`
alike. This is mechanical and behaviour-preserving: pyconf files keep passing strings
and keep working.

Note the hidden half. Values are not only compared, they are **emitted** —
`src/environment.py:896` writes `pi.base` straight into a generated environment, and
formats it into a `module load` line two statements later. Emission sites cannot be
found by grepping for a comparison; they look like ordinary variable use, so this step
is an audit by reading, not by pattern.

**Step 3 — relax the reader.** Only once steps 1 and 2 hold can `_convert_bool` start
returning `True` where it currently raises. This is why D10 rejects rather than coerces:
every TOML file written under the strict rule is still valid the day the rule loosens,
so no user's configuration is invalidated by the change. Coercing today would spend
that option for an ergonomic gain available later anyway.

**What would still not follow.** Two residuals survive any amount of detachment,
because neither is about pyconf:

- `environ` is an open key space whose values become environment variables. `true`
  rendered as `"yes"` may not be what the consuming program wants — the corpus writes
  `SALOME_USE_64BIT_IDS = "1"`. No rule infers the right spelling; only the author knows.
- Distinguishing a bool typed into a string-valued key (`tag = true`) from a bool meant
  as a flag requires knowing which keys are string-typed. That is a **schema**, and §2's
  inventory is measured from the corpus rather than declared. Writing that schema down
  is the prerequisite, and it is a larger piece of work than anything above — it is also
  what would let TOML tooling validate a SAT configuration before SAT ever reads it.

---

## 14. Appendix — format correspondence (source material for user documentation)

Not a constraint on the implementation. This is the reference a person converting a
configuration needs, collected here so that `doc/src/configuration.rst` has something
to be written from once the feature ships. §11.1 already records that the
per-configuration migration rule must reach the user documentation; this table is the
other half of that debt.

Where a row says *resolved*, the lock stores the computed value rather than the
construct, which is why JSON is an execution artifact and not a source format.

| construct | pyconf | TOML | JSON lock |
|---|---|---|---|
| mapping | `k : { ... }` | `[a.b]` or `{ ... }` inline | object |
| sequence | `k : [ ... ]` | `k = [ ... ]` | array |
| string | `'v'` or `"v"` | `"v"` | string |
| bare word value | `TBB` (unquoted) | `"TBB"` — quotes required | string |
| integer / float | `8080` | `8080` | number |
| reference | `$VARS.sep` | `"${VARS.sep}"` | **resolved** (`--raw`: template kept) |
| concatenation | `$a + '-' + $b` | `"${a}-${b}"` | **resolved** |
| literal `$` | `'$PRODUCT_ROOT_DIR'` | `"$PRODUCT_ROOT_DIR"` — `$` without `{` | string |
| literal `${` | not expressible | `"$${100}"` | string |
| comment | `# ...` | `# ...` | **lost** — JSON has none |
| product, app tag | `KERNEL` (bare key) | `KERNEL = true` or `{}` | `true` or `{}` |
| product, pinned | `boost : '1.58.0'` | `boost = "1.58.0"` | string |
| product, overridden | `p : { tag : ... }` | `p = { tag = ... }` | object, `__section__` added (D8) |
| yes/no flag | `debug : 'no'` | `debug = "no"` — never `false` (D10) | `"no"` |
| conditional override | `__overwrite__ : [ ... ]` | `[[__overwrite__]]` | **applied**, then absent |
| platform sections | `default` / `default_win` / … | same | **collapsed** to one (D7) |
| `@include` | unused in corpus | none | none |
| backtick eval | unused in corpus | none | none |

Reading it as a migration guide, the rows that cost people time are the ones where
pyconf allows something TOML does not spell the same way: a bare word value now needs
quotes, a bare product key becomes `{}` or `true`, a yes/no flag stays a quoted string
rather than becoming a boolean (§3, D10), and an `__overwrite__` target must be quoted
so TOML does not nest it. The worked example in §2 shows all four in place.

---

## 15. Impact map — what changes for existing users

Tasks 1 to 7 add modules nothing calls; no existing behaviour can change. Tasks 8 to 11
modify code every SAT invocation runs. This section enumerates each mechanism they
touch, who notices, and what must be said to users before it ships.

The governing claim is §3's hard constraint: *a configuration that is 100% pyconf must
be bit-for-bit unaffected.* Table A is where that claim is actually at risk.

### A. Mechanisms that change for users who write no TOML at all

| # | mechanism | task, site | what changes | risk |
|---|---|---|---|---|
| A1 | `get_product_config` gains an early branch | 9, `src/product.py:38` | every product resolution for every user runs new code. The branch keys off `__section__`, absent from any pyconf tree, so the else path must be byte-identical | **highest.** 11 modules consume `get_product_config`/`get_product_section`, and the repo has 11 test files of which 3 touch `product` or `environment` at all |
| A2 | layer paths go through `resolve_layer` | 10, `commands/config.py` 282, 303, 372, 476, 524, 568 | path construction moves out of `get_config`. Same answer expected, different code producing it | high. Site 476 does not open a file today -- it hands a bare name to `streamOpener` and lets pyconf search `APPLICATIONPATH`. Taking that back changes *how* the application is found even when *what* is found is identical |
| A3 | two files for one layer becomes fatal | 7 + 10, `discovery.resolve_layer` | a stray `local.toml` beside `local.pyconf` stops the run with `AmbiguousLayerError` | low today, since no `.toml` exists anywhere. It is a new failure mode a user can create by accident later |
| A4 | `sat init`, `sat config` writes route through `writer_for_layer` | 11, `commands/init.py` ×3, `commands/config.py:651`, `commands/jobs.py:1773` | a pyconf layer still writes exactly as today | low, but it is five call sites on the write path of a command users run early |

**A1 and A2 are the whole risk of the feature.** Neither is TOML-specific: they are
edits to the shared path, made for the benefit of files that do not exist yet. The
mitigation is §9's oracle, which is why §13 step 1 says to grow it into real coverage
of `product.py` and `environment.py` before anything else.

### B. Mechanisms a user opts into by converting one file

Each is a consequence of the §1 gate: one `.toml` layer routes the whole configuration
through the lock.

| # | mechanism | what the user sees | warning owed |
|---|---|---|---|
| B1 | migration is per configuration, not per file | converting one file routes all layers, including untouched pyconf ones, through the lock | yes -- already recorded as §11.1 |
| B2 | resolution becomes eager | `ConfigResolutionError` at load instead of at first access. A latent broken reference that never fired now stops the run | yes. This is the reason §10 rejects the universal lock pipeline; the same hazard applies to whoever opts in |
| B3 | platform collapse | the lock holds one section per product, chosen for this machine. Other platforms' sections are gone from it | yes -- and it is why the lock must never be committed |
| B4 | a new artifact appears | `<LOCAL.workdir>/.sat/<APPLICATION>.lock.json` | yes, with the `.gitignore` line (see C2) |
| B5 | staleness is mtime and size based | an edit not reflected in the build, if mtime is unreliable. `--relock` is the escape hatch | yes -- document `--relock` next to the lock, not buried in options |
| B6 | Python 3.11 floor to author | Rocky 9 ships 3.9, Ubuntu 22.04 ships 3.10: those machines cannot generate a lock, though they can consume one | yes -- and state the asymmetry, because "SAT needs 3.11" is the wrong summary |
| B7 | configuration becomes unwritable | `sat init --base` against a TOML LOCAL layer refuses, by design | yes -- refusing is the feature, but only if the message says so |

### C. Gaps found while mapping this — one planned, two not

| # | finding | evidence |
|---|---|---|
| C1 | **`sat package` regenerates configuration and would emit pyconf for a TOML source.** `commands/package.py` writes `<product>.pyconf` (1400), `local.pyconf` (1468) and the project pyconf (1546) into the archive. A user whose source is TOML would ship a package containing pyconf -- silently converted, by a command with no stated position on the matter | Task 11 enumerates five `__save__` sites; there are **12** outside `pyconf.py` itself. The four in `package.py` and one in `src/logger.py:337` are not among the five |
| C2 | ~~`.gitignore` has no entry for the lock~~ -- **already planned.** Task 8 step 6 adds `*.lock.json` and `.sat/`. Listed here only because it was missed on a first pass and the artifact is the one D6 forbids committing | `plan/08-lock.md`, step 6 |
| C3 | **Every command dumps the full config to a pyconf log.** `src/logger.py:337` writes `<datehour>_<command>.pyconf` on every invocation. For a TOML user that dump is pyconf-formatted and holds resolved values rather than the lazy tree -- harmless, but it is the artifact people paste into bug reports, so its meaning changes | `src/logger.py:330-338` |

C1 is the one that needs a decision rather than a note: emit pyconf and say so, refuse
as Task 11 refuses, or defer packaging TOML-sourced configurations entirely.

### What must reach users before this ships

Ordered by how expensive the surprise is:

1. **B2, eager resolution** -- the only item that can break a configuration that works today, at the moment of opting in.
2. **B1, all-or-nothing migration** -- the gap between what was edited and what changed behaviour.
3. **B3 and B4**, the lock: what it is, where it lives, that it is machine-local, and that it must not be committed.
4. **B6**, the version floor, stated as authoring-only.
5. **A3**, that two files naming one layer is an error, with the message quoted so it is recognised when met.
6. **B5 and B7**, `--relock` and write refusal, as operational notes.

Items A1, A2 and A4 need no user-facing warning by definition: if they are visible,
they are bugs. They need review attention instead, which is the opposite allocation to
the list above and worth stating explicitly, since the instinct is to document what was
hardest to write rather than what is hardest to live with.


---

## 16. Open decision — eager resolution cannot complete

**Status: DECIDED — option 2. Implemented in Task 8; `collapse_products` calls
`get_product_config`. See "Outcome" at the end of this section.**

### What happens

Building a real configuration with the real `get_config`, collapsing it, then writing it
with `JsonWriter(resolved=True)`:

| application | products | result |
|---|---|---|
| `MEDCOUPLING-9.12.0` | 42 | succeeds — 51 KB lock |
| `SALOME-9.12.0-MPI` | 148 | **fails** |

```
ConfigResolutionError: unable to evaluate $install_dir
in the configuration default.environ
```

### Why it is structural, not a bug

`install_dir` appears in no product file. `get_product_config` computes it by calling
`get_install_dir` at runtime and attaches it to the product info it returns. A product
whose `environ` block references `$install_dir` therefore holds a reference that resolves
only *after* runtime derivation — while the writer runs before it, by construction.

| reference | occurrences | files | resolvable at lock time |
|---|---|---|---|
| `$install_dir` | **521** | **33** | **no** — attached by `get_install_dir` at runtime |
| `$name` | 1114 | 274 | yes — `name` is a key in the section |

Collapsing does not help: this is not a platform-dead section (§5) nor a latent broken
reference (§15 B2). It is a reference into a value that does not exist yet, by design.

Worth noting how it was nearly missed: `MEDCOUPLING-9.12.0` contains none of those 33
products, so it locks cleanly. Validating against one application would have shipped it.

### The options

| # | option | what changes | cost |
|---|---|---|---|
| **1** | **Partial lock.** Leave `environ` blocks unresolved in the lock; `environment.py` resolves them at runtime as it does today | §4, §7; Task 5 gains a per-region mode; Task 6 must revive pyconf `$`-syntax inside those regions | The lock stops being uniformly resolved, so it has two modes in one document. Directly reverses Task 6's rule that `JsonReader` parses no templates — a rule that exists to stop a raw dump being loaded as an execution input. The "bash and jq can read it" motivation (§10) weakens wherever a value is still a template |
| **2** | **Derive `install_dir` during collapse.** `collapse_products` calls `get_install_dir` and stores the result, so `$install_dir` resolves like any other key | D6, D8, §10; Task 8's `collapse_products` | Pulls one derived value into the lock, which §10 rejected for `get_product_config`'s output as a whole. That rejection was about **duplicating ~300 lines**; *calling* the existing function is not duplication — it is the same principle Task 8 already applies to `get_product_section`. `is_stale` gains a new reason to invalidate, since `install_dir` depends on `base` and `install_mode`, which can change with no source file changing |
| **3** | **Exclude affected products.** Products with runtime-only references are not locked and fall back to the pyconf path | §1, D6 | Breaks the model: the lock is no longer the artifact SAT executes against, and a configuration is half locked. Rejected unless 1 and 2 both prove worse |
| **4** | **Resolve nothing; lock raw only.** The lock becomes a normalised source cache, not an execution artifact | §1, §7, D2, D6 | Abandons the `Cargo.lock` model the feature is built on, and the eager-resolution benefit with it. Listed for completeness |

### Recommendation

**Option 2.** It keeps one representation, one resolution pass, and one implementation of
the install-directory decision. The drift §10 feared comes from reimplementing a
decision, not from invoking it — and Task 8 already establishes invoking as the pattern.
Option 1 is the alternative worth taking seriously if pulling derived values into the
lock proves to cascade: the moment `install_dir` is in there, the next reviewer will ask
why `source_dir` and `build_dir` are not.

The deciding question is narrow enough to state: **is `install_dir` part of the decision
the lock records, or part of the work the lock feeds?** Option 2 says the former, option 1
the latter. Nothing else in this document answers it.

### Outcome

Option 2 was taken. `collapse_products` calls `get_product_config` rather than
`get_product_section`, so the lock stores the product info SAT actually derived --
`install_dir`, `install_mode` and the rest -- and `$install_dir` resolves like any other
key. One call, no reimplementation, the same principle Task 8 already applies to section
selection.

`get_product_config` keeps `install_dir_save` bookkeeping for repeat calls, so a second
collapse adds that one key while every value stays identical. That is pinned by
`test_collapsing_twice_changes_no_value`.

**The `$install_dir` failure class is gone.** Locking all 162 applications:

| | applications |
|---|---|
| lock cleanly | **116** |
| fail | **46** |

The 46 fall into three classes. **Two are genuine upstream configuration bugs; the third
is an artifact of the measurement** and is not a bug at all:

| apps | failure | verdict |
|---|---|---|
| 36 | `TypeError: can only concatenate str (not "bool") to str` | **bug** — see U1 below |
| 4 | `AttributeError: Unknown pyconf key: 'version_6_1_0_MPI'` | **bug** — see U2 below |
| 6 | `SatException: openssl has version 1.1.1n but is declared as native` | **not a bug** — Windows applications resolved on Linux. `openssl.pyconf` is incremental; `default` sets `get_source : "native"` and `default_win` overrides it to `"archive"`. On Windows the overlay yields `archive` and resolves correctly. Resolving a Windows application on Linux is not a supported operation, and the lock is platform-specific by construction (D7) -- so this is the measurement reaching somewhere it should not have |

So **40 of 162 applications, 25%, are blocked by two fixable lines**, and the lock is what
found them. Neither is a regression: each fails today too, later and with less context.

### The two upstream fixes

**U1 — `OPENTURNS_SALOME.pyconf`, `default` section: delete the `compil_script` line.**
Affects 36 applications.

```
build_source  : "cmake"           # <- not "script"
compil_script : $name + "-" + $APPLICATION.products.OPENTURNS_SALOME + $VARS.scriptExtension
```

The expression builds a script filename from the version the application requested. That
idiom is correct for a **prerequisite** — 72 product files use it, and applications pin
those versions. But `OPENTURNS_SALOME` is declared with a bare key in **all 46** of the
applications that include it, and pinned in none, so the reference resolves to `True` and
the concatenation cannot ever succeed.

It has gone unnoticed because the key is **dead**: `build_source` is `"cmake"`, and
`compil_script` is only read when `product_has_script()` is true, which requires
`build_source.lower() == 'script'` (`src/product.py:1161`). Nothing reads the key, so its
expression has never had to evaluate.

Deleting the line is the right fix, not pinning a version: a cmake-built product has no
compile script. It is dead configuration that happens to be wrong.

*Scope check, because the obvious worry is that this is systemic:* of 55 products ever
declared bare — including the 15 always-bare internally-developed ones such as `SHAPER`,
`SHAPERSTUDY`, `YDEFX` and `PARAVISADDONS` — **`OPENTURNS_SALOME` is the only one whose
file references `$APPLICATION.products.<self>`**. `KERNEL`, `GUI`, `GEOM` and `SMESH` are
not even always-bare, and never name their own version. The modules are immune because a
git checkout at the application tag never needs its version in a filename. The single
cross-product reference in the corpus is `hdf5_openmpi` reading `hdf5`, which is pinned in
161 of 162 applications. **One file using the prerequisite idiom while consumed as a
module — not a class.**

**U2 — `SALOME-10.0.0*.pyconf`: `ParaView` asks for a section that does not exist.**
Affects 4 applications.

```
ParaView : {tag:'6.1.0.c61dcc8ee0', base:'no', section:'version_6_1_0_MPI', hpc:'yes'}
```

`ParaView.pyconf` defines `default`, `version_6_0_0`, `version_6_0_0_MPI`,
`version_6_0_0_MPI_CO9`, `version_6_0_0_MPI_FD44` and `version_6_0_0_win`. There is no
`version_6_1_0_MPI` anywhere in the corpus. An explicit `section:` bypasses version
matching entirely (`src/product.py:429`), so the miss is immediate rather than falling
back to `default`.

### Consequent open question

What should lock generation do when a configuration has a latent error of this kind?

- **Abort, naming the key and the expression.** Strictly more useful than today's failure,
  which arrives during a build. But 28% of applications cannot adopt TOML until their
  configuration is fixed -- and 36 of them need one line changed in one product file.
- **Resolve what resolves, keep the rest raw.** Preserves today's behaviour exactly: the
  broken value fails when read, not before. Reintroduces option 1's two-modes problem.

**Decided: abort — but report every failure, not the first.**

Aborting is right: a latent error found at load time, with the key and the expression
named, beats the same error arriving mid-build. But dying on the first unresolvable value
is what made this investigation expensive. The first run reported one `TypeError` with no
indication that 35 other applications shared one cause, or that a second, unrelated bug
accounted for 4 more, or that 6 of the failures were not bugs at all.

So lock generation **collects** unresolvable values and reports them together:

- group by cause, not by application — one entry for U1, not 36
- name the key path, the expression, and the value that broke it
  (`$APPLICATION.products.OPENTURNS_SALOME` resolved to `True`)
- state the count of affected layers or products

Same strictness, and the first encounter becomes an actionable list instead of a puzzle.
This shapes Task 10's error path, and Task 5's writer needs to surface per-value failures
rather than letting the first exception escape.
