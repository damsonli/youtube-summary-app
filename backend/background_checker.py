import asyncio
import json
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict
import os
from pathlib import Path
import pytz

from subscription_manager import SubscriptionManager
from youtube_analyzer import YouTubeAnalyzer
from llm_client import LLMClient

class BackgroundChecker:
    def __init__(self):
        self.subscription_manager = SubscriptionManager()
        self.youtube_analyzer = YouTubeAnalyzer()
        self.llm_client = LLMClient()
        
        # Email configuration
        self.smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
        self.smtp_port = int(os.getenv('SMTP_PORT', '587'))
        self.email_user = os.getenv('EMAIL_USER')
        self.email_password = os.getenv('EMAIL_PASSWORD')
        self.from_email = os.getenv('FROM_EMAIL', self.email_user)
        
        # Timezone configuration
        timezone_name = os.getenv('TIMEZONE', 'UTC')
        try:
            self.user_timezone = pytz.timezone(timezone_name)
        except pytz.exceptions.UnknownTimeZoneError:
            print(f"Unknown timezone: {timezone_name}. Using UTC")
            self.user_timezone = pytz.UTC
        
    async def check_all_subscriptions(self):
        """Check all active subscriptions and send email notifications"""
        print(f"Starting background check at {datetime.now(timezone.utc)}")
        
        subscriptions = self.subscription_manager.get_subscriptions()
        print(f"Found {len(subscriptions)} active subscriptions")
        
        # Group subscriptions by email for efficient processing
        subscriptions_by_email = {}
        for sub in subscriptions:
            if sub.user_email not in subscriptions_by_email:
                subscriptions_by_email[sub.user_email] = []
            subscriptions_by_email[sub.user_email].append(sub)
        
        for user_email, user_subscriptions in subscriptions_by_email.items():
            print(f"Processing {len(user_subscriptions)} subscriptions for {user_email}")
            await self.process_user_subscriptions(user_email, user_subscriptions)
    
    async def process_user_subscriptions(self, user_email: str, subscriptions: List):
        """Process all subscriptions for a single user and send one email"""
        all_new_videos = []
        updated_subscriptions = []
        
        for subscription in subscriptions:
            try:
                print(f"Checking subscription: {subscription.channel_name}")
                new_videos = await self.check_subscription(subscription)
                
                if new_videos:
                    all_new_videos.extend([{
                        'channel_name': subscription.channel_name,
                        'channel_url': subscription.channel_url,
                        'videos': new_videos
                    }])
                
                # Update last_checked timestamp
                self.subscription_manager.update_last_checked(
                    subscription.id, 
                    datetime.now(timezone.utc).isoformat()
                )
                updated_subscriptions.append(subscription.channel_name)
                
            except Exception as e:
                print(f"Error checking subscription {subscription.channel_name}: {str(e)}")
        
        # Send email if there are new videos
        if all_new_videos:
            await self.send_notification_email(user_email, all_new_videos)
            print(f"Sent notification email to {user_email} with {sum(len(ch['videos']) for ch in all_new_videos)} new videos")
        else:
            print(f"No new videos found for {user_email}")
        
        print(f"Updated {len(updated_subscriptions)} subscriptions: {', '.join(updated_subscriptions)}")
    
    async def check_subscription(self, subscription) -> List[Dict]:
        """Check a single subscription for new videos since last check time"""
        try:
            print(f"Looking for new videos from: {subscription.channel_name}")
            
            # Determine time range for video filtering
            now_local = datetime.now(self.user_timezone)
            cutoff_time = self.get_cutoff_time(subscription.last_checked)
            
            # Convert cutoff to user timezone for comparison
            if cutoff_time.tzinfo != self.user_timezone:
                cutoff_local = cutoff_time.astimezone(self.user_timezone)
            else:
                cutoff_local = cutoff_time
                
            print(f"Checking videos since: {cutoff_local} ({self.user_timezone})")
            print(f"Current time: {now_local}")
            
            # Use cutoff date for early stopping (convert to date for compatibility)
            cutoff_date = cutoff_local.date()
            
            # Get recent videos from the channel with early stopping optimization
            videos = await self.youtube_analyzer.get_channel_videos(
                subscription.channel_url, 
                limit=20,  # Increased limit since we're using time-based filtering
                early_stop_date=cutoff_date,  # Stop when we hit videos older than cutoff
                user_timezone=self.user_timezone  # Pass timezone for proper date handling
            )
            
            # Filter videos published since last check time (more precise than daily)
            new_videos = []
            
            for video in videos:
                video_published = self.parse_video_published_time(video)
                if video_published and video_published > cutoff_local:
                    new_videos.append(video)
                    print(f"Found new video: {video['title']} (published: {video_published})")
            
            if not new_videos:
                print(f"No new videos since last check for {subscription.channel_name}")
                return []
            
            # Sort by publication time (newest first)
            new_videos.sort(key=lambda x: x.get('published_date', ''), reverse=True)
            
            # Smart summary distribution: AI summary for first 3, basic info for rest
            processed_videos = []
            
            for i, video in enumerate(new_videos):
                if i < 3:  # First 3 videos get full AI summary
                    print(f"Generating AI summary for video {i+1}: {video['title']}")
                    summary = await self.llm_client.generate_summary(video)
                    video['summary'] = summary
                    video['has_ai_summary'] = True
                else:  # Rest get basic info only
                    video['summary'] = f"📝 Published since last check - {video.get('description', '')[:150]}..." if video.get('description') else "📝 Published since last check"
                    video['has_ai_summary'] = False
                
                processed_videos.append(video)
            
            print(f"Processed {len(processed_videos)} new videos for {subscription.channel_name} ({len([v for v in processed_videos if v['has_ai_summary']])} with AI summaries)")
            return processed_videos
            
        except Exception as e:
            print(f"Error checking subscription {subscription.channel_name}: {str(e)}")
            return []
    
    def get_cutoff_time(self, last_checked: str) -> datetime:
        """Get the cutoff time for determining "new" videos"""
        if last_checked:
            try:
                # Parse timezone-aware timestamp
                if 'T' in last_checked and last_checked.endswith('+00:00'):
                    return datetime.fromisoformat(last_checked)
                elif 'T' in last_checked and not ('+' in last_checked or 'Z' in last_checked):
                    # Legacy format without timezone info - assume UTC
                    return datetime.fromisoformat(last_checked + '+00:00')
                else:
                    return datetime.fromisoformat(last_checked.replace('Z', '+00:00'))
            except ValueError:
                pass
        
        # Default: videos from last 24 hours
        return datetime.now(timezone.utc) - timedelta(hours=24)
    
    def parse_video_date(self, date_str: str) -> datetime:
        """Parse video date string to timezone-aware datetime object"""
        try:
            # Handle YYYY-MM-DD format (assume UTC and convert to user timezone)
            naive_date = datetime.strptime(date_str, "%Y-%m-%d")
            # Assume video dates are in UTC, then convert to user timezone for comparison
            utc_date = naive_date.replace(tzinfo=timezone.utc) if naive_date.tzinfo is None else naive_date
            return utc_date.astimezone(self.user_timezone) if self.user_timezone else utc_date
        except ValueError:
            try:
                # Handle other possible formats
                dt = datetime.fromisoformat(date_str)
                if dt.tzinfo is None:
                    # Add UTC timezone if naive
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(self.user_timezone) if self.user_timezone else dt
            except ValueError:
                return None
    
    def parse_video_published_time(self, video: Dict) -> datetime:
        """Parse video published time from video dict, returns timezone-aware datetime"""
        try:
            published_date = video.get('published_date', '')
            if not published_date:
                return None
            
            # Handle YYYY-MM-DD format - since we now use timestamp, this should be more accurate
            # Assume the published_date is already in user timezone from the new timestamp conversion
            date_obj = datetime.strptime(published_date, "%Y-%m-%d")
            
            # Make timezone-aware in user's timezone 
            # (this assumes the published_date from timestamp conversion is already in user timezone)
            localized_datetime = self.user_timezone.localize(date_obj)
            
            return localized_datetime
        except (ValueError, AttributeError) as e:
            print(f"Error parsing video published time '{published_date}': {e}")
            return None
    
    async def send_notification_email(self, user_email: str, channels_with_videos: List[Dict]):
        """Send email notification with new videos"""
        if not self.email_user or not self.email_password:
            print("Email credentials not configured, skipping email notification")
            return
        
        try:
            subject = f"YouTube Updates: {sum(len(ch['videos']) for ch in channels_with_videos)} new videos"
            body = self.generate_email_body(channels_with_videos)
            
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.from_email
            msg['To'] = user_email
            
            # Create both plain text and HTML versions
            text_part = MIMEText(body, 'plain')
            html_part = MIMEText(self.generate_html_email_body(channels_with_videos), 'html')
            
            msg.attach(text_part)
            msg.attach(html_part)
            
            # Send email
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.email_user, self.email_password)
                server.send_message(msg)
            
            print(f"Email sent successfully to {user_email}")
            
        except Exception as e:
            print(f"Failed to send email to {user_email}: {str(e)}")
    
    def generate_email_body(self, channels_with_videos: List[Dict]) -> str:
        """Generate plain text email body"""
        local_date = datetime.now(self.user_timezone).strftime('%Y-%m-%d')
        timezone_name = str(self.user_timezone)
        body = f"🎥 Your YouTube Channel Updates - {local_date} ({timezone_name})\n\n"
        
        total_videos = sum(len(ch['videos']) for ch in channels_with_videos)
        ai_summaries = sum(len([v for v in ch['videos'] if v.get('has_ai_summary', False)]) for ch in channels_with_videos)
        
        body += f"📊 Summary: {total_videos} new videos today ({ai_summaries} with AI summaries)\n\n"
        
        for channel_data in channels_with_videos:
            body += f"📺 {channel_data['channel_name']}\n"
            body += f"   {channel_data['channel_url']}\n\n"
            
            for i, video in enumerate(channel_data['videos']):
                icon = "🤖" if video.get('has_ai_summary') else "📌"
                body += f"   {icon} {video['title']}\n"
                body += f"      📅 {video['published_date']} | ⏱️ {video['duration']}\n"
                body += f"      🔗 {video['url']}\n"
                
                if video.get('has_ai_summary'):
                    # Add transcript indicator for AI summaries
                    transcript_icon = "📜" if video.get('has_transcript', False) else ""
                    summary_prefix = f"🤖{transcript_icon} AI Summary"
                    body += f"      {summary_prefix}: {video['summary'][:200]}...\n\n"
                else:
                    body += f"      {video['summary']}\n\n"
        
        body += "\n---\nYouTube Video Analyzer\nManage your subscriptions: [Your App URL]"
        return body
    
    def generate_html_email_body(self, channels_with_videos: List[Dict]) -> str:
        """Generate HTML email body"""
        total_videos = sum(len(ch['videos']) for ch in channels_with_videos)
        ai_summaries = sum(len([v for v in ch['videos'] if v.get('has_ai_summary', False)]) for ch in channels_with_videos)
        
        local_date = datetime.now(self.user_timezone).strftime('%Y-%m-%d')
        timezone_name = str(self.user_timezone)
        
        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .header {{ background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
                .summary-stats {{ background-color: #e3f2fd; padding: 15px; border-radius: 8px; margin-bottom: 20px; }}
                .channel {{ margin-bottom: 30px; border-left: 4px solid #007bff; padding-left: 15px; }}
                .video {{ background-color: #f8f9fa; padding: 15px; margin: 10px 0; border-radius: 8px; }}
                .video-ai {{ border-left: 4px solid #28a745; }}
                .video-basic {{ border-left: 4px solid #6c757d; }}
                .video-title {{ font-weight: bold; color: #007bff; margin-bottom: 5px; }}
                .video-meta {{ color: #666; font-size: 0.9em; margin-bottom: 10px; }}
                .video-summary {{ margin-top: 10px; }}
                .ai-badge {{ background-color: #28a745; color: white; padding: 2px 6px; border-radius: 4px; font-size: 0.8em; }}
                .basic-badge {{ background-color: #6c757d; color: white; padding: 2px 6px; border-radius: 4px; font-size: 0.8em; }}
                .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; color: #666; font-size: 0.9em; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h2>🎥 Your YouTube Channel Updates - {local_date} ({timezone_name})</h2>
                <p>Here are today's videos from your subscribed channels:</p>
            </div>
            
            <div class="summary-stats">
                <strong>📊 Today's Summary:</strong> {total_videos} new videos ({ai_summaries} with AI summaries)
            </div>
        """
        
        for channel_data in channels_with_videos:
            html += f"""
            <div class="channel">
                <h3>📺 {channel_data['channel_name']}</h3>
                <p><a href="{channel_data['channel_url']}">{channel_data['channel_url']}</a></p>
            """
            
            for video in channel_data['videos']:
                video_class = "video-ai" if video.get('has_ai_summary') else "video-basic"
                
                # Create badge with transcript indicator
                if video.get('has_ai_summary'):
                    transcript_icon = "📜" if video.get('has_transcript', False) else ""
                    badge = f'<span class="ai-badge">🤖{transcript_icon} AI Summary</span>'
                else:
                    badge = '<span class="basic-badge">📌 Basic Info</span>'
                
                html += f"""
                <div class="video {video_class}">
                    <div class="video-title">
                        <a href="{video['url']}">{video['title']}</a> {badge}
                    </div>
                    <div class="video-meta">
                        📅 {video['published_date']} | ⏱️ {video['duration']}
                    </div>
                    <div class="video-summary">
                        {video['summary']}
                    </div>
                </div>
                """
            
            html += "</div>"
        
        html += """
            <div class="footer">
                <p>YouTube Video Analyzer<br>
                <a href="[Your App URL]">Manage your subscriptions</a></p>
            </div>
        </body>
        </html>
        """
        return html

async def main():
    """Main function to run the background checker"""
    checker = BackgroundChecker()
    await checker.check_all_subscriptions()

if __name__ == "__main__":
    asyncio.run(main())