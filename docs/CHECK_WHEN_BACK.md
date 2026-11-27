# Things for Raj to check when back online

Written while you were on the train (Thu 26 Nov). Each item needs a human; I could not do it.

## Voice checks on the live page (about 15 minutes)
Open https://129-225-94-107.sslip.io/call/sunrise-salon on your laptop, then repeat on your phone.

1. **Does it hear you and answer?** Ask "How much is a men's haircut?" Expect "400 rupees with Anita Rao".
2. **Echo.** Use the laptop speakers, not headphones. The agent must not cut itself off or answer its own voice.
3. **Interrupt it.** While it is answering "When is the hair colour person in?", start talking. It should stop within about half a second.
4. **Silence.** Say nothing for 15 seconds. It should ask "Are you still there?", and hang up after about 40 seconds.
5. **A full booking.** "Book me a men's haircut tomorrow at 11." Give a name and a phone number. It reads the details back; say "yes". Then call again and cancel it with the same number.
6. **Phone numbers.** Does it hear your 10 digits correctly when you say them at normal speed? If not, tell me what it heard.
7. **The voice.** It is Piper's `en_US-lessac-medium`. Tell me if it is hard to understand at any point.
   Also listen to the read-back: it is now made in two pieces ("Let me read that back." then the rest). Is the join natural?
9. **Talk over the greeting (added Fri 27 Nov).** Press Call and start speaking in the first second or two. Today the agent finishes about 3 seconds of its greeting and does not hear what you said in that time (the framework's echo guard). I kept that guard on purpose. If item 2 (laptop speakers) shows no echo at all, tell me and I can shorten it.
8. **The second business:** https://129-225-94-107.sslip.io/call/greenline-auto-care, ask "How much is an oil change?"

If anything goes wrong, tell me roughly when. I can pull the full log of that call.

## Decisions waiting for you
1. **Put Cerebras first in the model order?** Same model on both. Measured over 22 replies:
   Cerebras first gives median 1.03 s and p95 1.64 s (meets the target); the approved order,
   Groq first, gives 1.43 s and 2.57 s (misses it). The cost is that every call then uses the
   Cerebras trial credit, and the live demo depends on a trial that ends in about 30 days,
   after which it falls back to Groq and the slower numbers.
2. **Check the Cerebras billing page** to confirm automatic top-up is off, so the 5 dollars
   of credit can run out without your card being charged. I cannot see that page.

## New since you left
- Owner's page: `https://129-225-94-107.sslip.io/admin/sunrise-salon?key=...` (the key is
  `ADMIN_KEY` in your `.env`). Try changing a price and saving, then call and ask for it.
  This is also the fastest way to do the live change on the review call.
- `docs/HANDOVER.md`: please read it as if you were the salon owner. Add your contact details
  at the bottom.
