import google.generativeai as genai
from google.generativeai import caching
import datetime
import os

def get_cached_content(system_instruction: str, model_name: str = "gemini-2.5-flash-lite"):
    """
    Creates or retrieves a cached content block for the given system instruction.
    For this MVP, we create a new cache for each run, but in production, 
    you'd look up by hash.
    """
    # Note: In a real persistent app, we would check if a cache with this content already exists.
    # Here we create a volatile cache with a TTL.
    
    try:
        cache = caching.CachedContent.create(
            model=model_name,
            display_name="orchestrator_system_prompt",
            system_instruction=system_instruction,
            contents=[], # Start with empty content, or add static docs here
            ttl=datetime.timedelta(minutes=60),
        )
        return cache
    except Exception as e:
        print(f"Warning: Failed to create context cache: {e}. Falling back to standard prompt.")
        return None
