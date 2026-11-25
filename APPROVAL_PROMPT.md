PLAN.md is approved with the changes below. Apply them to PLAN.md first (update the decisions,
architecture table, milestone times and section 7), show me the diff, then start Milestone 0.

1. Hosting (D1) is decided. Oracle Cloud, region India South (Hyderabad).
   - Instance: voice-receptionist, Intel VM.Standard3.Flex, 2 OCPU (4 vCPU), 12 GB RAM,
     100 GB disk, Ubuntu 22.04, x86_64. Paid from the Oracle Free Trial credit, so I am not
     charged. It is reclaimed when the trial ends in late December, after the review.
     Free Ampere (A1) and AMD shapes had no capacity in Hyderabad, which is why it is Intel.
   - Public IP: 129.225.94.107, user: ubuntu.
   - SSH private key: /Users/rajkumar/Downloads/ssh-key-2026-11-25.key
     Move it to ~/.ssh/porsai_oracle.key, chmod 600, and add a Host entry "porsai" in
     ~/.ssh/config. Never print the key, never copy it into the repo.
   - The OCI security list already allows TCP 22, 80 and 443 from 0.0.0.0/0 and the subnet
     routes to an internet gateway. Do not change OCI settings.
   - On the VM: open 80 and 443 in iptables (the Oracle Ubuntu image blocks them by default),
     insert the rules before the REJECT rule and make them persistent with netfilter-persistent.
     Install Docker Engine and the compose plugin.
   - HTTPS: Caddy with the hostname 129-225-94-107.sslip.io and Let's Encrypt.
   - Remove the Hugging Face check and the Google Cloud option from the plan.
   - Machine is 4 vCPU, not 2. Redo the TTS sizing and concurrency estimates for 4 vCPU.

2. Accounts (D2) are done. Groq key and LiveKit Cloud project "voice-receptionist" exist.
   I will paste the values into .env myself. Create .env.example with GROQ_API_KEY,
   LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET (plus any DB settings) and tell me when to
   fill .env. Never print secret values in the terminal or logs. The LiveKit project's data
   region shows "United States": measure call setup and audio round trip from India in M0 and
   report it.

3. GitHub repo (D3): create it yourself as a public repo ARajkumar45/sunrise-salon-voice-agent
   (not voice-receptionist). Use the gh CLI if it is logged in; if not, stop and tell me the
   exact command to run. Push after each milestone. .env must be in .gitignore before the
   first commit.

4. TTS (D4): default Kokoro (pinned release tag, never latest), fall back to Piper only if
   Kokoro misses the latency target on this 4 vCPU machine. Show me the bake-off table.

5. Latency report: the headline median and p95 must include every turn, tool-call turns too,
   measured exactly as the assignment says (from detecting end of speech to the first audio
   byte sent). You may also show tool and non-tool turns separately, but never leave turns out
   of the headline numbers.

6. Rate limits: the assignment says the reviewers will make a handful of test calls and it must
   not fail. In M5, run 3 calls at once against the deployed agent and show there are no 429
   errors, or show how the fallback handled them. Write the limits hit in the README.

7. Schedule. It is now Wednesday morning, so re-time the milestones (IST):
   M0 Wed 13:00, M1 Wed 17:00, M2 Wed 23:00, M3 Thu 13:00, M4 Thu 15:00, M5 Thu 22:00,
   M6 Fri 10:00, M7 Fri 15:00, M8 Fri 16:00 to 21:00 (submit by 21:00).
   - Thursday 15:30 to 21:00 I am on a train. I can use the laptop but the internet may drop.
     Plan voice tests that need me before 15:00 Thursday. During the train, work on things
     that do not need me (tests, docs, latency script, load test) and keep a list of what to
     check when I am back.
   - Friday 12:00 to 12:20 I have another interview. Nothing from me 11:00 to 12:30.
   - Cut order if late stays as in the plan. The two must-pass items and the test questions
     are never cut.

8. Every milestone: commit, push, update docs/EXPLAIN.md in plain simple English, and give me a
   short "how to explain this on the review call" note. I must be able to explain every file.

9. Before starting each milestone, re-read the matching part of the assignment PDF. If anything
   you plan differs from the PDF or this plan, stop and tell me first, starting with
   "DEVIATION: the plan says X, I suggest Y because Z". Never change the plan silently.
