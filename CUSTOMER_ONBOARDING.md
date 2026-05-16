# Tabor Synergy — Customer Onboarding Guide
**AI-Powered Medical Front Desk · Trial Edition**

> This guide walks you through everything from the moment you start your free trial
> to the moment your first patient chats with Aria.

---

## Quick Reference

| | Doctor / Admin | Patient |
|---|---|---|
| **URL** | `/c/your-clinic-slug` | `/chat/your-clinic-slug` |
| **Login needed?** | Yes — email + password | No — open and chat instantly |
| **What they see** | 3-tab clinic portal | Aria chat welcome page |
| **Support** | admin@tabor.taborsynergy.com | Your clinic's phone / email |

---

---

# PART 1 — DOCTOR / ADMIN ONBOARDING

## Step 1 — Start Your Free Trial

1. Go to **https://taborsynergy-agent.onrender.com/**
2. Click **"Start 14-Day Free Trial →"** on any pricing card
3. Fill in the signup form:

| Field | Example |
|---|---|
| Practice Name | Sunrise Dental Care |
| Contact Email | dr.smith@sunrisedental.com |
| Password | (choose something secure, min 6 chars) |
| Specialty | Dentistry |
| Phone | (512) 555-0199 |
| Plan | Growth — $597/mo |

4. Click **"Start My Free Trial →"**
5. You will see a **Success screen** with:
   - Your personal Aria URL (e.g. `…/c/sunrise-dental-a1b2c`)
   - A PayPal button to activate your paid plan when ready
   - A button to open your clinic portal

> **What happens behind the scenes:**
> - Your clinic is created instantly in the system
> - Tabor Synergy admin receives an email with your details
> - Your 14-day free trial starts immediately — no credit card needed

---

## Step 2 — Log In to Your Clinic Portal

1. Open your clinic portal URL: `https://taborsynergy-agent.onrender.com/c/your-slug`
2. Enter your **email** and **password** from signup
3. Click **Sign In →**
4. You land on your **Clinic Dashboard** with 3 tabs

> Forgot your URL? Email **admin@tabor.taborsynergy.com** — we'll send it to you within the hour.

---

## Step 3 — Explore Your 3-Tab Dashboard

### Tab 1 — Share with Patients

This is the most important tab. It gives you everything you need to put Aria in front of your patients.

**Patient Chat Link**
```
https://taborsynergy-agent.onrender.com/chat/your-slug
```
- Click **Copy Link** — paste it anywhere
- A **QR code** is auto-generated — print it and place it at your front desk, waiting room, and appointment reminder cards
- Patients open the link → Aria is ready instantly — **no login, no app, no account**

**How to share with patients:**

| Channel | What to do |
|---|---|
| SMS / Text | Copy the link → paste into a text message to your patients |
| WhatsApp | Send the link in your patient WhatsApp group or broadcast list |
| Email | Add the link to your appointment confirmation emails and newsletters |
| Website | Use the embed code (Tab 3) to add a chat bubble to your website |
| Waiting room | Print the QR code → frame it at reception |
| Instagram / Facebook | Put the link in your bio or pinned post |

**Ready-to-send patient message (copy and send as-is):**
```
Hi [Patient Name]!

You can now chat with our AI front desk assistant Aria at [Clinic Name] — 
24 hours a day, 7 days a week.

Book appointments, check insurance, ask billing questions, and more:
[Your Patient Chat Link]

Reply STOP to opt out.
```

---

### Tab 2 — Try Aria (Test Before You Share)

Before sending the link to patients, test Aria yourself to see exactly what your patients will experience.

**Recommended test prompts to try:**

| What to type | What Aria should do |
|---|---|
| `I want to book an appointment tomorrow` | Ask your name, DOB, insurance, preferred time → book it |
| `I am a new patient` | Collect full intake information |
| `Does Blue Cross cover my visit?` | Ask member ID → verify coverage → explain in plain language |
| `Why is my bill $350?` | Verify identity first → show invoice breakdown → offer payment link |
| `I want to cancel my appointment` | Confirm cancellation, mention policy, offer to rebook |
| `My father has chest pain` | Immediately say "Call 911" — no appointment attempt |
| `I want to speak to a real person` | Escalate to your staff contact instantly |

> If anything doesn't look right, email **admin@tabor.taborsynergy.com** — we'll adjust your configuration within 1 business day.

---

### Tab 3 — Embed on Your Website

Paste this snippet just before `</body>` on your website. A floating Aria chat bubble appears on every page automatically.

```html
<!-- Tabor Synergy — Your Clinic AI Chat -->
<script>
  window.ARIA_CLINIC_SLUG = "your-clinic-slug";
</script>
<script src="https://taborsynergy-agent.onrender.com/widget.js" async></script>
```

Works on: **WordPress, Wix, Squarespace, Webflow, custom HTML** — no developer needed.

---

## Step 4 — What Aria Knows About Your Clinic

During the trial, Aria is pre-configured with your:
- **Practice name and specialty** (from your signup form)
- **Contact email and phone** (from signup)
- **Standard hours and policies** (default — customizable)
- **Insurance list** (default — customizable)
- **Escalation workflow** (emergency → 911 first, complex → your contact)

**To customise your configuration**, email us at **admin@tabor.taborsynergy.com** with:

| What to update | Example |
|---|---|
| Office hours | Mon–Fri 8am–6pm, Sat 9am–1pm |
| Providers / doctors | Dr. Sarah Chen (DDS), Dr. James Rivera (DMD) |
| Insurance accepted | Aetna, BCBS, Delta Dental, MetLife |
| Cancellation policy | 48-hour notice, $75 fee |
| After-hours message | "Call our emergency line at (512) 555-0199" |
| Services offered | Root canals, cleanings, Invisalign, whitening |

---

## Step 5 — Admin Analytics (Ask Aria Directly)

While logged in, you can ask Aria about your clinic's performance:

```
Show today's appointments.
Show missed appointments.
Show pending payments.
Show patient satisfaction score.
Show monthly revenue.
Show busiest department.
```

Aria returns realistic simulated data during the trial period.

---

## Step 6 — Daily Admin Checklist

Ask Aria these every morning to stay on top of your practice:

```
1. Show today's appointments.
2. Which patients haven't confirmed tomorrow's appointments?
3. Show pending payments from this week.
4. Show any no-shows from yesterday.
5. Are there any patients on the waitlist?
```

---

## Step 7 — Activate Your Paid Plan

When your 14-day trial ends and you're ready to go live:

1. Click the **PayPal button** from your success screen (or email us for invoice/wire transfer)
2. Pay your selected plan amount:
   - Starter: **$297/mo**
   - Growth: **$597/mo**
   - Pro: **$997/mo**
3. Email **admin@tabor.taborsynergy.com** with your payment confirmation
4. We activate your account within **1 business day**
5. Your clinic continues running without any interruption

---

## Admin FAQ

**Q: Can I change my password?**
Email admin@tabor.taborsynergy.com — we'll reset it for you.

**Q: Can I have multiple staff members log in?**
Currently one login per clinic. Multi-user access is available on the Pro plan.

**Q: What happens when my trial expires?**
Aria will inform patients that the service is temporarily paused and display your contact number. Your data is preserved for 30 days.

**Q: Can patients book real appointments in the system?**
During trial, Aria simulates bookings. Full EHR/PMS integration (Epic, Dentrix, Athenahealth) is available on the Pro plan.

**Q: How do I add my logo and custom branding?**
White Label and custom branding available on the Pro plan. Email us to discuss.

---

---

# PART 2 — PATIENT ONBOARDING

> Share this section directly with your patients — print it, text it, or email it.

---

## Welcome to Aria — Your 24/7 AI Front Desk

Hi! Aria is the AI assistant for **[Your Clinic Name]**. You can chat with Aria any time — day or night — without calling the front desk or waiting on hold.

**Open your chat here:** `https://taborsynergy-agent.onrender.com/chat/your-slug`

No app to download. No account to create. Just open the link and start chatting.

---

## What Can You Ask Aria?

### Book or Change Appointments
```
I want to book an appointment.
I need to see a doctor this week.
Can I get an appointment for tomorrow morning?
I need to reschedule my Monday appointment to Wednesday.
I need to cancel my appointment.
```

### New Patient Registration
```
I am a new patient.
I just moved to the area and need a new doctor.
I need to fill out new patient forms.
```

### Insurance Questions
```
Do you accept Blue Cross Blue Shield?
What is my copay for a specialist visit?
Can you verify my Aetna insurance before my appointment?
I don't have insurance — what are my options?
```

### Billing & Payments
```
I have a question about my bill.
Why is my bill $350?
I want to pay my outstanding balance.
Can I get a payment plan?
Send me a payment link to my email.
```

### Follow-up Appointments
```
My doctor asked me to come back in 2 weeks.
I need a follow-up with Dr. Chen.
I had blood work done and need to discuss results.
```

### General Questions
```
What are your office hours?
Where is the clinic located?
What insurance do you accept?
How do I get my medical records?
```

---

## Specialty Prompts

### Dental
```
I need a root canal consultation.
I have a toothache — can I get seen today?
I want information about Invisalign.
My child needs a dental check-up.
```

### Dermatology
```
I need to get a mole checked.
I need treatment for acne.
I have a rash that won't go away.
```

### Pediatrics
```
My child needs a vaccination.
I need to book a well-child visit.
My baby has a fever — can I get a same-day appointment?
```

### Orthopedics
```
I have knee pain and it's getting worse.
I injured my shoulder playing sports.
I need to see someone about my back pain.
```

### OB-GYN
```
I need a prenatal consultation.
I need to schedule my annual exam.
```

### ENT
```
I have severe ear pain.
I've had a sinus infection for 2 weeks.
```

### Eye Care
```
I need an eye exam.
I need an eye pressure check for glaucoma.
```

### Urgent Care
```
I cut my hand and it won't stop bleeding.
I think I sprained my ankle.
I have a high fever and body aches.
```

### Family Medicine
```
I need a general health check-up.
I need a referral to a specialist.
```

---

## In an Emergency

If it is a life-threatening emergency, type:
```
My father has chest pain and cannot breathe.
```
Aria will immediately tell you to **call 911** and alert clinic staff. Do not wait — call 911 directly for any life-threatening situation.

---

## Your Privacy Is Protected

- Aria will **never share your medical information** without verifying your identity first
- You will always be asked for your **name + date of birth + last 4 digits of SSN** before any personal data is discussed
- All conversations are **HIPAA-compliant**
- Aria will **never** guess a diagnosis or recommend medication

---

## Need a Real Person?

Type:
```
I want to speak to a real person.
```
Aria will connect you to a staff member immediately.

Or call us directly: **[Your Clinic Phone Number]**

---

## Patient FAQ

**Q: Do I need to create an account?**
No. Just open the chat link and start talking.

**Q: Is this available 24/7?**
Yes. Aria never sleeps, never puts you on hold, and is available every day of the year.

**Q: Can Aria book a real appointment?**
Yes — Aria confirms your appointment details and logs it in our system. You'll receive a confirmation message.

**Q: What if Aria can't answer my question?**
Aria will escalate to a human staff member or provide the clinic's direct phone number.

**Q: Is my information safe?**
Yes. Aria is HIPAA-compliant. Your information is never shared without identity verification.

---

*Powered by Tabor Synergy · admin@tabor.taborsynergy.com*
*For clinic setup and support: admin@tabor.taborsynergy.com*
