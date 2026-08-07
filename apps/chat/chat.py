"""Streaming chat — a terminal conversation that prints tokens as they land.

The point of this app is the SSE channel. Every other app in this repo waits
for a whole reply before showing you anything; this one writes each token the
moment it arrives off the wire, which is what the relay's streaming API is for.

It is deliberately small. A conversation is a list of messages, a turn is one
`stream()` call printed as it goes, and the whole thing is a `while True` around
`input()`. There is no framework here to get in the way of reading it.

    tokennet-chat                        # any model, whichever maker is free
    tokennet-chat --model qwen3-coder-30b
    tokennet-chat --system "You are terse."
    echo "explain SSE" | tokennet-chat   # one-shot from a pipe

Ctrl-C abandons the reply being printed and gives you the prompt back; Ctrl-D
(or /exit) leaves.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Iterator
from typing import Protocol

import requests

from apps.lib.relay import AtCapacity, CallError, Chunk, Relay, Unauthorized, describe


class Streams(Protocol):
    """All a turn needs is something that yields chunks. Stated as a protocol
    so the tests can drive a scripted stream without faking a whole Relay."""

    def stream(self, model: str, prompt: str) -> Iterator[Chunk]: ...


# The relay routes `any` to whichever maker is free, which is what you want
# for a chat: the fastest way to a first token.
DEFAULT_MODEL = "any"


class Conversation:
    """The message list, and the one rule that keeps it from growing forever.

    A chat that never forgets eventually sends a context window's worth of
    history with every turn, and the reply gets slower each time. Dropping the
    oldest exchanges keeps turns cheap; `--history` sets how many are kept.
    """

    def __init__(self, system: str | None, keep_turns: int):
        self.system = system
        self.keep_turns = keep_turns
        self.messages: list[dict[str, str]] = []

    def add(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})
        # Two messages per exchange (yours and the model's).
        excess = len(self.messages) - self.keep_turns * 2
        if excess > 0:
            del self.messages[:excess]

    def as_prompt(self, user_text: str) -> str:
        """Flatten to the single prompt string the relay client takes.

        The consumer API is OpenAI-shaped and would accept a message array, but
        the client here keeps one prompt-in/reply-out call, so history is
        rendered into it. Plain and obvious beats clever: you can print this.
        """
        parts = []
        if self.system:
            parts.append(f"System: {self.system}")
        for message in self.messages:
            speaker = "User" if message["role"] == "user" else "Assistant"
            parts.append(f"{speaker}: {message['content']}")
        parts.append(f"User: {user_text}")
        parts.append("Assistant:")
        return "\n\n".join(parts)


def stream_turn(relay: Streams, model: str, prompt: str, out=sys.stdout) -> str:
    """Print one reply as it streams. Returns the whole text for the history.

    The byline arrives on its own frame before the first token, so it is
    printed first — you know whose GPU is answering while it is still typing.
    """
    started = time.monotonic()
    first_token_at: float | None = None
    said_byline = False
    text: list[str] = []

    for chunk in relay.stream(model, prompt):
        if chunk.maker and not said_byline:
            print(f"\033[2m[{chunk.maker}]\033[0m ", end="", file=out, flush=True)
            said_byline = True
        if not chunk.text:
            continue
        if first_token_at is None:
            first_token_at = time.monotonic()
        text.append(chunk.text)
        print(chunk.text, end="", file=out, flush=True)

    print(file=out)
    if first_token_at is not None:
        # The number that justifies streaming at all: how long you stared at
        # nothing before the first token, against how long the whole reply took.
        print(
            f"\033[2m  first token {first_token_at - started:.1f}s · "
            f"complete {time.monotonic() - started:.1f}s\033[0m",
            file=out,
        )
    return "".join(text)


def converse(relay: Relay, model: str, conversation: Conversation) -> int:
    """The REPL. One turn per loop, until stdin runs out."""
    while True:
        try:
            user_text = input("\033[1myou\033[0m › ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not user_text:
            continue
        if user_text in ("/exit", "/quit"):
            return 0

        try:
            reply = stream_turn(relay, model, conversation.as_prompt(user_text))
        except KeyboardInterrupt:
            # Abandon this reply, keep the session. The partial text is not
            # added to the history — half an answer is worse context than none.
            print("\n\033[2m  (interrupted)\033[0m")
            continue
        except Unauthorized:
            print("Credential rejected. Create a key at the console.", file=sys.stderr)
            return 1
        except AtCapacity:
            print("\033[2m  every maker is busy — try again\033[0m", file=sys.stderr)
            continue
        except (CallError, requests.RequestException) as e:
            print(f"\033[2m  {describe(e)}\033[0m", file=sys.stderr)
            continue

        conversation.add("user", user_text)
        conversation.add("assistant", reply)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="tokennet-chat",
        description="Chat with the network, streamed token by token.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"model to talk to (default: {DEFAULT_MODEL}, whichever maker is free)",
    )
    parser.add_argument("--system", help="a system instruction for the whole session")
    parser.add_argument(
        "--history",
        type=int,
        default=8,
        help="exchanges of history to keep (default: 8)",
    )
    args = parser.parse_args()

    try:
        relay = Relay.from_env()
    except Unauthorized:
        print(
            "No credential found. Create an API key in the console and either\n"
            "  export TOKENNET_API_KEY=<your key>\n"
            "or store it in ~/.tokennet/<domain>/credentials.",
            file=sys.stderr,
        )
        return 1

    conversation = Conversation(args.system, max(1, args.history))

    # Piped stdin is one prompt and out — the shape a script wants.
    if not sys.stdin.isatty():
        piped = sys.stdin.read().strip()
        if not piped:
            return 0
        try:
            stream_turn(relay, args.model, conversation.as_prompt(piped))
        except Unauthorized:
            print("Credential rejected.", file=sys.stderr)
            return 1
        except (AtCapacity, CallError, requests.RequestException) as e:
            print(describe(e), file=sys.stderr)
            return 1
        return 0

    print(f"\033[2mtalking to {args.model} · /exit or Ctrl-D to leave\033[0m")
    return converse(relay, args.model, conversation)


if __name__ == "__main__":
    sys.exit(main())
