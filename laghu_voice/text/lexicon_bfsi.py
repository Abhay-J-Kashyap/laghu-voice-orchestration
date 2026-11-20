"""English words common in Hindi banking calls, written the way they're said (design doc: Normalizer).

Laghu's frontend already spells acronyms (OTP, EMI, PAN, KYC) and knows a few words (Dr, km, ok).
Lowercase loanwords such as "loan" or "approve" it can't read, so they come from here. Keys are lower case.
Add brand and product names per agent.
"""

BFSI_WORDS: dict[str, str] = {
    "account": "अकाउंट", "accounts": "अकाउंट्स", "address": "एड्रेस", "amount": "अमाउंट",
    "application": "एप्लीकेशन", "apply": "अप्लाई", "approve": "अप्रूव", "approved": "अप्रूव्ड",
    "approval": "अप्रूवल", "balance": "बैलेंस", "bank": "बैंक", "branch": "ब्रांच", "call": "कॉल",
    "card": "कार्ड", "cash": "कैश", "charges": "चार्जेस", "cibil": "सिबिल", "confirm": "कन्फ़र्म",
    "credit": "क्रेडिट", "customer": "कस्टमर", "date": "डेट", "debit": "डेबिट", "details": "डिटेल्स",
    "document": "डॉक्यूमेंट", "documents": "डॉक्यूमेंट्स", "due": "ड्यू", "email": "ईमेल",
    "executive": "एग्ज़ीक्यूटिव", "fee": "फ़ीस", "form": "फ़ॉर्म", "home": "होम", "income": "इनकम",
    "installment": "इंस्टॉलमेंट", "insurance": "इंश्योरेंस", "interest": "इंटरेस्ट", "limit": "लिमिट",
    "link": "लिंक", "loan": "लोन", "loans": "लोन", "madam": "मैडम", "message": "मैसेज",
    "mobile": "मोबाइल", "number": "नंबर", "offer": "ऑफ़र", "online": "ऑनलाइन", "payment": "पेमेंट",
    "personal": "पर्सनल", "please": "प्लीज़", "policy": "पॉलिसी", "process": "प्रोसेस",
    "processing": "प्रोसेसिंग", "rate": "रेट", "salary": "सैलरी", "sir": "सर", "sorry": "सॉरी",
    "status": "स्टेटस", "tenure": "टेन्योर", "thank": "थैंक", "thanks": "थैंक्स", "transfer": "ट्रांसफ़र",
    "update": "अपडेट", "verify": "वेरिफ़ाई", "verification": "वेरिफ़िकेशन", "yes": "यस", "you": "यू",
}
