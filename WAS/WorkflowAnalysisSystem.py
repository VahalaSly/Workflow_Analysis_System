from argparse import ArgumentParser
import pandas as pd
import pathlib
import os
import sys
import data_processing.ProcessInputJson as PI
import data_processing.FeedbackSuite as FS
import machine_learning.RandomForest as RF
import analysis.ProcessResults as PR
import analysis.TopologicalAnalysis as TA


def get_arguments():
    parser = ArgumentParser(fromfile_prefix_chars='@')
    parser.add_argument("-f", "--file", dest="filepath",
                        help="KNIME workflow summary in JSON format", metavar="FILE PATH",
                        required=True)
    parser.add_argument("-u", "--user", dest="user",
                        help="The user calling the WAS", metavar="USERNAME",
                        required=True)
    parser.add_argument("-tf", "--task_features", dest="task_features",
                        help="Features of interest for tasks. If none, defaults to all.", metavar="FEATURE",
                        required=False, nargs="*", default='')
    parser.add_argument("-wf", "--workflow_features", dest="workflow_features",
                        help="Features of interest for workflows. If none, defaults to all.", metavar="FEATURE",
                        required=False, nargs="*", default='')
    parser.add_argument("-tc", "--task_classifier", dest="task_classifier",
                        help="Target node/task non-continuous KEY to be classified", metavar="KEY",
                        required=False, nargs="*", default='')
    parser.add_argument("-tr", "--task_regressor", dest="task_regressor",
                        help="Target node/task continuous numeric KEY to be regressed", metavar="KEY",
                        required=False, nargs="*", default='')
    parser.add_argument("-wc", "--workflow_classifier", dest="wk_classifier",
                        help="Target workflow non-continuous KEY to be classified", metavar="KEY",
                        required=False, nargs="*", default='')
    parser.add_argument("-wr", "--workflow_regressor", dest="wk_regressor",
                        help="Target workflow continuous numeric KEY to be regressed", metavar="KEY",
                        required=False, nargs="*", default='')
    return parser.parse_args()


def add_latest_exec_to_historical_data(historical_data_path, historical_data, latest_execution):
    try:
        if historical_data is not None:
            # pd.concat creates a union of the two dataframes, adding any new column
            latest_execution = pd.concat([historical_data, latest_execution], ignore_index=True, sort=False)
        latest_execution.to_csv(historical_data_path, index=False)
    except ValueError as e:
        print("Encountered error while trying to save new data to historical data.")
        print(e)


def analyse(paths_map,
            task_features,
            workflow_features,
            task_rf_label_map,
            workflow_rf_label_map):
    tasks_historical_data = None
    workflow_historical_data = None
    ## STEP 1 ##
    try:
        print("Initialising data pre-processing step...")
        task_df, workflow_df = PI.json_to_dataframe(paths_map['input_file'])
        print("Data pre-processing step successful! \n")
    except (KeyError, ValueError) as e:
        sys.stderr.write("Data pre-processing step unsuccessful :( \n")
        sys.stderr.write(str(e))
        raise e
    # create the hist filepaths for both tasks and workflows
    task_historical_data_path = "{}/tasks_historical_data.csv".format(paths_map['hist_dir'])
    workflow_historical_data_path = "{}/workflow_historical_data.csv".format(paths_map['hist_dir'])
    if os.path.isfile(task_historical_data_path) and os.path.isfile(workflow_historical_data_path):
        tasks_historical_data = pd.read_csv(task_historical_data_path, low_memory=False)
        workflow_historical_data = pd.read_csv(workflow_historical_data_path, low_memory=False)
        ## STEP 2 ##
        # if the user has selected some specific features, then only use these for the ML analysis
        # first we combine them with the labels to get all the user-defined columns:
        task_labels = list(set().union(*task_rf_label_map.values()))
        task_imp_columns = list(set(task_features + task_labels))
        workflow_labels = list(set().union(*workflow_rf_label_map.values()))
        workflow_imp_columns = list(set(workflow_features + workflow_labels))
        # since the historical data might not have the features...
        # ...we use the & operator to only get the feature column if it exists
        try:
            if len(task_features) > 0:
                task_filtered_df = task_df[task_imp_columns].copy(deep=True)
                tasks_historical_data = tasks_historical_data[
                    tasks_historical_data.columns.intersection(task_imp_columns)]
            else:
                task_filtered_df = task_df.copy(deep=True)
            if len(workflow_features) > 0:
                workflow_filtered_df = workflow_df[workflow_imp_columns].copy(deep=True)
                workflow_historical_data = workflow_historical_data[
                    workflow_historical_data.columns.intersection(workflow_imp_columns)]
            else:
                workflow_filtered_df = workflow_df.copy(deep=True)
        except KeyError as e:
            sys.stderr.write("Failed to match requested features with input data columns. "
                             "Make sure the desired features exist in the input data. \n")
            return e
        ### STEP 3 ###
        try:
            print("Initialising Random Forest step...")
            tasks_results = RF.predict(tasks_historical_data,
                                       task_filtered_df,
                                       task_rf_label_map)
            workflow_results = RF.predict(workflow_historical_data,
                                          workflow_filtered_df,
                                          workflow_rf_label_map)
            print("Random Forest step successful! \n")
        except (KeyError, ValueError) as e:
            sys.stderr.write("Random Forest step unsuccessful :( \n")
            return e
        ### STEP 4 ##
        try:
            print("Initialising results analysis step...")
            new_task_dataframe, task_imp_features = PR.process(tasks_results,
                                                               task_filtered_df)
            new_workflow_dataframe, workflow_imp_features = PR.process(workflow_results,
                                                                       workflow_filtered_df)
            print("Results analysis step successful! \n")
        except (KeyError, ValueError) as e:
            sys.stderr.write("Results analysis step unsuccessful :( \n")
            return e
        ### STEP 5 ##
        try:
            print("Initialising topological analysis step...")
            branch_stats, task_stats = TA.analyse(tasks_historical_data,
                                                  task_df,
                                                  task_imp_features,
                                                  task_rf_label_map)
            print("Topological analysis step successful! \n")
        except (KeyError, ValueError) as e:
            sys.stderr.write("Topological analysis step unsuccessful :( \n")
            return e
        ## STEP 6 ##
        try:
            print("Initialising feedback report step...")
            report = FS.produce_report(task_imp_features,
                                       workflow_imp_features,
                                       new_task_dataframe,
                                       new_workflow_dataframe,
                                       branch_stats,
                                       task_stats,
                                       paths_map)
            print("Feedback report step successful! \n")
            print("Report file:///{} has been saved. \n".format(report.replace('\\', '/')))
            print("Workflow Analysis Finished!")
        except (KeyError, ValueError) as e:
            sys.stderr.write("Results analysis step unsuccessful :( \n")
            return e
    else:
        print("No historical data available.")
    print("Saving new workflow execution data to historical data...")
    ### STEP 7 ###
    add_latest_exec_to_historical_data(task_historical_data_path,
                                       tasks_historical_data, task_df)
    add_latest_exec_to_historical_data(workflow_historical_data_path,
                                       workflow_historical_data, workflow_df)


def main():
    arguments = get_arguments()

    absolute_path = pathlib.Path(__file__).parent.absolute()
    json_file_path = "{}/{}".format(absolute_path, arguments.filepath)
    user = arguments.user
    user_dir = "{}/files/{}".format(absolute_path, user)
    report_path = '{}/../reports/{}'.format(absolute_path, user)
    historical_directory = "{}/csvs".format(user_dir)
    figures_directory = "{}/report/figures".format(user_dir)

    # each user gets its own directory to store the historical data, figures and report outputs
    # this checks whether the directory exists, and if it doesn't, creates it
    if not os.path.exists(historical_directory):
        os.makedirs(historical_directory)
    if not os.path.exists(figures_directory):
        os.makedirs(figures_directory)
    if not os.path.exists(report_path):
        os.makedirs(report_path)

    paths_map = {'input_file': json_file_path,
                 'output_dir': report_path,
                 'hist_dir': historical_directory,
                 'figures_dir': figures_directory}

    # retrieve the rest of the command-line arguments
    task_features = [arg for arg in arguments.task_features]
    workflow_features = [arg for arg in arguments.workflow_features]

    task_rf_label_map = {'classifier': [], 'regressor': []}
    workflow_rf_label_map = {'classifier': [], 'regressor': []}

    task_rf_label_map['classifier'] = [arg for arg in arguments.task_classifier]
    task_rf_label_map['regressor'] = [arg for arg in arguments.task_regressor]
    workflow_rf_label_map['classifier'] = [arg for arg in arguments.wk_classifier]
    workflow_rf_label_map['regressor'] = [arg for arg in arguments.wk_regressor]

    print("Welcome to the Workflow Analysis System!")
    print("Starting...")
    analyse(paths_map,
            task_features,
            workflow_features,
            task_rf_label_map,
            workflow_rf_label_map)

    print("Exiting...")


if __name__ == "__main__":
    main()
