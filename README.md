# Docker registry git driver

This is a [docker-registry backend driver][registry] which stores images 
in a git repository.

[![PyPI version][pypi-image]][pypi-url]
## Usage

```
docker run -d -p 5000:5000 -e LOGLEVEL=debug --name reg pyotr777/registry
```

## Alternative usage

Build registry image with Dockerfile

```
$ wget https://raw.githubusercontent.com/pyotr777/docker-registry-driver-git/master/Dockerfile
$ docker build --rm -t <image name> .
$ docker run -d -p 5000:5000 -e LOGLEVEL=debug --name reg <image name>
```

`<image name>` format is `your name/image name`, for example: `peter/registry`.

### Options

| option name | description |
|-----|-----|
|--name | can be anything |
|LOGLEVEL | can be debug, info, warn, error or critical |
| STORAGE_PATH | Path to git repository where images are stored. Set it with `-e STORAGE_PATH=/some/path` |
| SETTINGS_FLAVOR | Change storage backend driver. Default is "dev" which will use gitdriver. For details of switching drivers see here: http://github.com/docker/docker-registry#configuration-flavors . |

[pypi-url]: https://pypi.python.org/pypi/docker-registry-driver-git
[pypi-image]: https://badge.fury.io/py/docker-registry-driver-git.svg
[registry]: https://github.com/docker/docker-registry
