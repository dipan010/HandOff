import os
from google import genai
from dotenv import load_dotenv

def test_generation():
    load_dotenv()
    api_key = os.getenv("GOOGLE_API_KEY")
    client = genai.Client(api_key=api_key)
    
    print("Testing standard generation with gemini-2.0-flash...")
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents="Hello, say 'I am working' if you can read this."
        )
        print(f"Response: {response.text}")
    except Exception as e:
        print(f"Generation failed: {e}")

if __name__ == "__main__":
    test_generation()
