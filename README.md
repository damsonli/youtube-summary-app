# YouTube Video Analyzer

A containerized application that analyzes YouTube videos and channels using AI-powered summaries, with email notification support for channel subscriptions.

## Features

### 📹 Video Analysis
- **Single Video Analysis**: Analyze any YouTube video URL with AI-generated summaries
- **Channel Analysis**: Analyze multiple videos from a channel (3-15 videos configurable)
- **Smart Summary Distribution**: AI summaries for top videos, basic info for others to optimize costs
- **Advanced Transcript Extraction**: Multi-language subtitle support with automatic fallbacks
- **Real-time Progress**: Streaming updates during analysis with EventSource API
- **Responsive Design**: Mobile-first UI with adaptive layouts

### 📧 Email Notifications
- **Channel Subscriptions**: Subscribe to YouTube channels with email notifications
- **Smart Daily Updates**: Automatic emails with new videos since last check
- **Timezone-Aware Scheduling**: Configure times in your local timezone
- **Intelligent Filtering**: Only process videos uploaded since last check
- **Visual Content Indicators**: Clear distinctions between AI summaries and basic info
- **Consolidated Emails**: One email per user containing all channel updates

### 🛠️ Technical Features
- **Multi-LLM Architecture**: Support for Ollama (self-hosted) and OpenAI (cloud)
- **Real-time Service Monitoring**: Frontend displays active LLM service and connection status
- **Service Status Indicators**: Visual icons (🏠 Ollama, ☁️ OpenAI) with live health checks
- **Streaming API**: Real-time progress updates using Server-Sent Events
- **Comprehensive Error Handling**: Graceful fallbacks and detailed error reporting
- **Containerized Deployment**: Full Docker Compose setup with volume persistence
- **Modern Tech Stack**: React 18, FastAPI, Tailwind CSS, Python 3.13
- **JSON Data Persistence**: Simple, reliable storage with atomic operations

## Quick Start

### 1. Initial Setup

Create your environment configuration:
```bash
# Create .env file from this template
cat > .env << 'EOF'
# LLM Service Configuration - Choose your AI service
LLM_SERVICE=ollama  # Options: ollama, openai

# Ollama Configuration (if using ollama)
OLLAMA_HOST=http://your-ollama-server:11434
OLLAMA_MODEL=llama3.2

# OpenAI Configuration (if using openai)
# OPENAI_API_KEY=your-openai-api-key-here
# OPENAI_MODEL=gpt-4o-mini

# Email Configuration (required for subscriptions)
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
EMAIL_USER=your-email@gmail.com
EMAIL_PASSWORD=your-app-password
FROM_EMAIL=your-email@gmail.com

# Scheduling Configuration
TIMEZONE=America/New_York
SCHEDULE_TIME=09:00
# Optional: Multiple check times (comma-separated)
# SCHEDULE_TIMES=09:00,18:00
EOF
```

### 2. Deploy with Docker

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

### 3. Access the Application

- **Frontend Interface**: http://localhost
- **Backend API Documentation**: http://localhost:8000/docs
- **API Health Check**: http://localhost:8000

## Email Notification System

### Overview

The email notification system runs as a background scheduler daemon that automatically checks subscribed YouTube channels and sends consolidated daily updates with new videos.

### How It Works

**When emails are sent:**
- At your configured schedule time(s) daily
- Only when new videos are found since last check
- One consolidated email per subscriber containing all channel updates
- Uses timezone-aware scheduling for accurate local time processing

**Content Strategy:**
- **Videos since last check** - not just "today's" videos for better coverage
- **Smart AI usage**:
  - **First 3 videos per channel**: Full AI-generated summaries with transcripts when available
  - **Remaining videos**: Basic metadata (title, duration, thumbnail) to save API costs
- **Visual indicators**:
  - `🤖📜` = AI summary using video transcript (highest quality)
  - `🤖` = AI summary using title/description only
  - `📌` = Basic info only (no AI processing)

**Email Features:**
- HTML and plain text versions for compatibility
- Channel grouping for organized reading
- Direct YouTube links for easy access
- Timezone-aware timestamps
- Professional formatting with responsive design

### Email Configuration

#### Gmail Setup (Recommended)

1. **Enable 2-Factor Authentication** on your Gmail account
2. **Generate an App Password**:
   - Go to Gmail Settings → Security
   - Under "2-Step Verification", select "App passwords"
   - Generate password for "Mail"
   - Use this 16-character password in `EMAIL_PASSWORD`

#### Other Email Providers

**Outlook/Hotmail:**
```env
SMTP_SERVER=smtp-mail.outlook.com
SMTP_PORT=587
```

**Yahoo Mail:**
```env
SMTP_SERVER=smtp.mail.yahoo.com
SMTP_PORT=587
```

**Custom SMTP:**
```env
SMTP_SERVER=your-smtp-server.com
SMTP_PORT=587  # or 465 for SSL
```

### Timezone Configuration

All scheduling and date calculations respect your configured timezone:

```env
# Your local timezone (affects all time calculations)
TIMEZONE=America/New_York
SCHEDULE_TIME=09:00

# Multiple daily checks (optional)
SCHEDULE_TIMES=09:00,18:00
```

**Common timezone examples:**
- `UTC` - Coordinated Universal Time
- `America/New_York` - Eastern Time (EST/EDT)
- `America/Los_Angeles` - Pacific Time (PST/PDT)
- `America/Chicago` - Central Time (CST/CDT)
- `Europe/London` - GMT/BST
- `Europe/Paris` - CET/CEST
- `Asia/Tokyo` - Japan Standard Time
- `Australia/Sydney` - AEST/AEDT

**Important Notes:**
- **Schedule times** are interpreted in your local timezone
- **Video filtering** considers your local date for "new" videos
- **Email timestamps** display in your configured timezone

## LLM Service Configuration

### Overview

The application supports multiple Large Language Model services for generating AI summaries. Choose between self-hosted Ollama for privacy and cost control, or cloud-based OpenAI for ease of use and high quality.

### Supported Services

#### 🏠 Ollama (Self-Hosted)
**Best for: Privacy, cost control, custom models, unlimited usage**

```env
LLM_SERVICE=ollama
OLLAMA_HOST=http://your-ollama-server:11434
OLLAMA_MODEL=llama3.2
```

**Setup Requirements:**
- Ollama server running on local network or remote server
- Downloaded models (e.g., `ollama pull llama3.2`, `ollama pull llama3.1:8b`)
- No API costs or usage limits
- Complete data privacy

**Popular Models:**
- `llama3.2` - Latest Llama model, good balance of speed and quality
- `llama3.1:8b` - Larger model for better quality
- `mistral` - Alternative model with good performance
- `codellama` - Specialized for code analysis

#### ☁️ OpenAI (Cloud)
**Best for: Ease of use, high quality, no infrastructure management**

```env
LLM_SERVICE=openai
OPENAI_API_KEY=your-openai-api-key-here
OPENAI_MODEL=gpt-4o-mini
```

**Setup Requirements:**
- OpenAI account with API access
- API key from OpenAI dashboard (https://platform.openai.com/api-keys)
- Pay-per-use pricing (~$0.15-$0.60 per 1K tokens)

**Recommended Models:**
- `gpt-4o-mini` - Cost-effective, high quality (default)
- `gpt-4o` - Highest quality, more expensive
- `gpt-3.5-turbo` - Fastest, lowest cost

### Service Status Monitoring

The frontend displays real-time LLM service status:
- **Service Type**: Visual icons and names
- **Connection Status**: Live health checks with color coding
- **Configuration Details**: Model names, API key status, host information
- **Error Reporting**: Detailed troubleshooting information

**Connection Testing:**
- **Ollama**: Tests connection by listing available models
- **OpenAI**: Tests API key validity by calling models endpoint
- **No Token Usage**: Health checks are free and don't consume API credits

### Error Handling

Comprehensive error handling ensures reliability:
- **Invalid service configuration**: Clear setup instructions
- **Missing API credentials**: Specific guidance for each service
- **Network connectivity issues**: Graceful fallbacks to basic video info
- **Service unavailability**: Detailed error messages for troubleshooting
- **Rate limiting**: Automatic retry logic with exponential backoff

### Adding New LLM Services

The modular architecture supports easy addition of new services:

```python
# Example: Adding Anthropic Claude support
class AnthropicClient(BaseLLMClient):
    def __init__(self, api_key: str, model_name: str = "claude-3-haiku-20240307"):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model_name = model_name
    
    async def generate_summary(self, video_info: Dict) -> str:
        # Implementation using Anthropic API
        pass
    
    async def check_connection(self) -> bool:
        # Test Anthropic API connectivity
        pass
```

**Steps to add new services:**
1. Create client class implementing `BaseLLMClient`
2. Add service detection in `LLMClient._initialize_client()`
3. Update environment configuration
4. Add dependencies to `requirements.txt`
5. Update documentation

## API Reference

### Video Analysis Endpoints

**Stream Video Analysis** (Recommended)
```http
POST /analyze/video/stream
Content-Type: application/json

{
  "url": "https://www.youtube.com/watch?v=VIDEO_ID"
}
```
Returns: Server-Sent Events stream with progress updates and final result

**Single Video Analysis**
```http
POST /analyze/video
Content-Type: application/json

{
  "url": "https://www.youtube.com/watch?v=VIDEO_ID"
}
```
Returns: Complete analysis result

**Stream Channel Analysis**
```http
POST /analyze/channel/stream
Content-Type: application/json

{
  "url": "https://www.youtube.com/@channelname",
  "limit": 5
}
```
Returns: Server-Sent Events stream with progress updates

**Channel Analysis**
```http
POST /analyze/channel
Content-Type: application/json

{
  "url": "https://www.youtube.com/@channelname",
  "limit": 10
}
```
- `limit`: Number of videos to analyze (3-15, default: 5)

### Subscription Management

**Create Subscription**
```http
POST /subscriptions
Content-Type: application/json

{
  "channel_url": "https://www.youtube.com/@channelname",
  "channel_name": "Channel Display Name",
  "user_email": "user@example.com"
}
```

**Get All Subscriptions**
```http
GET /subscriptions
```

**Get User Subscriptions**
```http
GET /subscriptions/email/user@example.com
```

**Delete Subscription**
```http
DELETE /subscriptions/{subscription_id}
```

**Delete by Email and Channel**
```http
DELETE /subscriptions/email/{email}/channel?channel_url=ENCODED_URL
```

**Get Unique Emails**
```http
GET /subscriptions/emails
```

**Trigger Manual Check**
```http
POST /check-subscriptions
```

### System Endpoints

**Health Check**
```http
GET /
```

**LLM Service Status**
```http
GET /llm-service
```
Returns: Current service type, connection status, configuration details

**Test Streaming**
```http
GET /test-stream
```

## Development

### Backend Development

```bash
# Set up Python environment
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run development server
uvicorn main:app --reload --port 8000

# Run scheduler manually
python scheduler.py --run-once
python scheduler.py --daemon
```

### Frontend Development

```bash
# Set up Node.js environment
cd frontend
npm install

# Run development server (with API proxy)
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview
```

### Manual Testing

```bash
# Test single email notification
cd backend
python scheduler.py --run-once

# Test with specific timezone
TIMEZONE=Europe/London python scheduler.py --run-once

# Run background scheduler
python scheduler.py --daemon
```

### Development Tools

**API Documentation**: http://localhost:8000/docs (Swagger UI)
**Hot Reload**: Both frontend and backend support automatic reloading
**Debug Logging**: Comprehensive logging throughout the application
**Error Tracking**: Detailed error messages and stack traces

## Architecture

### System Overview

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Frontend      │    │    Backend      │    │   External      │
│   (React)       │◄──►│   (FastAPI)     │◄──►│   Services      │
│                 │    │                 │    │                 │
│ • Video UI      │    │ • REST API      │    │ • YouTube API   │
│ • Subscriptions │    │ • Streaming     │    │ • Ollama Server │
│ • Real-time     │    │ • Background    │    │ • OpenAI API    │
│   Progress      │    │   Scheduler     │    │ • SMTP Server   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
        │                        │                        │
        └────────────────────────┼────────────────────────┘
                                 │
                    ┌─────────────────┐
                    │   Data Layer    │
                    │                 │
                    │ • JSON Storage  │
                    │ • Docker Volume │
                    │ • Atomic Ops    │
                    └─────────────────┘
```

### Container Architecture

**Backend Container** (`backend/`)
- **Base**: Python 3.13-slim with ffmpeg
- **Services**: FastAPI server + Background scheduler daemon
- **Responsibilities**: 
  - REST API endpoints
  - YouTube data extraction
  - LLM service integration
  - Email notification system
  - Data persistence

**Frontend Container** (`frontend/`)
- **Build Stage**: Node.js for React compilation
- **Runtime Stage**: Nginx for static file serving
- **Features**:
  - Production-optimized React build
  - Gzip compression
  - API proxy configuration
  - Mobile-responsive design

### Technology Stack

**Backend Technologies:**
- `fastapi==0.116.1` - High-performance async API framework
- `uvicorn==0.35.0` - ASGI server with WebSocket support
- `yt-dlp==2025.7.21` - YouTube data extraction library
- `ollama==0.5.1` - Self-hosted LLM client
- `openai==1.97.0` - OpenAI API client
- `schedule==1.2.2` - Cron-like job scheduler
- `pytz==2025.2` - Timezone handling
- `requests==2.32.4` - HTTP client library

**Frontend Technologies:**
- `react==18.2.0` - Modern React framework
- `axios==1.6.0` - Promise-based HTTP client
- `react-markdown==9.0.0` - Markdown rendering with GitHub flavored markdown
- `tailwindcss==3.3.6` - Utility-first CSS framework
- `vite==5.0.8` - Fast build tool and dev server

### Data Flow

1. **User Input**: URL submission via React frontend
2. **API Request**: Axios HTTP client sends request to FastAPI
3. **Processing**: Backend extracts YouTube data via yt-dlp
4. **AI Analysis**: LLM service generates summaries (Ollama/OpenAI)
5. **Response**: Real-time progress via Server-Sent Events
6. **Display**: React components render results with markdown

### Background Services

**Scheduler Daemon:**
- Timezone-aware cron-like scheduling
- Multiple daily check support
- Graceful error handling and logging
- UTC conversion for accurate timing

**Email Processor:**
- Subscription grouping by email
- Smart AI usage optimization
- HTML/plain text email generation
- SMTP integration with multiple providers

## Data Storage

### Storage Architecture

The application uses a simple but robust JSON-based storage system:

**Location**: `./data/subscriptions.json`
**Format**: Array of subscription objects
**Persistence**: Docker volume mounting
**Concurrency**: Atomic read/write operations

### Subscription Data Structure

```json
{
  "id": "unique-uuid-string",
  "channel_url": "https://www.youtube.com/@channelname",
  "channel_name": "Human Readable Channel Name",
  "user_email": "subscriber@example.com",
  "created_at": "2025-01-15T10:30:00Z",
  "last_checked": "2025-01-16T09:00:00Z",
  "active": true
}
```

### Data Management Features

- **UUID-based IDs**: Unique subscription identification
- **Timestamp tracking**: Creation and last check times
- **Soft deletion**: Active flag for disabling subscriptions
- **Duplicate prevention**: Unique email/channel combinations
- **Atomic operations**: Prevents data corruption during concurrent access

### Backup and Recovery

**Docker Volume Configuration:**
```yaml
volumes:
  - ./data:/app/data
```

**Backup Strategy:**
```bash
# Manual backup
cp ./data/subscriptions.json ./backup/subscriptions-$(date +%Y%m%d).json

# Automated backup (add to cron)
0 2 * * * cp /path/to/data/subscriptions.json /path/to/backup/
```

## Requirements

### System Requirements
- **Docker**: Version 20.10+ with Docker Compose
- **Memory**: 2GB RAM minimum (4GB recommended)
- **Storage**: 1GB free space for containers and data
- **Network**: Internet connection for YouTube access and LLM services

### External Service Requirements

**For Ollama (Self-hosted):**
- Ollama server accessible via HTTP
- Downloaded language models (2GB+ storage per model)
- Adequate GPU/CPU for model inference

**For OpenAI (Cloud):**
- OpenAI account with API access
- Valid API key with sufficient credits
- Network access to api.openai.com

**For Email Notifications:**
- SMTP-enabled email account
- App-specific passwords for enhanced security
- Firewall allowance for SMTP ports (587/465)

## Troubleshooting

### Common Issues

#### Email Notifications Not Working

**Symptoms**: No emails received, scheduler errors
**Solutions**:
1. Verify SMTP credentials in `.env`
2. Check email provider settings (port, server)
3. Ensure app password is used (not regular password)
4. Test manually: `python scheduler.py --run-once`
5. Check spam/junk folders
6. Verify timezone configuration

#### LLM Service Connection Errors

**Symptoms**: "Service unavailable" errors, failed summaries
**Solutions**:
1. **Ollama**: Verify server URL and port accessibility
2. **OpenAI**: Check API key validity and account credits
3. Review service status in frontend LLM indicator
4. Check network connectivity and firewall rules
5. Validate model names in configuration

#### YouTube Access Issues

**Symptoms**: "Video not found" errors, extraction failures
**Solutions**:
1. Verify video/channel URLs are public and accessible
2. Check for geographic restrictions
3. Ensure yt-dlp is up to date (handled in Docker builds)
4. Test with different videos to isolate issues

#### Docker Container Problems

**Symptoms**: Containers not starting, build failures
**Solutions**:
1. Verify `.env` file exists and is properly formatted
2. Check Docker Compose logs: `docker-compose logs`
3. Ensure sufficient disk space and memory
4. Rebuild containers: `docker-compose up --build -d`
5. Check port conflicts (80, 8000)

### Debugging Tools

**Container Logs:**
```bash
# View all logs
docker-compose logs

# Follow specific service logs
docker-compose logs -f backend
docker-compose logs -f frontend

# View recent logs
docker-compose logs --tail=50
```

**Health Checks:**
```bash
# API health check
curl http://localhost:8000/

# LLM service status
curl http://localhost:8000/llm-service

# Frontend accessibility
curl http://localhost/
```

**Manual Testing:**
```bash
# Test email system
cd backend
python scheduler.py --run-once

# Test specific timezone
TIMEZONE=UTC python scheduler.py --run-once

# Test LLM connectivity
python -c "
from llm_client import LLMClient
import asyncio
client = LLMClient()
print(asyncio.run(client.check_connection()))
"
```

## Security Considerations

### Environment Security
- **Never commit `.env` files** to version control
- **Use app-specific passwords** instead of account passwords
- **Rotate API keys and passwords** periodically
- **Limit email sending rates** to avoid spam classification
- **Use strong, unique passwords** for all accounts

### API Security
- **API key protection**: Store securely, never expose in logs
- **Rate limiting**: Implement usage monitoring for cloud services
- **Network security**: Use HTTPS for all external API calls
- **Input validation**: All user inputs are sanitized and validated

### Data Privacy
- **Local storage**: Subscription data stored locally, not in cloud
- **Minimal data collection**: Only necessary email and channel information
- **No tracking**: No analytics or user behavior tracking
- **Secure transmission**: All API communications use encryption

### Deployment Security
- **Container isolation**: Services run in separate containers
- **Non-root execution**: Containers run with limited privileges
- **Volume restrictions**: Data access limited to necessary directories
- **Update management**: Regular dependency updates for security patches

## Performance Optimization

### Analysis Performance
- **Configurable limits**: Channel analysis limited to 3-15 videos
- **Early termination**: Stops processing when encountering old videos
- **Parallel processing**: Concurrent video analysis where possible
- **Caching**: Efficient subtitle extraction and processing

### Email Performance
- **Batch processing**: Group subscriptions by email for efficiency
- **Smart AI usage**: Limit expensive LLM calls to most important content
- **Optimized scheduling**: Configurable check frequencies
- **Error resilience**: Continue processing despite individual failures

### Resource Management
- **Memory efficiency**: Streaming responses to handle large datasets
- **Storage optimization**: Compact JSON storage with atomic operations
- **Network efficiency**: Minimal API calls and intelligent caching
- **Container optimization**: Multi-stage builds for smaller images

## Monitoring and Maintenance

### Application Monitoring
- **Health endpoints**: Built-in status checking for all services
- **Comprehensive logging**: Detailed logs for troubleshooting
- **Error tracking**: Graceful error handling with detailed reporting
- **Performance metrics**: Response times and success rates

### Maintenance Tasks
- **Data backup**: Regular subscription data backups
- **Log rotation**: Prevent log files from growing too large
- **Dependency updates**: Keep libraries current for security
- **Storage cleanup**: Monitor disk usage and clean temporary files

### Production Deployment
- **Load balancing**: Scale frontend containers as needed
- **Database migration**: Consider PostgreSQL for high-volume usage
- **Monitoring setup**: Implement proper logging and alerting
- **Backup automation**: Scheduled data backup procedures

## License

This project is for educational and personal use. Please respect YouTube's Terms of Service and API usage guidelines when using this application.

---

**Contributing**: This is a personal project, but issues and suggestions are welcome through GitHub.

**Support**: For questions or issues, please check the troubleshooting section above or create a GitHub issue with detailed information about your setup and the problem encountered.