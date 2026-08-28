#!/usr/bin/env python3
"""Pull a Greenhouse job's description and its exact application form.

    python gh_form.py <greenhouse-job-url> --profile luciano
    python gh_form.py --selftest

Writes out/<profile>/<company>-<role>/{jd.txt,form.json}.

The GET endpoint is public and unauthenticated. The matching POST that submits an
application needs the *employer's* board API key, which candidates cannot get --
see PLAN.md phase 6.
"""

import argparse
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{job_id}?questions=true"

# job-boards.greenhouse.io/acme/jobs/123, boards.greenhouse.io/acme/jobs/123,
# and the embedded form's boards.greenhouse.io/embed/job_app?for=acme&token=123
_PATH = re.compile(r"greenhouse\.io/(?:embed/job_app/?)?([^/?#]+)/jobs/(\d+)")
_EMBED = re.compile(r"greenhouse\.io/embed/job_app\?.*\bfor=([^&#]+).*?\btoken=(\d+)")


def parse_job_url(url: str) -> tuple[str, str]:
    """Return (board_token, job_id) from any Greenhouse job URL."""
    for pattern in (_EMBED, _PATH):
        m = pattern.search(url)
        if m:
            return m.group(1), m.group(2)
    raise ValueError(f"not a Greenhouse job URL: {url}")


def fetch(token: str, job_id: str) -> dict:
    with urllib.request.urlopen(API.format(token=token, job_id=job_id), timeout=30) as r:
        return json.load(r)


def html_to_text(raw: str) -> str:
    """Greenhouse returns the JD as escaped HTML."""
    # ponytail: regex de-tagging, no parser dep. Swap for BeautifulSoup if a JD
    # ever comes back mangled enough to matter.
    text = html.unescape(raw or "")
    text = re.sub(r"<(br|/p|/div|/li|/h\d)[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<li[^>]*>", "- ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def slug(*parts: str) -> str:
    s = "-".join(p.strip().lower() for p in parts if p)
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", s)).strip("-")


def summarize(job: dict) -> list[str]:
    """One line per form field, required ones first. This is what phase 6 fills."""
    lines = []
    for q in job.get("questions", []):
        fields = ", ".join(f"{f['name']}:{f['type']}" for f in q.get("fields", []))
        req = "REQUIRED" if q.get("required") else "optional"
        lines.append(f"[{req}] {q.get('label')} -> {fields}")
        for f in q.get("fields", []):
            if f.get("values"):
                opts = ", ".join(str(v.get("label")) for v in f["values"])
                lines.append(f"           options: {opts}")
    return lines


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("url", nargs="?", help="Greenhouse job URL")
    ap.add_argument("--profile", default="luciano", help="which profile this packet is for")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.url:
        ap.error("need a job URL (or --selftest)")

    token, job_id = parse_job_url(args.url)
    job = fetch(token, job_id)

    out = Path("out") / args.profile / slug(job.get("company_name", token), job.get("title", job_id))
    out.mkdir(parents=True, exist_ok=True)
    (out / "jd.txt").write_text(html_to_text(job.get("content", "")), encoding="utf-8")
    (out / "form.json").write_text(json.dumps(job, indent=2), encoding="utf-8")

    jd_len = len((out / "jd.txt").read_text(encoding="utf-8"))
    required = sum(1 for q in job.get("questions", []) if q.get("required"))
    print(f"{job.get('company_name')} — {job.get('title')}")
    print(f"  {out}/  (jd.txt {jd_len} chars, {len(job.get('questions', []))} fields, {required} required)")
    # phase 5's fallback rule keys off this length
    print(f"  tailoring: {'YES' if jd_len >= 800 else 'NO — JD too thin, use default-resume.md'}")
    print()
    print("\n".join(summarize(job)))
    return 0


def selftest() -> int:
    cases = [
        ("https://job-boards.greenhouse.io/anthropic/jobs/4461450008", ("anthropic", "4461450008")),
        ("https://boards.greenhouse.io/acme/jobs/123?gh_src=x", ("acme", "123")),
        ("https://job-boards.greenhouse.io/acme/jobs/123/", ("acme", "123")),
        ("https://boards.greenhouse.io/embed/job_app?for=acme&token=123", ("acme", "123")),
    ]
    for url, want in cases:
        got = parse_job_url(url)
        assert got == want, f"{url}: got {got}, want {want}"
    for bad in ("https://example.com/jobs/123", "https://greenhouse.io/acme"):
        try:
            parse_job_url(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{bad} should have raised")

    assert html_to_text("<p>A&amp;B</p><ul><li>one</li><li>two</li></ul>") == "A&B\n- one\n- two"
    assert slug("Acme Corp!", "Sr. Engineer") == "acme-corp-sr-engineer"
    print("selftest ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
