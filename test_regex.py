import re

content = """
| sk-ahXL4sXYXwlzxweIJg9Ryk4cC8j4OvHSkeGEQJ4uGyCl4z8R | gemini-2.5-pro | 🆕 New | $20 | 5 RPM | 2026-05-26 | KM recommended alternative for Premium GPT flagship |
"""

target = "gemini-2.5-pro"
# Pattern: key, then anything, then model name
pattern = re.compile(rf"(sk-[a-zA-Z0-9]{{40,}}).*?{re.escape(target)}", re.DOTALL)
match = pattern.search(content)
print(f"Match: {match.group(1) if match else 'None'}")

# Alternative: Model name, then anything, then key
pattern2 = re.compile(rf"{re.escape(target)}.*?(sk-[a-zA-Z0-9]{{40,}})", re.DOTALL)
match2 = pattern2.search(content)
print(f"Match2: {match2.group(1) if match2 else 'None'}")
