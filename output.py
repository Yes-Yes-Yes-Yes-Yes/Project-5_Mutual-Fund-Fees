from abc import ABC, abstractmethod
from typing_extensions import Self, Any

import os
import polars as pl
import altair as alt

from test import TEST

# OUTPUT.PY --- 
#   Handles all tasks related to outputting data.



class OUTPUT_DIRECTORY(ABC):
    def __init__(self, test: TEST, project_directory_path: str = r'.'):
        # Instantiating the TEST object for easier debugging / output visualization
        self._test = test;
        # Creating the '~\_OUTPUT\' directory path
        self._output_directory_path: str = os.path.join(project_directory_path, '_OUTPUT');
        if not os.path.exists(self._output_directory_path): os.mkdir(self._output_directory_path);
        # self._output_files is a dictionary which specifies:
        #   A. dict[str, ...]                                       = The OUTPUT file_name.
        #   B. dict[..., tuple[str, ...] ]                          = The OUTPUT type
        #   C. dict[..., tuple[..., dict[str, str], ...] ]          = Required arguments for the OUTPUT type.
        #   D. dict[..., tuple[..., ..., dict[str, pl.LazyFrame]] ] = Dictionary of lazyFrame data TO BE OUTPUT as a table OR data visualization.
        self._output_files: dict[str, tuple[str, dict[str, str], dict[str, pl.LazyFrame]] ] = {};


    @abstractmethod
    # validate_data() checks if we can perform analysis considering ALL given data and additional requirements.
    #   - If the combined data fails a check, we fix the data and report the number of changes.
    def _validate_data(self) -> bool:     pass;
    

    @abstractmethod
    def create_files(self) -> Self: pass;


    # find_diffs(...) compares the before and after of a lazyFrame, then returns a dictionary where:
    #    A. 'diffs':    Returns the recorded differences in lazyFrames for each column.
    #    B. 'numDiffs': Returns a lazyFrame which records the number of different observations for each column.
    def _find_diffs(self, name: str, before_lazyFrame: pl.LazyFrame, after_lazyFrame: pl.LazyFrame, diffColumns: list[str]) -> dict[str, Any]:
        #   0. Checking that BOTH lazyFrames contain the required columns
        assert(all((col in before_lazyFrame.collect_schema().names() and col in after_lazyFrame.collect_schema().names()) for col in diffColumns));
        #   1. Initialize TWO variables which:
        #       A. Lists the differences between each column in diffColumns
        #       B. Records the difference in the number of observations between each column in diffColumns.
        diffs:    dict[str, pl.LazyFrame] = { };
        numDiffs: dict[str, list[int]]    = {'LAZYFRAME | column': [], 'numBefore': [], 'numAfter': [], 'numDiff': []};
        #   2. For each diffColumn... 
        for diffColumn in diffColumns:
            beforeCol: pl.LazyFrame        = before_lazyFrame.rename({diffColumn : f'{diffColumn}\n[BEFORE]'}).select(f'{diffColumn}\n[BEFORE]');
            afterCol:  pl.LazyFrame        = after_lazyFrame.rename({diffColumn  : f'{diffColumn}\n[AFTER]'}).select(f'{diffColumn}\n[AFTER]');
            diff_lazyFrame:   pl.LazyFrame = beforeCol.join(afterCol, left_on = f'{diffColumn}\n[BEFORE]', right_on = f'{diffColumn}\n[AFTER]', how = 'anti');
            #   Record the observed differences, then record the number of observed differences.
            diffs[diffColumn] = diff_lazyFrame;
            numDiffs['LAZYFRAME | column'].append(f'{name.upper()} | {diffColumn}');
            numDiffs['numBefore'].append(before_lazyFrame.select(pl.len()).collect().item());
            numDiffs['numAfter'].append(after_lazyFrame.select(pl.len()).collect().item());
            numDiffs['numDiff'].append(diff_lazyFrame.select(pl.len()).collect().item());
        #   3. Obtain numDiffs as a lazyFrame for easier reading.
        numDiffs: pl.LazyFrame = pl.LazyFrame(numDiffs);
        return { 'diffs': diffs, 'numDiffs': numDiffs };


    
    # winsorize(key, lazyFrame, winsorizeColumns) winsorizes the numerical data of all columns 
    #   inside of `winsorizeColumns` and returns the percentage of values changes.
    def _winsorize(self, key: str, lazyFrame: pl.LazyFrame, winsorizeColumns: list[str], winsorize_pct: float = 0.95) -> pl.LazyFrame:
        #   0. Checking that the required columns exists and that the parameter columns are numeric.
        lazyFrame_schema: pl.Schema = lazyFrame.collect_schema();
        assert(all((col in lazyFrame_schema.names() and lazyFrame_schema[col].is_numeric()) for col in winsorizeColumns));
        #   1. For each winsorizeColumn, perform a 95% winsorizaion on the data values.
        lowerbound: float = (1 - winsorize_pct) / 2;
        upperbound: float = winsorize_pct + lowerbound;
        winsorized_lazyFrame: pl.LazyFrame = (
            lazyFrame
            .with_columns([ 
                (pl.col(col).clip( lower_bound = pl.col(col).quantile(lowerbound), upper_bound = pl.col(col).quantile(upperbound) )).alias(col)
                for col in winsorizeColumns
            ])
        );
        return winsorized_lazyFrame;


    # alignDates(...) aligns the 'Date' column for all lazyFrames in the given dictionary.
    def _alignDates(self, lazyFrame_dict: dict[str, pl.LazyFrame]) -> dict[str, pl.LazyFrame]:
        #   0. Check that there exists at least 2 lazyFrames 
        assert(len(lazyFrame_dict.keys()) >= 2);
        #      Checks that the 'Date' column exists in all of the lazyFrames.
        assert(all('Date' in lazyFrame.collect_schema().names() for lazyFrame in lazyFrame_dict.values()));
        #   1. Use temp_lazyFrame to find the set of common dates among ALL lazyFrames in the dictionary.
        temp_lazyFrame: pl.LazyFrame = list(lazyFrame_dict.values())[0].select('Date');
        for lazyFrame in lazyFrame_dict.values():     temp_lazyFrame = temp_lazyFrame.join(lazyFrame.select('Date'), on = 'Date', how = 'inner');
        #   2. Set all lazyFrames to only contain those dates
        edited_lazyFrame_dict: pl.LazyFrame[str, pl.LazyFrame] = {};
        for key, lazyFrame in lazyFrame_dict.items(): edited_lazyFrame_dict[key] = lazyFrame.filter( pl.col('Date').is_in(temp_lazyFrame.collect().get_column('Date')) );
        #   3. Log the new date-ranges of all ALL the data files.
        self._test.log_output(' * New Date-Range: ');
        self._test.log_output(f'    > Start Date: {temp_lazyFrame.sort('Date').select(pl.col('Date').first()).collect().item()}');
        self._test.log_output(f'    > End   Date: {temp_lazyFrame.sort('Date').select(pl.col('Date').last()).collect().item()}');
        self._test.log_output('');
        return edited_lazyFrame_dict;


    # output_files() standardizes tabular/diagram outputs into '~\_OUTPUT\<class-name>\' using the instructions inside of self._output_files dictionary.
    # The OUTPUT_DIRECTORY class obtains tabular/diagram outputs from its CHILDREN inside of create_files(...).
    def output_files(self) -> Self:
        for file_name, output in self._output_files.items():
            output_path: str                         = os.path.join(self._output_directory_path, file_name);
            output_type: str                         = output[0];
            output_args: dict[str, str]              = output[1];
            output_dataDict: dict[str, pl.DataFrame] = output[2];
            
            match (output_type):
                case 'default':
                    output_data: pl.DataFrame = output_dataDict['Main'].collect();

                    output_data.write_excel(
                        workbook = f'{output_path}.xlsx', worksheet = file_name, 
                        table_style = 'Table Style Medium 6',
                        include_header = True, autofilter = True, autofit = True, freeze_panes = (1,0)
                    );
                case 'line':
                    output_data: pl.DataFrame = output_dataDict['Main'].collect();
                    x_title: str = output_args['x'];
                    y_title: str = output_args['y'];
                    legend: str = output_args['legend'];
                    if (output_data[x_title].dtype == pl.Date): x_axis = alt.X(f'{x_title}:T', axis = alt.Axis(format = '%Y-%m-%d', labelAngle = -90), title = x_title);
                    else:                                       x_axis = alt.X(f'{x_title}:Q', title = x_title);

                    lineplot: alt.Chart = (
                        alt.Chart(output_data)
                        .mark_line(opacity = 0.3, tooltip = True)
                        .encode(
                            x = x_axis,
                            y = alt.Y(f'{y_title}:Q',                            title = y_title),
                            color = alt.Color(f'{legend}:N', sort = 'ascending', title = legend, legend = alt.Legend(title = legend, orient = 'top-right'))
                        ).properties(width = 1000, height = 400, title = f'{y_title} by {x_title}')
                        .interactive()
                    );
                    lineplot.save(f'{output_path}.html');
                case 'scatter':
                    output_data: pl.DataFrame = output_dataDict['Main'].collect();
                    x_title: str = output_args['x'];
                    y_title: str = output_args['y'];
                    legend: str = output_args['legend'];
                    if (output_data[x_title].dtype == pl.Date): x_axis = alt.X(f'{x_title}:T', axis = alt.Axis(format = '%Y-%m-%d', labelAngle = -90), title = x_title);
                    else:                                       x_axis = alt.X(f'{x_title}:Q', title = x_title);

                    scatterplot: alt.Chart = (
                        alt.Chart(output_data)
                        .mark_circle(size = 15, opacity = 0.3, tooltip = True)
                        .encode(
                            x = x_axis,
                            y = alt.Y(f'{y_title}:Q',                            title = y_title),
                            color = alt.Color(f'{legend}:N', sort = 'ascending', title = legend, legend = alt.Legend(title = legend, orient = 'top-right'))
                        ).properties(width = 1000, height = 400, title = f'{y_title} by {x_title}')
                        .interactive()
                    );
                    scatterplot.save(f'{output_path}.html');
                case 'line_independentYs':
                    outputData_A: pl.DataFrame = output_dataDict['A'].collect();
                    outputData_B: pl.DataFrame = output_dataDict['B'].collect();
                    x_title: str = output_args['x'];
                    yA_title: str = output_args['yA'];
                    yB_title: str = output_args['yB'];
                    if (outputData_A[x_title].dtype == pl.Date): x_axis = alt.X(f'{x_title}:T', axis = alt.Axis(format = '%Y-%m-%d', labelAngle = -90), title = x_title);
                    else:                                        x_axis = alt.X(f'{x_title}:Q', title = x_title);

                    lineplotA: alt.Chart = (
                        alt.Chart(outputData_A)
                        .mark_line(opacity = 0.3, color = 'steelblue', tooltip = True)
                        .encode(x = x_axis, y = alt.Y(f'{yA_title}:Q', title = yA_title, axis = alt.Axis(titleColor = 'steelblue', orient = 'left')))
                    );
                    lineplotB: alt.Chart = (
                        alt.Chart(outputData_B)
                        .mark_line(opacity = 0.3, color = 'orange', tooltip = True)
                        .encode(x = x_axis, y = alt.Y(f'{yB_title}:Q', title = yB_title, axis = alt.Axis(titleColor = 'orange', orient = 'right')))
                    );
                    layeredLineplot: alt.Chart = (
                        alt.layer(lineplotA, lineplotB)
                        .resolve_scale(y = 'independent')
                        .properties(width = 1000, height = 400, title = f'{yA_title} vs. {yB_title}')
                        .interactive()
                    );
                    layeredLineplot.save(f'{output_path}.html');

        
        return self;
