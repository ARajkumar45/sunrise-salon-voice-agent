# Your voice receptionist: a one-page guide for Sunrise Salon

This page is for the salon owner. No technical knowledge is needed.

## What it is
A voice receptionist on your website. A customer opens your call page, presses **Call**, and
talks to it from their browser, like a phone call.

Your call page: **https://129-225-94-107.sslip.io/call/sunrise-salon**

## What it does
- **Answers questions** about the salon: opening days and hours, who does what and when,
  prices, address, payment, parking, walk-ins, late arrival and the cancellation rule.
- **Books appointments.** It checks which times are really free, reads the details back to
  the customer, and books only after they say yes.
- **Moves and cancels appointments.** The customer gives the phone number they booked with.
- **Takes a message** when it does not know something, so your staff can call back.
- **Never books two people into the same slot**, even if two customers call at the same moment.

## What it will not do
- It will not guess. If something is not in your salon's details (for example membership
  plans), it says so and offers to pass the question to your staff.
- It will not give an exact price where your price says "from". It gives the starting price.
- It will not share one customer's name, number or booking with another caller, whoever they
  say they are.
- It will not give out staff members' personal phone numbers.
- It will not take payments, send text messages or reminders, or call customers.
- It only speaks English at the moment.
- It only discusses the salon. Asked for anything else, it politely returns to the salon.

## How to change hours, prices, services or answers
You do this yourself, in your browser. It takes about two minutes and works straight away.

1. Open your **owner's page** (keep this link private, it is your key):
   `https://129-225-94-107.sslip.io/admin/sunrise-salon?key=YOUR-KEY`
2. You will see your salon's details as plain text. For example:

   ```
   services:
   - name: Haircut (men)
     staff: Anita Rao
     price: Rs 400
   ```
3. Change what you need:
   - **A price:** change the text after `price:`.
   - **Opening times:** change `hours: 10:00-14:00` under the staff member. Use 24-hour
     time, so 4 PM is `16:00`.
   - **Working days:** change the list after `days:`, for example `[mon, wed, fri]`.
   - **A new service:** copy three lines of an existing service and change them. The name
     after `staff:` must match a staff member exactly.
   - **A common question:** change the text after `answer:`, or copy a `topic` and `answer`
     pair to add a new one.
   - **Something you do not offer:** add it to the `not_offered` list.
4. Press **Save**. If you see "Saved", the very next call uses the new details. If you see a
   red message, it tells you which line to fix. Nothing is changed until it says "Saved".

Keep the dashes and the spaces at the start of lines as they are. Existing bookings are kept
when you save.

**If customers are already booked**, the page will not let a change leave them without an
appointment. For example, if you shorten Anita's hours and someone is booked with her at a
time you removed, or you change the spelling of her name, you will see a red message listing
those bookings and nothing is saved. Move or cancel those bookings first (ask your support
contact), then make the change.

If you would rather not do it yourself, send the change to your support contact (below) and
it will be made for you, usually within minutes.

## Seeing what happened on a call
On the owner's page, click **Recent calls**. Each call shows everything that was said, every
time the receptionist checked or changed a booking, and how quickly it answered.
**Messages for staff** shows the questions customers left for you.

## When something goes wrong
| What you notice | What to do |
|---|---|
| A customer says the receptionist got something wrong | Open **Recent calls**, find the call by its time, and read it. If your details were wrong, fix them on the owner's page. If the receptionist said something that is not in your details, send the call number to support. |
| It gives an old price or old hours | Open the owner's page, check the line, press Save. |
| A customer was told a time was taken, but you think it was free | Someone else booked it first. Recent calls will show the other booking being made. |
| A booking needs changing and the customer cannot do it | Contact support with the customer's phone number and the change. |
| The Call button does nothing, or there is no voice | Ask the customer to allow the microphone and try Chrome or Safari. If it happens to you too, contact support. |
| It answers slowly or sounds confused for a while | It may be at its usage limit for the day (it runs on free services). It keeps working but with a simpler backup. Tell support if it lasts more than an hour. |
| It is completely down | Contact support. Take bookings by phone as usual until it is back. |

## Good to know
- Customers are identified by the phone number they give. Someone who knows a customer's
  number could move or cancel that customer's booking, exactly as they could by phoning your
  front desk.
- Phone numbers are heard, not typed. The receptionist always reads the number back before
  booking. Occasionally it mishears a digit and the customer needs to repeat it.
- The salon is closed on Sundays because nobody is listed as working that day. To open on a
  Sunday, add `sun` to someone's `days`.

## Support
Raj Kumar, who set this up for you. Contact details: *(to be added before handing over)*.
