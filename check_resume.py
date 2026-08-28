#!/usr/bin/env python3
"""Assert a tailored resume invents nothing that isn't in the profile.

    python3 check_resume.py out/luciano/acme-sre/resume.md --profile luciano
    python3 check_resume.py --selftest

Exit 1 on any claim in the resume that does not trace back to profile.md.
Tailoring may select, cut, and re-word. It may not add. This is what enforces that.
"""

import argparse
import re
import sys
from pathlib import Path

# Capitalized-at-sentence-start words are grammar, not claims, so the first token of
# every sentence is dropped before checking. These survive that and are still noise.
STOPWORDS = {
    "i", "a", "an", "the", "and", "or", "but", "for", "with", "from", "to", "of",
    "in", "on", "at", "by", "as", "is", "are", "was", "were", "be", "been",
    "present", "remote", "native", "fluent", "current", "personal", "project",
    "senior", "junior", "jr", "lead", "engineer", "analyst", "developer", "founder",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "years", "year", "months",
}

# A token worth checking: has a digit, is ALLCAPS, is CamelCase, is dotted (Node.js),
# or is simply Capitalized. Trailing possessives and punctuation are stripped first.
CLAIM = re.compile(r"^(?:[A-Z][\w.+#/-]*|\w*\d[\w.+#/%-]*)$")


def strip_markdown(text: str, drop_headings: bool = True) -> str:
    """drop_headings=True for a resume (its headings are layout, not claims);
    False for a profile, whose headings carry employer and project names."""
    lines = text.splitlines()
    if drop_headings:
        lines = [ln for ln in lines if not ln.lstrip().startswith("#")]
    # Leading bullet markers, so the bullet's first word counts as sentence-initial
    # and its verb ("Conducted", "Utilized") is not mistaken for a claim.
    lines = [re.sub(r"^\s*(?:[-*•]|\d+\.)\s+", "", ln) for ln in lines]
    text = "\n".join(lines)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)     # HTML comments
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)     # links -> label
    text = re.sub(r"[*_`]+", "", text)                        # emphasis
    return text


def claim_tokens(text: str) -> set[str]:
    """Tokens in `text` that assert something, minus sentence-initial capitals."""
    found = set()
    for sentence in re.split(r"(?<=[.!?])\s+|\n", strip_markdown(text)):
        words = sentence.split()
        for word in words[1:]:                     # drop sentence-initial capital
            tok = word.strip("(),;:•-—\"'’“”[]|").rstrip(".").strip()
            tok = re.sub(r"['’]s$", "", tok)
            if len(tok) < 2 or tok.lower() in STOPWORDS:
                continue
            if CLAIM.match(tok):
                found.add(tok)
    return found


def numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?", strip_markdown(text)))


def supported(tok: str, haystack: str) -> bool:
    if tok.lower() in haystack:
        return True
    # "Cypress-based" is supported by "Cypress", "Terraform-driven" by "Terraform".
    # ponytail: any part matching is enough, so "AWS-Kubernetes" would slip through.
    # A bare invented "Kubernetes" elsewhere in the resume still gets caught.
    parts = [p for p in re.split(r"[-/]", tok.lower()) if len(p) > 2]
    return any(p in haystack for p in parts)


def check(resume: str, profile: str) -> list[str]:
    haystack = strip_markdown(profile, drop_headings=False).lower()
    problems = []
    for tok in sorted(claim_tokens(resume)):
        if not supported(tok, haystack):
            problems.append(f"unsupported term: {tok}")
    for num in sorted(numbers(resume)):
        if num not in haystack:
            problems.append(f"unsupported number: {num}")
    return problems


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("resume", nargs="?", help="path to the generated resume.md")
    ap.add_argument("--profile", default="luciano")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return selftest()
    if not args.resume:
        ap.error("need a resume path (or --selftest)")

    profile_path = Path("profiles") / args.profile / "profile.md"
    problems = check(
        Path(args.resume).read_text(encoding="utf-8"),
        profile_path.read_text(encoding="utf-8"),
    )
    if problems:
        print(f"FAIL {args.resume} vs {profile_path}")
        for p in problems:
            print(f"  {p}")
        print(f"\n{len(problems)} claim(s) not traceable to the profile. Fix the resume, "
              f"or add the fact to the profile if it is genuinely true.")
        return 1
    print(f"ok {args.resume} — every claim traces to {profile_path}")
    return 0


def selftest() -> int:
    profile = """
    # Profile
    Worked at Wisecut AI on AWS with Terraform. Cut costs ~24.8%.
    Managed 20+ units at 99.5% availability.
    """
    # Reordering, cutting, and re-wording are all fine.
    ok = "Reduced the AWS invoice by ~24.8% using Terraform at Wisecut AI."
    assert check(ok, profile) == [], check(ok, profile)

    # The two failures that actually happen:
    invented_tech = "Deployed on AWS with Kubernetes."
    assert any("Kubernetes" in p for p in check(invented_tech, profile))

    invented_number = "Cut costs by 40% across 12 teams."
    problems = check(invented_number, profile)
    assert any("40" in p for p in problems), problems
    assert any("12" in p for p in problems), problems

    # Sentence-initial capitals are grammar, not claims.
    assert check("Managed infrastructure. Delivered results.", profile) == []

    # Headings and emphasis are not claims.
    assert check("## EXPERIENCE\n**Terraform** at Wisecut AI", profile) == []

    # A bullet's leading verb is grammar, not a claim.
    assert check("- Conducted migrations at Wisecut AI\n- Performed rightsizing", profile) == []

    # Employers and projects named only in a profile heading still count as support.
    assert check("Shipped the Widget API.", "## Widget API\nBuilt it.") == []

    # Hyphenated compounds are supported by their parts.
    assert check("Ran Terraform-driven rollouts.", profile) == []

    print("selftest ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
