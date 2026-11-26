# Voice receptionist for appointment-based businesses

A caller opens a web page, presses **Call** and talks to a voice agent from the browser. The
agent answers questions about the business and books, moves and cancels appointments.
Everything it knows about a business comes from the database, so a new business needs only
new data.

Built for the PorsAI Forward Deployed Engineer take-home by Raj Kumar.

| | |
|---|---|
| Live call page, Sunrise Salon | https://129-225-94-107.sslip.io/call/sunrise-salon |
| Live call page, second business | https://129-225-94-107.sslip.io/call/greenline-auto-care |
| Handover note for the salon owner | [docs/HANDOVER.md](docs/HANDOVER.md) |
| Plain-English walkthrough of every part | [docs/EXPLAIN.md](docs/EXPLAIN.md) |
| Raw measurement outputs | [docs/measurements/](docs/measurements/) |
| Demo video | *(link to be added)* |

Every number below comes from a real run against the deployed agent; the raw outputs are in
`docs/measurements/` and `docs/test-results.txt`. What does not work is listed under
[Known gaps](#known-gaps-and-limits). A line-by-line check against the assignment is in
[docs/REQUIREMENTS_CHECK.md](docs/REQUIREMENTS_CHECK.md).

---

## Architecture

```
Browser call page ──WebRTC audio──► LiveKit Cloud (free Build plan, carries the audio)
      │ GET /api/token?business=sunrise-salon          ▲ outbound connection only
      ▼                                                │
┌──── one VM (4 vCPU, 12 GB), docker compose ──────────┴────────────┐
│ caddy  HTTPS certificate, forwards to web                         │
│ web    FastAPI: call page, call token, owner page, call logs      │
│ agent  LiveKit Agents worker, one process per call                │
│          Silero VAD → Whisper → LLM + tools → Piper               │
│ tts    Piper text to speech (HTTP service)                        │
│ db     Postgres 16                                                │
└───────────────────────────────────────────────────────────────────┘
```

One caller turn: the voice detector hears the caller stop → the audio goes to Whisper → the
text goes to the LLM, which may call booking tools → the reply goes to Piper one sentence at a
time → audio returns to the browser through LiveKit.

### What is used and where it runs

| Part | What | Open source? | Where it runs |
|---|---|---|---|
| Voice agent framework | LiveKit Agents 1.8 (Python) | Yes, Apache-2.0 | Our VM |
| Audio transport | LiveKit Cloud, free Build plan | The server is open source; we use the hosted free tier | LiveKit Cloud (routed via India South) |
| Voice activity detection | Silero VAD | Yes, MIT | Our VM, inside the agent |
| Speech to text | Whisper `whisper-large-v3-turbo` | Open model | Groq free tier |
| LLM | `gpt-oss-120b`, medium reasoning | Open weights | Groq free tier and Cerebras (see below) |
| LLM fallbacks | `gpt-oss-20b`, then `qwen3.8-27b` | Open weights | Groq free tier |
| Text to speech | Piper, voice `en_US-lessac-medium` | Yes (Piper is GPL-3.0; it runs as its own container and our code only calls it over HTTP) | Our VM |
| Database | Postgres 16 | Yes | Our VM |
| Web | FastAPI, plain HTML page, `livekit-client` | Yes | Our VM |
| HTTPS | Caddy with Let's Encrypt | Yes | Our VM |

No closed voice platform and no closed speech or LLM API is used.

**About Cerebras and cost, stated plainly.** Groq's free tier allows 200,000 tokens a day per
model, which is roughly 100 replies on the best model. To stop the demo degrading after a
handful of calls, the same open model on Cerebras was added as a second provider. Cerebras is
credit based: it gives 5 dollars of trial credit when a card is added, and Raj also added 10
dollars of his own. Whether the spend stayed inside the 5 dollar trial credit is *(pending:
to be confirmed from the billing page)*. The project runs without Cerebras: leave
`CEREBRAS_API_KEY` empty and it uses Groq's free tier alone. Latency is reported both ways below.

**Hosting.** An Oracle Cloud VM in Hyderabad (Intel, 4 vCPU, 12 GB), paid from Oracle's free
trial credit. It will be reclaimed when the trial ends in late December 2026.

**AI coding tools used.** Claude Code (Anthropic) wrote most of the code, tests and documents,
directed and reviewed by Raj. `docs/EXPLAIN.md` exists so that every file can be explained.

---

## Run it

Needs Docker, a Groq API key and a LiveKit Cloud project (both free, no card).

```bash
cp .env.example .env        # then fill in GROQ_API_KEY and the three LIVEKIT_ values
docker compose up --build
```

Open http://localhost:8000 and press **Call**. The database tables are created and both demo
businesses are loaded on first start.

Verified from a fresh `git clone` on the server (as a second, separate stack on other ports):
all five containers started, both businesses were seeded, a scripted voice call was answered
correctly, and the 42 non-LLM tests passed. Output: `docs/measurements/clean_clone_test.txt`.
With images already built, the stack was healthy 9 seconds after `docker compose up`; the first
build downloads about 3 GB of images and takes several minutes. Not verified on a second
physical machine or on Windows.

Useful commands (put `docker compose exec web` in front):

```bash
python -m app.manage prompt sunrise-salon     # the instructions the agent is given
python -m app.manage calls sunrise-salon      # recent calls
python -m app.manage call 42                  # everything said and done on call 42
python -m app.manage messages sunrise-salon   # questions left for staff
python -m app.manage latency sunrise-salon    # latency report over recorded calls
python -m app.manage load data/sunrise-salon.yaml   # add or update a business from a file
```

---

## How the important parts work

### No double booking
The database refuses it. `app/schema.sql` has:

```sql
CREATE UNIQUE INDEX one_booking_per_slot ON bookings (staff_id, starts_at) WHERE status = 'booked';
```

A booking is one `INSERT`. If two calls insert the same staff member and start time at the
same instant, Postgres accepts one and rejects the other; `app/booking.py` turns the rejection
into "that slot has just been taken" and the agent offers other times. Moving a booking is one
`UPDATE`, protected by the same index. There is no "check, then insert" gap to slip through,
and nothing the LLM says or does can get around it.

### Interruptions
Silero VAD keeps listening while the agent speaks. After 0.2 s of caller speech the framework
cancels the LLM and Piper, discards queued audio, and keeps only what was actually spoken in
the conversation history. If no words follow (a cough), the agent resumes. The browser's echo
cancellation keeps the agent from hearing itself.

### How business data reaches the agent
The page URL carries the business slug. The server puts it into the signed LiveKit token.
When the agent joins, it reads the slug, loads that business's rows from Postgres and builds
its instructions from them (`app/prompt.py`; the template contains no business facts). The
tools are created with that business fixed inside them. Because this happens at the start of
every call, a data change is used by the very next call with no redeploy.

### Things the code does so they do not depend on the LLM
- **Availability** always comes from a tool that reads the database.
- **The booking read-back is spoken by the code, word for word**, including the phone number
  digit by digit. A plain "yes" from the caller then completes the booking in code.
- **Move and cancel** are refused until the caller has spoken after their booking was looked up.
- **Privacy:** no tool returns another customer's name or number; availability lists free times
  only; a booking can be fetched only with the phone number it was made with, inside its business.

### Long silence
After 15 s of silence the agent asks "Are you still there?", tries once more 10 s later, then
says goodbye and ends the call.

---

## Latency

Measured in the agent for every reply, exactly as the assignment defines it: the clock starts
when the voice detector decides the caller has finished speaking and stops when the first audio
of the reply is sent. Every reply is counted, including replies that call tools.

**66 replies over 21 real voice calls** to the deployed agent (plain questions, availability
checks, bookings, cancellations; 27 replies used a tool), made by a scripted caller in one
continuous run with no rate-limit errors:

| | Median | p95 | Worst | Target |
|---|---|---|---|---|
| **All 66 replies** | **1.04 s** | **1.79 s** | 2.08 s | 1.2 s / 2.0 s |
| Replies that used a tool (27) | 1.42 s | 1.82 s | 2.08 s | |
| Replies without a tool (39) | 0.91 s | 1.28 s | 1.45 s | |

| Stage | Median | p95 |
|---|---|---|
| Speech to text (Whisper) | 0.26 s | 0.36 s |
| LLM, time to first token | 0.43 s | 0.56 s |
| Text to speech, first audio | 0.20 s | 0.52 s |

The stages do not add up to the total: a tool reply makes two LLM requests, and the first
sentence must be complete before Piper speaks it.

**The same replies measured the way the industry usually measures**, which starts the clock
earlier, at the caller's last word:

| | Median | p95 |
|---|---|---|
| From the caller's last word to first audio sent (adds the 0.45 s end-of-speech wait) | 1.52 s | 2.27 s |
| As heard at the caller's end (the scripted caller's own clock) | 1.73 s | 2.37 s |

By that measure the agent is typical of production voice pipelines and slower than the
published targets (for example 1.5 s from Daily and Pipecat, 1.1 s from Twilio). Sources and a
fuller comparison, including human conversation timing, are in [docs/RESEARCH.md](docs/RESEARCH.md).

Why 66 and not 20: a 95th percentile needs at least 59 samples to be meaningful. Earlier
22-reply runs gave a p95 of 1.49 s and 1.64 s; the larger run's 1.79 s is the one to trust.

This is with the live configuration (Cerebras first). On Groq's free tier alone a 22-reply run
gave a median of 1.43 s and a p95 of 2.57 s, which misses the targets.

Reproduce on the server: `sh scripts/measure_latency.sh` (one round, 22 replies).

**Interruption:** the agent stops 0.22 to 0.26 s after the caller starts speaking (3 runs, the
agent's clock); about 0.5 s as heard at the caller's end, including network and audio already
in flight.

**Other measurements:** connecting takes 0.3 to 1.1 s, the greeting starts 1.0 to 1.9 s after
pressing Call, and the round trip laptop → LiveKit → VM → back is 21 to 23 ms from India.

---

## Several calls at once

Each scripted caller asks five questions, one of which needs a tool.

| Calls at once | Order | All answered | Rate-limit errors | Median | p95 |
|---|---|---|---|---|---|
| 3 | Groq first | 15 of 15 | 13, absorbed by fallback | 1.07 s | 3.29 s |
| 5 | Groq first | 25 of 25 | 27, absorbed by fallback | 1.27 s | 2.93 s |
| 3 | Cerebras first | 15 of 15 | 0 | 1.07 s | 3.63 s |
| 5 | Cerebras first | 25 of 25 | 0 | 1.22 s | 2.77 s |
| 8 | Cerebras first | 40 of 40 | 79 | 3.11 s | 15.1 s |
| 3 | Cerebras first, final run | 15 of 15 | 0 | 1.09 s | 2.19 s |

- No call failed and no reply was lost at any level.
- Up to 5 calls the median holds, but **p95 goes above the 2.0 s target under load**.
- 8 at once is too many for the free tiers. The errors were most likely Groq's speech to text
  limit of 20 requests a minute (not confirmed: the logs were cleared by a restart).
- The VM was not the limit: 20 to 30% CPU, 1.5 GB of 12 GB.
- The scripted callers ran on the same VM as the agent, so these numbers are a little pessimistic.

**Two live calls racing for one slot:** both callers were read the same slot; one was booked;
the other heard "the 11 am slot just got taken" and was offered other times. The database held
exactly one booking.

Reproduce: `sh scripts/concurrent_calls.sh 3`.

---

## Rate limits hit, and what production would do

| Limit (free tier) | Hit? | What happened | In production |
|---|---|---|---|
| Groq LLM, 8,000 tokens/minute per model | Yes, by a single booking call | Automatic fallback to the next model; no failed reply | Paid tier, or self-hosted model |
| Groq LLM, 200,000 tokens/day per model | Yes, during testing | Calls ran on the weaker fallback until it refilled | Same; this is why Cerebras was added |
| Groq Whisper, 20 requests/minute | Probably, at 8 calls at once | Replies delayed by retries | Paid tier, or self-hosted Whisper on a GPU |
| LiveKit Cloud Build plan, 5,000 participant minutes/month | No | Hard cap, never bills | Paid plan or self-hosted LiveKit |

What was done about it: three-model fallback, a second provider, requests cut from about 2,350
to about 1,500 tokens, and a cap on reply length. A reply uses 1,500 to 2,700 tokens; cached
prompt tokens are not discounted on Groq's free tier (checked).

---

## Tests

```bash
docker compose --profile test run --rm tests                      # everything
docker compose --profile test run --rm tests pytest -m "not llm"  # skip the ones that call an LLM
```

Tests use a separate throwaway database, never the live one.

| File | What it proves | Tests |
|---|---|---|
| `tests/test_booking.py` | Slots, hours, days, past times, book, move, cancel, the 2-hour rule, who may touch a booking | 23 |
| `tests/test_double_booking.py` | 50 simultaneous attempts on one slot, 20 rounds: exactly one wins. Also racing reschedules, reschedule against a new booking, 30 callers for a just-cancelled slot. With the unique index removed, all four fail. | 4 |
| `tests/test_tools.py` | Confirmation rules, the code-completed booking, privacy of tool answers | 8 |
| `tests/test_isolation.py` | One business cannot see or change another's data | 7 |
| `tests/test_conversations.py` | Simulated conversations with the real instructions, tools and model: the brief's 15 test questions, a full booking with "next Monday", "tomorrow", a taken slot, cancel, attempts to cancel someone else's booking, prompt tricks, a staff message, the second business | 25 |

Last complete run, on the deployed server: **67 passed, 0 failed** (42 without an LLM, 25
simulated conversations). Full list: [docs/test-results.txt](docs/test-results.txt).

The simulated conversations call a hosted LLM, so they use tokens (about 100,000 per run) and
their wording varies between runs. They check replies by keywords.

---

## The second business

`data/greenline-auto-care.yaml` is a car service centre: 60-minute slots, mechanics, a 24-hour
cancellation rule, no cash. It was added with that file and one command:

```bash
docker compose exec -T web python -m app.manage load /dev/stdin < data/greenline-auto-care.yaml
```

Time from running the command to a working call page: **16 seconds**. No code changed and
nothing was restarted. Writing the file took the AI assistant under a minute; by hand, expect
10 to 15 minutes (estimate).

---

## Call logs

Every call records what was said, every tool call with its arguments and result, each reply's
latency by stage, interruptions and silence handling.

```
17:13:28  CALLER: I would like to book a haircut for men tomorrow at 11 a.m.
17:13:28    TOOL  check_availability({"date":"2026-11-27","service":"Haircut (men)","time":"11:00"}) -> 11 AM is FREE. ...
17:13:34  AGENT : Great, may I have your name, please?
17:13:34    (reply started 1.37s after end of speech was detected, 1.85s after the caller's last word: stt 0.30s, llm 0.28s, tts 0.24s, used a tool)
```

Read them with `python -m app.manage call <id>`, or in the browser on the owner page:
`/admin/<business>?key=<ADMIN_KEY>` → Recent calls. The owner page also edits the business's
details; saving takes effect on the next call. It is protected by one shared key, not user accounts.

---

## Scaling to 1,000 businesses

What already holds: one deployment serves any number of businesses; a business is rows, not
code; each call loads only its own business; a call is one process using about 150 to 300 MB.

What would change, in order:

1. **Models first, because they are the real ceiling today.** Free tiers serve about 3 to 5
   simultaneous callers. Move speech to text and the LLM to paid tiers or self-host them on
   GPUs (Whisper, gpt-oss or a smaller model, and a GPU text to speech). Keep the fallback chain.
2. **Run more agent workers.** LiveKit Agents workers are stateless and register with LiveKit,
   which shares calls among them. Put them in an autoscaling group and scale on the worker's
   reported load. A 4 vCPU node handled 5 calls at about 25% CPU here, so tens of calls per node
   once the model limits are gone.
3. **Managed Postgres with a connection pooler.** 1,000 businesses is tiny data. Add
   row-level security as a second line of defence for tenant isolation, backups, and a
   time-based index on bookings.
4. **Real accounts for owners.** Replace the single admin key with per-business staff logins,
   and a self-service sign-up that creates the business rows.
5. **Tenant controls.** Per-business concurrency limits and usage metering so one busy
   business cannot starve the rest.
6. **Operations.** Central logs and metrics (latency per stage is already recorded per reply),
   alerts on error rates and fallback use, and regions close to callers.
7. **Telephony.** A SIP trunk into LiveKit for real phone numbers, one per business.

---

## Known gaps and limits

- **Latency on the free tier alone misses the target** (median 1.43 s, p95 2.57 s). It meets
  it with Cerebras first (1.03 s, 1.64 s), which uses credit rather than a free tier.
- **Under several simultaneous calls p95 exceeds 2 s**, and about 3 to 5 callers is the
  practical limit on free tiers.
- **Daily token limits.** After roughly 100 replies a day on Groq's best model, calls use
  weaker fallbacks. The last fallback (Qwen) once claimed a booking it had not looked up.
- **The LLM can still misspeak.** It once said "12 PM" for a booking correctly saved at
  12:30 PM. Bookings themselves are protected by code; sentences are not.
- **Phone numbers are heard, not typed.** Speech to text sometimes drops a digit. The
  read-back is the defence. A phone number identifies a caller; it does not authenticate them.
- **Voice testing is by a scripted caller with a synthetic voice, plus a real Chrome browser
  test.** The Chrome test (`scripts/browser_call_test.mjs`) proves the page loads, connects,
  publishes the microphone and plays the agent's voice, but its fake microphone could not play
  a recording, so the caller-to-agent direction is proven only by the scripted caller.
  *(pending: human voice checks, including echo on laptop speakers.)*
- **English only.** One Piper voice, an American accent.
- **Tenant isolation is enforced in application queries**, not by database row-level security.
- **The owner page uses one shared key** for all businesses.
- **A booking is one slot for one service.** No multi-slot services, no multi-service
  bookings, no reminders or confirmations by message.
- **No test covers a business in a second timezone**, though all time handling uses the
  business's own timezone.
- **The simulated conversations check keywords**, and their results vary slightly run to run.
- **Dates more than 10 days ahead** are not in the list the agent is given, so it has to work
  the date out itself. The booking tool still checks the date against real working days.
- **The live demo depends on trial credit** (Oracle VM, Cerebras) that ends in late December 2026.
- **Extras not built:** staff login and dashboard, analytics page, uploaded documents, human
  handoff by email, embeddable widget, phone number over SIP, other languages, calendar sync,
  confirmations and reminders.

---

## Repository layout

```
app/agent.py       the call: voice pipeline, silence handling, code-completed bookings
app/tools.py       the six tools the LLM can call, and the confirmation rules
app/booking.py     slots, availability, book, move, cancel
app/prompt.py      builds the agent's instructions from database rows
app/db.py          every database query
app/schema.sql     tables and the unique index
app/call_log.py    records transcript, tool calls and latency per reply
app/tts_piper.py   adapter from LiveKit Agents to the Piper service
app/web.py         call page and call token
app/admin.py       owner page: edit details, read call logs
app/manage.py      command-line helper
data/*.yaml        one file per business
tests/             unit, double-booking, isolation and simulated-conversation tests
scripts/           latency, concurrency and spike scripts
docs/              EXPLAIN.md, HANDOVER.md, measurements
```
