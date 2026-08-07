# `tokennet-chat` — streaming chat

A terminal conversation that prints each token the moment it arrives off the
wire. Every other app here waits for a whole reply before showing you anything;
this one exists to show what the relay's SSE channel actually buys you.

```sh
tokennet-chat                          # any model, whichever maker is free
tokennet-chat --model qwen3-coder-30b  # pin a model
tokennet-chat --system "You are terse."
tokennet-chat --history 2              # keep fewer exchanges in context
echo "explain SSE" | tokennet-chat     # one-shot from a pipe
```

Ctrl-C abandons the reply being printed and gives you the prompt back. Ctrl-D or
`/exit` leaves.

## What to watch

Two things print that you don't get from a buffered client:

**The byline lands first.** The relay names the machine serving you on its own
frame, ahead of the first token, so you see whose GPU is answering while it's
still typing.

**Both timings, at the end of each turn.** Time to first token, and time to the
complete reply:

```
you › explain SSE in one sentence
[curvy-sugar] Server-Sent Events is a one-way HTTP stream where the server
pushes newline-delimited `data:` frames to a client that just keeps reading.
  first token 0.6s · complete 3.1s
```

The gap between those two numbers is the entire argument for streaming. On a
busy maker the first token can arrive in well under a second while the full
answer takes several — a buffered client shows you nothing for the whole
duration.

## Layout

```
chat.py    the app: a Conversation, one streamed turn, and a REPL around them
tests/     unit tests driven against a scripted fake stream
```

It's deliberately small. A conversation is a list of messages, a turn is one
`stream()` call printed as it goes, and the session is a `while True` around
`input()`. There's no framework in the way.

## History

The conversation keeps the last 8 exchanges by default (`--history`). A chat
that never forgets eventually sends a context window of history with every turn
and gets slower each time, so the oldest exchanges are dropped. History is
flattened into a single prompt string, which you can print and read.
