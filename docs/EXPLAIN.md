# EXPLAIN: how this project works, in plain English

Read this the night before the review call. One section per milestone. Each section says
what was built, how it works, why it was done that way, and how to explain it out loud.

---

## Milestone 0: prove the risky parts first (Wed 25 Nov)

### What was built
Nothing a customer would use yet. M0 answers one question: do all the risky pieces work on
the real server, with real numbers, before we build features on top of them?

At the end of M0 there is a live page at https://129-225-94-107.sslip.io/call/sunrise-salon
where you press Call, a test agent says hello, and it answers one sentence back.

### The moving parts (five containers, one `docker compose up`)
| Container | What it does | File |
|---|---|---|
| `caddy` | Gets a free HTTPS certificate and forwards web traffic. Browsers refuse the microphone without HTTPS. | `Caddyfile` |
| `web` | Serves the call page and hands out call tokens. | `app/web.py`, `app/static/call.html` |
| `agent` | The voice agent. LiveKit starts one copy of `handle_call` per call. | `app/agent.py` |
| `tts` | Piper, turns text into speech. | `docker/piper.Dockerfile`, `app/tts_piper.py` |
| `db` | Postgres. Empty until Milestone 2. | `docker-compose.yml` |

### What happens when someone presses Call
1. The page asks our web server for a token (`/api/token?business=sunrise-salon`).
2. The server makes a new room name, and signs a token that says three things: this caller may
   join this room, send the agent named `receptionist` into it, and the business is
   `sunrise-salon`. The token is signed with our LiveKit secret, so the caller cannot change it.
3. The browser connects to LiveKit Cloud with the token and turns on the microphone.
4. LiveKit Cloud tells our agent (which keeps an outbound connection open to LiveKit) to join.
5. In the agent, each turn is: Silero VAD hears the caller stop → the audio goes to Whisper on
   Groq → the text goes to the LLM on Groq → the reply goes sentence by sentence to Piper →
   the audio goes back through LiveKit to the browser.

The audio never touches our web server. Our server needs no open ports except 80 and 443.

### Every file so far
- `app/agent.py`: the call. Sets up VAD, speech to text, LLM and text to speech, and logs each turn with latency numbers.
- `app/tts_piper.py`: a small adapter. LiveKit has no Piper plugin, so this sends one sentence to the Piper container over HTTP and passes the audio back.
- `app/web.py`: three routes: the call page, the token, a health check.
- `app/static/call.html`: one page, one button, about 60 lines of JavaScript using LiveKit's browser library.
- `Dockerfile`: one image used by both `web` and `agent`.
- `docker/piper.Dockerfile`: Piper with the voice file baked in.
- `docker-compose.yml`, `Caddyfile`: how the five containers are wired.
- `scripts/tts_bakeoff.py`: measures time to first audio for Kokoro and Piper.
- `scripts/groq_limits.py`: prints Groq's real rate limits and response times.
- `scripts/livekit_ping.py`: measures the round trip laptop → LiveKit → VM → back.
- `scripts/fake_caller.py`: a robot caller that joins a real call and plays a recorded question.
- `.env.example`: the names of the settings. The real `.env` is never committed.

### What we measured (all real runs)

**Text to speech, time to first audio on the VM (4 vCPU):**

| Callers at once | Kokoro, short sentence | Piper, short sentence |
|---|---|---|
| 1 | 0.92 s | 0.07 s |
| 3 | 1.89 s | 0.17 s |
| 5 | 2.81 s | 0.28 s |
| 8 | 4.12 s | 0.45 s |

Kokoro sounds better but is too slow on a CPU and makes callers queue. Piper is used.
Reproduce: `python scripts/tts_bakeoff.py piper http://127.0.0.1:5000 short` on the VM.

**Groq free tier, read from the response headers:** 8,000 tokens per minute and 1,000 requests
per day for each chat model, counted separately per model. Whisper: 2,000 requests per day.
Reproduce: `uv run python scripts/groq_limits.py some.wav`.

**LiveKit Cloud from India:** the project page says "United States", but the agent registered
with region "India South". Connecting takes 0.3 to 1.1 s. The round trip laptop → LiveKit → VM
→ LiveKit → laptop is 21 to 23 ms (median over 30 pings, three runs). The US label is not a
latency problem. Reproduce: `scripts/livekit_ping.py echo room` on the VM, `ping room` on the laptop.

**Full loop on the deployed agent (7 scripted calls):** greeting audio starts 1.4 to 1.9 s
after pressing Call. Per turn, from the agent's own metrics: LLM first token 0.29 to 0.52 s,
Piper first audio 0.18 to 0.30 s, and 1.53 to 1.68 s from the caller's last word to reply
audio. Two calls at once: no rate-limit errors, agent CPU about 10%.

### What is not good enough yet (honest list)
- 1.53 to 1.68 s is measured from the caller's actual last word. It includes 0.55 s that the
  voice detector waits to be sure the caller stopped, plus a default 0.5 s extra wait in the
  framework. Counted the assignment's way (from "system detects the caller stopped"), today's
  number is about 1.0 to 1.1 s. Removing the extra 0.5 s wait is the first job in Milestone 1.
- The test agent has a tiny prompt. Real prompts are bigger, so the Groq token limit has not
  been stressed yet. That is tested properly in Milestone 5 with 3 calls at once.
- `scripts/fake_caller.py` reports about 2.8 s, which is too high: it buffers up to a second of
  audio before sending, so its clock starts early. The agent's own metrics are the trusted
  numbers. The script gets fixed before it is used for the latency report.
- No human has made a voice call on the live page yet.

### How to explain this on the review call
> "Before building features I proved the four risky things on the real server: HTTPS and the
> microphone, text to speech speed, the free tier limits, and network distance to LiveKit. I
> measured Kokoro against Piper on the actual 4 vCPU machine. Kokoro needed 0.9 seconds for
> the first audio and Piper 0.07, so I chose Piper and kept the script and table in the repo.
> The agent runs on my VM and only makes outbound connections to LiveKit Cloud, which carries
> the audio. The business slug travels inside the signed call token, so the agent knows which
> business was called and the caller cannot fake it."

If asked "why not Kokoro?": the table above. If asked "why LiveKit Cloud and not self-hosted
LiveKit?": no UDP ports to open and manage on the VM, a free tier with a hard cap that cannot
bill, and the brief lists it as allowed.

---

## Milestone 1: the real call (Wed 25 Nov)

### What was built
The live page now answers as Sunrise Salon. Everything it knows comes from the database. The
agent stops when you talk over it, checks in when you go quiet, and writes a log of every call
with the latency of every reply.

### How business data reaches the agent (the question they will ask)
1. `data/sunrise-salon.yaml` holds everything about the salon in plain text.
2. When the `web` container starts, it creates the tables (`app/schema.sql`) and loads any
   data file whose business is not in the database yet (`db.seed_missing_businesses`).
3. When a call starts, `handle_call` in `app/agent.py` reads the business slug from the call
   token, then calls `db.load_business(slug)`: one business row, its staff with working hours,
   its services, its FAQs.
4. `app/prompt.py` turns those rows into the agent's instructions. The template has no business
   facts in it. See the result with `python -m app.manage prompt sunrise-salon`.
5. The greeting is also a database column, spoken directly (no LLM call, so it is instant).

Because step 3 happens at the start of every call, changing the data and running
`python -m app.manage load data/sunrise-salon.yaml` takes effect on the very next call.

### How interruptions work (the other question they will ask)
The voice detector (Silero VAD) listens to the caller all the time, even while the agent talks.
When it has heard the caller speak for 0.2 seconds (`INTERRUPT_AFTER` in `app/agent.py`), the
framework cancels the reply: it stops the LLM and Piper, and throws away audio that was queued
but not yet played. The conversation history keeps only the words the agent actually got out,
marked as cut off. If the "speech" was only a noise and no words follow, the agent resumes.
The browser's echo cancellation (switched on in `call.html`) stops the agent hearing itself.

Why 0.2 s and not lower: shorter makes coughs and background noise cut the agent off.

### How silence is handled
If nobody speaks for 15 seconds the framework marks the caller "away". `handle_silence` in
`app/agent.py` then says "Are you still there?", waits 10 s, tries once more, waits 10 s, says
goodbye and ends the call. If the caller speaks at any point, the task is cancelled.

### How latency is measured
`app/call_log.py` keeps a stopwatch per reply:
- **Start:** the moment the voice detector decides the caller has finished.
- **Stop:** the moment the first audio of the reply is sent.

That is the assignment's definition. One trap worth knowing: the framework's own event
timestamp for "caller stopped" is back-dated to the caller's last word, which is earlier than
the moment of detection by the 0.45 s the detector waits. So the code reads the clock itself
for the start, and stores the back-dated one separately as "since last word", which is what
the caller actually feels. Both are in the call log.

Stages logged for every reply: `stt_s` (Whisper request), `llm_first_token_s`, `tts_first_audio_s`.

### New and changed files
- `app/schema.sql`: all tables. Every business table has a `business_id`.
- `app/db.py`: every database query lives here.
- `app/prompt.py`: builds the instructions from database rows.
- `app/call_log.py`: `CallRecorder` writes the transcript, timings and interruptions.
- `app/agent.py`: now loads the business, starts the recorder, handles silence.
- `app/manage.py`: `load` a business file, show the `prompt`, list `calls`, show one `call`.
- `app/web.py`: creates tables and seeds data on startup; unknown businesses get a 404.
- `data/sunrise-salon.yaml`: the salon's data.
- `scripts/fake_caller.py`: robot caller with three modes: `ask`, `interrupt`, `silence`.
- `tests/audio/*.wav`: recorded questions (made with Piper) for the robot caller.

### What we measured on the deployed agent (scripted calls, Wed evening)
| Check | Result |
|---|---|
| Reply latency, assignment's definition, 5 questions | 0.72, 0.85, 0.86, 0.95 s and one 1.80 s |
| Same replies, from the caller's last word | 1.20 to 1.43 s, and 2.28 s for the slow one |
| Stages for a typical reply | Whisper 0.23 s, LLM first token 0.29 to 0.44 s, Piper 0.11 to 0.26 s |
| Interruption, agent's own clock (3 runs) | stopped 0.22, 0.22, 0.26 s after the caller began speaking |
| Interruption, heard at the caller's end (3 runs) | 0.48, 0.53, 0.54 s |
| Silence | check-in at 14 s and 26 s, goodbye at 39 s, call ended at 44 s |
| Answers | men's haircut, Sunday, address, hair colour days, UPI all correct from data |

Reproduce: `uv run python scripts/fake_caller.py ask tests/audio/sunday.wav`, then on the VM
`docker compose exec web python -m app.manage calls sunrise-salon` and `... call <id>`.

### Honest notes
- Five turns is not the 20+ the assignment asks for. The proper latency run is Milestone 5.
- One reply in five took 1.8 s because Groq's LLM took 1.4 s for its first token. If that
  happens more than 1 turn in 20, the 2.0 s p95 target is at risk. Watched in M5.
- The interruption figure heard from outside (about 0.5 s) is right at the limit. It includes
  network travel and audio already on its way. The agent itself stops in about 0.22 s.
- The prompt is about 1,050 tokens. Groq allows 8,000 tokens a minute per model, so one model
  serves about 7 replies a minute. Several calls at once will need the fallback models (M5).
- No booking yet (M2). Asked to book, the agent can only talk about it.

### How to explain this on the review call
> "Nothing about the salon is in the code or the prompt template. At the start of each call
> the agent reads that business's rows from Postgres and builds its instructions from them,
> so a data change shows up on the next call with no redeploy."

> "Interruptions: the voice detector keeps listening while the agent speaks. After 0.2 seconds
> of caller speech the framework cancels the LLM and text to speech and drops the queued audio.
> I measured it: the agent stops about 0.22 seconds after the caller starts."

> "Latency is measured in the agent, per reply, from the moment the detector decides the caller
> has finished to the first audio sent. I found the framework back-dates its own timestamp, so
> I read the clock myself to match the assignment's definition, and I log both."

---

## Milestone 2: bookings (Wed 25 Nov, night)

### What was built
The agent can now book, move and cancel appointments by voice. It checks real availability in
the database first, understands "tomorrow" in the salon's timezone, respects each stylist's
days and hours, and cannot double book.

### How double booking is prevented (the most important answer on the review call)
One line in `app/schema.sql`:

```sql
CREATE UNIQUE INDEX one_booking_per_slot ON bookings (staff_id, starts_at) WHERE status = 'booked';
```

It tells Postgres: a staff member can have only one live booking per start time. Booking is a
single `INSERT`. If two calls insert the same slot at the same instant, Postgres itself accepts
one and rejects the other with a "unique violation". `booking.book` catches that and tells the
agent "that slot has just been taken, offer another time".

Why this and not a check in code: "look if it is free, then insert" has a gap between the look
and the insert, and two calls can both slip through it. The database closing the gap means no
amount of timing luck, bugs in my code, or mistakes by the LLM can create a double booking.

- Moving a booking is one `UPDATE` of the start time, so the same index protects it, and if the
  new slot is taken nothing changes: the caller keeps the original booking.
- Cancelled rows are excluded (`WHERE status = 'booked'`), so a cancelled slot can be rebooked.
- The index is on the staff member, not the service. Anita's 10:00 is one slot whether it is a
  men's haircut or a blow dry.

**Proof:** `tests/test_double_booking.py` fires 50 booking attempts at one slot at the same
moment over 20 real database connections, 20 rounds in a row. Exactly one wins each time. It
also races two reschedules, a reschedule against a new booking, and 30 callers for a slot that
was just cancelled. I also ran the same tests with the index removed: all four fail. So the
tests really detect double booking; they do not pass by accident.

### How a booking call flows
The LLM has five tools (`app/tools.py`). Each is a small function that calls `app/booking.py`.

| Tool | What it does |
|---|---|
| `check_availability(service, date)` | Free times that day. If the stylist is off or full, the next two days with free times. |
| `book_appointment(service, date, time, name, phone)` | Books. Needs two calls, see below. |
| `find_my_bookings(phone)` | The caller's own upcoming bookings. |
| `reschedule_booking(booking_id, phone, new_date, new_time)` | Moves a booking. |
| `cancel_booking(booking_id, phone)` | Cancels, and says whether it was free. |

The tools are created per call by `build_tools(business, call_id, ...)`. The business is baked
in. The LLM chooses a service and a date, but there is no parameter for "which business", so it
cannot reach another business's data even if a caller talks it into trying.

### Safety rules written in code, not left to the prompt
LLMs sometimes act before asking. Two rules in `build_tools` make that harmless:
- **New booking takes two calls.** The first call to `book_appointment` books nothing and
  returns "ask the caller to confirm" with the details and the phone number digit by digit.
  Only a second call with the same details, after the caller has spoken again, books it.
- **Move and cancel need the caller to have spoken since `find_my_bookings`.** So the caller
  has heard which booking was found and answered before anything changes.

The counter of "how many times has the caller spoken" comes from `CallRecorder.caller_lines`.

### Dates and times
- `app/prompt.py` gives the LLM the current date and time in the business's timezone and a list
  of the next 10 days as `Thu 26 Nov=2026-11-26`. The LLM picks the date from that list.
- The tools accept only `YYYY-MM-DD` and 24-hour `HH:MM`, and check them against the stylist's
  real working hours (`booking.check_slot`). A wrong day, a time outside hours, a time not on a
  30-minute boundary, or a time in the past is refused with a reason the agent can say.
- All times are stored as `TIMESTAMPTZ` and built with the business's timezone.

### Privacy
- `check_availability` returns free times only. Taken slots are simply missing. There is no
  tool that can return a customer's name or number.
- A booking can only be seen, moved or cancelled with the phone number it was made with, inside
  the same business (`booking.get_own_booking`).

### Rate limits: what happened and what changed
During testing one booking call alone hit Groq's limit of 8,000 tokens a minute on the main
model, because each request was about 2,350 tokens (instructions, tool descriptions, history).
Two changes:
- **Fallback.** `llm.FallbackAdapter` in `app/agent.py` tries `openai/gpt-oss-120b`, then
  `qwen/qwen3.8-27b`, then `openai/gpt-oss-20b`. Each has its own 8,000 tokens a minute. The
  call log showed the fallback take over mid-call with no failure heard by the caller.
- **Smaller requests.** Shorter instructions and tool descriptions brought a request down to
  about 1,470 to 1,700 tokens.

### New and changed files
- `app/booking.py`: slots, availability, book, move, cancel. All rules are here.
- `app/tools.py`: the five tools and the two safety rules.
- `app/schema.sql`: `bookings` table and the unique index.
- `app/prompt.py`: appointment rules and a compact date list.
- `app/agent.py`: three-model fallback, tools attached to the agent.
- `tests/test_booking.py` (23 checks), `tests/test_double_booking.py` (4), `tests/test_tools.py` (5).
- `Dockerfile`, `docker-compose.yml`: a `tests` service.

### How to run the tests
```bash
docker compose --profile test run --rm tests
```
They use a separate throwaway database (`receptionist_test`), never the live one.
Result on the VM: **32 passed**.

### What was checked by scripted voice calls on the deployed agent
- "Book a haircut for men tomorrow at 11 AM" on Wednesday night became Thursday 26 November,
  availability was checked, details were read back, and after "yes" the row was in the database.
- "Move my booking to tomorrow at 12:30": found the booking, checked the slot, asked, moved it.
- "Cancel my booking": found it, said cancelling was free, asked, cancelled it.
- "Book me a facial on Tuesday": "Kavya isn't working on Tuesdays", offered Wednesday and Friday.

### Honest notes
- **Replies that use a tool are slower:** 1.2 to 2.6 s in these runs, against 0.9 to 1.6 s
  without. They count in the headline numbers. This puts the 2.0 s p95 target at risk and is
  the first thing to work on in Milestone 5.
- **The LLM once said the wrong time aloud.** After a move to 12:30 PM (correct in the database
  and in the tool result) it said "12 PM". The booking was right, the sentence was wrong.
- **Phone numbers by voice are fragile.** Speech to text sometimes drops a digit. The read-back
  before booking is the defence. A phone number is also identification, not authentication:
  anyone who knows your number could move your booking.
- **The agent sometimes asks for confirmation one more time than needed.**
- No human has made a booking by voice yet. Scripted calls use a synthetic voice.

### How to explain this on the review call
> "Double booking is impossible because the database refuses it. There is a unique index on
> staff member and start time for live bookings, and booking is a single insert. If two calls
> hit the same slot at once, Postgres lets one in and rejects the other, and my code turns that
> rejection into 'that slot was just taken'. I did not rely on checking first, because check
> then insert has a gap. The test fires 50 attempts at one slot at once, 20 times, and exactly
> one wins each time. With the index removed the same test fails."

> "The LLM never decides whether a slot is free. It asks a tool, the tool asks the database.
> And it cannot change a booking before the caller has heard the details and answered: that
> rule is in code, in build_tools, not just in the prompt."

---

## Milestone 3: answers and safety (Thu 26 Nov)

### What was built
- `tests/test_conversations.py`: 24 simulated conversations. Each one types what a caller would
  say into the real agent brain (same instructions, same tools, same Groq models as a live
  call; only the audio is missing) and checks the reply and the database.
  - 15 are the assignment's own test questions, named `test_q01` to `test_q15`.
  - 9 more cover a full booking with "next Monday", "tomorrow", a taken slot, cancelling,
    trying to cancel someone else's booking, two more prompt tricks, and passing a question
    to staff.
- `leave_message_for_staff` tool and `staff_messages` table: when the agent does not know
  (for example, membership plans), it offers to pass the question on, and saves it.
  Read them with `python -m app.manage messages sunrise-salon`.
- `check_availability` takes an optional time and answers "11 AM is NOT available" in so
  many words, after the LLM once described a taken slot as available.
- `find_my_bookings` now says whether cancelling each booking would be free.
- `app/agent.py`: `build_agent` and `build_llm` are shared by live calls and tests, so the
  tests exercise exactly what callers get.

### Why the agent answers only from the business's data
Three layers, strongest first:
1. **It cannot see what it must not say.** No tool returns another customer's name or number.
   Availability lists free times only. Staff phone numbers are not in the database at all.
   A trick prompt cannot extract data the model never receives.
2. **Tools are tied to one business and one phone number.** See Milestone 2.
3. **Instructions** (`RULES` in `app/prompt.py`): answer only from the business information,
   say so when it is not there and offer to pass it to staff, never give an exact price for
   a "from" price, refuse customer details whoever the caller claims to be, decline anything
   that is not reception work.

Layer 3 is the weak one: it depends on the LLM obeying. Layers 1 and 2 hold even if it does not.

### Model setting changed (approved by Raj)
The plan had gpt-oss-120b at its fastest reasoning setting, then Qwen, then gpt-oss-20b.
Testing showed:
- At the fastest setting, gpt-oss-120b skipped rules: it asked "which time?" for a Tuesday
  facial without checking, left out cash and cards for the UPI question, and once called a
  taken slot available.
- Qwen claimed "I found your appointment" without calling any tool.

Now: `openai/gpt-oss-120b` with `medium` reasoning, then `openai/gpt-oss-20b`, then Qwen last.
Cost: about 0.3 s more per reply. Both are settings (`LLM_MODELS`, `LLM_REASONING`).

### Second provider for the same model: Cerebras (approved by Raj)
Groq's free tier gives each model 200,000 tokens per day. One reply costs about 1,500 to
2,700 tokens, so the best model serves roughly 100 replies a day. Wednesday night's testing
used all of it. Cached prompt tokens are not discounted (checked).

Cerebras serves the same open model, `gpt-oss-120b`. `build_llm` in `app/agent.py` now reads a
list of `provider:model` entries and tries them in order:
`groq:openai/gpt-oss-120b`, `cerebras:gpt-oss-120b`, `groq:openai/gpt-oss-20b`, `groq:qwen/qwen3.8-27b`.
Without a `CEREBRAS_API_KEY` the Cerebras entry is skipped, so the project still runs on Groq alone.

Measured from the VM with the real prompt, medium reasoning, time to first spoken token:
Cerebras 0.39 to 0.61 s; Groq 0.56 to 0.97 s.

Be clear about what Cerebras is: a trial with 5 dollars of credit that lasts 30 days, not a
permanent free tier. Usage is deducted from that credit. When it runs out or expires, the
agent falls through to the Groq models.

### Bookings no longer depend on the LLM remembering a step
Testing showed two LLM habits that could mislead a caller:
- it asked "shall I confirm that booking?" without reading the details back;
- once it said "your appointment is all set" without calling the booking tool, so nothing was saved.

Both are now handled by code:
- **The read-back is spoken by the code, word for word.** The first `book_appointment` call
  says "Let me read that back. Haircut (men) with Anita Rao on Monday 30 November at 10:30 AM,
  for Asha Verma, phone number 9 8 7 6 ... Shall I book it?" and ends the turn (`StopResponse`).
- **A plain yes books it, in code.** `Receptionist.llm_node` in `app/agent.py` runs just before
  every LLM reply. If a read-back is waiting and the caller's line is a short, unqualified yes
  (`is_plain_yes` in `app/tools.py`), the code inserts the booking itself and tells the LLM the
  result, so the LLM only has to say it. "Yes but make it 11" is not a plain yes and goes to
  the LLM as normal.
- Calling `book_appointment` again for a booking the caller already has answers "Already booked".

### What has been proven
- The last full run (conversations on Cerebras `gpt-oss-120b`, medium) was 58 passed, 1 failed.
  The failure was the booking conversation; it was fixed by the change above and then passed
  3 times out of 3. The README's test section carries the final full-run result.
- No run, on any model or setting, revealed another customer's details or double booked.
- The 35 tests that do not need an LLM pass.

### Honest notes
- gpt-oss-20b (the current fallback) is good at the booking flow but less polished: it once
  answered the UPI question with stray words from its instructions. That line was removed.
- "Who has the 11:00 slot?" is always safe (no data to leak) but the wording varies: sometimes
  a clear "I can't share customer details", sometimes just whether the slot is free.
- The tests check replies by keywords, not by a human or a judge model. I read every
  transcript in these runs; the keyword checks agreed with my reading.

### How to explain this on the review call
> "The agent can't leak another customer's details because it never has them. No tool returns
> a customer name, availability lists only free times, and a booking can only be fetched with
> the phone number it was made with. The prompt also tells it to refuse, but I don't rely on
> the prompt for anything that matters."

> "I test with simulated conversations that run the real instructions, tools and models, one
> per test question from the brief. They showed me the fastest model setting was skipping
> rules, so I traded about 0.3 seconds of latency for a setting that follows them."

---

## Milestone 4: a second business with data only (Thu 26 Nov)

### What was done
A car service centre, **Greenline Auto Care**, now has its own live call page at
`/call/greenline-auto-care`. It was added with one new file, `data/greenline-auto-care.yaml`,
and one command. `git status` showed that file as the only change: no code was touched.

It is deliberately different from the salon, to show the differences come from data:
60-minute slots (salon: 30), "mechanic" instead of "stylist", free cancellation up to 24 hours
(salon: 2), no cash accepted, different people, days and services.

### How long it took
- Loading the file and getting a working call page on the live server: **16 seconds**
  (one command, measured with a stopwatch in the shell).
- Writing the file: the AI assistant wrote it in under a minute. By hand, copying the salon's
  file and changing the values, expect 10 to 15 minutes. (Estimate, not measured.)
- Server restarts needed: none. The next call simply reads the new rows.

### The exact steps
```bash
# 1. Copy data/sunrise-salon.yaml to a new file and edit the values.
# 2. Load it (on the server; the file is piped in, so the image is not rebuilt):
docker compose exec -T web python -m app.manage load /dev/stdin < data/greenline-auto-care.yaml
# 3. Open /call/greenline-auto-care and press Call.
```
The same command with an edited file updates an existing business. That is the live-change
procedure for the review call.

### Why one business cannot see another's data
- Every table that holds business data has a `business_id` column, and every query in
  `app/db.py` and `app/booking.py` filters on it.
- The agent for a call is built from one business's rows (`db.load_business(slug)`), so its
  instructions contain only that business.
- The tools are created with that business baked in (`build_tools(business, ...)`). No tool
  has a parameter for choosing a business, so there is nothing for a trick prompt to aim at.
- The slug comes from the signed call token, set by our server from the page URL.

### Proof
`tests/test_isolation.py` (7 tests, no LLM needed):
- each agent's instructions contain its own facts and none of the other's;
- the garage runs on its own slot length, days and cancellation rule;
- neither business can use the other's services;
- a salon booking is invisible to the garage, even with the same phone number and the booking's
  id, and cannot be cancelled or moved from the garage's side;
- the garage's 10:00 stays free when the salon's 10:00 is booked;
- staff messages and call logs stay with their business;
- reloading a business's file keeps its existing bookings.

One simulated conversation: the garage agent quotes the oil change price, and asked about a
men's haircut with Anita it says it has no such information.

A scripted voice call to the live garage page: "An oil change costs Rs 1,800 and is done by
Imran Sheikh", "I can only help with Greenline Auto Care services", "48 Baner Road in Baner, Pune".

Test count now: 42 without an LLM, 25 simulated conversations.

### Honest notes
- Isolation is enforced by the application's queries, not by database row-level security. A
  bug in a new query that forgot `business_id` could leak. The isolation tests exist to catch
  that. Row-level security in Postgres would be the next layer for a real product.
- Both businesses are in the same timezone, so a second timezone is covered only by the code
  using the business's timezone everywhere, not by a test.

### How to explain this on the review call
> "Adding a business is adding rows. I copied the salon's data file, changed the values, ran
> one load command, and the garage's page was taking calls 16 seconds later with no code change
> and no restart. The agent is built per call from that business's rows, and its tools are
> created with the business fixed inside them, so there is no way to ask for another business."

---

## Milestone 5: measurements (Thu 26 Nov, evening)

All numbers are from real voice calls to the deployed agent, made by the scripted caller
running on the server. Raw outputs are in `docs/measurements/`.

### How to reproduce (on the server, in the project folder)
```bash
sh scripts/measure_latency.sh        # 7 calls, 22 replies, prints the latency report
sh scripts/concurrent_calls.sh 3     # 3 calls at once, prints rate-limit errors and latency
docker compose --profile test run --rm tests            # all tests
docker compose exec web python -m app.manage latency sunrise-salon   # report over all calls
```

### Latency: 22 replies, every reply counted, tool replies included
Measured from the moment end of speech is detected to the first reply audio sent.

| Model order | Median | p95 | Replies with a tool (9) | Replies without (13) |
|---|---|---|---|---|
| Groq first, then Cerebras (the approved order) | 1.43 s | 2.57 s | median 1.94 s | median 1.13 s |
| Cerebras first, then Groq | **1.03 s** | **1.64 s** | median 1.49 s | median 0.90 s |

Target: 1.2 s median, 2.0 s p95. Cerebras first meets it. Groq first does not.

Stages, Cerebras first: speech to text 0.24 s, LLM first token 0.43 s, text to speech first
audio 0.24 s (medians). The stages do not add up to the total because a reply that uses a
tool makes two LLM requests, and the first sentence has to be complete before Piper speaks it.

What the caller feels (from their last word, which adds the 0.45 s the voice detector waits):
median 1.51 s with Cerebras first, 1.91 s with Groq first.

### Several calls at once
Each caller asks five questions; one of the five needs a tool.

| Calls at once | Order | All answered? | Rate-limit errors | Median | p95 |
|---|---|---|---|---|---|
| 3 | Groq first | yes (15 of 15) | 13, absorbed by 5 fallbacks | 1.07 s | 3.29 s |
| 5 | Groq first | yes (25 of 25) | 27, absorbed by 8 fallbacks | 1.27 s | 2.93 s |
| 3 | Cerebras first | yes (15 of 15) | 0 | 1.07 s | 3.63 s |
| 5 | Cerebras first | yes (25 of 25) | 0 | 1.22 s | 2.77 s |
| 8 | Cerebras first | yes (40 of 40) | 79 | 3.11 s | 15.1 s |

What this says, honestly:
- **No call failed and no reply was lost at any level tested.** "Every model failed" was 0 in
  every run.
- **Up to 5 calls at once the median stays near target, but p95 does not.** Tool replies
  slow to 2.1 to 2.9 s under load.
- **8 at once is too many.** The 79 errors were almost certainly Groq's speech-to-text limit
  of 20 requests a minute (8 callers asked 40 questions in about a minute, and no LLM fallback
  was triggered). I could not confirm it from the logs because they were cleared when the
  agent restarted. Replies waited for retries, up to 15 s.
- The server itself was not the limit: the agent used 20 to 30% of the CPU and 1.5 GB of 12 GB.
- The scripted callers ran on the same server as the agent, so they competed for CPU. Real
  callers would not. The load numbers are therefore slightly pessimistic.

So on free tiers this deployment serves about 3 to 5 simultaneous callers, and the ceiling is
speech to text requests per minute, not the machine.

### Two live calls racing for the same slot
Two scripted callers asked for the same slot (Friday 11 AM with Anita) at the same time. Both
were read the details back. One was booked. The other heard "I'm sorry, the 11 am slot just got
taken" and was offered the other free times. The database had exactly one booking for the slot.
Transcripts are in `docs/measurements/m_load_groq_first.txt`.

### Tests
59 passed in the last complete run (35 without an LLM, 24 conversations). Since then 7
isolation tests and 1 more conversation were added: 42 without an LLM pass, and the new
conversation passes. A final complete run is part of Friday's review.

### Honest notes
- 22 replies is just over the 20 the assignment asks for. p95 over 22 values is the second
  slowest reply, so one bad reply moves it a lot.
- The scripted caller uses a synthetic voice with clean audio. Real callers with noise or
  accents may get slower or wrong transcripts.
- Interruption was measured in Milestone 1 (agent stops 0.22 to 0.26 s after the caller starts
  speaking; about 0.5 s as heard by the caller) and not re-measured here.

### How to explain this on the review call
> "I measure latency inside the agent for every reply: the clock starts when the voice detector
> decides the caller has finished and stops when the first audio is sent. Over 22 replies,
> including the ones that call tools, the median is about 1.0 seconds and the 95th percentile
> 1.6. With several calls at once nothing fails, but the slowest replies go over 2 seconds,
> and the real ceiling is the free speech to text limit of 20 requests a minute, about 3 to 5
> callers. In production I would pay for speech to text or host Whisper myself."

---

## After the milestones: why replies were slower than published targets, and two fixes (Fri 27 Nov)

### The question
Our reply time met the assignment's targets, but compared the way the industry measures (from
the caller's last word to audio heard) it was 1.73 s, slower than published targets such as
1.5 s. So I looked at where each reply's time went, using the call logs of the 66 measured replies.

### What the logs showed
Every step waited for the step before it. For a reply without a tool (medians):

| Step | Time |
|---|---|
| Wait in silence, to be sure the caller has finished | 0.48 s |
| Then send the recording to Whisper and wait for the text | 0.25 s |
| Then the LLM starts answering | 0.44 s |
| Then Piper makes the first audio | 0.17 s |

Two of these could be shortened by us. Two could not.

### Fix 1: speech to text starts during the wait (`app/stt_early.py`)
Whisper needs the whole recording, so before, it only started once the 0.45 s wait was over.
But during that wait nothing useful was happening.

Now there are two voice detectors listening to the same audio:
- A quick one, which says "probably finished" after 0.2 s of quiet. At that moment the
  recording is sent to Whisper, as a guess.
- The normal one, which says "finished" after 0.45 s of quiet, as before.

If the caller stays quiet, the text is ready at about the moment the normal detector fires, so
the LLM can start at once. If the caller carries on talking, the guess is thrown away and a new
one is made at the next pause, with the whole recording so far. The framework still gets
exactly one transcript per caller turn.

Two safety points:
- The decision that the caller has finished still takes the full 0.45 s. Nobody is cut off
  sooner than before.
- Each thrown-away guess is a wasted Whisper request, and the free tier allows 20 a minute.
  So after 2 wasted guesses in one turn, the agent stops guessing for that turn. A caller
  reading out a phone number digit by digit hits this limit.

### Fix 2: a long sentence is spoken first clause first (`app/tts_piper.py`)
Piper gives back no audio until it has finished the whole piece of text it was given, and it
needs about 0.045 s for every second of speech. A booking read-back is 9 seconds of speech, so
it started 0.49 s late. Now a sentence of 60 characters or more is cut once, after its first
comma, colon or semicolon. "Let me read that back:" is ready in 0.12 s and the rest is made
while it plays.

### What could not be shortened
- **The LLM's 0.43 s.** I timed the provider directly from the server: 0.36 to 0.40 s before
  the first byte, even for a one-line prompt on an open connection. The network to it is
  0.02 s. Thinking at "medium" instead of "low" costs about 0.05 s. So this is the provider's
  time to start, not something in our code.
- **The 0.45 s wait itself.** Making it shorter would cut off people who pause. Doing that
  safely needs a turn-detection model, which I did not add.

### A bug I made and caught
My first version of fix 1 joined the pieces of audio around each pause, and the pieces
overlapped, so Whisper heard some sounds twice. A phone number came out as
"9 8 7 6 5 4 4 3 2 1 0" and a booking call failed. I found it by reading the call transcripts
of the measurement run, not from the latency numbers, which looked fine. The fix keeps one
continuous recording per turn, and a test now checks that no audio is sent twice. The numbers
from that faulty run were thrown away.

### Result (66 replies each time, same script)

| | Before | After |
|---|---|---|
| Median, assignment's definition | 1.04 s | 0.81 s |
| 95th percentile, assignment's definition | 1.79 s | 1.74 s |
| Worst reply | 2.08 s | 1.90 s |
| Median as heard by the caller | 1.73 s | 1.50 s |
| 95th percentile as heard | 2.37 s | 2.35 s |

### Honest notes
- **The typical reply got 0.23 s faster. The slowest replies did not.** The slowest are tool
  replies after a dictated phone number: two LLM requests, and no head start for speech to
  text because of the wasted-guess limit.
- At 1.50 s as heard, we are at Daily's 1.5 s target and still slower than Twilio's 1.1 s.
- I cannot hear the audio. The cut after the first clause leaves a pause of about 0.35 s
  there, which is normal for a comma or colon, but Raj should listen to a booking read-back.
- This changes the plan's pipeline (the plan had speech to text start after the end-of-speech
  wait). Raj asked for the fix; the change is described here and in the README.

### How to explain this on the review call
> "My first numbers met your targets, but when I compared them with published figures the way
> the industry measures, I was slower. The logs showed speech to text only started after the
> 0.45 second wait that decides the caller has finished. So I added a second, quicker voice
> detector that sends the audio to Whisper after 0.2 seconds as a guess, while the decision
> still takes 0.45. That took the median from 1.04 to 0.81 seconds. I also cut long sentences
> after the first clause so Piper starts speaking sooner. The slowest replies did not improve:
> they are tool calls after a dictated phone number. What is left is the LLM provider's own
> 0.4 seconds and the wait itself, which would need a turn-detection model."


---

## Final check for edge cases: what was found and fixed (Fri 27 Nov, morning)

### What was done
Raj asked for one more check of everything, edge cases included. Three things were done:
1. An independent reviewer (a second AI session that had not written the code) read the
   booking, tools, database, owner-page and web code looking for real bugs.
2. I re-read the new latency code asking "what if this step fails?".
3. Seven awkward callers were run as real voice calls (`scripts/edge_calls.py`), and the live
   owner page and public addresses were sent bad input.

### Problems found and fixed (each has a test)

| # | Problem | How it could happen | Fix |
|---|---|---|---|
| 1 | **A booking the caller put off could be booked later.** | Agent reads back a booking. Caller: "No wait, let me check my calendar." Later the caller says "Okay, thank you" and the code took that as the yes. | The read-back is dropped at once on "no", "wait", "let me think", "maybe later" and similar, and after a second answer that is not a yes (`app/tools.py`). |
| 2 | **Renaming a staff member on the owner page made their booked slots look free**, so a slot could be sold twice. | Double booking is blocked per staff member and time. A rename created a new staff row; old bookings stayed on the old row. | An edit that would leave any upcoming booking without a slot is refused as a whole, with a message naming the bookings (`db.bookings_that_no_longer_fit`). |
| 3 | The same hole from changing the slot length, a staff member's hours or days, or moving a service to another staff member. | For example 30-minute slots changed to 60: a 10:30 booking no longer blocks a 10:00 slot. | Same check as 2. |
| 4 | **`slot_minutes: 0` would hang the agent** for every call to that business. | A typo on the owner page. The loop that lists slots never ended. | Every value is checked before saving (`db.check_business_data`): slot length 5 to 480, a real timezone name, hours that end after they start, at least one working day, no empty names, and so on. |
| 5 | A misspelt timezone saved fine and then broke every call. | "Asia/Bangalor". | Same check as 4. |
| 6 | A "yes" that also carried the phone number could skip the digit-by-digit read-back. | Agent: "10:30 AM Monday. What's your number?" Caller: "Sure, it's Priya, 98765..." | The shortcut now needs the agent to have offered to book that exact time, and the caller's line to contain no digits. "1 PM" no longer matches inside "11 PM". |
| 7 | If speech to text failed for one caller turn, the call could end in silence. | The provider is down or over its limit even after retries. | The turn is dropped, the agent says "Sorry, I didn't catch that. Could you say it again?", and the call goes on (`app/stt_early.py`, `app/agent.py`). |
| 8 | Piper answers text with nothing to say ("...", a lone dash) with an error. | The LLM writes "..." as a sentence. | Such text is replaced by a tenth of a second of silence (`app/tts_piper.py`). |
| 9 | A cancelled booking could be reported as "moved" if the cancel and the move arrived together; a booking in the past could be cancelled or moved. | Two calls about the same booking at once. | The move only touches a booking that is still booked; lookups only return upcoming bookings (`app/booking.py`). |
| 10 | Any future date was accepted, even the year 2031. | The LLM works out a date with the wrong year. | Dates more than a year ahead are refused with "check the year". |
| 11 | The owner page could create a brand-new business; odd characters in the key or the address gave a server error instead of a clear refusal. | Hand-made requests. | The page only edits an existing business; a non-English key is simply wrong (403); odd addresses are "No such business" (404). |
| 12 | A check-in after a cough ("Are you still there?") was logged as a 15-second reply. | Caller coughs, then stays silent. | The latency clock is cleared when the long-silence handling starts (`app/call_log.py`). No measured reply was affected (the worst was 1.9 s). |

### What the awkward callers showed (real voice calls, read word for word)
- **Caller hangs up mid-answer:** the call closes cleanly, nothing is left running.
- **Caller pauses mid-sentence:** one reply that answers both halves.
- **Caller asks a second question over the first answer:** the agent stops in 0.21 s and
  answers the second question.
- **7.6 seconds of speech with five questions in it:** one reply, all five answered.
- **A second of loud hiss:** no reply and no made-up words; the next question is answered.
- **"Yes, go ahead" with nothing to confirm:** the agent asks which service; nothing is booked.
- **Cancel with a number that has no booking:** the agent says so and asks for the number again.
- **Caller talks over the greeting: NOT handled well.** See the next section.

### One thing found and NOT changed: the first 3 seconds of the greeting
LiveKit ignores the caller for the first 3 seconds of the agent's first speech. It does this
so that the agent's own voice, coming back through a loudspeaker before the browser's echo
cancellation has settled, does not interrupt the greeting. The effect: a caller who starts
talking at once is not heard and has to repeat themselves. Our interruption figure (0.21 s)
is true for every reply after that.

It is one setting (`aec_warmup_duration`). I did not change it because the risk it guards
against (echo on laptop speakers) is exactly what I cannot test without a human, and Raj's
voice check has not happened yet. It is listed in the README's known gaps. **Raj to decide.**

### Things found and deliberately left, all listed in the README's known gaps
- One shared owner key opens every business (already listed; now says what that means).
- No limit on how often a browser can ask for a call.
- A phone number is the only proof of who the caller is.
- Move and cancel are confirmed in the LLM's words, not read back by code.

### Plan change to know about
The owner page is now stricter than before: it refuses edits it used to accept (problems 2
to 5). On the review call, a price, FAQ or added service still saves in one go. Changing a
staff member's hours, days or name is refused **only if** someone is booked in a slot the
change removes, and the red message names those bookings.

### Checked and found fine
No secrets in the repository or its history. Postgres, Piper and the web port are not
reachable from the internet (checked from outside). Every bookings query is limited to its
business. No tool returns a customer's name. All SQL uses parameters. The call and owner
pages put text on screen as text, never as HTML.

### How to explain this on the review call
"Before submitting I had the code reviewed by a second reviewer and ran awkward callers
against the live agent. The most important finding was on the owner page: double booking was
blocked per staff member and start time, so renaming a staff member or changing the slot
length could leave an existing booking where the check no longer saw it. Now any edit that
would orphan an upcoming booking is refused and tells the owner which bookings are in the
way. The second was a read-back that stayed open: a caller who said 'let me think' and later
'okay, thanks' would have been booked. Both have tests. One thing I found and left for a
human check is that the greeting cannot be interrupted in its first three seconds, which is
the framework's echo guard."
