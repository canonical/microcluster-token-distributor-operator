# Contributing to microcluster-token-distributor-operator

Welcome future and current contributors. If you are reading this you are looking for
how to make a contribution to the microcluster-token-distributor-operator. This guide
will take you through the process of making contributions to this repository. The
purpose of this guide is to help set up your development environment and understand
the contribution process.

## Development environment

This project uses a few tools necessary to build and maintain the project. To get
started run the following commands:

```bash
sudo snapcraft install charmcraft --classic
sudo snapcraft install astral-uv --classic
```

The above commands will ensure that you have have the charmcraft tool for building
charms and the uv tool for managing python virtual environments and dependences.

If you haven't already done so, clone this repository.

```bash
git clone https://github.com/canonical/microcluster-token-distributor-operator
```

Once the repository is cloned locally, install the `tox-uv` plugin for your tox
environment. This will setup tox so that it will use the `uv.lock` files when creating
the virtual environment and running tests.

```bash
uv tool install tox --with tox-uv
```

The above command has installed tox into your local path's virtual environment. Confirm
this is the case by checking the tox version. 

```bash
tox --version
```

You should see output similar to the output below:

```
4.26.0 from /home/ubuntu/.local/share/uv/tools/tox/lib/python3.12/site-packages/tox/__init__.py
registered plugins:
    tox-uv-1.26.0 at /home/ubuntu/.local/share/uv/tools/tox/lib/python3.12/site-packages/tox_uv/plugin.py with uv==0.7.13
```

> [!NOTE]
> Many IDEs have plugins that support uv. You may find it useful for setting up the virtual environment
> in your IDE to use the uv plugin.
>
> If you want to manage your own virtual environment, you can do this with the `uv sync --all-extras`
> command. See the [uv documentation](https://docs.astral.sh/uv/) for more details on using uv.

## Running tests using tox

The tox file defines that the tox environments are built using the packages defined in the
`uv.lock` file. There are several targets available to run, most of which will be run on any
pull request.

To see a list of tox environments available to run, use the `tox -l` command.

Run the targets using the `tox -e {environment}` to run the target. For example:

```bash
tox -e lint
```

## Setting up Juju

[Juju](https://juju.is/) is relatively easy to set up and install for local development
purposes. The [tutorial](https://documentation.ubuntu.com/juju/3.6/tutorial/) has more details
on how to setup a simple environment.

For the sake of this example, we'll use the local LXD provider for Juju. If you have not
initialized LXD on your local system do so by running the following:

```bash
lxd init --auto
```

If you don't know whether LXD has been initialized or not, you can run the following command:

```bash
lxc profile show default
```

When LXD is initialized, the profile will contain information regarding the networking
and the storage. It should look something like:

```
name: default
description: Default LXD profile
config: {}
devices:
  eth0:
    name: eth0
    network: lxdbr0
    type: nic
  root:
    path: /
    pool: default
    type: disk
used_by: {}
project: default
```

Next, install juju by running the following:

```bash
sudo snap install juju --channel 3/stable
```

Note that we're specifying the channel of 3/stable. The current development is on the
latest Juju 3.x stable release.

Once Juju is installed, you can bootstrap a controller on top of the LXD cluster
by running:

```bash
juju bootstrap localhost localhost
```

After the bootstrap step is complete, test it out by deploying the Ubuntu charmed
operator, a simple charm that provides an Ubuntu image.

```bash
juju add-model testy-mctest-test
juju deploy --base ubuntu@24.04 ubuntu
```

It may take a couple of minutes for the first instance to launch, particularly if the
matching container image has not been pulled down to the local machine.

Look for the status of the application by running `juju status`. When finished deploying
the juju status should look similar to:

```
Model              Controller           Cloud/Region         Version  SLA          Timestamp
testy-mctest-test  localhost-localhost  localhost/localhost  3.4.5    unsupported  19:15:35-07:00

App     Version  Status  Scale  Charm   Channel        Rev  Exposed  Message
ubuntu  24.04    active      1  ubuntu  latest/stable   26  no       

Unit       Workload  Agent  Machine  Public address  Ports  Message
ubuntu/0*  active    idle   0        10.167.81.182          

Machine  State    Address        Inst id        Base          AZ  Message
0        started  10.167.81.182  juju-8f4f01-0  ubuntu@24.04      Running
```

Once you see the above, the development environment is ready for deploying new
operators. The ubuntu application is no longer necessary and can be removed by:

```bash
juju remove-application ubuntu
```

## Building the operator

To build the microcluster-token-distributor charmed operator, use the `charmcraft
pack` command in project root directory (the same location as the charmcraft.yaml).

When finished building successfully, you should see the following output:

```
Packed microcluster-token-distributor_amd64.charm
```

## Testing the locally packed charm

To deploy the locally packed charm, run the following command:

```bash
juju deploy --base ubuntu@24.04 ./microcluster-token-distributor_amd64.charm
```

If you've made some local changes and wish to deploy the updated changes to an existing
environment, simply use the `juju refresh` command:

```bash
juju refresh --path ./microcluster-token-distributor_amd64.charm microcluster-token-distributor
```

