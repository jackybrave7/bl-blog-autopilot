from src.translate import call_deepseek

result = call_deepseek(
    'Return JSON: {"status": "ok"}',
    "ping",
)
print(result)
