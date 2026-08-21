# Domain documentation

RosBridge Pro is a single-context repository.

## Before exploring

Read the following sources when relevant:

- `CONTEXT.md`: canonical domain glossary.
- `docs/modules/<capability>/design.md`: accepted module design.
- `docs/architecture/adr/`: durable architecture decisions.
- Relevant GitHub Spec and implementation tickets.

If a file does not exist, continue without inventing its contents.

## CONTEXT.md

`CONTEXT.md` contains domain terms and relationships only. It does not contain implementation
plans, requirements, task status, or code walkthroughs.

`domain-modeling` creates and updates it only when terminology is actually resolved.

## Module design and ADR

Implementation-specific designs belong in `docs/modules/`.

Create an ADR only when a decision is consequential, difficult to reverse, and surprising
without its context. Use the repository's existing `docs/architecture/adr/` path.

If code, a Spec, module design, or ADR conflicts, report the conflict before choosing an
interpretation.
