# 🚀 Zapier Video Automation — Setup Instructions

**Your Email:** write2dinakar10@gmail.com  
**Project:** Tabor Synergy AI Medical Front Desk  
**Goal:** Automate script → voice-over audio generation  

---

## STEP 1: Enable Google Cloud APIs (5 minutes)

### 1.1 Create Google Cloud Project
- Go to: https://console.cloud.google.com
- Click "Select a Project" (top-left)
- Click "NEW PROJECT"
- Name: `Tabor-Video-Automation`
- Click "CREATE"
- Wait for project to be created (~1 min)

### 1.2 Enable Text-to-Speech API
- In search bar (top), type: `text-to-speech`
- Click "Text-to-Speech API"
- Click "ENABLE"
- Wait for activation (~30 seconds)

### 1.3 Enable Google Drive API
- In search bar, type: `google drive api`
- Click "Google Drive API"
- Click "ENABLE"
- Wait for activation

### 1.4 Create Service Account
- Left menu → "Service Accounts"
- Click "CREATE SERVICE ACCOUNT"
- Service account name: `zapier-video-automation`
- Service account ID: (auto-filled, keep it)
- Description: `Zapier integration for video generation`
- Click "CREATE AND CONTINUE"
- Grant role: `Editor` (from dropdown)
- Click "CONTINUE" → "DONE"

### 1.5 Create & Download JSON Key
- In Service Accounts list, click the account you just created
- Go to "KEYS" tab
- Click "ADD KEY" → "Create new key"
- Choose "JSON"
- Click "CREATE"
- JSON file downloads automatically
- **SAVE THIS FILE SAFELY** — you'll need it for Zapier

---

## STEP 2: Create Zapier Zap (15 minutes)

### 2.1 Sign Into Zapier
- Go to: https://zapier.com
- Log in (create account if needed)
- Click "Create" → "Make a Zap"

### 2.2 Set Trigger (Webhook)
- **Trigger App:** Search "Webhooks by Zapier"
- **Trigger Event:** "Catch Raw Hook"
- Click "Continue"
- **Webhook URL** will appear — **COPY THIS** and save it
- Click "Continue"

### 2.3 Test Webhook Trigger
- You'll see: "We're waiting on you to send data"
- Copy the webhook URL
- Open your terminal/command prompt
- Paste this command (replace WEBHOOK_URL):

```bash
curl -X POST WEBHOOK_URL \
  -H "Content-Type: application/json" \
  -d '{
    "script": "Hi! I am Dinakar from Tabor Synergy. This is a test.",
    "voice": "en-US-Neural2-A",
    "email": "write2dinakar10@gmail.com"
  }'
```

- Click "Test trigger"
- Should show: "We found 1 request"
- Click "Continue"

### 2.4 Add Action: Google Cloud Text-to-Speech
- Click "Add an action"
- Search: `google cloud text-to-speech`
- Click it
- **Authentication:**
  - Click "Connect"
  - Choose "Service Account"
  - Upload the JSON key file you saved from Step 1.5
  - Click "Yes, continue"

### 2.5 Configure TTS Settings
- **Input Text:** Click field → choose `script` from dropdown
- **Language Code:** `en-US`
- **Voice Name:** `en-US-Neural2-A` (professional, natural)
- **Speaking Rate:** `1.0`
- **Audio Encoding:** `MP3`
- Click "Continue"

### 2.6 Test TTS Action
- Click "Test this step"
- Should generate audio successfully
- Look for output: "Audio Content"
- Click "Continue"

### 2.7 Add Action: Google Drive - Upload File
- Click "Add an action"
- Search: `google drive`
- Choose "Google Drive"
- **Event:** "Upload File"
- **Authentication:** Use your personal Google account
- Click "Continue"

### 2.8 Configure Drive Upload
- **File:** Click field → choose "Audio Content" from TTS output
- **Filename:** `tabor_demo_{{Unix Timestamp}}_voice.mp3`
- **Parent Folder ID:** 
  - Go to Google Drive → Create folder "Tabor Video Assets"
  - Right-click folder → "Get link"
  - Copy the folder ID from URL: `https://drive.google.com/drive/folders/FOLDER_ID`
  - Paste folder ID here
- Click "Continue"

### 2.9 Test Drive Upload
- Click "Test this step"
- Should show: "File uploaded successfully"
- Go to Google Drive → Verify file is in "Tabor Video Assets" folder
- Click "Continue"

### 2.10 Add Final Action: Gmail Notification
- Click "Add an action"
- Search: `gmail`
- Choose "Gmail"
- **Event:** "Send Email"
- **Authentication:** Your Gmail (write2dinakar10@gmail.com)
- Click "Continue"

### 2.11 Configure Gmail Notification
- **To:** `write2dinakar10@gmail.com`
- **Subject:** `✅ Your Video Audio is Ready — Next: Create Slides`
- **Body:** Paste this:

```
Hi Dinakar,

Your voice-over audio has been generated and saved to Google Drive!

📁 Folder: Tabor Video Assets
🎙️ File: tabor_demo_[timestamp]_voice.mp3

NEXT STEP (5 minutes of manual work):
1. Create 5 slides in Canva with script key points
2. Export slides as MP4
3. Download the MP3 audio from Google Drive
4. Open CapCut (free app)
5. Import Canva MP4 + Google Drive MP3
6. Sync audio to slides
7. Export final video as MP4
8. Upload to Loom (free)
9. Share Loom link for cold emails

Ready? Start with Canva!

— Tabor Video Automation
```

- Click "Continue"

### 2.12 Test Gmail
- Click "Test this step"
- Check your Gmail inbox (write2dinakar10@gmail.com)
- Should receive test email
- Click "Continue"

### 2.13 Turn On Zap
- Review all steps (scroll up)
- Click "Publish" (top-right)
- Zap is now LIVE and ready to use!

---

## STEP 3: Use the Automation

### 3.1 Submit Script to Generate Audio

**Option A: Using cURL (Command Line)**
```bash
curl -X POST YOUR_WEBHOOK_URL \
  -H "Content-Type: application/json" \
  -d '{
    "script": "Hi! I am Dinakar from Tabor Synergy. I built an AI front desk for medical clinics...",
    "voice": "en-US-Neural2-A",
    "email": "write2dinakar10@gmail.com"
  }'
```

**Option B: Simple Webhook Tester**
- Go to: https://webhook.site
- Create new unique URL
- Use in Zapier step 2.2 instead
- Paste JSON into "Raw body"
- Click "Send"

### 3.2 Wait for Automation
- Takes 2-3 minutes
- Check email at write2dinakar10@gmail.com
- Notification arrives when audio is ready

### 3.3 Download Audio
- Go to Google Drive
- Folder: "Tabor Video Assets"
- Download MP3 file

### 3.4 Create Video (5 min manual work)

**Step A: Create Slides (2 min)**
1. Go to canva.com
2. Create → Video (1280x720)
3. Add 5 slides:
   - Slide 1: "AI Medical Front Desk"
   - Slide 2: "The Problem" (40% calls missed)
   - Slide 3: "The Solution" (Aria features)
   - Slide 4: "Live Demo"
   - Slide 5: "Start Free Trial"
4. Use brand colors: #1E40AF (blue), #059669 (green)
5. Export as MP4

**Step B: Combine Audio + Video (3 min)**
1. Download CapCut (free, capcut.com)
2. Open CapCut → New project
3. Import:
   - Canva MP4 (slides)
   - Google Drive MP3 (audio)
4. Drag audio to timeline
5. Sync audio timing to slides
6. Export as MP4 (1080p)

**Step C: Upload to Loom**
1. Go to loom.com
2. Upload your MP4
3. Get share link: `loom.com/share/xxxxx`

### 3.5 Use Video in Cold Email
- Replace `[VIDEO LINK]` in Email 2 template
- Paste Loom link
- Send to 50 prospects

---

## TROUBLESHOOTING

### ❌ "Permission Denied" when uploading to Drive
**Fix:**
- Go to Google Cloud Console
- Service Accounts → Your account
- Roles → Click pencil → Make sure "Editor" is selected
- Or create new JSON key

### ❌ "Webhook not found"
**Fix:**
- Copy webhook URL correctly from Zapier Step 2.2
- Test with curl command exactly as shown
- Check for typos in JSON

### ❌ "Audio sounds robotic"
**Fix:**
- Change voice to: `en-US-Neural2-C`
- Reduce speaking rate to: `0.9`
- Break script into shorter paragraphs

### ❌ "Gmail not receiving notification"
**Fix:**
- Verify Gmail is authenticated in Zapier
- Check spam folder
- Re-test the Gmail action in Zapier

---

## QUICK REFERENCE

| Item | Value |
|------|-------|
| **Email** | write2dinakar10@gmail.com |
| **Google Cloud Project** | Tabor-Video-Automation |
| **Service Account** | zapier-video-automation |
| **TTS Voice** | en-US-Neural2-A |
| **Google Drive Folder** | Tabor Video Assets |
| **Zapier Zap Name** | Tabor Video Generator |
| **Output Format** | MP3 (audio) + MP4 (video) |

---

## NEXT STEPS AFTER SETUP

1. ✅ Setup complete (you're here)
2. ⏳ Test with sample script (5 min)
3. 🎙️ Generate real demo video (15 min)
4. 📧 Use in Email 2 of cold campaign
5. 📊 Track reply rates (Email 2 should be highest)

---

## SUPPORT

If you get stuck:
1. Check the troubleshooting section above
2. Review Zapier step numbers
3. Test each action individually before moving to next
4. Watch Zapier's built-in tutorials (click "?" icon)

**Setup time: 30 minutes**  
**Per video: 15 minutes**  
**Cost: $0**

Good luck! 🚀