import os
from google import genai
from dotenv import load_dotenv

def list_models():
    load_dotenv()
    api_key = os.getenv("GOOGLE_API_KEY")
    client = genai.Client(api_key=api_key)
    
    print("Available models:")
    for model in client.models.list():
        # Check for bidiGenerateContent support if possible, or just print all
        # The genai SDK doesn't always expose supported_methods in a simple way
        # so let's just print the names.
        print(f"- {model.name}")

if __name__ == "__main__":
    list_models()
