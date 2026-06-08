import sys; sys.path.insert(0,".")
from app.config import settings
from groq import Groq
try:
    Groq(api_key=settings.groq_api_key).chat.completions.create(model=settings.groq_model, max_tokens=5, messages=[{"role":"user","content":"hi"}])
    print("Groq quota: OK")
except Exception as e:
    print("Groq quota: " + str(e)[:140])
