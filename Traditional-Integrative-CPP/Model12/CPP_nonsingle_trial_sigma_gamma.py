#!/home/a.ghaderi/.conda/envs/envjm/bin/python

import os
import numpy as np
from scipy import stats
from time import time
import matplotlib.pyplot as plt

from numba import njit
import tensorflow as tf

from bayesflow.networks import InvertibleNetwork, InvariantNetwork
from bayesflow.amortizers import SingleModelAmortizer
from bayesflow.trainers import ParameterEstimationTrainer
from bayesflow.diagnostics import *
from bayesflow.models import GenerativeModel


def prior(batch_size):
    """
    Samples from the prior 'batch_size' times. 
    ----------

    Arguments:
    batch_size : int -- the number of samples to draw from the prior
    ----------

    Output:
    theta : np.ndarray of shape (batch_size, theta_dim) -- the samples batch of parameters
    """

    # Prior ranges for the simulator
    # drift ~ U(-3.0, 3.0)
    # boundary ~ U(0.5, 4.0)
    # beta ~ U(0.1, 0.9)  # relative start point
    # tau ~ U(0.1, 1.0)
    # sigma_e ~ U(0.1, 4.0)
    # gamma ~ ~ U(0.5, 4.0) 
    n_parameters = 6
    p_samples = np.random.uniform(low=(0.1, 0.5, 0.1, 0.1, 0.1, 0.5),
                                  high=(3.0, 4.0, 0.9, 1.0, 4.0, 4.0), size=(batch_size, n_parameters))
    return p_samples.astype(np.float32)

@njit
def diffusion_trial(drift, boundary, beta, ndt, sigma, gamma, dc=1.0, dt=.005, max_steps=2e4):
    """Simulates a trial from the diffusion model."""

    n_steps = 0.
    evidence = boundary * beta

    # Simulate a single DM path
    while (evidence > 0 and evidence < boundary and n_steps < max_steps):

        # DDM equation
        evidence += drift*dt + np.sqrt(dt) * dc * np.random.normal()

        # Increment step
        n_steps += 1.0

    # decision time
    dt = n_steps * dt

    # CPP slope
    cpp = np.random.normal(gamma*drift, sigma)
    
    if evidence >= boundary:
        choicert =  dt + ndt
        
    elif evidence <= 0:
        choicert = -dt - ndt
    else:
        choicert = np.sign(evidence - boundary*.5)*(dt + ndt)  # Choose closest boundary at max_steps
    return choicert, cpp

@njit
def diffusion_condition(params, n_trials):
    """Simulates a diffusion process over an entire condition."""

    drift, boundary, beta, ndt, sigma, gamma = params
    choicert = np.empty(n_trials)
    cpp = np.empty(n_trials)
    for i in range(n_trials):
        choicert[i], cpp[i] = diffusion_trial(drift, boundary, beta, ndt, sigma, gamma)
    return choicert, cpp

def batch_simulator(prior_samples, n_obs):
    """
    Simulate multiple diffusion_model_datasets.
    """

    n_sim = prior_samples.shape[0]
    sim_choicert = np.empty((n_sim, n_obs), dtype=np.float32)
    sim_cpp = np.empty((n_sim, n_obs), dtype=np.float32)

    # Simulate diffusion data
    for i in range(n_sim):
        sim_choicert[i], sim_cpp[i] = diffusion_condition(prior_samples[i], n_obs)

    # For some reason BayesFlow wants there to be at least two data dimensions
    sim_data = np.stack([sim_choicert, sim_cpp], axis=-1)
    return sim_data

# Connect the networks through a SingleModelAmortizer instance.
summary_net = InvariantNetwork()
inference_net = InvertibleNetwork({'n_params': 6})
amortizer = SingleModelAmortizer(inference_net, summary_net)

# Connect the prior and simulator through a GenerativeModel class which will take care of forward inference.
generative_model = GenerativeModel(prior, batch_simulator)

trainer = ParameterEstimationTrainer(
    network=amortizer,
    generative_model=generative_model,
    checkpoint_path="Checkpoint"
)

# Variable n_trials
def prior_N(n_min=100, n_max=300):
    """
    A prior or the number of observation (will be called internally at each backprop step).
    """

    return np.random.randint(n_min, n_max + 1)

# Experience-replay training
losses = trainer.train_experience_replay(epochs=500,
                                         batch_size=32,
                                         iterations_per_epoch=1000,
                                         capacity=100,
                                         n_obs=prior_N)

# Validate (quick and dirty)
n_param_sets = 500
n_samples = 1000
true_params = prior(n_param_sets)
x = batch_simulator(true_params, n_samples).astype(np.float32)
param_samples = amortizer.sample(x, n_samples=n_samples)
param_means = param_samples.mean(axis=0)
true_vs_estimated(true_params, param_means, ['drift', 'boundary', 'beta', 'ndt', 'sigma', 'gamma'], filename="../Save_Validate/NDDM2_sigma_gamma_4")
