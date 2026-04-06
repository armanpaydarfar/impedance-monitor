# CLAUDE.md — impedance-monitor

Standalone ANT Neuro electrode impedance monitoring utility.
Before starting any session, read the implementation plan:
`/home/arman-admin/Documents/SoftwareDocs/eego_impedance_monitor_implementation_plan.md`

---

## Platform

- **Linux only.** No Windows-specific code. No platform guards needed.

---

## SDK Safety

These rules apply permanently — in every session, for every task including bug fixes
and new features.

- `acquisition/eego_sdk.py` is the **only** file that may import `ctypes` or load
  `libeego-SDK.so`. No other module touches the SDK.
- `eego_sdk.py` must never be imported in mock mode. The acquisition backend is
  injected at runtime — keep that boundary clean.
- The SDK allows only **one stream active at a time.** `stop()` must call
  `eemagine_sdk_close_stream`, `eemagine_sdk_close_amplifier`, and
  `eemagine_sdk_exit()` in that order before the process exits.
- **Discard the first `getData()` result** after opening an impedance stream.
  SDK issue 3162 — first reading cycle delivers wrong values, unresolved in 1.3.19.
- **Values below 100 Ω are open-circuit, not good impedance.** SDK issue 3165.
  Always classify as `Status.OPEN`. Never `Status.GOOD`.

---

## Code Analysis Protocol

- **Read before you claim.** Before asserting what a function or code path does, read
  it with the Read tool. Do not infer behaviour from naming conventions or context.

- **Read both sides before comparing.** When analysing a discrepancy between two code
  paths, read both in full before drawing any conclusion.

- **Cite sources.** Any code referenced in an analysis must include the exact file path
  and line number. If a snippet is not directly quoted from the repo, label it
  explicitly as pseudocode or assumption.

- **No fabricated code.** Never present inferred or reconstructed code as if it were
  observed in the repo. If the actual implementation is unknown, say so and read the
  file before continuing.

---

## Proposing Changes

- Do not propose a change until the relevant source files have been read. State what
  was read and where before proposing anything.

- Do not add features, refactor, or clean up code beyond what was asked. A bug fix does
  not justify touching surrounding code.

- Do not add error handling or validation for scenarios that cannot happen given
  existing system guarantees.

---

## Error Handling

- **Surface real errors.** Do not silently suppress exceptions. If an exception is
  caught, it must be re-raised, logged with enough context to diagnose the failure, or
  suppressed with an explicit inline comment explaining why suppression is safe in that
  specific case.

- **`try/except` is acceptable when architecturally justified** — resource cleanup,
  protocol-level recovery, or documented degradation paths. It is not a substitute for
  understanding a failure mode and is not a way to make code "more robust" by default.

- **Prefer fail-fast in the SDK acquisition layer.** Silent recovery from an unexpected
  error can mask unsafe hardware state. Unless a specific recovery action is defined and
  safe, let the exception propagate.

- The GUI `closeEvent` must call `backend.stop()` and `session.close()` before
  `event.accept()`. No lingering SDK streams or open file handles after window close.

---

## Software Development Practices

- **Single responsibility.** Functions and modules should do one thing. If a helper is
  only used once, inline it rather than abstracting it.

- **No speculative abstractions.** Implement what the task requires. Do not design for
  hypothetical future requirements.

- **Prefer editing existing files.** Do not create new files unless genuinely necessary.

- **No dead code.** Do not leave commented-out code, unused imports, or
  removed-feature stubs in committed files.

- **Comments explain why, not what.** Inline comments should document intent and
  non-obvious reasoning, not restate what the code does. One clear sentence beats
  three vague ones.

- **Keep documentation current.** When modifying a function, update its docstring.
  When adding a function, add a docstring. When a change affects behaviour described
  in `README.md`, update that file too. Applies only to code directly touched by the
  task.

- **Do not add comments to unrelated code.** Do not add or update docstrings, inline
  comments, or documentation for code that is not part of the current task.

---

## Commit Hygiene

- Do not commit unless explicitly asked.
- Stage files individually — never `git add .` or `git add -A`.
- Commit messages should explain *why*, not just *what*.
- Do not add `Co-Authored-By` or any AI attribution lines to commit messages.

---

## Dependency and Environment

- The conda environment is named `lsl`, Python 3.12.
- `pyproject.toml` is the reference for dependencies. Do not introduce packages that
  cannot be installed on Linux via pip or conda.

---

## External System Dependencies

`libeego-SDK.so` is not managed by conda and will not appear in `pyproject.toml`.
It must be installed separately (obtained from ANT Neuro) and locatable via the SDK
path resolution order defined in the implementation plan. `install.sh` handles this
for new users. If the SDK is not found, the tool must fail with a clear message — not
silently fall back to mock mode.
