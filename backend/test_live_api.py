import asyncio
import os
from google import genai
from google.genai import types
from dotenv import load_dotenv

async def test_live_api():
    load_dotenv()
    api_key = os.getenv("GOOGLE_API_KEY")
    model_id = "models/gemini-2.5-flash-native-audio-latest"
    print(f"Testing model: {model_id}")
    
    client = genai.Client(api_key=api_key)
    
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"], # REQUIRED for this model
        system_instruction=types.Content(
            parts=[types.Part(text="You are a helpful assistant.")]
        ),
    )
    
    try:
        async with client.aio.live.connect(
            model=model_id,
            config=config,
        ) as session:
            print(f"Successfully connected to {model_id}!")
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_live_api())
