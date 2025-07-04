# microcluster-token-distributor

More information: https://charmhub.io/microcluster-token-distributor

This is a operator charm for management and token distribution for microcluster charms, such as MicroOVN.

This exists to avoid using the peer relation for sharing things like this due to its quadratic scaling properties which make it not suitable for large scale deployments, as it is designed with smaller scale applications in mind.

## Deployment

An example deployment looks something like this:

```
juju deploy microovn -n 3
juju deploy microcluster-token-distributor
juju relate microovn microcluster-token-distributor
```

This should give you a small MicroOVN (as an example microcluster charm) deployment, and token distributor should facilitate the cluster setup and join process.

## Internals

Microcluster-token-distributor acts as a mirror for important information such as hostnames and join tokens. If a given unit has "mirror"=up in their unit databag, microcluster-token-distributor will mirror anything else in the databag so long as it is of the form "mirror-<key>" = value. It will not overwrite anything and if it has the key in its databag it will only replace the value if the value is "empty". Microcluster-token-distributor will also automatically add "mirror-<hostname>"="empty" to its databag for any units exposing their hostname.

The unit leader handles the mirror on the token-distributor side, and can handle total unit loss with no information lost due to the lack of stored state. On the microcluster charm side (eg MicroOVN) the voter unit with the first name alphabetically manages its side of the mirror and is referred to as the "communicator node". We do this to avoid any split brain issues that might occur if we instead just used the unit leader.

## Other resources

- [Contributing](CONTRIBUTING.md) <!-- or link to other contribution documentation -->

- See the [Juju SDK documentation](https://juju.is/docs/sdk) for more information about developing and improving charms.
