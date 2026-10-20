# LED Matrix Controller

[![CodSpeed Badge](https://img.shields.io/endpoint?url=https://codspeed.io/badge.json)](https://codspeed.io/worgarside/led-matrix-controller)

This service is intended to be run on a Raspberry Pi and receives messages from a MQTT broker to control an LED matrix. I currently control my matrix from [Home Assistant](https://github.com/worgarside/home-assistant).

## Deployment

Published stable releases deploy to `pi@10.0.0.51` from the shared CC runner through the [LAN deployment SSH action](https://github.com/worganisation/github-config-files/tree/0b7ce9549e48edc9a4057ef9bd46acea5d2a6850/actions/lan-ssh). The `production-deploy` environment requires the `DEPLOY_SSH_PRIVATE_KEY` secret and `DEPLOY_SSH_KNOWN_HOSTS` variable containing the independently verified host key for `10.0.0.51`. The matching public key must be authorized for `pi`, and the runner firewall must allow SSH to that address.

The Pi checkout is `/home/pi/led-matrix-controller`, with its `.env` file, `uv`, GNU Make, a C++ compiler, Python 3.11 development headers, and Cython available. The deployment user needs non-interactive sudo access to install the systemd units, reload systemd, and restart the matrix and installed audio processor services.

The workflow fetches and runs `scripts/deploy-release.sh` from the selected release tag, so the deployment entrypoint is available even when the Pi has an older checkout. The same operation is available locally as `make deploy TAG=<tag>`. This rejects dirty checkouts and tags outside `origin/main` or without the deployment entrypoint, checks out the release in detached HEAD, installs locked runtime dependencies and the pinned native matrix bindings, installs systemd units, and restarts the matrix plus the audio processor when its unit is installed. Untracked submodule build outputs are preserved and do not block deployment; tracked submodule changes still block it. Runtime dependency sync preserves the separately installed native bindings. Each restarted service must keep the same process alive for ten seconds.

To redeploy a published stable release containing the deployment script, run **Actions → Deploy MtrxPi Release → Run workflow** from `main` and enter its tag. Deployments to mtrxpi are serialized, and prereleases are excluded. A failed installation or health check fails the deployment; inspect the job output and service journal before retrying.

## Development

Use Python 3.11 and install the locked dependencies with `uv sync --locked`. PyAudio needs PortAudio development headers (`portaudio19-dev` on Debian). The Python and NumPy versions match the Pi deployment; dependency upgrades must retain compatibility with its native matrix bindings.

`make run` starts the controller on the Pi. `make vscode-shortcut-1` starts the controller with the desktop matrix emulator; both use `led_matrix_controller/main.py`. The `rain` target is an alias for `run`, and content selection comes from MQTT.

Unit tests and CodSpeed benchmarks have separate repository-owned workflows. Both install native dependencies in a Python 3.11 container. Unit tests exclude benchmarks; CodSpeed runs only `tests/benchmark`, without coverage or parallel test workers.

Home Assistant discovers the controller’s numeric, enum, boolean and text content settings through retained MQTT configurations under `homeassistant/`. The controller publishes these on broker connection and reconnection, and when Home Assistant announces `online` on `homeassistant/status`. Settings share the MtrxPi device and use stable `mtrxpi_<content>_<setting>` unique IDs and default entity IDs. Their command and state topics retain the setting values; discovery publishes only configuration, so connecting does not replace saved values with startup defaults. Home Assistant’s MQTT integration must have discovery enabled with its default prefix and birth topic.

## Content

All content has the following parameters:

### Clock

Literally just a clock.

| ![Clock](./readme/clock.gif) |
|-----------------------------|
| *The clock, with a demonstration of the position/scale parameters being modified* |

#### Parameters

| Name | Description |
|------|-------------|
| `scale` | Scale of the clock, can only be 1 or 2 |
| `x_pos` | X position of the content |
| `y_pos` | Y position of the content |

### Raining Grid

A cellular automata that simulates the current rainfall. My Home Assistant instance sends messages to the Pi via MQTT to update the rain chance parameter.

It can also display a plant growth simulation, where the plants grow according to a Home Assistant-controlled configuration and decay back to nothing when the rain drops below a given threshold.

| ![Raining Grid](./readme/raining-grid.gif) |
|--------------------------------------------|
| *The raining grid simulation (in real time)* |

| ![Raining Grid with Plants](./readme/raining-grid-plants.gif) |
|--------------------------------------------|
| *The raining grid simulation with plants (in 8x speed)* |

#### Parameters

| Name | Description |
|------|-------------|
| `rain_chance` | The chance of rain, between 0 and 100 |
| `rain_speed` | The time period between rain cells, in ticks |
| `splash_speed` | The time period between rain cells, in ticks |
| `plant_limit` | The maximum number of plants on the grid |
| `plant_growth_chance` | The chance of a plant growing when rain hits the bottom/the end of a plant, between 0 and 100 |
| `distance_between_plants` | The distance between plants, in cells |
| `plant_decay_propagation_speed` | The speed at which a plant decays, in ticks |
| `leaf_growth_chance` | The chance of a leaf growing in a valid location on any given tick, between 0 and 100 |


### Sorting Algorithms

A visualisation of a number of sorting algorithms.

| ![Sorting Algorithms](./readme/sorting-algorithms.gif) |
|-------------------------------------------------------|
| *A random selection of the sorting algorithms* |

#### Parameters

| Name | Description |
|------|-------------|
| `algorithm` | The algorithm to use |
| `completion_display_time` | The time to display the sorted array for, in seconds |
| `iterations` | The number of iterations to run the sorting algorithm for before expiring the content |
| `randomize_algorithm` | Whether to randomize the algorithm on each iteration |
