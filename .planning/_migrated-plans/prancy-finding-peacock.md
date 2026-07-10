# Fix Arrow PIL Image Serialization in Kaggle Notebook

## Context

Training ran for 2 hours on T4 x2 — model loaded, LoRA applied, dataset copied and loaded (10,671 samples). Failed at cell-8 (format conversion verification) because:

**Root cause:** `dataset.map(format_for_gemma4)` embeds PIL Images into the messages dict as `{"type": "image", "url": PIL_Image}`. HuggingFace Arrow serialization converts PIL Images to dicts after `.map()`, so `part["url"]` is a dict, not a PIL Image — causing `AttributeError: 'dict' object has no attribute 'size'`.

This also means the collator (cell-16) would fail the same way when accessing `part["url"]` during actual training.

## Change

### File: `notebooks/kaggle_gemma4_lora_train.ipynb`

**Remove the `.map(format_for_gemma4)` step entirely.** Instead, have the collator do the Gemma 4 format conversion lazily during batch construction — avoiding Arrow serialization of PIL Images.

### Cell 13-14 (markdown + format_for_gemma4): Replace with simple skip

Replace cells 13-14 with a single cell that prints a message explaining the collator handles formatting:

```python
# Gemma 4 format conversion is handled lazily in the collator (cell 16)
# to avoid Arrow serialization of PIL Images via dataset.map()
print(f"Dataset ready: {len(dataset)} samples")
print("Gemma 4 format conversion will happen in the collator during training.")
```

### Cell 16 (collator): Rewrite to use raw dataset format

The collator currently expects `part["url"]` to contain a PIL Image (from the `.map()` step). Rewrite it to:
1. Take `ex["images"][0]` as the PIL Image directly from the dataset's `images` column
2. Build Gemma 4 template messages with `{"type": "image", "url": img}` from the raw dataset messages (which have `{"type": "image"}` placeholders)
3. Everything else stays the same

```python
class Gemma4VisionCollator:
    def __init__(self, processor, max_seq_length=2048):
        self.processor = processor
        self.max_seq_length = max_seq_length

    def __call__(self, examples):
        texts = []
        images = []

        for ex in examples:
            raw_messages = ex["messages"]
            pil_image = ex["images"][0] if ex["images"] else None
            images.append(pil_image)

            # Build Gemma 4 template messages from raw dataset format
            template_messages = []
            img_idx = 0
            for msg in raw_messages:
                template_content = []
                for part in msg.get("content", []):
                    if part.get("type") == "image":
                        template_content.append({
                            "type": "image",
                            "url": pil_image,
                        })
                    elif part.get("type") == "text":
                        template_content.append({
                            "type": "text",
                            "text": part["text"],
                        })
                template_messages.append({
                    "role": msg["role"],
                    "content": template_content,
                })

            text = self.processor.apply_chat_template(
                template_messages,
                tokenize=False,
                add_generation_prompt=False,
            )
            texts.append(text)

        batch = self.processor(
            text=texts,
            images=images,
            padding=True,
            truncation=True,
            max_length=self.max_seq_length,
            return_tensors="pt",
        )

        labels = batch["input_ids"].clone()
        batch["labels"] = labels
        return batch


collator = Gemma4VisionCollator(processor, max_seq_length=MAX_SEQ_LENGTH)
test_batch = collator(dataset[:2])
print("Collator output keys:", list(test_batch.keys()))
for k, v in test_batch.items():
    if isinstance(v, torch.Tensor):
        print(f"  {k}: shape={v.shape}, dtype={v.dtype}")
    elif isinstance(v, list):
        print(f"  {k}: list of {len(v)} items")
    else:
        print(f"  {k}: {type(v).__name__}")
```

### Cells 0-12, 15, 17-27: No changes

All other cells stay as-is. The GPU check, P100 guard, model loading, LoRA, dataset copy, training args, SFTTrainer, save, and verify cells are all correct.

## Bonus: Speed Improvement

Removing the `.map(format_for_gemma4)` step eliminates the 114-minute serialization overhead. The collator now does format conversion per-batch (2 samples at a time), which is instantaneous.

## Verification

1. Push to Kaggle
2. User runs with T4 x2 + Internet + dataset attached
3. Cells 0-12 pass (config, install, GPU check, processor, model, LoRA, dataset copy)
4. Cell 13-14 (new skip cell) passes instantly
5. Cell 16 (collator test) passes — processes 2 samples through processor
6. Training proceeds through 500 steps
7. Adapter saved, download from Output tab
