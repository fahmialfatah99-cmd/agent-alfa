import sys
from google import genai
from google.genai import types
from tools import AVAILABLE_TOOLS, get_system_stats

print("Verifying tools and client...")
print("Tools loaded:", len(AVAILABLE_TOOLS))
stats = get_system_stats()
print("System stats sample:", stats)
