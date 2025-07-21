import ollama
import asyncio
from typing import Dict
import os

class LLMClient:
    def __init__(self, model_name: str = "llama3.2", host: str = None):
        self.model_name = model_name
        # Use environment variable or provided host for remote Ollama server
        self.host = host or os.getenv('OLLAMA_HOST', 'http://localhost:11434')
        self.client = ollama.AsyncClient(host=self.host)
    
    async def generate_summary(self, video_info: Dict) -> str:
        """Generate a summary of the video using remote Ollama"""
        try:
            # Create prompt with video information
            prompt = self._create_prompt(video_info)
            
            # Generate summary using remote Ollama
            response = await self.client.chat(
                model=self.model_name,
                messages=[
                    {
                        'role': 'user',
                        'content': prompt
                    }
                ],
                options={"num_ctx": 131072}
            )
            
            return response['message']['content']
        except Exception as e:
            # Fallback to basic summary if LLM fails
            return f"Failed to generate AI summary: {str(e)}. Title: {video_info.get('title', 'Unknown')}"
    
    def _create_prompt(self, video_info: Dict) -> str:
        """Create a prompt for the LLM based on video information"""
        title = video_info.get('title', 'Unknown Title')
        description = video_info.get('description', 'No description available')
        duration = video_info.get('duration', 'Unknown duration')
        uploader = video_info.get('uploader', 'Unknown uploader')
        transcript = video_info.get('transcript', '')
        
        # Build the information section
        info_section = f"""**Title:** {title}
**Channel:** {uploader}
**Duration:** {duration}
**Description:** {description}"""
        
        # Add transcript if available
        if transcript and transcript.strip() and transcript != "Transcript available (processing required)":
            info_section += f"""
**Transcript:** {transcript}"""
            # Adjust prompt for transcript availability
            instruction = "Based on the video title, description, and full transcript provided:"
        else:
            instruction = "Based on the available video information:"
        
        prompt = f"""
Please provide a well-formatted markdown summary of this YouTube video {instruction}

{info_section}

Please provide a structured response with:

## Summary
A brief 2-3 sentence overview of what this video is about.

## Key Topics
- List the main topics or themes covered
- Use bullet points for clarity

## Target Audience
Who would find this video most interesting or useful?

## Key Takeaways
- Important points or insights from the video
- Actionable information if applicable

Use markdown formatting (headings, bold, bullet points) to make the response clear and readable. {"Focus on the transcript content when available. " if transcript and transcript.strip() else ""}Keep the response under 500 words and focus on the most important information.
"""
        return prompt
    
    async def check_connection(self) -> bool:
        """Check if the remote Ollama server is accessible"""
        try:
            models = await self.client.list()
            return True
        except Exception as e:
            print(f"Failed to connect to Ollama server at {self.host}: {str(e)}")
            return False