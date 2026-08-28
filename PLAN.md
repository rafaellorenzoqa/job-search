# Build plan

Goal: an agent that finds jobs on LinkedIn, resolves them to their real ATS posting,
pulls the exact application form, writes a resume tailored to that job, drafts the
answers, and hands you a ready-to-submit payload.

Each phase is independently useful and ends with a check you can run. Do not start
phase N+1 until phase N's check passes.

---

## The agent is Claude Code

You are not building an agent loop. Claude Code + the `linkedin` MCP + this repo's
`CLAUDE.md` *is* the agent: the model calls tools, reads files, writes files. The
scripts below exist only for the parts that are pure plumbing (HTTP GET, JSON
parsing) — things a script does more cheaply and reliably than a model.

Rule of thumb for everything below: **script the deterministic parts, let the model
do the judgment parts.** Fetching a form schema is deterministic. Deciding which
three bullets from your history match this JD is judgment.

Do not reach for the Agent SDK until the manual loop works end to end and you are
bored of running it by hand. That boredom is the requirement document.

---

## Phase 0 — MCP wired ✅ / login ⬜

`.mcp.json` is written and the server binary runs. Session not yet created.

**Check:** `uvx mcp-server-linkedin@latest --status` prints a valid session.
Run `uvx mcp-server-linkedin@latest --login` first, then restart Claude Code.

---

## Phase 1 — The fact base ✅

Two people use this tool, so everything personal is namespaced:

```
profiles/luciano/profile.md          superset of every fact
profiles/luciano/default-resume.md   hand-written fallback CV
profiles/rafael/...                  same, awaiting his resume
out/<profile>/<company>-<role>/      packets, never shared between profiles
```

The two files per person, and the distinction between them, are the whole design:

- **`profile.md`** — the *superset*. Every role, every bullet, every number, every
  skill, every link, plus standard answers (work authorization, salary, start date,
  notice period). Long is fine — nobody reads it directly. It is the pool tailoring
  draws from, and tailoring can only ever draw from it.
- **`default-resume.md`** — the *fallback CV*. One page, general-purpose,
  hand-curated. Used verbatim when there is no usable JD.

Why not generate the default from the profile: the fallback ships when the agent
knows *least* about the job, so it is the one you least want a model improvising.
You write it; the agent never edits it.

Luciano's is built from `CV Luciano Nova (en-US) v2.pdf`. His `## Standard answers`
and `## Stories` are deliberately blank and marked `NEEDS INPUT` — a CV does not
contain work authorization, salary, notice period, or STAR narratives, and forms ask
for all of them. Anthropic's form, pulled live in phase 4, has a **required**
visa-sponsorship question. Guessing one is exactly the failure this project exists to
avoid, so these stay blank until he fills them in.

Rafael's profile is a loud placeholder. A job routed to a profile with no facts must
fail, never fall back to a blank resume.

**Check:** every claim in `default-resume.md` appears in `profile.md`. If something
lives only in the CV, move it into the profile — the profile must be the superset or
tailoring will silently drop facts.

---

## Phase 2 — Job intake

`jobs.yaml` is the queue. One entry per job:

```yaml
- profile: luciano      # which person this row is for
  linkedin_id: "4461450008"
  company: Acme
  role: Senior Backend Engineer
  apply_url:            # filled by phase 3
  ats:                  # greenhouse | lever | other | easy_apply
  status: todo          # todo | prepared | submitted | rejected | interview
```

One shared queue rather than one per person: both may target the same job, and a
single file is one thing to scan.

The agent fills this with `search_jobs` (keywords, location, `work_type`,
`date_posted`, `max_pages`) then `get_job_details` per id. `get_saved_jobs` covers
jobs you starred by hand.

**Check:** run one search, get ≥1 row in `jobs.yaml` with a real `linkedin_id`.

Rate-limit this. LinkedIn bans for aggressive scraping and the ban is on your real
account.

---

## Phase 3 — Resolve LinkedIn job → ATS posting

The bridge everyone forgets. A LinkedIn posting is either:

- **Easy Apply** → stays on LinkedIn. No API. Out of scope (see Phase 7).
- **"Apply on company website"** → carries an off-site URL. That URL is the prize.

From a Greenhouse URL `job-boards.greenhouse.io/acme/jobs/1234567`, parse
`board_token=acme` and `job_id=1234567`. Lever and Ashby have equivalent shapes.
Anything else → `ats: other`, handle manually.

**Check:** one `jobs.yaml` row with `ats: greenhouse` and both ids parsed out.

---

## Phase 4 — `gh_form.py` — pull the exact application form ✅

```
GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{id}?questions=true
```

Public, unauthenticated, verified working. Returns `content` (the full JD as HTML)
and `questions` — every field, its `name`, its `type`, and whether it is `required`.

Field types you will see: `input_text`, `textarea`, `input_file`,
`multi_value_single_select`, `multi_value_multi_select`. Selects carry their allowed
`values` — the agent must pick from them, never invent an option.

Writes `out/<profile>/<company>-<role>/{jd.txt,form.json}` and prints the field list
with its select options, which is the shopping list phase 6 fills.

`Resume/CV` accepts **both** `input_file` and `textarea` (`resume_text`). Use the
textarea. That deletes the entire PDF-rendering problem from this project.

**Check:** `python3 gh_form.py --selftest` (URL parsing across all four Greenhouse
URL shapes, plus the HTML stripper). Live run verified against
`anthropic/jobs/4461450008` — 19 fields, 14 required.

---

## Phase 5 — Tailored resume ✅  ⭐ the new feature

**Input:** `profiles/<who>/profile.md` + `jd.txt` → **output:** `out/<who>/<company>-<role>/resume.md`

### Fallback rule

Tailor when the JD is usable, otherwise copy that profile's `default-resume.md` verbatim. Usable
means: the JD text exists, is longer than ~800 characters, and names concrete
requirements (skills, tools, years). A one-paragraph "we're looking for great
people!" post is not a specification — take the fallback and note it in `notes.md`.
Record which path was taken; you will want to know later whether a rejection came
from a tailored or a default CV.

### Tailoring is selection, not generation

This is the safety property that makes the whole feature usable. The agent may:

- **choose** which roles and bullets from `profile.md` appear, and in what order
- **cut** anything irrelevant to this JD
- **re-word** a bullet to use the JD's vocabulary for the same thing
  (`"Postgres" → "PostgreSQL"`, `"queues" → "event-driven architecture"`)
- **re-weight** the summary line toward what this job is asking for

The agent may **not** add a technology, employer, title, date, metric, or outcome
that is not already in `profile.md`. Not "adjacent" ones, not "reasonable
inferences." If the JD wants Kubernetes and the profile has none, that gap goes in
`notes.md` — that is the point of `notes.md`.

### The check that enforces it

`check_resume.py <resume> --profile <who>` — extracts every number and every
claim-bearing token from the resume and asserts each traces back to `profile.md`.
Exit 1 on any that does not. Crude, and it catches the failure that actually happens:
a model inventing "5 years" or "Kubernetes" because the JD asked for it.
Run it on every generated resume.

It ignores what is grammar rather than claim — headings, emphasis, sentence-initial
capitals, and a bullet's leading verb — and accepts a hyphenated compound when a part
matches ("Terraform-driven" from "Terraform"). Profile headings count as support,
since employer and project names often live only there.

```
ponytail: token-membership check, not semantic. Upgrade to an LLM-judge
pass over (profile, resume) if it starts missing real fabrications.
```

**Check:** generate resumes for two different JDs from the same profile. They must
differ in content, and both must pass `check_resume.py`.

---

## Phase 6 — Answers + payload

For each entry in `form.json`: standard fields come from `profile.md`'s standard
answers. Selects get an allowed value copied exactly. Free-text questions ("Why
Anthropic?", "Describe your experience with X") are drafted by the agent from
`profile.md` + `jd.txt`, same no-invention rule as Phase 5.

Assemble `out/<who>/<company>-<role>/payload.json`, keyed by the field `name`s from
`form.json`, with `resume_text` holding the Phase 5 resume.

**You submit.** The `POST` needs the employer's board API key (Basic Auth, from
their Dev Center) — candidates cannot get one. So this phase ends with a complete,
validated payload and a browser tab; you paste and click. Greenhouse does no
server-side validation of required fields on that endpoint anyway, so the
client-side check below is not optional busywork — it is the only validation there is.

Keep the POST path written but unreachable behind a `board_api_key` config value
that is empty. If you ever have one, it is a two-line change.

**Check:** `payload.json` contains a non-empty value for every `required: true`
field in `form.json`. That assertion is the script.

---

## Phase 7 — Later, if ever

- **Tracking:** flip `status` in `jobs.yaml`, add `submitted_at`. One line of yaml.
- **Lever / Ashby:** same shape as Phase 4, different JSON. Add when you hit enough
  of them to care.
- **LinkedIn Easy Apply:** needs Playwright against the modal. Real ban risk. Only
  if the API path proves insufficient.
- **Agent SDK / cron:** only once the manual loop is boring.

---

## Rules

- Never invent experience, dates, titles, numbers, or skills. Gaps go in `notes.md`.
- Never invent a select-option value; copy from `form.json`.
- Rate-limit LinkedIn scraping.
- One packet per job in `out/<profile>/<company>-<role>/`: `jd.txt`, `form.json`, `resume.md`,
  `answers.md`, `payload.json`, `notes.md`.
