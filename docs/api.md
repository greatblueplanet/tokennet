# The consumer API

The contract these apps — and any fork of them — depend on. The reference
implementation is [`relay.py`](../apps/lib/relay.py); this page is the
same contract written down for reading rather than running.

Everything is HTTP against the deployment's *data plane*,
`https://data.<domain>` (`data.tokennet.dev` by default), authenticated with
an `Authorization: Bearer <key>` header — an API key, minted in the web
console (see the README's "Get a credential").

## `GET /v1/models`

What is being served *right now*. One entry per (maker, model) pair — the same
model id appears once for every machine serving it — plus routing
pseudo-models. Fields the apps read:

| field | meaning |
|---|---|
| `id` | the model id |
| `maker` | the machine serving this entry (absent on pseudo-models) |
| `context_window` | that maker's context window for the model |
| `tokennet_pseudo` | `true` on routing pseudo-models: `any`, aliases |
| `available` | `false` means offering it would just fail on send — skip it |
| `location` | "City, CC" of the maker, when the relay resolved one |

Two consequences worth spelling out:

- **Real capacity is the maker count, not the model count.** A maker serves
  one request at a time, so the number of non-pseudo entries for a model *is*
  the useful parallelism of a fan-out (`Relay.fleet_width`). Counting
  pseudo-models would count routing, not machines.
- **`any` is a model id.** Send it and the relay routes the request to
  whichever maker is free.

## Picking a model — you never pick a maker

The `model` field of the chat request is the **only** routing input a client
has. A worked example: three makers online, two models, so `GET /v1/models`
returns

```json
{"object": "list", "data": [
  {"id": "qwen3-coder-30b", "object": "model", "owned_by": "tokennet",
   "context_window": 32768, "maker": "curvy-sugar", "location": "Portland, US"},
  {"id": "qwen3-coder-30b", "object": "model", "owned_by": "tokennet",
   "context_window": 16384, "maker": "mellow-brick"},
  {"id": "deepseek-v4-flash", "object": "model", "owned_by": "tokennet",
   "context_window": 65536, "maker": "sudden-lake", "location": "Berlin, DE"},
  {"id": "any", "object": "model", "owned_by": "tokennet",
   "tokennet_pseudo": true, "description": "routes to any available model",
   "available": true}
]}
```

and the client's choices for `model` are:

- `"qwen3-coder-30b"` — pin the model. The relay sends the request to
  whichever of `curvy-sugar` and `mellow-brick` is free; two entries means a
  fan-out can run two wide.
- `"deepseek-v4-flash"` — pin the model. Only one maker serves it, so every
  request lands on `sudden-lake` — but you got there by naming the model, not
  the machine.
- `"any"` — no preference. The relay routes to whichever maker is free,
  serving whatever model it serves.
- an alias id, when the deployment exposes one (`tokennet_pseudo` and
  `alias: true`, with the concrete ids in `models`) — send it like any other
  model id and the relay routes within that set.

So posting a completion to a specific model is just naming it:

```sh
curl https://data.tokennet.dev/v1/chat/completions \
  -H "Authorization: Bearer $TOKENNET_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "qwen3-coder-30b",
       "messages": [{"role": "user", "content": "Say pong."}],
       "stream": true}'
```

The model is pinned; the machine is not. The relay picks a free maker serving
that id and stamps its choice on every reply frame — this run landed on
`mellow-brick`:

```
data: {"choices":[{"delta":{"content":"pong"}}],"maker":"mellow-brick"}

data: [DONE]
```

**There is no way to address a maker.** The `maker` field in the model list
is information — who is serving, from where, with what context window — not
an address. The relay picks the machine on every request; a client that cares
who served it reads the byline off the stream after the fact.

## `POST /v1/chat/completions`

OpenAI-style. The apps always send:

```json
{"model": "...", "messages": [{"role": "user", "content": "..."}], "stream": true}
```

**Always streamed, never buffered** — the relay bounds how long it will wait
for a *whole* non-streaming answer, so a slow model on a busy maker would time
out even while making progress. The reply is SSE: `data: {chunk}` frames
ending in `data: [DONE]`. Per chunk:

- `choices[0].delta.content` — a piece of the text (some frames carry no
  choice at all, e.g. the final usage frame);
- `maker` — the machine serving the request. **Written by the relay, not the
  maker**, so a maker cannot claim to be someone else. This is the byline the
  apps print;
- `error` — an error can arrive *inside* the stream (a maker dying
  mid-generation). Whatever streamed before it is a partial answer: fail the
  call rather than hand back a truncated one.

The client exposes this two ways. `Relay.stream()` yields one `Chunk` per frame
as it arrives, which is what an interactive app wants — the `maker` frame
normally lands ahead of the first token, so a chat can print the byline while
the answer is still coming. `Relay.chat()` is that same generator accumulated
into a whole reply, which is what a batch app wants. One SSE parser, two shapes.

## The error taxonomy

Only three flavours a caller acts on differently:

- **401** — bad credential. Every later call fails the same way, so stop the
  whole run rather than rediscovering it once per request.
- **503** — every maker serving the model is momentarily busy. Since a maker
  serves one request at a time this is ordinary backpressure, not failure:
  wait and retry *without* spending an attempt. (`relay.py` waits 2 s between
  tries, gives up after 5 minutes.)
- **anything else** — a real failure: no maker serves the model (404), a
  disconnect (502), a malformed reply. Retry a bounded number of times
  (`relay.py`: two more attempts), then give up on the item.

The bearer should be an **API key**: keys don't expire mid-run, which is what
a batch client fanning out hundreds of requests overnight needs.
