# Milestone 4, part B: five live calls

Since Amendment 3, `m4/auto_calls.py` makes these calls (the same lines, in Devanagari, with Laghu's female
voice). The tables below are what it says.

Hindi in English letters, with the meaning in brackets. The agent asks one thing at a time; answer each
question as it comes, after it finishes speaking (you can interrupt it, but for these five calls, don't).
If it mishears and asks again, answer again as a caller would. Don't restart a call: each call counts once.

The passcode: after the read-back, the client prints `[demo passcode from the backend: 7 8 8 3 5 3]`. Read the
six digits out one by one in Hindi (saat, aath, aath, teen, paanch, teen). Digits: ek, do, teen, chaar,
paanch, chhah, saat, aath, nau, shoonya.

The PAN: say each letter as its English name and each digit in Hindi, with a small pause between them.

## L1: Rajesh, approved, agrees (expected: completed)

| Agent asks | You say |
| --- | --- |
| Do you have three-four minutes? | Haan ji, bataiye. (Yes, go ahead.) |
| Your full name? | Mera naam Rajesh Kumar hai. |
| Date of birth? | Baarah April, unnees sau athaasi. (12 April 1988) |
| PAN, one character at a time? | A, B, C, D, E, ek, do, teen, chaar, F. |
| Reads it back: is it all correct? | Haan, sab sahi hai. |
| The code? | (the six digits, in Hindi) |
| How much? | Teen lakh rupaye. (3 lakh) |
| For how long? | Teen saal ke liye. (3 years) |
| Monthly income? | Pachaanve hazaar. (95,000) |
| Job, own business, or not working? | Main naukri karta hoon. (I have a job.) |
| The offer, then: do you agree? | Haan, main sahmat hoon. (Yes, I agree.) |

## L2: Imran, declined, wants to talk to someone (expected: transferred)

| Agent asks | You say |
| --- | --- |
| Three-four minutes? | Haan ji. |
| Name? | Mera naam Imran Qureshi hai. |
| Date of birth? | Ikkees July, unnees sau ikyaanve. (21 July 1991) |
| PAN? | C, D, E, F, G, teen, chaar, paanch, chhah, H. |
| Is it all correct? | Haan, sahi hai. |
| The code? | (the six digits) |
| How much? | Do lakh. (2 lakh) |
| How long? | Do saal. (2 years) |
| Income? | Saath hazaar. (60,000) |
| Job or business? | Mera apna business hai. (I have my own business.) |
| "I can't offer this loan today. Would you like to talk to a colleague?" | Haan, kisi se baat karwa dijiye. (Yes, connect me to someone.) |

## L3: Anita, approved, declines the terms (expected: consent_declined)

| Agent asks | You say |
| --- | --- |
| Three-four minutes? | Haan, bataiye. |
| Name? | Mera naam Anita Desai hai. |
| Date of birth? | Athaarah February, unnees sau nabbe. (18 February 1990) |
| PAN? | F, G, H, I, J, chhah, saat, aath, nau, K. |
| Is it all correct? | Haan ji. |
| The code? | (the six digits) |
| How much? | Ek lakh. (1 lakh) |
| How long? | Do saal. |
| Income? | Atthaasi hazaar. (88,000) |
| Job or business? | Naukri. (A job.) |
| The offer, then: do you agree? | Nahin, mujhe sochna hai. (No, I need to think.) |

## L4: Priya, asks for too much, gets a smaller offer, agrees (expected: completed)

| Agent asks | You say |
| --- | --- |
| Three-four minutes? | Haan ji. |
| Name? | Mera naam Priya Sharma hai. |
| Date of birth? | Teen November, unnees sau chauraanve. (3 November 1994) |
| PAN? | B, C, D, E, F, do, teen, chaar, paanch, G. |
| Is it all correct? | Haan, sab sahi hai. |
| The code? | (the six digits) |
| How much? | Pandrah lakh, teen saal ke liye. (15 lakh, for 3 years: it should skip the tenure question) |
| Income? | Bayaalees hazaar. (42,000) |
| Job or business? | Salary milti hai. (I get a salary.) |
| A smaller offer, then: do you agree? | Haan, theek hai. (Yes, okay.) |

## L5: Kavya, no account, leaves her details (expected: lead_captured)

| Agent asks | You say |
| --- | --- |
| Three-four minutes? | Haan ji. |
| Name? | Mera naam Kavya Reddy hai. |
| Date of birth? | Chaudah August, unnees sau baanve. (14 August 1992) |
| PAN? | Z, Z, Z, Z, Z, nau, nau, nau, nau, Z. |
| Is it all correct? | Haan, sahi hai. |
| "No account found. Shall I email you a link?" | Haan, bhej dijiye. (Yes, send it.) |
| Email? | K, A, V, Y, A, dot, R, E, D, D, Y, at, example, dot, com. |
| Reads it back: correct? | Haan, sahi hai. |

After the five calls: `python m4\summarize_live.py --last 5` and send me what it prints, plus the five trace
files it names (in `traces\`).
