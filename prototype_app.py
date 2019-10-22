from typing import Dict, Tuple
import streamlit as st
import numpy as np
import scipy as sp

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns

from exploration_view import exploration_view
from util import generate_random_winrate_matrix, generate_random_discrete_distribution 
from util import compute_progression_of_nash_during_training
from util import highlight_text


@st.cache
def compute_winrate_matrices(num_matrices):
    matrices = {checkpoint: generate_random_winrate_matrix(size + 1)
                for size, checkpoint in enumerate(range(100, 1001, 100))}
    return matrices

    
def single_empirical_game_view():
    name = 'Single empirical winrate game'
    st.write(f'# {name}')

    selfplay_choice = st.sidebar.radio('Select Self-Play algorithm',
                                       ('Naive SP', 'Full History SP', 'Iterated Nash Response'))

    min_checkpoint, max_checkpoint, step_checkpoint = 100, 1000, 100
    range_checkpoint = range(min_checkpoint, max_checkpoint + 1, step_checkpoint)
    checkpoint = st.sidebar.slider('Choose benchmarking checkpoint (episode number)',
                                   min_checkpoint, max_checkpoint, step=step_checkpoint)


    progression_nash = compute_progression_of_nash_during_training(range_checkpoint)

    plot_progression_nash_equilibriums(progression_nash, highlight=checkpoint)

    st.write('## Winrate matrix and Logit matrix heatmaps')

    matrices = compute_winrate_matrices(num_matrices=len(range_checkpoint))
    winrate_matrix = matrices[checkpoint]
    logit_matrix = np.log(winrate_matrix / (np.ones_like(winrate_matrix) - winrate_matrix))

    plot_game_matrices(winrate_matrix, logit_matrix)

    st.write('## `TODO:` Nash marginals and joint heatmap (which joint actions / payoffs are most common)')


def plot_game_matrices(winrate_matrix, logit_matrix):
    fig, ax = plt.subplots(1, 2)
    ax[0].set_title('Empirical winrate matrix')
    winrate_matrix_heatmap = sns.heatmap(winrate_matrix, annot=True, ax=ax[0], cmap=sns.color_palette('RdYlGn_r')[::-1],
                                         vmin=0.0, vmax=1.0, cbar_kws={'label': 'Head to head winrates'})
    ax[0].set_xlabel('Agent ID')
    ax[0].set_ylabel('Agent ID')

    ax[1].set_title('Log-odds winrate matrix')
    logit_matrix_heatmap = sns.heatmap(logit_matrix, annot=True, ax=ax[1], cmap=sns.color_palette('RdYlGn_r')[::-1],
                                       cbar=False)
    ax[1].set_xlabel('Agent ID')
    ax[0].set_ylim(len(winrate_matrix) + 0.2, -0.2)
    ax[1].set_ylim(len(logit_matrix) + 0.2, -0.2)
    plt.tight_layout()
    st.pyplot()
    plt.close()


def plot_progression_nash_equilibriums(progression_nash, highlight):
    fig, ax = plt.subplots(1, 1)
    # Only show lower triangular
    mask = np.zeros_like(progression_nash)
    mask[np.triu_indices_from(mask, k=1)] = True
    sns.heatmap(progression_nash.transpose(), annot=True, mask=mask, vmax=1.0, vmin=0.0,
                cmap=sns.color_palette('RdYlGn_r')[::-1], cbar_kws={'label': 'Support under Nash'})
    # Workaround to prevent top and bottom of heatmaps to be cutoff
    # This is a known matplotlib bug
    ax.set_ylim(len(progression_nash) + 0.2, -0.2)
    plt.title('Progression of Nash equilibrium during training')
    plt.ylabel('Training iteration')
    plt.xlabel('Agent ID')

    highlight_text(ax, str(highlight))

    st.pyplot()
    plt.close()


def run():
    VIEWS = {'Optimality (external) measurements': single_empirical_game_view,
             'Exploration (internal) measurements': exploration_view}
    view_name = st.sidebar.selectbox("Choose view", list(VIEWS.keys()), 0)
    view = VIEWS[view_name]

    view()


if __name__ == '__main__':
    run()
