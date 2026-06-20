"""
Code Review Agent — 配置中心
"""
import os
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class Config:
    # LLM
    llm_provider: str = os.getenv("CR_LLM_PROVIDER", "deepseek")
    llm_model: str = os.getenv("CR_LLM_MODEL", "deepseek-v4-flash")
    llm_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    llm_base_url: str = os.getenv("CR_LLM_BASE_URL", "https://api.deepseek.com/v1")
    llm_temperature: float = 0.0  # 0 = deterministic
    
    # Review
    max_diff_size: int = 200_000  # 200KB
    max_review_timeout: int = 300  # 5分钟超时
    max_retries: int = 3
    
    # RAG
    chroma_persist_dir: str = "./data/chroma"
    chunk_size: int = 500  # tokens
    chunk_overlap: int = 50
    
    # Output
    output_dir: str = "./reports"

config = Config()
