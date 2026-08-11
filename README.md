# tokennet

A network of volunteer machines serving open language models.

People run a small program called a maker on hardware they already own — a spare
GPU, or an Apple Silicon Mac. It brings up an open model on their machine and
registers with a central relay, which tracks who's online and what they're
running. Machines come and go all day, so the network is whatever happens to be
connected when you ask.

To use it you talk to one endpoint, an OpenAI-style HTTP API at
`https://data.tokennet.dev`. Point any OpenAI-compatible client at it and the
relay routes your request to whichever maker is free and running the model you
asked for.

Three things make it more than a proxy:

- **It runs on spare capacity.** None of this hardware was bought to serve you.
  It's the idle time of machines people own for other reasons: a workstation
  between jobs, a gaming rig overnight, a Mac that's awake anyway. A proxy
  resells datacenter time. This uses up slack that was going to waste.
- **Every reply names the machine that served it.** The relay attaches the name,
  not the maker, so a maker can't claim to be someone else. You know whose
  machine answered you.
- **It's two-sided.** Providing capacity earns credit, consuming spends it. The
  credit is called TNT (tokennet-tokens). New accounts get a grant, so you can
  try the network without sharing anything, and you earn more by connecting a
  maker and keeping it online. TNT is a closed loop: no cash-out, nothing billed
  to a card.

The models are open-weight. The idea is for the commons to provide AI inference
free, paid for in shared capacity rather than money.

## Create an account

Go to <https://console.tokennet.dev>.

The first sign-in creates the account. There's no separate registration step, no
waitlist, and no payment method. Two ways in:

- **Email.** Enter your address and you get a 6-digit code. It's good for about
  ten minutes and works once.
- **GitHub.** Sign in with your GitHub account.

Either way you land with a starting TNT balance.

### Get an API key

The login gets you into the console. Your programs need a key.

1. Go to **Keys** in the console.
2. Create one. It looks like `sk-tnk-…` and it's shown once, since the server
   only stores a hash of it. Copy it before you leave the page.
3. Hand it to your tools. For the shell at hand:

   ```sh
   export TOKENNET_API_KEY=<your key>
   ```

   Or put it in the file every tokennet client reads:

   ```sh
   mkdir -p ~/.tokennet/tokennet.dev
   echo 'TOKENNET_API_KEY=<your key>' > ~/.tokennet/tokennet.dev/credentials
   ```

### Check that it works

See who's online:

```sh
curl https://data.tokennet.dev/v1/models \
  -H "Authorization: Bearer $TOKENNET_API_KEY"
```

Ask the network something:

```sh
curl https://data.tokennet.dev/v1/chat/completions \
  -H "Authorization: Bearer $TOKENNET_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"<a model from the list above>",
       "messages":[{"role":"user","content":"Say pong."}]}'
```

The reply carries the name of the maker that served it.

You can revoke keys from the same **Keys** page. **Usage** shows what you've
spent and earned.

## Share a machine

The other half of an account. The console's **Makers** page issues an enrollment
code. Run the maker program on your machine, give it the code, and it registers
with the relay and starts taking work. Your first maker earns a bonus, and
connected time earns credit by the hour, since availability is supply even when
nobody's asking.

Part-time machines are welcome. A laptop that joins for an evening and leaves is
worth having, and the network is built for hardware that comes and goes. Uptime
credit starts after half an hour of continuous connection, so rapid
connect/disconnect churn earns nothing.

You need less hardware than you'd think. An Apple Silicon Mac is a first-class
maker: there's a menu-bar app that runs it without a terminal window, and Metal
recipes for several of the models, so a Mac you're using for other things can
serve while it's awake. Unified memory is what makes that work at modest sizes —
a **24 GB Mac** has room for gpt-oss-20b at its full 128K context, which is a
current reasoning model with tool calling, not a toy. No discrete GPU required.

The two sides are independent. Consume without sharing, or share without
consuming.

## Apps

Two client apps live in [`apps/`](apps/), with the relay client they share.
They're reference code: a few hundred lines of plain Python each, meant to be
read and forked.

- [`tokennet-jury`](apps/jury/) puts a jury of reviewer personas on a document
  and reports where they disagree. It's what a network of many machines is good
  at: every juror is a separate request on a different maker.
- [`tokennet-chat`](apps/chat/) is a terminal conversation that prints tokens as
  they stream in, so you can watch how long the first token takes against the
  whole reply.

```sh
uv run tokennet-chat
uv run tokennet-jury apps/jury/examples/in-defense-of-doing-nothing.md
```

The apps are MIT licensed, not AGPL like the rest of the repo, because copying
them into your own project is the point. See [`apps/README.md`](apps/README.md).

## Privacy

**Use this network for public data.**

Anyone can bring a machine to it. That means the machine answering you belongs
to someone else, and your prompt reaches it in the clear so a model can run on
it. Assume whoever runs that maker can read what you send.

Validation work is ongoing. The relay probes makers, scores the replies, and
rogue makers get removed. But that scoring is about whether a maker runs the
model it advertises. It won't stop one from keeping a copy of your prompt.

So: public data only. I use it for my own open source work, where everything in
the prompt is already public somewhere. Don't send it anything you wouldn't hand
to a stranger.

## The source

The core (the relay, the maker, the console, the CLIs) isn't open yet. It's
coming soon.
