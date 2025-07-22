from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List
import asyncio
import json
import os
import pytz

from youtube_analyzer import YouTubeAnalyzer
from llm_client import LLMClient
from subscription_manager import SubscriptionManager

app = FastAPI(title="YouTube Video Analyzer", version="1.0.0")

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for now
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize services
youtube_analyzer = YouTubeAnalyzer()
llm_client = LLMClient()

# Initialize timezone configuration (same as background_checker)
timezone_name = os.getenv('TIMEZONE', 'UTC')
try:
    user_timezone = pytz.timezone(timezone_name)
except pytz.exceptions.UnknownTimeZoneError:
    print(f"Unknown timezone: {timezone_name}. Using UTC")
    user_timezone = pytz.UTC
# Lazy initialization for subscription_manager to avoid issues during Docker build
subscription_manager = None

def get_subscription_manager():
    global subscription_manager
    if subscription_manager is None:
        subscription_manager = SubscriptionManager()
    return subscription_manager

class VideoAnalysisRequest(BaseModel):
    url: str

class ChannelAnalysisRequest(BaseModel):
    url: str
    limit: Optional[int] = 5

class SubscriptionRequest(BaseModel):
    channel_url: str
    channel_name: str
    user_email: str

class VideoResult(BaseModel):
    title: str
    url: str
    duration: str
    published_date: str
    thumbnail: str
    summary: str
    has_transcript: bool = False

class SubscriptionResponse(BaseModel):
    id: str
    channel_url: str
    channel_name: str
    user_email: str
    created_at: str
    last_checked: Optional[str] = None
    active: bool = True

@app.get("/")
async def root():
    return {"message": "YouTube Video Analyzer API"}

@app.get("/llm-service")
async def get_llm_service():
    """Get current LLM service configuration"""
    try:
        service = os.getenv('LLM_SERVICE', 'ollama').lower()
        config = {
            "service": service,
            "status": "unknown"
        }
        
        # Add service-specific info
        if service == 'ollama':
            config["host"] = os.getenv('OLLAMA_HOST', 'http://localhost:11434')
            config["model"] = os.getenv('OLLAMA_MODEL', 'llama3.2')
        elif service == 'openai':
            config["model"] = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')
            config["has_api_key"] = bool(os.getenv('OPENAI_API_KEY'))
        
        # Test connection
        try:
            connection_ok = await llm_client.check_connection()
            config["status"] = "connected" if connection_ok else "disconnected"
        except Exception as e:
            config["status"] = "error"
            config["error"] = str(e)
        
        return config
    except Exception as e:
        return {"error": f"Failed to get LLM service info: {str(e)}"}

@app.get("/test-stream")
async def test_stream():
    """Test streaming endpoint"""
    async def generate():
        for i in range(5):
            yield await send_progress(f"Test step {i+1}", i+1, 5)
            await asyncio.sleep(1)
    
    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})

async def send_progress(message: str, step: int, total: int):
    """Send progress update as JSON"""
    progress_data = {
        "type": "progress",
        "message": message,
        "step": step,
        "total": total,
        "progress": round((step / total) * 100, 1)
    }
    return f"data: {json.dumps(progress_data)}\n\n"

@app.post("/analyze/video/stream")
async def analyze_video_stream(request: VideoAnalysisRequest):
    """Stream video analysis with progress updates"""
    async def generate():
        try:
            print(f"Starting video analysis for: {request.url}")
            yield await send_progress("🔍 Extracting video information...", 1, 3)
            await asyncio.sleep(0.5)  # Small delay to ensure message is sent
            
            video_info = await youtube_analyzer.get_video_info(request.url, user_timezone)
            print(f"Video info extracted: {video_info.get('title', 'Unknown')}")
            
            yield await send_progress("🤖 Generating AI summary...", 2, 3)
            await asyncio.sleep(0.5)  # Small delay to ensure message is sent
            
            summary = await llm_client.generate_summary(video_info)
            print(f"Summary generated: {len(summary)} characters")
            
            yield await send_progress("✅ Analysis complete!", 3, 3)
            await asyncio.sleep(0.5)  # Small delay to ensure message is sent
            
            # Send final result
            result = VideoResult(
                title=video_info['title'],
                url=video_info['url'],
                duration=video_info['duration'],
                published_date=video_info['published_date'],
                thumbnail=video_info['thumbnail'],
                summary=summary,
                has_transcript=video_info.get('has_transcript', False)
            )
            
            final_data = {
                "type": "result",
                "data": result.dict()
            }
            yield f"data: {json.dumps(final_data)}\n\n"
            
        except Exception as e:
            error_data = {
                "type": "error",
                "message": str(e)
            }
            yield f"data: {json.dumps(error_data)}\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})

@app.post("/analyze/video", response_model=VideoResult)
async def analyze_video(request: VideoAnalysisRequest):
    try:
        # Extract video info with timezone
        video_info = await youtube_analyzer.get_video_info(request.url, user_timezone)
        
        # Generate summary using LLM
        summary = await llm_client.generate_summary(video_info)
        
        return VideoResult(
            title=video_info['title'],
            url=video_info['url'],
            duration=video_info['duration'],
            published_date=video_info['published_date'],
            thumbnail=video_info['thumbnail'],
            summary=summary,
            has_transcript=video_info.get('has_transcript', False)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/analyze/channel/stream")
async def analyze_channel_stream(request: ChannelAnalysisRequest):
    """Stream channel analysis with progress updates"""
    async def generate():
        try:
            print(f"Channel analysis request: {request}")
            yield await send_progress("🔍 Fetching channel information...", 1, 10)
            
            videos = await youtube_analyzer.get_channel_videos(
                request.url, 
                limit=request.limit,
                user_timezone=user_timezone
            )
            
            yield await send_progress(f"📹 Found {len(videos)} videos to analyze", 2, 10)
            
            if not videos:
                yield await send_progress("❌ No videos found matching the criteria", 10, 10)
                # Send empty result
                final_data = {
                    "type": "result",
                    "data": []
                }
                yield f"data: {json.dumps(final_data)}\n\n"
                return
            
            results = []
            for i, video_info in enumerate(videos, 1):
                yield await send_progress(f"🤖 Analyzing video {i}/{len(videos)}: {video_info['title'][:50]}...", 2 + i, 10)
                
                summary = await llm_client.generate_summary(video_info)
                results.append(VideoResult(
                    title=video_info['title'],
                    url=video_info['url'],
                    duration=video_info['duration'],
                    published_date=video_info['published_date'],
                    thumbnail=video_info['thumbnail'],
                    summary=summary,
                    has_transcript=video_info.get('has_transcript', False)
                ))
            
            yield await send_progress("✅ Channel analysis complete!", 10, 10)
            
            # Send final result
            final_data = {
                "type": "result",
                "data": [result.dict() for result in results]
            }
            yield f"data: {json.dumps(final_data)}\n\n"
            
        except Exception as e:
            error_data = {
                "type": "error",
                "message": str(e)
            }
            yield f"data: {json.dumps(error_data)}\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})

@app.post("/analyze/channel", response_model=List[VideoResult])
async def analyze_channel(request: ChannelAnalysisRequest):
    try:
        # Get channel videos
        videos = await youtube_analyzer.get_channel_videos(
            request.url, 
            limit=request.limit,
            user_timezone=user_timezone
        )
        
        # Generate summaries for all videos
        results = []
        for video_info in videos:
            summary = await llm_client.generate_summary(video_info)
            results.append(VideoResult(
                title=video_info['title'],
                url=video_info['url'],
                duration=video_info['duration'],
                published_date=video_info['published_date'],
                thumbnail=video_info['thumbnail'],
                summary=summary,
                has_transcript=video_info.get('has_transcript', False)
            ))
        
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Subscription endpoints

@app.post("/subscriptions", response_model=SubscriptionResponse)
async def create_subscription(request: SubscriptionRequest):
    """Create a new channel subscription"""
    try:
        # Check if subscription already exists
        manager = get_subscription_manager()
        if manager.subscription_exists(request.user_email, request.channel_url):
            raise HTTPException(status_code=400, detail="Subscription already exists for this email and channel")
        
        subscription = manager.add_subscription(
            channel_url=request.channel_url,
            channel_name=request.channel_name,
            user_email=request.user_email
        )
        return SubscriptionResponse(**subscription.__dict__)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/subscriptions", response_model=List[SubscriptionResponse])
async def get_subscriptions():
    """Get all subscriptions"""
    try:
        subscriptions = get_subscription_manager().get_subscriptions()
        return [SubscriptionResponse(**sub.__dict__) for sub in subscriptions]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/subscriptions/email/{email}", response_model=List[SubscriptionResponse])
async def get_subscriptions_by_email(email: str):
    """Get subscriptions for a specific email"""
    try:
        subscriptions = get_subscription_manager().get_subscriptions_by_email(email)
        return [SubscriptionResponse(**sub.__dict__) for sub in subscriptions]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/subscriptions/{subscription_id}")
async def delete_subscription(subscription_id: str):
    """Delete a subscription"""
    try:
        success = get_subscription_manager().delete_subscription(subscription_id)
        if success:
            return {"message": "Subscription deleted successfully"}
        else:
            raise HTTPException(status_code=404, detail="Subscription not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/subscriptions/email/{email}/channel")
async def delete_subscription_by_email_channel(email: str, channel_url: str):
    """Delete a subscription by email and channel URL"""
    try:
        success = get_subscription_manager().delete_subscription_by_email_and_channel(email, channel_url)
        if success:
            return {"message": "Subscription deleted successfully"}
        else:
            raise HTTPException(status_code=404, detail="Subscription not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/subscriptions/emails")
async def get_unique_emails():
    """Get all unique email addresses with subscriptions"""
    try:
        emails = get_subscription_manager().get_all_unique_emails()
        return {"emails": emails}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/check-subscriptions")
async def trigger_background_check():
    """Manually trigger background subscription check"""
    try:
        from background_checker import BackgroundChecker
        checker = BackgroundChecker()
        await checker.check_all_subscriptions()
        return {"message": "Background check completed successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)