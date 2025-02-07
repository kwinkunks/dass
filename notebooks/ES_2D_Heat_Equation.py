# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.14.4
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Parameter estimation using ES and the 2D Heat Equation

# %%
import numpy as np
import pandas as pd

np.set_printoptions(suppress=True)
# Relatively easy to find good solution
rng = np.random.default_rng(1234)
# More difficult
# rng = np.random.default_rng(100)

import matplotlib.pyplot as plt

plt.rcParams["figure.figsize"] = (6, 6)
plt.rcParams.update({"font.size": 10})
# Ignore error when drawing many figures
plt.rcParams.update({"figure.max_open_warning": 0})
from ipywidgets import interact
import ipywidgets as widgets

from p_tqdm import p_map

from scipy.ndimage import gaussian_filter

import iterative_ensemble_smoother as ies

# %%
# %load_ext autoreload
# %autoreload 2
from dass import pde, utils, analysis, taper, geostat

# %% [markdown]
# ## Define ensemble size and parameters related to the simulator

# %%
N = 50

# Number of grid-cells in x and y direction
nx = 10

# time steps
k_start = 0
k_end = 500

# %% [markdown]
# ## Define prior
#
# The Ensemble Smoother searches for solutions in `Ensemble Subspace`, which means that it tries to find a linear combination of the priors that best fit the observed data.
# A good prior is therefore vital.
#
# Some fields are trickier to solve than others.
# Here are two ways of defining a prior, one more complex or difficult to solve for than the other.

# %%
complex_prior = True


def sample_prior_perm(N):
    mesh = np.meshgrid(np.linspace(0, 1, nx), np.linspace(0, 1, nx))
    lperms = np.exp(geostat.gaussian_fields(mesh, rng, N, r=0.8))
    return lperms


# Evensens' formulation of the Ensemble Smoother has the prior as
# a (nx * nx, N) matrix, i.e (number of parameters, N).
if complex_prior:
    A = sample_prior_perm(N).T

    alphas = []
    for j in range(A.shape[1]):
        alphas.append(A[:, j].reshape(nx, nx))

else:
    alphas = []
    for i in range(N):
        alpha = np.exp(
            5
            * gaussian_filter(
                gaussian_filter(rng.random(size=(nx, nx)), sigma=2.0), sigma=1.0
            )
        )
        alphas.append(alpha)

    A = np.zeros(shape=(nx * nx, N))
    for e in range(N):
        A[:, e] = alphas[e].ravel()

# %%
# Putting multiple 2D matrices into a single matrix and from that calculate covariance matrices
# leads to a somewhat strange looking matrix.
plt.matshow(np.cov(A))

# %% [markdown]
# ## Define true parameters, set true initial conditions and calculate the true temperature field
#
# Perhaps obvious, but we do not have this information in real-life.

# %%
dx = 1

if complex_prior:
    # Set the coefficient of heat transfer for each grid cell.
    alpha_t = sample_prior_perm(1).T.reshape(nx, nx)
else:
    # Using trick from page 15 of "An Introduction to the Numerics of Flow in Porous Media using Matlab".
    # It's a nice way to generate realistic-looking parameter fields.
    # In real life we use third-party tools to generate good (whatever that means) prior parameter fields.
    alpha_t = np.exp(
        5
        * gaussian_filter(
            gaussian_filter(rng.random(size=(nx, nx)), sigma=2.0), sigma=1.0
        )
    )

# Calculate maximum `dt`.
# If higher values are used, the numerical solution will become unstable.
dt = dx**2 / (4 * max(np.max(A), np.max(alpha_t)))

# True initial temperature field.
u_init = np.empty((k_end, nx, nx))
u_init.fill(0.0)

# Heating the plate at two points initially.
# How you define initial conditions will effect the spread of results,
# i.e., how similar different realisations are.
u_init[:, 5, 5] = 100
# u_init[:, 6, 6] = 100

# How much noise to add to heat equation, also called model noise.
# scale = 0.1
scale = None

u_t = pde.heat_equation(u_init, alpha_t, dx, dt, k_start, k_end, rng=rng, scale=scale)

# %% [markdown]
# # How-to create animation (Press `y` to convert from markdown to code)
#
# import matplotlib.animation as animation
# from matplotlib.animation import FuncAnimation
#
# fig, ax = plt.subplots()
# p = ax.pcolormesh(u[0], cmap=plt.cm.jet)
# fig.colorbar(p)
#
# def animate(k):
#     return p.set_array(u[k])
#
# anim = animation.FuncAnimation(
#     fig, animate, interval=1, frames=k_end, repeat=False
# )
# anim.save("heat_equation_solution.gif", writer="imagemagick")

# %% [markdown]
# ## Plot every cells' heat transfer coefficient, i.e., the parameter field

# %%
fig, ax = plt.subplots()
ax.set_title("True parameter field")
ax.invert_yaxis()
p = ax.pcolormesh(alpha_t.T)
utils.colorbar(p)
fig.tight_layout()


# %% [markdown]
# ## Interactive plot of true temperature field
#
# Shows how the temperature of the true field changes with time.

# %%
def interactive_truth(k):
    fig, ax = plt.subplots()
    fig.suptitle("True temperature field")
    p = ax.pcolormesh(u_t[k].T, cmap=plt.cm.jet, vmin=0, vmax=100)
    ax.invert_yaxis()
    ax.set_title(f"k = {k}")
    utils.colorbar(p)
    fig.tight_layout()


interact(
    interactive_truth,
    k=widgets.IntSlider(min=k_start, max=k_end - 1, step=1, value=0),
)

# %% [markdown]
# ## Define placement of sensors and generate synthetic observations based on the true temperature field

# %%
# Heat sources are kind of like injection wells
# We can think about heat sources as injection wells.
# Sensors would then typically be placed where we have production wells.
# We'll place the sensors close to heat-sources because the plate cools of quite quickly.
obs_coordinates = [
    utils.Coordinate(5, 3),
    utils.Coordinate(3, 5),
    utils.Coordinate(5, 7),
    utils.Coordinate(7, 5),
    utils.Coordinate(2, 2),
    utils.Coordinate(7, 2),
]

# Random placement of sensors
# Try adding a lot of sensors to see how the fit changes.
# As a side-note, in a reservoir setting, we might drill horizontal wells so sensors
# may in fact be placed quite far away from whever we started drilling a production well.
# pad = 1
# coords = np.array([(x, y) for x in range(pad, nx - pad) for y in range(pad, nx - pad)])
# ncoords = coords.shape[0]
# nmeas = 10
# coords_idx = np.random.choice(np.arange(ncoords), size=nmeas, replace=False)
# obs_coordinates = [utils.Coordinate(xc, yc) for xc, yc in coords[coords_idx]]

# At which times observations are taken
obs_times = np.linspace(5, k_end, 8, endpoint=False, dtype=int)

d = utils.observations(obs_coordinates, obs_times, u_t, lambda value: abs(0.05 * value))
# number of measurements
m = d.shape[0]
print("Number of observations: ", m)

k_levels = d.index.get_level_values("k").to_list()
x_levels = d.index.get_level_values("x").to_list()
y_levels = d.index.get_level_values("y").to_list()

# Plot temperature field and show placement of sensors.
obs_coordinates_from_index = set(zip(x_levels, y_levels))
x, y = zip(*obs_coordinates_from_index)

fig, ax = plt.subplots()
p = ax.pcolormesh(u_t[0].T, cmap=plt.cm.jet)
ax.invert_yaxis()
ax.set_title("True temperature field with sensor placement")
utils.colorbar(p)
ax.plot([i + 0.5 for i in x], [j + 0.5 for j in y], "s", color="white", markersize=5)

# %% [markdown]
# # Ensemble Smoother (ES)

# %% [markdown]
# ## Define random seeds because multiprocessing
#
# https://numpy.org/doc/stable/reference/random/parallel.html#seedsequence-spawning

# %%
ss = np.random.SeedSequence(12345)
child_seeds = ss.spawn(N)
streams = [np.random.default_rng(s) for s in child_seeds]


# %% [markdown]
# ## Interactive plot of prior parameter fields
#
# We will search for solutions in the space spanned by the prior parameter fields.
# This space is sometimes called the Ensemble Subspace.

# %%
def interactive_prior_fields(n):
    fig, ax = plt.subplots()
    ax.set_title(f"Prior field {n}")
    ax.invert_yaxis()
    p = ax.pcolormesh(alphas[n].T)
    utils.colorbar(p)
    fig.tight_layout()


interact(
    interactive_prior_fields,
    n=widgets.IntSlider(min=0, max=N - 1, step=1, value=0),
)

# %% [markdown]
# ## Run forward model (heat equation) `N` times

# %%
fwd_runs = p_map(
    pde.heat_equation,
    [u_init] * N,
    alphas,
    [dx] * N,
    [dt] * N,
    [k_start] * N,
    [k_end] * N,
    streams,
    [scale] * N,
    desc=f"Running forward model.",
)


# %% [markdown]
# ## Interactive plot of single realisations
#
# Note that every realization has the same initial temperature field at time-step `k=0`, but that the plate cools down differently because it has different material properties.

# %%
def interactive_realisations(k, n):
    fig, ax = plt.subplots()
    ax.invert_yaxis()
    fig.suptitle(f"Temperature field for realisation {n}")
    p = ax.pcolormesh(fwd_runs[n][k].T, cmap=plt.cm.jet, vmin=0, vmax=100)
    ax.set_title(f"k = {k}")
    utils.colorbar(p)
    fig.tight_layout()


interact(
    interactive_realisations,
    k=widgets.IntSlider(min=k_start, max=k_end - 1, step=1, value=0),
    n=widgets.IntSlider(min=0, max=N - 1, step=1, value=0),
)

# %% [markdown]
# ## Ensemble representation for measurements (Section 9.4 of [1])
#
# Note that Evensen calls measurements what ERT calls observations.

# %%
# Assume diagonal ensemble covariance matrix for the measurement perturbations.
# Is this a big assumption?
Cdd = np.diag(d.sd.values**2)

# 9.4 Ensemble representation for measurements
E = rng.multivariate_normal(mean=np.zeros(len(Cdd)), cov=Cdd, size=N).T
E = E - E.mean(axis=1, keepdims=True)
assert E.shape == (m, N)

# We will not use the sample covariance Cee, and instead use Cdd directly.
# It is not clear to us why Cee is proposed used.
# Cee = (E @ E.T) / (N - 1)

D = np.ones((m, N)) * d.value.values.reshape(-1, 1) + E

# %% [markdown]
# ## Measure model response at points in time and space where we have observations

# %%
Y_df = pd.DataFrame({"k": k_levels, "x": x_levels, "y": y_levels})

for real, fwd_run in enumerate(fwd_runs):
    Y_df = Y_df.assign(**{f"R{real}": fwd_run[k_levels, x_levels, y_levels]})

Y_df = Y_df.set_index(["k", "x", "y"], verify_integrity=True)

# %%
Y = Y_df.values

assert Y.shape == (
    m,
    N,
), "Measured responses must be a matrix with dimensions (number of observations x number of realisations)"


# %% [markdown]
# ## Checking coverage
#
# There's good coverage if there is overlap between observations and responses at sensor points.

# %%
def plot_responses(
    time_steps,
    observations,
    responses_ensemble,
    response_truth,
    responses_ensemble_post=None,
):
    x_levels = observations.index.get_level_values("x").to_list()
    y_levels = observations.index.get_level_values("y").to_list()

    obs_coordinates = set(zip(x_levels, y_levels))

    for x, y in obs_coordinates_from_index:
        fig, ax = plt.subplots()
        ax.set_title(f"Sensor readings at coordinate {x, y}")
        ax.set_ylabel("Temperature")
        ax.set_xlabel("Time step $k$")
        ax.grid()

        df_single_sensor = observations.query(f"x=={x} & y=={y}")

        y_sensor = df_single_sensor["value"]
        yerr_sensor = df_single_sensor["sd"]

        ax.errorbar(
            time_steps,
            y_sensor,
            yerr_sensor,
            ecolor="red",
            capsize=10,
            elinewidth=1,
            markeredgewidth=1,
        )

        ax.plot(
            time_steps,
            responses_ensemble.query(f"x=={x} & y=={y}"),
            color="gray",
            alpha=0.2,
            label="_nolegend_",
        )
        ax.plot([], [], "gray", label="Prior responses")

        ax.plot(
            time_steps, response_truth[time_steps, x, y], color="black", label="Truth"
        )

        if responses_ensemble_post is not None:
            ax.plot(
                time_steps,
                responses_ensemble_post.query(f"x=={x} & y=={y}"),
                color="orange",
                alpha=0.2,
            )
            ax.plot([], [], "orange", label="Posterior responses")

        ax.legend(loc="best")

        fig.tight_layout()


plot_responses(np.unique(k_levels), d, Y_df, u_t)

# %% [markdown]
# ## Deactivate sensors that measure the same temperature in all realizations
#
# This means that the temperature did not change at that sensor location.
# Including these will lead to numerical issues.

# %%
enough_ens_var_idx = Y.var(axis=1) > 1e-6

print(
    f"{list(enough_ens_var_idx).count(False)} measurements will be deactivated because of ensemble collapse"
)
Y = Y[enough_ens_var_idx, :]
D = D[enough_ens_var_idx, :]
Cdd = Cdd[enough_ens_var_idx, :]
Cdd = Cdd[:, enough_ens_var_idx]

# %% [markdown]
# ## Deactivate responses that are too far away from observations

# %%
ens_std = Y.std(axis=1)
ens_mean = Y.mean(axis=1)
obs_std = d.sd.values[enough_ens_var_idx]
obs_value = d.value.values[enough_ens_var_idx]
innov = obs_value - ens_mean

is_outlier = np.abs(innov) > 3.0 * (ens_std + obs_std)

print(
    f"{list(is_outlier).count(True)} out of {Y.shape[0]} measurements will be deactivated because they are outliers"
)
Y = Y[~is_outlier, :]
D = D[~is_outlier, :]
Cdd = Cdd[~is_outlier, :]
Cdd = Cdd[:, ~is_outlier]

# %% [markdown]
# ## Adaptive localization
#
# Localization with correlation used as distance.

# %%
Y_prime = Y - Y.mean(axis=1, keepdims=True)
C_YY = Y_prime @ Y_prime.T / (N - 1)
Sigma_Y = np.diag(np.sqrt(np.diag(C_YY)))
corr_trunc = 3 / np.sqrt(N)

A_ES_loc = []

for A_chunk in np.array_split(A, indices_or_sections=10):
    A_prime = A_chunk - A_chunk.mean(axis=1, keepdims=True)
    C_AA = A_prime @ A_prime.T / (N - 1)

    # State-measurement covariance matrix
    C_AY = A_prime @ Y_prime.T / (N - 1)
    Sigma_A = np.diag(np.sqrt(np.diag(C_AA)))

    # State-measurement correlation matrix
    c_AY = np.linalg.inv(Sigma_A) @ C_AY @ np.linalg.inv(Sigma_Y)

    _, corr_idx_Y = np.where(np.triu(np.abs(c_AY)) > corr_trunc)
    corr_idx_Y = np.unique(corr_idx_Y)

    Y_loc = Y[corr_idx_Y, :]
    D_loc = D[corr_idx_Y, :]
    Cdd_loc = Cdd[corr_idx_Y, :]
    Cdd_loc = Cdd_loc[:, corr_idx_Y]

    X_loc = analysis.ES(Y_loc, D_loc, Cdd_loc)
    A_ES_loc.append(A_chunk @ X_loc)

A_ES_loc = np.vstack(A_ES_loc)
A_ES_loc = A_ES_loc.clip(min=1e-8)

# %% [markdown]
# ## Perform ES update

# %%
X = analysis.ES(Y, D, Cdd)
A_ES = A @ X

# %%
# Sanity check as the results should be the same
# with and without localization when correlation truncation is set to zero.
if corr_trunc == 0.0:
    assert np.isclose(A_ES, A_ES_loc, atol=1e-5).all()

# %%
# The update may give non-physical parameter values, which here means negative heat conductivity.
# Setting negative values to a small positive value but not zero because we want to be able to divide by them.
A_ES = A_ES.clip(min=1e-8)

# %% [markdown]
# ## Testing the new iterative_ensemble_smoother package
#
# As part of ERT development, we wrote an efficient implementation of the iterative ensemble smoother.
# This package is available via pypi and you can easily test it out here if you wish.
#
# ```python
# A_ES_ert = ies.ensemble_smoother_update_step(
#     Y,
#     A,
#     obs_std[~is_outlier],
#     obs_value[~is_outlier],
#     inversion=ies.InversionType.EXACT,
# )
# ```

# %% [markdown]
# ## Numerical comparison of prior and posterior using RMSE
#
# The posterior calculated by ES is on average expected to be closer to the truth than the prior.
# By "closer", we mean in terms of Root Mean Squared Error (RMSE).
# The reason for this is that ES is based on the Kalman Filter, which is the "Best Linear Unbiased Estimator" (BLUE) and BLUE estimators have this property.
# However, this holds for certain only when the number of realizations tends to infinity.
# In practice this mean that we might end up with an increased RMSE when using a finite number of realizations.

# %%
err_posterior = alpha_t.ravel() - A_ES.mean(axis=1)
np.sqrt(np.mean(err_posterior * err_posterior))

# %%
err_posterior_loc = alpha_t.ravel() - A_ES_loc.mean(axis=1)
np.sqrt(np.mean(err_posterior_loc * err_posterior_loc))

# %%
err_prior = alpha_t.ravel() - A.mean(axis=1)
np.sqrt(np.mean(err_prior * err_prior))

# %% [markdown]
# ## IES

# %%
# Step length in Gauss Newton
gamma = 1.0

# Coefficient matrix as defined in Eq. 16 and Eq. 17.
W = np.zeros(shape=(N, N))

W = analysis.IES(Y, D, Cdd, W, gamma)
X_IES = np.identity(N) + W
A_IES = A @ X_IES
A_IES = A_IES.clip(min=1e-8)

# %%
err_posterior_ies = alpha_t.ravel() - A_IES.mean(axis=1)
np.sqrt(np.mean(err_posterior_ies * err_posterior_ies))

# %% [markdown]
# ## Graphical comparison of prior and posterior mean-fields

# %%
fig, ax = plt.subplots(nrows=1, ncols=4)
fig.set_size_inches(10, 10)

ax[0].set_title(f"Posterior dass")
ax[0].invert_yaxis()
ax[1].set_title(f"Posterior loc")
ax[1].invert_yaxis()
ax[2].set_title(f"Truth")
ax[2].invert_yaxis()
ax[3].set_title(f"Prior")
ax[3].invert_yaxis()

vmin = 0
vmax = np.max(alpha_t) + 0.1 * np.max(alpha_t)
p0 = ax[0].pcolormesh(A_ES.mean(axis=1).reshape(nx, nx).T, vmin=vmin, vmax=vmax)
p1 = ax[1].pcolormesh(A_ES_loc.mean(axis=1).reshape(nx, nx).T, vmin=vmin, vmax=vmax)
p2 = ax[2].pcolormesh(alpha_t.T, vmin=vmin, vmax=vmax)
p3 = ax[3].pcolormesh(A.mean(axis=1).reshape(nx, nx).T, vmin=vmin, vmax=vmax)

utils.colorbar(p0)
utils.colorbar(p1)
utils.colorbar(p2)
utils.colorbar(p3)

ax[0].set_aspect("equal", "box")
ax[1].set_aspect("equal", "box")
ax[2].set_aspect("equal", "box")
ax[3].set_aspect("equal", "box")

fig.tight_layout()

# %% [markdown]
# ## Plot standard deviations of fields to see which grid cells were updated the most

# %%
fig, ax = plt.subplots(nrows=1, ncols=3)
fig.set_size_inches(10, 10)

ax[0].set_title(f"ES")
ax[0].invert_yaxis()
ax[1].set_title(f"ES loc")
ax[1].invert_yaxis()
ax[2].set_title(f"Prior")
ax[2].invert_yaxis()

vmin = A.std(axis=1).min() - 0.1 * A.std(axis=1).min()
vmax = A.std(axis=1).max() + 0.1 * A.std(axis=1).max()
p0 = ax[0].pcolormesh(A_ES.std(axis=1).reshape(nx, nx).T, vmin=vmin, vmax=vmax)
p1 = ax[1].pcolormesh(A_ES_loc.std(axis=1).reshape(nx, nx).T, vmin=vmin, vmax=vmax)
p2 = ax[2].pcolormesh(A.std(axis=1).reshape(nx, nx).T, vmin=vmin, vmax=vmax)

utils.colorbar(p0)
utils.colorbar(p1)
utils.colorbar(p2)

ax[0].set_aspect("equal", "box")
ax[1].set_aspect("equal", "box")
ax[2].set_aspect("equal", "box")

fig.tight_layout()

# %% [markdown]
# ## Investigate quality of history match

# %%
alphas_post = []
for realization in range(A_ES.shape[1]):
    alphas_post.append(A_ES[:, realization].reshape(nx, nx))

fwd_runs = p_map(
    pde.heat_equation,
    [u_init] * N,
    alphas_post,
    [dx] * N,
    [dt] * N,
    [k_start] * N,
    [k_end] * N,
    streams,
    [scale] * N,
    desc=f"Running forward model.",
)

Y_df_post = pd.DataFrame({"k": k_levels, "x": x_levels, "y": y_levels})

for real, fwd_run in enumerate(fwd_runs):
    Y_df_post = Y_df_post.assign(**{f"R{real}": fwd_run[k_levels, x_levels, y_levels]})

Y_df_post = Y_df_post.set_index(["k", "x", "y"], verify_integrity=True)

plot_responses(np.unique(k_levels), d, Y_df, u_t, Y_df_post)

# %% [markdown]
# ## Check that single iteration of IES with step length 1.0 is the same as ES.

# %%
assert np.isclose(X_IES, X, atol=1e-5).all()

# %%
