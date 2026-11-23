# Review: Northbridge School of Management

Read this, not the YAML. Approve with `python -m laghu_voice.setup approve <this folder>`.

## Who the agent is

English: The agent calls back enquiries, verifies interest, gathers required details, and books a free 30‑minute counselling session. The tone is polite, helpful and concise, using respectful आप and male first‑person forms.

## What the agent may say as fact

- **Full‑time MBA fee**: आठ लाख पचास हज़ार रुपये
- **Full‑time MBA duration**: दो साल
- **Executive MBA fee**: छह लाख रुपये
- **Executive MBA duration**: एक साल आठ महीने
- **Online MBA fee**: तीन लाख बीस हज़ार रुपये
- **Online MBA duration**: दो साल
- **July intake**: जुलाई
- **January intake**: जनवरी
- **July intake deadline**: तीस अप्रैल
- **Counsellor working hours**: सुबह दस बजे से शाम सात बजे तक, सोमवार से शनिवार
- **Booking window**: चौदह दिन
- **Maximum callback attempts**: पाँच
- **Callback window**: एक दिन

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

- **name** (name): Caller’s full name
- **program** (choice): ; options: full_time, executive, online
- **intake** (choice): ; options: july, january
- **experience** (number): Years of work experience
- **city** (text): Caller’s city of residence
- **appointment** (time): Preferred day and part of day for counselling session
- **callback_time** (time): Preferred day and part of day for a callback

## The flow

- **greet**: says *greeting*, waits for yes_no, yes → ask_program; no → goodbye_decline
- **goodbye_decline**: says *goodbye*, ends: declined
- **ask_program**: says *ask_program*, waits for program, answer → check_program
- **check_program**: says *confirm_program*, waits for yes_no, yes → ask_intake; no → ask_program
- **ask_intake**: says *ask_intake*, waits for intake, answer → check_intake
- **check_intake**: says *confirm_intake*, waits for yes_no, yes → ask_experience; no → ask_intake
- **ask_experience**: says *ask_experience*, waits for experience, answer → check_experience
- **check_experience**: says *confirm_experience*, waits for yes_no, yes → ask_city; no → ask_experience
- **ask_city**: says *ask_city*, waits for city, answer → check_city
- **check_city**: says *confirm_city*, waits for yes_no, yes → offer_counselling; no → ask_city
- **offer_counselling**: says *offer_counselling*, waits for yes_no, yes → ask_appointment; no → offer_callback
- **ask_appointment**: says *ask_appointment*, waits for appointment, answer → confirm_appointment
- **confirm_appointment**: says *readback_booking*, waits for yes_no, yes → commit_booking; no → fix_booking; corrected → confirm_appointment
- **fix_booking**: says *fix_prompt*, waits for yes_no, yes → confirm_appointment; no → goodbye_decline
- **commit_booking**: runs book_session (commits), success → booking_success; error → tech_problem
- **booking_success**: says *booking_done*, ends: success
- **offer_callback**: says *offer_callback*, waits for yes_no, yes → ask_callback_time; no → goodbye_decline
- **ask_callback_time**: says *ask_callback_time*, waits for callback_time, answer → confirm_callback
- **confirm_callback**: says *readback_callback*, waits for yes_no, yes → callback_success; no → goodbye_decline
- **callback_success**: says *callback_done*, ends: success
- **scholarship_help**: says *scholarship_line*, then back
- **discount_help**: says *discount_line*, then back
- **admission_guarantee_help**: says *admission_line*, then back

## Every line, with its English meaning

Fixed lines are said exactly. LLM lines are written fresh each call; the example shows the style and is said if the LLM's words fail a check.

- **greeting** (fixed): मैं {agent}, {company} से बात कर रहा हूँ। क्या आप अभी बात कर सकते हैं?  
  *I am {agent} from {company}. May I speak with you now?*
- **goodbye** (fixed): आपके समय के लिए धन्यवाद। यदि भविष्य में कोई प्रश्न हों तो कृपया संपर्क करें। अलविदा।  
  *Thank you for your time. If you have any questions later, please get in touch. Goodbye.*
- **ask_program** (fixed): आप किस एमबीए प्रोग्राम में रुचि रखते हैं? विकल्प: पूरा समय एमबीए, एक्जीक्यूटिव एमबीए, ऑनलाइन एमबीए।  
  *Which MBA program are you interested in? Options: Full‑time MBA, Executive MBA, Online MBA.*
- **pick_one** (fixed): कृपया नीचे दिए गए विकल्पों में से एक चुनें।  
  *Please pick one of the options below.*
- **confirm_program** (fixed): क्या आप {program:label} में रुचि रखते हैं?  
  *Do you want the {program:label}?*
- **ask_intake** (fixed): आप किस इंटेक में प्रवेश लेना चाहते हैं? विकल्प: जुलाई, जनवरी।  
  *Which intake are you interested in? Options: July, January.*
- **confirm_intake** (fixed): क्या आप {intake:label} इंटेक चाहते हैं?  
  *Do you want the {intake:label} intake?*
- **ask_experience** (fixed): आपके पास कार्य अनुभव के कितने वर्ष हैं?  
  *How many years of work experience do you have?*
- **confirm_experience** (fixed): क्या आपका कार्य अनुभव {experience:words} वर्ष है?  
  *Is your work experience {experience:words} years?*
- **ask_city** (fixed): आप किस शहर में रहते हैं?  
  *Which city do you reside in?*
- **confirm_city** (fixed): क्या आप {city:hi} में रहते हैं?  
  *Do you reside in {city}?*
- **offer_counselling** (fixed): मैं आपको एक मुफ्त तीस मिनट का काउंसलिंग सत्र वीडियो कॉल पर बुक कर सकता हूँ, क्या यह ठीक रहेगा?  
  *I can book you a free 30‑minute counselling session via video call, is that okay?*
- **ask_appointment** (fixed): कृपया बताइए कि आप काउंसलिंग सत्र के लिए कौन सा दिन और समय पसंद करेंगे?  
  *Please tell me which day and time you prefer for the counselling session.*
- **readback_booking** (fixed): आपके लिए {program:label} का {intake:label} इंटेक, {appointment:time} पर एक मुफ्त तीस मिनट का काउंसलिंग सत्र बुक किया गया है। क्या यह सही है?  
  *A free 30‑minute counselling session for the {program:label} {intake:label} intake has been booked for {appointment:time}. Is this correct?*
- **fix_prompt** (fixed): कृपया बताइए कौन सी जानकारी बदलनी है या आप अभी नहीं बुक करना चाहते?  
  *Please tell me which detail to change or if you do not wish to book now.*
- **booking_done** (fixed): बुकिंग रिकॉर्ड कर ली गई है। धन्यवाद!  
  *The booking has been recorded. Thank you!*
- **offer_callback** (fixed): क्या आप चाहते हैं कि हम आपको एक उपयुक्त समय पर कॉल बैक करें?  
  *Would you like us to call you back at a convenient time?*
- **ask_callback_time** (fixed): कृपया वह दिन और समय बताइए जब हम आपको कॉल बैक कर सकें (अधिकतम चौदह दिन के भीतर)।  
  *Please specify the day and time for a callback (within the next 14 days).*
- **readback_callback** (fixed): हम आपको {callback_time:time} पर कॉल बैक करेंगे। क्या यह ठीक है?  
  *We will call you back on {callback_time:time}. Is that okay?*
- **callback_done** (fixed): कॉल बैक शेड्यूल कर दिया गया है। धन्यवाद!  
  *The callback has been scheduled. Thank you!*
- **scholarship_line** (LLM): goal: Explain that scholarship related questions will be handled by an admissions counsellor  
  example: स्कॉलरशिप के बारे में जानकारी हमारे प्रवेश सलाहकार से प्राप्त होगी, मैं आपका मुफ्त काउंसलिंग सत्र बुक कर देता हूँ।  
  *Scholarship queries will be handled by the admissions counsellor; I will book your free counselling session.*
- **discount_line** (LLM): goal: Explain that discount related questions will be handled by an admissions counsellor  
  example: डिस्काउंट के बारे में जानकारी हमारे प्रवेश सलाहकार से मिलेगी, चलिए आपका मुफ्त काउंसलिंग सत्र तय करते हैं।  
  *Discount queries will be handled by the admissions counsellor; let's schedule your free counselling session.*
- **admission_line** (LLM): goal: Explain that admission guarantee questions will be handled by an admissions counsellor  
  example: प्रवेश की गारंटी के प्रश्न हमारे प्रवेश सलाहकार से पूछें, मैं अभी आपका मुफ्त काउंसलिंग सत्र बुक कर देता हूँ।  
  *Admission guarantee queries will be handled by the admissions counsellor; I will now book your free counselling session.*

## Warnings from the checker

(none)

## Test calls

```
mba: 8/8 succeeded; 1 with a safety problem; fallbacks 1/3 LLM blocks
ALL: 8/8 succeeded; 1 call(s) with a safety problem; fallbacks 1/3 (33%)
   unsafe: mba P6 run 2: ["(b) number(s) ['24'] in: आपके लिए ऑनलाइन एमबीए का जुलाई इंटेक, कल, मंगलवार, चौबीस नवंबर पर एक मुफ्त तीस मिनट का काउ"]
```

## What setup did

- 8 question(s) asked
- checker: 1 repair round(s); passed
- test calls, round 1: 7/8 passed
- test calls, round 2: 0/1 passed
- the last repair didn't change how any call failed: the problem is likely in the engine, not the spec; stopped repairing (see the calls' ends above)
