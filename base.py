from typing_extensions import Self, Callable, Any, final

import os
import polars as pl
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.optimize import minimize

from test import TEST
from input import *
from output import OUTPUT_DIRECTORY

# BASE.PY --- 
#   Handles data analysis for our original economic motivation:
#       - NO WINSORIZATION


@final
class BASE(OUTPUT_DIRECTORY):
    def __init__(self, ticker: YAHOO__TICKER, fama: KENNETH__FAMA, momentum: KENNETH__MOM, expense_ratio: EDGAR__EXPENSE_RATIO, total_net_asset: EDGAR__TOTAL_NET_ASSET,
                 test: TEST, project_directory_path: str = '.'):
        super().__init__(test, project_directory_path);
        self._output_directory_path: str = os.path.join(self._output_directory_path, type(self).__name__);
        # Either deleting all files inside of '~\_OUTPUT\<class-name>\' OR creating the '~\_OUTPUT\<class-name>\' directory.
        if os.path.exists(self._output_directory_path): [os.unlink(os.path.join(self._output_directory_path, file)) for file in os.listdir(self._output_directory_path)];
        else:                                           os.mkdir(self._output_directory_path);

        # Obtaining the DATA
        self._test.log_output(f'{type(self).__name__}: BEGIN DATA CLEANING');
        self.__data: dict[str, pl.LazyFrame] = { };
        #   1. ticker ( mutual funds / ETFs )
        fileFilter: dict[str, list[Callable]] = { 'HLIEX': [], 'MADVX': [], 'LAFYX': [], 'AVLIX': [], 'GSIIX': [], 'VINIX': [], 'VSCIX': [], 'VIVIX': [] };
        self.__data.update(ticker.read_files(fileFilter = fileFilter, dataGroup = type(self).__name__));
        #   2. fama
        fileFilter: dict[str, list[Callable]] = { 'F-F_Research_Data_Factors': [] };
        self.__data.update(fama.read_files(fileFilter = fileFilter, dataGroup = type(self).__name__));
        #   3. momentum
        fileFilter: dict[str, list[Callable]] = { 'F-F_Momentum_Factor': [] };
        self.__data.update(momentum.read_files(fileFilter = fileFilter, dataGroup = type(self).__name__));
        #   4. expense_ratio
        fileFilter: dict[str, list[Callable]] = { 'expense_ratio': [] };
        self.__data.update(expense_ratio.read_files(fileFilter = fileFilter, dataGroup = type(self).__name__));
        #      Transforming the expense_ratio into PIVOT table for easier analysis.
        self.__data['expense_ratio'] = (
            self.__data['expense_ratio']
            .pivot(index = 'Date', on = 'Ticker', on_columns = ['HLIEX', 'MADVX', 'LAFYX', 'AVLIX', 'GSIIX', 'VINIX', 'VSCIX', 'VIVIX'], values = 'Expense_Ratio')
            .rename({col: f'Expense_Ratio\n[{col}]' for col in ['HLIEX', 'MADVX', 'LAFYX', 'AVLIX', 'GSIIX', 'VINIX', 'VSCIX', 'VIVIX']})
            .drop_nulls()
            .sort('Date')
        );
        self._validate_data();
        
        #   5. total_net_asset
        #           - Note that total_net_asset is EXTEMPT from the date-alignment since it is the only metric calculated anually.
        fileFilter: dict[str, list[Callable]] = { 'tna_history': [] };
        self.__data.update(total_net_asset.read_files(fileFilter = fileFilter, dataGroup = type(self).__name__));
        #      Transforming the expense_ratio into PIVOT table for easier analysis.
        self.__data['tna_history'] = (
            self.__data['tna_history']
            .pivot(index = 'Date', on = 'Ticker', on_columns = ['HLIEX', 'MADVX', 'LAFYX', 'AVLIX', 'GSIIX'], values = 'Total-Net-Asset')
            .rename({col: f'Total-Net-Asset\n[{col}]' for col in ['HLIEX', 'MADVX', 'LAFYX', 'AVLIX', 'GSIIX']})
            .sort('Date')
        );
        self._test.log_output(f'{type(self).__name__}: DATA CLEANING COMPLETE!\n\n');


    def _validate_data(self) -> None:
         # RUNNING VALIDATE_DATA() ---
        #       1. Aligning the 'Date's in EACH of the lazyFrame columns.
        data_aligned: dict[str, pl.LazyFrame] = self._alignDates(lazyFrame_dict = self.__data);
        #       2. Record the difference in the number of values BEFORE and AFTER aligning.
        recordDiffs: pl.LazyFrame = pl.LazyFrame(schema = {'LAZYFRAME | column': pl.String, 'numBefore': pl.Int64, 'numAfter': pl.Int64, 'numDiff': pl.Int64});
        for key in data_aligned.keys():
            diffs: dict[str, Any] = self._find_diffs(name = key, before_lazyFrame = self.__data[key], after_lazyFrame = data_aligned[key], diffColumns = ['Date']);
            recordDiffs = pl.concat([recordDiffs, diffs['numDiffs']], how = 'vertical');
        #       3. Log the result, then set the current data to the aligned data.
        self._test.log_output(' * Impact of Date-Alignmnt: ');
        self._test.log_output(recordDiffs.sort('numBefore', descending = True));
        self.__data = data_aligned;
        return;


    def create_files(self) ->  Self:
        # FUNCTIONS FOR CREATE_FILES() ---
        #   * getRegressionSummary_withFactors(...) finds each ACTIVE mutual fund's regression summary
        #       against the CAPM, Fama-French, and Carhart 4-Factor Model.
        def getRegressionSummary_withFactors():
            allTickers: list[str] = [ col.split('\n')[-1]
                                      for col in self.__data['Active'].select(pl.selectors.starts_with('Excess-Market-Return')).collect_schema().names() ];
            
            for ticker in allTickers:
                # For calculating the Regression Model statistics
                excessMarketReturn: pd.DataFrame = self.__data['Active'].select(pl.selectors.starts_with('Excess-Market-Return') & pl.selectors.ends_with(ticker)).collect().to_pandas();
                grossMarketReturn:  pd.DataFrame = self.__data['Active'].select(pl.selectors.starts_with('Gross-Market-Return') & pl.selectors.ends_with(ticker)).collect().to_pandas();
                capm:               pd.DataFrame = self.__data['Factor'].select('Market-Excess-Return').collect().to_pandas();
                fama:               pd.DataFrame = self.__data['Factor'].select(['Market-Excess-Return', 'Small-Minus-Big', 'Huge-Minus-Low']).collect().to_pandas();
                carhart:            pd.DataFrame = self.__data['Factor'].drop(['Date', 'Risk-Free-Rate']).collect().to_pandas();

                #   Calculating the Regression Models:
                #       - Regression A: excessMarketReturn ~ capm
                model_capm                = sm.OLS(excessMarketReturn, sm.add_constant(capm)).fit();
                alpha_capm: float         = model_capm.params['const'];
                tStat_capm: float         = model_capm.tvalues['const'];
                trackError_capm: float    = model_capm.resid.std(ddof = 1);
                infoRatio_capm: float     = alpha_capm / trackError_capm;
                rSquared_capm: float      = model_capm.rsquared
                model_grossCapm           = sm.OLS(grossMarketReturn, sm.add_constant(capm)).fit();
                alpha_grossCapm: float    = model_grossCapm.params['const'];
                #       - Regression B: excessMarketReturn ~ fama
                model_fama                = sm.OLS(excessMarketReturn, sm.add_constant(fama)).fit();
                alpha_fama: float         = model_fama.params['const'];
                tStat_fama: float         = model_fama.tvalues['const'];
                trackError_fama: float    = model_fama.resid.std(ddof = 1);
                infoRatio_fama: float     = alpha_fama / trackError_fama;
                rSquared_fama: float      = model_fama.rsquared
                model_grossFama           = sm.OLS(grossMarketReturn, sm.add_constant(fama)).fit();
                alpha_grossFama: float    = model_grossFama.params['const'];
                #       - Regression C: excessMarketReturn ~ carhart
                model_carhart             = sm.OLS(excessMarketReturn, sm.add_constant(carhart)).fit();
                alpha_carhart: float      = model_carhart.params['const'];
                tStat_carhart: float      = model_carhart.tvalues['const'];
                trackError_carhart: float = model_carhart.resid.std(ddof = 1);
                infoRatio_carhart: float  = alpha_carhart / trackError_carhart;
                rSquared_carhart: float   = model_carhart.rsquared
                model_grossCarhart        = sm.OLS(grossMarketReturn, sm.add_constant(carhart)).fit();
                alpha_grossCarhart: float = model_grossCarhart.params['const'];
                # Output the results into _OUTPUT.txt
                self._test.log_output(f' * ANALYZING {ticker} FACTOR STATISTICS...');
                self._test.log_output('         - marketExcess ~ capm         OLS Results -- ');
                self._test.log_output(f'            > Alpha:       {alpha_capm}');
                self._test.log_output(f'            > T-Statistic: {tStat_capm}');
                self._test.log_output(f'            > Track Error: {trackError_capm}');
                self._test.log_output(f'            > Info Ratio:  {infoRatio_capm}');
                self._test.log_output(f'            > R-Squared:   {rSquared_capm}');
                self._test.log_output('         - grossMarketExcess ~ capm    OLS Results -- ');
                self._test.log_output(f'            > Alpha:       {alpha_grossCapm}');
                self._test.log_output('');
                self._test.log_output('         - marketExcess ~ fama         OLS Results -- ');
                self._test.log_output(f'            > Alpha:       {alpha_fama}');
                self._test.log_output(f'            > T-Statistic: {tStat_fama}');
                self._test.log_output(f'            > Track Error: {trackError_fama}');
                self._test.log_output(f'            > Info Ratio:  {infoRatio_fama}');
                self._test.log_output(f'            > R-Squared:   {rSquared_fama}');
                self._test.log_output('         - grossMarketExcess ~ fama    OLS Results -- ');
                self._test.log_output(f'            > Alpha:       {alpha_grossFama}');
                self._test.log_output('');
                self._test.log_output('         - marketExcess ~ carhart      OLS Results -- ');
                self._test.log_output(f'            > Alpha:       {alpha_carhart}');
                self._test.log_output(f'            > T-Statistic: {tStat_carhart}');
                self._test.log_output(f'            > Track Error: {trackError_carhart}');
                self._test.log_output(f'            > Info Ratio:  {infoRatio_carhart}');
                self._test.log_output(f'            > R-Squared:   {rSquared_carhart}');
                self._test.log_output('         - grossMarketExcess ~ carhart OLS Results -- ');
                self._test.log_output(f'            > Alpha:       {alpha_grossCarhart}');
                self._test.log_output(f'   COMPLETED ANALYZING {ticker} FACTOR STATISTICS!');
                self._test.log_output('\n\n\n');
            return;
        #   * getRegressionSummary_withBenchmark(...) regresses the mutual fund against a multitude of benchmarks to calculate an alpha UNDER specific requirements.
        #       - Also calculates the Active VS. Passive Expense Ratios, and compares the two values.
        def getRegressionSummary_withBenchmark():
            allTickers: list[str] = [ col.split('\n')[-1]
                                      for col in self.__data['Active'].select(pl.selectors.starts_with('Excess-Market-Return')).collect_schema().names() ];
            
            for ticker in allTickers:                
                excessMarketReturn: np.typing.NDArray = self.__data['Active'].select(pl.selectors.starts_with('Excess-Market-Return') & pl.selectors.ends_with(ticker)).collect().to_numpy();
                benchmark:          np.typing.NDArray = self.__data['Passive'].select(pl.selectors.ends_with('[VINIX]') | pl.selectors.ends_with('[VIVIX]') | pl.selectors.ends_with('[VSCIX]')).collect().to_numpy();
                # Calculating the Regression Models:
                #   1. Obtaining the Y-X values as a NUMPY array
                y: np.typing.NDArray = np.asarray(excessMarketReturn, dtype = float).ravel();
                X: np.typing.NDArray = np.asarray(benchmark,          dtype = float);
                #   2. FUNCTION to obtain a LIST OF VALUES, which we MINIMIZE
                def objective(parameters: list):
                    alpha = parameters[0];
                    betas = parameters[1:];
                    residuals = y - (alpha + X @ betas);
                    return np.sum(residuals ** 2);
                #   3. Calculate the OLS ( from `objective` )
                result = minimize(
                    objective,
                    # Initial-Values: Alpha = 0,  Equal Benchmark Weights
                    np.array([0.0] + [1 / X.shape[1]] * X.shape[1]),
                    method = 'SLSQP',
                    # Restrictiions: Alpha can be ANY value, Betas/Weights CANNOT be negative
                    bounds = [(None, None)] + [(0, 1)] * X.shape[1],
                    # Requirements:  Betas/Weights MUST sum to 1
                    constraints = [{ 'type': 'eq', 'fun': lambda params: np.sum(params[1:]) - 1 }], 
                    # Program-Specific Requirements:
                    #       - ftol:    Set a convergence tolerance
                    #       - maxiter: Number of allowed iterations until stopping.
                    options = { 'ftol': 1e-12, 'maxiter': 1000 }
                );
                if not result.success: exit(1);
                # Calculating the Benchmark Expense_Ratios
                alpha:                  float       = result.x[0];
                weights:                list[float] = result.x[1:];
                #   1. Obtaining the AVERAGE ACTIVE  benchmark expense_ratio
                active_expenseRatio: float = self.__data['expense_ratio'].select( pl.col(f'Expense_Ratio\n{ticker}').mean() ).collect().item();
                #   2. Obtaining the AVERAGE PASSIVE benchmark expense_ratios
                passive_expenseRatios: list[float] = (
                    list(
                        self.__data['expense_ratio']
                        .select([ pl.col('Expense_Ratio\n[VINIX]').mean(), pl.col('Expense_Ratio\n[VIVIX]').mean(), pl.col('Expense_Ratio\n[VSCIX]').mean() ])
                        .collect()
                        .row(0)
                    )
                );
                passive_expenseRatio: float         = sum([weight * expense_ratio for weight, expense_ratio in zip(weights, passive_expenseRatios)]);
                # Output the results into _OUTPUT.txt
                self._test.log_output(f' * ANALYZING {ticker} BENCHMARK STATISTICS...');
                self._test.log_output('         - marketExcess ~ benchmark OLS Results -- ');
                self._test.log_output(f'             > Alpha:                           {alpha}');
                self._test.log_output(f'             > Weights:                         {weights}');
                self._test.log_output(f'             > Active  Benchmark Expense Ratio: {active_expenseRatio}');
                self._test.log_output(f'               Passive Benchmark Expense Ratio: {passive_expenseRatio}');
                self._test.log_output(f'               Difference Active VS. Passive:   {active_expenseRatio - passive_expenseRatio}');
                self._test.log_output(f'   COMPLETED ANALYZING {ticker} BENCHMARK STATISTICS!');
                self._test.log_output('\n\n\n');
            return;
        #   * getRegressionPersistance() calculates the alpha for ALL tickers across each of the CAPM/FAMA/CARHART models between TWO time periods.
        def getRegressionPersistance():
            allTickers: list[str] = [ col.split('\n')[-1]
                                         for col in self.__data['Active'].select(pl.selectors.starts_with('Excess-Market-Return')).collect_schema().names() ];

            for ticker in allTickers:
                #   1. Calculating the preliminary values...
                #       - Obtaining the MIDDLE date to-be-used to split the alphas
                timeSplit: pl.Date = self.__data['Active'].select('Date').sort('Date').collect().get_column('Date');
                timeSplit          = timeSplit[(len(timeSplit) // 2) - 1];  
                #       - For calculating the Regression Model statistics
                before_excessMarketReturn: pd.DataFrame = self.__data['Active'].filter(pl.col('Date') <= timeSplit).select(pl.selectors.starts_with('Excess-Market-Return') & pl.selectors.ends_with(ticker)).collect().to_pandas();
                before_capm:               pd.DataFrame = self.__data['Factor'].filter(pl.col('Date') <= timeSplit).select('Market-Excess-Return').collect().to_pandas();
                before_fama:               pd.DataFrame = self.__data['Factor'].filter(pl.col('Date') <= timeSplit).select(['Market-Excess-Return', 'Small-Minus-Big', 'Huge-Minus-Low']).collect().to_pandas();
                before_carhart:            pd.DataFrame = self.__data['Factor'].filter(pl.col('Date') <= timeSplit).drop(['Date', 'Risk-Free-Rate']).collect().to_pandas();

                after_excessMarketReturn:  pd.DataFrame = self.__data['Active'].filter(pl.col('Date') > timeSplit).select(pl.selectors.starts_with('Excess-Market-Return') & pl.selectors.ends_with(ticker)).collect().to_pandas();
                after_capm:                pd.DataFrame = self.__data['Factor'].filter(pl.col('Date') > timeSplit).select('Market-Excess-Return').collect().to_pandas();
                after_fama:                pd.DataFrame = self.__data['Factor'].filter(pl.col('Date') > timeSplit).select(['Market-Excess-Return', 'Small-Minus-Big', 'Huge-Minus-Low']).collect().to_pandas();
                after_carhart:             pd.DataFrame = self.__data['Factor'].filter(pl.col('Date') > timeSplit).drop(['Date', 'Risk-Free-Rate']).collect().to_pandas();
                #   2. Calculating the Regression Models:
                #       - Regression A: excessMarketReturn ~ capm
                alpha_capm_before    = sm.OLS(before_excessMarketReturn, sm.add_constant(before_capm)).fit().params['const'];
                alpha_capm_after     = sm.OLS(after_excessMarketReturn, sm.add_constant(after_capm)).fit().params['const'];
                #       - Regression B: excessMarketReturn ~ fama
                alpha_fama_before    = sm.OLS(before_excessMarketReturn, sm.add_constant(before_fama)).fit().params['const'];
                alpha_fama_after     = sm.OLS(after_excessMarketReturn, sm.add_constant(after_fama)).fit().params['const'];
                #       - Regression C: excessMarketReturn ~ carhart
                alpha_carhart_before = sm.OLS(before_excessMarketReturn, sm.add_constant(before_carhart)).fit().params['const'];
                alpha_carhart_after  = sm.OLS(after_excessMarketReturn, sm.add_constant(after_carhart)).fit().params['const'];
                # Output the results into _OUTPUT.txt
                self._test.log_output(f' * ANALYZING {ticker} PERSISTANCE...');
                self._test.log_output('         - CAPM');
                self._test.log_output(f'             > Alpha-Before:                        {alpha_capm_before}');
                self._test.log_output(f'             > Alpha-After:                         {alpha_capm_after}');
                self._test.log_output('         - FAMA');
                self._test.log_output(f'             > Alpha-Before:                        {alpha_fama_before}');
                self._test.log_output(f'             > Alpha-After:                         {alpha_fama_after}');
                self._test.log_output('         - CARHART');
                self._test.log_output(f'             > Alpha-Before:                        {alpha_carhart_before}');
                self._test.log_output(f'             > Alpha-After:                         {alpha_carhart_after}');
                self._test.log_output(f'   COMPLETED ANALYZING {ticker} PERSISTANCE!');
                self._test.log_output('\n\n\n');
            return;
        #   * getFlows() uses the Net-Total-Return and Total-Net-Asset to calculate the monthly-fund-flow.
        def getFlows():
            allTickers: list[str] = [ col.split('\n')[-1]
                                      for col in self.__data['Active'].select(pl.selectors.starts_with('Net-Total-Return')).collect_schema().names() ];

            for ticker in allTickers:
                # Annualize the monthly netTotalReturns
                netTotalReturns: pl.LazyFrame = (
                    self.__data['Active']
                    .select(['Date'] + [pl.selectors.starts_with('Net-Total-Return') & pl.selectors.ends_with(ticker)])
                    .filter(pl.col('Date') >= pl.date(pl.col('Date').first().dt.year(), 3, 1) )
                    .sort('Date')
                    .rolling(index_column = 'Date', period = '1y', offset = '-1y', closed = 'right')
                    .agg([ ((pl.col(f'Net-Total-Return\n{ticker}') + 1).product() - 1).alias(f'Net-Total-Return\n{ticker}') ])
                );
                totalNetAsset:   pl.LazyFrame = (
                    self.__data['tna_history']
                    .select(['Date'] + [pl.selectors.starts_with('Total-Net-Asset') & pl.selectors.ends_with(ticker)])
                    .drop_nulls()
                );
                # Calculating the Flow
                flow: pl.LazyFrame = (
                    netTotalReturns
                    .join(totalNetAsset, on = 'Date', how = 'inner', validate = '1:1')
                    .select([
                        pl.col('Date'),
                        (pl.col(f'Total-Net-Asset\n{ticker}') - (pl.col(f'Total-Net-Asset\n{ticker}').shift(1) * (1 + pl.col(f'Net-Total-Return\n{ticker}')))).alias(f'Flow\n{ticker}')
                    ]).drop_nulls()
                );
                self._test.log_output(f' * ANALYZING {ticker} FLOW...');
                self._test.log_output(flow);
                self._test.log_output(f'   COMPLETED ANALYZING {ticker} FLOW!');
                self._test.log_output('\n\n\n');
            return;
        
        # RUNNING CREATE_FILES() ---
        #   Obtain the calculated metrics.
        #       1. Combining the KENNETH factors into ONE key-value pair for convenience.
        self.__data['Factor'] = (
            self.__data['F-F_Research_Data_Factors']
            .join(self.__data['F-F_Momentum_Factor'], on = 'Date', how = 'inner', validate = '1:1')
            .sort('Date')
        );
        #       2. ---
        #           - Combining the PASSIVE mutual funds into ONE key-value pair for convenience.
        #           - Calculating the EXCESS return from the treasury risk-free rate.
        self.__data['Passive'] = (
            self.__data['VINIX']
            .join(self.__data['VIVIX'], on = 'Date', how = 'inner', suffix = '\n[VIVIX]', validate = '1:1')
            .join(self.__data['VSCIX'], on = 'Date', how = 'inner', suffix = '\n[VSCIX]', validate = '1:1')
            .with_columns(pl.col('Net-Total-Return').alias('Net-Total-Return\n[VINIX]'))
            .drop(pl.col('Net-Total-Return'))
            .join(self.__data['Factor'].select(['Date', 'Risk-Free-Rate']), on = 'Date', how = 'inner', validate = '1:1')
            .with_columns(pl.col(pl.Float64) - pl.col('Risk-Free-Rate'))
            .drop('Risk-Free-Rate')
            .with_columns( pl.selectors.starts_with('Net-Total-Return').name.replace('^Net-Total-Return', 'Excess-Market-Return') )
            .drop(pl.selectors.starts_with('Net-Total-Return'))
            .sort('Date')
        );
        #       3. ---
        #           - Combining the ACTIVE mutual funds into ONE key-value pair for convenience.
        #           - Calculating the EXCESS return from the treasury risk-free rate.
        self.__data['Active'] = (
            self.__data['HLIEX']
            .join(self.__data['MADVX'], on = 'Date', how = 'inner', suffix = '\n[MADVX]', validate = '1:1')
            .join(self.__data['LAFYX'], on = 'Date', how = 'inner', suffix = '\n[LAFYX]', validate = '1:1')
            .join(self.__data['AVLIX'], on = 'Date', how = 'inner', suffix = '\n[AVLIX]', validate = '1:1')
            .join(self.__data['GSIIX'], on = 'Date', how = 'inner', suffix = '\n[GSIIX]', validate = '1:1')
            .with_columns(pl.col('Net-Total-Return').alias('Net-Total-Return\n[HLIEX]'))
            .drop('Net-Total-Return')
            .join(self.__data['Factor'].select(['Date', 'Risk-Free-Rate']), on = 'Date', how = 'inner', validate = '1:1')
            .with_columns(pl.col(pl.Float64) - pl.col('Risk-Free-Rate'))
            .drop('Risk-Free-Rate')
            .with_columns( pl.selectors.starts_with('Net-Total-Return').name.replace('^Net-Total-Return', 'Excess-Market-Return') )
        );
        #           - For each ticker, adding the expense ratio INTO the Excess-Market-Returns to obtain the Gross-Market-Returns.
        self.__data['Active'] = (
            self.__data['Active']
            .join(self.__data['expense_ratio'], on = 'Date', how = 'inner', validate = '1:1')
            .with_columns([
                (
                    (pl.selectors.starts_with('Excess-Market-Return') & pl.selectors.ends_with(f'[{ticker}]')) + 
                    (pl.selectors.starts_with('Expense_Ratio')        & pl.selectors.ends_with(f'[{ticker}]'))
                ).alias(f'Gross-Market-Return\n[{ticker}]')
                for ticker in ['HLIEX', 'MADVX', 'LAFYX', 'AVLIX', 'GSIIX']
            ]).drop(pl.selectors.starts_with('Expense_Ratio'))
            .sort('Date')
        );
        del self.__data['F-F_Research_Data_Factors'];
        del self.__data['F-F_Momentum_Factor'];
        del self.__data['VINIX'];
        del self.__data['VSCIX'];
        del self.__data['VIVIX'];
        del self.__data['HLIEX'];
        del self.__data['MADVX'];
        del self.__data['LAFYX'];
        del self.__data['AVLIX'];
        del self.__data['GSIIX'];

        self._test.log_output(f'{type(self).__name__}: BEGIN DATA ANALYSIS...');
        getRegressionSummary_withFactors();
        self._test.log_output('---------------------------------------------------------------------------------------------------------');
        getRegressionSummary_withBenchmark();
        self._test.log_output('---------------------------------------------------------------------------------------------------------');
        getRegressionPersistance();
        self._test.log_output('---------------------------------------------------------------------------------------------------------');
        getFlows();
        self._test.log_output(f'{type(self).__name__}: COMPLETE DATA ANALYSIS!');
        self._test.log_output('');
        return self;
