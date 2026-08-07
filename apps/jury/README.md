# `tokennet-jury` — Second Opinion

Point it at a public document. A jury of independent jurors, each a distinct
reviewer **persona** (the Evidence Skeptic, the Statistician, the Charitable
Reader, …), judges every claim it makes. You get back the claims the jury
**doubted**, and the claims it **split** on.

```sh
tokennet-jury https://example.com/we-are-the-best   # a URL
tokennet-jury paper.txt --jurors 7 --output v.md    # a file
pbpaste | tokennet-jury -                           # stdin (pbpaste is macOS's)
tokennet-jury --list                                # the persona roster
tokennet-jury paper.txt --panel 2,3,10,11           # seat the skeptics
tokennet-jury paper.txt --model qwen3-coder-30b     # pin the model (default: any)
```

No document handy? There's one here built to make a jury argue,
[a manifesto in defense of doing nothing](examples/in-defense-of-doing-nothing.md),
equal parts real philosophy and confident nonsense. The fun is watching which is
which get caught:

```sh
tokennet-jury examples/in-defense-of-doing-nothing.md
```

**Disagreement is the product.** Unanimous agreement is reassuring and dull. A
split jury is the sentence you should go read yourself. Nothing synthesizes the
jurors' answers away: the tally happens on your machine, in plain code (`tally`
in `jury.py`), and every vote is shown with the persona that judged and the
maker that served it. A verdict you can't audit is just one more opinion.

## Reading the verdict

On a terminal the report is coloured rather than marked up, one block per claim:

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

Supported is green, unsupported orange, contradicted red, abstentions dim — and
every verdict also carries its own mark (✓ ✗ ⊘ ·), so the report still reads if
you can't tell the colours apart. `--output` writes markdown instead, and so
does a redirected stdout: that's someone saving the report, not reading it.

The jury roster says which machine took which seat:

```
- #2 The Evidence Skeptic — "Where's the proof?" …
  - served by patient-anvil ×2, ludicrous-foot
```

The relay picks a maker per request, so one juror's votes can land on several
machines. That spread is the independence, and the roster shows it rather than
averaging it away.

## Why it needs a network of many machines

Each juror is a separate request, so a 7-juror panel is 7 requests that can be
in flight at once on 7 different makers. The app tells you how wide the network
actually is before it seats a panel, since a jury is only independent if the
jurors ran somewhere independent.

## Layout

```
jury.py       the app: fetch, extract claims, deliberate, tally, report
personas.py   the 13 reviewer personas and their instructions
examples/     a document written to provoke disagreement
tests/        unit tests for the tally, the CLI, and one live end-to-end run
```

The tally is the part worth reading closely. A program whose entire output is a
vote count must never invent a vote, lose a split, or break a tie toward
comfort, and `tests/test_jury.py` pins exactly that.

## Docs

[`docs/jury.md`](../../docs/jury.md) is the longer write-up: how claims are
extracted, how a persona becomes a prompt, and how the report is assembled.
