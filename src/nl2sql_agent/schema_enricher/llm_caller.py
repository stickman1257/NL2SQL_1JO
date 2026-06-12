"""MLX 기반 LLM Caller — Qwen 2.5 3B Instruct.

DBExplorerAgent의 llm_caller로 사용된다.
```python
from .llm_caller import create_mlx_caller
caller = create_mlx_caller("mlx-community/Qwen2.5-3B-Instruct-4bit")
response = caller(messages)
```
"""

from __future__ import annotations

from functools import lru_cache
from mlx_lm import load, generate
from mlx_lm.sample_utils import make_sampler
from transformers import AutoTokenizer


@lru_cache(maxsize=1)
def _load_model(model_name: str):
    """모델을 1번만 로드하고 캐싱한다."""
    print(f"[LLM] 모델 로딩 중: {model_name}")
    model, tokenizer = load(model_name)
    print("[LLM] 모델 로딩 완료")
    return model, tokenizer


def create_mlx_caller(
    model_name: str = "mlx-community/Qwen2.5-3B-Instruct-4bit",
    max_tokens: int = 512,
    temperature: float = 0.3,
    top_p: float = 0.9,
    verbose: bool = False,
):
    """MLX 모델을 로드하고 messages → response 함수를 반환한다.

    Args:
        model_name: HuggingFace의 MLX 모델명
        max_tokens: 생성 최대 토큰 수
        temperature: 샘플링 온도 (0.0=결정적, 높을수록 다양)
        top_p: nucleus sampling
        verbose: 생성 과정 출력 여부

    Returns:
        messages (list[dict]) 를 받아 str 을 반환하는 함수
    """
    model, tokenizer = _load_model(model_name)
    sampler = make_sampler(temp=temperature, top_p=top_p)

    def llm_caller(messages: list[dict]) -> str:
        """DBExplorerAgent가 사용하는 llm_caller 인터페이스."""
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
