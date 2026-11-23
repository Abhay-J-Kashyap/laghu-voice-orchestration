# Review: Sanjeevani Family Clinic

Read this, not the YAML. Approve with `python -m laghu_voice.setup approve <this folder>`.

## Who the agent is

English: The agent is a courteous clinic receptionist who calls the caller by name, gathers their details (patient name, age, reason or preferred doctor, and preferred day and time within the next 7 days), confirms the appointment and books it. The tone is polite, helpful and professional, using short spoken Hindi sentences.

## What the agent may say as fact

- **Dr. Mehra fee**: 500 rupees
- **Dr. Khan fee**: 700 rupees
- **Dr. Iyer fee**: 700 rupees
- **follow_up_free_within_days**: 7 days
- **appointment_window_days**: 7 days

## Your answers to its questions

- Where are appointments recorded, and how is the booking confirmed to the patient? → we have a register at reception, the agent just tells them the day and time on the call. no sms or whatsapp
- How many patients can each doctor see in a morning or evening slot, and what happens if a slot is full? → dont worry about that, reception manages the queue. if they come in their slot they will be seen
- How should the agent pick the doctor when the caller only describes a problem? → child under 14 goes to dr khan, skin hair or nail problems dr iyer, everything else dr mehra
- What should the agent do in an emergency (chest pain, breathing trouble, heavy bleeding)? → tell them to go to the nearest hospital immediately, dont book anything
- Can patients reschedule or cancel on this call? → no, for that they should call the reception during clinic hours
- What details must be collected besides name, age, doctor and time? → nothing else. we already have the number they are calling from
- Can someone book for another person, like a parent for a child? → yes thats common, just take the patients name and age not the callers
- When should the agent hand over to a person? → if they ask for someone at the clinic or ask about reports, test results or medicines. then pass to reception

## What it asks for

- **name** (name): Patient's full name
- **age** (number): Patient's age in years
- **doctor** (choice): Doctor to see the patient; options: mehra, khan, iyer
- **problem** (text): Brief description of the health problem
- **appointment_time** (time): Preferred day and part of day (morning/ evening) within next 7 days

## The flow

- **greet**: says *greeting*, waits for yes_no, yes → ask_problem; no → goodbye_decline
- **goodbye_decline**: says *goodbye_decline*, ends: declined
- **ask_problem**: says *ask_problem*, waits for problem, answer → decide_doctor
- **decide_doctor**: says *decide_doctor*, then ask_age
- **ask_age**: says *ask_age*, waits for age, answer → ask_time
- **ask_time**: says *ask_time*, waits for appointment_time, answer → confirm
- **confirm**: says *read_back*, waits for yes_no, yes → book; no → fix; corrected → confirm
- **fix**: says *fix_prompt*, waits for yes_no, corrected → confirm; yes → confirm; no → goodbye_decline
- **book**: runs book_appointment (commits), ok → booked_success; error → tech_problem
- **booked_success**: says *booked*, ends: success
- **emergency**: says *emergency_line*, then handover
- **human**: says *human_line*, then handover
- **report**: says *report_line*, then handover
- **cancel**: says *cancel_not_allowed*, then handover

## Every line, with its English meaning

Fixed lines are said exactly. LLM lines are written fresh each call; the example shows the style and is said if the LLM's words fail a check.

- **greeting** (fixed): मैं {agent}, {company} से बात कर रहा हूँ। क्या अभी बात कर सकते हैं?  
  *I am {agent} from {company}. May we talk now?*
- **goodbye_decline** (fixed): समझ गया, धन्यवाद। अलविदा।  
  *Understood, thank you. Goodbye.*
- **ask_problem** (LLM): goal: Please ask the caller to briefly describe their health problem.  
  example: कृपया अपनी स्वास्थ्य समस्या का संक्षिप्त विवरण दें।  
  *Ask the caller to briefly describe their health problem.*
- **ask_doctor** (fixed): आप किस डॉक्टर से मिलना चाहेंगे? डॉ. मेहरा, डॉ. खान या डॉ. आयर।  
  *Which doctor would you like to see? Dr. Mehra, Dr. Khan, or Dr. Iyer?*
- **pick_one** (fixed): कृपया एक विकल्प चुनें।  
  *Please choose one option.*
- **ask_age** (fixed): कृपया रोगी की आयु बताइए।  
  *Please tell the patient's age.*
- **ask_time** (fixed): कौन सा दिन और सुबह या शाम आप आना चाहेंगे? (अगले सात दिनों में)  
  *Which day and morning/evening would you like to come? (within next 7 days)*
- **read_back** (fixed): मैं समझा कि {name:hi} की आयु {age:words} साल है, डॉक्टर {doctor:label} के साथ, {appointment_time:time} पर। क्या यह सही है?  
  *I have understood that {name} is {age} years old, with Dr. {doctor} at {appointment_time}. Is this correct?*
- **fix_prompt** (LLM): goal: Ask which detail the caller wants to change or if they prefer not to book now.  
  example: कौन सी जानकारी बदलनी है या आप अभी बुक नहीं करना चाहते?  
  *Ask which detail the caller wants to change or if they prefer not to book now.*
- **booked** (fixed): आपकी अपॉइंटमेंट {appointment_time:time} को डॉक्टर {doctor:label} के साथ बुक हो गई है। धन्यवाद।  
  *Your appointment with Dr. {doctor} at {appointment_time} is booked. Thank you.*
- **emergency_line** (fixed): यह एक आपातकालीन स्थिति है, कृपया तुरंत नजदीकी अस्पताल जाएँ।  
  *This is an emergency, please go to the nearest hospital immediately.*
- **human_line** (fixed): मैं आपको क्लिनिक के स्टाफ से जोड़ रहा हूँ। कृपया प्रतीक्षा करें।  
  *Connecting you to clinic staff. Please hold.*
- **report_line** (fixed): रिपोर्ट या दवा संबंधी जानकारी के लिए मैं आपको रिसेप्शन से जोड़ता हूँ।  
  *For reports or medication information, I will connect you to reception.*
- **cancel_not_allowed** (fixed): कॉल पर रद्दीकरण या पुनर्निर्धारण संभव नहीं है, कृपया रिसेप्शन से संपर्क करें।  
  *Cancellation or rescheduling cannot be done over this call; please contact reception.*
- **goodbye** (fixed): धन्यवाद, अलविदा।  
  *Thank you, goodbye.*
- **decide_doctor** (LLM): goal: Based on the described problem and the patient’s age, select the appropriate doctor (Dr. Mehra, Dr. Khan or Dr. Iyer) and set the {doctor} slot.  
  example: समस्या के आधार पर डॉक्टर चुनें और {doctor:label} सेट करें।  
  *Select the appropriate doctor based on problem and age, set {doctor}.*

## Warnings from the checker

(none)

## Test calls

```
clinic: 3/8 succeeded; 0 with a safety problem; fallbacks 0/22 LLM blocks
   P1 cooperative run 3: age: wrong: 35 for 34
   P2 over-answerer run 3: age: wrong: 27 for 28
   P3 undecided run 3: age: wrong: 50 for 45
   P4 self-corrector run 3: problem: wrong: 'knee pain' for 'joint pain in knees'
   P5 questioner run 3: age: wrong: 65 for 60
ALL: 3/8 succeeded; 0 call(s) with a safety problem; fallbacks 0/22 (0%)
```

## What setup did

- 8 question(s) asked
- checker: 0 repair round(s); passed
- test calls, round 1: 1/8 passed
- test calls, round 2: 0/7 passed
- test calls, round 3: 2/7 passed
