# Vektor Engineering Rules

## File Size & Modularity
- **Keep every new file under 250 lines.** Split large components, routers, or services into focused modules before they grow past 250 lines.
- Keep functions small, single-purpose, and shallowly nested; use early returns.

## No AI Slop
- **Code:** Do not duplicate logic, add unused abstractions, leave placeholder stubs, or hardcode fake fallbacks. Reuse existing repository, gateway, and UI helpers.
- **Comments:** Do not write obvious comments that narrate *what* the code does (e.g., `# increment counter`). Only comment *why* a non-obvious invariant, security boundary, or workaround exists.
- **Types & Schemas:** Keep strict TypeScript (`tsc --noEmit`) and strict Python (`mypy`, `ruff`) passing on every change.

## Security & Verification
- Never log, return, or expose raw API keys or `.env` secrets to clients or LLMs.
- Always run relevant `pytest`, `ruff check`, `mypy`, and frontend `tsc --noEmit` after edits.
