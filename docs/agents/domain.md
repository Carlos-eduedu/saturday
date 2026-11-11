# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

`AGENTS.md` (imported by `CLAUDE.md`) is the project contract: non-negotiable rules, scope, phases and the Granatech/CLT/WhatsApp specs. It wins over anything below.

## Before exploring, read these

- **`GLOSSARY.md`** at the repo root.
- **`docs/decisoes/`**: this repo's ADRs. Read the ones that touch the area you're about to work in.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates them lazily when terms or decisions actually get resolved.

## File structure

Single-context repo:

```
/
├── GLOSSARY.md
├── docs/decisoes/
│   ├── 0001-outbox-dono-do-reagendamento.md
│   └── 0002-workspace-uv-unico.md
└── apps/core/src/saturday/
```

New decisions follow the existing convention: `docs/decisoes/NNNN-slug-em-portugues.md`, written in Portuguese. Do not create `docs/adr/`.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `GLOSSARY.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing decision in `docs/decisoes/`, surface it explicitly rather than silently overriding:

> _Contradicts 0001 (outbox dono do reagendamento), but worth reopening because…_
