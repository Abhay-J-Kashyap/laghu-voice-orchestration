# Review: Northbridge School of Management

Read this, not the YAML. Approve with `python -m laghu_voice.setup approve <this folder>`.

## Who the agent is

English: The agent calls back leads who filled the enquiry form, confirms their interest, gathers program choice, intake, work experience and city, and books a free 30‑minute counselling session. The tone is polite, helpful and concise, using respectful आप and first‑person masculine forms.

## What the agent may say as fact

- **Full‑time MBA fee**: 8.5 lakh rupees
- **Executive MBA fee**: 6 lakh rupees
- **Online MBA fee**: 3.2 lakh rupees
- **Full‑time MBA duration**: 2 years
- **Executive MBA duration**: 18 months
- **Online MBA duration**: 2 years
- **July intake**: July
- **January intake (Online MBA only)**: January
- **July intake deadline**: 30 April
- **Counsellor working hours**: 10 am to 7 pm, Monday to Saturday
- **Maximum callback attempts**: 5
- **Callback window**: 1 day between attempts
- **Maximum booking horizon**: 14 days from today

## Your answers to its questions

- What system or calendar should the agent use to record and confirm counselling session bookings? → Bookings are recorded in the admissions team's shared booking calendar. The agent confirms the day and time out loud on the call. A counsellor from admissions then calls the student a day before the session to confirm. The agent does not send any SMS, WhatsApp or email.
- What specific information (e.g., email, phone, preferred video platform) must be collected to send the counselling session invitation? → phone
- Are there any blackout dates or holidays when counsellors are not available despite the 10 am‑7 pm schedule? → no
- What is the exact script or rule for handling callers who are not eligible (e.g., insufficient marks or no entrance score)? → please reach out to the college management for a payment seat or a discussion about your scores
- If the prospect wants a callback, what is the maximum number of callback attempts and the preferred time‑window for those callbacks? → 5 callback attempts and 1 day time window between each callback
- Should the agent verify the prospect’s city to determine if they are eligible for on‑campus programs, and if so, what cities are considered out‑of‑area? → No, the agent should not check a city for eligibility. Anyone from any city can apply. The agent only notes the city so the counsellor knows. The Full-time and Executive MBA are on campus in Pune. The Online MBA can be done from anywhere in India. If the caller is outside Pune, the agent mentions that the Online MBA needs no relocation and offers the counselling session by phone or video.
- What is the procedure for escalating the call to a human supervisor (e.g., if the prospect asks about scholarships or admission guarantees)? → The agent never answers questions about scholarships, fee waivers, discounts or admission guarantees. For these, and whenever the caller asks for a person, it says an admissions counsellor will handle that, offers to book the free counselling session, or arranges a callback from the admissions team. It never promises or hints that admission or a scholarship is certain. Admission is decided by the admissions committee after an application is submitted.
- How should the agent confirm the booking with the prospect (e.g., SMS, email) and what exact details must be included in that confirmation? → The agent confirms the booking out loud, at the end of the call. It does not send an SMS or email. It reads back the booking in one sentence: the day and time of the counselling session, that it is a free 30-minute session by phone or video, and the program the caller is interested in. It asks the caller to say yes if that is correct. If the caller corrects anything, the agent fixes it and reads it back again. A counsellor from admissions will call the caller a day before to confirm.

## What it asks for

- **name** (name): Caller’s name
- **program** (choice): ; options: full_time, executive, online
- **intake** (choice): ; options: july, january
- **experience** (number): Years of work experience
- **city** (text): Caller’s city
- **appointment** (time): Preferred day and part of day for counselling session
- **callback_time** (time): Preferred day and part of day for a callback

## The flow

- **greet**: says *greeting*, waits for yes_no, yes → ask_program; no → goodbye_decline
- **goodbye_decline**: says *goodbye*, ends: declined
- **ask_program**: says *ask_program*, waits for program, answer → program_chosen
- **program_chosen**: then ask_intake
- **ask_intake**: says *ask_intake*, waits for intake, answer → intake_chosen
- **intake_chosen**: then ask_experience
- **ask_experience**: says *ask_experience*, waits for experience, answer → experience_given
- **experience_given**: then ask_city
- **ask_city**: says *ask_city*, waits for city, answer → city_given
- **city_given**: then offer_counselling
- **offer_counselling**: says *offer_counselling*, waits for yes_no, yes → choose_appointment; no → offer_callback
- **choose_appointment**: says *choose_appointment*, waits for appointment, answer → appointment_set
- **appointment_set**: then confirm_booking
- **offer_callback**: says *offer_callback*, waits for yes_no, yes → ask_callback_time; no → goodbye_no_booking
- **ask_callback_time**: says *ask_callback_time*, waits for callback_time, answer → callback_time_set
- **callback_time_set**: then goodbye_callback_scheduled
- **confirm_booking**: says *readback_booking*, waits for yes_no, yes → book_session; no → fix_booking; corrected → confirm_booking
- **fix_booking**: says *fix_prompt*, waits for yes_no, yes → confirm_booking; no → goodbye_no_booking; corrected → confirm_booking
- **book_session**: runs book_session (commits), booked → booking_success; error → tech_problem
- **booking_success**: says *booking_done*, ends: success
- **goodbye_no_booking**: says *goodbye*, ends: declined
- **goodbye_callback_scheduled**: says *callback_scheduled*, ends: declined
- **scholarship_help**: says *scholarship_line*, then back
- **discount_help**: says *discount_line*, then back
- **admission_guarantee_help**: says *admission_line*, then back

## Every line, with its English meaning

Fixed lines are said exactly. LLM lines are written fresh each call; the example shows the style and is said if the LLM's words fail a check.

- **greeting** (fixed): मैं लघु, नॉर्थब्रिज स्कूल ऑफ मैनेजमेंट से बात कर रहा हूँ। क्या अभी बात कर सकते हैं?  
  *I am Laghu from Northbridge School of Management. May I speak with you now?*
- **ask_program** (fixed): आप किस एमबीए प्रोग्राम में रुचि रखते हैं? {program:words}  
  *Which MBA program are you interested in? {program:words}*
- **pick_one** (fixed): कृपया एक विकल्प चुनें।  
  *Please pick one option.*
- **ask_intake** (fixed): आप किस इंटेक में दाखिला लेना चाहते हैं? {intake:words}  
  *Which intake would you like to join? {intake:words}*
- **ask_experience** (fixed): आपके पास कार्य अनुभव के कितने वर्ष हैं?  
  *How many years of work experience do you have?*
- **ask_city** (fixed): आप किस शहर से हैं?  
  *Which city are you from?*
- **offer_counselling** (fixed): हम एक मुफ्त तीस मिनट का काउंसलिंग सत्र वीडियो या फ़ोन पर पेश कर रहे हैं। क्या आप इसे बुक करना चाहेंगे?  
  *We are offering a free 30‑minute counselling session via video or phone. Would you like to book it?*
- **choose_appointment** (fixed): काउंसलिंग सत्र के लिए आपका पसंदीदा दिन और समय बताइए।  
  *Please tell me your preferred day and time for the counselling session.*
- **offer_callback** (fixed): यदि आप अभी नहीं कर सकते तो हम आपको वापस कॉल कर सकते हैं। क्या आप कॉल बैक चाहते हैं?  
  *If you cannot now, we can call you back. Would you like a callback?*
- **ask_callback_time** (fixed): कॉल बैक के लिए आपका पसंदीदा दिन और समय बताइए।  
  *Please tell me your preferred day and time for the callback.*
- **readback_booking** (fixed): आपके लिए {program:label} का {intake:label} इंटेक में, {appointment:time} पर एक मुफ्त तीस मिनट का काउंसलिंग सत्र बुक किया गया है। क्या यह सही है?  
  *Read back the program, intake, and appointment time for the free 30‑minute counselling session.*
- **fix_prompt** (fixed): कृपया बताइए कि कौन सी जानकारी बदलनी है?  
  *Please tell me which detail you would like to change.*
- **booking_done** (fixed): आपकी बुकिंग सफल रही। धन्यवाद!  
  *Your booking was successful. Thank you!*
- **callback_scheduled** (fixed): हम आपके लिए एक कॉल शेड्यूल कर देंगे। धन्यवाद!  
  *We will schedule a callback for you. Thank you!*
- **scholarship_line** (LLM): goal: Explain that scholarship queries will be handled by an admissions counsellor.  
  example: छात्रवृत्ति संबंधी प्रश्न हमारे एडमिशन काउंसलर द्वारा संभाले जाएंगे।  
  *Scholarship queries will be handled by an admissions counsellor.*
- **discount_line** (LLM): goal: Explain that discount queries will be handled by an admissions counsellor.  
  example: छूट संबंधी प्रश्न हमारे एडमिशन काउंसलर द्वारा संभाले जाएंगे।  
  *Discount queries will be handled by an admissions counsellor.*
- **admission_line** (LLM): goal: Explain that admission guarantee queries will be handled by an admissions counsellor.  
  example: पक्का एडमिशन संबंधी प्रश्न हमारे एडमिशन काउंसलर द्वारा संभाले जाएंगे।  
  *Admission guarantee queries will be handled by an admissions counsellor.*

## Warnings from the checker

- line ask_program: asks for program without naming its options
- line ask_intake: asks for intake without naming its options

## Test calls

```
mba: 5/8 succeeded; 0 with a safety problem; fallbacks 2/17 LLM blocks
   P4 self-corrector run 1: experience: wrong: 10 for 4; appointment: wrong: '8:morning' for {'days': 1, 'part': 'morning'}
   P6 interrupter run 1: ended transferred (transferred), expected success; appointment: not collected
   P8 human-seeker run 1: ended success (booked), expected transferred; experience: wrong: 10 for 0
ALL: 5/8 succeeded; 0 call(s) with a safety problem; fallbacks 2/17 (12%)
```

## What setup did

- 8 question(s) asked
- checker: 2 repair round(s); passed
- test calls, round 1: 5/8 passed
- setup stopped: DailyLimit: HTTP 429: {"error":{"message":"Rate limit reached for model `openai/gpt-oss-120b` in organization `org_01m23mgkvfe918kwnmb4gqcdvf` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 197082, Requested 5441. Please try again in 18m9.935999999s. Need more tokens? Upgrade to Dev Tier t
