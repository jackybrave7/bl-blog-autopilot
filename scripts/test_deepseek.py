from src.translate import call_deepseek, deepseek_config

print("translate_model:", deepseek_config()["translate_model"])
print(call_deepseek('Return JSON: {"status": "ok"}', "ping"))
