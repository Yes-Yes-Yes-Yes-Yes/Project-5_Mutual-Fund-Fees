import time

from test import TEST
from input import *
from base import BASE
from sensitivity_A import SENSITIVITY_A
from sensitivity_B import SENSITIVITY_B

# MAIN.PY ---
#   Hub where all functions are run and cursory changes are made.
#   EX: Changing the file-path parameters of an INPUT class

# The current-working-directory should START at '~\<Project-Name>\'
project_directory_relativePath: str = r'.';



def main():
    #   0. Instantiating the TEST class
    test = TEST(project_directory_path = project_directory_relativePath);

    #   1. Instantiating the INPUT classes
    ticker       = (YAHOO__TICKER(test = test, project_directory_path = project_directory_relativePath)
                    .download_tickerFiles(tickerNames = ['HLIEX', 'MADVX', 'LAFYX', 'AVLIX', 'GSIIX', 'VINIX', 'VSCIX', 'VIVIX'], interval = '1mo'));
    fama         = (KENNETH__FAMA(test = test, project_directory_path = project_directory_relativePath)
                    .download_factorFiles(fileNames = ['F-F_Research_Data_Factors']));
    momentum     = (KENNETH__MOM(test = test, project_directory_path = project_directory_relativePath)
                    .download_factorFiles(fileNames = ['F-F_Momentum_Factor']));
    expense_ratio = EDGAR__EXPENSE_RATIO(test = test, project_directory_path = project_directory_relativePath);
    total_net_asset = EDGAR__TOTAL_NET_ASSET(test = test, project_directory_path = project_directory_relativePath);
    

    #   2. Instantiating the OUTPUT classes
    base = BASE(
        ticker = ticker, fama = fama, momentum = momentum, expense_ratio = expense_ratio, total_net_asset = total_net_asset,
        test = test, project_directory_path = project_directory_relativePath
    );
    sensitivity_A = SENSITIVITY_A(
        ticker = ticker, fama = fama, momentum = momentum, expense_ratio = expense_ratio, total_net_asset = total_net_asset,
        test = test, project_directory_path = project_directory_relativePath
    );
    sensitivity_B = SENSITIVITY_B(
        ticker = ticker, fama = fama, momentum = momentum, expense_ratio = expense_ratio, total_net_asset = total_net_asset,
        test = test, project_directory_path = project_directory_relativePath
    );
    
    #   3. Running main()...
    base.create_files();
    sensitivity_A.create_files();
    sensitivity_B.create_files();
    return;



if __name__ == '__main__':
    start_time: float = time.time();
    
    main();

    print('-------------------------------------------------------------');
    print(f'TOTAL RUNTIME: {round(time.time() - start_time, 5)} Seconds!');
    print('-------------------------------------------------------------');
