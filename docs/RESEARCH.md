# How our numbers compare with published references

Researched on 26 November 2026. Every reference figure below was read on the page or paper
linked, in that session, unless it is marked **unverified**. Our own figures are measurements
on the deployed agent (`docs/measurements/`).

## The most important point: which of our numbers is comparable

The assignment defines latency as "from the moment your system detects the caller stopped
speaking to the first audio byte of the reply sent to the caller". We measure exactly that,
and it is our headline number.

Almost every published figure uses a different, stricter start: **the moment the caller
actually stops speaking**. That includes the time the system waits in silence to be sure the
caller has finished (0.45 s in our case). Published figures also usually end when the caller
*hears* the reply, not when the server sends it.

So we have three numbers, and each answers a different question:

| Our number | Start of the clock | End of the clock | Compare it with |
|---|---|---|---|
| **Assignment's definition** | Voice detector reports end of speech | First reply audio sent by the server | The assignment's targets (1.2 s median, 2.0 s p95). No published source we opened uses this start point. |
| **From the caller's last word** | Caller's last word (back-dated by the agent) | First reply audio sent by the server | "Platform" figures such as Twilio's platform turn gap. |
| **As heard at the caller's end** | End of the scripted caller's recording | First reply audio received by the scripted caller | "Voice-to-voice" and "mouth-to-ear" figures (Daily, Twilio, Hamming, benchmarks). |

Measured over **66 replies in 21 real voice calls** to the deployed agent, in one continuous
run with no rate-limit errors (`docs/measurements/final_latency_66_replies.txt`). 27 of the 66
replies called a tool.

| Our number | Median | p95 | Worst |
|---|---|---|---|
| Assignment's definition | **1.04 s** | **1.79 s** | 2.08 s |
| From the caller's last word | 1.52 s | 2.27 s | 2.56 s |
| As heard at the caller's end | 1.73 s | 2.37 s | 2.75 s |

Stages (medians): speech to text 0.26 s, LLM first token 0.43 s, text to speech first audio 0.20 s.

The "as heard" figure slightly understates the truth: the scripted caller's recordings end
with 0.1 to 0.2 s of silence, so its clock starts that much after the last word.

## Reference figures

### Response latency of voice agents

| Source | Figure | How they define it | Type |
|---|---|---|---|
| Daily / Pipecat, "Voice AI & Voice Agents: An Illustrated Primer" (2025, updated June 2026), https://voiceaiandvoiceagents.com/ | "1,500 ms voice-to-voice latency is an important target"; "as low as 500 ms" demonstrated; LLM first token "600 ms or less is fast enough" | "from the end of the user's speech to the beginning of the LLM's speech", measured at the client | Engineering guide |
| Twilio, "A Guide to Core Latency in AI Voice Agents (Cascaded Edition)", P. Bredeson, 17 Nov 2025, https://www.twilio.com/en-us/blog/developers/best-practices/guide-core-latency-ai-voice-agents | Median targets. Mouth-to-ear turn gap: target 1,115 ms, upper limit 1,400 ms. Platform turn gap: 885 / 1,100 ms. Speech to text 350 / 500. LLM first token 375 / 750. Text to speech first byte 100 / 250 | "begins when the user stops speaking and ends when the agent's reply reaches their ear"; the platform gap leaves out the voice network | Vendor engineering blog |
| Hamming, "Voice AI latency: what's fast, what's slow, how to fix it", S. Sharma, 12 Jan 2026, https://hamming.ai/blog/voice-ai-latency-whats-fast-whats-slow-how-to-fix-it | Production traffic: P50 1.4 to 1.7 s, P90 3.3 to 3.8 s, P95 4.3 to 5.4 s. "Target under 800ms end-to-end" | First audio byte minus end of user speech | Vendor blog; the data cannot be audited |
| Retell AI, reporting Cekura benchmarks, 2026, https://www.retellai.com/learn/voice-ai-latency-benchmarks-comparing-real-time-response-performance | Production phone agents: lowest median 2.38 s, slowest 3.76 s. Benchmark means: fastest 1.27 s, slowest 3.08 s | Caller stops speaking to agent starts, measured from the caller's side on real phone calls | Vendor marketing page reporting a third party |
| Lin et al., "Full-Duplex-Bench", arXiv:2503.04721, 2025 (ASRU 2025) | Turn-taking latency: Moshi 0.265 s, dGSLM 0.352 s, Freeze-Omni 0.953 s, Gemini Live 1.301 s | "between the end of the user's speech and the start of the model's response" | Peer-reviewed benchmark |
| OpenAI, "Hello GPT-4o", 2024, https://openai.com/index/hello-gpt-4o/ | Speech-to-speech model: "as little as 232 milliseconds, with an average of 320"; the older cascaded Voice Mode averaged 2.8 s (GPT-3.5) and 5.4 s (GPT-4) | Not defined on the page | Vendor announcement |
| Défossez et al., "Moshi", arXiv:2410.00037, 2024 | "theoretical latency of 160ms, 200ms in practice" | Model latency, not a measured turn gap | Preprint |
| LiveKit, "Understand and improve voice agent latency", 13 Apr 2026, https://livekit.com/blog/understand-and-improve-agent-latency | No numeric target is published | | Vendor blog |

### How long systems wait to decide the caller has finished

| Setting | Default | Source |
|---|---|---|
| LiveKit Silero VAD, minimum silence | 0.55 s (we use 0.45 s) | https://docs.livekit.io/agents/build/turns/vad/ |
| LiveKit endpointing, minimum extra delay | 0.5 s (we set 0) | https://docs.livekit.io/agents/build/turns/turn-detector/ |
| Pipecat VAD stop time | 0.2 s with a turn model; 0.8 s listed for VAD alone | https://docs.pipecat.ai/server/utilities/audio/silero-vad-analyzer |
| Industry habit | "Most defaults are set around 500ms" | Twilio guide above |

### Human conversation

| Source | Figure | What it measures |
|---|---|---|
| Levinson & Torreira, "Timing in turn-taking and its implications for processing models of language", Frontiers in Psychology 6:731, 2015, https://www.frontiersin.org/articles/10.3389/fpsyg.2015.00731/full | "the gaps between turns average around 200 ms" | End of one speaker to start of the next |
| Same paper, reporting Stivers et al., PNAS 2009 | Across 10 languages, "means between 7 and 468 ms"; English 236 ms | Response time to yes/no questions, face to face. The 2009 paper itself could not be opened, so this is **verified only through the 2015 review**. |
| Heldner & Edlund, "Pauses, gaps and overlaps in conversations", Journal of Phonetics 38, 2010 | In one corpus, gaps: mean 424 ms, median 318 ms. 70 to 82% of intervals were shorter than 500 ms, and 82 to 95% shorter than 1,000 ms | Automatic detection over three speech corpora |
| Same | The fastest human vocal reaction is "about 200ms" | Simple reaction time |

### Telephony standard

ITU-T Recommendation G.114 (05/2003), https://www.itu.int/rec/T-REC-G.114-200305-I/en :
mouth-to-ear delays "of less than 150 ms" give "essentially transparent interactivity", and
one-way delay should "not exceed ... 400 ms". **These are one-way transmission delays, not
response times.** They are relevant to our network leg (21 to 23 ms round trip from India to
the server through LiveKit), not to how quickly the agent replies.

### Interruption

No published target for how quickly an agent should stop speaking was found. Twilio, Hamming
and Daily give qualitative advice only. Picovoice defines the metric as "time from the user's
first interrupting syllable to silence from the agent"
(https://picovoice.ai/guide/voice-agents/voice-ux-latency-turn-taking/). Full-Duplex-Bench
reports time *to respond* after an interruption (Moshi 0.257 s, Gemini Live 1.183 s), which is
a different thing from time to fall silent.

### The models

| Model | Published figure | Source |
|---|---|---|
| whisper-large-v3-turbo on Groq | Word error rate 12%, 216 times real time (test set not stated) | https://console.groq.com/docs/speech-to-text |
| whisper-large-v3-turbo, OpenAI | Decoder "reduced from 32 to 4" layers; "performs similarly to large-v2", with larger degradation on some languages | https://github.com/openai/whisper/discussions/2363 |
| gpt-oss-120b on Groq | About 500 tokens a second; no first-token figure published | https://console.groq.com/docs/model/openai/gpt-oss-120b |
| gpt-oss-120b on Cerebras | About 3,000 tokens a second; no first-token figure published | https://inference-docs.cerebras.ai/models/openai-oss |
| Piper | Real-time factor 0.153 on a laptop CPU, **unverified** (reported second-hand; the paper body could not be read) | arXiv:2512.08006 |

### How many samples a 95th percentile needs

Lehmann & Paromau, "Beyond Point Estimates: Distributional Uncertainty in Machine Learning
Performance Evaluation", arXiv:2501.16931, 2025: "only central quantiles can be estimated
reliably, whereas more extreme quantiles require substantially larger sample sizes". A
distribution-free confidence interval for a quantile u exists only if u^n + (1-u)^n is at
most alpha. For the 95th percentile at 95% confidence that needs **at least 59 samples**
(our arithmetic from their rule). With 22 samples the "p95" is simply the second slowest
reply. That is why the measurement was extended beyond the assignment's minimum of 20.

## Honest reading

**Against the assignment's targets** (1.2 s median, 2.0 s p95, its own definition): met, at
1.04 s and 1.79 s over 66 replies. One reply of 66 took longer than 2.0 s (2.08 s).

**Against what the industry publishes**, using our like-for-like "as heard" figure of 1.73 s median:
- It is **slower than the published targets**: Daily and Pipecat's 1,500 ms, Twilio's 1,115 ms
  mouth-to-ear target (and above its 1,400 ms upper limit), and Hamming's 800 ms.
- It is **in line with what production systems are reported to deliver**: Hamming's observed
  median of 1.4 to 1.7 s, and faster than the 2.38 to 3.76 s medians reported for phone agents.
- Our tail is good by comparison: p95 2.37 s against Hamming's reported 4.3 to 5.4 s.
- It is **far from human conversation**, where gaps average around 0.2 s, and far from
  speech-to-speech models (0.2 to 0.35 s).

So the fair summary is: typical for a production pipeline of this kind, not fast, and it meets
the assignment's targets because the assignment's clock starts later than the industry's.

**Where the time goes, against Twilio's per-stage targets:**

| Stage | Ours (median) | Twilio target / upper limit | Verdict |
|---|---|---|---|
| End-of-speech wait | 0.45 s | "around 500 ms" is the common default | Slightly better than usual |
| Speech to text | 0.26 s | 350 / 500 ms | Better than target |
| LLM first token | 0.43 s | 375 / 750 ms | Between target and limit |
| Text to speech first audio | 0.20 s | 100 / 250 ms | Misses target, inside limit |

The biggest single item is the 0.45 s end-of-speech wait, which the assignment's definition
does not count. The next lever would be a turn-detection model so that the wait can be
shortened without cutting callers off, then streaming speech to text.

**Interruption.** No published target exists to compare against. Ours: the agent stops 0.21 s
after detecting the caller's speech, about 0.5 s as heard by the caller. The assignment asks
for half a second.

**Sample size.** 66 replies clears the 59 needed for the 95th percentile to mean something.
The earlier 22-reply runs (p95 of 1.49 s and 1.64 s) were too small for that, and the larger
run's 1.79 s is the figure to trust.

## What is not like for like
- Our headline figure starts after the voice detector's wait. Published figures start at the
  caller's last word. Compare our "from the caller's last word" and "as heard" figures instead.
- Hamming's and Retell's figures are production phone traffic across many deployments. Ours
  is one deployment, a scripted caller with clean synthetic speech, and a browser, not a phone.
- Speech-to-speech models (GPT-4o voice, Moshi) are a different architecture from our
  speech to text → LLM → text to speech pipeline, and their published endpoints differ.
- Human gap figures come from face-to-face conversation. People also plan their reply while
  the other person is still talking, which a pipeline like ours does not do.
- Groq's 12% word error rate has no stated test set. It does not predict accuracy on browser
  microphone audio. We did not measure word error rate ourselves.
- Our scripted caller ran on the same server as the agent, so its "as heard" figure includes
  the trip through LiveKit but not a home or mobile connection.
