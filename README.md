# Docker registry git driver

This is a [docker-registry backend driver][registry-core] which stores images 
in a git repository.

[![PyPI version][pypi-image]][pypi-url]
## Usage



```
pip install docker-registry-driver-git
```

Then edit your docker-registry configuration so that `storage` reads `gitdriver`.


## Options

You may add any of the following to your main docker-registry configuration to further configure it:

```yaml
storage: gitdriver
storage_path: /gitrepopath

```
[pypi-url]: https://pypi.python.org/pypi/docker-registry-driver-git
[pypi-image]: https://badge.fury.io/py/docker-registry-driver-git.svg
