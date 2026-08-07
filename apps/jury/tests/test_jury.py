"""Unit tests for the jury — all local, no network.

The tally is the app: a program whose entire output is a vote count must
never invent a vote, lose a split, or break a tie toward comfort.
"""

import pytest

from apps.jury import personas
from apps.jury.jury import (
    MAX_DOCUMENT_CHARS,
    Judgment,
    Opinion,
    Terminal,
    _parse_claims,
    _parse_opinion,
    excerpt,
    report,
    strip_html,
    tally,
)


def opinion(juror: str, verdict: str) -> Opinion:
    return Opinion(
        juror=juror, maker="ludicrous-foot", verdict=verdict, reason="because"
    )


def judgment(claim: str, verdicts: list[str]) -> Judgment:
    return Judgment(
        claim=claim,
        opinions=[opinion(f"juror-{i}", v) for i, v in enumerate(verdicts)],
    )


# --- parsing model replies ---


def test_parses_a_claim_list_even_when_fenced_or_chatty():
    assert _parse_claims('["The sky is blue.", "Water is wet."]') == [
        "The sky is blue.",
        "Water is wet.",
    ]
    assert _parse_claims('```json\n["One claim."]\n```') == ["One claim."]
    assert _parse_claims('Here are the claims:\n["One claim."]\nHope this helps!') == [
        "One claim."
    ]


def test_refuses_an_unusable_claim_list():
    # No list, or an empty one, is not a set of claims — the caller turns that
    # into a clean error rather than convening a jury with nothing to judge.
    assert _parse_claims("I couldn't find any claims.") is None
    assert _parse_claims("[]") is None
    assert _parse_claims('["  "]') is None


def test_parses_a_verdict():
    raw = _parse_opinion('{"verdict":"unsupported","reason":"Only nine people."}')
    assert raw == {"verdict": "unsupported", "reason": "Only nine people."}


def test_excerpt_bounds_the_document():
    # Every juror must be shown the same text, so the excerpt is a hard cut.
    assert len(excerpt("x" * (MAX_DOCUMENT_CHARS + 100))) == MAX_DOCUMENT_CHARS
    assert excerpt("short") == "short"


# --- the tally ---


def test_a_split_jury_is_flagged_as_contested():
    unanimous = tally([judgment("c", ["supported"] * 3)])[0]
    assert not unanimous.contested()
    assert unanimous.agreement() == 1.0

    split = tally([judgment("c", ["supported", "supported", "unsupported"])])[0]
    assert split.contested()
    assert split.majority == "supported"
    assert (split.agreed, split.voted) == (2, 3)


def test_abstentions_are_not_votes():
    # A juror we couldn't read must not silently become a vote for whatever
    # the others said.
    f = tally([judgment("c", ["supported", "abstained", "abstained"])])[0]
    assert f.voted == 1
    assert f.majority == "supported"
    assert not f.contested(), "one vote can't disagree with itself"

    nobody = tally([judgment("c", ["abstained"] * 3)])[0]
    assert nobody.undecided()
    assert nobody.majority == "abstained"


def test_a_tie_breaks_toward_doubt():
    # A jury split down the middle has *not* established that the document
    # backs the claim.
    f = tally([judgment("c", ["supported", "unsupported"])])[0]
    assert f.majority == "unsupported"
    assert f.doubted()


def test_the_report_leads_with_doubt_then_dissent():
    findings = tally(
        [
            judgment("fine", ["supported"] * 3),
            judgment("undecided", ["abstained"] * 3),
            judgment("split", ["supported", "supported", "unsupported"]),
            judgment("doubted", ["unsupported"] * 3),
        ]
    )
    assert [f.claim for f in findings] == ["doubted", "split", "fine", "undecided"]


# --- the report ---


def panel() -> list[personas.Persona]:
    return personas.seat([2, 4], 0)


def test_a_finding_shows_the_tally_the_bylines_and_the_reasons():
    findings = tally(
        [
            Judgment(
                claim="It doubles productivity.",
                opinions=[
                    Opinion(
                        "a",
                        "ludicrous-foot",
                        "unsupported",
                        "only nine people were surveyed",
                    ),
                    Opinion("b", "ludicrous-foot", "unsupported", "no evidence"),
                    Opinion("c", "ludicrous-foot", "supported", "seems fine"),
                ],
            )
        ]
    )
    out = report("https://example.com", panel(), findings)
    assert "It doubles productivity." in out
    assert "2 of 3 juror(s) agreed" in out
    assert "ludicrous-foot" in out, f"no byline:\n{out}"
    assert "only nine people were surveyed" in out, f"no reason:\n{out}"
    assert "⚠" in out, "a doubted+split claim gets the loudest flag"
    assert "split on **1**" in out


def test_the_report_names_the_machines_that_served_and_where():
    # (A) which makers served the votes and (B) where they are, once, at a
    # glance — the per-vote lines then only repeat the name, not the place.
    findings = tally(
        [
            Judgment(
                claim="c",
                opinions=[
                    Opinion("a", "ludicrous-foot", "supported", ""),
                    Opinion("b", "ludicrous-foot", "supported", ""),
                    Opinion("c", "patient-anvil", "unsupported", ""),
                    Opinion("d", None, "abstained", ""),  # no maker, not counted
                ],
            )
        ]
    )
    out = report("doc.txt", panel(), findings, {"ludicrous-foot": "Palo Alto, US"})
    assert (
        "**Served by:** ludicrous-foot (Palo Alto, US) — 2 vote(s); patient-anvil — 1 vote(s)"
        in out
    )


def test_the_roster_says_which_machine_took_which_seat():
    # The Served-by line says which machines served; this says which seat each
    # one sat in. A juror is not pinned to a machine — the relay picks per
    # request — so a persona's votes can spread across several, busiest first.
    jury = panel()
    first, second = jury[0].name, jury[1].name
    findings = tally(
        [
            Judgment(
                claim="c1",
                opinions=[
                    Opinion(first, "patient-anvil", "supported", ""),
                    Opinion(second, "ludicrous-foot", "unsupported", ""),
                ],
            ),
            Judgment(
                claim="c2",
                opinions=[
                    Opinion(first, "patient-anvil", "supported", ""),
                    Opinion(second, "patient-anvil", "unsupported", ""),
                ],
            ),
        ]
    )
    out = report("doc.txt", jury, findings)
    # One machine took both of this juror's seats, and says so.
    assert "*served by patient-anvil ×2*" in out
    # This one was spread across two machines, one vote each — no count needed,
    # and ties break on the name so the same votes always render the same way.
    assert "*served by ludicrous-foot, patient-anvil*" in out


def test_the_terminal_style_colours_verdicts_and_drops_the_markdown():
    # Markdown on a screen just means reading around asterisks. The terminal
    # dressing carries the same information in colour instead.
    findings = tally(
        [
            Judgment(
                claim="c",
                opinions=[
                    Opinion("a", "patient-anvil", "supported", ""),
                    Opinion("b", "patient-anvil", "contradicted", ""),
                ],
            )
        ]
    )
    out = report("doc.txt", panel(), findings, style=Terminal())

    assert "**" not in out, f"markdown leaked onto the screen:\n{out}"
    assert "##" not in out
    # Supported and contradicted must not look alike — that is the whole point.
    assert f"{Terminal.VERDICT_COLOURS['supported']}\033[1msupported" in out
    assert f"{Terminal.VERDICT_COLOURS['contradicted']}\033[1mcontradicted" in out


def test_both_styles_carry_the_same_words():
    # One report, two skins: what you read on screen is what you saved.
    findings = tally([judgment("The sky is blue.", ["supported", "unsupported"])])
    plain = report("doc.txt", panel(), findings, style=Terminal())
    for fragment in ("The sky is blue.", "1 of 2 juror(s) agreed", "Second opinion"):
        assert fragment in plain
        assert fragment in report("doc.txt", panel(), findings)


def test_a_document_the_jury_agrees_with_says_so():
    findings = tally([judgment("The sky is blue.", ["supported"] * 3)])
    out = report("doc.txt", panel(), findings)
    assert "Nothing stood out" in out
    assert "doubted **0**" in out


def test_an_empty_jury_report_explains_itself():
    out = report("doc.txt", panel(), [])
    assert "No checkable claims" in out


# --- the personas ---


def test_roster_numbers_unique_and_populated():
    numbers = [p.number for p in personas.PERSONAS]
    assert len(set(numbers)) == len(numbers), "duplicate persona numbers"
    assert len(numbers) >= 5, "roster is suspiciously small"
    for p in personas.PERSONAS:
        assert p.name and p.lens and p.detail


def test_panel_seats_the_named_personas():
    assert [p.number for p in personas.seat([3, 1], 0)] == [3, 1]
    with pytest.raises(ValueError):
        personas.seat([250], 0)  # unknown number must fail
    with pytest.raises(ValueError):
        personas.seat([1, 1], 0)  # a repeat must fail


def test_random_jury_is_sized_distinct_and_capped():
    for _ in range(32):
        seated = personas.seat(None, 5)
        assert len(seated) == 5
        assert len({p.number for p in seated}) == 5, "repeated a persona"
    assert len(personas.seat(None, 999)) == len(personas.PERSONAS)
    assert len(personas.seat(None, 0)) == 1, "at least one juror"


# --- the HTML extractor ---


def test_strips_scripts_styles_and_tags():
    html = (
        "<html><head><style>body { color: red }</style>"
        "<script>var x = 1 < 2;</script></head>"
        "<body><h1>Title</h1><p>Hello <b>world</b>.</p></body></html>"
    )
    text = strip_html(html)
    assert "Title" in text
    assert "Hello world." in text
    assert "color: red" not in text, f"style body leaked: {text!r}"
    assert "var x" not in text, f"script body leaked: {text!r}"


def test_block_tags_become_breaks_so_sentences_do_not_fuse():
    text = strip_html("<p>First sentence.</p><p>Second sentence.</p>")
    assert "First sentence.\nSecond sentence." in text, f"paragraphs fused: {text!r}"


def test_unescapes_the_entities_that_matter():
    assert strip_html("<p>a &amp; b &lt; c</p>").strip() == "a & b < c"
