# Second Opinion — the rules

What `tokennet-jury` actually does between "here is a document" and the
report, so nothing in the verdict is a surprise. The code is
[`jury.py`](../apps/jury/jury.py); the roster is
[`personas.py`](../apps/jury/personas.py) (`tokennet-jury --list` prints
it).

## The pipeline

1. **Source** — a URL, a file, or `-` for stdin. A URL gets a *crude*
   HTML-to-text pass: scripts and styles dropped, block tags become line
   breaks, everything else kept — a nav bar will survive it. That's an honest
   trade (the jury's question tolerates clutter), but for a clean read, pipe
   the text in yourself.
2. **Claims** — one model call lists the document's checkable factual claims.
   One pass, one model, because every juror must judge the *same* list or
   their disagreement means nothing. It is the pipeline's one single point of
   failure, which is why the report prints the claims: you can see what was
   judged.
3. **Deliberation** — every persona judges every claim: `claims × jurors`
   independent requests, fanned out across the fleet. A juror that fails on a
   claim simply doesn't vote on it.
4. **Tally and report** — locally, in plain code (`tally`). No model
   summarizes the jurors.

## The limits

- **The document is truncated to 24,000 characters** (roughly ten pages of
  prose, ~6k tokens). Context windows vary by whichever machine picks a
  request up, and every juror must see the *same* text — so one conservative
  budget for all of them. Point the jury at a long paper and it judges the
  front of it.
- **At most 8 claims** are extracted, preferring the load-bearing ones.
- **Default jury: 5 personas**, seated at random from the 13 — odd, so a
  majority is possible; small, because five reads of a claim is already a
  real signal and the fleet's slots are somebody's electricity. `--jurors N`
  resizes; `--panel 2,4,10` seats exact personas instead.
- **One model for all jurors** (`--model`, default `any`): the diversity is
  the persona, not the model.

A run costs `claims × jurors + 1` completions — with the defaults, up to 41.

## Verdicts, ties, abstentions

Each juror answers with one of **supported**, **unsupported**,
**contradicted** (the document says something incompatible with the claim). A
reply that can't be read as one of those is recorded as **abstained** — the
juror said nothing usable, and guessing which way it meant to vote would be
worse than a smaller jury.

The majority is the verdict with the most votes, abstentions never counted.
**Ties break toward doubt**: on an equal count, `unsupported` beats
`supported` and `contradicted` beats both. A jury split down the middle on
whether a document backs a claim has not established that it does. If *nobody*
voted, the claim is reported as undecided — an absence of a verdict, not
dressed up as consensus.

## The report's order and flags

Claims are ordered by what deserves attention: doubted first, then split, then
the boring agreement; undecided last. Each headline carries a glyph:

| flag | meaning |
|---|---|
| ⚠ | doubted **and** split — the jury leans against it, and disagreed |
| ✗ | doubted, unanimously |
| ≠ | split, but the majority still said supported |
| ✓ | supported, unanimously |
| · | undecided — no juror returned a usable verdict |

Every vote is printed with its persona *and* the maker that served it (with
its advertised location, when the relay knows one) — the independence is the
evidence, and a verdict you can't audit is just one more opinion.

## Which machine took which seat

The report answers that twice, at different resolutions. The **Served by** line
lists every machine that served a vote, busiest first, with its location. The
**jury roster** goes further and says, per juror, which machines sat in that
seat:

```
- #2 The Evidence Skeptic — "Where's the proof?" …
  - served by patient-anvil ×2, ludicrous-foot
```

A juror is not pinned to a machine. The relay picks a maker per request, so one
persona's votes can spread across several, and the roster shows that spread
rather than hiding it behind a single name. Machines are listed busiest first,
ties broken on the name, so the same votes always render the same way and two
reports can be diffed.

## Markdown for a file, colour for a screen

The same report is rendered two ways. `--output` writes markdown. Printing to a
terminal drops the markup — asterisks are noise you have to read around — and
spends colour on the distinction that matters. Redirected stdout gets markdown,
since that is somebody saving the report rather than reading it.

| verdict | mark | colour |
|---|---|---|
| supported | ✓ | green |
| unsupported | ✗ | orange |
| contradicted | ⊘ | red |
| abstained | · | dim |

Two deliberate choices there. The colours are **256-colour, not the basic
eight**: the basic palette is whatever the user's theme makes it, and its green
and yellow land close enough together to be indistinguishable in a soft theme.
Green against *orange* separates by brightness as well as hue. And **colour is
never the only signal** — every verdict carries its own mark, so the report
still reads for someone red-green colourblind, or in a piped copy with the
escape codes stripped.

## How a claim is laid out

```
⚠ Claim #1: A well-rested mind makes fewer mistakes
   Consensus: ✗ unsupported (3 of 5 juror(s) agreed)
   Details:
     ✗ unsupported  The Devil's Advocate via peaceful-receipt
         The document claims this without providing any evidence, survey or
         study to support an empirical claim about rest and error reduction.
     ✓ supported  The Evidence Skeptic via peaceful-receipt
         The document directly states it as part of its argument.
```

The claim and the jury's verdict on it are one thought, so no blank line
separates them. The votes sit under a `Details:` label, indented, with each
juror's reasoning wrapped into its own block beneath its verdict — left flush,
the reasons become a wall of prose that cannot be skimmed, and the verdict
column is the thing you actually want to read down.

