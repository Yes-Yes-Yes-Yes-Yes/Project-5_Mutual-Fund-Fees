from abc import ABC, abstractmethod
from itertools import chain
from typing_extensions import Self, Callable

import os
import io
import zipfile as zf
import urllib.request
import yfinance as yf
import polars as pl

from test import TEST

# INPUT.PY --- 
#   Handles all tasks related to reading + cleaning data.



class INPUT_DIRECTORY(ABC):
    def __init__(self, test: TEST, project_directory_path: str = r'.'):
        self._test = test;
        self._globalInput_directory_path: str = os.path.join(project_directory_path, r'data');
        if not os.path.exists(self._globalInput_directory_path): os.mkdir(self._globalInput_directory_path);


    # read_files(fileFilter, dataGroup) reads ALL files from '~\data\' AND _.parquet files from '~\data\<dataGroup>\' directories and EITHER:
    #   A. Reads all _.parquet files.
    #   B. Reads ALL other fileTypes, formats the lazyFrame, applies the given filters per file, and converts the lazyFrame into a _.parquet file to be stored inside of the '~\data\<dataGroup>\' directory.
    # Then return a dictionary of lazyFrames.
    #   - The file_name MUST added inside of fileFiler to be read.
    #   - If a _.parquet file and another file share the same name, the OTHER file will NOT be read in to enable faster reading of data.
    def read_files(self, fileFilter: dict[str, list[Callable]], dataGroup: str) -> dict[str, pl.LazyFrame]:
        dataGroup_directory_path: str = os.path.join(self._globalInput_directory_path, dataGroup);
        if not os.path.exists(dataGroup_directory_path): os.mkdir(dataGroup_directory_path);

        globalEntries:    os._ScandirIterator = [entry for entry in os.scandir(self._globalInput_directory_path)
                                                 if entry.is_file()];
        dataGroupEntries: os._ScandirIterator = [entry for entry in os.scandir(dataGroup_directory_path)
                                                 if entry.is_file() and entry.name.endswith('.parquet')];
        allEntries: os._ScandirIterator = chain(globalEntries, dataGroupEntries);
        allEntries = sorted(allEntries, key = lambda entry: entry.stat().st_mtime, reverse = True);

        lazyFrame_files: dict[str, pl.LazyFrame] = {};
        for entry in allEntries:
            file_name:      str = os.path.splitext(entry.name)[0];
            file_extension: str = os.path.splitext(entry.name)[1];
            if file_name not in fileFilter.keys():  continue;
            if file_name in lazyFrame_files.keys(): continue;

            if entry.name.endswith('.parquet'):  lazyFrame_files[file_name] = pl.scan_parquet(entry.path);         continue;
            else:                                lazyFrame_files[file_name] = self._format_lazyFrame(file_name, entry.path);
            
            for filter in fileFilter[file_name]: lazyFrame_files[file_name] = lazyFrame_files[file_name].pipe(filter);
            lazyFrame_files[file_name].sink_parquet(path = os.path.join(dataGroup_directory_path, entry.name.replace(file_extension, '.parquet')));
        return lazyFrame_files;


    @abstractmethod
    # _format_lazyFrame(file_name, path) reformats the lazyFrame to correct conventions/dataTypes.
    #   - Verifies the data and if an issue is found, logs the file which caused the issue AND immediately terminates the program.
    def _format_lazyFrame(self, file_name: str, path: str) -> pl.LazyFrame: pass


    # _remove_nullDupes(file_name, lazyFrame_file) removes NULL values across ALL columns, and duplicate-values selected columns from the lazyFrame.
    #   - Logs the number of NULL values removed OR dupliate-values removed.
    def _remove_nullDupes(self, file_name: str, lazyFrame_file: pl.LazyFrame, dupeBy: list[str] = ['Date']) -> pl.LazyFrame:
        # FUNCTIONS FOR REMOVE_NULLDUPES() ---
        #   * remove_nullValues() removes all rows in which there exists a NULL value in ANY column.
        def remove_nullValues() -> pl.LazyFrame:
            lazyFrame: pl.LazyFrame = lazyFrame_file.drop_nulls();
            numRemoved: int = lazyFrame_file.collect().height - lazyFrame.collect().height;
            if (numRemoved != 0): self._test.log_output(f' * {file_name}: {numRemoved} ROWS WERE REMOVED DUE TO NULL VALUES!');
            return lazyFrame;
        #   * remove_duplicateValues() removes duplicate Dates.
        def remove_duplicateValues() -> pl.LazyFrame:
            lazyFrame: pl.LazyFrame = lazyFrame_file.unique(subset = dupeBy, keep = 'first', maintain_order = True);
            numRemoved: int = lazyFrame_file.collect().height - lazyFrame.collect().height;
            if (numRemoved != 0): self._test.log_output(f' * {file_name}: {numRemoved} ROWS WERE REMOVED DUE TO DUPLICATE VALUES!');
            return lazyFrame;
        
        # RUNNING REMOVE_NULLDUPES() ---
        lazyFrame_file = remove_nullValues();
        lazyFrame_file = remove_duplicateValues();
        lazyFrame_file = lazyFrame_file.sort(dupeBy);
        return lazyFrame_file;





class YAHOO__TICKER(INPUT_DIRECTORY):
    # download_tickerFiles(tickerNames, interval)...
    #   1. Downloads information about given `tickerNames`s from Yahoo Finance.
    #   2. Stores the information as _.csv files in the self._globalInput_directory_path.
    def download_tickerFiles(self, tickerNames: list[str], interval: str = '1d') -> Self:
        #   1. If the given files already exist in the self._globalInput_directory_path, skip redownloading the files.
        if all(f'{tickerName}.csv' in os.listdir(self._globalInput_directory_path) for tickerName in tickerNames): return self;
        #   2. Otherwise, download the files from the given source.
        for tickerName in tickerNames:
            ticker: yf.Ticker = yf.Ticker(tickerName);
            dataFrame: yf.DataFrame = ticker.history(period = 'max', interval = interval,
                                                     auto_adjust = False, actions = True);
            if dataFrame.empty: continue;
            dataFrame.to_csv(os.path.join(self._globalInput_directory_path, f'{tickerName}.csv'), index_label = 'Date');
        return self;
    

    def _format_lazyFrame(self, file_name: str, path: str) -> pl.LazyFrame:
        lazyFrame_file: pl.LazyFrame = pl.scan_csv(path, infer_schema = False, has_header = True);
        # Defining column names, dataTypes, and column-specfic requirements.
        column_dataTypes: dict[str, pl.Expr] = {
            'Date':          (pl.col('Date').str.to_datetime(format = '%Y-%m-%d %H:%M:%S%z').dt.date()).alias('Date'),
            'Close':         (pl.col('Close').cast(pl.Float64)).alias('Close'),
            'Dividends':     (pl.col('Dividends').cast(pl.Float64)).alias('Dividend'),
            'Capital Gains': (pl.col('Capital Gains').cast(pl.Float64)).alias('Capital-Gain')
        };
        column_dataTypes = {col : column_dataTypes[col] for col in column_dataTypes.keys()
                            if col in lazyFrame_file.collect_schema().names()};
        lazyFrame_file = lazyFrame_file.select(column_dataTypes.values());
        lazyFrame_file = self._remove_nullDupes(file_name = file_name, lazyFrame_file = lazyFrame_file);

        # Requirements GIVEN Specific Columns:
        #   1. Calculate the net-total-returns INCLUDING .
        if all(col in lazyFrame_file.collect_schema().names() for col in ['Date', 'Close', 'Dividend', 'Capital-Gain']):
            lazyFrame_file = (lazyFrame_file
                              .sort('Date')
                              .with_columns( (((pl.col('Close') + pl.col('Dividend') + pl.col('Capital-Gain')) / pl.col('Close').shift(1)) - 1).alias('Net-Total-Return') )
                              .drop_nulls()
                              .drop(['Close', 'Dividend', 'Capital-Gain']));
        return lazyFrame_file;



class KENNETH__FAMA(INPUT_DIRECTORY):
    def __init__(self, test: TEST, project_directory_path: str = r'.'):
            super().__init__(test = test, project_directory_path = project_directory_path);
            self.__kenneth_url: str = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/";

    # download_factorFiles(fileNames)...
    #   1. Downloads information about given `fileNames`s from Dartsmouth.
    #   2. Stores the information as _.csv files in the self._globalInput_directory_path.
    def download_factorFiles(self, fileNames: list[str]) -> Self:
        #   1. If the given files already exist in the self._globalInput_directory_path, skip re-downloading the files.
        if all(f'{fileName}.csv' in os.listdir(self._globalInput_directory_path) for fileName in fileNames): return self;
        #   2. Otherwise, download the files from the given source.
        for fileName in fileNames:
            with urllib.request.urlopen(f'{self.__kenneth_url}{fileName}_CSV.zip', timeout = 60) as httpResponse: 
                zipFile: zf.ZipFile = zf.ZipFile(io.BytesIO(httpResponse.read()));
                csvPath: str = [name for name in zipFile.namelist()
                                if name.lower().endswith('.csv')][0];
                with open(os.path.join(self._globalInput_directory_path, csvPath), 'wb') as file: file.write(zipFile.read(csvPath)); 
        return self;


    def _format_lazyFrame(self, file_name: str, path: str) -> pl.LazyFrame:
        lazyFrame_file: pl.LazyFrame = pl.scan_csv(path, infer_schema = False, has_header = True, skip_lines = 4);
        lazyFrame_file  = lazyFrame_file.filter(pl.int_range(0, pl.len()) <= 1202);
        # Defining column names, dataTypes, and column-specfic requirements.
        column_dataTypes: dict[str, pl.Expr] = {
            '':          (pl.col('').str.strip_chars().str.to_date(format = '%Y%m')).alias('Date'),
            'RF':        (pl.col('RF').str.strip_chars().cast(pl.Float64)  / 100).alias('Risk-Free-Rate'), 
            'Mkt-RF':    (pl.col('Mkt-RF').str.strip_chars().cast(pl.Float64) / 100).alias('Market-Excess-Return'),
            'SMB':       (pl.col('SMB').str.strip_chars().cast(pl.Float64) / 100).alias('Small-Minus-Big'),
            'HML':       (pl.col('HML').str.strip_chars().cast(pl.Float64) / 100).alias('Huge-Minus-Low')
        };
        column_dataTypes = {col : column_dataTypes[col] for col in column_dataTypes.keys()
                            if col in lazyFrame_file.collect_schema().names()};
        lazyFrame_file = lazyFrame_file.select(column_dataTypes.values());
        lazyFrame_file = self._remove_nullDupes(file_name = file_name, lazyFrame_file = lazyFrame_file);
        return lazyFrame_file;



class KENNETH__MOM(INPUT_DIRECTORY):
    def __init__(self, test: TEST, project_directory_path: str = r'.'):
            super().__init__(test = test, project_directory_path = project_directory_path);
            self.__kenneth_url: str = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/";

    # download_factorFiles(fileNames)...
    #   1. Downloads information about given `fileNames`s from Dartsmouth.
    #   2. Stores the information as _.csv files in the self._globalInput_directory_path.
    def download_factorFiles(self, fileNames: list[str]) -> Self:
        #   1. If the given files already exist in the self._globalInput_directory_path, skip re-downloading the files.
        if all(f'{fileName}.csv' in os.listdir(self._globalInput_directory_path) for fileName in fileNames): return self;
        #   2. Otherwise, download the files from the given source.
        for fileName in fileNames:
            with urllib.request.urlopen(f'{self.__kenneth_url}{fileName}_CSV.zip', timeout = 60) as httpResponse: 
                zipFile: zf.ZipFile = zf.ZipFile(io.BytesIO(httpResponse.read()));
                csvPath: str = [name for name in zipFile.namelist()
                                if name.lower().endswith('.csv')][0];
                with open(os.path.join(self._globalInput_directory_path, csvPath), 'wb') as file: file.write(zipFile.read(csvPath)); 
        return self;


    def _format_lazyFrame(self, file_name: str, path: str) -> pl.LazyFrame:
        lazyFrame_file: pl.LazyFrame = pl.scan_csv(path, infer_schema = False, has_header = True, skip_lines = 13);
        lazyFrame_file  = lazyFrame_file.filter(pl.int_range(0, pl.len()) <= 1196);
        # Defining column names, dataTypes, and column-specfic requirements.
        column_dataTypes: dict[str, pl.Expr] = {
            '':          (pl.col('').str.strip_chars().str.to_date(format = '%Y%m')).alias('Date'),
            'Mom':       (pl.col('Mom').str.strip_chars().cast(pl.Float64) / 100).alias('Momentum')
        };
        column_dataTypes = {col : column_dataTypes[col] for col in column_dataTypes.keys()
                            if col in lazyFrame_file.collect_schema().names()};
        lazyFrame_file = lazyFrame_file.select(column_dataTypes.values());
        lazyFrame_file = self._remove_nullDupes(file_name = file_name, lazyFrame_file = lazyFrame_file);

        # Requirements GIVEN Specific Columns:
        #   1. Removing missing data from the 'Mom' column.
        if all(col in lazyFrame_file.collect_schema().names() for col in ['Momentum']):
            lazyFrame: pl.LazyFrame = lazyFrame_file.filter(~pl.col('Momentum').is_in([-0.9999, -9.99]));
            numRemoved: int = lazyFrame_file.collect().height - lazyFrame.collect().height;
            if (numRemoved != 0): self._test.log_output(f' * {file_name}: {numRemoved} ROWS WERE REMOVED DUE TO NULL VALUES!');
            lazyFrame_file = lazyFrame;
        return lazyFrame_file;



class EDGAR__EXPENSE_RATIO(INPUT_DIRECTORY):
    def _format_lazyFrame(self, file_name: str, path: str) -> pl.LazyFrame:
        lazyFrame_file: pl.LazyFrame = pl.scan_csv(path, infer_schema = False, has_header = True);
        lazyFrame_file = lazyFrame_file.drop_nulls();
        # Defining column names, dataTypes, and column-specfic requirements.
        column_dataTypes: dict[str, pl.Expr] = {
            'fiscal_year_end':   (pl.col('fiscal_year_end').str.to_date(format = '%Y-%m-%d').dt.month_start()).alias('Date'),
            'ticker':            (pl.col('ticker').cast(pl.String)).alias('Ticker'),
            'expense_ratio_pct': (pl.col('expense_ratio_pct').cast(pl.Float64) / 100).alias('Expense_Ratio')
        }
        column_dataTypes = {col : column_dataTypes[col] for col in column_dataTypes.keys()
                            if col in lazyFrame_file.collect_schema().names()};
        lazyFrame_file = lazyFrame_file.select(column_dataTypes.values());
        lazyFrame_file = self._remove_nullDupes(file_name = file_name, lazyFrame_file = lazyFrame_file, dupeBy = ['Date', 'Ticker']);

        # Requirements GIVEN Specific Columns:
        #   1. Transform the ANNUAL expense ratio into the MONTHLY expense ratio.
        if all(col in lazyFrame_file.collect_schema().names() for col in ['Expense_Ratio']):
            lazyFrame_file = lazyFrame_file.with_columns( (pl.col('Expense_Ratio') / 12).alias('Expense_Ratio') );
        #   2. Backward-fill the expense_ratios from ANNUAL -> MONTHLY.
        if all(col in lazyFrame_file.collect_schema().names() for col in ['Date']):
            lazyFrame_file = (
                lazyFrame_file
                .with_columns([
                    pl.date_ranges(
                        start = pl.col('Date').dt.offset_by('-11mo'), 
                        end = pl.col('Date'), 
                        interval = '1mo'
                    ).over('Ticker')
                    .alias('Date') 
                ]).explode('Date')
                # Removes overlapping date observations IF the given company changes their payment schedule
                .unique(subset = ['Ticker', 'Date'], keep = 'first', maintain_order = True)
                .sort(['Ticker', 'Date'])
            );
        return lazyFrame_file;



class EDGAR__TOTAL_NET_ASSET(INPUT_DIRECTORY):
    def _format_lazyFrame(self, file_name: str, path: str) -> pl.LazyFrame:
        lazyFrame_file: pl.LazyFrame = pl.scan_csv(path, infer_schema = False, has_header = True);
        lazyFrame_file = lazyFrame_file.drop_nulls();
        # Defining column names, dataTypes, and column-specfic requirements.
        column_dataTypes: dict[str, pl.Expr] = {
            'fiscal_year_end':      (pl.col('fiscal_year_end').str.to_date(format = '%Y-%m-%d').dt.month_start()).alias('Date'),
            'ticker':               (pl.col('ticker').cast(pl.String)).alias('Ticker'),
            'net_assets_thousands': (pl.col('net_assets_thousands').cast(pl.Float64) * 1000).alias('Total-Net-Asset')
        }
        column_dataTypes = {col : column_dataTypes[col] for col in column_dataTypes.keys()
                            if col in lazyFrame_file.collect_schema().names()};
        lazyFrame_file = lazyFrame_file.select(column_dataTypes.values());
        lazyFrame_file = self._remove_nullDupes(file_name = file_name, lazyFrame_file = lazyFrame_file, dupeBy = ['Date', 'Ticker']);
        return lazyFrame_file;
