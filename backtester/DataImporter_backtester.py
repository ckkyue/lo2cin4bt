"""
DataImporter_backtester.py

【功能說明】
------------------------------------------------------------
本模組為 Lo2cin4BT 回測框架的數據導入工具，負責從外部來源載入回測所需的行情數據，支援多種格式與來源，並確保數據結構與回測引擎相容。

【流程與數據流】
------------------------------------------------------------
- 由 BaseBacktester 調用，載入回測所需的行情數據
- 載入數據後傳遞給 BacktestEngine 進行回測

```mermaid
flowchart TD
    A[BaseBacktester] -->|調用| B[DataImporter]
    B -->|載入數據| C[BacktestEngine]
```

【維護與擴充重點】
------------------------------------------------------------
- 新增/修改數據來源、格式時，請同步更新頂部註解與下游流程
- 若數據結構有變動，需同步更新本檔案與 BacktestEngine
- 數據格式如有調整，請同步通知協作者

【常見易錯點】
------------------------------------------------------------
- 數據來源錯誤或格式不符會導致載入失敗
- 欄位缺失或型態錯誤會影響回測執行
- 數據對齊問題會導致信號產生異常

【範例】
------------------------------------------------------------
- importer = DataImporter()
  data = importer.load_data()

【與其他模組的關聯】
------------------------------------------------------------
- 由 BaseBacktester 調用，數據傳遞給 BacktestEngine
- 需與 BacktestEngine 的數據結構保持一致

【參考】
------------------------------------------------------------
- pandas 官方文件
- Base_backtester.py、BacktestEngine_backtester.py
- 專案 README
"""

import pandas as pd
import numpy as np
import logging
import os
from datetime import datetime, timedelta

try:
    from dataloader.Base_loader import DataLoader
except ImportError as e:
    logging.error(f"無法導入 DataLoader: {str(e)}")
    raise ImportError("請確認 dataloader.Base_loader 模組存在並可導入。")

# 設置日誌
log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "lo2cin4bt", "logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "backtest_errors.log")

class DataImporter:
    """從 dataloader 載入數據，標準化格式，檢測頻率。

    Attributes:
        data (pd.DataFrame): 標準化數據，包含 Time, Open, High, Low, Close, Volume, predictors。
        frequency (str): 自動檢測的數據頻率（day, week, month, hour, minute, 15m, 4h 等）。

    Example:
        >>> importer = DataImporter_backtester()
        >>> data, freq = importer.load_and_standardize_data()
        >>> print(data.head())
        >>> print(f"Frequency: {freq}")
    """

    def __init__(self):
        self.data: pd.DataFrame | None = None
        self.frequency = None
        self.logger = logging.getLogger(self.__class__.__name__)

    def load_and_standardize_data(self, Backtest_id="unknown"):
        """載入並標準化數據，自動檢測頻率。

        Args:
            Backtest_id (str): 回測唯一 ID，用於日誌記錄。

        Returns:
            tuple: (pd.DataFrame, str) - 標準化數據與自動檢測頻率。

        Raises:
            ValueError: 數據載入失敗或格式不正確。
            ImportError: DataLoader 模組無法導入。
        """
        try:
            loader = DataLoader()
            result = loader.load_data()
            if isinstance(result, str) and result == "__SKIP_STATANALYSER__":
                self.data = loader.data
                self.frequency = loader.frequency
                return "__SKIP_STATANALYSER__", self.frequency
            else:
                self.data = result
                self.frequency = loader.frequency
            
            if self.data is None or (isinstance(self.data, pd.DataFrame) and self.data.empty):
                raise ValueError("數據載入失敗或數據為空")

            # 確保必要欄位
            required_cols = ["time", "open", "high", "low", "close", "volume"]
            missing_cols = [col for col in required_cols if col.lower() not in [c.lower() for c in self.data.columns]]
            if missing_cols:
                raise ValueError(f"缺少必要欄位: {missing_cols}")

            # 標準化欄位名稱（只對價格欄位進行標準化，保留預測因子的原始大小寫）
            column_mapping = {}
            new_columns = []
            
            for col in self.data.columns:
                col_lower = col.lower()
                if col_lower == "time":
                    column_mapping[col] = "Time"
                    new_columns.append("Time")
                elif col_lower == "open":
                    column_mapping[col] = "Open"
                    new_columns.append("Open")
                elif col_lower == "high":
                    column_mapping[col] = "High"
                    new_columns.append("High")
                elif col_lower == "low":
                    column_mapping[col] = "Low"
                    new_columns.append("Low")
                elif col_lower == "close":
                    column_mapping[col] = "Close"
                    new_columns.append("Close")
                elif col_lower == "volume":
                    column_mapping[col] = "Volume"
                    new_columns.append("Volume")
                else:
                    # 保留預測因子欄位的原始大小寫
                    new_columns.append(col)
            
            # 應用欄位重命名
            self.data = self.data.rename(columns=column_mapping)

            # 確保 Time 為 datetime64
            if self.data is not None:
                self.data["Time"] = pd.to_datetime(self.data["Time"])
                if self.data["Time"].duplicated().any():
                    raise ValueError("Time 欄位包含重複值")

            # 檢測頻率
            self.frequency = self._detect_frequency()

            return self.data, self.frequency

        except Exception as e:
            self.logger.error(f"數據載入或標準化失敗: {e}", extra={"Backtest_id": Backtest_id})
            raise

    def _detect_frequency(self):
        """自動檢測數據頻率，支援非標準頻率。

        Returns:
            str: 檢測到的頻率（day, week, month, hour, minute, 15m, 4h 等）。
        """
        try:
            if self.data is None:
                raise ValueError("數據未載入")
                
            # 取前 100 筆數據（或全部）計算時間差
            time_diffs = self.data["Time"].diff().dropna().dt.total_seconds()
            if len(time_diffs) == 0:
                raise ValueError("無法計算時間差，數據過少")
            median_diff = np.median(time_diffs)

            # 定義頻率映射（秒）
            freq_map = {
                60: "minute",
                60 * 15: "15m",
                60 * 60: "hour",
                60 * 60 * 4: "4h",
                60 * 60 * 24: "day",
                60 * 60 * 24 * 7: "week",
                60 * 60 * 24 * 30: "month",
            }

            # 尋找最接近的頻率
            closest_diff = min(freq_map.keys(), key=lambda x: abs(x - median_diff))
            return freq_map.get(closest_diff, "custom")

        except Exception as e:
            self.logger.error(f"頻率檢測失敗: {e}", extra={"Backtest_id": "unknown"})
            return "custom"