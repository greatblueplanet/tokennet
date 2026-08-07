# Client apps

Apps that talk to the network, and the client they share. They're reference
code on purpose: each one is a few hundred lines of plain Python you can read in
a sitting, fork, and turn into your own thing.

| App | What it does |
|---|---|
| [`jury/`](jury/) | A jury of reviewer personas judges a document and reports where they *disagree* |
| [`chat/`](chat/) | A terminal conversation that prints tokens as they stream off the wire |

[`lib/`](lib/) is the relay client underneath both: credential resolution, the
model list, and the SSE stream. It's the one piece worth copying into your own
project as-is.

Each app owns its folder — its code, its README, and its tests. If you only care
about one, you only have to read one directory.

## Running them

```sh
uv run tokennet-jury --help
uv run tokennet-chat
```

Or install the commands onto your PATH:

```sh
uv tool install --editable .
```

Both need an API key. Create one in the console and either export
`TOKENNET_API_KEY` or store it in `~/.tokennet/<domain>/credentials`; see the
[repo README](../README.md#get-an-api-key).

## Tests

```sh
just test          # offline, no credential needed
just test-live     # real requests to a real deployment
```

Unit tests are hermetic, driven against a fake relay served over loopback. The
live tests skip cleanly when no credential is configured.

## License

The apps are MIT (see [LICENSE](LICENSE)), not the AGPL that covers the rest of
the repo. They exist to be copied into your own projects, and MIT is what makes
that painless.
