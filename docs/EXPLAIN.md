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

## Milestone 3: answers and safety (Thu 26 Nov, early morning). NOT fully proven yet

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

### What has and has not been proven
- First full run (fastest setting): 17 of 24 passed.
- With medium reasoning, every conversation that had failed passed when run in small groups:
  facial on Tuesday, UPI, the 11:00 slot question, cancel, taken slot.
- **A clean full run of all 24 on the final settings has NOT happened.** The attempt ran out of
  Groq quota part way (see below), so 12 tests failed with "all LLMs failed", not wrong answers.
- No run, on any model or setting, revealed another customer's details or double booked.

### The daily token limit (the biggest open risk)
Groq's free tier gives each model 200,000 tokens per day. One reply costs about 1,500 to
2,700 tokens (instructions, tool descriptions, conversation so far, and with medium reasoning
the model's hidden thinking). Wednesday night's testing used the whole day's allowance for
gpt-oss-120b. Until it refills (it is a rolling 24 hours), live calls run on gpt-oss-20b.

What that means in practice: roughly 100 replies a day on the best model, so a handful of
booking calls. Cached prompt tokens are not discounted (checked). Options are in the README's
limits section once decided: add another free provider of the same open models as extra
fallback, shrink requests further, and avoid running the conversation tests more than needed.

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
