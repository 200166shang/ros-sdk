# Issue tracker: GitHub

Specs and implementation tickets for this repository live in GitHub Issues. Use the `gh` CLI
and infer the repository from `git remote`.

## Workflow

- `to-spec` publishes the confirmed feature specification as a GitHub Issue.
- `to-tickets` decomposes that specification into independently reviewable tracer-bullet
  tickets.
- Each ticket records its parent Spec, blockers, observable result, and acceptance evidence.
- `implement` works one unblocked ticket at a time.
- Each implementation ticket normally corresponds to one primary PR.
- PRs are not treated as incoming feature requests.

## Wayfinder

A large, unclear effort uses one map Issue and linked decision Issues. Decision Issues resolve
uncertainty; they do not directly deliver production code. Once the map is clear, `to-spec`
converts the decisions into one buildable specification.

Use GitHub sub-issues and native blocking relationships when available. Otherwise record
`Part of`, `Blocked by`, and task-list links in Issue bodies.
