import json

nb_path = "/Users/echo/kaggle/gemma4-agent-dashboard/notebooks/colab_real_gemma_evaluator.ipynb"
with open(nb_path, "r", encoding="utf-8") as f:
    nb = json.load(f)

bulletproof_call_llm = """def call_llm(messages, temperature=0.2, max_new_tokens=1024):
    \"\"\"二重安全ネット付きの推論関数 (TemplateError 完全防止 & 確実な発話生成)\"\"\"
    normalized = []
    sys_prefix = ""
    for m in messages:
        role = m["role"]
        if role == "system":
            sys_prefix += m["content"].strip() + "\\n\\n"
            continue
            
        # ロールを user と assistant に統一
        r = "assistant" if role in ["assistant", "model"] else "user"
        content = m.get("content", "").strip()
        if not content:
            content = "(empty)"
            
        if r == "user" and sys_prefix:
            content = sys_prefix + content
            sys_prefix = ""
            
        if not normalized:
            normalized.append({"role": r, "content": content})
        elif normalized[-1]["role"] == r:
            normalized[-1]["content"] += "\\n\\n" + content
        else:
            normalized.append({"role": r, "content": content})
            
    if not normalized and sys_prefix:
        normalized.append({"role": "user", "content": sys_prefix})
        
    # テンプレート適用 (失敗時は Gemma 公式タグで直接フォールバック)
    try:
        prompt_text = tokenizer.apply_chat_template(
            normalized,
            tokenize=False,
            add_generation_prompt=True
        )
    except Exception as e:
        # 万が一 Jinja が失敗しても特殊トークンで直結生成
        prompt_text = ""
        for m in normalized:
            tag = "model" if m["role"] == "assistant" else "user"
            prompt_text += f"<start_of_turn>{tag}\\n{m['content']}<end_of_turn>\\n"
        prompt_text += "<start_of_turn>model\\n"
        
    inputs = tokenizer(prompt_text, return_tensors="pt").to(model.device)
    input_len = inputs["input_ids"].shape[1]
    
    t0 = time.time()
    with torch.inference_mode():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=(temperature > 0.0),
            temperature=max(temperature, 1e-4),
            pad_token_id=tokenizer.eos_token_id
        )
    elapsed = time.time() - t0
    resp = tokenizer.decode(outputs[0][input_len:], skip_special_tokens=True).strip()
    return resp, elapsed
"""

cell3_src = "".join(nb["cells"][3]["source"])
idx = cell3_src.find("def call_llm(")
if idx != -1:
    end_idx = cell3_src.find('print("[Engine] ✅ 推論関数 call_llm 準備完了。")')
    cell3_src = cell3_src[:idx] + bulletproof_call_llm + "\n" + cell3_src[end_idx:]
    nb["cells"][3]["source"] = [l + "\n" for l in cell3_src.split("\n")[:-1]]

# Cell 7 の role も assistant に統一
cell7_src = "".join(nb["cells"][7]["source"])
cell7_src = cell7_src.replace('{"role": "model", "content": resp}', '{"role": "assistant", "content": resp if resp else "(no tool call)"}')
nb["cells"][7]["source"] = [l + "\n" for l in cell7_src.split("\n")[:-1]]

with open(nb_path, "w", encoding="utf-8") as f:
    json.dump(nb, f, indent=2, ensure_ascii=False)
print("Updated notebook with bulletproof call_llm.")
