"""Unit tests for the streaming chat — all local, no network.

Two things carry the app: history that stays bounded, and a turn that prints
tokens as they arrive rather than after the reply is complete.
"""

import io

from apps.chat.chat import Conversation, stream_turn
from apps.lib.relay import Chunk


class FakeRelay:
    """A relay that hands back a scripted stream and records what it was asked."""

    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self.prompts: list[str] = []

    def stream(self, model, prompt):
        self.prompts.append(prompt)
        yield from self.chunks


# --- history ---


def test_history_keeps_the_most_recent_exchanges_and_drops_the_rest():
    conversation = Conversation(system=None, keep_turns=2)
    for i in range(4):
        conversation.add("user", f"q{i}")
        conversation.add("assistant", f"a{i}")
    # Two exchanges = four messages, and they are the newest ones.
    assert [m["content"] for m in conversation.messages] == ["q2", "a2", "q3", "a3"]


def test_the_prompt_carries_the_system_line_and_the_history():
    conversation = Conversation(system="Be terse.", keep_turns=8)
    conversation.add("user", "hello")
    conversation.add("assistant", "hi")
    prompt = conversation.as_prompt("and now?")
    assert prompt.startswith("System: Be terse.")
    assert "User: hello" in prompt
    assert "Assistant: hi" in prompt
    # The live question goes last, with the model cued to continue from it.
    assert prompt.endswith("User: and now?\n\nAssistant:")


def test_a_fresh_conversation_sends_only_the_question():
    conversation = Conversation(system=None, keep_turns=8)
    assert conversation.as_prompt("just this") == "User: just this\n\nAssistant:"


# --- one streamed turn ---


def test_a_turn_prints_the_byline_then_the_tokens_and_returns_the_whole_reply():
    relay = FakeRelay(
        [
            Chunk("", "ludicrous-foot"),
            Chunk("hel", "ludicrous-foot"),
            Chunk("lo", "ludicrous-foot"),
        ]
    )
    out = io.StringIO()
    reply = stream_turn(relay, "any", "hi", out=out)

    assert reply == "hello"
    printed = out.getvalue()
    assert "ludicrous-foot" in printed
    assert "hello" in printed
    # The byline is printed before any of the answer.
    assert printed.index("ludicrous-foot") < printed.index("hel")


def test_a_turn_reports_time_to_first_token_separately_from_the_total():
    # The number that justifies streaming: a reader sees something long before
    # the reply is finished, so both timings are worth showing.
    relay = FakeRelay([Chunk("", "acme"), Chunk("word", "acme")])
    out = io.StringIO()
    stream_turn(relay, "any", "hi", out=out)
    printed = out.getvalue()
    assert "first token" in printed and "complete" in printed


def test_an_empty_reply_prints_no_timings():
    # Nothing arrived, so there is no first token to time.
    relay = FakeRelay([Chunk("", "acme")])
    out = io.StringIO()
    assert stream_turn(relay, "any", "hi", out=out) == ""
    assert "first token" not in out.getvalue()
