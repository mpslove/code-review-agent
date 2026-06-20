"""
Code Review Agent — Multi-Agent AI Code Review

A multi-agent system that performs automated code review using 4 specialized
LLM reviewers (Security, Performance, Architecture, Style) with multi-round
voting, false-positive verification, and ensemble mode for production-quality output.

Usage:
    python -m src.main --diff-file path/to/diff.txt
    python -m src.main --pr owner/repo#123
    git diff main | python -m src.main

Requirements:
    - Python 3.10+
    - DeepSeek API key (set DEEPSEEK_API_KEY env var)
    - No GPU required (API-based)
"""

from setuptools import setup, find_packages

setup(
    name="code-review-agent",
    version="1.0.0",
    description="Multi-Agent AI Code Review System",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="Hermes Agent",
    python_requires=">=3.10",
    packages=find_packages(),
    install_requires=[
        "requests>=2.28",
        "pydantic>=2.0",
        "chromadb>=0.4",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0",
            "pytest-cov",
        ],
    },
    entry_points={
        "console_scripts": [
            "cr-agent=src.main:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Quality Assurance",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ],
)
