import sys, os
from unittest.mock import MagicMock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_s = MagicMock()
sys.modules.setdefault("celery", _s)
sys.modules["app.workers.celery_app"] = MagicMock(celery_app=_s)

import groq
from app.config import settings
from app.services.claude_report import _REPORT_TOOL, _SYSTEM, generate_report

print("groq version :", groq.__version__)
print("model        :", settings.groq_model)
print("api_key set  :", bool(settings.groq_api_key))
print("tool name    :", _REPORT_TOOL["function"]["name"])
print("required keys:", _REPORT_TOOL["function"]["parameters"]["required"])
print()
print("All imports OK — generate_report is wired to Groq.")
