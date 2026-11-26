# Reply email to PorsAI (draft, for Raj to send)

Fill in the three items in [square brackets] before sending. The owner page key is the
`ADMIN_KEY` value in your `.env`; paste it into the email, never into the repository.

---

**Subject:** Voice AI Agent take-home: submission, Raj Kumar

Hi [name],

Here is my submission for the Forward Deployed Engineer take-home.

- **Live call page (Sunrise Salon):** https://129-225-94-107.sslip.io/call/sunrise-salon
- **Second business, added with data only:** https://129-225-94-107.sslip.io/call/greenline-auto-care
- **Public repo:** https://github.com/ARajkumar45/sunrise-salon-voice-agent
- **Demo video (under 5 minutes):** [Google Drive link, access set to "anyone with the link"]
- **Handover note for the salon owner:** https://github.com/ARajkumar45/sunrise-salon-voice-agent/blob/main/docs/HANDOVER.md
- **Owner page (edit business details, read call logs):** https://129-225-94-107.sslip.io/admin/sunrise-salon?key=[ADMIN_KEY]

What it is: LiveKit Agents with Silero VAD, Whisper for speech to text, gpt-oss-120b as the
LLM and Piper for text to speech, with Postgres. `docker compose up` runs everything.

Measured on the deployed agent, over 66 replies including the ones that call tools: median
1.04 s and 95th percentile 1.79 s from end of speech detected to first audio sent. Measured the
way the industry usually does, from the caller's last word to audio heard, the median is 1.73 s;
the README and docs/RESEARCH.md set that against published figures. 67 automated
tests pass, including 25 simulated conversations (your 15 test questions among them) and a
test that fires 50 simultaneous bookings at one slot.

Things I would rather you hear from me than find:

- The main LLM runs on Cerebras, which is credit based, not a free tier. I added it because
  Groq's free tier allows 200,000 tokens a day for the best model, about 100 replies. It is the
  same open model. Without the Cerebras key the project runs on Groq's free tier alone, where
  I measured a median of 1.43 s and a 95th percentile of 2.57 s, which misses the target.
- With several calls at once nothing fails, but the 95th percentile goes above 2 seconds, and
  about 3 to 5 simultaneous callers is the practical limit on free tiers.
- The demo runs on trial credit (Oracle VM, Cerebras) that ends in late December.
- None of the optional extras is built, apart from a small owner page protected by a shared key.

The README lists every known gap, the rate limits I hit, and a note on scaling to 1,000
businesses. `docs/REQUIREMENTS_CHECK.md` goes through the assignment line by line with the
evidence for each item. I used Claude Code as my AI coding tool and can explain any part of the code.

I am happy to walk through it and make a live change on the review call.

Thanks,
Raj Kumar
[phone number]
