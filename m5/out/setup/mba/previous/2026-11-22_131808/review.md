# Review: Northbridge School of Management

Read this, not the YAML. Approve with `python -m laghu_voice.setup approve <this folder>`.

## Who the agent is

English: The agent calls back leads who filled the enquiry form, confirms their interest, gathers program, intake, work experience and city, and books a free 30‑minute counselling session. The tone is polite, helpful and concise, using respectful आप and male first‑person forms.

## What the agent may say as fact

- **Full‑time MBA fee**: आठ लाख पचास हजार रुपये
- **Full‑time MBA duration**: दो साल
- **Executive MBA fee**: छह लाख रुपये
- **Executive MBA duration**: एक साल आठ महीने
- **Online MBA fee**: तीन लाख बीस हजार रुपये
- **Online MBA duration**: दो साल
- **July intake**: जुलाई
- **January intake**: जनवरी
- **July intake deadline**: तीस अप्रैल
- **Eligibility marks**: पचास प्रतिशत
- **Minimum work experience for Executive MBA**: तीन साल

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
- **phone** (digits): 10‑digit phone number
- **program** (choice): ; options: full_time, executive, online
- **intake** (choice): ; options: july, january
- **work_exp** (number): Years of work experience
- **city** (text): Caller’s city of residence
- **session_time** (time): Preferred day and part of day for the counselling session (within next 14 days)
- **callback_time** (time): Preferred day and part of day for a callback if caller is busy

## The flow

- **greet**: says *greeting*, waits for yes_no, yes → ask_program; no → decline_greeting
- **decline_greeting**: says *goodbye_decline*, ends: declined
- **ask_program**: says *ask_program*, waits for program, answer → ask_intake
- **ask_intake**: says *ask_intake*, waits for intake, answer → ask_work_exp
- **ask_work_exp**: says *ask_work_exp*, waits for work_exp, answer → ask_city
- **ask_city**: says *ask_city*, waits for city, answer → offer_session
- **offer_session**: says *offer_session*, waits for yes_no, yes → ask_session_time; no → callback_offer
- **callback_offer**: says *callback_offer*, waits for yes_no, yes → ask_callback_time; no → goodbye_no_booking
- **ask_session_time**: says *ask_session_time*, waits for session_time, answer → confirm_details
- **ask_callback_time**: says *ask_callback_time*, waits for callback_time, answer → confirm_callback
- **confirm_details**: says *readback_details*, waits for yes_no, yes → commit_booking; no → fix_details; corrected → confirm_details
- **fix_details**: says *fix_prompt*, waits for yes_no, yes → confirm_details; no → goodbye_no_booking; corrected → confirm_details
- **commit_booking**: runs book_session (commits), session_booked → booking_success; error → tech_problem
- **booking_success**: says *booking_confirmed*, ends: success
- **confirm_callback**: says *readback_callback*, waits for yes_no, yes → callback_success; no → goodbye_no_booking; corrected → confirm_callback
- **callback_success**: says *callback_confirmed*, ends: success
- **goodbye_no_booking**: says *goodbye_no_booking*, ends: declined
- **scholarship_help**: says *scholarship_line*, then back
- **admission_help**: says *admission_line*, then back
- **human_help**: says *human_line*, then handover

## Every line, with its English meaning

Fixed lines are said exactly. LLM lines are written fresh each call; the example shows the style and is said if the LLM's words fail a check.

- **greeting** (fixed): मैं {agent}, {company} से बात कर रहा हूँ। क्या आप अभी बात कर सकते हैं?  
  *I am {agent} from {company}. May I speak with you now?*
- **goodbye_decline** (fixed): समझ गया, धन्यवाद। अलविदा।  
  *Understood, thank you. Goodbye.*
- **ask_program** (fixed): आप किस एमबीए प्रोग्राम में रुचि रखते हैं? फुल टाइम एमबीए, एक्जीक्यूटिव एमबीए या ऑनलाइन एमबीए?  
  *Which MBA program are you interested in? Full‑time MBA, Executive MBA, or Online MBA?*
- **ask_intake** (fixed): आप कौन सा इंटेक चाहते हैं? जुलाई या जनवरी?  
  *Which intake do you prefer? July or January?*
- **ask_work_exp** (fixed): आपके पास कितने साल का कार्य अनुभव है?  
  *How many years of work experience do you have?*
- **ask_city** (fixed): आप किस शहर में रहते हैं?  
  *Which city do you reside in?*
- **offer_session** (fixed): हम एक मुफ्त तीस मिनट का काउंसलिंग सत्र वीडियो या फ़ोन पर बुक कर सकते हैं। क्या आप अभी बुक करना चाहेंगे?  
  *We can book a free 30‑minute counselling session via video or phone. Would you like to book it now?*
- **callback_offer** (fixed): यदि आप अभी व्यस्त हैं, तो हम आपके लिए एक कॉल बैक शेड्यूल कर सकते हैं। क्या आप कॉल बैक चाहते हैं?  
  *If you are busy now, we can schedule a callback. Would you like a callback?*
- **ask_session_time** (fixed): कॉलिंग के लिए आपका पसंदीदा दिन और समय (आगे के चौदह दिनों में) बताइए।  
  *Please tell me your preferred day and time for the counselling session within the next 14 days.*
- **ask_callback_time** (fixed): कॉल बैक के लिए आपका पसंदीदा दिन और समय (आगे के चौदह दिनों में) बताइए।  
  *Please tell me your preferred day and time for the callback within the next 14 days.*
- **readback_details** (fixed): आपने {program:label} प्रोग्राम, {intake:label} इंटेक, {work_exp:words} साल का कार्य अनुभव, {city:hi} शहर, और {session_time:time} समय चुना है। यह एक मुफ्त तीस मिनट का काउंसलिंग सत्र है। क्या यह सही है?  
  *You have selected the {program:label} program, {intake} intake, {work_exp:words} years of work experience, city {city}, and {session_time:time} for the session. It's a free 30‑minute counselling session. Is this correct?*
- **fix_prompt** (fixed): कृपया वह विवरण बताइए जिसे आप बदलना चाहते हैं, या यदि आप अब नहीं बुक करना चाहते तो नहीं कहें।  
  *Please tell me which detail you would like to change, or say no if you do not wish to book now.*
- **booking_confirmed** (fixed): आपका मुफ्त तीस मिनट का काउंसलिंग सत्र {session_time:time} के लिए बुक हो गया है, {program:label} प्रोग्राम के लिए। धन्यवाद।  
  *Your free 30‑minute counselling session has been booked for {session_time:time} for the {program:label} program. Thank you.*
- **readback_callback** (fixed): आपका कॉल बैक {callback_time:time} पर निर्धारित किया गया है। क्या यह सही है?  
  *Your callback has been scheduled for {callback_time:time}. Is this correct?*
- **callback_confirmed** (fixed): आपका कॉल बैक {callback_time:time} पर तय हो गया है। धन्यवाद।  
  *Your callback has been scheduled for {callback_time:time}. Thank you.*
- **goodbye_no_booking** (fixed): कोई बात नहीं, यदि आप बाद में बुक करना चाहें तो हमें कॉल करें। अलविदा।  
  *No problem, call us later if you wish to book. Goodbye.*
- **scholarship_line** (LLM): goal: Explain that the agent cannot promise scholarships and will forward the query to an admissions counsellor.  
  example: मैं छात्रवृत्ति या फीस में छूट के बारे में जानकारी नहीं दे सकता, लेकिन हमारे एडमिशन काउंसलर इस पर चर्चा करेंगे।  
  *I cannot provide scholarship or fee waiver details, but an admissions counsellor will discuss this.*
- **admission_line** (LLM): goal: Explain that admission cannot be guaranteed and will be decided by the admissions committee.  
  example: मैं एडमिशन की गारंटी नहीं दे सकता, यह हमारे एडमिशन कमेटी द्वारा तय किया जाता है।  
  *I cannot guarantee admission; it is decided by the admissions committee.*
- **human_line** (LLM): goal: Offer to arrange a human counsellor or callback while still proposing the free session.  
  example: मैं आपको हमारे एडमिशन काउंसलर से जोड़ दूँगा, साथ ही आप चाहें तो मुफ्त काउंसलिंग सत्र बुक कर सकते हैं।  
  *I will connect you to an admissions counsellor, and you may also book the free counselling session.*
- **pick_one** (fixed): कृपया इनमें से एक चुनें।  
  *Please choose one of these.*

## Warnings from the checker

(none)

## Test calls

```
mba: 2/8 succeeded; 0 with a safety problem; fallbacks 0/17 LLM blocks
   P1 cooperative run 1: ended transferred (transferred), expected success
   P2 over-answerer run 1: ended transferred (transferred), expected success
   P3 undecided run 1: ended transferred (transferred), expected success
   P4 self-corrector run 1: ended transferred (transferred), expected success; work_exp: wrong: 10 for 4; city: wrong: 'Bengaluru' for 'Bangalore'
   P5 questioner run 1: callback_time: wrong: '1:morning' for {'days': 8, 'part': 'morning'}
   P6 interrupter run 1: ended None (None), expected success; no ending after 30 caller turns
ALL: 2/8 succeeded; 0 call(s) with a safety problem; fallbacks 0/17 (0%)
```

## What setup did

- 8 question(s) asked
- checker: 1 repair round(s); passed
- test calls, round 1: 2/8 passed
- setup stopped: DailyLimit: HTTP 429: {"error":{"message":"Rate limit reached for model `openai/gpt-oss-120b` in organization `org_01m23mgkvfe918kwnmb4gqcdvf` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199758, Requested 1192. Please try again in 6m50.4s. Need more tokens? Upgrade to Dev Tier today at 
