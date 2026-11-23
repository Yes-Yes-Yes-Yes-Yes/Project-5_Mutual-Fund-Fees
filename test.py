from typing_extensions import Self, Callable

import os
import polars as pl

# TEST.PY --- 
#   Handles all tasks related to debugging code or testing existing data.



class TEST:
    def __init__(self, project_directory_path: str = r'.'):
        # Resetting the log and error files
        self._log_path: str = os.path.join(project_directory_path, '_OUTPUT.txt');
        with open(self._log_path, 'w', encoding = 'utf-8') as log_file: pass;
        self._error_path: str = os.path.join(project_directory_path, '_ERROR.txt');
        with open(self._error_path, 'w', encoding = 'utf-8') as log_file: pass;


    # log_output(output) QUICKLY logs dataFrames/text into _OUTPUT.txt
    def log_output(self, output: str | pl.DataFrame | pl.LazyFrame) -> None:
        with open(self._log_path, 'a', encoding = 'utf-8') as log_file:
            with pl.Config(fmt_str_lengths = 1000000, tbl_rows = -1, tbl_cols = -1):
                if isinstance(output, pl.LazyFrame): log_file.write(f'{output.collect()}\n\n');
                else:                                log_file.write(f'{output}\n');
    
    
    # _log_output(output) QUICKLY logs dataFrames/text into _ERROR.txt
    def log_error(self, output: str | pl.DataFrame | pl.LazyFrame) -> None:
            with open(self._error_path, 'a', encoding = 'utf-8') as log_file:
                with pl.Config(fmt_str_lengths = 1000000, tbl_rows = -1, tbl_cols = -1):
                    if isinstance(output, pl.LazyFrame): log_file.write(f'{output.collect()}\n\n');
                    else:                                log_file.write(f'{output}\n');
