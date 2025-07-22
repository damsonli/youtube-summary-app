import ollama
import asyncio
from typing import Dict, Optional
import os
from abc import ABC, abstractmethod

class LLMServiceError(Exception):
    """Custom exception for LLM service errors"""
    pass

class BaseLLMClient(ABC):
    """Abstract base class for LLM clients"""
    
    @abstractmethod
    async def generate_summary(self, video_info: Dict) -> str:
        """Generate a summary of the video"""
        pass
    
    @abstractmethod
    async def check_connection(self) -> bool:
        """Check if the service is accessible"""
        pass

class OllamaClient(BaseLLMClient):
    def __init__(self, model_name: str = "llama3.2", host: str = None):
        self.model_name = model_name
        self.host = host or os.getenv('OLLAMA_HOST', 'http://localhost:11434')
        try:
            self.client = ollama.AsyncClient(host=self.host)
        except Exception as e:
            raise LLMServiceError(f"Failed to initialize Ollama client: {str(e)}")
    
    async def generate_summary(self, video_info: Dict) -> str:
        """Generate summary using Ollama"""
        try:
            prompt = _build_prompt(video_info)
            response = await self.client.chat(
                model=self.model_name,
                messages=[{'role': 'user', 'content': prompt}],
                options={"num_ctx": 131072}
            )
            return response['message']['content']
        except Exception as e:
            raise LLMServiceError(f"Ollama generation failed: {str(e)}")
    
    async def check_connection(self) -> bool:
        """Check Ollama server connection"""
        try:
            await self.client.list()
            return True
        except Exception:
            return False

class OpenAIClient(BaseLLMClient):
    def __init__(self, api_key: str, model_name: str = "gpt-4o-mini"):
        if not api_key:
            raise LLMServiceError("OpenAI API key is required")
        
        try:
            import openai
            self.client = openai.AsyncOpenAI(api_key=api_key)
            self.model_name = model_name
        except ImportError:
            raise LLMServiceError("OpenAI package not installed. Install with: pip install openai")
        except Exception as e:
            raise LLMServiceError(f"Failed to initialize OpenAI client: {str(e)}")
    
    async def generate_summary(self, video_info: Dict) -> str:
        """Generate summary using OpenAI"""
        try:
            prompt = _build_prompt(video_info)
            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=[{'role': 'user', 'content': prompt}],
                max_tokens=1000,
                temperature=0.7
            )
            return response.choices[0].message.content
        except Exception as e:
            raise LLMServiceError(f"OpenAI generation failed: {str(e)}")
    
    async def check_connection(self) -> bool:
        """Check OpenAI API connection"""
        try:
            await self.client.models.list()
            return True
        except Exception:
            return False

class LLMClient:
    def __init__(self):
        self.service = os.getenv('LLM_SERVICE', 'ollama').lower()
        self.client = self._initialize_client()
    
    def _initialize_client(self) -> BaseLLMClient:
        """Initialize the appropriate LLM client based on configuration"""
        try:
            if self.service == 'ollama':
                model_name = os.getenv('OLLAMA_MODEL', 'llama3.2')
                host = os.getenv('OLLAMA_HOST', 'http://localhost:11434')
                return OllamaClient(model_name=model_name, host=host)
            
            elif self.service == 'openai':
                api_key = os.getenv('OPENAI_API_KEY')
                if not api_key:
                    raise LLMServiceError("OPENAI_API_KEY environment variable is required for OpenAI service")
                model_name = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')
                return OpenAIClient(api_key=api_key, model_name=model_name)
            
            else:
                raise LLMServiceError(f"Unsupported LLM service: {self.service}. Supported services: ollama, openai")
        
        except LLMServiceError:
            raise
        except Exception as e:
            raise LLMServiceError(f"Failed to initialize LLM service '{self.service}': {str(e)}")
    
    async def generate_summary(self, video_info: Dict) -> str:
        """Generate a summary using the configured LLM service"""
        try:
            return await self.client.generate_summary(video_info)
        except LLMServiceError as e:
            # Return detailed error for service configuration issues
            return f"LLM Service Error: {str(e)}"
        except Exception as e:
            # Fallback to basic summary for other errors
            return f"Failed to generate AI summary: {str(e)}. Title: {video_info.get('title', 'Unknown')}"
    
    async def check_connection(self) -> bool:
        """Check if the configured LLM service is accessible"""
        try:
            return await self.client.check_connection()
        except Exception as e:
            print(f"Failed to check connection for {self.service} service: {str(e)}")
            return False

def _build_prompt(video_info: Dict) -> str:
    """Shared prompt building function for all LLM services"""
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