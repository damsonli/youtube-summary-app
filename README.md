# YouTube Video Analyzer

A containerized application that analyzes YouTube videos and channels using AI-powered summaries, with email notification support for channel subscriptions.

## Features

### 📹 Video Analysis
- **Single Video Analysis**: Paste a YouTube video URL and get an AI-generated summary
- **Channel Analysis**: Analyze multiple videos from a channel with filtering options
- **Smart Summary Distribution**: AI summaries for top videos, basic info for others
- **Transcript Detection**: Automatic extraction of video transcripts for higher quality AI summaries
- **Real-time Progress**: Streaming updates during analysis

### 📧 Email Notifications
- **Channel Subscriptions**: Subscribe to YouTube channels with email notifications
- **Daily Updates**: Automatic emails with today's new videos
- **Timezone Support**: Schedule times in your local timezone
- **Smart Filtering**: Only today's videos with efficient AI usage
- **Transcript Indicators**: Visual indicators show when AI summaries use video transcripts

### 🛠️ Technical Features
- **Multiple LLM Services**: Support for Ollama (self-hosted) and OpenAI (cloud) 
- **Flexible AI Processing**: Choose between local Ollama or cloud-based OpenAI
- **Real-time Service Status**: Frontend displays which LLM service is active, connection status, and service details
- **Service Status Indicators**: Visual icons (🏠 Ollama, ☁️ OpenAI) with color-coded connection status
- **Fully Containerized**: Easy deployment with Docker
- **Modern UI**: React frontend with Tailwind CSS
- **FastAPI Backend**: High-performance async API
- **Data Persistence**: JSON-based storage for subscriptions

## Quick Start

### 1. Initial Setup

Copy the environment template and configure:
```bash
cp .env.template .env
```

Edit `.env` with your settings:
```env
# LLM Service Configuration
LLM_SERVICE=ollama  # Choose: ollama, openai

# Ollama Configuration (if using ollama)
OLLAMA_HOST=http://your-ollama-server:11434
OLLAMA_MODEL=llama3.2

# OpenAI Configuration (if using openai)
# OPENAI_API_KEY=your-openai-api-key-here
# OPENAI_MODEL=gpt-4o-mini

# Email Configuration (optional, for subscriptions)
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
EMAIL_USER=your-email@gmail.com
EMAIL_PASSWORD=your-app-password
FROM_EMAIL=your-email@gmail.com

# Timezone and Schedule
TIMEZONE=America/New_York
SCHEDULE_TIME=09:00
```

### 2. Deploy with Docker

```bash
docker-compose up -d
```

### 3. Access the Application

- **Frontend**: http://localhost
- **Backend API**: http://localhost:8000

## Email Notification System

### Overview

The email notification system automatically checks subscribed YouTube channels and sends daily updates with new videos.

### How It Works

**When emails are sent:**
- Daily at your configured time (default: 9:00 AM in your timezone)
- Only when new videos are found
- One consolidated email per user with all subscribed channels

**What videos are included:**
- **Today's videos only** - based on your local timezone
- **Smart summary distribution**:
  - **First 3 videos per channel**: Full AI-generated summaries
  - **Remaining videos**: Basic info (title, duration, thumbnail)
- **Visual indicators**:
  - `🤖📜` = AI summary based on video transcript (highest quality)
  - `🤖` = AI summary based on title/description only
  - `📌` = Basic info (no AI summary)

**Email content:**
- Subject: "YouTube Updates: X new videos"
- Plain text and HTML versions
- Grouped by channel for easy reading
- Direct links to videos and channels

### Email Configuration

#### Gmail Setup (Recommended)

1. **Enable 2-Factor Authentication** on your Gmail account
2. **Generate an App Password**:
   - Go to Gmail Settings → Security
   - Generate an "App Password" for "Mail"
   - Use this password in `EMAIL_PASSWORD`

#### Other Email Providers

**Outlook/Hotmail:**
```env
SMTP_SERVER=smtp-mail.outlook.com
SMTP_PORT=587
```

**Yahoo:**
```env
SMTP_SERVER=smtp.mail.yahoo.com
SMTP_PORT=587
```

### Timezone Configuration

Schedule times and "today" calculations use your local timezone:

```env
# Your timezone (affects schedule times and "today" calculation)
TIMEZONE=America/New_York
SCHEDULE_TIME=09:00

# Multiple daily checks
SCHEDULE_TIMES=09:00,18:00
```

**Common timezone examples:**
- `UTC` - Coordinated Universal Time
- `America/New_York` - Eastern Time (EST/EDT)
- `America/Los_Angeles` - Pacific Time (PST/PDT)
- `Europe/London` - GMT/BST
- `Asia/Tokyo` - Japan Standard Time

**Important:**
- **Schedule times** are interpreted in your **local timezone**
- **"Today's videos"** are calculated based on your **local date**
- **Email timestamps** show your **local timezone**

## LLM Service Configuration

### Overview

The application supports multiple LLM services for generating AI summaries. You can choose between self-hosted Ollama or cloud-based OpenAI.

### Supported Services

#### 🏠 Ollama (Self-Hosted)
**Best for: Privacy, cost control, custom models**

```env
LLM_SERVICE=ollama
OLLAMA_HOST=http://your-ollama-server:11434
OLLAMA_MODEL=llama3.2
```

**Setup Requirements:**
- Run Ollama server on local network or remote server
- Install desired models (e.g., `ollama pull llama3.2`)
- No API costs or usage limits

#### ☁️ OpenAI (Cloud)
**Best for: Ease of use, high quality, no infrastructure**

```env
LLM_SERVICE=openai
OPENAI_API_KEY=your-openai-api-key-here
OPENAI_MODEL=gpt-4o-mini
```

**Setup Requirements:**
- OpenAI account with API access
- Generate API key from OpenAI dashboard
- Pay-per-use pricing

### Error Handling

The application includes comprehensive error handling:
- **Invalid service name**: Clear error message with supported options
- **Missing API key**: Specific error for OpenAI configuration
- **Network issues**: Graceful fallback with basic video info
- **Service unavailable**: Detailed error messages for troubleshooting

### Adding Other Services

The architecture supports easy addition of other LLM services. To add support for new services (e.g., Anthropic Claude, Google Gemini):

1. Create a new client class implementing `BaseLLMClient`
2. Add service detection in `LLMClient._initialize_client()`
3. Update environment template and documentation
4. Add required dependencies to `requirements.txt`

**Example structure for new services:**
```python
class AnthropicClient(BaseLLMClient):
    def __init__(self, api_key: str, model_name: str = "claude-3-haiku-20240307"):
        # Implementation here
    
    async def generate_summary(self, video_info: Dict) -> str:
        # Service-specific implementation
    
    async def check_connection(self) -> bool:
        # Connection check implementation
```

## Development

### Backend Development
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload
```

### Frontend Development
```bash
cd frontend
npm install
npm run dev
```

### Manual Testing
```bash
# Test email notifications once
cd backend
python scheduler.py --run-once

# Run scheduler daemon
python scheduler.py --daemon
```

## API Endpoints

### Video Analysis
- `POST /analyze/video/stream` - Stream video analysis with progress
- `POST /analyze/video` - Analyze single video
- `POST /analyze/channel/stream` - Stream channel analysis with progress
- `POST /analyze/channel` - Analyze channel videos

### Subscription Management
- `POST /subscriptions` - Create new subscription
- `GET /subscriptions` - Get all subscriptions
- `GET /subscriptions/email/{email}` - Get subscriptions by email
- `DELETE /subscriptions/{id}` - Delete subscription
- `POST /check-subscriptions` - Trigger manual check

### System
- `GET /` - API health check
- `GET /test-stream` - Test streaming functionality

## Data Storage

### Data Directory (`./data/`)

This directory contains persistent application data that is **not tracked by git**:

- `subscriptions.json` - User subscription data (emails, channels, timestamps)

**Docker Usage:**
```yaml
volumes:
  - ./data:/app/data
```

**Important:**
- **Do not commit** JSON files to git (already excluded in .gitignore)
- **Backup regularly** if running in production
- **Shared between** backend and scheduler containers

## Subscription Management

### Email-Based Features
- **Duplicate prevention**: Can't subscribe to same channel twice with same email
- **Email grouping**: All subscriptions for an email get processed together
- **Individual unsubscribe**: Remove specific channel subscriptions
- **Bulk management**: View all subscriptions by email

### Subscription Workflow
1. User provides **email + channel URL + channel name**
2. System checks for **duplicates**
3. **Stores subscription** with timestamp
4. **Daily checker** finds new videos from today
5. **Sends consolidated email** with all new videos

## Architecture

### Container Structure
- **backend**: FastAPI server + Background scheduler daemon
- **frontend**: React app served by nginx

### Background Services
- **Scheduler**: Runs daily checks at configured times
- **Background Checker**: Processes subscriptions and sends emails
- **Email System**: HTML/plain text emails with SMTP support

### Dependencies
- **Python**: FastAPI, yt-dlp, schedule, pytz, ollama
- **Node.js**: React, Vite, Tailwind CSS
- **External**: Ollama server for AI summaries

## Requirements

- Docker & Docker Compose
- Remote Ollama server with a model (e.g., llama3.2)
- Internet connection for YouTube access
- SMTP email account (for notifications)

## Troubleshooting

### No emails received
1. Check email credentials in `.env`
2. Verify SMTP settings for your provider
3. Check spam folder
4. Run manual test: `python scheduler.py --run-once`

### Authentication errors
- Gmail: Use App Password, not regular password
- Enable "Less secure apps" if needed (not recommended)
- Check 2FA is enabled and App Password is generated

### Missing videos
- Check subscription `last_checked` timestamp
- Videos must be from today (in your timezone)
- Maximum processing: All of today's videos per channel

### Docker issues
- Ensure `.env` file exists and is configured
- Check container logs: `docker-compose logs backend`
- Verify Ollama server is accessible

## Security Notes

- **Never commit `.env` file** to version control
- **Use App Passwords** instead of regular passwords
- **Rotate credentials** periodically
- **Limit email rate** to avoid being marked as spam
- **Backup subscription data** regularly

## License

This project is for educational and personal use.