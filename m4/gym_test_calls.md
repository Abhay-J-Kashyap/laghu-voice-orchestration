# Gym agent: test calls

Seven calls, each aimed at a set of edge cases. Hindi in English letters, its meaning in brackets, and what the
agent should do. Speak naturally: small changes in wording are fine and are part of the test.

**Rule** means the fixed rules decide, so the result should be exact. **Groq** means the LLM decides, so check
that the result is sensible, not word for word.

Start the server with:
`python -m laghu_voice.server --tts laghu --dialog agent --agent-spec agents\gym_onboarding.yaml`
Send me the trace after each call (`traces\<session>.jsonl`).

## Call 1: the straight path, answering two things at once

| You say | Agent should |
| --- | --- |
| Haan ji, boliye. (Yes, go ahead.) | Ask your name. *Rule* |
| Mera naam Abhay hai. (My name is Abhay.) | Ask your fitness goal, maybe using your name. *Groq, one call* |
| Wazan kam karna hai. (I want to lose weight.) | React briefly, then ask monthly, quarterly or yearly. *Rule* |
| Teen mahine wala, subah ka batch. (The three-month one, morning batch.) | **Skip the batch-time question** and ask when you'll start. *Rule* |
| Kal se. (From tomorrow.) | "The quarterly plan's fee is 4,000 rupees. Your membership starts tomorrow, in the morning batch. Shall I book it?" *Rule* |
| Haan, book kar do. (Yes, book it.) | "Booked, details by SMS", then the call ends. *Rule* |

## Call 2: talking over the agent (wear headphones)

| You say | Agent should |
| --- | --- |
| *While the greeting is still playing:* Haan haan, boliye. | Stop within about 0.2 s, then ask your name |
| Ek second. (One second.) | Say only "जी, ज़रूर" (sure), then wait. It shouldn't say "are you there?" for about 20 s. *Rule* |
| *After about 5 s:* Mera naam Abhay hai. | Ask your goal |
| Phir se boliye. (Say that again.) | Repeat its last question. *Rule* |
| Bas fit rehna. (Just staying fit.) | Ask the plan |
| *Halfway through the plan question:* Mahine wala. (The monthly one.) | Stop, take monthly, ask the batch time. *Rule* |
| Shaam. (Evening.) | Ask when you'll start |
| Parson. (Day after tomorrow.) | Fee 1,500, starts the day after tomorrow, evening batch: "Shall I book it?" |
| *While it is reading the fee:* Haan haan. | **Not book.** "Before we go ahead, please hear it all", then the fee and the question again. *Rule* |
| *Let it finish:* Haan. | Book; the call ends |

## Call 3: two answers at once, and ranges

| You say | Agent should |
| --- | --- |
| Haan. → Mera naam Abhay hai. | (as before) |
| Wazan bhi kam karna hai aur muscle bhi banani hai. (I want to lose weight and build muscle.) | Say you named two and ask you to pick one; **no guess**. *Rule* |
| Muscle banana. (Building muscle.) | Ask the plan |
| Ek saal wala. (The one-year one.) | Ask the batch time |
| Subah ya shaam. (Morning or evening.) | "Our batches are morning, afternoon and evening. Which one?" **No guess.** *Rule* |
| Shaam. | Ask when you'll start |
| Do teen din baad. (In two or three days.) | Ask for one exact day. *Rule* |
| Teen se paanch din. (Three to five days.) | Ask again, **worded differently**, ideally naming your options. *Rule decides, Groq words it* |
| Do mahine baad. (Two months later.) | Say you can start any time in the next 30 days, then ask again. *Groq reads it, the rule limit applies* |
| Chaar din baad. (In four days.) | Fee 12,000, starts in four days: "Shall I book it?" |
| Nahin. (No.) | Offer a free one-day trial |
| Nahin. | Thank you and goodbye; the call ends |

## Call 4: questions the agent should answer from what it knows

| You say | Agent should |
| --- | --- |
| Haan. → Mera naam Abhay hai. | Ask your goal |
| Pehle ye batao, kitne plan hain tumhare paas? (First tell me, how many plans do you have?) | List monthly 1,500, quarterly 4,000, yearly 12,000, then ask your goal again. *Groq* |
| Gym kab tak khula rehta hai? (Until when is the gym open?) | 6 am to 10 pm every day, then the question again. *Groq* |
| Trainer milega kya? (Will I get a trainer?) | A trainer on the gym floor is included. *Groq* |
| Personal training kitne ka hai? (How much is personal training?) | Costs extra; ask the front desk. **No price**: if it makes one up, the trace shows the sentence was rejected. *Groq + check* |
| Koi aur plan hai? (Any other plan?) (said flatly, no question tone) | Answer from the plans, not "didn't understand". *Groq* |
| Aaj mausam kaisa hai? (How's the weather today?) | "On this call I can help with gym membership", then the question again. *Groq* |
| Cricket ka score kya hai? (What's the cricket score?) | Second off-topic request: hand over to the front desk; the call ends. *Groq* |

## Call 5: bargaining and trials

Answer the first questions quickly (Abhay, fit rehna, mahine wala, shaam, kal se) to reach the fee.

| You say | Agent should |
| --- | --- |
| Thoda discount de do. (Give me a little discount.) | Fees are the same for everyone: "Shall I book at this fee?" *Rule* |
| Main purana customer hoon, discount milna chahiye. (I'm an old customer, I should get a discount.) | The same answer, **worded differently**, not "didn't understand" |
| Nahin. | Offer a free one-day trial |
| Ek hafte ka trial mil sakta hai? (Can I get a one-week trial?) | "We offer one day only. Shall I book it?" **Not book yet.** *Rule* |
| Nahin. | Go back to the trial offer |
| Theek hai, ek din ka hi kar do. (Okay, make it just one day.) | Book the trial; the call ends. *Groq reads the yes* |

## Call 6: silence

| You do | Agent should |
| --- | --- |
| Haan. Then, when it asks your name, **say nothing** | After about 6 s: "Are you there?" plus the question |
| Stay silent | Ask twice more, about 6 s apart |
| Stay silent | The fourth time: "I can't hear you, I'm ending this call", then the call ends |

Variant: answer "Ek second" instead, then stay silent. The first "are you there?" should come after about 20 s,
not 6.

## Call 7: ending early and asking for a person (two short calls)

| You say | Agent should |
| --- | --- |
| *Call 7a, at the greeting:* Abhi nahin, baad mein baat karenge. (Not now, we'll talk later.) | "No problem, call us whenever you like." The call ends |
| *Call 7b, at any question:* Mujhe kisi insaan se baat karni hai. (I want to talk to a person.) | Connect to the front desk; the call ends. *Rule* |
| *Or:* Manager se baat karao. (Let me talk to the manager.) | The same. *Rule* |

## What I'll look at in the traces

- Whether each **Rule** row did exactly what it says.
- Whether each **Groq** row was sensible: numbers only from the gym's facts, no invented prices, no
  repeated sentences.
- How often the example line was said instead of Groq's words, and why (`guard` in the dialog records).
- Timing: turn end to first agent audio, and how often the filler played.
- Barge-ins: how fast the agent stopped, and whether anything stale was said after you spoke.

## Call 8: retest of the fixes from calls 1 to 4

One call, in this order. Restart the server first.

| You say | Agent should |
| --- | --- |
| *At the greeting:* Haan haan, mera naam Abhay hai. (Yes yes, my name is Abhay.) | Skip the name question and ask your fitness goal. *Groq reads the name* |
| *Cut in while it asks:* Haan main hoon, bas paanch second. (Yes I'm here, just five seconds.) | Just "Sure." and wait. *Rule* |
| Phir se boliye. (Say it again.) | "I'll say it again" plus the goal question, with no "I was asking" |
| Pehle ye batao, kitne plan hain? (First tell me, how many plans are there?) | "Three plans: monthly, quarterly, yearly" plus the goal question. *Groq*, no refusal |
| Mera fitness lakshya vajan bhi kam karna hai aur muscle bhi banana hai. (My fitness goal is to lose weight and also build muscle.) | Ask you to pick one. Not booked as "stay fit" |
| Vajan kam karna. (Lose weight.) | Ask which plan |
| Mahine wala. (The monthly one.) | Ask which batch time |
| Shaam. *(one word, then stop talking)* | Ask when you'll start, **without the 1.5 s wait**. The trace says `dialog_hint` |
| Main sure nahin hoon, kya main baad mein bata sakta hoon? (I'm not sure, can I tell you later?) | Say you can change it later at the front desk, then ask again. *Groq* |
| Parson. (The day after tomorrow.) *(one word)* | The fee and the booking question, again without the long wait |
| *Cut in near the very end of the booking question:* Haan, book kar do. (Yes, book it.) | Book it, without reading everything again. If you cut in early (during the fee), it should read it again |
