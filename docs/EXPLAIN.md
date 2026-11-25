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
