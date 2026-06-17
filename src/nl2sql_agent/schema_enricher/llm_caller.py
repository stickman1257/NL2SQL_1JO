"""Schema Enricher용 LLM Caller — CUDA(transformers) / MLX 백엔드.

Mac(Apple Silicon) → MLX, Linux/Windows NVIDIA GPU → CUDA 를 지원한다.
``backend="auto"`` 로 플랫폼에 맞게 자동 선택할 수 있다.

```python
from nl2sql_agent.schema_enricher.llm_caller import create_llm_caller

# 자동 선택 (Mac→MLX, CUDA GPU→cuda)
caller = create_llm_caller(backend="auto")

# 명시적 선택
caller = create_llm_caller(backend="cuda", model_name="Qwen/Qwen2.5-3B-Instruct")
caller = create_llm_caller(backend="mlx", model_name="mlx-community/Qwen2.5-3B-Instruct-4bit")
```
"""

from __future__ import annotations

import platform
from functools import lru_cache
from typing import Callable, Dict, List, Optional

LLMCaller = Callable[[List[Dict]], str]

DEFAULT_CUDA_MODEL = "Qwen/Qwen2.5-3B-Instruct"
DEFAULT_MLX_MODEL = "mlx-community/Qwen2.5-3B-Instruct-4bit"
SUPPORTED_BACKENDS = ("auto", "cuda", "transformers", "gpu", "mlx")


def is_apple_silicon() -> bool:
    return platform.system() == "Darwin" and platform.machine().lower() in {"arm64", "aarch64"}


def is_mlx_available() -> bool:
    try:
        import mlx_lm  # noqa: F401
        return True
    except ImportError:
        return False


def is_cuda_available() -> bool:
    try:
        import torch

        return torch.cuda.is_available()
    except ImportError:
        return False


def detect_backend() -> str:
    """실행 환경에 맞는 백엔드를 추론한다. Mac+MLX → mlx, CUDA GPU → cuda."""
    if is_apple_silicon() and is_mlx_available():
        return "mlx"
    if is_cuda_available():
        return "cuda"
    if is_apple_silicon():
        return "mlx"
    return "cuda"


def normalize_backend(backend: str) -> str:
    normalized = (backend or "auto").lower().strip()
    if normalized == "auto":
        return detect_backend()
    if normalized in {"cuda", "transformers", "gpu"}:
        return "cuda"
    if normalized == "mlx":
        return "mlx"
    raise ValueError(f"지원하지 않는 backend: {backend!r} ({', '.join(SUPPORTED_BACKENDS)})")


def resolve_model_path(backend: str, path: str = "", path_cuda: str = "", path_mlx: str = "") -> str:
    """백엔드별 기본 모델 경로를 해석한다. path가 있으면 우선 사용."""
    if path:
        return path
    resolved = normalize_backend(backend)
    if resolved == "mlx":
        return path_mlx or DEFAULT_MLX_MODEL
    return path_cuda or DEFAULT_CUDA_MODEL


@lru_cache(maxsize=4)
def _load_transformers_model(
    model_name: str,
    load_in_4bit: bool,
    device_map: str,
    dtype: str,
):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    print(f"[LLM] CUDA/transformers 모델 로딩 중: {model_name}")
    if torch.cuda.is_available():
        print(f"[LLM] GPU: {torch.cuda.get_device_name(0)}")
    else:
        print("[LLM] CUDA 미탐지 — CPU 또는 device_map 자동 배치로 실행")

    quantization_config = None
    if load_in_4bit:
        from transformers import BitsAndBytesConfig

        quantization_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
        )

    torch_dtype = _resolve_dtype(torch, dtype)
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype=torch_dtype,
        device_map=device_map,
        trust_remote_code=True,
        quantization_config=quantization_config,
    )
    model.eval()
    print("[LLM] 모델 로딩 완료")
    return model, tokenizer


@lru_cache(maxsize=2)
def _load_mlx_model(model_name: str):
    from mlx_lm import load

    print(f"[LLM] MLX 모델 로딩 중: {model_name}")
    model, tokenizer = load(model_name)
    print("[LLM] 모델 로딩 완료")
    return model, tokenizer


def _resolve_dtype(torch_module, dtype: str):
    if dtype == "auto":
        return "auto"
    if dtype in {"float16", "fp16"}:
        return torch_module.float16
    if dtype in {"bfloat16", "bf16"}:
        return torch_module.bfloat16
    if dtype in {"float32", "fp32"}:
        return torch_module.float32
    return "auto"


def create_transformers_caller(
    model_name: str = DEFAULT_CUDA_MODEL,
    max_tokens: int = 512,
    temperature: float = 0.3,
    top_p: float = 0.9,
    device_map: str = "auto",
    load_in_4bit: bool = True,
    dtype: str = "auto",
) -> LLMCaller:
    """HuggingFace transformers + CUDA(NVIDIA GPU) 기반 caller."""
    model, tokenizer = _load_transformers_model(model_name, load_in_4bit, device_map, dtype)

    def llm_caller(messages: list) -> str:
        import torch

        prompt = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = tokenizer([prompt], return_tensors="pt")
        inputs = {key: value.to(model.device) for key, value in inputs.items()}
        do_sample = temperature > 0
        generation_kwargs = {
            "max_new_tokens": max_tokens,
            "do_sample": do_sample,
            "pad_token_id": tokenizer.eos_token_id,
        }
        if do_sample:
            generation_kwargs["temperature"] = temperature
            generation_kwargs["top_p"] = top_p
        with torch.no_grad():
            generated = model.generate(**inputs, **generation_kwargs)
        output_ids = generated[0][inputs["input_ids"].shape[-1] :]
        return tokenizer.decode(output_ids, skip_special_tokens=True).strip()

    return llm_caller


def create_mlx_caller(
    model_name: str = DEFAULT_MLX_MODEL,
    max_tokens: int = 512,
    temperature: float = 0.3,
    top_p: float = 0.9,
    verbose: bool = False,
) -> LLMCaller:
    """Apple Silicon MLX 기반 caller (Mac 전용)."""
    try:
        from mlx_lm import generate
        from mlx_lm.sample_utils import make_sampler
    except ImportError as exc:
        raise ImportError(
            "MLX 백엔드를 사용하려면 Apple Silicon Mac에 mlx-lm을 설치하세요: "
            "pip install mlx mlx-lm"
        ) from exc

    model, tokenizer = _load_mlx_model(model_name)
    sampler = make_sampler(temp=temperature, top_p=top_p)

    def llm_caller(messages: list) -> str:
        prompt = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        response = generate(
            model,
            tokenizer,
            prompt=prompt,
            max_tokens=max_tokens,
            sampler=sampler,
            verbose=verbose,
        )
        return response.strip()

    return llm_caller


def create_llm_caller(
    backend: str = "auto",
    model_name: Optional[str] = None,
    max_tokens: int = 512,
    temperature: float = 0.3,
    top_p: float = 0.9,
    device_map: str = "auto",
    load_in_4bit: bool = True,
    dtype: str = "auto",
    verbose: bool = False,
    path_cuda: str = "",
    path_mlx: str = "",
) -> LLMCaller:
    """백엔드에 맞는 LLM caller를 생성한다.

    Args:
        backend: ``auto`` | ``cuda`` | ``mlx`` (auto = 환경 자동 감지)
        model_name: 공통 모델 경로 (지정 시 path_cuda/path_mlx보다 우선)
        path_cuda: CUDA 전용 모델 (model_name 미지정 시)
        path_mlx: MLX 전용 모델 (model_name 미지정 시)
    """
    resolved_backend = normalize_backend(backend)
    resolved_model = resolve_model_path(
        resolved_backend,
        path=model_name or "",
        path_cuda=path_cuda,
        path_mlx=path_mlx,
    )
    print(f"[LLM] backend={resolved_backend}, model={resolved_model}")

    if resolved_backend == "cuda":
        return create_transformers_caller(
            model_name=resolved_model,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            device_map=device_map,
            load_in_4bit=load_in_4bit,
            dtype=dtype,
        )
    return create_mlx_caller(
        model_name=resolved_model,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        verbose=verbose,
    )
