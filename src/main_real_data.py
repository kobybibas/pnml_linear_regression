import logging
import os
import os.path as osp
import time

import hydra
import pandas as pd
import psutil
import ray

from data_utils.real_data_utils import create_trainset_sizes_to_eval, execute_trails
from data_utils.real_data_utils import download_regression_datasets, get_data

logger = logging.getLogger(__name__)


def submit_dataset_experiment_jobs(dataset_name: str, cfg) -> pd.DataFrame:
    # Get dataset statistic
    train_ratio, val_ratio, test_ratio = 0.6, 0.2, 0.2
    x_all, y_all = get_data(dataset_name, cfg.data_dir, is_add_bias_term=cfg.is_add_bias_term)
    n_train, n_features = int(train_ratio * x_all.shape[0]), x_all.shape[1]

    # Define train set to evaluate
    trainset_sizes = create_trainset_sizes_to_eval(n_train, n_features,
                                                   cfg.num_trainset_sizes_over_param,
                                                   cfg.is_underparam_region, cfg.num_trainset_sizes_under_param)
    logger.info('{}: [n_data, n_features]=[{} {}]'.format(dataset_name, x_all.shape[0], n_features))
    logger.info(trainset_sizes)

    # Pass the same large object into a number of tasks.
    x_all_id = ray.put(x_all)

    # Submit tasks
    task_list = [execute_trails.remote(x_all_id, y_all, cfg.n_trails, trainset_size,
                                       dataset_name, i, len(trainset_sizes),
                                       is_eval_mdl=cfg.is_eval_mdl,
                                       is_eval_empirical_pnml=cfg.is_eval_empirical_pnml,
                                       is_eval_analytical_pnml=cfg.is_eval_analytical_pnml,
                                       is_adaptive_var=cfg.is_adaptive_var,
                                       is_standardize_feature=cfg.is_standardize_feature,
                                       is_standardize_samples=cfg.is_standardize_samples
                                       ) for i, trainset_size in enumerate(trainset_sizes)]
    return task_list


def collect_dataset_experiment_results(ray_task_list: list):
    """
    Wait task experiment to finish
    :param ray_task_list: list of jobs
    :return: dataframe with results
    """

    res_list = []
    total_jobs = len(ray_task_list)
    for job_num in range(total_jobs):
        t1 = time.time()
        ready_id, ray_task_list = ray.wait(ray_task_list)
        res_i = ray.get(ready_id[0])
        res_list.append(res_i)
        logger.info(
            '[{:04d}/{}] {}. Size [train val test]=[{:03d} {} {}] in {:3.1f} sec. Local time {:3.1f} sec'.format(
                job_num, total_jobs - 1, res_i['dataset_name'],
                res_i['trainset_size'], res_i['valset_size'], res_i['testset_size'],
                         time.time() - t1, res_i['time']))

    # Save to file
    res_df = pd.DataFrame(res_list)
    res_df = res_df.sort_values(by=['num_features', 'trainset_size', 'dataset_name'], ascending=[False, True, True])
    return res_df


def ray_init(cpu_num: int, is_local_mode: bool):
    """
    Initialize multiprocess. Every trainset size in a separate process
    :param cpu_num: NUmber of cpu to use. -1 to use all available
    :param is_local_mode: whether to run in the local computer. Used for debug.
    :return:
    """
    cpu_count = psutil.cpu_count()
    cpu_to_use = cpu_num if cpu_num > 0 else cpu_count
    cpu_to_use = cpu_to_use if is_local_mode is False else 1
    logger.info('cpu_count={}. Executing on {}. is_local_mode={}'.format(cpu_count, cpu_to_use, is_local_mode))
    ray.init(local_mode=is_local_mode, num_cpus=cpu_to_use)


@hydra.main(config_name='../configs/real_data.yaml')
def execute_real_datasets_experiment(cfg):
    t0 = time.time()
    logger.info(cfg.pretty())
    out_path = os.getcwd()

    # Move from output directory to src
    os.chdir('../../src')
    logger.info('[cwd out_dir]=[{} {}]'.format(os.getcwd(), out_path))

    # Download data
    if cfg.is_datasets_statistics is True:
        download_regression_datasets(cfg.data_dir, out_path)

    # Initialize multiprocess. Every trainset size in a separate process
    ray_init(cfg.num_cpus, cfg.is_local_mode)

    # Iterate on datasets: send jobs
    ray_task_list, len_datasets = [], len(cfg.dataset_names)
    for i, dataset_name in enumerate(cfg.dataset_names):
        t1 = time.time()
        ray_task_list += submit_dataset_experiment_jobs(dataset_name, cfg)
        logger.info('[{}/{}] Finish submit dataset {} in {:.2f} sec'.format(i, len_datasets - 1, dataset_name,
                                                                            time.time() - t1))

    # Collect results
    res_df = collect_dataset_experiment_results(ray_task_list)
    out_file = osp.join(out_path, 'results.csv')
    res_df.to_csv(out_file, index=False)
    logger.info('Finish! in {:.2f} sec. {}'.format(time.time() - t0, out_file))


if __name__ == "__main__":
    execute_real_datasets_experiment()