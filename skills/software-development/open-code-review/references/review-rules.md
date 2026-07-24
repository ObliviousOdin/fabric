# Built-in review rules (defaults)

These are the checks every reviewer applies when no user rule matches a file
(Step 3, priority 5). A file also inherits any matching rule from a resolved
rule file — those *add to* these defaults unless the user rule intentionally
replaces them.

Group findings under the `category` values the output schema uses:
`bug`, `security`, `performance`, `maintainability`, `test`, `style`,
`documentation`, `other`. Assign `severity`: `critical`, `high`, `medium`,
`low`.

## Correctness (`bug`)

- Null / undefined dereference (NPE): a value that can be null is used without a
  guard — especially returns from lookups, `find`, `get`, external calls.
- Off-by-one and boundary errors in loops, slices, and index math.
- Wrong or inverted conditionals; `==` vs `is`/`===`; truthiness on `0`/`""`.
- Unhandled branches: `switch`/`match` without a default; enum grew, handler
  didn't.
- Resource lifecycle: files, sockets, DB connections, locks opened but not
  closed on every path (including error paths) — leaks and deadlocks.
- Error handling swallowed: empty `catch`, `except: pass`, ignored error
  returns, `.catch(() => {})` — hides failures.

## Concurrency (`bug`, often `high`/`critical`)

- Shared mutable state without synchronization; data races.
- Check-then-act (TOCTOU): existence/permission checked, then used, with a gap.
- Non-atomic read-modify-write on counters, maps, caches.
- Blocking calls inside locks; lock ordering that can deadlock.

## Security (`security`)

- Injection: SQL/NoSQL built by string concatenation or f-strings; OS command
  via `os.system`/`subprocess(..., shell=True)`; template/HTML injection.
- XSS: untrusted data written to `innerHTML`, unescaped template output.
- Path traversal: user input joined into a filesystem path without
  normalization/containment checks.
- Unsafe deserialization: `pickle.loads`, `yaml.load` (unsafe), Java native
  deserialization on untrusted bytes.
- Secrets: hardcoded API keys, tokens, passwords, private keys in source.
- AuthN/AuthZ: missing permission check on a privileged path; trusting a
  client-supplied identity/role.
- Weak crypto / insecure randomness for security purposes; disabled TLS verify.

## Performance (`performance`)

- N+1 access patterns: a query/call per item in a loop that could be batched.
- Redundant work: repeated reads, recomputation, duplicate API calls.
- Hot-path or per-request allocation of heavy objects; blocking I/O on a hot
  path; unbounded in-memory growth.
- Missing pagination/streaming on large result sets.

## Maintainability (`maintainability`)

- Copy-paste-with-variation that should share an abstraction.
- Leaky abstraction: exposing internals, breaking an existing boundary.
- Stringly-typed code where a constant/enum/registry already exists.
- Parameter sprawl and dead code introduced by the change.

## Tests (`test`)

- New behavior with no test; a bug fix with no regression test.
- Change-detector tests that assert implementation details, not behavior.

## Style / Docs (`style`, `documentation`) — usually `low`

- Public API added without a docstring/comment describing contract.
- Naming that fights the file's conventions.

## Applying rules well

- **Search before flagging.** Confirm with `git blame`, neighboring code, or a
  grep — a finding with no evidence is noise; drop it or mark it low.
- **Respect the repo.** Fold `AGENTS.md` / `CLAUDE.md` / `FABRIC.md` and linter
  configs into the check so findings match house style.
- **Severity honestly.** `critical`/`high` = data loss, security hole, or a
  crash on a real path. Don't inflate a nit to get attention.
