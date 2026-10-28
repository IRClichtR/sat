# SAT `--venv` feature — Design

Status: design approved in brainstorming (2026-10-09), pending written-spec review.
Branch: `feat/venv_compilation`. Source request: `INSTRUCTIONS.md`.

## 1. Goal

Let SAT build and run a **native** SALOME application against a Python virtual
environment, so that the Python prerequisites of the application can be installed
with pip, without root, instead of through system packages (`apt`/`rpm`).

Intended workflow (from `INSTRUCTIONS.md`): create a venv → check dependencies in
the venv → install missing dependencies with a sat command → compile with
`--venv`, combined with the usual options (`-p`, `--with_children`, ...).

Architecture imperatives:
- Break nothing: a user who never passes `--venv` sees no behaviour change.
- Anything that has to be switched on (venv, wrapper) can be activated or
  reverted with one simple command.

## 2. Findings (answers to the exploratory questions)

### 2.1 What prevents SAT from working with a venv today

Running SAT itself is not the problem: `SAT/sat` uses `#!/usr/bin/env python`,
which resolves to the venv's interpreter once the venv is activated, and SAT's only
third-party dependency is `distro`. The blockers are in the environment SAT builds
for compilation and runtime:

| Blocker | Location |
|---|---|
| `set_nativ_env` hardcodes `PYTHON_ROOT_DIR=/usr` and `PYTHONBIN=/usr/bin/python3`, so builds, `pip_install.sh` and `runSalome.py` target the system interpreter | `SAT_SALOME/products/env_scripts/Python.py` (project, not SAT) |
| Native Python products (numpy, scipy, Babel...) are checked **only** via rpm/apt; a pip-installed package shows as KO and the only remedy is a root install | `commands/config.py:859` (`check_install_system`), `src/product.py:1306` (`check_system_dep`) |
| When Python is **compiled** (not native), `Python.py::set_env` sets `PYTHONHOME`, which disables any venv | project env script |
| `distro` missing makes SAT `sys.exit(-1)` at import time, so SAT cannot even start to create a venv on a clean Python ≥ 3.8 | `src/architecture.py:30-40` |
| Generated launchers / env files would freeze `/usr/bin/python3` | consequence of the first row |

### 2.2 Where pip products come from today

| Product declaration | Source | Code |
|---|---|---|
| `'native'` | Nothing is downloaded or installed; SAT expects the OS package | `compile.py:288`, `source.py:423` |
| Versioned + product `pip:"yes"` + app `properties.pip:'yes'` | **PyPI**: `python -m pip download` into `$archive_dir/wheels`, then `pip install --no-index --find-links` | `source.py:188`, `compile.py:535-580`, `internal_config/salomeTools.pyconf:20` |
| Versioned + `pip:"no"` (`*_no_pip` sections), or Windows (`pip_install_whl`) | FTP archive (`ARCHIVEFTP`) | `source.py:194` |

Both native and non-native SALOME apps set `pip_install_dir : 'python'`, so versioned
pip products are installed into the site-packages of whichever `python` comes first in
`PATH`. With the venv first in `PATH`, that is already the venv.

**SAT's existing "pip mode" is not a venv.** It was introduced in 2019 (sat #17206,
`c4f41ce`) and is triggered by `APPLICATION.properties.pip:'yes'` +
`pip_install_dir:'python'`. Pip products are installed into the site-packages of the
Python **that SAT compiled itself**, `INSTALL/Python` (`src/product.py:553-559`, "we
assume python is installed in install_dir/Python"). Its isolation comes from that
private interpreter; this is the Windows / non-native model (§2.5).

The block commented out in `src/environment.py:612-616` ("skip pip products when pip
is activated and installation is done in python") belongs to that mode. It was added in
`c4f41ce` (2019-07-17) to skip the environment of pip products installed in Python. It
was disabled in `5e7b4c7` (2019-09-06, "bug variables ROOT_DIR des produits pip
absentes quand install dans python") because skipping the product also skipped its
env script, which dropped variables like `NUMPY_INCLUDE_DIR` / `<PRODUCT>_ROOT_DIR` that
dependent products' CMake needs. Since then the env script runs with
`prereq_dir = INSTALL/Python`. This design does not touch that block.

**PEP 668 blocker in native apps.** In a native app, `INSTALL/Python` does not exist and
`python -m pip install` targets the **system** interpreter. On Ubuntu 24.04 that
interpreter is marked externally managed (`/usr/lib/python3.12/EXTERNALLY-MANAGED`, PEP
668), and SAT's command (`INTERNAL.command.pip_install`) passes neither `--user` nor
`--break-system-packages`. So a versioned `pip:"yes"` product in a native app is
expected to fail to install today (and would need root anyway). With `--venv`, `python`
resolves to the venv and the same code path works unchanged. This is a second reason for
the feature, beyond native products (verified in §7.2 step 7).

### 2.3 Cost

SAT side: one new module (`src/venv.py`), a single hook in `src/environment.py`,
small additions in `src/system.py` and `src/architecture.py`, and option
declarations in the commands. No change is needed in the project (SAT_SALOME).
None of the 58 module shebangs need to change.

### 2.4 Destructiveness

None. The venv is a separate directory. The only persistent state is one key,
`LOCAL.venv`, in `data/local.pyconf`. No git-tracked file is modified.

### 2.5 Cross-platform

- `venv` is standard library on every OS; only the layout differs
  (`bin/python` vs `Scripts\python.exe`), and one helper handles it.
- **Windows** apps declare **zero** native products. SAT builds Python itself
  (`Python-3.9.bat`) into a private `INSTALL/Python`, and pip products are installed
  into that private interpreter (`pip_install_whl.bat`). That Python is already an
  isolated, user-owned environment, which is what `--venv` gives Linux native apps.
  The same is true of non-native Linux apps. `--venv` is therefore refused when
  `Python` is not native (see D11), and the code is still written portably.
- System-package installation (`--install_system`) is Linux-only (`apt-get`, `dnf`/`yum`).
  It does not depend on `--venv`, so native applications without a venv benefit too.

## 3. Decisions

| # | Decision | Rejected alternatives (and why) |
|---|---|---|
| D1 | The venv hosts the application's **native Python products** (those with `pip:"yes"`); SALOME is built and run against the venv interpreter. | Venv only for running SAT (doesn't address the root/apt problem) |
| D2 | Native products are split into two groups: **venv group** = `native` + `properties.pip:"yes"`; **system group** = every other native product (boost, qt, PyQt, sip, opencv, nlopt, lapack...). The product `name` is used as the pip distribution name (as `compile.py` already does). | — |
| D3 | Dependency installation is a **separate step before compile** (`sat config --check_system --venv --install_venv`); `compile` keeps treating native products as native. | Reuse the compile-time pip path for native products (mixes up the meaning of `native`); no new mechanism (no install command, contradicts the workflow) |
| D4 | Two separate, symmetric opt-ins on `sat config --check_system`: `--install_venv` (pip into the venv, no root; **requires `--venv`**) and `--install_system` (`sudo apt-get/dnf install -y` after showing the command and asking for confirmation; **independent of `--venv`**: without it, it installs every missing native product, as today's model expects; with it, only the system group). Both can be given in one call (venv first, then system). | Single flag doing both (bundles a root action with a harmless one); print-only (contradicts "install with a sat command"); bare `--install` (ambiguous: install what, where?); `--install_venv` implying `--venv` (a second way to enable venv mode, see D19) |
| D5 | `--venv` on commands is **boolean**; the path is read from `LOCAL.venv`. | Optional path value (the option parser has no optional-value type); implicit detection from `sys.prefix != sys.base_prefix` (silent behaviour change) |
| D6 | `--venv` is declared on `config` and on **every environment-building command**: `compile`, `configure`, `make`, `makeinstall`, `script`, `environ`, `launcher`, `application`, `test`. `package` is out of scope. `run` and `shell` are left out: they build no environment, and `run` forwards all its arguments to the launcher, whose venv shebang (D18) already covers it. | Minimal set (diverging build environments between commands); global `sat --venv` option (differs from the requested syntax) |
| D7 | `sat init --venv <path>` writes a **wrapper** `<venv>/bin/sat` (`Scripts\sat.bat` on Windows) that runs `SAT/sat` with the venv's interpreter. No shebang is modified. | Activate only (easy to forget); rewrite the `SAT/sat` shebang (dirties a tracked file, conflicts on pull) |
| D8 | *(amended 2026-10-13)* `sat init --venv` takes either no value (→ `$LOCAL.workdir/venv`), a path, or `forget` (forgets `LOCAL.venv`; the venv on disk is left alone). The venv is always stored in `LOCAL.venv` as an absolute path; there is no `default` keyword. SAT's option parser (getopt) has no optional values, so `commands/init.py` turns a bare `--venv` (last argument, or followed by another option) into `--venv=<workdir>/venv` before parsing. | Path required (inconsistent with the `'default'` convention of `local.pyconf`) |
| D9 | The venv is always created with `--system-site-packages`, so system Python modules (PyQt5, sip...) stay importable and venv packages take precedence. | Fully isolated venv (PyQt from PyPI bundles its own Qt, so there is an ABI clash with the system Qt SALOME is built against); configurable (YAGNI) |
| D10 | `--install_venv` installs **unpinned** by default. Optional pins go in `APPLICATION.venv : { numpy : '1.26.4' }` and can be overridden with `-o`. (When the app has no `venv` section, the `-o` rule must create the mapping with quoted keys: `-o "APPLICATION.venv={'numpy':'1.26.4'}"`; the dotted form only works on an existing section.) | Unpinned only (not reproducible); apt-equivalent version (fragile Debian→PEP 440 mapping) |
| D11 | `--venv` requires `Python` to be `native` in the application; otherwise SAT errors with "this application builds its own Python, already isolated". | — |
| D12 | Environment overrides live **in SAT only**, in a hook placed right after the native Python env script runs. Overridden: `PATH` (prepend `<venv>/bin`), `VIRTUAL_ENV`, `PYTHONBIN`, `Python3_EXECUTABLE`. **Not** overridden: `PYTHON_ROOT_DIR`, `PYTHON_INCLUDE`, `PYTHON_LIBRARY`, `PYTHON_VERSION` (a venv has no headers or libpython of its own). | Fix only `set_nativ_env` in the project (older project branches would miss it); both (the project fix is kept as a follow-up, §8) |
| D13 | Bootstrap fix: if `distro` is missing, `src/architecture.py` falls back to `platform.freedesktop_os_release()` (Python ≥ 3.10) instead of exiting. | — |
| D14 | Running SAT from the venv (wrapper) and building against the venv (`--venv`) stay **independent**. | Wrapper implies `--venv` (implicit mode, rejected in D5) |
| D15 | Tests: unit tests in `test/test_060_venv.py` plus a documented manual E2E run on `MEDCOUPLING-9.15.0-native` (UB24.04), including a non-regression snapshot without `--venv`. | Unit tests only (nothing proves CMake finds the venv); automated E2E (too slow and machine-dependent) |
| D16 | `--venv` is a long option only (`-v` is taken by global `verbose` and `init --VCS`). | — |
| D17 | **Switching a product from compiled (FTP archive or git) to a pip package in the venv** is a pure configuration change, reversible in one command: declare the product `'native'` in the application (permanently, or for one call with `-o "APPLICATION.products.<p>='native'"`), with `pip:"yes"` in the product section selected for `native` (normally `default`; `{tag:'native', section:'<s>'}` picks another one, `src/product.py:120-212`), and optionally pin `APPLICATION.venv.<p>` to the previously compiled version. Revert = restore the previous declaration. After a switch in either direction, dependent products must be rebuilt (`sat compile APP --venv -p <p> --with_children --clean_all`). No new code path: classification (D2) does not depend on `get_source`, and SAT never adds a stale `INSTALL/<p>` to the environment of a product that is now native. This is a forward-looking scenario that does not exist in today's applications; it is covered by dedicated tests (§7.1.1, §7.2 step 6). | Dedicated "pip-from-source" mode (not needed for PyPI packages; out of scope, §8) |
| D18 | In venv mode, the generated `salome` launcher's header `#! /usr/bin/env python3` is replaced by `#! <venv>/bin/python3` (`src/fileEnviron.py`, where the header is already rewritten for Python 2, line 483). With the D12 variables also in the launcher, **`./salome` behaves the same whether or not the venv is activated**. `sat environ --venv` files (`env_launch.sh`, `env_build.sh`) carry `PATH`/`VIRTUAL_ENV`, so sourcing them is equivalent to activation. Launchers generated without `--venv` are unchanged. | Ask users to activate before `./salome` (the launcher itself would otherwise run in `/usr/bin/python3` before applying the environment) |
| D19 | **Three workflow rules, no implicit behaviour:** (1) `sat init --venv [<path>]` is the only way to create or select a venv; no other command creates one. (2) Venv mode is on **if and only if** `--venv` is on the command line; nothing implies it. (3) Install flags act on what the check finds, so they require `--check_system`. Each violation is an error naming the exact command to type (§6.4). | `--install_venv` implying `--venv`; auto-creating the venv on first use |

## 4. User workflow (Linux, native application)

```bash
# 1. Create once, with any system python3, no root
SAT/sat init --venv                    # <workdir>/venv; or --venv <path>; --venv forget to forget it

# 2. Optional: activate (puts the `sat` wrapper on PATH)
source <venv>/bin/activate             # otherwise call <venv>/bin/sat directly

# 3. Check (two groups: system / venv)
sat config APP --check_system --venv

# 4. Install what is missing (can be combined in one call: venv first, then system)
sat config APP --check_system --venv --install_venv     # pip into the venv, no root
sat config APP --check_system --venv --install_system   # sudo apt-get/dnf, system group only, with confirmation

# 5. Build (combines with every usual option)
sat prepare APP
sat compile APP --venv -p SMESH --with_children

# 6. Generate the launcher, then run it, activated or not (D18)
sat launcher APP --venv
<workdir>/salome

# Revert: leave out --venv; `sat init --venv forget`; delete the venv folder
```

Workflow **without** a venv (today's behaviour, plus the new system install):

```bash
sat config APP --check_system                     # check (every native product via apt/rpm)
sat config APP --check_system --install_system    # sudo apt-get/dnf, with confirmation
sat compile APP
```

Rules (D19): `sat init --venv` first; `--venv` on every venv command line;
install flags only together with `--check_system`; `--install_venv` only with `--venv`.

Example check output:

```
System packages (apt)               Venv packages (pip, <venv>)
  - boost        : OK                 - numpy    : OK (venv 2.1.0)
  - qt           : KO                 - scipy    : KO
  - PyQt         : OK                 - Sphinx   : OK (system 7.2.6)
```

## 5. Architecture

### 5.1 New module `src/venv.py`

| Function | Responsibility |
|---|---|
| `venv_python(venv_dir)` | Interpreter path: `bin/python` or `Scripts\python.exe`. The only place that knows the OS layout. |
| `venv_bin_dir(venv_dir)` | `bin` or `Scripts` |
| `resolve_venv_dir(config)` | `LOCAL.venv` → absolute path; raises `SatException` if unset, missing, or not a venv (`pyvenv.cfg` absent) |
| `create_venv(venv_dir, logger)` | `<sys.executable> -m venv --system-site-packages`, then `pip install distro`, then write the wrapper; reuses an existing venv; errors if the directory exists and is not a venv |
| `write_wrapper(venv_dir, sat_path)` | `bin/sat` (sh, `exec <venv python> <abs SAT/sat> "$@"`, chmod +x) or `Scripts\sat.bat` |
| `enable_venv_mode(config, logger)` | Called by commands when `--venv` is set: resolves the venv, checks that `Python` is native (D11), and sets the runtime-only key `config.VARS.venv_dir` |
| `split_native_products(config)` | `(venv_products, system_products)` per D2 |
| `get_requirements(config, venv_products, logger)` | `{product: "pip_name" or "pip_name==pin"}` from `APPLICATION.venv`; warns about pins on products outside the venv group |
| `check_venv_pkgs(venv_dir, products)` | One subprocess `<venv python> -c <script>` that uses `importlib.metadata` to look up each distribution (names normalised per PEP 503) → per product: OK/KO, version, origin (`venv` if the distribution's location is under `venv_dir`, else `system`) |
| `install_venv_pkgs(config, venv_dir, products, logger)` | `<venv python> -m pip install name[==pin]`, wheels cached in `$archive_dir/wheels`; keeps going past individual failures; returns the failure count |
| `apply_venv_env(env, venv_dir)` | Applies the D12 overrides on a `SalomeEnviron` |

### 5.2 Changes to existing code

| File | Change |
|---|---|
| `src/architecture.py` | `distro` fallback (D13) |
| `src/system.py` | `get_pkg_install_cmd(dist_name)` → `["apt-get","install","-y"]` (DB, UB, MN) / `["dnf","install","-y"]` (CO, FD; `yum` if `dnf` is absent), `None` elsewhere; `install_system_pkgs(...)` (sudo unless root, confirmation, batch refusal; independent of `--venv`); `check_system_pkgs` unchanged |
| `src/environment.py` | Hook in `SalomeEnviron.set_a_product`, native branch, right after `run_env_script(pi, native=True)`: `if pi.name == "Python" and "venv_dir" in self.cfg.VARS: src.venv.apply_venv_env(self, self.cfg.VARS.venv_dir)`. `SalomeEnviron` writes both to memory (build) and to files (launcher/environ), so this one hook covers both. |
| `commands/init.py` | `--venv [<path>\|forget]`; `normalize_venv_arg` gives a bare `--venv` the default path |
| `commands/config.py` | `--venv`, `--install_venv`, `--install_system`; `check_install_system` shows the two groups in venv mode and is unchanged otherwise; `--install_system` works with or without `--venv` |
| `src/fileEnviron.py` | In venv mode (`sat_venv_python` passed in the launcher's additional env), replace the `#! /usr/bin/env python3` launcher header with `#! <venv>/bin/python3` (D18) |
| `commands/{compile,configure,make,makeinstall,script,environ,launcher,application,test}.py` | Declare `--venv` (`src.venv.add_venv_option(parser)`); call `src.venv.handle_venv_option(options, runner.cfg, logger)` right after parsing |

### 5.3 Isolation guarantee

Without `--venv`, `config.VARS.venv_dir` is never set, the hook never fires, and
every code path is unchanged. The only change active without the flag is the
`distro` fallback, and it runs only where SAT used to exit with an error.

## 6. Data flow and error handling

### 6.1 `sat init --venv [<path>|forget]`

```
path (bare --venv: <workdir>/venv) → resolve → exists & is a venv  → reuse (re-write wrapper, ensure distro)
                       → exists & not a venv → ERROR, nothing written
                       → missing             → create_venv → wrapper
             → write LOCAL.venv (last step, only if everything succeeded)
forget       → remove LOCAL.venv (venv on disk untouched)
```

### 6.2 `sat config APP --check_system [--venv] [--install_venv] [--install_system]`

```
validate rules (D19) → error if violated
--venv    : enable_venv_mode → split_native_products
              system group → check_system_pkgs (unchanged)
              venv group   → check_venv_pkgs
no --venv : all native products → check_system_pkgs (unchanged, today's output)
display
--install_venv   → install_venv_pkgs(KO venv group) → re-check → display
--install_system → KO system packages (system group with --venv, all native without)
                   → show command → confirm [y/N] → sudo ... → re-check → display
```

### 6.3 Environment-building commands with `--venv`

```
enable_venv_mode → normal command flow (unchanged)
  → SalomeEnviron.set_a_product("Python"), native → project set_nativ_env
  → hook apply_venv_env → PATH / VIRTUAL_ENV / PYTHONBIN / Python3_EXECUTABLE
```

### 6.4 Errors

| Case | Behaviour |
|---|---|
| `--venv` without `LOCAL.venv` | Error: `no venv configured: run 'sat init --venv [<path>]'` |
| `LOCAL.venv` missing or not a venv on disk | Error naming the path; suggests running `init` again |
| `Python` not native | Error: "this application builds its own Python, already isolated; --venv is not needed" |
| `--install_venv` without `--venv` | Error: `--install_venv requires --venv` |
| `--install_venv` / `--install_system` without `--check_system` | Error: `--install_* requires --check_system` |
| `--install_system` in batch mode (`-b`) | Refused, prints the command to run manually |
| `--install_system` with no supported package manager (Windows, other distro) | Message, return code ≠ 0 |
| A pip install fails | Others continue; final summary; return code ≠ 0 |
| Pin on a product outside the venv group | Warning, ignored |

## 7. Tests

### 7.1 Automated — `test/test_060_venv_*.py` … `test/test_069_venv_*.py`

Follows the repo conventions (`unittest`, `import initializeTest`, run with pytest),
using `tempfile` directories.

- `venv_python` / `venv_bin_dir` on both platforms (patched `is_windows`)
- `resolve_venv_dir`: path, unset → error, non-venv dir → error; `default_venv_path` → `<workdir>/venv`; `default` is an ordinary directory name
- `create_venv`: real venv, `pyvenv.cfg` has `include-system-site-packages = true`,
  wrapper present and executable, `distro` importable from the venv, idempotent on
  a second call, error on an existing non-venv dir
- `init --venv forget` removes `LOCAL.venv` and leaves the venv on disk; a bare `--venv` (last, or followed by another option) gets `<workdir>/venv`
- `split_native_products` on a fake config (native+pip / native without pip /
  `pip:"no"` / non-native)
- pins: pinned → `name==ver`, unpinned → `name`, pin outside the group → warning
- `check_venv_pkgs` on a real venv: installed → OK (venv), missing → KO
- `apply_venv_env`: the 4 variables set; `PYTHON_ROOT_DIR` / `PYTHON_INCLUDE` unchanged
- `enable_venv_mode`: non-native Python → error; native → `VARS.venv_dir` set
- Non-regression: `SalomeEnviron` without venv mode yields the same variables
  with and without the patch
- `distro` fallback: import made to fail → `freedesktop_os_release` used, no exit
- `get_pkg_install_cmd`: DB/UB/MN → `apt-get`; CO/FD → `dnf` (or `yum`); others → `None`
- Option rules (D19): `--venv` without `LOCAL.venv` → error with the `sat init` hint;
  `--install_venv` without `--venv` → error; install flags without `--check_system` → error
- `--install_system` package list (sudo call mocked, nothing installed): with `--venv` →
  only the system group; without `--venv` → every KO native product; batch mode →
  refused, command printed
- Launcher header (D18): generated in venv mode → first line is `#! <venv>/bin/python3`;
  generated without `--venv` → unchanged `#! /usr/bin/env python3`
- Tests that need PyPI are skipped when there is no network

#### 7.1.1 Forward-looking scenario: compiled product → pip package in the venv (D17)

Fixture: a fake product pyconf `fakepkg` with two sections:
- `version_X_compiled`: `get_source` `archive` (FTP) or `git` (GitHub); the tests are
  parametrized over both, with `pip:"no"` and a compile script.
- `default`: `pip:"yes"`. Its `name` is a small, pure-Python PyPI distribution, used as a
  stand-in so that the install really runs.

A fake stale install `INSTALL/fakepkg/lib/pythonX.Y/site-packages/` simulates a
previous compiled build.

| Test | Asserts |
|---|---|
| `test_switch_classification` | Declared `{tag:'X', section:'version_X_compiled'}` → **not** in the venv group (handled by compile). Declared `'native'` → in the venv group. Same result for `archive` and `git`. |
| `test_switch_one_command` | Without editing any file, loading the config with `-o "APPLICATION.products.fakepkg='native'"` puts `fakepkg` in the venv group; without `-o` it is compiled again. |
| `test_switch_install_possible` | After the switch, `install_venv_pkgs` installs `fakepkg` into a real venv, pinned through `APPLICATION.venv.fakepkg`; `check_venv_pkgs` reports `OK (venv <pinned version>)`; the venv interpreter imports it from inside `venv_dir`. (Skipped without network.) |
| `test_switch_no_shadowing` | In venv mode with `fakepkg` native, the environment built by `SalomeEnviron` contains no path under the stale `INSTALL/fakepkg`; `PYTHONBIN` is the venv interpreter. |
| `test_switch_revert` | Switching back to the compiled declaration: `INSTALL/fakepkg/.../site-packages` is back in `PYTHONPATH`, ahead of the venv, so the compiled build wins even though the pip package is still installed in the venv. |
| `test_switch_without_venv_untouched` | Same switch **without** `--venv`: `fakepkg` native goes back to the system group (apt/rpm check), exactly as today. |

### 7.2 Manual E2E — `MEDCOUPLING-9.15.0-native` on UB24.04

1. Before the patch: `sat environ APP` → reference snapshot.
2. After the patch, without `--venv`: `sat environ APP` → identical to the snapshot.
3. `init --venv` → `config --check_system --venv` → `--install_venv` →
   `compile --venv` → `launcher --venv`.
4. Check that `CMakeCache.txt` has `Python3_EXECUTABLE=<venv>/bin/python`. Then, from a
   shell **without** activation:
   `./salome shell -- python3 -c "import sys, numpy; print(sys.prefix, numpy.__file__)"`
   must print the venv path for both (D18). Repeat from an activated shell: same output.
5. `init --venv forget` → commands without `--venv` behave as before.
6. Switch scenario (D17) on a real compiled pip product of the app: compile it from its
   FTP archive, switch it with `-o "APPLICATION.products.<p>='native'"`, run
   `--install_venv` with the matching pin, `compile --venv -p <p> --with_children --clean_all`,
   check that the launcher imports it from the venv, then revert by dropping `-o` and
   check that the compiled build is used again.
7. PEP 668 check (§2.2): in the native app, compile a **versioned** `pip:"yes"` product
   (e.g. `-o "APPLICATION.products.toml='0.10.2'"`) **without** `--venv` → expected
   failure with `externally-managed-environment`; then the same command **with**
   `--venv` → success, and the package is installed under `<venv>/lib/pythonX.Y/site-packages`.
   Record the actual outputs in the run report. If step one does not fail, update §2.2
   with what actually happens.

## 8. Out of scope / follow-ups

- `sat package --venv` (a binary package would embed a machine-specific venv path).
- Project cleanup: make `SAT_SALOME/.../Python.py::set_nativ_env` derive paths
  from `sys.executable` / `VIRTUAL_ENV` instead of hardcoding `/usr`; the SAT hook
  then becomes a no-op.
- Fully isolated venv mode.
- Optional `--venv <path>` override per command.
- "pip-from-source" mode: pip-installing a product from the sources `sat prepare`
  fetched (FTP archive or git tag, patches applied) instead of PyPI, for packages
  that are not on PyPI.

## 9. Risks to verify during implementation

- ~~`from distro import linux_distribution`~~: checked, `distro` 1.9.0 still
  provides it (deprecated but working). No pin needed.
- CMake: `Python3_EXECUTABLE` as an *environment* variable is not read by
  FindPython; what steers it to the venv is `VIRTUAL_ENV` (default
  `Python3_FIND_VIRTUALENV=FIRST`) and `PATH`. Confirm that SALOME's CMake macros
  are not forced back to `/usr` through `PYTHON_ROOT_DIR` (manual E2E, step 4).
- `freedesktop_os_release` exists only on Python ≥ 3.10; on 3.8/3.9 without
  `distro`, keep the current error message.
