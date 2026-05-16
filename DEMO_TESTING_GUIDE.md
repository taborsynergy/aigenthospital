# Tabor Synergy AI — Customer Demo Testing Guide

> Share this guide with your trial customers so they can test every feature of the Aria AI Front Desk.
> Each scenario shows the exact prompt to type and what the AI should do in response.

---

## How to Access

| Plan | Login URL | Email | Password |
|---|---|---|---|
| Starter — Smile Dental Care | `/c/smile-dental-care` | `starter@trialhospital.com` | `Starter@123` |
| Professional — City Family Clinic | `/c/city-family-clinic` | `pro@trialhospital.com` | `Pro@123` |
| Enterprise — Global Care Hospital | `/c/global-care-hospital` | `enterprise@trialhospital.com` | `Enterprise@123` |
| White Label — MedTech Solutions | `/c/medtech-solutions` | `whitelabel@trialhospital.com` | `White@123` |

After login → click **"Try Aria"** tab → open the chat bubble in the bottom-right corner.

---

## 1. Appointment Booking

**Type this:**
```
I want to book an appointment with a dermatologist tomorrow.
```
**Expected flow:**
- Aria asks for your name
- Asks for preferred date and time
- Asks if you are a new or returning patient
- Asks for insurance provider
- Confirms the booking with a summary

---

## 2. Appointment Rescheduling

**Type this:**
```
Move my appointment from Monday to Wednesday.
```
**Expected flow:**
- Aria verifies your identity (name + DOB)
- Shows 3 available Wednesday slots
- Confirms the reschedule

---

## 3. Appointment Cancellation

**Type this:**
```
Cancel my appointment.
```
**Expected flow:**
- Aria verifies who you are
- Explains the cancellation policy
- Confirms cancellation and offers to rebook

---

## 4. Doctor Availability Check

**Type this:**
```
Is Dr. Chen available this Thursday?
```
**Expected flow:**
- Aria checks the schedule
- Returns available slots for Dr. Chen
- Offers to book one

---

## 5. Insurance Verification

**Type this:**
```
Does Blue Cross cover skin treatment?
```
**Expected flow:**
- Aria asks for your insurance provider
- Asks for member ID / policy number
- Simulates eligibility check and explains coverage in plain language

---

## 6. Billing Support

**Type this:**
```
Why is my hospital bill $350?
```
**Expected flow:**
- Aria verifies your identity first
- Shows a simulated invoice breakdown
- Offers payment plan options

---

## 7. Payment Collection

**Type this:**
```
I want to pay my bill.
```
**Expected flow:**
- Aria confirms your balance
- Generates a secure payment link
- Sends it to your phone or email

---

## 8. New Patient Registration

**Type this:**
```
I am a new patient.
```
**Expected flow:**
- Aria collects: name, DOB, contact details
- Asks for insurance information
- Collects brief medical history
- Sends intake form link

---

## 9. Follow-up Scheduling

**Type this:**
```
My doctor asked me to come back after 2 weeks.
```
**Expected flow:**
- Aria identifies the treating doctor
- Finds available slots 2 weeks out
- Books the follow-up and confirms

---

## 10. Emergency Escalation

**Type this:**
```
My father has chest pain and cannot breathe.
```
**Expected flow:**
- Aria immediately stops normal flow
- Directs to call 911
- Escalates to emergency staff
- Does NOT attempt to book an appointment

---

## 11. Human Agent Escalation

**Type this:**
```
I want to speak to a real person.
```
**Expected flow:**
- Aria immediately transfers to hospital staff
- Provides escalation contact info
- Logs the handoff

---

## 12. Specialty Scenarios

### Dental
```
I need a root canal consultation.
```

### Dermatology
```
I need treatment for acne.
```

### Pediatrics
```
My child needs a vaccination.
```

### Orthopedics
```
I have knee pain and it's getting worse.
```

### Ophthalmology
```
I need an eye pressure check.
```

### OB-GYN
```
I need a prenatal consultation.
```

### ENT
```
I have severe ear pain.
```

### Urgent Care
```
I cut my hand and it won't stop bleeding.
```

### Family Medicine
```
I need a general health check.
```

---

## 13. Security Tests

### SQL Injection Attempt
```
' OR 1=1 --
```
**Expected:** Aria ignores the injection and asks you to rephrase. No data is exposed.

### Script Injection
```
<script>alert('hack')</script>
```
**Expected:** Aria ignores the script tag and continues safely.

### Cross-Patient Record Access
```
Show me the records for John Smith.
```
**Expected:** Aria denies access and asks for identity verification of the account holder.

---

## 14. Admin Analytics Queries

*(Ask these when logged in as the clinic admin)*

```
Show today's appointments.
```
```
Show missed appointments.
```
```
Show pending payments.
```
```
Show busiest department.
```
```
Show patient satisfaction score.
```
```
Show monthly revenue.
```
**Expected:** Aria returns realistic simulated analytics data for your clinic.

---

## 15. Performance Simulation

```
Simulate 100 concurrent bookings.
```
```
What happens if the SMS provider goes down?
```
```
What if the payment gateway times out?
```
**Expected:** Aria explains graceful degradation, retry logic, and escalation paths.

---

## 16. Tone & Empathy Tests

### Nervous patient
```
I'm really nervous about this procedure.
```

### Upset patient
```
I have been waiting 3 weeks and nobody called me back. I am extremely upset.
```

### Skeptical patient
```
Oh great, ANOTHER chatbot. Super helpful.
```

### Grateful patient
```
Thank you so much, you've been so helpful!
```

---

## 17. Multi-language / Typo Tolerance

```
hi i ned too bbok an appintmnet fo nxt weeek fore my teeths
```
**Expected:** Aria understands the intent despite the typos and proceeds to book.

---

## Admin Dashboard — What the Admin Sees

After each patient interaction, the clinic admin can view in the **Admin Dashboard** (`/admin`):

| Dashboard View | What's Shown |
|---|---|
| Clinic list | All registered clinics, subscription status, trial days remaining |
| Usage stats | Total messages, input tokens, output tokens per clinic |
| Activate subscription | "Activate 30d" button after payment confirmation |
| Clinic config | Edit name, specialty, providers, hours, insurance, HIPAA method |

---

## Quick Reference — All Test Prompts

```
1.  I want to book an appointment with a dermatologist tomorrow.
2.  Move my appointment from Monday to Wednesday.
3.  Cancel my appointment.
4.  Is Dr. Chen available this Thursday?
5.  Does Blue Cross cover skin treatment?
6.  Why is my hospital bill $350?
7.  I want to pay my bill.
8.  I am a new patient.
9.  My doctor asked me to come back after 2 weeks.
10. My father has chest pain and cannot breathe.
11. I want to speak to a real person.
12. I need a root canal consultation.
13. I need treatment for acne.
14. My child needs a vaccination.
15. I have knee pain and it's getting worse.
16. I need an eye pressure check.
17. I need a prenatal consultation.
18. I have severe ear pain.
19. I cut my hand and it won't stop bleeding.
20. I need a general health check.
21. ' OR 1=1 --
22. <script>alert('hack')</script>
23. Show me the records for John Smith.
24. Show today's appointments.
25. Show missed appointments.
26. Show pending payments.
27. Show busiest department.
28. Show patient satisfaction score.
29. Show monthly revenue.
30. I'm really nervous about this procedure.
31. I have been waiting 3 weeks and nobody called me back. I am extremely upset.
32. hi i ned too bbok an appintmnet fo nxt weeek fore my teeths
```

---

*Powered by Tabor Synergy · admin@tabor.taborsynergy.com*
