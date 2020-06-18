import logging

import math
import numpy as np
from scipy.optimize import NonlinearConstraint, minimize

from pnml_utils import Pnml, add_test_to_train

logger = logging.getLogger(__name__)


class PnmlMinNorm(Pnml):
    def __init__(self, constrain_factor, *args, **kargs):
        super().__init__(*args, **kargs)

        # The norm constrain is set to: constrain_factor * ||\theta_MN||^2
        self.constrain_factor = constrain_factor

        #  The norm constrain is set to: constrain_factor * ||\theta_MN||^2
        theta_erm_min_norm = super().fit_least_squares_estimator(self.phi_train, self.y_train)
        self.max_norm = self.constrain_factor * np.sum(theta_erm_min_norm ** 2)

        # Fitted least squares parameters with norm constraint
        self.fit_least_squares_estimator = self.fit_least_squares_estimator_with_max_norm
        self.theta_erm = self.fit_least_squares_estimator(self.phi_train, self.y_train, lamb=0.0)

    def set_constrain_factor(self, constrain_factor: float):
        # The norm constrain is set to: constrain_factor * ||\theta_MN||^2
        self.constrain_factor = constrain_factor

    def fit_least_squares_estimator_with_max_norm(self, phi: np.ndarray, y: np.ndarray,
                                                  lamb: float = 0.0) -> np.ndarray:
        max_norm = self.max_norm

        def cons_f(x):
            return (x ** 2).sum()

        def cons_J(x):
            return 2 * x

        def mse(x):
            return np.power(y - x.T.dot(phi), 2).mean()

        x0 = self.theta_erm if self.theta_erm is not None else np.zeros(phi.shape[0])

        nonlinear_constraint = NonlinearConstraint(cons_f, 0, max_norm, jac=cons_J)
        res = minimize(mse, x0, constraints=[nonlinear_constraint], method='SLSQP',
                       options={'disp': False, 'maxiter': 1000, 'ftol': 1e-12})
        if res.success is False:
            logger.info('fit_least_squares_estimator_with_max_norm: Failed')
            logger.info('y: {}'.format(y[-1]))
            logger.info(res)
        theta = res.x
        return theta

    def calc_pnml_epsilon(self, y_test, phi_test, phi, y_train) -> float:
        """
        :param y_test: Test sample label
        :param phi_test: Test sample data
        :param phi: features of all dataset, train + test sample
        :param y_train: trainset labels
        :return:
        """
        y = np.append(y_train, y_test)
        theta = self.fit_least_squares_estimator(phi, y, lamb=0.0)
        y_hat = phi_test.T.dot(theta)
        return float(y_test - y_hat)

    @staticmethod
    def calc_genies_probs(epsilons: np.ndarray, sigma_square: float) -> np.ndarray:
        genies_probs = (1 / np.sqrt(2 * np.pi * sigma_square)) * np.exp(-epsilons ** 2 / (2 * sigma_square))
        return genies_probs

    def execute_regret_calc(self, phi_test: np.array):
        """
        Calculate normalization factor using numerical integration
        :param phi_test: test features to evaluate.
        :return: log normalization factor.
        """
        assert self.phi_train is not None
        assert self.theta_erm is not None

        phi = add_test_to_train(self.phi_train, phi_test)

        # Predict around the ERM prediction
        y_pred = self.theta_erm.T.dot(phi)[-1]
        y_vec = self.y_to_eval + y_pred

        # Genies prediction
        epsilons = np.array([self.calc_pnml_epsilon(y, phi_test, phi, self.y_train) for y in y_vec])
        genies_probs = self.calc_genies_probs(epsilons, self.min_sigma_square)

        # Integrate to find the pNML normalization factor
        norm_factor = np.trapz(genies_probs, x=y_vec)

        # The genies predictors
        self.genies_output = {'y_vec': y_vec, 'probs': genies_probs, 'epsilons': epsilons}
        regret = np.log(norm_factor)
        return regret


def calc_analytic_norm_factor(phi_train: np.ndarray, phi_test: np.ndarray,
                              theta_mn: np.ndarray, sigma_square: float) -> float:
    """
    Calculate the normalization factor of the pnml learner.
    :param phi_train: the train feature matrix (train+test).
    :param phi_test: test features.
    :param sigma_square: the variance of the noise.
    :param theta_mn: minimum norm solution parameters
    :return: normalization factor.
    """
    M, N = phi_train.shape
    u, h_square, uh = np.linalg.svd(phi_train.dot(phi_train.T), full_matrices=True)
    P_N = np.linalg.pinv(phi_train.dot(phi_train.T))
    theta_mn_P_N_theta_mn = theta_mn.T.dot(P_N).dot(theta_mn)

    # x^T P_N^|| x
    x_P_N_x = np.sum(((u.T.dot(phi_test)).squeeze() ** 2 / h_square)[:N])

    # ||x_\bot||^2
    x_bot_square = np.sum(((u.T.dot(phi_test)) ** 2)[N:])

    # Analytical normalization factor
    nf = 1 + x_P_N_x + (2 * math.gamma(7 / 6) / np.sqrt(np.pi)) * (
                (theta_mn_P_N_theta_mn ** 2) * (x_bot_square ** 4) / (sigma_square ** 2)) ** (1 / 6)
    return nf


def execute_x_test_regret(x_test: np.ndarray,
                          model_degree: int,
                          sigma_square: float,
                          constant_dict: dict,
                          genie_file: str,
                          debug_dict=None,
                          ):
    # Get constant
    P_N = constant_dict["P_N"]
    theta_mn_P_N_theta_mn = constant_dict["theta_mn_P_N_theta_mn"]
    u = constant_dict["u"]
    h_square = constant_dict["h_square"]
    data_h = constant_dict["data_h"]
    phi_train = constant_dict["phi_train"]
    M, N = phi_train.shape

    # Convert to features
    phi_test = data_h.convert_point_to_features(x_test, model_degree)

    # x^T P_N^|| x
    x_P_N_x = np.sum(((u.T.dot(phi_test)).squeeze() ** 2 / h_square)[:N])

    # ||x_\bot||^2
    x_bot_square = np.sum(((u.T.dot(phi_test)) ** 2)[N:])

    # Simulation
    nf_simulation, genies_probs, y_vec = calc_nf_from_simulation(genie_file, sigma_square)
    regret_simulation = np.log(nf_simulation)

    # Analytical
    regret_analytical = np.log(
        1
        + x_P_N_x
        + (2 * math.gamma(7 / 6) / np.sqrt(np.pi))
        * ((theta_mn_P_N_theta_mn ** 2) * (x_bot_square ** 4) / (sigma_square ** 2)) ** (1 / 6)
    )

    # Add to debug dict
    if debug_dict is not None:
        debug_dict["x_bot_square"].append(x_bot_square)
        debug_dict["sigma_square"].append(sigma_square)
        debug_dict["x_P_N_x"].append(x_P_N_x)
        debug_dict["genies_probs"].append(genies_probs)
        debug_dict["y_vec"].append(y_vec)
    if nf_simulation < 1:
        print("Warning: ", x_test, nf_simulation)
    return regret_simulation, regret_analytical, debug_dict
