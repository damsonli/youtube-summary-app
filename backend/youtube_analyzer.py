import yt_dlp
import asyncio
import requests
from typing import Dict, List, Optional
from datetime import datetime, timedelta, timezone
import re
import pytz

class YouTubeAnalyzer:
    def __init__(self):
        self.ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'writesubtitles': False,  # Don't write subtitle files
            'writeautomaticsub': False,  # Don't write auto-generated subtitle files
        }
    
    async def get_video_info(self, url: str, user_timezone=None) -> Dict:
        """Extract information from a single video URL"""
        try:
            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, self._extract_video_info, url)
            return self._format_video_info(info, user_timezone)
        except Exception as e:
            raise Exception(f"Failed to extract video info: {str(e)}")
    
    def _extract_video_info(self, url: str) -> Dict:
        """Synchronous video info extraction"""
        with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)
    
    async def get_channel_videos(self, url: str, limit: int = 5, early_stop_date=None, user_timezone=None) -> List[Dict]:
        """Extract videos from a channel URL with optional early stopping optimization"""
        try:
            print(f"Extracting channel info for: {url}")
            loop = asyncio.get_event_loop()
            channel_info = await loop.run_in_executor(None, self._extract_channel_info, url)
            
            # Get videos from channel
            videos = []
            entries = channel_info.get('entries', [])
            print(f"Found {len(entries)} total entries")
            
            # Sort by upload date (newest first)
            if entries:
                entries = sorted(entries, key=lambda x: x.get('upload_date', ''), reverse=True)
                print(f"Sorted {len(entries)} entries by upload date (newest first)")
            
            if not entries:
                print("No entries found")
                return []
            
            # Early stopping optimization: process videos one by one and stop when we hit old videos
            processed_count = 0
            for i, entry in enumerate(entries):
                if entry and entry.get('id'):
                    # Stop if we've reached the limit
                    if processed_count >= limit:
                        print(f"Reached limit of {limit} videos, stopping")
                        break
                    
                    print(f"Processing video {processed_count+1}: {entry.get('title', 'Unknown')}")
                    video_url = f"https://www.youtube.com/watch?v={entry['id']}"
                    video_info = await self.get_video_info(video_url, user_timezone)
                    
                    # Early stopping: check if this video is older than our cutoff date
                    if early_stop_date and video_info.get('published_date'):
                        try:
                            # Parse the formatted date (YYYY-MM-DD) - this is already in user timezone
                            video_date = datetime.strptime(video_info['published_date'], "%Y-%m-%d")
                            
                            # Compare dates directly (both should be in user timezone)
                            if video_date.date() < early_stop_date:
                                print(f"Early stopping: Video {processed_count+1} '{video_info['title']}' is from {video_date.date()}, which is before {early_stop_date}")
                                # Don't add this video to results since it's too old
                                break
                        except ValueError as e:
                            print(f"Could not parse published_date '{video_info.get('published_date')}' for video {processed_count+1}: {e}")
                        except Exception as e:
                            print(f"Error processing date for video {processed_count+1}: {e}")
                    
                    videos.append(video_info)
                    processed_count += 1
                else:
                    print(f"Skipping invalid entry: {entry}")
            
            if early_stop_date:
                print(f"Optimized processing: checked {processed_count} videos (stopped early, saved {len(entries) - processed_count} video fetches)")
            else:
                print(f"Standard processing: processed {processed_count} videos")
            
            return videos
        except Exception as e:
            print(f"Error in get_channel_videos: {str(e)}")
            raise Exception(f"Failed to extract channel videos: {str(e)}")
    
    def _extract_channel_info(self, url: str) -> Dict:
        """Synchronous channel info extraction"""
        channel_opts = {
            **self.ydl_opts,
            'extract_flat': True,
            'playlistend': 50,  # Get recent videos
        }
        
        with yt_dlp.YoutubeDL(channel_opts) as ydl:
            return ydl.extract_info(url, download=False)
    
    def _format_video_info(self, info: Dict, user_timezone=None) -> Dict:
        """Format video info into consistent structure"""
        # Extract transcript if available
        transcript = self._extract_transcript(info)
        
        # Use timestamp for more accurate date handling, fallback to upload_date
        timestamp = info.get('timestamp')
        upload_date = info.get('upload_date', '')
        
        return {
            'title': info.get('title', 'Unknown Title'),
            'url': info.get('webpage_url', ''),
            'duration': self._format_duration(info.get('duration', 0)),
            'published_date': self._format_timestamp_or_date(timestamp, upload_date, user_timezone),
            'thumbnail': info.get('thumbnail', ''),
            'description': info.get('description', '')[:500] + '...' if info.get('description') else '',
            'view_count': info.get('view_count', 0),
            'uploader': info.get('uploader', ''),
            'transcript': transcript,
            'has_transcript': bool(transcript and transcript.strip()),
        }
    
    def _format_duration(self, seconds: int) -> str:
        """Convert seconds to MM:SS or HH:MM:SS format"""
        if not seconds:
            return "0:00"
        
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        seconds = seconds % 60
        
        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes}:{seconds:02d}"
    
    def _format_date(self, date_str: str, user_timezone=None) -> str:
        """Format YYYYMMDD to readable date with timezone awareness"""
        if not date_str or len(date_str) != 8:
            return "Unknown Date"
        
        try:
            # Parse the date as UTC (YouTube upload dates are in UTC)
            # YouTube gives us YYYYMMDD which represents the UTC date
            utc_date = datetime.strptime(date_str, "%Y%m%d")
            utc_date = utc_date.replace(tzinfo=timezone.utc)
            
            # Convert to user timezone if provided
            if user_timezone:
                local_date = utc_date.astimezone(user_timezone)
                return local_date.strftime("%Y-%m-%d")
            else:
                return utc_date.strftime("%Y-%m-%d")
        except ValueError:
            return "Unknown Date"
    
    def _format_timestamp_or_date(self, timestamp, upload_date: str, user_timezone=None) -> str:
        """Format timestamp (preferred) or upload_date with timezone awareness"""
        # Prefer timestamp for accuracy, fallback to upload_date
        if timestamp:
            try:
                # Convert Unix timestamp to datetime
                utc_datetime = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                
                # Convert to user timezone if provided
                if user_timezone:
                    local_datetime = utc_datetime.astimezone(user_timezone)
                    return local_datetime.strftime("%Y-%m-%d")
                else:
                    return utc_datetime.strftime("%Y-%m-%d")
            except (ValueError, OSError) as e:
                print(f"Error processing timestamp {timestamp}: {e}, falling back to upload_date")
        
        # Fallback to upload_date method
        return self._format_date(upload_date, user_timezone)
    
    def _filter_by_date(self, entries: List, date_filter: str) -> List:
        """Filter videos by date (e.g., 'last_week', 'last_month')"""
        if not date_filter:
            return entries
        
        now = datetime.now(timezone.utc)
        cutoff_date = None
        
        if date_filter == "last_week":
            cutoff_date = now - timedelta(days=7)
        elif date_filter == "last_month":
            cutoff_date = now - timedelta(days=30)
        elif date_filter == "last_year":
            cutoff_date = now - timedelta(days=365)
        else:
            print(f"Unknown date filter: {date_filter}")
            return entries
        
        print(f"Filtering videos since: {cutoff_date}")
        filtered = []
        for entry in entries:
            if entry and entry.get('upload_date'):
                try:
                    upload_date = datetime.strptime(entry['upload_date'], "%Y%m%d")
                    upload_date = upload_date.replace(tzinfo=timezone.utc)  # Make timezone-aware
                    print(f"Video '{entry.get('title', 'Unknown')}' uploaded: {upload_date}")
                    if upload_date >= cutoff_date:
                        filtered.append(entry)
                        print(f"  -> Included")
                    else:
                        print(f"  -> Excluded (too old)")
                except ValueError as e:
                    print(f"  -> Excluded (invalid date): {e}")
                    continue
            else:
                print(f"Entry missing upload_date: {entry}")
        
        print(f"Date filter result: {len(filtered)} videos remaining")
        return filtered
    
    def _extract_transcript(self, info: Dict) -> str:
        """Extract transcript/subtitles from video info if available"""
        try:
            # Check for automatic captions first (usually more available)
            automatic_captions = info.get('automatic_captions', {})
            subtitles = info.get('subtitles', {})
            
            # Prefer English language, fallback to any available language
            languages_to_try = ['en', 'en-US', 'en-GB']
            
            # Try automatic captions first
            for lang in languages_to_try:
                if lang in automatic_captions:
                    return self._process_subtitle_data(automatic_captions[lang])
            
            # Fallback to manual subtitles
            for lang in languages_to_try:
                if lang in subtitles:
                    return self._process_subtitle_data(subtitles[lang])
            
            # If no English, try any available language
            if automatic_captions:
                first_lang = list(automatic_captions.keys())[0]
                return self._process_subtitle_data(automatic_captions[first_lang])
            
            if subtitles:
                first_lang = list(subtitles.keys())[0]
                return self._process_subtitle_data(subtitles[first_lang])
            
            return ""
            
        except Exception as e:
            print(f"Error extracting transcript: {str(e)}")
            return ""
    
    def _process_subtitle_data(self, subtitle_list: List) -> str:
        """Process subtitle data and extract text content"""
        try:
            if not subtitle_list:
                return ""
            
            # Find the best subtitle format (prefer 'json3' or 'srv1' for easier parsing)
            subtitle_info = None
            preferred_formats = ['json3', 'srv1', 'vtt', 'ttml']
            
            # Look for preferred formats
            for fmt in preferred_formats:
                for sub in subtitle_list:
                    if sub.get('ext') == fmt:
                        subtitle_info = sub
                        break
                if subtitle_info:
                    break
            
            # If no preferred format found, use the first available
            if not subtitle_info and subtitle_list:
                subtitle_info = subtitle_list[0]
            
            if not subtitle_info or 'url' not in subtitle_info:
                return ""
            
            # Fetch the subtitle content with rate limit handling
            response = requests.get(subtitle_info['url'], timeout=10)
            if response.status_code == 429:
                print(f"Rate limited on subtitle fetch, skipping transcript")
                return ""
            response.raise_for_status()
            
            # Parse the subtitle content based on format
            subtitle_text = self._parse_subtitle_content(response.text, subtitle_info.get('ext', ''))
            
            # Limit transcript length for LLM processing
            if len(subtitle_text) > 3000:
                subtitle_text = subtitle_text[:3000] + "... (transcript truncated)"
            
            return subtitle_text
            
        except Exception as e:
            print(f"Error processing subtitle data: {str(e)}")
            return ""
    
    def _parse_subtitle_content(self, content: str, format_type: str) -> str:
        """Parse subtitle content and extract clean text"""
        try:
            if format_type in ['json3', 'srv1']:
                # Parse JSON format captions
                import json
                data = json.loads(content)
                
                if 'events' in data:
                    # Extract text from events
                    text_parts = []
                    for event in data['events']:
                        if 'segs' in event:
                            for seg in event['segs']:
                                if 'utf8' in seg:
                                    text_parts.append(seg['utf8'])
                    return ' '.join(text_parts)
                
            elif format_type == 'vtt':
                # Parse WebVTT format
                lines = content.split('\n')
                text_parts = []
                for line in lines:
                    line = line.strip()
                    # Skip empty lines, timestamps, and metadata
                    if line and '-->' not in line and not line.startswith('WEBVTT') and not line.startswith('NOTE'):
                        # Remove HTML tags if present
                        clean_line = re.sub(r'<[^>]+>', '', line)
                        if clean_line:
                            text_parts.append(clean_line)
                return ' '.join(text_parts)
            
            elif format_type == 'ttml':
                # Parse TTML format (basic XML parsing)
                # Remove XML tags and extract text content
                clean_text = re.sub(r'<[^>]+>', ' ', content)
                clean_text = re.sub(r'\s+', ' ', clean_text).strip()
                return clean_text
            
            # Fallback: try to extract any readable text
            clean_text = re.sub(r'<[^>]+>', ' ', content)
            clean_text = re.sub(r'\s+', ' ', clean_text).strip()
            return clean_text
            
        except Exception as e:
            print(f"Error parsing subtitle content: {str(e)}")
            return ""