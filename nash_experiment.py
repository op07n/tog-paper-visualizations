import logging
import pickle
import os
import time
from typing import List, Tuple

import yaml
import torch
import numpy as np
import pandas as pd

from regym.util.experiment_parsing import initialize_agents
from regym.util.experiment_parsing import initialize_training_schemes
from regym.util.experiment_parsing import filter_relevant_agent_configurations
from regym.environments import generate_task
from regym.environments.task import Task
from regym.rl_loops.multiagent_loops.simultaneous_action_rl_loop import self_play_training
from regym.training_schemes import SelfPlayTrainingScheme, NaiveSelfPlay, FullHistorySelfPlay
from regym.rl_algorithms import build_PPO_Agent, AgentHook

from regym.game_theory import compute_winrate_matrix_metagame, compute_nash_averaging


def experiment(task: Task, training_agent, self_play_scheme: SelfPlayTrainingScheme,
               checkpoint_at_iterations: List[int], base_path: str, seed: int,
               benchmarking_episodes: int):
    logger = logging.getLogger(f'Experiment: Task: {task.name}. SP: {self_play_scheme.name}. Agent: {training_agent.name}')

    np.random.seed(seed)
    torch.manual_seed(seed)

    population = training_phase(task, training_agent, self_play_scheme,
                                checkpoint_at_iterations, base_path)
    logger.info('FINISHED training! Moving to saving')
    winrate_submatrices, evolution_maxent_nash_and_nash_averaging = compute_optimality_metrics(population, task,
                                                                                               benchmarking_episodes,
                                                                                               logger)
    save_results(winrate_submatrices,
                 evolution_maxent_nash_and_nash_averaging,
                 checkpoint_at_iterations,
                 save_path=f'{base_path}/results')
    logger.info('FINISHED saving')
    logger.info('DONE')


def compute_optimality_metrics(population, task, benchmarking_episodes, logger):
    logger.info('Computing winrate matrix')
    winrate_matrix = compute_winrate_matrix_metagame(population, env=task.env,
                                                     episodes_per_matchup=benchmarking_episodes)
    winrate_submatrices = [winrate_matrix[:i, :i] for i in range(1, len(winrate_matrix) + 1)]
    logger.info('Computing nash averagings for all submatrices')
    evolution_maxent_nash_and_nash_averaging = [compute_nash_averaging(m, perform_logodds_transformation=True)
                                                for m in winrate_submatrices]
    return winrate_submatrices, evolution_maxent_nash_and_nash_averaging


def save_results(winrate_submatrices: List[np.ndarray],
                 evolution_maxent_nash_and_nash_averaging: List[Tuple[np.ndarray]],
                 checkpoint_at_iterations: List[int],
                 save_path: str):
    if not os.path.exists(save_path): os.makedirs(save_path)
    save_winrate_matrices(winrate_submatrices, checkpoint_at_iterations, save_path)
    save_evolution_maxent_nash_and_nash_averaging(evolution_maxent_nash_and_nash_averaging,
                                                  checkpoint_at_iterations, save_path)


def save_winrate_matrices(winrate_submatrices, checkpoint_at_iterations, save_path):
    checkpoints_winrate_submatrices = {checkpoint: m
                                       for checkpoint, m in
                                       zip(checkpoint_at_iterations, winrate_submatrices)}
    pickle.dump(checkpoints_winrate_submatrices,
                open(f'{save_path}/winrate_matrices.pickle', 'wb'))


def save_evolution_maxent_nash_and_nash_averaging(evolution_maxent_nash_and_nash_averaging, checkpoint_at_iterations, save_path):
    maxent_nash_list, nash_averaging_list = zip(*evolution_maxent_nash_and_nash_averaging)
    nash_progression_df = pd.DataFrame(maxent_nash_list, index=checkpoint_at_iterations,
                                       columns=list(range(len(checkpoint_at_iterations))))
    nash_progression_df.to_csv(path_or_buf=f'{save_path}/evolution_maxent_nash.csv')


def training_phase(task: Task, training_agent, self_play_scheme: SelfPlayTrainingScheme,
                   checkpoint_at_iterations: List[int], base_path: str):
    """
    :param task: Task on which agents will be trained
    :param training_agent: agent representation + training algorithm which will be trained in this process
    :param self_play_scheme: self play scheme used to meta train the param training_agent.
    :param checkpoint_at_iterations: array containing the episodes at which the agents will be cloned for benchmarking against one another
    :param agent_queue: queue shared among processes to submit agents that will be benchmarked
    :param process_name: String name identifier
    :param base_path: Base directory from where subdirectories will be accessed to reach menageries, save episodic rewards and save checkpoints of agents.
    """

    logger = logging.getLogger(f'TRAINING: Task: {task.name}. SP: {self_play_scheme.name}. Agent: {training_agent.name}')
    logger.info('Started')

    menagerie, menagerie_path = [], f'{base_path}/menagerie'
    agents_to_benchmark = [] # Come up with better name

    if not os.path.exists(base_path):
        os.makedirs(base_path)
        os.mkdir(menagerie_path)

    completed_iterations, start_time = 0, time.time()

    trained_policy_save_directory = base_path

    for target_iteration in sorted(checkpoint_at_iterations):
        next_training_iterations = target_iteration - completed_iterations
        (menagerie, trained_agent,
         trajectories) = train_for_given_iterations(task.env, training_agent, self_play_scheme,
                                                    menagerie, menagerie_path,
                                                    next_training_iterations, completed_iterations, logger)
        del trajectories # we are not using them here
        completed_iterations += next_training_iterations
        save_trained_policy(trained_agent,
                            save_path=f'{trained_policy_save_directory}/{target_iteration}_iterations.pt',
                            logger=logger)

        agents_to_benchmark += [trained_agent.clone()]
        training_agent = trained_agent # Updating

    logger.info('FINISHED training. Total duration: {} seconds'.format(time.time() - start_time))
    return agents_to_benchmark


def train_for_given_iterations(env, training_agent, self_play_scheme,
                               menagerie, menagerie_path,
                               next_training_iterations, completed_iterations, logger):

    training_start = time.time()
    (menagerie, trained_agent,
     trajectories) = self_play_training(env=env, training_agent=training_agent, self_play_scheme=self_play_scheme,
                                        target_episodes=next_training_iterations, iteration=completed_iterations,
                                        menagerie=menagerie, menagerie_path=menagerie_path)
    training_duration = time.time() - training_start
    logger.info('Training between iterations [{}, {}]: {:.2} seconds'.format(
                completed_iterations, completed_iterations + next_training_iterations,
                training_duration))
    return menagerie, training_agent, trajectories


def save_trained_policy(trained_agent, save_path: str, logger):
    logger.info(f'Saving agent \'{trained_agent.name}\' in \'{save_path}\'')
    AgentHook(trained_agent.clone(training=False), save_path=save_path)


def initialize_experiment(experiment_config, agents_config):
    task = generate_task(experiment_config['environment'])
    sp_schemes = initialize_training_schemes(experiment_config['self_play_training_schemes'])
    agents = initialize_agents(experiment_config['environment'], agents_config)

    seed = experiment_config['seed']
    return task, sp_schemes, agents, seed


def load_configs(config_file_path):
    all_configs = yaml.load(open(config_file_path), Loader=yaml.FullLoader)
    experiment_config = all_configs['experiment']
    agents_config = filter_relevant_agent_configurations(experiment_config,
                                                         all_configs['agents'])
    return experiment_config, agents_config


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    config_file_path = './config.yaml'
    experiment_config, agents_config = load_configs(config_file_path)

    task, sp_schemes, agents, seed = initialize_experiment(experiment_config, agents_config)
    checkpoint_at_iterations = list(range(0, 50, 10))

    base_path = experiment_config['experiment_id']
    import ipdb; ipdb.set_trace()
    for sp_scheme in sp_schemes:
        for agent in agents:
            training_agent = agent.clone(training=True)
            path = f'{base_path}/{sp_scheme.name}-{agent.name}'
            experiment(task=task, self_play_scheme=sp_scheme,
                       training_agent=training_agent,
                       checkpoint_at_iterations=checkpoint_at_iterations,
                       benchmarking_episodes=experiment_config['benchmarking_episodes'],
                       base_path=path, seed=seed)
