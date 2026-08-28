# job-search

Agent that finds LinkedIn jobs, resolves them to their ATS posting, pulls the exact
application form, and writes a job-tailored resume + answers.

Build plan and phase order: `PLAN.md`. Follow it in order.

## Sources of truth

Two people use this tool. Everything personal is namespaced by profile:

- `profiles/<who>/profile.md` — superset of every fact. Tailoring draws only from here.
- `profiles/<who>/default-resume.md` — hand-written fallback CV. The agent never edits it.
- `out/<who>/<company>-<role>/` — packets, never shared between profiles.

Profiles: `luciano`, `rafael` — both built from their CVs.

Rafael's profile has a `## CONFLICTS` section (year counts and overlapping dates that
contradict each other in his CV). Never pick a side on one silently; if a JD makes a
conflict load-bearing, ask.

Fields marked `NEEDS INPUT` in a profile are unanswered on purpose. Never fill one
in by guessing — including inferring work authorization or visa status from
nationality or location. Ask, or leave the form field empty and note it.

## Tools
- `linkedin` MCP (`.mcp.json`, stickerdaniel/linkedin-mcp-server) — drives a real
  Chromium with my logged-in session. `search_jobs` -> `job_ids` ->
  `get_job_details`; also `get_saved_jobs`, `get_my_profile`. **It cannot apply** —
  `easy_apply` is a search filter only.
- `gh_form.py <greenhouse-url> --profile <who>` — pulls the JD and the exact
  application form (public, unauthenticated Greenhouse endpoint) into the packet.
  `--selftest` covers the URL parsing. The submit `POST` needs the *employer's*
  API key, so submission stays manual.
- `check_resume.py <resume.md> --profile <who>` — fails if the resume claims anything
  not in that profile. Run it on **every** generated resume; a tailored resume that
  has not passed it does not go out.

Session lives in `~/.linkedin-mcp/profile` and expires; re-run
`uvx mcp-server-linkedin@latest --login`, check with `--status`.

## Rules
- Never invent experience, dates, titles, numbers, or skills. Tailoring selects,
  cuts, and re-words what is in `profile.md` — it never adds. Gaps go in `notes.md`.
- Never invent a select-option value; copy it from `form.json`.
- Rate-limit LinkedIn scraping. Bans hit the real account.
