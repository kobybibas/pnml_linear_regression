import numpy as np

from learner_classes.learner_utils import compute_mse, compute_logloss, estimate_sigma_with_valset


def calc_theta_mn(x_arr: np.ndarray, y_vec: np.ndarray) -> np.ndarray:
    # x_arr: each row is feature vec
    inv = np.linalg.pinv(x_arr.T @ x_arr)
    theta = inv @ x_arr.T @ y_vec
    return theta


def calc_mn_learner_performance(x_train: np.ndarray, y_train: np.ndarray,
                                x_val: np.ndarray, y_val: np.ndarray,
                                x_test: np.ndarray, y_test: np.ndarray,
                                theta_mn: np.ndarray = None) -> dict:
    if theta_mn is None:
        theta_mn = calc_theta_mn(x_train, y_train)

    var = estimate_sigma_with_valset(x_val, y_val, theta_mn)

    res_dict_mn = {'test_mse': compute_mse(x_test, y_test, theta_mn),
                   'train_mse': compute_mse(x_train, y_train, theta_mn),
                   'theta_norm': np.mean(theta_mn ** 2),
                   'test_logloss': compute_logloss(x_test, y_test, theta_mn, var),
                   'variance': var}
    return res_dict_mn
