# Project-4_Credit-Spread-Liquidity

## Program Requirements
* __Language:__ Python 3.14
* __Required Packages:__\
  Most of the required packages can be installed inside of the Python terminal using `python -m pip install <insert-package-name>` OR `py -m pip install <insert-package-name>`.
    | Package           | Version                | Installation Purposes                                                                  |
    | :---------------- | :--------------------- | :------------------------------------------------------------------------------------- |
    | typing_extensions | 4.16                   | Add labels to classTypes and dataTypes to better define program structure.             | 
    | yFinance          | 26.30                  | Used to obtain data from Yahoo Finance ONCE.                                           |
    | polars            | 2.00                   | Faster alternative to Pandas to handle basic dataFrame structure and updates.          |
    | pandas            | 2.5.4                  | Used INSTEAD of Polars when required from OTHER packages ( like sci.py or statsmodels) |
    | pyarrow           | 26.0.0                 | Transforms Polars dataFrames --> Pandas dataFrames                                     |
    | statsmodels       |	0.15.0	               | Helps calculate multiple-linear regression models.                                     |
    | scipy             |	2.5.4	                 | Helps calculate multiple-linear regression models under SPECIFIC conditions.           |
    | fastexcel         | 0.21.0                 | Converts Excel files into dataFrames.                                                  |
    | xlsxwriter        | 3.2.9                  | Handles outputs from dataFrames into Excel.                                            |


## Program Instructions
  - To run the program in its *ENTIRETY* in VS-Code, EITHER:
      * Set the current-working-directory to `~\<project-name>\` AND press `Run Python File` inside of main.py.
      * Run the program as `& "<python.exe file-path>" "<main.py file-path>"` inside of the Python terminal.\
        __EX:__  `& "C:\Users\Justin Yi Cheng\AppData\Local\Python\pythoncore-3.14-64\python.exe" "c:/Users/Justin Yi Cheng/UWaterloo/CFM 301/CFM-301_Factor-Testing/main.py"`\
        
    All analysis should be output inside of the `~\_OUTPUT\` directory AND/OR the _OUTPUT.txt file.

  - All relevant data analysis are found inside the OUTPUT_DIRECTORY class or CHILDREN of the OUTPUT_DIRECTORY class. \
    File-specific data-cleaning is done in `input.py`, while data-cleaning that requires "additional information" is done in the OUTPUT_DIRECTORY class.\
    __EX:__ Information regarding globalFilters OR information from other files.
      * __All other files, *while necessary to RUN the program*, are used to define program structure, file structure, or make debugging easier.__

  - Comments assume the *reader has a basic understanding of Python, the given packages, and abstraction.*   \
    As a result, comments are only added to explain BLOCKS of code OR provide explanations for confusing implementations.\
    __EX__: I will NOT explain `(pl.col('gvkey').cast(pl.Utf8)).alias('Global-Company-Key')`, but I may explain that:
    ```
    column_dataTypes: dict[str, pl.Expr] = {
      'gvkey':    (pl.col('gvkey').cast(pl.Utf8)).alias('Global-Company-Key'),
      'conm':     (pl.col('conm').cast(pl.Utf8)).alias('Company-Name'),
      'datadate': (pl.col('datadate').str.to_date(format = '%Y-%m-%d')).alias('Date')
    };
    ```
    attempts to generally define standardized dataTypes and naming conventions for columns inside of specific fileTypes.
