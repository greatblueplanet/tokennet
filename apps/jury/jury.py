"""Second Opinion — a jury of independent reviewer personas judges a public
document and tells you where they disagree.

Point it at a public document — a URL, a file, or ``-`` for stdin. Each juror
is a different reviewer *persona* (the Evidence Skeptic, the Statistician, the
Charitable Reader, …), and each judges every claim the document makes.

**The diversity is the persona, not the model.** Even when the fleet serves a
single model, seating five personas gives a real jury of five stances rather
than one model sampled five times. The fleet supplies cheap, distributed
inference — each juror runs on whatever maker is free, and its vote carries
the byline of the machine that served it.

**The question is narrow on purpose**: does *this document* support the claim?
Not whether the claim is true in the world — that needs knowledge a small
model doesn't reliably have. Support-by-the-text is answerable from the text
alone, and it is what catches **overclaiming**: a press release that says
"proven to double productivity" on the strength of nine survey responses isn't
lying about the world, it's claiming more than its own text supports.

**Disagreement is the product.** Nothing synthesizes the jurors' answers away —
the tally happens on your machine, in plain code (see :func:`tally`), and
every vote is shown with the persona that judged and the maker that served it.
A chair model synthesizing a verdict would launder exactly the signal we came
for: if four jurors say "unsupported" and one says "supported", the
interesting fact is *that they disagreed*.

PRIVACY: the jurors can read what they are sent, so this is a tool for public
documents — which is also its subject.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import textwrap
from concurrent.futures import CancelledError, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from html.parser import HTMLParser

import requests

from apps.lib import relay
from apps.lib.relay import Relay, Unauthorized

from . import personas
from .personas import Persona

# How many jurors, by default. Odd, so a jury can actually reach a majority;
# small, because five reads of a claim is already a real signal and the
# fleet's slots are somebody's electricity.
DEFAULT_JURORS = 5

# How much of the document a juror is shown. Context windows vary by whoever's
# machine picks the request up, and every juror must see the *same* text or
# they are not judging the same thing. So one conservative budget for all of
# them, ~4 chars per token.
MAX_DOCUMENT_CHARS = 24_000

EXTRACT = """\
Read the document below and list the factual claims it makes — the assertions a \
sceptical reader would want checked. Prefer the load-bearing ones: what it says \
is true, effective, proven, or measured. Ignore opinions, questions and hedged \
speculation.

Reply with ONLY a JSON array of strings, no prose and no code fence:
["claim one", "claim two"]

Each claim must be a single self-contained sentence, quoting or closely \
paraphrasing the document. At most 8 claims.

The document:
"""

JUDGE = """\
You are one of several independent reviewers. Judge ONE claim against the \
document below.

The claim was taken FROM this document, so of course the document says it. \
"The document states it" is therefore NEVER, by itself, a reason to call a \
claim supported. Nor is it a reason to call one unsupported.

FIRST decide which kind of claim this is.

(a) A PLAIN FACT the author is entitled to simply state — its own price, \
location, product name, what it announced, or what its own survey found. \
Reporting "nine users said they felt more productive" is a plain fact: it is \
the author telling you what happened, and it needs no further evidence.
    → Verdict: supported. (Unless the document contradicts it.)

(b) An EMPIRICAL or COMPARATIVE claim about effect, proof, magnitude or \
superiority — the tells are words like "proven", "doubles", "twice as \
fast", "eliminates", "the only", "the best", "zero". These are claims \
about the world, and the author is NOT entitled to simply assert them.
    → Ask: does the document actually offer evidence that warrants THIS claim?
      - Real evidence, adequate to the claim → supported.
      - No evidence, or evidence far weaker than the claim needs (a handful of \
people saying they *felt* something; two anecdotes; a survey standing in for \
proof) → unsupported.

Reply with ONLY a JSON object, no prose and no code fence:
{"verdict": "supported" | "unsupported" | "contradicted",
 "reason": "one short sentence citing the document"}

- contradicted: the document says something incompatible with the claim.

Be strict with (b) and fair with (a). Confidence is not evidence; a superlative \
is not evidence. But do not punish a document for stating ordinary facts about \
itself.
"""


# --- the document: a URL, a file, or stdin ---


def load_source(source: str) -> tuple[str, str]:
    """Read the document named by `source`. Returns (origin, text).

    Only public documents belong here: every juror is somebody else's machine
    and can read what it is sent — a press release, a paper, a marketing page.
    That is not a limitation so much as the app's subject.
    """
    if source == "-":
        text = sys.stdin.read()
    elif source.startswith(("http://", "https://")):
        resp = requests.get(source, timeout=60)
        if resp.status_code != 200:
            raise SystemExit(f"{source} returned {resp.status_code}")
        text = strip_html(resp.text)
    else:
        text = open(source, encoding="utf-8").read()
    text = text.strip()
    if not text:
        raise SystemExit(f"{source} had no readable text")
    return source, text


class _TextExtractor(HTMLParser):
    """A *crude* HTML-to-text pass: drop script/style bodies, turn block tags
    into line breaks, keep the prose. It is not a reader-mode implementation
    and will happily include a nav bar — an honest trade, because the jury's
    job (does this text support that claim?) survives some clutter. For a
    clean read, pipe the text in yourself."""

    BLOCK_TAGS = frozenset("p div br li h1 h2 h3 h4 h5 h6 tr section article".split())

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skipping = 0  # inside <script>/<style>

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skipping += 1
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skipping = max(0, self._skipping - 1)
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skipping:
            self.parts.append(data)


def strip_html(page: str) -> str:
    parser = _TextExtractor()
    parser.feed(page)  # convert_charrefs unescapes &amp;-style entities for us
    parser.close()
    # Collapse runs of blank space, keeping line breaks between blocks so
    # sentences from different paragraphs don't fuse into nonsense.
    lines = ("".join(parser.parts)).splitlines()
    return "\n".join(" ".join(line.split()) for line in lines if line.strip())


def excerpt(text: str) -> str:
    return text[:MAX_DOCUMENT_CHARS]


# --- the verdicts, and the local tally ---

# Ordered so a tie breaks toward doubt (see `_finding`).
VERDICTS = ("supported", "unsupported", "contradicted")


def parse_verdict(text: str) -> str:
    v = text.strip().lower()
    # A juror whose reply we can't read has said nothing usable. Record it as
    # an abstention rather than guessing which way it meant to vote.
    return v if v in VERDICTS else "abstained"


@dataclass
class Opinion:
    """One juror's view of one claim."""

    juror: str
    # Which machine served it — the byline. Independence you can check.
    maker: str | None
    verdict: str
    reason: str


@dataclass
class Judgment:
    """One claim, and what the jury made of it."""

    claim: str
    opinions: list[Opinion] = field(default_factory=list)


@dataclass
class Finding:
    """The jury's finding on a claim, computed here in plain code."""

    claim: str
    # The verdict with the most votes (abstentions never win — they aren't votes).
    majority: str
    # How many jurors voted, ignoring abstentions.
    voted: int
    # How many agreed with the majority.
    agreed: int
    opinions: list[Opinion]

    def contested(self) -> bool:
        """A jury that did not speak with one voice — the flag worth reading."""
        return self.voted > 1 and self.agreed < self.voted

    def undecided(self) -> bool:
        """Nobody voted (every juror abstained or failed). Not a verdict — an
        absence of one, reported as such rather than dressed up as consensus."""
        return self.voted == 0

    def agreement(self) -> float:
        return self.agreed / self.voted if self.voted else 0.0

    def doubted(self) -> bool:
        """The jury doubts the document backs this up. What you came for."""
        return self.majority in ("unsupported", "contradicted")


def tally(judgments: list[Judgment]) -> list[Finding]:
    """Tally each claim, then order the report by what deserves attention:
    claims the jury *doubted* first, then claims it *split* on, then the
    boring ones. This happens locally — no model summarizes the jurors."""
    findings = [_finding(j) for j in judgments]
    findings.sort(key=_rank, reverse=True)
    return findings


def _rank(finding: Finding) -> float:
    if finding.undecided():
        return -1.0  # nothing was decided; don't lead with it
    doubt = 2.0 if finding.doubted() else 0.0
    # A 3-2 split scores higher than a 5-0 agreement.
    return doubt + (1.0 - finding.agreement())


def _finding(judgment: Judgment) -> Finding:
    votes: dict[str, int] = {}
    for opinion in judgment.opinions:
        if opinion.verdict != "abstained":
            votes[opinion.verdict] = votes.get(opinion.verdict, 0) + 1
    # Ties break toward doubt: on an equal count the *later* verdict in
    # VERDICTS wins — i.e. unsupported over supported. A jury split down the
    # middle on whether a document backs a claim has not established that it does.
    majority = max(
        votes, key=lambda v: (votes[v], VERDICTS.index(v)), default="abstained"
    )
    return Finding(
        claim=judgment.claim,
        majority=majority,
        voted=sum(votes.values()),
        agreed=votes.get(majority, 0),
        opinions=judgment.opinions,
    )


# --- the deliberation: claims × personas, all independent ---


def extract_claims(fleet: Relay, model: str, document: str) -> list[str]:
    """Extract the claims. One pass, one model — every juror must judge the
    *same* list, or their verdicts aren't comparable and the disagreement
    signal is meaningless. (This is the one step with a single point of
    failure, which is why the claims are printed in the report: you can see
    what was judged.)"""
    reply = fleet.ask(model, EXTRACT + excerpt(document))
    claims = _parse_claims(reply.text)
    if not claims:
        raise SystemExit(
            "the model didn't return a usable list of claims — try another --model"
        )
    return claims


def _parse_claims(reply: str) -> list[str] | None:
    """Pull a JSON array of claims out of a reply, tolerating the fence and
    the throat-clearing a small model wraps it in."""
    start, end = reply.find("["), reply.rfind("]")
    if start < 0 or end <= start:
        return None
    try:
        raw = json.loads(reply[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, list):
        return None
    claims = [c.strip() for c in raw if isinstance(c, str) and c.strip()]
    return claims or None


def _parse_opinion(reply: str) -> dict | None:
    start, end = reply.find("{"), reply.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(reply[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _judge(
    fleet: Relay, model: str, persona: Persona, claim: str, document: str
) -> Opinion:
    """One persona, one claim. The persona framing leads the prompt (it sets
    the juror's stance); the shared JUDGE task and the document follow, so
    every juror weighs the *same* text and the *same* question through a
    different lens."""
    prompt = (
        f"{persona.detail}\n\n{JUDGE}\nThe claim:\n{claim}\n\nThe document:\n{document}"
    )
    reply = fleet.ask(model, prompt)
    raw = _parse_opinion(reply.text) or {"verdict": "abstained", "reason": ""}
    return Opinion(
        juror=persona.name,
        maker=reply.maker,
        verdict=parse_verdict(str(raw.get("verdict", ""))),
        reason=str(raw.get("reason", "")),
    )


def deliberate(
    fleet: Relay, jury: list[Persona], model: str, claims: list[str], document: str
) -> list[Judgment]:
    """Every persona judges every claim: `claims × personas` independent
    requests, which is exactly the shape the network is built for. All
    personas use the same `model` (the relay load-balances across whatever
    makers serve it) — the diversity is the persona, not the model.

    A juror that fails on a claim simply doesn't vote on it: a missing opinion
    is honest, and better than inventing a verdict to fill the table."""
    judgments = [Judgment(claim=claim) for claim in claims]
    total, done = len(claims) * len(jury), 0
    fatal: list[Exception] = []

    def one(index: int, persona: Persona):
        return index, persona, _judge(fleet, model, persona, claims[index], document)

    with ThreadPoolExecutor(max_workers=len(jury)) as pool:
        futures = [
            pool.submit(one, index, persona)
            for index in range(len(claims))
            for persona in jury
        ]
        for future in as_completed(futures):
            try:
                index, persona, opinion = future.result()
            except CancelledError:
                continue
            except Unauthorized as e:
                # A bad credential fails identically for every remaining
                # request — don't spend the whole jury rediscovering that.
                if not fatal:
                    fatal.append(e)
                    for f in futures:
                        f.cancel()
                continue
            except Exception as e:
                # A juror that couldn't answer simply doesn't vote. Better a
                # smaller jury than a fabricated verdict.
                print(f"  ! a juror abstained: {relay.describe(e)}", file=sys.stderr)
                continue
            done += 1
            print(f"\r  {done}/{total} opinions in", end="", file=sys.stderr)
            judgments[index].opinions.append(opinion)
    print(file=sys.stderr)
    if fatal:
        raise SystemExit(relay.describe(fatal[0]))
    return judgments


# --- the report ---


class Markdown:
    """How the report is dressed when it is going into a file: markdown."""

    def h1(self, text: str) -> str:
        return f"# {text}"

    def strong(self, text: str) -> str:
        return f"**{text}**"

    def em(self, text: str) -> str:
        return f"*{text}*"

    def verdict(self, text: str) -> str:
        return f"**{text}**"

    def claim(self, number: int, glyph: str, text: str) -> str:
        return f"## {glyph} Claim #{number}: {text}"

    def consensus(self, verdict: str, agreed: int, voted: int) -> str:
        return f"**Consensus:** {verdict} — {agreed} of {voted} juror(s) agreed."

    def details(self) -> str:
        return "\n**Details:**\n"

    def vote(self, verdict: str, byline: str, reason: str) -> str:
        line = f"- **{verdict}** — *{byline}*"
        return f"{line}: {reason}" if reason else line

    def rule(self) -> str:
        return "---"


class Terminal:
    """How the report is dressed when it is going to a screen.

    Markdown on a terminal is worse than no markup at all — you end up reading
    around the asterisks. So the emphasis becomes colour, and the verdicts get
    the colour that matters: whether the jury backed the claim or doubted it.
    """

    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    # 256-colour, not the basic 8: the basic palette is whatever the user's
    # theme says it is, and its green and yellow land close enough together to
    # be indistinguishable. Green against *orange* separates by brightness as
    # well as hue, so it survives a dim theme.
    GREEN = "\033[38;5;41m"
    ORANGE = "\033[38;5;214m"
    RED = "\033[38;5;196m"

    VERDICT_COLOURS = {
        "supported": GREEN,
        "unsupported": ORANGE,
        "contradicted": RED,
        "abstained": DIM,
    }
    # Colour is never the only signal. Anyone red-green colourblind, or reading
    # a piped copy with the codes stripped, still gets the mark.
    VERDICT_MARKS = {
        "supported": "✓",
        "unsupported": "✗",
        "contradicted": "⊘",
        "abstained": "·",
    }

    def h1(self, text: str) -> str:
        return f"{self.BOLD}{text}{self.RESET}\n{'═' * len(text)}"

    def strong(self, text: str) -> str:
        return f"{self.BOLD}{text}{self.RESET}"

    def em(self, text: str) -> str:
        return f"{self.DIM}{text}{self.RESET}"

    def verdict(self, text: str) -> str:
        colour = self.VERDICT_COLOURS.get(text, "")
        mark = self.VERDICT_MARKS.get(text, "")
        return f"{colour}{self.BOLD}{mark} {text}{self.RESET}" if colour else text

    # The glyph is how you skim a long report, so it carries the same scale.
    FLAG_COLOURS = {"✓": GREEN, "≠": ORANGE, "⚠": ORANGE, "✗": RED}

    def claim(self, number: int, glyph: str, text: str) -> str:
        colour = self.FLAG_COLOURS.get(glyph, self.DIM)
        return (
            f"{colour}{glyph}{self.RESET} "
            f"{self.BOLD}Claim #{number}: {text}{self.RESET}"
        )

    def consensus(self, verdict: str, agreed: int, voted: int) -> str:
        # Directly under the claim, no blank line: the claim and what the jury
        # made of it are one thought, and the eye should not have to cross a gap.
        return (
            f"   Consensus: {self.verdict(verdict)} "
            f"{self.DIM}({agreed} of {voted} juror(s) agreed){self.RESET}"
        )

    def details(self) -> str:
        return f"   {self.DIM}Details:{self.RESET}"

    def vote(self, verdict: str, byline: str, reason: str) -> str:
        """One juror's vote, indented under Details, with its reasoning wrapped
        and indented again beneath it.

        The reasons run to two or three lines each. Left flush against the
        verdicts they become a wall of prose you cannot skim; set in their own
        indented block, the verdict column stays scannable down the page.
        """
        head = f"     {self.verdict(verdict)}  {self.DIM}{byline}{self.RESET}"
        if not reason:
            return head
        width = max(40, shutil.get_terminal_size((100, 24)).columns - 10)
        body = textwrap.fill(
            reason, width=width, initial_indent=" " * 9, subsequent_indent=" " * 9
        )
        return f"{head}\n{self.DIM}{body}{self.RESET}"

    def rule(self) -> str:
        return f"{self.DIM}{'─' * 60}{self.RESET}"


Style = Markdown | Terminal


def _seats(by_maker: dict[str, int]) -> str:
    """One juror's machines, busiest first: `curvy-sugar ×3, acme ×1`.

    Ties break on the name so the same votes always render the same way — a
    report you can diff is worth more than one ordered by dict insertion.
    """
    return ", ".join(
        maker if votes == 1 else f"{maker} ×{votes}"
        for maker, votes in sorted(by_maker.items(), key=lambda kv: (-kv[1], kv[0]))
    )


def report(
    origin: str,
    jury: list[Persona],
    findings: list[Finding],
    locations: dict[str, str] | None = None,
    style: Style | None = None,
) -> str:
    """Render the jury's findings, headed by the empanelled personas so a
    reader knows exactly which stances judged the document. Every juror's vote
    is shown with the machine that served it — a verdict you can't audit is
    just another opinion. `locations` maps a maker's name to its advertised
    location, for the Served-by line.

    `style` decides the dressing: `Markdown()` (the default) for a file,
    `Terminal()` for a screen. One report, two skins — the structure and the
    wording are identical, so what you read is what you saved."""
    s = style or Markdown()
    # Two tallies over the same votes: which machines served at all, and which
    # machine took which seat. The relay picks a maker per request, so a juror
    # is not pinned to one machine — a persona's votes can be spread across
    # several, and that is what the per-juror line has to show.
    served: dict[str, int] = {}
    seats: dict[str, dict[str, int]] = {}
    for finding in findings:
        for opinion in finding.opinions:
            if opinion.maker:
                served[opinion.maker] = served.get(opinion.maker, 0) + 1
                by_maker = seats.setdefault(opinion.juror, {})
                by_maker[opinion.maker] = by_maker.get(opinion.maker, 0) + 1

    out = [s.h1("Second opinion") + "\n", f"{s.strong('Document:')} {origin}\n"]
    out.append(
        f"{s.strong('Jury:')} {len(jury)} juror(s), "
        "each a different reviewer persona:\n"
    )
    for p in jury:
        out.append(f"- {s.strong(f'#{p.number} {p.name}')} — {p.lens}")
        # Which machine took this seat. The relay picks per request, so a busy
        # juror can show several — that spread is the independence, visible.
        if p.name in seats:
            out.append("  - " + s.em("served by " + _seats(seats[p.name])))
    out.append("")

    # The machines that actually served the votes, and where they are — the
    # at-a-glance answer to "were the seats really different?"
    if served:
        parts = []
        for maker, votes in sorted(served.items(), key=lambda kv: -kv[1]):
            where = (locations or {}).get(maker)
            parts.append(
                f"{maker} ({where}) — {votes} vote(s)"
                if where
                else f"{maker} — {votes} vote(s)"
            )
        out.append(s.strong("Served by:") + " " + "; ".join(parts) + "\n")

    if not findings:
        out.append("No checkable claims were found in this document.")
        return "\n".join(out) + "\n"

    doubted = sum(1 for f in findings if f.doubted())
    contested = sum(1 for f in findings if f.contested())
    out.append(
        f"The jury read {len(findings)} claim(s). "
        f"It doubted {s.strong(str(doubted))}, and split on {s.strong(str(contested))}.\n"
    )
    if doubted == 0 and contested == 0:
        out.append(
            "Nothing stood out: the jury agreed the document supports what it claims.\n"
        )
    out.append(s.rule() + "\n")

    for number, finding in enumerate(findings, 1):
        # Claim, then straight into what the jury made of it, then the votes
        # underneath — one block per claim, indented so the page has a spine.
        out.append(s.claim(number, _flag(finding), finding.claim))
        if finding.undecided():
            out.append(s.em("No juror returned a usable verdict on this claim.") + "\n")
            continue
        out.append(s.consensus(finding.majority, finding.agreed, finding.voted))
        out.append(s.details())
        # Every vote, with its byline: the independence is the evidence.
        for opinion in finding.opinions:
            byline = (
                f"{opinion.juror} via {opinion.maker}"
                if opinion.maker
                else opinion.juror
            )
            out.append(s.vote(opinion.verdict, byline, opinion.reason.strip()))
        out.append("")

    out.append(
        s.rule()
        + "\n\n"
        + s.em(
            "The jury judged only whether this document supports each claim — "
            "not whether the claim is true in the world. A split jury is not "
            "proof of anything; it is a sentence worth reading yourself."
        )
    )
    return "\n".join(out) + "\n"


def _flag(finding: Finding) -> str:
    """A glyph that tells you, at a glance, why a claim is near the top."""
    if finding.undecided():
        return "·"
    if finding.doubted() and finding.contested():
        return "⚠"
    if finding.doubted():
        return "✗"
    if finding.contested():
        return "≠"
    return "✓"


# --- the CLI ---


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="tokennet-jury",
        description=(
            "Second Opinion: a jury of independent reviewer personas judges a "
            "public document and tells you where they disagree."
        ),
        epilog=(
            "examples:\n"
            "  tokennet-jury https://example.com/we-are-the-best\n"
            "  tokennet-jury paper.txt --jurors 9 --output verdict.md\n"
            "  tokennet-jury paper.txt --panel 2,3,10,11    # the skeptics\n"
            "  tokennet-jury --list\n"
            "  pbpaste | tokennet-jury -\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "source",
        nargs="?",
        help="the document: a URL, a path, or `-` for stdin (omit only with --list)",
    )
    parser.add_argument(
        "--jurors",
        "-j",
        type=int,
        default=DEFAULT_JURORS,
        help=f"how many personas to seat, at random (default {DEFAULT_JURORS})",
    )
    parser.add_argument(
        "--panel",
        help="seat these specific personas by number, e.g. `--panel 2,4,10` (see --list)",
    )
    parser.add_argument(
        "--list", action="store_true", help="print the persona roster and exit"
    )
    parser.add_argument(
        "--model",
        default="any",
        help="model the jurors use; `any` lets the relay route each request "
        "to whatever maker is free (default: any)",
    )
    parser.add_argument(
        "--output", "-o", help="write the report here as well as printing it"
    )
    args = parser.parse_args(argv)

    if args.list:
        print(f"The jury roster ({len(personas.PERSONAS)} personas):\n")
        for p in personas.roster():
            print(f"  #{p.number:<2} {p.name:<22} {p.lens}")
        print(
            "\nSeat a random jury with `--jurors N`, or choose with `--panel 2,4,10`."
        )
        return

    # Seat the jury *first* — a bad `--panel` should fail before we fetch a
    # document or spend a token.
    try:
        panel = [int(n) for n in args.panel.split(",")] if args.panel else None
        jury = personas.seat(panel, args.jurors)
    except ValueError as e:
        raise SystemExit(str(e)) from None

    if not args.source:
        raise SystemExit(
            "no document — give a URL, a file, or `-` for stdin (or --list)"
        )

    origin, text = load_source(args.source)
    print(f"Read {origin} ({len(text)} chars).", file=sys.stderr)
    # One compact line here — the report carries the full roster with lenses,
    # and printing both in long form was clutter.
    print(
        f"Empanelled jury ({len(jury)} of {len(personas.PERSONAS)}): "
        + ", ".join(p.name for p in jury),
        file=sys.stderr,
    )

    try:
        fleet = Relay.from_env()
    except Unauthorized as e:
        raise SystemExit(str(e)) from None

    print("Extracting the claims…", file=sys.stderr)
    try:
        claims = extract_claims(fleet, args.model, text)
    except (relay.CallError, relay.AtCapacity, Unauthorized) as e:
        raise SystemExit(relay.describe(e)) from None
    print(f"Found {len(claims)} claim(s).", file=sys.stderr)

    judgments = deliberate(fleet, jury, args.model, claims, excerpt(text))

    # Where each serving machine is, for the report's Served-by line. Best
    # effort: a maker that left between the votes and now just has no location.
    try:
        locations = {
            m.maker: m.location for m in fleet.models() if m.maker and m.location
        }
    except Exception:
        locations = {}

    # Tally — locally. No model gets to summarize the jurors; that would
    # launder the disagreement we came for.
    findings = tally(judgments)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report(origin, jury, findings, locations))
        print(f"Written to {args.output}.", file=sys.stderr)

    # A file gets markdown; a terminal gets colour. Redirected stdout is
    # somebody saving the report, so it gets markdown too — escape codes in a
    # piped file are nobody's idea of a good time.
    screen: Style = Terminal() if sys.stdout.isatty() else Markdown()
    print(report(origin, jury, findings, locations, style=screen))


if __name__ == "__main__":
    main()
