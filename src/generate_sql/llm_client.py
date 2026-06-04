import re
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from .config import ModelConfig


class BaseLLMClient(ABC):
    @abstractmethod
    def chat(self, messages: List[Dict[str, str]], max_new_tokens: Optional[int] = None, temperature: Optional[float] = None) -> str:
        raise NotImplementedError


class TransformersLLMClient(BaseLLMClient):
    def __init__(self, config: ModelConfig):
        self.config = config
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        dtype = self._resolve_dtype(torch, config.dtype)
        quantization_config = None
        if config.load_in_4bit:
            from transformers import BitsAndBytesConfig

            quantization_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4",
            )
        self.tokenizer = AutoTokenizer.from_pretrained(config.model_name, trust_remote_code=config.trust_remote_code)
        self.model = AutoModelForCausalLM.from_pretrained(
            config.model_name,
            torch_dtype=dtype,
            device_map=config.device_map,
            trust_remote_code=config.trust_remote_code,
            quantization_config=quantization_config,
        )
        self.model.eval()

    def chat(self, messages: List[Dict[str, str]], max_new_tokens: Optional[int] = None, temperature: Optional[float] = None) -> str:
        import torch

        text = self._apply_chat_template(messages)
        inputs = self.tokenizer([text], return_tensors="pt")
        inputs = {key: value.to(self.model.device) for key, value in inputs.items()}
        temp = self.config.temperature if temperature is None else temperature
        do_sample = temp is not None and temp > 0
        generation_kwargs = {
            "max_new_tokens": max_new_tokens or self.config.max_new_tokens,
            "do_sample": do_sample,
            "repetition_penalty": self.config.repetition_penalty,
            "pad_token_id": self.tokenizer.eos_token_id,
        }
        if do_sample:
            generation_kwargs["temperature"] = temp
            generation_kwargs["top_p"] = self.config.top_p
        with torch.no_grad():
            generated = self.model.generate(**inputs, **generation_kwargs)
        output_ids = generated[0][inputs["input_ids"].shape[-1] :]
        text = self.tokenizer.decode(output_ids, skip_special_tokens=True)
        return self._strip_thinking(text).strip()

    def _apply_chat_template(self, messages: List[Dict[str, str]]) -> str:
        kwargs = {"tokenize": False, "add_generation_prompt": True}
        if self.config.enable_thinking is not None:
            try:
                return self.tokenizer.apply_chat_template(messages, enable_thinking=self.config.enable_thinking, **kwargs)
            except TypeError:
                pass
        return self.tokenizer.apply_chat_template(messages, **kwargs)

    def _resolve_dtype(self, torch_module, dtype: str):
        if dtype == "auto":
            return "auto"
        if dtype in {"float16", "fp16"}:
            return torch_module.float16
        if dtype in {"bfloat16", "bf16"}:
            return torch_module.bfloat16
        if dtype in {"float32", "fp32"}:
            return torch_module.float32
        return "auto"

    def _strip_thinking(self, text: str) -> str:
        return re.sub(r"(?is)<think>.*?</think>", "", text).strip()


class OpenAICompatibleLLMClient(BaseLLMClient):
    def __init__(self, config: ModelConfig):
        self.config = config
        from openai import OpenAI

        self.client = OpenAI(base_url=config.openai_base_url, api_key=config.openai_api_key)

    def chat(self, messages: List[Dict[str, str]], max_new_tokens: Optional[int] = None, temperature: Optional[float] = None) -> str:
        response = self.client.chat.completions.create(
            model=self.config.model_name,
            messages=messages,
            max_tokens=max_new_tokens or self.config.max_new_tokens,
            temperature=self.config.temperature if temperature is None else temperature,
        )
        return response.choices[0].message.content or ""


class LLMClientFactory:
    @staticmethod
    def create(config: ModelConfig) -> BaseLLMClient:
        if config.backend == "transformers":
            return TransformersLLMClient(config)
        if config.backend in {"openai", "openai-compatible", "vllm"}:
            return OpenAICompatibleLLMClient(config)
        raise ValueError(f"Unsupported backend: {config.backend}")
