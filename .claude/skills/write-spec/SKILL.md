---
name: write-spec
description: Author a technical spec / implementation plan as a structured markdown doc before writing any code. Use when the user asks to plan, design, or spec a non-trivial change ("write a plan", "design doc", "tech spec", "how would you approach X", "plan the migration/refactor"). Produces a reviewed doc under research/active/ and STOPS for explicit approval before implementation.
argument-hint: "[short task description]"
---

# write-spec

Turn a non-trivial task into a written, self-reviewed technical spec, and hold at a
hard gate until the user approves implementation. This skill is about **writing and
maintaining the spec** — not executing it.

## When to use
- The task is multi-step, touches multiple files/systems, or has design trade-offs.
- The user asks for a plan, design doc, tech spec, RFC, or "how would you approach…".
- Skip for trivial, single-obvious-edit changes — just do those.

## Workflow (do these in order)

### 1. Gather context first — never spec from memory
Before writing, investigate the actual codebase/system: read the relevant files,
confirm how things currently work, check versions/deps/config, and verify any claim the
spec will rely on. Cite concrete file paths and facts. A spec built on guesses is the
main failure mode — every assumption you can cheaply verify, verify.

### 2. Create the doc in the research directory
- Location: `research/` at the repo root. If it doesn't exist, create it with two
  subdirs:
  - `research/active/` — specs currently being worked or awaiting approval.
  - `research/archive/` — superseded or completed specs.
- Filename: `<date>-<task>.md`, where `<date>` is today in `YYYY-MM-DD` and `<task>` is
  a short kebab-case slug. Example: `2026-08-01-slack-events-migration.md`.
- New spec goes in `research/active/`.

### 3. Write the spec with these sections (in this order)
1. **Context** — what exists today, why this work is being considered, links to prior
   docs/tickets. Ground it in the facts gathered in step 1.
2. **Goals & Non-Goals** — what success is, and explicit boundaries (what this will *not*
   do). Non-goals prevent scope creep and are as important as goals.
3. **Phases** — the work broken into independently shippable, ordered phases. Each phase
   should state its deliverable and whether it changes behavior. Prefer phases that each
   leave the system working/green.
4. **Detailed Design & Pseudo Code** — per phase: concrete steps, key
   functions/modules/interfaces, and **pseudo code** for the non-obvious parts. Show
   file/module layout when structure changes. Specify tests where relevant.
5. **Alternative Designs Considered** — the real options weighed, each with pros/cons and
   why it was or wasn't chosen. At least the ones a reviewer would ask "why not X?".
6. **Open Questions** — decisions genuinely needing the user's input, each with a
   recommended default. These become the review gate.
7. **Appendix** — supporting detail: captured data, command references, links, raw
   findings that would clutter the body.

### 4. Critically review the spec after writing (mandatory)
Do a genuine self-review pass — do not rubber-stamp your own draft. Hunt for:
- internal contradictions (a decision in one section undercut in another),
- unstated assumptions and unverified claims,
- gaps that would bite during implementation (sequencing, test/CI parity, rollback,
  security, concurrency, error paths),
- sections that don't reconcile after edits.

Fix what you find, in the doc. Then briefly report the issues you caught and how you
resolved them — this pass has repeatedly caught real problems, so treat empty findings
with suspicion.

### 5. STOP — get explicit approval before implementing
After the reviewed spec is ready:
- Present a concise summary and surface the **Open Questions** for decisions.
- **Do not write or change any implementation code.** Wait for the user to review.
- Only start implementation on an **explicit** instruction to do so (e.g. "start
  implementing", "go", "proceed"). Resolving open questions is *not* by itself approval
  to implement — confirm.
- When open questions are answered, record the answers in a **Decisions (locked)**
  section and proceed to the consistency review in step 6.

### 6. On every spec update, re-review for consistency
Any time the spec changes (new decision, scope change, review feedback):
- Re-read the whole doc and reconcile every section with the change.
- Update stale cross-references, risk notes, phase tables, and decisions.
- Report what you changed and any inconsistency the pass surfaced.
Locked decisions must not silently contradict earlier prose — update the prose.

### 7. Archive when done or superseded
When a spec is fully implemented, or replaced by a newer one, move it from
`research/active/` to `research/archive/` (keep the filename). Active stays small and
reflects only live work.

## Notes
- Keep specs skimmable: tables for phases/decisions, pseudo code fenced, prose tight.
- Reference real paths as `file:line` so they're clickable.
- `research/` is gitignored — specs are local working notes, not tracked artifacts. If
  the entry is missing from `.gitignore`, add it when creating the directory.
- Run this skill inline in the main thread (not a subagent): the step-5 approval gate and
  the back-and-forth on open questions need direct conversation with the user.
- The gate in step 5 is the point of this skill — a reviewed plan the user has signed
  off on beats a fast start on the wrong design.
