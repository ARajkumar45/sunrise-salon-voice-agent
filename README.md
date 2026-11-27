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

One caller turn: the voice detector hears the caller stop (Whisper has already been sent the
recording a moment earlier, see Latency) → the text goes to the LLM, which may call booking
tools → the reply goes to Piper one sentence at a time → audio returns to the browser through
LiveKit.

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

The index works per staff member and start time, so it only holds while the slot grid stays
put. An owner edit that would leave an upcoming booking without a slot (renaming or removing
its staff member, moving its service to someone else, changing the hours, the working days or
the slot length around it) is therefore refused as a whole, with a message naming the
bookings (`db.bookings_that_no_longer_fit`). Before this check, renaming a staff member made
their booked slots look free.

### Interruptions
Silero VAD keeps listening while the agent speaks. After 0.2 s of caller speech the framework
cancels the LLM and Piper, discards queued audio, and keeps only what was actually spoken in
the conversation history. If no words follow (a cough), the agent resumes. The browser's echo
cancellation keeps the agent from hearing itself.

One exception, a framework default we kept: during the first 3 seconds of the greeting the
agent cannot be interrupted and does not take in what the caller says. LiveKit does this so
that the agent's own voice, coming back through the caller's loudspeaker before echo
cancellation has settled, cannot cut the greeting off. See Known gaps.

### How business data reaches the agent
The page URL carries the business slug. The server puts it into the signed LiveKit token.
When the agent joins, it reads the slug, loads that business's rows from Postgres and builds
its instructions from them (`app/prompt.py`; the template contains no business facts). The
tools are created with that business fixed inside them. Because this happens at the start of
every call, a data change is used by the very next call with no redeploy.

### Things the code does so they do not depend on the LLM
- **Availability** always comes from a tool that reads the database.
- **The booking read-back is spoken by the code, word for word**, including the phone number
  digit by digit. A plain "yes" from the caller then completes the booking in code. The
  read-back does not stay open: "no", "wait" or "let me think" drops it at once, and so does a
  second answer that is not a yes, so an "okay, thanks" later in the call books nothing.
  (One exception: if the agent itself has just offered to book that exact time and the caller
  answers with a plain yes that contains no digits, the booking is made without a second
  read-back.)
- **Owner edits are checked before they are saved** (`db.check_business_data`): a slot length
  of 0, a misspelt timezone, hours that end before they start, a service naming nobody, and
  similar mistakes are refused with a plain message, because each of them would break calls.
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
| **All 66 replies** | **0.81 s** | **1.74 s** | 1.90 s | 1.2 s / 2.0 s |
| Replies that used a tool (27) | 1.17 s | 1.79 s | 1.90 s | |
| Replies without a tool (39) | 0.71 s | 0.89 s | 1.33 s | |

| Stage | Median | p95 |
|---|---|---|
| Speech to text (Whisper) | 0.26 s | 0.36 s |
| ...of which after end of speech was detected | 0.01 s | 0.36 s |
| LLM, time to first token | 0.43 s | 0.56 s |
| Text to speech, first audio | 0.20 s | 0.37 s |

The stages do not add up to the total: a tool reply makes two LLM requests, and speech to
text mostly runs before the clock starts (see below).

**The same replies measured the way the industry usually measures**, which starts the clock
earlier, at the caller's last word:

| | Median | p95 |
|---|---|---|
| From the caller's last word to first audio sent (adds the 0.45 s end-of-speech wait) | 1.29 s | 2.22 s |
| As heard at the caller's end (the scripted caller's own clock) | 1.50 s | 2.35 s |

**Repeat run on the submitted code** (after the edge-case fixes of 27 Nov, same script, 66 replies, no rate-limit errors): median 0.76 s, p95 1.71 s, worst 2.02 s by the assignment's definition (one reply of the 66 was over 2.0 s); 1.24 s / 2.19 s from the caller's last word; 1.48 s / 2.40 s as heard. Three calls at once: 15 of 15 answered, median 0.75 s, p95 1.43 s. `docs/measurements/latency_final_66_replies.txt`, `docs/measurements/edge_cases_and_final_checks.txt`.

By that measure the agent is typical of production voice pipelines. It is at the 1.5 s target
published by Daily and Pipecat and slower than Twilio's (1.1 s target, 1.4 s upper limit).
Sources and a fuller comparison, including human conversation timing, are in
[docs/RESEARCH.md](docs/RESEARCH.md).

### Two fixes made after the first 66-reply measurement

The first 66-reply run gave a median of 1.04 s and a p95 of 1.79 s (1.73 s median as heard).
The call logs showed every stage running strictly one after another, so two things were changed:

1. **Speech to text now starts during the end-of-speech wait** (`app/stt_early.py`). Before,
   the agent waited 0.45 s of quiet and only then sent the recording to Whisper (another
   0.26 s). Now a second, quicker voice detector sends the recording after 0.2 s of quiet, as
   a guess that the caller has finished. If the caller carries on, that attempt is thrown away.
   The decision that the caller has finished still takes the full 0.45 s.
2. **A long sentence is spoken first clause first** (`app/tts_piper.py`). Piper returns no
   audio until a whole piece of text is done, so a 9-second booking read-back started 0.49 s
   late. Cut after its first clause, it starts in 0.12 s.

| Same script, 66 replies each | Before | After |
|---|---|---|
| Median, assignment's definition | 1.04 s | 0.81 s |
| p95, assignment's definition | 1.79 s | 1.74 s |
| Median as heard by the caller | 1.73 s | 1.50 s |
| p95 as heard by the caller | 2.37 s | 2.35 s |

**The median improved by about 0.23 s; the slowest replies did not.** They are replies that
call a tool (two LLM requests) after the caller dictated a phone number. Digit-by-digit speech
is full of short pauses, each of which wastes an early attempt, so after two wasted attempts
in one turn the agent stops guessing (to protect the 20 requests a minute of the free speech
to text tier) and that turn gets no head start.

What is left is not ours to shorten on this setup: the LLM's 0.43 s is the provider's time to
start answering (the network to it is 0.02 s), and Piper needs about 0.045 s per second of
speech. The next lever would be a turn-detection model, so the 0.45 s wait itself can shrink
without cutting callers off.

Why 66 and not 20: a 95th percentile needs at least 59 samples to be meaningful.

This is with the live configuration (Cerebras first). On Groq's free tier alone a 22-reply run
(before the two fixes) gave a median of 1.43 s and a p95 of 2.57 s, which misses the targets.

Raw output: `docs/measurements/latency_after_fixes_66_replies.txt` (after) and
`docs/measurements/final_latency_66_replies.txt` (before).

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
| 3 | Cerebras first, 26 Nov | 15 of 15 | 0 | 1.09 s | 2.19 s |
| 3 | Cerebras first, after the two latency fixes (27 Nov) | 15 of 15 | 0 | 0.81 s | 1.38 s |

- No call failed and no reply was lost at any level.
- After the two latency fixes, 3 calls at once stay inside both targets (15 replies, so the
  p95 is only indicative). 5 and 8 at once were measured before the fixes and not repeated:
  there the median held up to 5 calls, but **p95 went above the 2.0 s target**.
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
| Groq Whisper, 20 requests/minute | Probably, at 8 calls at once | Replies delayed by retries. Starting speech to text early adds up to 2 requests to a turn in which the caller pauses mid-sentence | Paid tier, or self-hosted Whisper on a GPU |
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
| `tests/test_booking.py` | Slots, hours, days, past times, the last slot of the day, a date in the wrong year, book, move, cancel, cancel twice, a passed booking, phone numbers written differently, the 2-hour rule, who may touch a booking | 28 |
| `tests/test_double_booking.py` | 50 simultaneous attempts on one slot, 20 rounds: exactly one wins. Also racing reschedules, reschedule against a new booking, 30 callers for a just-cancelled slot. With the unique index removed, all four fail. | 4 |
| `tests/test_tools.py` | Confirmation rules, the code-completed booking, a read-back the caller put off is never booked by a later "okay", privacy of tool answers | 12 |
| `tests/test_owner_edits.py` | Owner edits: an edit that would leave an upcoming booking without a slot is refused and changes nothing (rename, slot length, hours, days, service moved); values that would break calls are refused; the owner key check | 8 |
| `tests/test_isolation.py` | One business cannot see or change another's data | 7 |
| `tests/test_stt_early.py` | Early speech to text, with the real voice detector and real recordings: one transcript per caller turn, the whole turn in it, no audio sent twice, at most 3 requests for a turn full of pauses, a failed transcription loses one turn but not the call | 5 |
| `tests/test_tts_piper.py` | Where a long sentence is cut for Piper, and where it must not be (short sentences, "12,500", stray words); text with nothing to say ("...") is not sent to Piper | 6 |
| `tests/test_conversations.py` | Simulated conversations with the real instructions, tools and model: the brief's 15 test questions, a full booking with "next Monday", "tomorrow", a taken slot, cancel, attempts to cancel someone else's booking, prompt tricks, a staff message, the second business | 25 |

Last complete run, on the deployed server: **95 passed, 0 failed** (70 without an LLM, 25
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
- **The owner page uses one shared key** for all businesses, so whoever holds it can read and
  edit every business, including call logs. The key travels in the address, so it appears in
  the web server's log and the browser's history. Per-business logins are the fix.
- **The greeting cannot be interrupted in its first 3 seconds**, and words spoken over it in
  that time are not heard (the framework's echo guard, see Interruptions). A caller who starts
  talking at once has to repeat themselves. It can be shortened with one setting
  (`aec_warmup_duration`), but only after checking by ear that a laptop loudspeaker does not
  then cut the greeting off. *(pending: Raj's decision after the human voice check.)*
- **No limit on how often the call page can ask for a call.** Anyone could start many calls
  and use up the free quotas. Production needs a rate limit per address in front of `/api/token`.
- **Changing a booking needs only the phone number it was made with.** A caller who knows
  someone's number can hear that person's appointment time and service (never their name) and
  cancel or move it.
- **Move and cancel are not read back by code.** They are refused until the caller has spoken
  after the lookup, but the confirmation sentence is the LLM's.
- **If speech to text fails for a caller turn** (after its own retries) the agent says "Sorry,
  I didn't catch that" and the call goes on. If the LLM or Piper fails three times in a row
  the framework ends the call without a spoken apology.
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
app/stt_early.py   starts speech to text during the end-of-speech wait
app/web.py         call page and call token
app/admin.py       owner page: edit details, read call logs
app/manage.py      command-line helper
data/*.yaml        one file per business
tests/             unit, double-booking, isolation and simulated-conversation tests
scripts/           latency, concurrency, awkward-caller (edge_calls.py) and spike scripts
docs/              EXPLAIN.md, HANDOVER.md, measurements
```
