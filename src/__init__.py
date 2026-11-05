"""
基于大语言模型的上市公司公告风险识别与解释助手。

对外主要入口：
- `Pipeline.run(raw_text, pages)` -> `AnalysisResult`
- `ingest.load_any(filename, data)` -> (raw_text, pages)
"""
# -*- coding: utf-8 -*-

__version__ = "1.0.0"

from .config import get_config
from .pipeline import Pipeline
from .schemas import AnalysisResult

__all__ = ["Pipeline", "AnalysisResult", "get_config", "__version__"]
