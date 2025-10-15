from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    TrainingArguments,
    Trainer,
    DataCollatorForLanguageModeling
)
from datasets import Dataset
from peft import LoraConfig, get_peft_model, TaskType
import torch
import json
import os
import re

BASE_MODEL = "EleutherAI/polyglot-ko-1.3b"

# 1. 데이터셋/출력/프롬프트 리스트
config_list = [
    # {
    #     "train_file": "./medical_data.jsonl",
    #     "output_dir": "./medical_data_adapter",
    #     "prompt": "다음 의료 문서에서 핵심 키워드를 추출해주세요.\n\n"
    # },
    # {
    #     "train_file": "./legal_data.jsonl",
    #     "output_dir": "./legal_data_adapter",
    #     "prompt": "다음 법률 문서에서 핵심 키워드를 추출해주세요.\n\n"
    # },
    {
        "train_file": "./tour_data_all.jsonl",
        "output_dir": "./tour_data_all_adapter",
        "prompt": "다음 관광 문서에서 핵심 키워드를 추출해주세요.\n\n"
    }
]

# 2. 공통: LoRA 설정
target_modules = ["query_key_value", "dense", "dense_h_to_4h", "dense_4h_to_h"]
lora_config = LoraConfig(
    r=8, lora_alpha=32, lora_dropout=0.1,
    bias="none", target_modules=target_modules,
    task_type=TaskType.CAUSAL_LM
)

def load_jsonl(file_path):
    if not os.path.exists(file_path):
        print(f"⚠️ 파일이 존재하지 않습니다: {file_path}")
        return []
    data = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            try:
                data.append(json.loads(line.strip()))
            except json.JSONDecodeError as e:
                print(f"⚠️ JSON 파싱 오류 ({file_path}, line {line_num}): {e}")
    print(f"✅ {file_path} 로딩 완료: {len(data)}개 샘플")
    return data

def build_prompt_with_keyword_contexts(text, keywords, prompt_template, max_total_length=730, window=180):
    used_contexts = []
    used_keywords = set()
    total_len = 0

    for kw in keywords:
        for match in re.finditer(re.escape(kw), text):
            idx = match.start()
            start = max(0, idx - window // 2)
            end = min(len(text), idx + len(kw) + window // 2)
            ctx = text[start:end]

            if ctx in used_contexts:
                continue
            if total_len + len(ctx) > max_total_length:
                break

            used_contexts.append(ctx)
            used_keywords.add(kw)
            total_len += len(ctx)
    return used_contexts, list(used_keywords)

def tokenize_function_factory(prompt_template, tokenizer):
    def tokenize_function(examples):
        batch_texts = []
        for i in range(len(examples['text'])):
            text = examples['text'][i]
            keywords = examples['keyword'][i] if isinstance(examples['keyword'][i], list) else [examples['keyword'][i]]
            contexts, selected_keywords = build_prompt_with_keyword_contexts(text, keywords, prompt_template)
            if not contexts or not selected_keywords:
                continue
            prompt = prompt_template + "\n\n".join(contexts) + "\n\n키워드: "
            target = ", ".join(selected_keywords) + tokenizer.eos_token
            full_text = prompt + target
            batch_texts.append(full_text)

        tokenized = tokenizer(batch_texts, padding=True, truncation=True, max_length=512)
        tokenized["labels"] = []
        for i, input_ids in enumerate(tokenized["input_ids"]):
            full_text = batch_texts[i]
            try:
                keyword_start = full_text.index("키워드:")
                prompt_text = full_text[:keyword_start + len("키워드:")]
                prompt_token_count = len(tokenizer(prompt_text, add_special_tokens=False)["input_ids"])
            except ValueError:
                prompt_token_count = len(input_ids)
            masked_labels = [-100] * prompt_token_count + input_ids[prompt_token_count:]
            tokenized["labels"].append(masked_labels)
        return tokenized
    return tokenize_function

# 3. 반복학습
for config in config_list:
    print(f"\n==== {config['output_dir']} 학습 시작 ====")
    # (1) 토크나이저/모델 매번 새로 로딩(권장)
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
        device_map="auto" if torch.cuda.is_available() else None,
        trust_remote_code=True
    )
    model = get_peft_model(model, lora_config)
    print(f"✅ 모델 로딩 완료 - 디바이스: {next(model.parameters()).device}")

    # (2) 데이터 로딩
    train_data = load_jsonl(config['train_file'])
    if not train_data:
        print(f"❌ {config['train_file']}에 데이터가 없습니다. 건너뜀.")
        continue
    train_dataset = Dataset.from_list(train_data)

    # (3) 토큰화
    tokenize_function = tokenize_function_factory(config['prompt'], tokenizer)
    tokenized_train = train_dataset.map(
        tokenize_function,
        batched=True,
        batch_size=32,
        remove_columns=train_dataset.column_names,
        desc="토큰화"
    )

    # (4) 데이터 콜레이터
    data_collator = DataCollatorForLanguageModeling(
        tokenizer=tokenizer,
        mlm=False,
        pad_to_multiple_of=8,
        return_tensors="pt"
    )

    # (5) 학습 인자
    training_args = TrainingArguments(
        output_dir=config['output_dir'],
        overwrite_output_dir=True,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,
        save_strategy="steps",
        save_steps=500,
        save_total_limit=2,
        logging_steps=50,
        num_train_epochs=3,
        learning_rate=2e-4,
        warmup_ratio=0.1,
        fp16=torch.cuda.is_available(),
        dataloader_pin_memory=False,
        remove_unused_columns=False,
        report_to="none",
        seed=42,
        max_grad_norm=1.0,
        weight_decay=0.01,
        adam_beta2=0.999,
        adam_epsilon=1e-8,
        dataloader_drop_last=True,
        ignore_data_skip=True
    )

    # (6) Trainer 및 학습
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized_train,
        data_collator=data_collator,
        tokenizer=tokenizer
    )
    try:
        trainer.train()
        print(f"✅ {config['output_dir']} 학습 완료!")
    except Exception as e:
        print(f"❌ 학습 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        continue

    # (7) 모델/토크나이저/설정 저장
    model.save_pretrained(config['output_dir'])
    tokenizer.save_pretrained(config['output_dir'])
    config_info = {
        "base_model": BASE_MODEL,
        "target_modules": target_modules,
        "lora_config": {
            "r": lora_config.r,
            "lora_alpha": lora_config.lora_alpha,
            "lora_dropout": lora_config.lora_dropout
        },
        "training_samples": len(train_data)
    }
    with open(os.path.join(config['output_dir'], "training_info.json"), "w", encoding="utf-8") as f:
        json.dump(config_info, f, indent=2, ensure_ascii=False)
    print(f"🎉 {config['output_dir']} 저장 완료!")

print("\n💡 모든 도메인 어댑터 학습이 끝났습니다.")