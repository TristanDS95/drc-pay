# Simplicity review (the "ponytail" pass)

A lightweight discipline for keeping this codebase small: **the best code is the code we never
wrote.** Adapted from the MIT-licensed [ponytail](https://github.com/DietrichGebert/ponytail)
ruleset - we keep the philosophy, not the plugin.

"Lazy" here means **efficient, not careless.** It governs *what we build*, never our safety bar.

## The ladder - stop at the first rung that holds
Before writing code:
1. Does this need to exist at all? (YAGNI)
2. Does the standard library do it? Use it.
3. Does a native platform / framework feature cover it? Use it.
4. Does an already-installed dependency solve it? Use it.
5. Can it be one line? Make it one line.
6. Only then: write the minimum code that works.

## Rules
- No abstraction we didn't ask for; no layer with one caller; no config nobody sets.
- Deletion over addition. Boring over clever. Fewest files.
- Ship the simple version and name the trade-off in the same breath - never stall.
- Mark a deliberate shortcut with a `# ponytail:` comment that names its ceiling.

## When NOT to be lazy (hard line - especially here)
This is a **payments** codebase. Never simplify away:
- The **money core**: the double-entry ledger, the transaction state machine, idempotency,
  integer-minor-unit `Money`. Load-bearing for correctness - not over-engineering.
- **Input validation at trust boundaries** (amount/fee/recipient are server-derived; the client
  is never trusted).
- **Error handling that prevents lost or duplicated money** (refund-on-failure, `manual_review`).
- **Security**: callback signature verification, secret hygiene, the auth gate.
- Anything a test pins, or anything we explicitly chose to keep.

Non-trivial logic keeps **one runnable check** behind it (a test). That's the floor, not bloat.

## The review process (the `/ponytail-review` equivalent)
Review a diff or a file for over-engineering only. **List findings - never auto-apply.** One
line each:

> `<file>:L<n>: <tag> <what>. <replacement>.`

Tags:
- `delete:` - dead code, unused flexibility, speculative feature. Replaced by nothing.
- `stdlib:` - hand-rolled thing the standard library ships. Name the function.
- `native:` - code/dep doing what the platform already does. Name the feature.
- `yagni:` - abstraction with one implementation, config nobody sets, layer with one caller, unused API.
- `shrink:` - same logic, fewer lines. Show the shorter form.

End with the only metric that matters: `net: -<N> lines possible.` If there's nothing to cut,
say **`Lean already. Ship.`** and stop.

Correctness bugs, security holes, and performance go to a *separate* review pass - this one hunts
complexity only, and never flags the money core or the one smoke test behind a change.

_Source & credit: [DietrichGebert/ponytail](https://github.com/DietrichGebert/ponytail) (MIT)._
